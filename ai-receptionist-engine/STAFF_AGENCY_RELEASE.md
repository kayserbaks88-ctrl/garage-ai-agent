# Staff Manager agency extension — local review

For the subsequent payroll and attendance work on `staff-v2-polish`, see
`STAFF_PAYROLL_RELEASE.md`. That change requires a new versioned migration;
the historical no-migration note below applies only to the earlier polish release.

## Staff v2 polish (`staff-v2-polish`)

No database migration or service configuration change is introduced by this work.
The existing Resend transport is reused without changes to Garage/quote emails.
Assignment email is enabled by default; `STAFF_ASSIGNMENT_EMAIL_ENABLED=0`
(or another value outside `1`, `true`, `yes`, `on`) explicitly disables it.
`RESEND_API_KEY`, `RESEND_FROM_EMAIL` and a valid recipient are required.
Portal links use `STAFF_PUBLIC_BASE_URL`, falling back to Render's
`RENDER_EXTERNAL_URL`; neither is derived from a request Host header.
An explicitly configured invalid URL fails rather than silently using the fallback.
Existing failed/disabled outcomes are not automatically retried or backfilled.

A Staff-only stderr logger records attempted, sent (provider accepted), failed,
and disabled outcomes using numeric identifiers and sanitized reasons. No recipient,
message body or secret is logged. An outbox savepoint isolates notification queue
errors from assignment changes; transport is still called only after commit.
Provider acceptance does not prove inbox delivery; a separately authorized real
email test is still required after deployment.

The agency employee portal shows only that employee's current/upcoming jobs, site
address, UK window, reference, status and directions. History is collapsed below
the main tools; completed shifts are distinguished from simply expired windows.
Inactive/photo-required sites cannot offer portal clock-in. Existing server-side
assignment, GPS, photo, employee and business checks remain authoritative.

Manager assignments use separate UK start/end dates and times. End date follows
start date for same-day jobs, while an explicitly different overnight end date is
retained. Repeated autumn times require BST/GMT selection; spring gaps and offsets
that disagree with the UK date are rejected. Legacy ISO submissions still work.

Local validation on 2026-09-30: all 67 Staff tests passed with no skips against
synthetic schemas on localhost PostgreSQL. The runner rejected non-local database
targets, disabled dotenv and blocked outbound Python network connections. Tests
cover notification actions/failures, employee job isolation, photo/inactive-site
restrictions, date controls and DST, plus existing fixed/agency/payroll workflows.
Template compilation and `git diff --check` passed. No production data, real email,
commit, push or deployment was involved. Browser/device acceptance and actual
Resend inbox delivery remain separate checks after deployment approval.

Implemented against the current `trimtech/modules/staff/routes.py`, database,
payroll, WhatsApp agent and templates. Nothing has been deployed.

## Behavior

- Existing businesses remain `fixed`. The site selector, GPS radius and photo
  restrictions, breaks, leave, employee profiles, approval and payroll remain.
- Managers can enable `agency` per business, create/reassign/cancel assignments,
  review a weekly roster and create an audited override window for missing jobs.
  Assignment mutations use a PostgreSQL transaction-level business lock;
  overlapping scheduled windows are rejected, while consecutive jobs are allowed.
- Agency clock-in resolves the employee's eligible assignment on the server.
  It checks active employee/site, business ownership and the current time window.
  Windows are half-open (`start <= now < end`) and can cross UK midnight.
- Portal clocking stores coordinates, accuracy, capture time and radius result.
  Agency requires a fresh capture. Assigned name/address, planned times and site
  coordinates are snapshotted. Historical shifts remain unassigned.
- Optional employee origins require consent and are encrypted with Fernet using
  `STAFF_TRAVEL_KEY`. Managers can view a consented origin. Disabling clears the
  current origin but does not rewrite historical encrypted travel snapshots.
- Travel is a straight-line estimate, never mileage pay. Missing origins or
  coordinates yield no estimate. An address/postcode alone is not geocoded.
- Managers can correct completed shifts, sites, existing breaks and travel
  estimates with a reason. Original assignment/GPS/travel snapshots are retained.
  Corrections reset approval and flag affected draft payroll. Flagged drafts
  cannot be approved or shown as employee payslips until explicitly recalculated
  after shift review. Recalculation retains the original hourly-rate snapshots.
