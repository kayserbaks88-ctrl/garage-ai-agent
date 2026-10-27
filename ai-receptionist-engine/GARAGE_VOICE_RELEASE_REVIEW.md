# Garage Voice reliability and conversation candidate

Local branch: `garage-voice-reliability-20261023`, based on
`de22317b66c16f4fd0fc508cdb2b1dbaca084990`. No push, deployment, production
access, database migration, provider switch or credential/settings change.
Existing Staff Manager, PayChaser, Stripe and root working changes are preserved.

## Implemented stages

1. Fixed all Vapi `business.name` error messages to use `business_name`.
   Calendar failures return structured failure instead of an attribute-error 500.
2. Requested-slot and alternative searches use one paginated, request-local day
   snapshot. A fresh conflict read still precedes a write. A client is reused for
   create's read/insert and reschedule's get/check/update. No global calendar,
   caller, payroll or employee-data cache exists. All-day/overlapping busy events,
   cancelled/transparent events and malformed busy intervals are handled safely.
   Caller booking searches read every page and normalize UK phone formatting.
   New writes and offers respect the configured numeric opening/closing hours;
   verify those values match the garage's actual published hours before release.
   Weekday-specific holiday/working-day capacity is not newly implemented.
3. All six existing tool URLs remain. The batch Function webhook now dispatches
   all six names, accepts direct or nested Function definitions and JSON-string
   arguments, preserves tool-call IDs and returns structured JSON inside Vapi's
   result string. Caller/business envelope fields override model arguments.
4. Optional Bearer authentication and strict confirmation context are implemented.
   Strict mode checks explicit agreement plus signed, ten-minute availability or
   booking tokens bound to business, caller and call. Changes to service/slot or
   the listed booking invalidate the relevant token. This prevents stale backend
   context being reused; it does not prove that an LLM heard a real caller say
   yes. The prompt and audio/LLM evaluation must enforce that conversational rule.
5. Stable call/operation IDs produce deterministic calendar event IDs. An existing
   matching booking is returned on replay; changed operation details are rejected.
   An insert timeout is reconciled against that ID without issuing another insert.
   Cancellation and rescheduling use Calendar ETags to reject concurrent changes;
   moving also checks the original start time. No missing create/move reference or unconfirmed cancellation is reported as
   success. Legacy direct requests without operation IDs remain compatible and
   do not gain persistent deduplication automatically.
6. Vehicle lookup returns a signed vehicle token when authentication is configured.
   Echoing it into create avoids the redundant lookup only for the same confirmed
   registration/business/caller/call. Invalid, expired or missing tokens fall back
   to the existing DVLA lookup. There is no cross-caller vehicle cache.
7. Optional deferred WhatsApp uses a Calendar-backed outbox marker written in the
   same insert as the appointment. No ephemeral background thread is used. The
   authenticated worker claims each pending event with `If-Match`/ETag before
   sending. Provider acceptance is recorded as `sent` (NOT proof of delivery).
   Exceptions or interrupted sends remain `uncertain`/`processing` for manual
   reconciliation, never blindly resent. Booking success survives notification
   failure. Existing synchronous notification behaviour is the default until an
   operator verifies the worker.
8. Ambiguous/nonexistent naive UK daylight-saving timestamps are rejected. Explicit
   offsets remain supported. Booking timeouts instruct reconciliation before retry.
9. `GARAGE_VOICE_SYSTEM_PROMPT.md` is a natural UK conversation candidate, ready to
   merge with the actual saved prompt. It covers concise follow-ups, corrections,
   uncertainty, interruptions, confirmations, all six tools and honest fallback.
   It is deliberately not injected into the uninspected master assistant.

## Compatibility and settings gates

No environment values were set outside the test process. These new controls are
opt-in, not instructions to activate them on the live system now:

