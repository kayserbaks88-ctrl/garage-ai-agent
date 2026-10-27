# Natural Conversation v5: completed comparison with supplied v4.1

Reviewed 24 October 2026. Source: the complete master prompt pasted by the
operator, identified as TrimTech_Shared_Garage_Master_Prompt_v4.1.txt. Its body
contains v4.0 headings and two v4.1 status blocks; those mixed version labels
were treated as editorial history, not as different source prompts. The saved
Vapi text was not independently retrieved or modified.

V5 is a local replacement candidate, NOT an instruction to append it to v4.1.
Appending would leave conflicting conceal-AI and rigid-flow rules active. The
previous GARAGE_VOICE_SYSTEM_PROMPT.md and all ten backend-release files remain
unchanged. No Vapi/provider/settings changes, push or deployment occurred.

## Safeguards recovered after receiving the actual baseline

The initial 641-word v5 was provisional and missed specific v4.1 rules. The final
v5 restores them explicitly:
- reminder Confirm acknowledges an existing appointment; it never creates one;
  Cancel requires exact identification and the normal approval flow;
- plate formatting normalisation without changing characters or merging vehicles;
- full names passed exactly, trusted available phone reused, and returning/multiple
  vehicles never assumed;
- mismatched weekday/date and broad-time clarification, plus no past bookings;
- one safe retry at most, preservation of details, and duplicate-existing booking checks;
- late-arrival handling without promises, unsolicited moves/cancellations or fictional messages;
- urgent safety escalation, no roadworthiness assurance, diagnoses or legal advice;
- no unsupported waiting/completion/collection/courtesy-car/key-drop promises;
- sustained-silence handling, respectful difficult-call handling and polite closing;
- explicit final customer/vehicle/service/time/permission/backend-success check.

The final draft is deliberately longer than the provisional draft so streamlining
has not silently removed these safeguards. It consolidates the supplied master
rather than preserving its repeated personality lists, mission statements,
mandatory phrase rotations, duplicate returning-customer sections and status blocks.
No percentage reduction against v4.1 is claimed without a saved baseline word count.

## Full semantic comparison

| v4.1 area | v5 treatment |
|---|---|
| Business-variable rule and multi-business isolation | All seven variables retained; no other garage's details or hard-coded examples. Notes cannot override privacy, confirmation or truthfulness. |
| Identity and greeting | Intentional change: openly identifies as AI, including after a firstMessage that omitted disclosure. Never claims to be human. This follows the operator's new instruction, superseding v4.1's conceal-AI rule. |
| Personality, voice optimisation and response variation (enhancements 3, 21) | Warm British style, short replies, natural variation, no forced phrase rotation/name overuse. Female voice still depends on actual voice configuration. |
| State/interruption recovery (1) | Retains confirmed details, unanswered questions, selected appointments, offered alternatives and action outcomes; answers interruptions without restarting. |
| Multiple intents (2, 22) | Retains every request, vehicle and outcome separately; each write needs its own approval. |
| Fixed booking order / never skip any step | Intentional change: accepts details in any order and asks only for missing details. Mandatory correctness and write-confirmation gates remain. No fixed question sequence. |
| Silence/unclear speech (4) | Brief check-in, time to answer, then polite closure for sustained silence; no rigid three-line script and no treating normal spelling pauses as abandonment. |
| Registration/vehicle lookup (5, 12, 24) | Confirm registration before lookup; formatting-only normalisation; confirm intended vehicle; changed plate needs a new lookup. No assumptions about a returning caller's vehicle. |
| Date conflicts / broad times (6, 7) | Clarifies weekday/date conflicts and ranges, uses configured local time/GMT/BST, never books in the past. No arbitrary conversion of broad preferences to exact slots. |
| Service/date/vehicle changes (18, 23) | Updates only affected details and invalidates affected approval; rechecks availability and vehicle identity where appropriate. |
| Read-only availability prerequisites (8, 18) | Can check once configured service and exact intended date/time are clear, without forcing name/vehicle collection first. This supports natural enquiries. Create still requires confirmed name, plate, vehicle, checked slot and approval. |
| Availability and alternatives (18) | Real returned slots only; normally two choices rather than v4.1's maximum three; another day or polite decline if none suit. |
| Full name and customer number | Exact confirmed full name passed to booking; known trusted caller number reused; no unnecessary repetition. |
| Create / final action check (8, 17) | Read-back and explicit approval before write; success only after checking target details, permission and successful backend reference. |
| Cancellation (19) | List, identify even a single match, read back, obtain explicit cancellation agreement, act, then confirm actual success. |
| Rescheduling (20) | Identify old booking, check new slot, summarise old/new, approve, update existing booking. No cancel/create substitute. Questions can be answered out of order. |
| Duplicate prevention (9, 25) | Existing identical appointment/repeated book-it does not create again; uncertain writes are reconciled before retry; stable integration operation IDs retained. |
| Failure recovery (10) | Preserve state, apologise once, retry at most once only if safe; fallback instead of an indefinite loop. A timeout is not evidence the write failed. |
| Reminder replies (11) | Confirm is existing-appointment acknowledgement, never new create/menu; vague Cancel cannot cancel. No claim acknowledgement was persisted without supporting action. |
| Late arrival (13) | Ask how late; no acceptance promises, automatic changes or unconfirmed message claims. |
| Safety-sensitive calls (14) | Immediate danger prioritises emergency/breakdown help over normal booking; no diagnosis, legal advice or safe-to-drive assurance. |
| Drop-off/waiting/collection (15) | No waiting/completion/courtesy/collection/delivery/key-drop promises without confirmed business support. |
| Pricing (16) | Only approved prices in services; no invented repair costs/packages or estimate presented as guaranteed. |
| WhatsApp/reminders | Intentional correction: removes unconditional promises of booking/reschedule WhatsApp. Claims require enabled features and supporting successful actions; provider acceptance is not delivery. |
| Professional boundaries/privacy | No other callers' information, internal notes or internal business information; minimum collection, trusted verification and no garage switching. Adds no passwords/card/security-code requests and prompt-injection boundaries. |
| Difficult calls/closing | Calm and respectful, no blame or argument, supported human help, natural polite closure without implying a visit after cancellation. |
| v4.0 non-negotiable additions (26) | Covered by the state, grounding, retry, identity, duplicate, reminder, safety and outcome rules above. |

