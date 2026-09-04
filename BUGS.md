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

---

## 4. Agent offers appointment times before its own stated opening hours

**Severity:** Medium

**Calls:** `schedule-basic`, transcript-02
(`CA27150c3e15e66dcd440410e7a03c2948`) at 1:25, against `weekend-booking`,
transcript-05 (`CAa644f945e34f08a63aef467be2a79a69`) at 1:42.

**Details:** Asked directly for its hours, the agent states them precisely:

> [1:42] AGENT: Our office hours are Monday, Tuesday, and Thursday, 9 a.m. to
> 4 p.m. Wednesday, 12 p.m. to 7 p.m. Friday, 9 a.m. to 12 p.m. We don't have
> appointments outside these hours...

In an earlier call it offered this patient two Tuesday slots before that:

> [1:25] AGENT: We have morning openings on Tuesday, September 8th, with
> Dr. Zyg Bigniulakoski at 830 and 845, and with Dr. Kelly Noble at 9 and 915.

8:30 and 8:45 on a Tuesday are 30 and 45 minutes before the practice opens. The
scheduling path and the hours path disagree, and the agent asserts each
confidently without reference to the other.

This is the same failure as the example bug in the brief -- booking outside
operating hours -- reached from the opposite direction. The weekend case is
handled (see below); the weekday boundary is not.

**Corroborated in transcript-10** (`CA466f590950fad61318aa496fbeb7d4ac`, at 0:56). Asked the same question
forty minutes later on a separate call, the agent gave byte-identical hours:
Monday, Tuesday and Thursday 9-4, Wednesday 12-7, Friday 9-12. The hours are
stable and consistently reported, so the 8:30 and 8:45 slots are not drift in
the hours data. The scheduling path is the one that is wrong, and it presents
its slots with the same confidence as the correct answer.

**Not a bug:** the weekend probe in transcript-05 did not reproduce the example
bug. Asked for Sunday, the agent refused and stated the practice is Monday to
Friday; pushed to Saturday, it refused again. Whatever guards the weekend case
is either not applied to opening times or does not know them.

---

## 5. A past appointment is listed as upcoming, and can be "cancelled"

**Severity:** Medium

**Call:** `reschedule`, transcript-06 (`CA15e8687b46cb18effe133ed41eb53282`)
at 0:50 and 3:28. Contrast with `weekend-booking`, transcript-05, at 2:54.

**Details:** The call was placed at 12:47pm on Friday September 4th. Asked what
was on file, the agent answered:

> [0:50] AGENT: You have two upcoming appointments. One is today, Friday,
> September 4th at 10 a.m. with Kelly Noble, M.D. The other is Tuesday,
> September 8th at 8.30 a.m. with Z. Bignew-Lukosky, M.D.

The 10 a.m. appointment had already passed nearly three hours earlier. The
agent then took the patient through cancelling it and confirmed twice that it
was done, without ever noting that the time had elapsed.

The same record is reported differently between calls. In transcript-05, placed
at 12:29pm the same day, the agent named only the Tuesday appointment:

> [2:54] AGENT: You already have an appointment booked for Tuesday, September
> 8th at 8.30 a.m. for your knee.

Two calls eighteen minutes apart disagree about what is booked. A patient
relying on either answer cannot tell which is right, and "cancelling" an
appointment they have already missed gives false reassurance about a visit that
did not happen.

**Not a bug, and done well:** offered a second Tuesday slot, the agent checked
it against the existing one rather than double-booking blindly -- *"There's
enough time between them so you can keep both."* And the cancellation itself was
handled correctly: this scenario was written expecting a rescheduled slot to
survive a later cancellation, and that did not happen. The agent cancelled the
right appointment and reported the remaining one consistently.

---

## 6. Advertised self-service capabilities defer to a callback instead of completing

**Severity:** High

