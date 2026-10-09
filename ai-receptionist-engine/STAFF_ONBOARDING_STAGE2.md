# Staff Manager Stage 2: trials and guided setup

This is a local implementation on `staff-v2-polish`. Public registration remains
disabled by default (`STAFF_REGISTRATION_ENABLED=0`). Do not enable it until the
complete onboarding and Stage 3 billing flow have been tested and approved.
No Stripe integration, HMRC submission, production migration or deployment is part
of this stage. This document supersedes the Stage 1 report's historical statement
that Stage 2 has not begun; its owner-provisioning and proxy prerequisites remain.

## Behaviour

- Registration creates a pending trial and setup record in the same transaction
  as the isolated business and administrator. Verification starts the trial for
  exactly 336 hours, using the database clock. No payment card is requested.
- A permanent unique claim for the normalised administrator email prevents a
  second trial for that identity. Verification retries, password resets and
  duplicate registrations cannot renew a trial. Changing email identities can
  still evade this basic protection; this is not business identity verification.
- The manager dashboard displays remaining days and the end time. Trial dates
  cannot be supplied or changed through a public form.
- Expiry is checked on requests; no scheduled cleanup deletes records. Manager
  writes and new employee work/leave/travel changes are blocked. Reads, payslip
  downloads and sign-out remain available. Employees can end an existing break,
  submit evidence for an open shift and clock out with the unchanged GPS rules.
  Expiry does not approve hours, reduce pay, finalise payroll or send payslips.
- The subscription information page explains expiry and that online subscriptions
  are not yet available. It cannot take a payment or grant paid access.
- Existing businesses without a trial record retain their existing access and
  login behaviour. They are not silently enrolled in a trial. Before launch,
  reconcile any privately registered Stage 1 accounts and decide their policy;
  no automatic backfill or existing-account conversion is performed here.

## Guided setup

Seven saved steps cover company details, sites/GPS, employees, invitations,
assignments/rotas, payroll profiles and final review. Company details are stored
in the new business/setup records. Other steps open the existing Staff tools;
they do not duplicate scheduling, payroll or employee storage. Those tools link
back to setup. Progress saves on a valid step submission and resumes at the next
step; unsaved form text is not persisted automatically.

Completion is derived from saved records as well as the manager's acknowledgement:
active sites need an address and GPS coordinates; employees must be active;
invitations need activated credentials for all active employees; agency mode
needs a scheduled assignment (fixed mode may schedule later); payroll needs a
reviewed profile for every active employee. Final review requires every earlier
step. Removing a prerequisite makes the corresponding checklist item incomplete.
No payroll defaults are inferred, no run is created and no payroll is approved.

Address autocomplete reuses the existing lookup configuration and manual entry
fallback. Payroll guidance states that HMRC/RTI submissions are not automated.

## Employee invitations and access

- Existing Resend transport; 48-hour random, hashed, single-use invitation tokens.
  Email links carry tokens in fragments, not query strings. GET does not consume
  an invitation; acceptance requires a CSRF-protected POST and a 12–128 character
  password. Opening the email never activates access by itself.
- Employee ID, business, active state and current email are checked together.
  Resending revokes older unused invitations. Accepting a replacement rotates
  the credential version and invalidates older employee sessions.
- New trial businesses use employee phone plus the chosen password, not payroll
  number. Password whitespace is preserved. Shared database rate limits use the
  Stage 1 trusted-proxy resolver. Invalid proxy configuration fails closed.
- Provider acceptance is displayed separately from confirmed inbox delivery.
  Failed sends preserve the employee and can be retried. Logs contain the
  invitation ID and outcome, not the raw token, password, email or provider error.
- New trial businesses are directed from the Staff WhatsApp handler to the secure
  portal, preventing a phone-only path from bypassing authentication or expiry.
  Legacy fixed/agency WhatsApp behaviour is unchanged.
- Password recovery for invited employees is a new invitation from their manager.
  Legacy payroll-number access remains an existing security limitation, unchanged
  for grandfathered businesses; a separate approved transition is still needed.

## Database migration and release prerequisites

New explicit migration: `20261008_staff_onboarding_v1`, implemented in
`trimtech.modules.staff.onboarding_migration`. It creates only:

- `so_trials`, `so_trial_claims`, `so_setup`
- `so_employee_credentials`, `so_employee_invites`
- `so_schema_migrations`

It requires the existing Staff migrations and Stage 1 identity migration. It uses
the shared migration advisory transaction lock, verifies existing fingerprints,
records its checksum/fingerprint transactionally and is repeatable. It does not
alter `staff_*`, `sm_*`, Garage Voice or PayChaser tables. Foreign keys reference
existing employees and identities and prevent their deletion while referenced.
There is no automatic migration at startup, and no destructive down migration.
`payroll_migration.py` matches Git HEAD exactly; do not edit its already-deployed
v3 SQL/checksum to support onboarding.

