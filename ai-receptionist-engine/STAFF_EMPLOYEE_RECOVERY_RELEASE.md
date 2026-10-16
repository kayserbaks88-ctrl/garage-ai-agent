# Employee password recovery release

Base: fd888e0c4a6b3bdada558673692b5bf6e934a2ab on staff-v2-polish,
matching the operator-supplied deployed baseline. Render auto-deploy remains Off.

Employee sign-in now links to tenant-specific recovery. The request takes the
recorded email and phone and gives the same acknowledgement for unknown,
inactive, ambiguous, unactivated and rate-limited accounts. A bounded worker
performs lookup and sending after the HTTP response path has queued the request;
provider latency and account eligibility do not determine the public response.
The queue is process-local and best effort. Delivery failure, saturation or a
worker restart may require another request; acknowledgement is not proof of inbox delivery.

Only an active employee with existing credentials in an active business can
receive a reset. Tokens expire after one hour, are stored hashed in the existing
employee invitation table, and use a separate hash namespace from invitations
and administrator tokens. Token IDs bind them to the current credential version,
so a later password change invalidates earlier links. Consumption locks business,
employee, credential and token state, rechecks tenant/current email/expiry,
updates existing credentials only, rotates their version and revokes outstanding
employee links. It never provisions access or approves a joining request.

Success uses a 303 redirect to a confirmation page with employee sign-in.
Replay/expiry offers sign-in or another email; password validation preserves
the hidden token for retry. Existing CSRF, shared identity/IP rate limits,
no-store headers, mobile password handling and duplicate-submit protection apply.
Only the target tenant's employee authentication is cleared from the current
session. Administrator recovery, sessions and cookie are unchanged.

Validation: 35 Python tests passed with database/network connections blocked,
plus both existing JavaScript suites and 12 browser/device cases. PostgreSQL and
email calls were mocked; no migration or live email was executed. Mobile pages
were checked at 360px and desktop at 1280px, including hidden token submission,
CSRF, duplicate events, restored-page controls and horizontal overflow.
Guarded app:app startup made zero database/network connections and started no
background threads. The normal Garage type configuration and validation remained
enabled in the isolated startup harness. Startup has no new DDL or writes.

No migration, new dependency or new environment setting is required. Existing
RESEND_API_KEY, RESEND_FROM_EMAIL and STAFF_PUBLIC_BASE_URL (or the existing
RENDER_EXTERNAL_URL fallback) are reused without modification. Production values
and inbox delivery were not independently inspected. Real iPhone Safari password
save behaviour and actual email delivery remain post-deployment smoke checks.
No PayChaser, Garage Voice, administrator recovery or billing runtime code changed.
Unrelated marketing working-tree changes are excluded.

Manual deployment, after approval: on the existing garage-voice-agent service,
use Deploys > Manual Deploy > Deploy a specific commit, paste this release's full
Git SHA and select Deploy Commit. Preserve the existing root, build, start and
empty pre-deploy commands; run no migrations or configuration changes. Keep
STAFF_STRIPE_ENABLED=0. Verify the selected SHA and healthy startup, then test an
approved employee email/reset/sign-in and the existing administrator login.
