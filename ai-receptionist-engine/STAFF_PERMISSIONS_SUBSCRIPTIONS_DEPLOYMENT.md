# Staff permissions and subscriptions deployment readiness — 17 October 2026

Status: **Release preparation/push authorized; deployment remains operator-controlled
and pending production evidence.**
The operator has authorized committing and pushing the Staff-only release to
`staff-permissions-subscriptions-release-20261017`. Render deployment and production
settings changes remain outside this authorization. The existing production-linked
branch is not advanced by this release push. Record the resulting full commit SHA
from the release handoff; deploy that exact SHA only after production checks.
Read alongside STAFF_PERMISSIONS_SUBSCRIPTIONS_REVIEW.md, including its rollback caveat.

Operator update: both PLATFORM_ADMIN_USERNAME and PLATFORM_ADMIN_PASSWORD already
exist in Render. Preserve them exactly; do not create, replace or rotate them.
Their presence is operator-confirmed; effective runtime settings and production
commit/database state remain unverified from this VS Code session.

Current validation: 65 focused tests passed, zero failures/errors/skips, using the
existing disposable loopback PostgreSQL cluster. Dotenv was disabled, database
connections restricted to that cluster, outbound Python socket connections blocked,
and provider operations mocked. Suites: accounts, billing, onboarding, platform
polish and subscription management. `git diff --check` passed. These tests do not
establish production account state or production configuration.

## Verified from the candidate

- Dedicated platform access requires both PLATFORM_ADMIN_USERNAME (nonblank after trimming) and PLATFORM_ADMIN_PASSWORD (nonempty), plus a platform-role session whose username matches. Sign in through `/platform/login?next=/staff/platform/businesses` in a fresh browser session or after `/platform/logout`; an existing flag-only session must reauthenticate.
- These variables are read by the **shared TrimTech platform login**. They replace its dashboard-credential fallback for platform sign-in across that application. They are not Staff-specific credential names. Dashboard login still reads DASHBOARD_USERNAME/PASSWORD. Customer login and Staff owner password hashes are independent. Do not promise that platform operators can keep using dashboard credentials at `/platform/login`.
- Reading the existing two variables does not update accounts, memberships, business records, Garage Voice settings or PayChaser settings. Preserve their existing configuration. A shared-service deployment/restart still warrants smoke checks.
- Staff owner authentication and membership checks remain database-backed. Customer sign-in clears stale platform session identity, not the owner account. Existing active, verified owners of active businesses retain access; this is conditional on actual production rows. Oakfield's production status and successful owner sign-in have NOT been verified.
- STAFF_STRIPE_ENABLED must remain the string `0`. No production flag was inspected or changed. Disabled billing prevents provider operations, including webhook processing (503); it does not prove that no real subscriptions exist or stop existing provider charges.
- Owner lifecycle routes require owner membership, CSRF, reason and typed exact business ID. The transaction rechecks ownership and locks the selected business. Platform actions require the dedicated platform identity. Updates, audit history and cancellation-request review are scoped by business ID; a request audit ID from another business is rejected. Authorized platform administrators can deliberately select any business: confirmation mitigates selection mistakes but cannot prove human intent.
- End-trial and deactivation reject recorded ongoing subscriptions and unresolved checkout intents. Deactivation also rejects open shifts. Checkout locking serializes against deactivation. Local cancellation requests and reviews never confirm provider cancellation or stop charges. Current provider state must be reconciled before lifecycle use if local records may be stale or incomplete.
- No new dependencies, schema changes, migration commands or backfills are required for this delta. Existing operational, identity, onboarding and billing schemas must already verify. Missing schema or missing owner membership is a separate prerequisite, not permission to migrate or provision users during deployment.

## Required production evidence before release approval

