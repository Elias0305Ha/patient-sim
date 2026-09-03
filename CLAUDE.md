# patient-sim

A test harness that places automated phone calls to a healthcare voice AI agent,
plays a realistic patient persona, records and transcribes both sides, and
surfaces bugs in the agent under test.

Built as a submission for the Pretty Good AI AI Engineering Challenge.

## Hard rules

These are not suggestions. Violating any of these breaks the submission.

1. The only phone number this project ever dials is **+1-805-439-8008**.
   Never dial any other number. Never read a destination number from user input.
   The number lives in `.env` as `TARGET_NUMBER` and is asserted before every call.
2. All outbound calls originate from **one** Twilio number, set once in `.env`.
   The graders look up call quality by that number. It never changes.
3. No secrets in the repo, ever. Everything sensitive comes from `.env`.
   `.env` is gitignored. `.env.example` is committed with empty values.
   Before any commit, check that no key, token, or SID appears in tracked files.
4. Audio is **g711 μ-law, 8kHz, mono** end to end. Twilio speaks it, OpenAI
   Realtime accepts it. Do not resample. Do not convert to PCM. Do not add
   an audio processing library. If you think you need one, you have a bug
   somewhere else.
5. Personas and scenarios live in `scenarios/*.yaml` as data. Never hardcode
   a persona, a goal, or a test case inside Python.
6. This project calls a live production system that real patients use.
   Calls are spaced out, never run in parallel, and never loop unattended.

## Architecture

```
scenario.yaml ──> prompt builder ──> OpenAI Realtime (ears + brain + voice)
                                            │  ▲
                                    audio out│  │audio in
                                            ▼  │
                    Twilio  <──  bridge.py (dumb relay)
                       │
                   phone call ──> +1-805-439-8008 (agent under test)
                       │
                  Twilio recording ──> results/recordings/*.mp3
```

Flow of one call:

1. `caller.py` loads a scenario, starts a local websocket server, and asks
   Twilio to place an outbound call with `record=true` and dual-channel
   recording.
2. Twilio connects the call's audio to our websocket via `<Connect><Stream>`.
3. `bridge.py` opens a second websocket to the OpenAI Realtime API, sends the
   session config built from the scenario, then relays audio in both
   directions until either side hangs up.
4. Transcript events from Realtime are written to `results/transcripts/` with
   elapsed-second timestamps for both sides.
5. Turn timing (agent response latency, overlaps, dead air) is written to
   `results/metrics/`.
6. After the call, Twilio's recording is downloaded to `results/recordings/`.
7. `grade.py` reads a transcript and emits candidate issues as JSON. A human
   triages those into `BUGS.md`. The grader never writes the bug report.

## Design decisions and why

Record these in `ARCHITECTURE.md` as they are made. Current position:

- **OpenAI Realtime API instead of an STT to LLM to TTS pipeline.** The
  challenge is graded first on whether the bot holds a natural conversation
  with sensible turn-taking. A three-stage pipeline stacks latency at every
  handoff and leaves endpointing as our problem to solve. Realtime does
  server-side VAD and responds in well under a second.
- **g711 μ-law passthrough.** Twilio Media Streams emits μ-law 8kHz and
  Realtime accepts μ-law 8kHz, so the bridge does zero audio conversion.
  This is the reason for pairing these two specific services.
- **Twilio's own call recording instead of capturing audio ourselves.** One
  parameter gives a dual-channel recording with the agent and our bot on
  separate tracks. Writing our own mixer would add a failure mode for no gain.
- **The bridge stays dumb.** All intelligence lives in the scenario prompt and
  the post-call grader. If the bridge starts making decisions, that is a
  design smell.

Alternatives evaluated and rejected: Vapi and Retell (they hide the part being
tested), Pipecat and LiveKit Agents (abstraction costs more to learn than the
code it saves for a single outbound use case), Twilio ConversationRelay (hands
turn-taking control to Twilio, which is the graded bar).

## Layout

```
scenarios/*.yaml        persona, goal, success criteria, edge-case flags
src/caller.py           CLI entry point, places calls, orchestrates a run
src/bridge.py           Twilio <-> Realtime audio relay, transcript capture
src/prompt.py           builds the Realtime session config from a scenario
src/metrics.py          turn timing, overlaps, dead air
src/grade.py            LLM pass over a transcript, emits candidate issues
results/transcripts/    transcript-NN.txt, both sides, timestamped
results/recordings/     NN.mp3
results/metrics/        NN.json
results/summary.md      generated table across all runs
BUGS.md                 hand-written, the actual deliverable
ARCHITECTURE.md         decisions and tradeoffs
CHANGELOG.md            what broke, what changed, after each round of calls
```

## Conventions

- Python 3.11. Dependencies: `twilio`, `websockets`, `pyyaml`, `python-dotenv`,
  `openai`. Nothing else without a reason written down.
- Standard library `logging`, structured, one line per websocket event with a
  monotonic elapsed timestamp. Logs are the only way to debug a silent call.
- Every module runs standalone for testing where practical.
- Type hints on function signatures. No heavy typing gymnastics.
- Small functions. If the bridge relay loop exceeds about 60 lines, split it.

## How to work with me on this

- **Read the current docs before writing API code.** The OpenAI Realtime API
  and Twilio Media Streams message formats change. Fetch the official docs and
  quote the exact event names and field shapes you are going to use. Do not
  write Realtime or Media Streams code from memory. A wrong event name produces
  a call that connects, sits in silence, and raises no error.
- **Explain before you write.** Describe the file, its functions, and the data
  flow in prose first. Wait for my go-ahead.
- **One file at a time.** Do not scaffold the whole repo in one pass.
- **When something breaks, give me ranked hypotheses and how to test each one,
  not a patch.** I want to understand the system, not just get it running.
- I have to defend every line of this on a video call. If I cannot explain it,
  it does not ship.

## API notes to verify, not to trust

Treat everything below as a starting point to check against live docs.

- TwiML for bidirectional audio is `<Connect><Stream url="wss://..."/></Connect>`.
  `<Start><Stream>` is one-way and will not work here.
- Twilio Media Streams sends JSON events: `connected`, `start`, `media`, `stop`.
  `media.payload` is base64 μ-law, roughly 20ms per frame. To send audio back,
  post a `media` event carrying the `streamSid`. To cut off audio already
  buffered on Twilio's side during a barge-in, send a `clear` event.
- Realtime session config sets input and output audio format to μ-law and
  enables server-side turn detection. Both sides of the transcript arrive as
  events: one for what it heard, one for what it said. Confirm the exact event
  names against the docs.
- When Realtime signals that the other party started speaking, that is the
  trigger to clear Twilio's buffer so our bot stops talking over the agent.

## Local development

Twilio needs a public URL to reach the websocket server, so a tunnel
(ngrok or equivalent) points at the local port during development. The tunnel
URL goes in `.env` as `PUBLIC_WSS_BASE` and changes every time the tunnel
restarts.