**Calls:** `refill-request` transcript-03 (`CA4b64964c047b17cc35a1c0285c90e6f8`)
at 1:04, `identity-mismatch` transcript-04
(`CAcdd1823e43b73b6742e77381d0156b67`) at 1:08, `insurance-update`
transcript-07 (`CAc09f471c20aa162aa86ed2e0b9288dd8`) at 1:19 and 2:04.

**Details:** The signup flow states: *"You can create or change appointments,
update insurance, or refill a prescription at the demo clinic Pivot Point
Orthopedics."* Of those four capabilities, only appointment scheduling and
changing actually complete during the call. The other three all end in a
promise that somebody else will deal with it:

- Refill (transcript-03): *"Would you like me to connect you to our patient
  support team for further help?"* -- and that transfer then fails outright
  (see bug 2).
- Identity correction (transcript-04): *"The clinic support team will review and
  confirm the change as soon as they can."*
- Insurance (transcript-07): *"our team will follow up with you directly to
  confirm your Blue Cross Blue Shield plan and let you know if it's accepted."*

Each deferral is individually reasonable. Together they mean a patient can call
the number advertised for these tasks, complete none of them, and leave with no
confirmed timeline. Two of the three are also unverifiable to the caller: they
are told a note was made, but nothing is read back.

**Compounding this, in transcript-07 the agent contradicts itself about whether
it captured anything:**

> [1:19] AGENT: We were not able to collect your insurance details just now, so
> our team will follow up with you directly...
>
> [2:04] AGENT: I've noted that you provided your Blue Cross Blue Shield member
> ID, and do not have the group number handy, so they will not wait for that.

The patient stated the member ID aloud (XKP884120366). The agent never repeats
it back, so there is no way for the caller to confirm it was heard correctly --
and the two statements above cannot both be true.

The agent also never answered the direct question *"do you actually accept this
plan?"*, which the patient asked twice.

---

## 7. Existing-appointment check runs on some calls and not others

**Severity:** Medium

**Calls:** `interruptions` transcript-08 (`CAbbe70c84c7f8dab41de81b32173a5426`) at 0:51-1:15, against
`reschedule` transcript-06 (`CA15e8687b46cb18effe133ed41eb53282`) at 2:26.

**Details:** At the end of transcript-06 the agent confirms the patient's only
remaining appointment:

> [3:28] AGENT: You still have one appointment booked Tuesday, September 8th at
> 8.30 a.m. with Dr. Lukosky.

In transcript-08 the same patient asks for the earliest available slot. The
agent offers and books Tuesday September 8th at 10 a.m. with the same doctor,
without mentioning the 8.30 a.m. appointment that already exists that morning:

> [0:51] AGENT: Your least available appointment is Tuesday, September 8th at
> 10 a.m. with Dr. Zygmunt Likoski. Would you like to book that slot?
>
> [1:15] AGENT: Your appointment is set for Tuesday, September 8th at 10 a.m.
> with Dr. Zygmunt Lukosky at Pivot Point Orthopedics.

The patient now has two appointments with the same provider on the same
morning and was told about neither conflict.

This is not a missing feature. Two calls earlier the agent performed exactly
this check unprompted:

> [2:26] AGENT: You have an appointment with Dr. Lukoski at 8.30 a.m. on
> Tuesday, September 8th, and the new slot with Dr. Noble would be at 10.30
> a.m. the same day. There's enough time between them so you can keep both.

So the capability exists but does not run consistently. The difference between
the two calls is that transcript-08 reached booking through a fast path where
the caller was repeatedly interrupting and asking to skip ahead, which suggests
the check is tied to a conversational route rather than to the booking action
itself.

**Also in this call:** *"Your least available appointment is..."* -- presumably
"next" or "earliest". Minor, but it is the sentence that presents the slot the
patient is asked to accept.

**Not a bug:** the agent handled being interrupted well. Our caller cut in
during the greeting and twice more mid-sentence; the agent did not restart its
script from the top, did not repeat itself, and completed the booking in 1:46.

---

## 8. A request for a new appointment is silently absorbed into an existing one

