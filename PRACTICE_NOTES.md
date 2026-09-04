# Practice notes: what the agent under test claims to do

Collected from the pgai.us/athena signup flow. This is ground truth for writing
scenarios and for telling a real bug (agent got something wrong) apart from an
expected limitation (we tested something outside its scope).

## Demo practice

- Name: **Pivot Point Orthopedics**
- Product: Pretty Good AI voice agent, demo instance
- Confirmation screen listed a callable demo number, (615) 645-1400, and a
  "call me instead" option. **Neither is used.** Every test call goes to the
  assessment number only: **+1-805-439-8008**. Do not dial anything else.

## Capabilities the confirmation screen states

Direct quote from the signup flow: "You can create or change appointments,
update insurance, or refill a prescription at the demo clinic Pivot Point
Orthopedics."

That's four confirmed capabilities to build scenarios around:
1. Create an appointment
2. Change/cancel an appointment
3. Update insurance information
4. Refill a prescription

Orthopedics-specific angles worth testing on top of the generic set, since
this is a specialty practice, not general primary care:
- Physical therapy referral / follow-up scheduling
- Post-surgery follow-up appointment
- Imaging or X-ray scheduling
- DME requests (crutches, braces, slings)
- Joint pain triage / urgency of symptoms

## Registered test patient identity

Signing up created a real patient record in their demo system:

- Name: **Elias Hakenso**
- DOB: **May 3, 2003**

Use this exact name and DOB as the caller identity in scenarios that require
the agent to look up or verify an existing patient. A made-up identity will
likely fail lookup on every call and produce uninteresting "patient not
found" transcripts instead of testing the actual scheduling/refill/insurance
logic.

Scenarios that intentionally test identity verification failure (wrong DOB,
mismatched name) should do so as a deliberate edge case, not by accident.

## Open questions to fill in once more of the demo is explored

- Office hours (esp. weekend closures, since PGAI's own example bug report is
  a Sunday-booking mistake)
- Whether multiple providers/locations exist
- Insurance carriers it recognizes, if any are named
- Whether it distinguishes new vs. established patient
