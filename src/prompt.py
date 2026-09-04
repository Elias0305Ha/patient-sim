"""Turn a scenario YAML file into an OpenAI Realtime `session.update` payload.

Pure functions only: no network, no globals, no side effects. Run this module
directly to dump the payload for a scenario and eyeball it before burning a call:

    python src/prompt.py scenarios/schedule-basic.yaml

Audio is G.711 mu-law 8kHz in both directions so the bridge never converts a
sample. On the GA Realtime interface that format is expressed as the nested
object {"type": "audio/pcmu"} -- not the beta's flat "g711_ulaw" string.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

MODEL = "gpt-realtime-2.1"

# G.711 mu-law, 8kHz, mono. Same object for input and output; see module docstring.
MULAW_FORMAT = {"type": "audio/pcmu"}

# Keys a scenario file must define. Everything else is optional.
REQUIRED_KEYS = ("id", "goal", "patient")


def _text(value: Any) -> str:
    """Collapse a YAML folded scalar into one clean line.

    `>` blocks keep a trailing newline and wrap at the source line width, which
    would otherwise show up as stray breaks mid-sentence in the prompt.
    """
    return " ".join(str(value).split())


def load_scenario(path: str | Path) -> dict[str, Any]:
    """Read a scenario YAML file and fail loudly if it is missing required keys."""
    scenario = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(scenario, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level")

    missing = [key for key in REQUIRED_KEYS if key not in scenario]
    if missing:
        raise ValueError(f"{path}: missing required key(s): {', '.join(missing)}")
    return scenario


def build_instructions(scenario: dict[str, Any]) -> str:
    """Compose the system prompt that makes the bot behave like a real patient.

    Four things this has to get right, because they are what the call is graded
    on: stay in character, steer toward the goal instead of waiting to be asked,
    speak in short natural turns, and end the call once the goal resolves.
    """
    patient = scenario["patient"]
    lines: list[str] = [
        "You are a patient calling a medical practice on the telephone. You are "
        "a real person with a real problem, not an assistant and not a test "
        "script. Never mention that you are an AI, never break character, and "
        "never refer to prompts, scenarios, or testing.",
        "",
        "WHO YOU ARE",
        f"- Your name is {patient['name']}.",
    ]

    if patient.get("dob"):
        lines.append(
            f"- Your date of birth is {patient['dob']}. Give it when asked to "
            "verify your identity."
        )
    if patient.get("phone"):
        lines.append(f"- Your phone number is {patient['phone']}.")
    for detail in patient.get("details", []):
        lines.append(f"- {_text(detail)}")

    lines += [
        "",
        "WHY YOU ARE CALLING",
        f"- {_text(scenario['goal'])}",
    ]

    if scenario.get("must_cover"):
        lines.append(
            "- Before the call ends, make sure you have raised each of these, "
            "working them in naturally rather than reading them as a list:"
        )
        lines += [f"    * {_text(item)}" for item in scenario["must_cover"]]

    lines += [
        "",
        "HOW YOU TALK",
        "- One or two sentences per turn. This is a phone call, not a monologue.",
        "- Plain spoken English. Contractions, small hesitations, occasional "
        "'um' or 'sorry, one sec'. Do not sound polished or scripted.",
        "- Never read out bullet points, headings, or anything list-shaped.",
    ]

    # Every scenario waits its turn except the one whose whole point is barging
    # in. Without this the global rule and that scenario contradict each other.
    if scenario.get("barge_in"):
        lines.append(
            "- Do not wait for them to finish. Cut in when you have heard "
            "enough, the way an impatient caller does. Stay polite about it."
        )
    else:
        lines.append(
            "- Let the other person finish. If you do talk over them, "
            "apologise briefly and let them go first."
        )

    lines += [
        "- If you are asked something you were not given an answer for, improvise "
        "something an ordinary patient would plausibly say. Stay consistent with "
        "anything you have already said on this call.",
        "",
        "DRIVING THE CALL",
        "- You called them, so you open the conversation once they greet you.",
        "- Keep steering back to why you called. If the answer is vague, ask a "
        "direct follow-up. If they change the subject, come back to your goal.",
        "- Push for a specific outcome: an actual date and time, an actual "
        "confirmation, an actual answer. Do not accept 'someone will call you "
        "back' without first asking when and who.",
    ]

    if scenario.get("style"):
        lines += ["", "YOUR MOOD RIGHT NOW", f"- {_text(scenario['style'])}"]

    # Calm by default. A level caller is also the better test instrument: when
    # the agent gets something wrong, an unflustered correction shows whether it
    # recovers, where an agitated one muddies what caused the failure.
    urgency = _text(
        scenario.get(
            "urgency",
            "You would like this sorted out, and you are in no particular rush "
            "about it. Nothing here is an emergency.",
        )
    )
    lines += [
        "",
        "HOW YOU SOUND",
        f"- {urgency}",
        "- Calm and even the whole way through. Steady, low-key, easy to deal "
        "with. Never anxious, never pushy, never chirpy.",
        "- Calm does not mean slow. Answer as soon as they finish speaking, "
        "without leaving a gap.",
        "- If they get something wrong, mishear you, or repeat themselves, stay "
        "relaxed about it. Correct them once, plainly, and carry on. Do not "
        "get irritated and do not over-apologise.",
        "- Do not narrate what you are about to do. Just say the thing.",
    ]

    end_when = _text(
        scenario.get(
            "end_when",
            "you have either achieved your goal or been clearly told it is not "
            "possible",
        )
    )
    lines += [
        "",
        "ENDING THE CALL",
        f"- Once {end_when}, read back what was agreed to confirm you have it "
        "right, thank them, say goodbye, and stop talking.",
        "- Do not drag the call out once it is done, and do not hang up early "
        "while anything you came for is still unresolved.",
    ]

    return "\n".join(lines)


def build_session_update(scenario: dict[str, Any]) -> dict[str, Any]:
    """Build the GA `session.update` client event for this scenario."""
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": MODEL,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": MULAW_FORMAT,
                    # server_vad fires on a silence timer instead of judging
                    # whether a thought is finished, which removes the
                    # deliberation semantic_vad spends before every reply.
                    # "high" eagerness was already the fastest semantic setting,
                    # so this is the only remaining lever on the gap.
                    #
                    # The risk is cutting the agent off mid-pause. 500ms is
                    # comfortably longer than the breath between clauses and
                    # short enough to feel prompt. If calls start showing
                    # interruptions, raise this before changing anything else.
                    "turn_detection": {
                        "type": "server_vad",
                        "silence_duration_ms": 500,
                        "prefix_padding_ms": 300,
                        "threshold": 0.5,
                    },
                    # Gives us the agent's side of the transcript.
                    "transcription": {"model": "whisper-1", "language": "en"},
                },
                "output": {
                    "format": MULAW_FORMAT,
                    # ash reads male and sits lower and steadier than cedar,
                    # which suits a caller who stays level-headed. Overridable
                    # per scenario so a persona can be cast differently.
                    "voice": scenario.get("voice", "ash"),
                },
            },
            "instructions": build_instructions(scenario),
        },
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python src/prompt.py <scenario.yaml>")
    print(json.dumps(build_session_update(load_scenario(sys.argv[1])), indent=2))
