# Architecture

## How it works

One command places one call. `caller.py` loads a scenario YAML, starts the
bridge websocket server in the same process, checks that the public tunnel is
reachable, then asks Twilio to dial +1-805-439-8008 with TwiML that connects the
call's audio to that websocket. `bridge.py` opens a second websocket to the
OpenAI Realtime API, sends a session configuration built from the scenario, and
then relays audio frames in both directions until either side hangs up. Realtime
does the listening, the thinking and the speaking; the bridge only copies bytes
and records what was said. Afterwards the transcript is written to
`results/transcripts/` and Twilio's dual-channel recording is downloaded to
`results/recordings/`.

```
scenario.yaml ──> prompt.py ──> OpenAI Realtime (ears + brain + voice)
                                        │  ▲
                                audio out│  │audio in
                                        ▼  │
                Twilio  <──  bridge.py (dumb relay)
                   │
               phone call ──> +1-805-439-8008 (agent under test)
                   │
              Twilio recording ──> results/recordings/NN.mp3
```

## The decisions that mattered

**Realtime API rather than an STT → LLM → TTS pipeline.** The brief says
submissions that fail to hold a coherent voice conversation are rejected without
further review, so latency and turn-taking were the constraints to optimise
against, not model quality. A three-stage pipeline adds a handoff at every
boundary and makes endpointing — deciding when the other party has finished
speaking — our problem to solve. Realtime does voice activity detection
server-side and replies in well under a second. The cost is control: we cannot
inspect or post-process the intermediate text before it becomes speech. For a
test harness whose job is to sound like a patient, that trade is clearly worth
making. If the goal had been deterministic scripted probes, the pipeline would
have won.

**G.711 μ-law end to end, with no audio processing anywhere.** Twilio Media
Streams emits base64 μ-law at 8kHz and Realtime accepts the same, so
`media.payload` is forwarded into `input_audio_buffer.append` untouched and
audio deltas are wrapped straight back into Twilio media messages. This is the
specific reason for pairing these two services. It removes resampling, format
conversion and an audio library from the system, along with every bug those
would bring. There is no `audioop`, no `numpy`, no buffering, and no queue in
the audio path.

**Twilio's own recording rather than capturing audio ourselves.** One parameter
(`recording_channels="dual"`) produces a two-track recording with the agent and
our bot separated, which makes overlaps audible on review. Writing our own mixer
would have added a failure mode and produced worse evidence.

**The bridge makes no decisions.** All persona and steering logic lives in the
scenario prompt; all judgement about call quality happens afterwards by reading
transcripts. The bridge's only behavioural rule is barge-in: when Realtime
reports `input_audio_buffer.speech_started`, Twilio is sent a `clear` to drop
audio it has already buffered from us. Without that one message the bot talks
over the agent for the length of the buffer, which is most of what "bad
turn-taking" sounds like on a recording.

**Scenarios are data, not code.** Each call is a YAML file with a persona, a
goal, things the caller must raise, a tone, and an end condition. Adding a test
case never means editing Python. One flag, `barge_in`, inverts turn-taking for
the single scenario whose purpose is interrupting.

## Alternatives evaluated

- **Vapi, Retell** — they own the orchestration layer being tested here, which
  would hide the part of the system worth demonstrating.
- **Pipecat, LiveKit Agents** — real frameworks, but for a single outbound use
  case they cost more to learn than the roughly 250 lines they would replace.
- **Twilio ConversationRelay** — hands turn-taking to Twilio. Turn-taking is the
  graded bar, so it is not something to delegate.
- **server_vad vs semantic_vad** — started on `semantic_vad`, which waits for a
  finished thought rather than a silence timer and interrupts less. It left an
  audible gap before every reply even at `eagerness: "high"`. Switched to
  `server_vad` at 500ms, which is noticeably snappier; the risk is clipping a
  mid-sentence pause, so that threshold is the first thing to raise if
  interruptions appear.

## What testing taught us

Two pieces of tooling exist because of specific failures, and both are worth
more than the code they contain.

`bridge.py --selftest` connects to Realtime, applies the session config and
reports what the server accepted, without placing a call. The GA Realtime
interface differs from the beta in ways that fail silently: audio format is a
nested object (`{"type": "audio/pcmu"}`) rather than the beta's flat
`"g711_ulaw"` string, `session.type` is required, and the beta header must be
dropped. Getting any of those wrong produces a call that connects, sits in
silence and raises no error. The selftest turns a five-minute phone debugging
loop into a one-second check.

`caller.py` preflights the tunnel with a real websocket handshake before
dialling. Quick tunnels expire without warning, and the first version of that
check used an HTTP GET — which hangs against a websocket server, so it failed
precisely when everything was working. The lesson generalised: probe with the
same protocol the real client uses.

Iteration on the caller itself came from listening rather than reading. Call 1
worked but sounded synthetic and slow. Three rounds of changes followed —
turn detection, voice, and finally explicit instructions to speak with real
disfluency, since the model's default clean sentences are the strongest tell
that a caller is not a person. `audition.py` records a sample per candidate
voice so that choice could be made by ear without spending calls; it initially
auditioned the wrong thing, because response-level `instructions` replace the
session instructions rather than adding to them, discarding the persona.
