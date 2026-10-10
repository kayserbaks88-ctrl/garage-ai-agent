# Staff Manager joining and optional payroll deployment

Prepared on 11 October 2026 for `staff-v2-polish`. Deployment remains blocked
until production evidence below is recorded. No push, deploy, production
migration or production setting change was performed during preparation.

## Required production evidence

- Confirm the Render web service uses repository
  `kayserbaks88-ctrl/garage-ai-agent`, branch `staff-v2-polish`, and application
  root `ai-receptionist-engine`. A local `origin/staff-v2-polish` tracking ref
  does not establish Render's configuration.
- Identify a recent backup of the exact production database: source database,
  capture time, immutable archive checksum and successful restore verification.
  The historically recorded archive `2026-10-08T21_08Z.dir.tar.gz` has a successful
  PostgreSQL 18 restore report with unchanged employee/payroll records and SHA256
  `b51e0ac4df7fcce76da329d8b6cb84997d88921d4e3c88ca4aa870c03ef45195`.
  Its metadata names `trimtech_paychaser_db`. The filename alone does not verify
  capture time, and the available evidence does not tie the archive to the
  current independently identified production database. The original archive
  is also missing from its recorded Downloads path. This remains a blocker.
- Verify the production Staff operational v3, accounts, onboarding and billing
  schema fingerprints against the candidate code using a read-only connection.
  Production schema compatibility was not checked live in this preparation.

## Exact migration

From the deployed candidate's `ai-receptionist-engine` directory, with the
confirmed production `DATABASE_URL` already supplied by Render:

```sh
python -m trimtech.modules.staff.joining_migration
```

This is the only new migration required by these changes. Do not substitute the
general Staff migration or the older payroll migration. Do not run it at startup.

The joining entry point verifies existing schemas before and after applying its
DDL. It creates `sj_schema_migrations`, `sj_links` and `sj_registrations`, with
indexes and foreign keys, and inserts its own migration ledger record. It has
no UPDATE, DELETE, DROP, TRUNCATE or ALTER of existing business, employee or
payroll tables. Existing prerequisite migration modules are only verified;
their migration functions are not called. The transaction rolls back on failure,
uses an advisory lock, and sets 5-second lock and 60-second statement timeouts.
A repeat invocation verifies the recorded checksum and schema fingerprint.
Unversioned partial joining tables fail rather than being repaired.

Adding foreign keys can briefly acquire locks on referenced tables; a timeout
must be investigated and retried deliberately. The source review and disposable
PostgreSQL tests do not establish the live database's schema, privileges or
custom event-trigger behavior.

## Security and application scope

Manager actions require the Staff administrator cookie and active membership of
the requested business. Employee sessions and shared Garage dashboard sessions
do not authorize manager approval. Staff POST forms require CSRF validation;
trial expiry blocks manager mutations. Public registrations derive business
scope from a hashed, expiring bearer token and cannot choose role, pay or status.
Pending registrations have no employee account. Approval is tenant scoped,
atomic, prevents duplicate/replayed approvals and creates ordinary staff only.
Passwords are hashed and pending hashes are cleared after review. Rate limits
use shared PostgreSQL storage and the configured trusted proxy address.

Optional payroll setup saves company preferences, without creating tax profiles,
payroll runs or payslips. Wage estimates are read-only and clearly presented as
gross estimates. Detailed payroll still requires reviewed employee profiles.
Historical break treatment remains recorded on each break.

All implementation changes are within Staff modules, Staff templates and Staff
JavaScript. Garage Voice, PayChaser, shared routing, deployment configuration and
their existing migrations are unchanged. This establishes source scope;
production smoke checks are still required after any future approved deployment.

## Local validation

- Complete Python discovery: all 197 actual regression tests passed, with no
  skipped tests, against local PostgreSQL using unique disposable schemas.
  Four independent processes partitioned the entire discovery inventory.
  Discovery initially added one failed import for the Garage smoke script
  because Windows CP1252 cannot print its checkmark emoji. Re-running that
  script with Python `-X utf8` succeeded; no application fix was needed.
- Both JavaScript regression files passed under Node's test runner: address
  selection and employee joining.
- Garage business loading and service resolution smoke scripts passed.
- New PostgreSQL migration tests compare every existing table's full records
  before first application and repeat application, with business, employee,
  payroll and unrelated application data present. A forced DDL failure rolls
  back all new joining tables and preserves those records.
- Tenant, manager authentication, CSRF, approval/replay, trial, payroll,
  payslip, statutory calculation and template regressions passed.
- `git diff --check` passed. No live production checks or changes were performed.

## Future approved rollout

1. Resolve the backup, Render branch and live-schema evidence requirements.
2. Check Render auto-deploy behavior before pushing, so a push does not deploy
   before the intended rollout. Obtain deployment authorization.
3. Push the reviewed local commit to `origin/staff-v2-polish` only when authorized.
4. Apply the exact joining migration from that candidate revision in the
   confirmed production environment, and require its verification success.
5. Deploy the reviewed commit through Render. Confirm the deployed commit hash.
6. Smoke-test Staff manager login, tenant denial, pending registration, approval,
   employee login, payroll deferral and existing payroll. Verify Garage Voice
   and PayChaser health and their key flows.

If application rollback is necessary, redeploy the preceding application commit;
retain the additive joining tables and any newly created records. Do not drop
tables or restore over the live database without a separate recovery decision.