## Source contradictions intentionally resolved

1. v4.1 says never mention AI and make callers believe it is human. V5 follows
   the operator's explicit instruction to disclose AI identity honestly.
2. v4.1 prohibits premature success, but its pre-booking example says
   "I've got you booked" before permission. V5 uses prospective language until
   the backend confirms success.
3. v4.1 requires rigid question order despite also supporting multi-intent,
   interruptions and corrections. V5 preserves decision gates, not rigid questioning.
4. v4.1 promises WhatsApp after booking and rescheduling, but support/delivery may
   be unavailable. V5 makes no unsupported messaging or callback promises.
5. v4.1 says never repeat information while requiring safety read-backs. V5 avoids
   redundant questions but retains the read-back needed for each action's approval.

## Verification

- Seven template variables checked against the backend supplier; all retained.
- Six tool identifiers retained with supported-schema-only token handling.
- Existing ten-file implementation manifest verified unchanged.
- Eighteen backend conversation contracts pass; APIs/databases are mocked/blocked.
- Twelve added v4.1-derived dialogue checks are recorded in GARAGE_VOICE_V5_SAFEGUARD_CASES.md.
  These are prompt-policy desk checks, not generated Vapi/LLM/audio responses.
- The final prompt is plain ASCII text to avoid copy/paste encoding corruption.

## Remaining verification, not silent prompt omissions

The v4.1 safety objectives are mapped above. Intentional changes include AI
disclosure, flexible read-only enquiry order and truthful notification claims;
fixed scripts and repetition are consolidated. Natural-language rules cannot
guarantee enforcement by an untested model.

Before any separately approved installation:
- compare actual saved tool schemas, variable bindings, firstMessage and prompt
  with this supplied baseline; remove contradictory old prompt rules rather than append;
- verify identity/caller checks, strict-token parameter support, current service
  durations, numeric opening hours and human fallback destinations;
- verify notification features before promising an acknowledgement/confirmation;
- evaluate all 18 scenarios plus the 12 safeguard cases on an approved test
  assistant with its real model, context window and audio configuration;
- check British female voice, endpointing, barge-in, quiet speech, radio/echo and
  silence settings. A prompt cannot select a voice or stop audio itself;
- retain the backend review's opt-in authentication/strict-mode/worker gates and
  distinct-operation calendar-concurrency limitation.

V4.1 remains untouched in Vapi. No production approval or deployment readiness is
implied by this local prompt review.