| Setting | Default | Effect / deployment dependency |
|---|---|---|
| `VAPI_WEBHOOK_SECRET` | unset | Signing/authentication key only. Setting it alone does not enable enforcement. When authentication or strict mode is explicitly enabled, every Vapi webhook (including assistant selection) requires `Authorization: Bearer ...`. Configure saved Vapi server/tool credentials in a coordinated future release. Never print or put the value in source. |
| `GARAGE_VOICE_WEBHOOK_AUTH_ENABLED` | off | Explicit opt-in to webhook authentication. Leave unset/0 until saved Vapi credentials are verified. Strict mode also requires authentication. |
| `GARAGE_VOICE_STRICT_MODE` | off | Requires the webhook secret and trusted call/operation context, explicit `confirmed: true`, and matching tokens. Do not enable until all six tool schemas and the prompt are verified. |
| `GARAGE_VOICE_DEFER_CONFIRMATIONS` | off | Removes WhatsApp sending from the booking response path; requires the worker-ready flag and an internal scheduler credential, otherwise booking is rejected before a write. |
| `GARAGE_VOICE_NOTIFICATION_WORKER_READY` | off | Set only after the operator configures and verifies durable scheduled invocation and monitors pending/uncertain work. This release does not create a scheduler job. |

The worker is `POST /vapi/notifications/run`, with JSON `{"business_id":"the-garage-id"}`
and Bearer authentication using existing `INTERNAL_API_TOKEN`, falling back to
`REMINDER_CRON_SECRET`. This endpoint never permits unauthenticated execution.
It processes at most 20 pending items per call. No production invocation occurred.
It is intentionally independent of existing reminder endpoints/schedules.

## Tool mapping handoff

| Tool name | Existing API Request endpoint |
|---|---|
| `lookup_vehicle` | `/vapi/lookup-vehicle` |
| `check_availability` | `/vapi/check-availability` |
| `create_booking` | `/vapi/book-appointment` |
| `list_bookings` | `/vapi/list-bookings` |
| `cancel_appointment` | `/vapi/cancel-appointment` |
| `reschedule_appointment` | `/vapi/reschedule-appointment` |

Function tools may instead use `/vapi/tools` with Vapi's `toolCallList` envelope.
Do not repoint saved API Request tools to a Function webhook by changing only the
URL: their body/result contracts differ. Verify the deployed mappings manually.

For strict mode, authenticated call metadata must carry `call.id` and the actual
caller number; routing must carry the actual called number. These must come from
Vapi configuration/context, not fields the LLM is allowed to generate. Function
tools use the Vapi tool-call ID as operation identity. Direct API Request tools
must supply a stable `operation_id` for the same action on retries. A new action
needs a new identifier; do not reuse one action's ID for a changed request.

Availability returns `availability_token` beside the requested slot and beside
each alternative. Create echoes the selected token, plus `confirmed: true` and
optional `vehicle_token`. Listing returns a `booking_token` per booking. Cancel
echoes the chosen booking token; reschedule echoes both that token and the new
slot's availability token. The reschedule service must match the existing booking.
Tokens are opaque, signed internal data: do not speak or log them. After ten
minutes or changed details, find/check the details and reconfirm.

## Verification and measurable improvement

61 mocked backend regressions pass. Staged checks passed at 14, 28, 50 and 55
tests, then 58, before the final 61-test run. No network or database connections are allowed
by the test runner; DVLA, Calendar, WhatsApp and business lookup use synthetic
fixtures. No real bookings, messages, credentials or customer records were used.

The suite includes backend contracts for all 18 original UK garage scenarios,
including corrections, withdrawn cancellation, rescheduling without cancel/create,
slot conflicts, uncertain writes, unconfirmed/background-like input, missing
registration and UK date/DST ambiguity. It does NOT run speech recognition,
the saved LLM, live streaming, denoising, echo or acoustic interruption handling.
Those are still acceptance tests on an approved test assistant/number. Do not
describe the noise/echo cases as proven audio performance.

| Synthetic busy calendar, 09:00Ã¢â‚¬â€œ17:00, 60-minute MOT | Before | After |
|---|---:|---:|
| Free-day alternative search requests/client constructions | 4 | 1 |
| Fully busy alternative search requests/client constructions | 15 | 1 |
| Full requested-slot + busy-day alternatives | 16 | 1 |
| Calendar client constructions within create or reschedule | 2 | 1 |
| Second DVLA call with a valid signed vehicle token | 1 | 0 |
| WhatsApp calls in create response, deferred mode ready | 1 | 0 |