**Severity:** High

**Call:** `vague-symptoms` transcript-09 (`CA23790649a431c0b25fc194b7c75d3499`) at 1:16-2:45.

**Details:** The patient calls about a shoulder problem, a different complaint
from anything previously booked, agrees to be seen, and states no provider
preference. Rather than creating an appointment, the agent surfaces an existing
one and offers it as the answer:

> [1:54] AGENT: You already have an office visit scheduled for Tuesday,
> September 8th at 10 a.m. Would you like to keep that appointment, reschedule
> it, or cancel it?

The patient, reasonably, takes this to mean he is booked. The agent then
confirms that slot as being for the new complaint:

> [2:45] AGENT: You've got it. September 8th at 10 a.m. for your shoulder and
> upper arm.

That 10 a.m. appointment was created in transcript-08 for an unrelated reason.
No new appointment exists. A patient with two distinct problems leaves believing
both will be seen, in a single visit that was never scheduled for the second
one.

**The record is now inconsistent across three consecutive calls for the same
patient:**

| Call | What the agent reported as booked |
| --- | --- |
| transcript-06 | Tuesday 8:30 a.m. with Dr. Lukoski, stated as the only appointment |
| transcript-08 | Tuesday 10:00 a.m. with Dr. Lukoski; the 8:30 is not mentioned |
| transcript-09 | Tuesday 10:00 a.m., now described as the shoulder visit; the 8:30 is not mentioned |

Each call is internally confident and none of them agree. Taken with bug 7,
the pattern is that appointment state is read differently depending on the route
through the conversation rather than from a single source of truth.

**Not a bug:** the agent stayed inside its scope. Asked directly whether these
symptoms were something the practice handles, it answered as routing rather
than diagnosis -- *"Pivot Point Orthopedics treats shoulder and upper arm
issues, including catching, weakness, or limited movement"* -- and moved to
scheduling without offering an opinion on what was wrong. For a vague,
self-doubting caller, that is the right boundary.

---

## 9. Provider names are unstable within a single call

**Severity:** Medium — **needs confirmation against the recording, see below**

**Call:** `post-op-imaging` transcript-11 (`CAd98d3baa5198fc13a0339d84a0c5ffb5`) at 1:30-2:56.
Audio: `results/recordings/11.mp3`.

**Details:** The agent offers a provider, then names that same provider three
more times over the next ninety seconds, differently each time:

> [1:30] AGENT: ...openings for follow-up visits on Tuesday, September 8th with
> **Judy Hauser**, Carl Menz, PT, or Kelly Noble, MD.
>
> [1:44] AGENT: The earliest available slot is Tuesday, September 8th at 9 a.m.
> with **Doogie Hauser**.
>
> [2:12] AGENT: Your appointment is set for Tuesday, September 8th at 9 a.m.
> with **Doogie Houser** at Pivot Point Orthopedics.
>
> [2:56] AGENT: You're all set for Tuesday, September 8th at 9 a.m. with
> **Duvy Hauser** at Pivot Point Orthopedics.

The two confirmations of the booking name two different people. A patient cannot
tell who they are scheduled with, and "Doogie Houser" is close enough to a
well-known fictional physician to sound like the agent is not reading a real
record.

The same instability shows up elsewhere: the practice's own name is rendered
"Edit Point Orthopedics" in transcript-10 at 0:56, and Dr. Zbigniew Lukoski
appears as "Zyg Bigniulakoski", "Z. Bignew-Lukosky" and "Zygmunt Likoski" across
transcripts 02, 05 and 08.

**Verification needed.** These transcripts are produced by speech recognition
over the agent's audio, so this entry cannot distinguish between the agent
mispronouncing names and our transcription mishearing them. Two things argue for
the former -- the variation occurs within one call under identical audio
conditions, and it affects proper nouns specifically while surrounding speech
transcribes cleanly -- but that is inference. Confirm against 11.mp3 before
treating this as a defect in the agent rather than in our tooling.
