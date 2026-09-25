# Staff Manager agency extension — local review

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

The existing shared dashboard login remains the manager authorization model;
this extension does not introduce individual manager accounts or business
membership roles. Employee routes remain tied to the business/employee session.
Direct database assignment writers must use the same serialization policy.
Distance is not routed driving distance and no reimbursement policy is inferred.
No staging database, production data or deployment configuration was changed.