1. Authenticate to Render and confirm the service identity (retained notes name `garage-voice-agent`), repository, branch (`staff-v2-polish` in retained notes), root, build/start/pre-deploy commands, auto-deploy policy, current successful SHA, database mapping and recoverable backup. Retained notes are not current evidence. Do not reuse historical rollback SHAs blindly.
2. Privately inspect effective environment settings, including linked groups and overrides. Confirm both dedicated credentials and STAFF_STRIPE_ENABLED=0. Do not print secrets. Check existing platform operators understand the new credentials.
3. Use authenticated independent Render database identity evidence before a read-only production connection. Verify all four existing schema ledgers against candidate code. `staff_production_readonly_check.py` performs read-only schema/ownership inventory but does not independently prove database identity; use it only after confirming the target. The existing `.release-validation/STAFF_READONLY_ACCESS.md` documents the independently guarded preflight.
4. Confirm Oakfield's exact business ID, active business, active owner membership, active verified administrator and an owner-controlled successful login. Repeat for existing business owners. Do not infer ownership from a business name, reset passwords, create memberships, start trials or backfill data to make checks pass. A login creates an ordinary session; coordinate owner testing separately from read-only SQL checks.
5. Reconcile actual ongoing Staff subscriptions/checkouts against the provider through an authorized billing operator before exposing lifecycle use. Disabled billing cannot refresh stale records. Billing activation/tax setup is outside this release.
6. Prepare a Staff-only release diff including the new subscription module, admin template and tests. Exclude unrelated marketing edits and staff-stripe-corrections.ps1. Release parent is d8f769d5700ca6f2494db88e3d00fc72f7ffdc1d; this is not independent evidence of the production SHA.

## Render settings and deployment sequence — after separate authorization

| Setting | Required value/action |
| --- | --- |
| PLATFORM_ADMIN_USERNAME | Preserve existing value; code trims username and requires it to be nonblank |
| PLATFORM_ADMIN_PASSWORD | Preserve existing secret; code requires a nonempty value |
| STAFF_STRIPE_ENABLED | `0`, unchanged |
| DASHBOARD_USERNAME / DASHBOARD_PASSWORD | Preserve existing values |
| DATABASE_URL, session secret, proxy trust, email, public URL, registration and other Stripe settings | Preserve existing verified values; no additions required by this delta |

1. Close the evidence prerequisites above. Record the exact previous SHA and rollback environment, especially billing flag and dedicated credential availability. Confirm auto-deploy is off before any later authorized push.
2. Read the confirmed service's **Environment** page and verify the existing credential variables are effective on this service and STAFF_STRIPE_ENABLED is exactly `0`. Do not save changes, create/replace credentials, or edit shared environment groups. Environment presence alone does not establish which values the running deployment loaded; confirm deployment/configuration timing or inspect runtime presence privately.
3. Commit/push is now authorized: create and validate the scoped release commit, record its full SHA, and push only the new release branch named above. Do not advance the production-linked branch or change Render's branch/settings. The operator will select the exact release SHA for manual deployment.
4. After deployment authorization, choose **Manual Deploy > Deploy a specific commit**, enter that reviewed full SHA, and deploy. Preserve existing root/build/start commands and existing pre-deploy configuration; add no migrations. Stop if existing commands contain unexpected migration/provisioning steps.
5. Confirm exact deployed SHA, healthy startup and effective STAFF_STRIPE_ENABLED=0. Fresh platform login must open the directory but must not impersonate a Staff owner. Owner login (including Oakfield) must open only their authorized businesses and Subscription & Billing; another business URL must deny access. Confirm ordinary owners cannot open platform routes. Check Garage Voice and PayChaser health and existing authorized sign-in flows. Do not end real trials, deactivate businesses, initiate checkout, refresh billing or alter payroll as smoke tests. Rehearse destructive lifecycle actions only on disposable staging businesses.

## Rollback

- Before any early trial endings exist, redeploy the independently verified prior compatible SHA after approval. A rollback to older permission code also restores the prior authorization weakness; prefer a corrective release retaining the dedicated-access guard.
- After any `subscription_management/end_trial` audit event exists, **do not deploy unmodified older code**: it ignores the event and can restore remaining trial access. Prepare and validate a rollback-compatible build of the prior application retaining the audit-aware trial access check (and compatible directory status handling). Retain dedicated platform guards and inactive-business employee checks where needed. Otherwise stop lifecycle use and prepare a forward fix before reverting.
- Keep business active flags, trial dates, audit events and all account/payroll/billing data. Reactivation uses the audited application action; it does not undo early trial ending. Do not delete audit events, reverse migrations or restore an old database over live data.
- Render Deploys > previous successful deploy > Rollback > Rollback to this deploy reuses that deployment's environment variables and build configuration. It does not restore the database or overwrite current saved service settings. Inspect target environment first: ensure effective STAFF_STRIPE_ENABLED=0 and dedicated credentials. If those differ or the old code needs compatibility changes, use a standard deployment of the reviewed compatible SHA with verified current settings instead of a blind artifact rollback. Dashboard rollback disables auto-deploy; API rollback does not.
- Verify restored SHA/environment, trial expiry behavior, inactive-business denial, platform authorization, owner/Oakfield access, Garage Voice and PayChaser health.

Render references: https://render.com/docs/configure-environment-variables ; https://render.com/docs/deploys ; https://render.com/docs/rollbacks