- Finalized payroll is immutable here: proposed corrections enter an adjustment
  queue. A manager records the external payroll adjustment reference or explains
  why no adjustment was required. This does not issue a payment automatically.
- Agency WhatsApp messages direct employees to the portal, because that path
  captures the required fresh GPS accuracy and timestamp. Fixed WhatsApp clocking
  remains available; its behavior is not replaced by the agency portal workflow.

## Local verification

Revalidated on 2026-09-25 using a fresh Python 3.12.8 environment installed from
this directory's complete requirements file and a fresh local PostgreSQL 16.15
cluster. The latest full unittest discovery passed all 26 tests in 131.694 seconds, with no
skips: six existing payroll tests, three validation tests and 17 database/route
integration tests. The initial attempt against an older local cluster failed
because its expected role did not exist; the successful run used the new cluster.

All 71 installed packages passed `uv pip check`. All 98 application/test Python
files compiled. Flask application import and the `/` health route passed with
network connections blocked and dotenv loading disabled. The business registry
smoke script and imports of the five corrected reminder/campaign modules passed.
Both working-tree and staged `git diff --check` passed. Gunicorn execution on
Render's Linux runtime remains a staging check; it cannot be validated on Windows.

### Follow-up review and expanded local validation (2026-09-25)

Reviewed all eleven release-preparation items, distinguishing them from the
already-present agency extension. No unnecessary Staff Manager business-rule
change was found in these preparation edits:

| Item | Review result |
| --- | --- |
| `.gitignore` | Excludes local tooling, environments and backups only. |
| Canonical `requirements.txt` | Deduplication retains existing effective OpenAI/HTTPX/Twilio pins; cryptography supports the extension; Gunicorn pin affects deployment and still needs a staging boot. |
| `.python-version` | Makes the existing Python 3.12.8 target explicit. |
| `runtime.txt` | Matching legacy pin; no runtime version change. |
| `integrations/campaigns.py` | Only malformed import tokens and final newline corrected. |
| `integrations/customer_care.py` | Same import-only repair. |
| `integrations/review_request.py` | Same import-only repair. |
| `integrations/vehicle_remiders.py` | Same import-only repair. |
| `trimtech/integrations/mot_reminders.py` | Same import-only repair. |
| This release runbook | Documentation only. |
| Git index cleanup | 5,872 virtual-environment files and two ZIPs untracked; local copies verified present. |

An AST comparison confirms that each repaired module is identical to HEAD once
the invalid duplicated import tokens are corrected. Existing extension behavior
such as mandatory correction reasons, draft recalculation and explicit schema
migration predates these release-preparation edits; this review does not imply
the entire agency extension has no intentional effect on fixed-company workflows.

