"""Place one call to the assessment line and bring back the evidence.

    python src/caller.py scenarios/schedule-basic.yaml

Runs the bridge websocket server in-process, asks Twilio to dial out and stream
the call's audio to it, waits for the call to finish, then downloads Twilio's
dual-channel recording as MP3.

Safety: the destination is read from TARGET_NUMBER and asserted against the one
number this project is allowed to dial. It is never taken from an argument.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from twilio.rest import Client

from bridge import serve
from prompt import load_scenario

load_dotenv()

log = logging.getLogger("caller")

# The only number this project may ever dial. Asserted before every call.
ALLOWED_TARGET = "+18054398008"

# Twilio hangs the call up itself at this point, so a wedged call cannot run
# unattended. The brief asks for 1-3 minute calls; this is headroom, not a budget.
MAX_CALL_SECONDS = 240

ROOT = Path(__file__).resolve().parent.parent
RECORDING_DIR = ROOT / "results" / "recordings"
TRANSCRIPT_DIR = ROOT / "results" / "transcripts"


def require_env(*names: str) -> dict[str, str]:
    values = {name: os.environ.get(name, "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise SystemExit(
            f"Missing in .env: {', '.join(missing)}\n"
            "Copy .env.example to .env and fill it in."
        )
    return values


def check_target(number: str) -> str:
    if number != ALLOWED_TARGET:
        raise SystemExit(
            f"REFUSING TO DIAL {number}.\n"
            f"This project only ever calls the assessment line {ALLOWED_TARGET}.\n"
            "Fix TARGET_NUMBER in .env."
        )
    return number


def build_twiml(wss_base: str) -> str:
    """TwiML that hands the call's audio to our bridge.

    <Connect> is bidirectional. <Start> only streams audio to us, which would
    give a bot that can hear the agent but never speak to it.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Connect><Stream url="{wss_base.rstrip("/")}/" /></Connect>'
        "</Response>"
    )


def place_call(client: Client, twiml: str, to: str, from_: str):
    return client.calls.create(
        to=to,
        from_=from_,
        twiml=twiml,
        # Dual channel puts the agent and our bot on separate tracks, which
        # makes overlaps audible when reviewing.
        record=True,
        recording_channels="dual",
        time_limit=MAX_CALL_SECONDS,
    )


def wait_for_completion(client: Client, call_sid: str) -> str:
    """Poll until Twilio reports the call is over, and return the final status."""
    terminal = {"completed", "busy", "failed", "no-answer", "canceled"}
    deadline = time.monotonic() + MAX_CALL_SECONDS + 60

    while time.monotonic() < deadline:
        status = client.calls(call_sid).fetch().status
        if status in terminal:
            return status
        time.sleep(3)
    return "timed-out"


def next_index() -> int:
    """Number the recording to match the transcript the bridge just wrote."""
    return max(len(list(TRANSCRIPT_DIR.glob("transcript-*.txt"))), 1)


def download_recording(client: Client, call_sid: str, account_sid: str,
                       auth_token: str, index: int) -> Path | None:
    """Fetch the call recording as MP3. The brief requires MP3 or OGG."""
    for attempt in range(10):
        recordings = client.recordings.list(call_sid=call_sid, limit=1)
        if recordings:
            recording = recordings[0]
            url = (
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"
                f"/Recordings/{recording.sid}.mp3"
            )
            response = requests.get(url, auth=(account_sid, auth_token), timeout=60)
            response.raise_for_status()

            RECORDING_DIR.mkdir(parents=True, exist_ok=True)
            path = RECORDING_DIR / f"{index:02d}.mp3"
            path.write_bytes(response.content)
            return path

        log.info("recording not ready yet (attempt %d/10)", attempt + 1)
        time.sleep(5)

    log.warning("no recording appeared for %s", call_sid)
    return None


async def run(scenario_path: str) -> int:
    env = require_env(
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
        "TARGET_NUMBER",
        "PUBLIC_WSS_BASE",
    )
    target = check_target(env["TARGET_NUMBER"])
    scenario = load_scenario(scenario_path)
    port = int(os.environ.get("WS_PORT", "8080"))

    # Start the bridge before dialling; Twilio connects within a second of answer.
    server = asyncio.create_task(serve(scenario_path, port))
    await asyncio.sleep(1)

    client = Client(env["TWILIO_ACCOUNT_SID"], env["TWILIO_AUTH_TOKEN"])
    log.info("scenario %s: dialling %s from %s",
             scenario["id"], target, env["TWILIO_FROM_NUMBER"])

    call = place_call(
        client, build_twiml(env["PUBLIC_WSS_BASE"]), target, env["TWILIO_FROM_NUMBER"]
    )
    log.info("call %s placed; waiting for it to finish", call.sid)

    status = await asyncio.to_thread(wait_for_completion, client, call.sid)
    log.info("call ended with status: %s", status)

    server.cancel()

    if status != "completed":
        log.error("call did not complete; no recording to fetch")
        return 1

    path = await asyncio.to_thread(
        download_recording, client, call.sid, env["TWILIO_ACCOUNT_SID"],
        env["TWILIO_AUTH_TOKEN"], next_index(),
    )
    if path:
        log.info("recording saved: %s", path)
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Place one test call.")
    parser.add_argument("scenario")
    args = parser.parse_args()
    return asyncio.run(run(args.scenario))


if __name__ == "__main__":
    raise SystemExit(main())
