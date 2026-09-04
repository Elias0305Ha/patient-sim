"""Relay audio between a Twilio Media Stream and the OpenAI Realtime API.

The bridge is deliberately dumb. It copies base64 mu-law frames in both
directions, records what each side said, and clears Twilio's playback buffer
when the other party starts talking. Every decision about *what* to say lives in
the scenario prompt; every judgement about whether the call was any good happens
after the call. If this file starts reasoning about the conversation, something
has gone wrong.

Two modes:

    python src/bridge.py --selftest scenarios/schedule-basic.yaml
        Connect to Realtime only. Proves the websocket URL, the API key and the
        session schema without placing a phone call.

    python src/bridge.py --serve scenarios/schedule-basic.yaml
        Run the websocket server Twilio connects to. Normally started for you
        by caller.py.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import websockets
from dotenv import load_dotenv

from prompt import MODEL, build_session_update, load_scenario

load_dotenv()

log = logging.getLogger("bridge")

REALTIME_URL = f"wss://api.openai.com/v1/realtime?model={MODEL}"

# Realtime server events we act on. Everything else is logged and ignored.
AUDIO_DELTA = "response.output_audio.delta"
SPEECH_STARTED = "input_audio_buffer.speech_started"
AGENT_TRANSCRIPT = "conversation.item.input_audio_transcription.completed"
BOT_TRANSCRIPT = "response.output_audio_transcript.done"

TRANSCRIPT_DIR = Path(__file__).resolve().parent.parent / "results" / "transcripts"


def realtime_headers() -> dict[str, str]:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set; check your .env")
    # No OpenAI-Beta header: that is the beta interface, and GA rejects it.
    return {"Authorization": f"Bearer {key}"}


def _mmss(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


class CallRecord:
    """The transcript of one call, timestamped from the moment audio started."""

    def __init__(self, scenario_id: str) -> None:
        self.scenario_id = scenario_id
        self.started = time.monotonic()
        self.lines: list[tuple[float, str, str]] = []

    def add(self, speaker: str, text: str, started_at: float | None = None) -> None:
        """Record one utterance, timed from when it was *spoken*.

        Transcripts arrive when transcription finishes, not when the person
        began talking, and a long turn can finish transcribing after the reply
        it provoked. Stamping on arrival puts answers before their questions,
        which would make every timestamp in the bug report wrong.
        """
        elapsed = (started_at or time.monotonic()) - self.started
        self.lines.append((elapsed, speaker, text))
        log.info("[%s] %s: %s", _mmss(elapsed), speaker, text)

    def write(self, call_sid: str | None = None) -> Path | None:
        """Save the transcript, unless nobody said anything.

        Any websocket probe reaching this port opens a call record. Without this
        guard those write empty transcripts that then throw off call numbering.
        """
        if not self.lines:
            log.info("nothing was said; no transcript written")
            return None

        TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        existing = len(list(TRANSCRIPT_DIR.glob("transcript-*.txt")))
        path = TRANSCRIPT_DIR / f"transcript-{existing + 1:02d}.txt"

        header = [f"scenario: {self.scenario_id}"]
        if call_sid:
            header.append(f"call_sid: {call_sid}")
        header.append("")

        body = [
            f"[{_mmss(t)}] {who}: {text}"
            for t, who, text in sorted(self.lines, key=lambda line: line[0])
        ]
        path.write_text("\n".join(header + body) + "\n", encoding="utf-8")
        return path


async def selftest(scenario_path: str) -> int:
    """Connect to Realtime, apply the session config, report what came back.

    Places no call and costs nothing. Run after any change to the session
    schema: a rejected config would otherwise surface as a phone call that
    connects and then sits in silence.
    """
    scenario = load_scenario(scenario_path)

    log.info("connecting to %s", REALTIME_URL)
    async with websockets.connect(
        REALTIME_URL, additional_headers=realtime_headers()
    ) as ws:
        log.info("connected; sending session.update")
        await ws.send(json.dumps(build_session_update(scenario)))

        deadline = time.monotonic() + 10
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log.error("SELFTEST FAILED: no session.updated within 10s")
                return 1
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                log.error("SELFTEST FAILED: no session.updated within 10s")
                return 1

            event = json.loads(raw)
            kind = event.get("type")

            if kind == "error":
                log.error(
                    "REJECTED: %s", json.dumps(event.get("error", event), indent=2)
                )
                return 1
            if kind == "session.created":
                log.info("session.created -- URL and API key are good")
            elif kind == "session.updated":
                audio = event.get("session", {}).get("audio", {})
                log.info("session.updated -- server accepted this audio config:")
                log.info("%s", json.dumps(audio, indent=2))
                log.info("SELFTEST PASSED")
                return 0


async def _twilio_to_openai(twilio_ws, openai_ws, state: dict[str, Any]) -> None:
    """Forward caller audio into Realtime. Payloads cross over untouched."""
    async for raw in twilio_ws:
        msg = json.loads(raw)
        event = msg.get("event")

        if event == "media":
            await openai_ws.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": msg["media"]["payload"],
                    }
                )
            )
        elif event == "start":
            state["stream_sid"] = msg["start"]["streamSid"]
            state["call_sid"] = msg["start"].get("callSid")
            log.info("stream start: %s", state["stream_sid"])
        elif event == "connected":
            log.info("twilio connected")
        elif event == "stop":
            log.info("stream stop")
            return


async def _openai_to_twilio(openai_ws, twilio_ws, state: dict[str, Any]) -> None:
    """Forward model audio out to the call, and record both sides."""
    record: CallRecord = state["record"]

    async for raw in openai_ws:
        event = json.loads(raw)
        kind = event.get("type")

        if kind == AUDIO_DELTA:
            # First delta of a reply is the moment our patient starts speaking.
            state.setdefault("bot_started", time.monotonic())
            await _send_twilio(
                twilio_ws,
                state,
                {"event": "media", "media": {"payload": event["delta"]}},
            )
        elif kind == SPEECH_STARTED:
            # The agent started talking. Twilio may already hold seconds of our
            # audio; without this clear we talk straight over them.
            state["agent_started"] = time.monotonic()
            if await _send_twilio(twilio_ws, state, {"event": "clear"}):
                log.info("barge-in: cleared twilio buffer")
        elif kind == AGENT_TRANSCRIPT:
            record.add(
                "AGENT",
                (event.get("transcript") or "").strip(),
                state.pop("agent_started", None),
            )
        elif kind == BOT_TRANSCRIPT:
            record.add(
                "PATIENT",
                (event.get("transcript") or "").strip(),
                state.pop("bot_started", None),
            )
        elif kind == "error":
            log.error("realtime error: %s", json.dumps(event.get("error", event)))


async def _send_twilio(twilio_ws, state: dict[str, Any], message: dict) -> bool:
    """Send a message to Twilio, stamped with the stream it belongs to.

    Anything sent before the `start` event has nowhere to go, so it is dropped.
    """
    stream_sid = state.get("stream_sid")
    if not stream_sid:
        return False
    await twilio_ws.send(json.dumps({**message, "streamSid": stream_sid}))
    return True


async def handle_call(twilio_ws, scenario: dict[str, Any]) -> None:
    """One phone call: open Realtime, configure it, pump until either side ends."""
    state: dict[str, Any] = {"record": CallRecord(scenario["id"])}

    async with websockets.connect(
        REALTIME_URL, additional_headers=realtime_headers()
    ) as openai_ws:
        await openai_ws.send(json.dumps(build_session_update(scenario)))
        log.info("realtime session configured")

        pump = [
            asyncio.create_task(_twilio_to_openai(twilio_ws, openai_ws, state)),
            asyncio.create_task(_openai_to_twilio(openai_ws, twilio_ws, state)),
        ]
        try:
            done, pending = await asyncio.wait(
                pump, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in done:
                if task.exception() is not None:
                    raise task.exception()
        finally:
            path = state["record"].write(state.get("call_sid"))
            if path:
                log.info("transcript written: %s", path)


async def serve(scenario_path: str, port: int) -> None:
    scenario = load_scenario(scenario_path)

    async def handler(twilio_ws):
        log.info("incoming twilio connection")
        try:
            await handle_call(twilio_ws, scenario)
        except Exception:
            log.exception("call failed")

    async with websockets.serve(handler, "0.0.0.0", port):
        log.info("bridge listening on port %d for scenario %s", port, scenario["id"])
        await asyncio.Future()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Twilio <-> Realtime audio bridge")
    parser.add_argument("scenario")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--selftest", action="store_true", help="check Realtime only")
    mode.add_argument("--serve", action="store_true", help="run the Twilio server")
    args = parser.parse_args()

    if args.selftest:
        return asyncio.run(selftest(args.scenario))
    asyncio.run(serve(args.scenario, int(os.environ.get("WS_PORT", "8080"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