Counts are demonstrated with mocks/code paths; there are no measured live call
latency, TTS quality or production timing claims. The initial free requested slot
already required one calendar read and still does. Notification work is shifted,
not eliminated. Calendar pagination can require more than one page request.

## Remaining risks and pre-deployment dashboard review

- Inspect the saved master assistant's real prompt, six tool schemas/URLs/types,
  result extraction, call context variables, timeouts/retries and auth settings.
  Confirm whether it serves other garages before publishing changes.
- Authentication and strict checks are inactive without coordinated configuration.
  A compatibility deployment alone must not be described as full security hardening.
- Deterministic IDs prevent replay of the SAME operation. Different simultaneous
  operations still have a Google Calendar read-before-write race; there is no
  distributed overlap reservation or resource-capacity transaction. No database
  or locking infrastructure was added under this release's constraints. Agree
  the required concurrency policy before claiming guaranteed no double-booking.
- Legacy unmarked calendar events remain accessible under existing compatibility
  rules. Verify separate calendar mappings and business metadata, especially if
  two garages share a calendar; do not silently rewrite historical records.
- Deferred delivery needs a real verified worker and monitoring. `processing` or
  `uncertain` entries require checking provider status and the current booking
  before any operator-approved retry. Exactly-once WhatsApp delivery cannot be
  promised across separate Calendar/Twilio systems. Do not roll back code with
  pending notifications without a plan to drain/reconcile them.
- Verify numeric opening/closing-hour settings; this code does not derive working
  hours/holidays from free-text prompt instructions. Confirm service durations.
- On a test assistant, replay all 18 conversations with a real LLM and synthetic
  caller audio: quiet/soft voices, pauses, accents, workshop noise/radio,
  backchannels, speakerphone echo, and genuine overlapping correction. Measure
  speech-end Ã¢â€ â€™ endpoint Ã¢â€ â€™ LLM/tool Ã¢â€ â€™ TTS Ã¢â€ â€™ audible response, p50/p95, false
  interruptions and stopping time; ordinary mock timings are not voice latency.

## Voice and timing recommendation

Keep the current provider until its exact settings are known. First audition a
UK female voice/model within that provider. The investigation's alternative
shortlist remains ElevenLabs British female on a Vapi-supported real-time model,
and Cartesia Gemma (`en-GB`) on a supported Sonic model. These are audition
options, not a decision to switch or a verified improvement in this telephone
path. Confirm pricing, model availability and telephone-band pronunciation at
adoption; do not purchase or create accounts as part of this candidate.

Inspect start/wait/smart endpointing, stop words/voice duration/backoff,
acknowledgement handling, Soniox model/language/confidence configuration,
denoising and TTS chunking. Tune one factor at a time against the current version.
Do not import sample thresholds without checking the actual assistant. A noise
filter is not proof of speaker identification or echo cancellation. Preserve
genuine caller interruptions while testing false triggers from radio/backchannels.

## Files and rollback

The original backend scope is ten files: shared garage booking engine, Google Calendar
service, Vapi routes, new Vapi safety and notifications modules, two test modules,
the Python scenario fixture, prompt candidate and this review document.
No Staff Manager, PayChaser, Stripe, requirements or migration files changed.

The controlled release additionally includes the three reviewed v5 prompt documents:
GARAGE_VOICE_SYSTEM_PROMPT_V5.md, GARAGE_VOICE_V5_COMPARISON.md and
GARAGE_VOICE_V5_SAFEGUARD_CASES.md. The total release scope is thirteen files.
The prompt documents do not change the saved Vapi assistant automatically.

The 24 October compatibility check made webhook authentication explicitly opt-in
through GARAGE_VOICE_WEBHOOK_AUTH_ENABLED (or strict mode), so an existing secret
alone does not change the current integration. The focused suite now passes
63 tests, including two additional authentication compatibility cases. Broader
isolated regression results and any release commit SHA are recorded separately
in the release evidence; publication remains gated on actual Render verification.
Retain the base commit and existing saved assistant version as rollback references.
Before a future deployment, record the actual deployed SHA/settings and coordinate
auth/strict feature flags with saved tool changes. To roll back a future release,
restore the prior code and saved assistant/configuration together, preserving
calendar data. Added operation/notification metadata needs no schema rollback;
pending/uncertain notifications must be reconciled, never deleted blindly.