The expanded restore check found a real verification defect: PostgreSQL's
dump/restore reparses varchar-list casts into equivalent per-element text casts,
changing the SQL returned by `pg_get_constraintdef` and index decompilation.
The only application change in this follow-up is a narrow normalization in
`migrations.py` for that equivalent form. It preserves original fingerprints,
migration SQL/checksum, database constraints and business rules. See PostgreSQL's
[decompilation documentation](https://www.postgresql.org/docs/17/functions-info.html).
The existing migration test now reproduces constraint/index reparse and verifies
that changed allowed values, changed index predicates and added columns still
fail drift checks. The suite remains 26 tests, all passing after the fix.

Additional checks passed:

- Linux x86_64/Python 3.12.8 binary-wheel dependency resolution (dry run); all 71
  installed Windows packages remain compatible. This is not Linux execution.
- Real localhost HTTP request through a WSGI validator, application import,
  authenticated Staff dashboard, all 18 Jinja templates and missing-secret
  startup rejection. External Python network access was blocked.
- Migration CLI run twice on synthetic legacy data; all original fields and
  row counts preserved, historical shifts unassigned, no orphan shifts, and an
  unrelated-table sentinel unchanged. No production or PayChaser data was used.
- Custom-format migrated backup restored into a separate local database with
  identical table rows and valid migration fingerprint. Pre-migration backup
  restored into another database with identical legacy rows.
- Unmigrated schema verification rejects startup without modifying data; a
  deliberately conflicting migration rolls back all partial changes.
- Previous committed Staff modules and templates run against the migrated
  restored schema: dashboards, fixed clocking, breaks, leave approval, shift
  approval and payroll generation pass, with the fingerprint preserved. This
  covers fixed synthetic data, not rollback after a live agency rollout.
- Python compilation and both staged/unstaged whitespace checks pass.

Actual Gunicorn `--check-config` cannot run here: Windows lacks `fcntl`, WSL is
not installed, and Docker is unavailable. The WSGI check does not prove Gunicorn
worker fork/restart, Render proxy/TLS behavior or Linux binary loading. Those
remain staging requirements. Local evidence is retained in the ignored
`.release-validation/` directory, including `full-suite-rerun.log`,
`extended-results.json`, scripts and synthetic backup files. The local database
server was stopped after validation. No commit, push, deployment or Render
production database access was performed.

The broad compilation check found and corrected pre-existing duplicated
`from`/`import` tokens in `integrations/campaigns.py`, `customer_care.py`,
`review_request.py`, `vehicle_remiders.py` and `trimtech/integrations/mot_reminders.py`.
These changes only restore valid imports of the existing reminder sender.

Use Python 3.12 with Flask, psycopg2-binary, cryptography, tzdata and the project's
OpenAI SDK dependency (WhatsApp tests disable API calls). From this
directory, point `STAFF_TEST_DATABASE_URL` at a disposable PostgreSQL database:

```powershell
$env:STAFF_TEST_DATABASE_URL = 'postgresql://TEST_USER@127.0.0.1:TEST_PORT/postgres'
$env:PYTHON_DOTENV_DISABLED = '1'
$env:DATABASE_URL = $env:STAFF_TEST_DATABASE_URL
$env:OPENAI_API_KEY = ''
python -m unittest discover -s . -p 'test_*.py' -v
```

The tests use randomly named `staff_test_*` schemas, seed the old schema and old
shifts, apply the migration, exercise real HTTP routes and SQL, and remove only
their own schemas. They do not read `DATABASE_URL` or contact production.

Coverage includes fixed clock-in/out, breaks, leave approval/rejection/cancellation,
profile editing, bulk approval, payroll, two agency employees at different sites,
consecutive jobs, concurrent overlap rejection, reassignment, cancellation,
missing assignments, wrong-site/poor/stale/missing GPS, photo restrictions,
CSRF, unauthorized employee requests, cross-business IDs, encrypted consented
origins, immutable estimates, manager corrections, audit, draft recalculation,
finalized adjustment resolution, UK clock changes, repeatable migration and drift.
The fixed WhatsApp clock/break flow and the agency portal handoff are covered too.

## Before any deployment

1. Confirm the currently deployed code matches this checkout and take a database
   backup. No deployed-repository comparison has been performed in this session.
2. Restore a production backup into staging. The local tests use a representative
   legacy fixture; they are not a restored production/staging copy.
3. Install the updated `requirements.txt` from this directory. Provision a separate
   Fernet key in the service's secret store as `STAFF_TRAVEL_KEY`. Keep that key
   backed up for historical snapshots. Never commit it or substitute the session
   signing secret. Losing/changing it makes existing origins unavailable.
4. Point `DATABASE_URL` at staging and run:

   ```text
   python -m trimtech.modules.staff.migrations
   ```

   This runs the versioned migration transactionally, records a checksum and
   schema fingerprint, defaults old businesses to fixed and leaves old shifts
   unassigned. Re-running verifies the recorded migration. Application startup
   only verifies; it does not apply the extension or repair drift.
5. Review the staging data and run the flows with real manager/employee accounts.
   Verify browser location permission, denied permission and physical GPS on the
   devices actually used. Flask route tests do not prove device GPS behavior or
   visual browser layout. Photo-required portal clocking remains unavailable.
6. After deployment is separately authorized, migrate the production database
   before starting this application version. Keep businesses fixed, then opt
   selected businesses into agency only after their roster and site data are ready.

## Render deployment contract

The deployable Flask application is this directory's `app.py`. Configure the
Render web service with this directory as its root directory so the following
settings are unambiguous:

- Root directory: `ai-receptionist-engine`
- Runtime: Python `3.12.8` (recorded in this directory's `.python-version`;
  `runtime.txt` retains the matching legacy pin)
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Migration command: a separately authorized one-off command using the same
  release image and `DATABASE_URL`; application startup must not run it

`ai-receptionist-engine/requirements.txt` is the canonical web-service dependency
file. The repository-root `requirements.txt` belongs to the older root-level
application surface and must not be used for this Flask service. Do not merge the
two files or install both as an implicit workaround. Confirm the Render service's
root directory and commands in the dashboard before release.

Render's documented runtime selectors are `PYTHON_VERSION` (highest precedence)
and `.python-version`: https://render.com/docs/python-version. Verify that any
service-level `PYTHON_VERSION` is `3.12.8` and confirm the actual interpreter in
the staging build log. Do not rely on `runtime.txt` alone.

Repository preparation removes the accidentally tracked `.venv311` environment
and two handoff ZIP archives from the Git index only; local copies are preserved.
Ignore rules now exclude these files, virtual environments, release-validation
output and database dump/backup files. The dependency file has one entry per
package, preserving OpenAI `1.84.0`, HTTPX `0.28.1` and Twilio `9.2.3`, and pins
Gunicorn to `22.0.0` to match the existing root application requirement.

Required existing secrets must remain available, including `DATABASE_URL` and
`FLASK_SECRET_KEY`. Add `STAFF_TRAVEL_KEY` as a separately generated persistent
Fernet key. Never use or rotate it casually after encrypted employee origins exist.

## Backup and rollback runbook

Before each staging or production migration:

1. Record the release commit, Render service, database identifier, migration
  version and current row-count report.
2. Take a provider-native PostgreSQL backup and wait for it to show a successful,
  restorable state. Do not treat an application export or local copy as the
  production backup.
3. Restore the backup into a new database or staging instance. Validate the
  connection target, schema, Staff Manager counts, PayChaser counts and orphan
  checks before any migration.

The migration is transactional and has no down-migration. If the application
release fails after a successful migration, stop the new web release and revert
to the previous application commit only after confirming that the previous code
can tolerate the additive schema. Do not manually drop agency tables or columns.

If database rollback is required, keep production stopped or in maintenance mode,
restore the verified backup into a separate provider-managed database, rerun the
validation report there, and use the provider's approved database replacement or
connection-switch procedure. Repointing `DATABASE_URL` is a controlled production
change and requires explicit approval. Preserve the original database until the
rollback is verified; do not overwrite it during investigation.

After either rollback path, verify fixed-company clocking, breaks, leave, payroll,
WhatsApp behavior and application startup before reopening traffic. Keep the
backup identifier, restore identifier, release commit, migration checksum and
`STAFF_TRAVEL_KEY` record together.

The local rollback rehearsal on 2026-09-25 passed: a custom-format backup of the
migrated local database restored into a new database and retained Staff Manager,
PayChaser and migration records. This does not validate Render's provider-native
restore or connection-switch operation; that procedure still requires staging or
Render-console confirmation.

## Remaining release checks

Local preparation is complete. The local release commit containing this runbook
captures the agency extension, tests, runtime pins and repository cleanup.
Production is NOT approved or ready yet. The final eight-file validation review
covered the five import-only repairs, migration fingerprint normalization,
regression tests and this runbook; no further Staff Manager behavior changes were
made during release commit preparation. The latest suite result remains 26 passed,
zero failures/errors/skips. No push, deployment or production access is authorized.

### Staging availability and next step

Repository inspection found no staging deployment manifest, staging branch,
staging service/database identifier or documented usable staging target. Only
`main` and the locally recorded `origin/main` branch exist. Local disposable
PostgreSQL fixtures are not a usable hosted staging environment. No remote
service inventory was queried, so an independently configured external staging
service has not been ruled out or verified.

STOP before deployment or migration. The next step is to identify and verify an
existing isolated staging web service and PostgreSQL database, or obtain separate
authorization to provision them. Do not use production as a substitute and do not
push `main` as a staging test: its deployment automation has not been verified.

Once that separate environment and deployment authorization exist, test this exact
release commit with service root `ai-receptionist-engine`, Python `3.12.8`, build
`pip install -r requirements.txt` and start `gunicorn app:app`. Use staging-only
`DATABASE_URL`, session/travel secrets and test integration credentials; prevent
outbound messages and bookings from reaching real customers. Populate staging
with synthetic fixtures or an independently authorized sanitized backup restore.
Verify the database target explicitly before running
`python -m trimtech.modules.staff.migrations` there, repeat it to verify stability,
then complete the staging and phone acceptance checks below. Obtaining or
restoring production data is not authorized by this local release-commit task.

Before declaring production ready, record evidence for all of the following:

- Actual Render service root, build/start commands, Python version and deployed
  commit comparison; successful Linux build and Gunicorn startup in staging.
- Verified provider backup and isolated staging restore, pre/post migration row
  counts and orphan checks, including Staff Manager and PayChaser; migration
  repeatability and provider rollback/connection-switch rehearsal.
- Persistent staging/production secret configuration, including the separately
  backed-up `STAFF_TRAVEL_KEY`, without copying staging connection settings into
  production or changing production during validation.
- Real manager/employee acceptance of fixed and agency flows, payroll corrections
  and adjustments, browser layout and the physical-device GPS cases below.
- Separate explicit production migration/deployment authorization after these
  gates pass. Keep existing businesses fixed until their agency pilot is ready.

The previously reported local restore rehearsal and test suite do not replace a staging
restore or physical-device verification. Before production approval, staging must
be tested with real manager and employee accounts for location permission granted,
permission denied, stale capture, poor accuracy, wrong site and physical GPS.
Photo-required portal clocking remains an explicitly unsupported path in this
release and must not be presented as available.

## Boundaries

### Assignment email and site presence (staging branch)

New migration: `20260928_staff_operations_v2`, following the unchanged
`20260923_agency_v1` SQL/checksum. The same migration CLI applies both versions:
`python -m trimtech.modules.staff.migrations`, from `ai-receptionist-engine`.
It verifies the original recorded fingerprint before upgrading an existing v1
database and records a new checksum/fingerprint. Startup verifies the latest
version and never applies changes. Existing organisation modes and records remain.

Schema additions only:

- `staff_assignment_notifications`: assignment/employee/business, unique event
  key, action, recipient and snapshotted email details, pending/sent/failed/disabled
  status, provider ID, sanitized error code, creation/attempt timestamps; pending
  queue index. Foreign keys restrict deletion of referenced assignments/employees.
- `staff_shift_presence`: one row per shift, business/employee, immutable target
  coordinates/radius copied from shift evidence (legacy shifts fall back to the
  site on first observation), current status, last capture/receipt, outside count
  and start time, departure flag and update timestamp; business index.
- `staff_presence_events`: append-only application evidence with shift/business/
  employee, status, capture/record/effective timestamps, distance, accuracy and
  reason; shift history index. No employee location coordinates are stored here.

Do not run this migration on production as part of this change. Use the existing
backup and target-verification procedure before any separately authorized staging
migration. Local tests use random schemas in a localhost synthetic database only.

Email reuses Resend (`integrations/email_helper.py`). Configure staging secrets:

- `STAFF_ASSIGNMENT_EMAIL_ENABLED=1` (otherwise outcomes are recorded as disabled).
- `RESEND_API_KEY` and `RESEND_FROM_EMAIL` with a verified sender.
- `STAFF_PUBLIC_BASE_URL=https://YOUR-STAGING-HOST` for employee portal links.

Notifications are queued in the assignment transaction and attempted after commit.
Creation, update and cancellation notify the employee; reassignment also notifies
the previous employee that they are no longer scheduled. Dates and times include
UK BST/GMT labels. The email contains the full address and optional client reference.
No password or login token is included in the portal link.

Provider failures do not roll back assignments. The assignments page shows recent
email outcomes. `sent` means Resend accepted the email, not confirmed delivery;
missing employee email, disabled configuration and failures remain recorded.
There is no delivery webhook or automatic failed-message retry in this release.
Pending records left by a process interruption are attempted on the next action
for the same assignment; investigate pending/failed records before any manual
resend. Each queued event uses a Resend idempotency key. Provider idempotency has a
limited retention window, so do not blindly retry old ambiguous attempts.

Employees opt into presence updates using **Start presence updates** while clocked
in, and can stop them. The visible portal requests a new GPS sample about every
30 seconds; hidden/locked browsers may suspend it. This is not guaranteed continuous
background tracking. Clock-in/out GPS validation is unchanged. Presence never changes
hours, breaks, leave, approval, payroll or existing shift evidence.

Defaults (bounded environment overrides):

- `STAFF_PRESENCE_GRACE_SECONDS=60` (0–3600).
- `STAFF_PRESENCE_CONFIRMATIONS=3` (2–10).
- `STAFF_PRESENCE_STALE_SECONDS=120` (60–3600).

A departure requires consecutive fresh readings outside the radius plus reported
accuracy, satisfying both count and elapsed grace. Readings must be timestamped
within 60 seconds (at most 10 seconds ahead), accurate within the smaller of 100m
and the radius, newer than the previous capture and at least 10 seconds apart by
server receipt. Returning inside the radius records `returned`. Uncertain boundary
readings reset pending departure confirmation. Long gaps reset confirmation too.

The manager dashboard polls every 30 seconds. Stale transitions are recorded when
the dashboard reads/polls presence or a new sample arrives, with the effective
expiry timestamp stored separately from observation time. No always-running
tracking worker is deployed. An unobserved shift starts as `location_stale`.
Presence events remain when shifts are approved or included in payroll.

Before staging acceptance, test real-device permission denial, drift, departure,
return, screen lock/background pause and network loss. Use controlled test email
recipients to verify accepted messages actually arrive. Unit/integration email
tests mock delivery and never contact employees.

Local validation on 2026-09-28: all 54 Staff tests passed with no skips in
179.750 seconds, using isolated schemas on the existing localhost synthetic
PostgreSQL cluster. This includes v1-to-v2 upgrade preservation/repeatability,
drift rejection, all notification actions and nonblocking delivery failure,
presence departure/return/staleness, replay/accuracy/access checks and retained
events through shift approval/payroll inclusion. Python and Jinja compilation,
JavaScript syntax/foreground lifecycle checks and `git diff --check` passed.
No staging/production migration, real email, push or deployment was performed.

### Staging UK work-site address search

The manager site forms (add, edit and inline assignment site creation) use Ideal
Postcodes through an authenticated, CSRF-protected server endpoint. No schema
change is required. Configure **only the staging service**, without deploying
production:

- `STAFF_ADDRESS_LOOKUP_ENVIRONMENT=staging`
- `STAFF_IDEAL_POSTCODES_API_KEY`: the staging Ideal Postcodes key, stored as a
  server secret. Never place it in JavaScript, templates or committed files.

Without both settings, provider requests are disabled and manual entry remains
available. The server uses UK (`GBR`) autocomplete and resolves only the chosen
address. Resolving an address consumes provider lookup credit; provision a funded
staging key with provider-side usage/budget limits. No account or credit purchase
is performed by this code change. The per-worker application throttle is 60
requests per business per minute; provider limits should cover the whole account.

Typed search text and the selected address identifier are sent to Ideal Postcodes
by the server. Requests time out and errors are sanitized; secrets and provider
error bodies are never returned to the browser. Search responses use `no-store`.

Selecting a result fills the full address only. Provider coordinates are discarded.
The manager must capture GPS at the site or explicitly confirm that the entered
coordinates identify the selected site before saving. GPS accuracy/radius checks
and existing organisation modes remain unchanged.

Staging acceptance: search a full postcode, partial street with town, and a known
building/site name; select a result and confirm the complete postcode is filled.
Check that coordinates do not change and saving requires coordinate review.
Check no matches, exhausted/invalid provider key and network failures allow manual
entry. Test both Add Work Site and the assignment's inline new-site form.

Provider contracts:
https://docs.ideal-postcodes.co.uk/docs/api/find-address/ and
https://docs.ideal-postcodes.co.uk/docs/api/resolve-address/.

The existing shared dashboard login remains the manager authorization model;
this extension does not introduce individual manager accounts or business
membership roles. Employee routes remain tied to the business/employee session.
Direct database assignment writers must use the same serialization policy.
Distance is not routed driving distance and no reimbursement policy is inferred.
No staging database, production data or deployment configuration was changed.
