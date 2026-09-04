# Bug report — Pivot Point Orthopedics voice agent

Issues found across test calls to +1-805-439-8008. Ranked most to least severe.

Each entry cites the transcript in `results/transcripts/` and the Twilio call
SID, so any claim can be checked against the matching recording in
`results/recordings/`.

> **A note on timestamps.** Transcripts 01 and 02 stamp each line when its
> transcription completed, not when the speaker began. A long agent turn can
> therefore sort *after* the reply it provoked. This was fixed before call 3, so
> transcripts 03 onward are ordered by when speech actually started. Nothing
> below relies on the relative ordering of lines in transcripts 01 or 02.

---

## 1. Agent assigns a fabricated date of birth and cannot correct it live

**Severity:** High

**Calls:** all four. Primary evidence: `identity-mismatch`, transcript-04
(`CAcdd1823e43b73b6742e77381d0156b67`). Corroborating: `schedule-basic`
transcript-01 (`CA51ccdb2defb2d9637c1c85958a8000fc`) and transcript-02
(`CA27150c3e15e66dcd440410e7a03c2948`), `refill-request` transcript-03
(`CA4b64964c047b17cc35a1c0285c90e6f8`).

**Details:** In every call, without the patient having given a date of birth,
the agent volunteers *"your date of birth is July 4th, 2000."* The same date,
four independent calls, four fresh sessions. It appears to be a default in the
demo environment, but it is presented to the patient as a fact already on their
record.

The clearest demonstration is transcript-04. The patient corrects the date and
then asks four separate times, over roughly three minutes, for confirmation
that the record has been updated (0:51, 1:21, 1:57, 2:45). Twice the agent
reads back what is actually stored:

> [1:39] AGENT: Right now, your date of birth is listed as July 4, 2000.
>
> [2:19] AGENT: Your date of birth is still showing as July 4th, 2000 right
> now. I send your request to the clinic support team to update it to May 3rd,
> 2003. They usually confirm updates by phone or email within one business day.

So the fabricated value is not just spoken, it is stored. The agent has no
self-service path to correct a patient's own identity data during the call,
only an escalation that does not resolve within it. The call ends at 3:44 with
the wrong date of birth still on the record.

Date of birth is a primary identifier for matching patients to records and for
prescription safety. A value the system invented, wrote to the record, and
cannot correct through the same channel is the most consequential field to get
wrong.

**Worth noting:** in transcript-03 this same agent *correctly refuses* to refill
a medication it has no record of, rather than inventing one. It is careful not
to fabricate medication data while freely fabricating identity data.

---

## 2. Support escalation dead-ends at an internal test line

**Severity:** High

**Call:** `refill-request`, transcript-03
(`CA4b64964c047b17cc35a1c0285c90e6f8`) at 1:04–1:31.

**Details:** The patient requests a refill (meloxicam 15mg, roughly four days of
supply left). The agent correctly reports no matching medication on the chart
and offers to connect the patient to the support team. The patient accepts. The
call never reaches support:

> [1:04] AGENT: I don't see any medications on your chart that I can refill
> right now... Would you like me to connect you to our patient support team for
> further help?
>
> [1:17] PATIENT: Yes, please connect me...
>
> [1:24] AGENT: Time for you now. Thank you.
>
> [1:30] AGENT: Hello, you've reached the Pretty Good AI test line. Goodbye.

The call ends there. A patient days away from running out of medication is
offered help, accepts it, and is dropped onto what appears to be internal test
infrastructure with no path to a human.

The failure is also silent from the patient's side: nothing signals that the
transfer failed, so a real caller would have no reason to think anything other
than that the practice hung up on them.

---

## 3. Agent asks for a name it has already been given and acknowledged

**Severity:** Medium

**Call:** `schedule-basic`, transcript-01
(`CA51ccdb2defb2d9637c1c85958a8000fc`) at 0:21–0:38.

**Details:** The patient gives their name and reason for calling in one turn.
The agent acknowledges the name by using it, then immediately asks for the same
name again:

> [0:21] PATIENT: Hi, this is Elias Hakenso. I'm calling to set up an
> appointment to have my right knee looked at.
>
> [0:38] AGENT: Thanks, Elias. Would you like me to create a demo patient
> profile for you so we can get started with scheduling your appointment? I
> just need your first and last name to set it up.

Using the name proves it was captured, which rules out a speech recognition
failure and points at the profile-creation step not reading from what the
conversation already established. It costs a turn, and to a caller it reads as
the agent not listening.

The same pattern appears in transcript-02, where the patient gives their name
and the agent's next line asks for it again.
