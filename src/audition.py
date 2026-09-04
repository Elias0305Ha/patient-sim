"""Record a short sample of each candidate voice, so we can pick one by ear.

    python src/audition.py scenarios/schedule-basic.yaml ash cedar ballad verse

Writes results/auditions/<voice>.wav. Each sample uses the real scenario
persona, so what you hear is the delivery we would actually ship, not a neutral
read of some unrelated sentence.

Costs a few seconds of Realtime audio per voice and places no phone call.

One caveat: samples are 24kHz PCM, not the 8kHz mu-law of a real call. The
phone line band-limits every voice equally, so comparing them here is still
valid -- but a voice will sound better here than it does on the call.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import sys
import wave
from pathlib import Path

import websockets

from bridge import REALTIME_URL, realtime_headers
from prompt import build_session_update, load_scenario

log = logging.getLogger("audition")

AUDITION_DIR = Path(__file__).resolve().parent.parent / "results" / "auditions"

SAMPLE_RATE = 24_000

# What the sample says. Open-ended on purpose: we want to hear the model's own
# phrasing and hesitation under the persona, not a sentence we wrote for it.
CUE = (
    "The practice has just answered the phone and asked how they can help. "
    "Say your opening two sentences, out loud, exactly as you would on the call."
)


async def audition(scenario_path: str, voice: str) -> Path:
    scenario = load_scenario(scenario_path)

    session = build_session_update(scenario)
    session["session"]["audio"]["output"]["voice"] = voice
    # The cue is appended to the session instructions rather than passed on
    # response.create: response-level instructions REPLACE the session ones, so
    # doing it that way silently threw the whole persona away and auditioned a
    # generic assistant instead of our patient.
    session["session"]["instructions"] += f"\n\nRIGHT NOW\n- {CUE}"
    # Plain PCM so the sample can be written straight to a WAV file.
    session["session"]["audio"]["output"]["format"] = {
        "type": "audio/pcm",
        "rate": SAMPLE_RATE,
    }
    # Nothing is speaking to us, so turn detection has no job here.
    session["session"]["audio"]["input"].pop("turn_detection", None)

    chunks: list[bytes] = []
    said = ""

    async with websockets.connect(
        REALTIME_URL, additional_headers=realtime_headers()
    ) as ws:
        await ws.send(json.dumps(session))
        await ws.send(json.dumps({"type": "response.create"}))

        async for raw in ws:
            event = json.loads(raw)
            kind = event.get("type")

            if kind == "response.output_audio.delta":
                chunks.append(base64.b64decode(event["delta"]))
            elif kind == "response.output_audio_transcript.done":
                said = event.get("transcript", "").strip()
            elif kind == "error":
                raise RuntimeError(json.dumps(event.get("error", event)))
            elif kind == "response.done":
                break

    AUDITION_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDITION_DIR / f"{voice}.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(b"".join(chunks))

    log.info('%-8s -> %s', voice, path.name)
    log.info('%-8s    "%s"', "", said)
    return path


async def run(scenario_path: str, voices: list[str]) -> int:
    for voice in voices:
        try:
            await audition(scenario_path, voice)
        except Exception as exc:
            log.error("%-8s failed: %s", voice, exc)
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Sample candidate voices.")
    parser.add_argument("scenario")
    parser.add_argument("voices", nargs="+", help="voice names to try")
    args = parser.parse_args()
    return asyncio.run(run(args.scenario, args.voices))


if __name__ == "__main__":
    raise SystemExit(main())