After separate approval and backup/pre-flight, the explicit application-root
command would be `python -m trimtech.modules.staff.onboarding_migration` in the
approved database environment. It has NOT been run against production. Deploying
Stage 2 requires its schema first; the application does not fall back around a
missing migration. If Stage 1 is not deployed, its identity migration and owner
provisioning must also be approved and completed in order.

Before any public launch:

1. Resolve the Stage 1 production owner-provisioning/cutover plan and confirmed
   Render inbound trusted-proxy ranges. Never trust arbitrary forwarded headers.
2. Approve backup, schema pre-flight, migrations and deployment separately.
3. Keep registration closed; test actual Resend delivery, invitation links, UK
   address lookup, and mobile Safari/PWA navigation under the real HTTPS domain.
4. Complete and test Stage 3 billing, subscription synchronisation and expiry
   recovery before considering public registration. No billing is implemented now.

Application rollback does not remove this additive schema. If rolling back to
Stage 1 or earlier, keep public registration closed and account for the absence
of trial enforcement and invited-employee password support in that code. Do not
silently downgrade new employees to payroll-number login. Preserve records made
after release; a database restore is a separate recovery decision.

## Local verification

Stage 2 files added or updated (relative to `ai-receptionist-engine/`):

| Area | Files |
| --- | --- |
| Trial/setup/invitations | `trimtech/modules/staff/onboarding.py`, `onboarding_migration.py`, `onboarding_routes.py`, `employee_invitations.py` (all in that module directory) |
| Existing authentication and routes | `trimtech/modules/staff/accounts.py`, `manager_auth.py`, `routes.py`, `agent.py` (all in that module directory) |
| Templates | `templates/staff_account.html`, `staff_agency.html`, `staff_base.html`, `staff_dashboard.html`, `staff_employee_access.html`, `staff_employee_login.html`, `staff_setup.html`, `staff_subscription.html` (all in `templates/`) |
| Tests | `test_staff_accounts.py`, `test_staff_onboarding.py`, `test_staff_agency.py`, `test_staff_address_lookup.py` |
| Report | `STAFF_ONBOARDING_STAGE2.md` |

Other uncommitted files are retained Stage 1 work: `STAFF_ACCOUNTS_STAGE1.md`,
`static/staff_account.js`, `test_staff_mobile_payroll.py`,
`test_staff_provision_proxy.py`, and Staff modules `accounts_migration.py`,
`agency_routes.py`, `provision_owners.py`, `trusted_proxy.py`. They have not been
discarded or committed. There are no Garage Voice, PayChaser, environment-secret
or payroll-migration edits in this change set.

The guarded runner `.release-validation/run_polish.py` uses Python 3.12, only
PostgreSQL at `127.0.0.1:55449`, disposable UUID schemas and blocked outbound
Python network connections. Dotenv loading is disabled, email credentials are
cleared and notification providers are mocked. Do not run these tests against
production or substitute a production URL.

Focused account suite: 15 passed. Focused new Stage 2 suite: 11 passed after fixing
an expiry response that used unsupported `abort(402)`. The replacement returns a
proper HTTP 402 employee page with safe portal navigation. PostgreSQL errors deliberately raised by
rollback tests and simulated failed notifications are expected only when the
associated test finishes `ok`; final unittest totals determine success.

Windows PowerShell may label redirected unittest progress as `NativeCommandError`
because unittest writes progress to stderr. That wrapper does not establish a
test failure. Deliberate notification logs include `notification_queue_failed`,
`message_or_delivery_failed`, `employee_email_missing_or_invalid`, and interrupted
payslip queue processing. Their associated tests must pass, and the runner must
finish with `OK` and exit code 0. The unmodified pytest/unittest failure sections,
not console colour, determine whether work remains.

Final full regression run, 8 October 2026:

- `python -X utf8 -B .release-validation/run_polish.py 'test*.py'`
  using `.release-validation/venv/Scripts/python.exe`: **153 passed, 0 failures,
  0 errors, 0 skips**, 646.841 seconds, exit code 0.
- Includes the 15 account tests and 11 additional Stage 2 tests, plus existing
  tenant isolation, provisioning/proxy, GPS, fixed/agency, attendance, leave,
  payroll calculations, payslip issuing/download and rota regressions.
- Identity and onboarding migration failure/rollback tests passed. Repeated
  migration verification preserved the existing operational and identity schema
  fingerprints. These are local disposable-schema results, not production checks.
- Both legacy registry smoke scripts passed separately; all four Garage service
  lookups resolved with PostgreSQL, SQLite and outbound network access blocked.
- `git diff --check` passed. No real email or browser/device delivery test was run.
- Full output is retained locally in `.release-validation/stage2-regression.log`.

Stage 2 is ready for local review/approval. Public launch remains blocked pending
the prerequisites above and separately approved Stage 3 work. Nothing was
committed, pushed, deployed or run against production.
