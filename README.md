# patient-sim

An automated voice bot that calls a healthcare AI agent, plays a realistic
patient, records and transcribes both sides of the conversation, and surfaces
bugs in the agent under test.

Built for the Pretty Good AI AI Engineering Challenge. Every call goes to the
assessment line, **+1-805-439-8008**, and nowhere else.

- **[BUGS.md](BUGS.md)** — what we found. Nine issues, plus the probes that
  found nothing, which are recorded too.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — how it works and why it is built
  this way.
- **[results/transcripts/](results/transcripts/)** — both sides of 11 calls,
  timestamped.
- **[results/recordings/](results/recordings/)** — the same 11 calls as
  dual-channel MP3.

## How it works, briefly

`caller.py` starts a websocket server, has Twilio dial the test line, and
streams the call's audio to it. `bridge.py` relays that audio to the OpenAI
Realtime API, which listens, thinks and speaks as the patient. Audio is G.711
μ-law at 8kHz on both sides, so nothing is converted anywhere. Personas live in
`scenarios/*.yaml`, never in Python.

## Setup

Requires Python 3.11+ (developed on 3.14).

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill it in, see below
```

### Environment

Every variable is documented in [.env.example](.env.example). `.env` is
gitignored and must never be committed.

| Variable | Where it comes from |
| --- | --- |
| `TWILIO_ACCOUNT_SID` | Twilio console, Account Info |
| `TWILIO_AUTH_TOKEN` | Twilio console, Account Info |
| `TWILIO_FROM_NUMBER` | The one Twilio number all calls originate from, E.164 |
| `TARGET_NUMBER` | `+18054398008`. Asserted before every call; do not change |
| `OPENAI_API_KEY` | An account with Realtime API access and credit |
| `PUBLIC_WSS_BASE` | Your tunnel's `wss://` URL, no trailing slash |
| `WS_PORT` | Local port for the bridge. Default `8080` |

### Tunnel

Twilio needs a public URL to reach the bridge on your machine.

```bash
cloudflared tunnel --url http://localhost:8080
```

Copy the printed `https://…trycloudflare.com` URL into `PUBLIC_WSS_BASE` with
the scheme changed to `wss://`. Quick tunnels expire, so this changes each time
you restart it. `caller.py` checks the tunnel before dialling and tells you if
it has gone stale rather than wasting a call finding out.

## Running

Place one call:

```bash
python src/caller.py scenarios/schedule-basic.yaml
```

That prints the conversation live, writes `results/transcripts/transcript-NN.txt`
and downloads `results/recordings/NN.mp3`.

### Other commands

```bash
# Check the Realtime session config without placing a call. Costs nothing.
python src/bridge.py --selftest scenarios/schedule-basic.yaml

# Print the prompt a scenario produces, to review before spending a call.
python src/prompt.py scenarios/schedule-basic.yaml

# Record a sample of each candidate voice and choose one by ear.
python src/audition.py scenarios/schedule-basic.yaml cedar ash ballad verse

# Re-download a recording that failed to save. The call SID is in the transcript.
python src/caller.py --fetch CA1234... 07
```

## Scenarios

| File | What it tests |
| --- | --- |
| `schedule-basic.yaml` | Baseline: book an appointment for knee pain |
| `refill-request.yaml` | Medication refill |
| `reschedule.yaml` | Move an appointment, then cancel it |
| `insurance-update.yaml` | Update insurance with an incomplete card |
| `weekend-booking.yaml` | Push for a Sunday slot when the office is closed |
| `identity-mismatch.yaml` | Correct a wrong date of birth on the record |
| `vague-symptoms.yaml` | A caller who cannot describe the problem |
| `interruptions.yaml` | Deliberate barge-in; the caller talks over the agent |
| `hours-and-location.yaml` | Hours, address, parking, walk-ins. No booking |
| `post-op-imaging.yaml` | Post-surgical follow-up and an MRI request |

Adding a test case means writing a YAML file, not editing code. Each one sets a
persona, a goal, points the caller must raise, a tone and an end condition.

## Layout

```
src/caller.py       places calls, orchestrates a run, downloads recordings
src/bridge.py       Twilio <-> Realtime relay, transcript capture, --selftest
src/prompt.py       builds the Realtime session config from a scenario
src/audition.py     records voice samples for comparison
scenarios/*.yaml    personas and test cases
results/            transcripts and recordings
PRACTICE_NOTES.md   what the agent under test claims it can do
```

## Notes

- Calls are placed one at a time, never in parallel and never unattended. This
  dials a live system.
- Twilio hangs up at `MAX_CALL_SECONDS` (330s) so a wedged call cannot run on.
- `results/` is deliberately committed. Transcripts and recordings are the
  evidence the bug report rests on.
