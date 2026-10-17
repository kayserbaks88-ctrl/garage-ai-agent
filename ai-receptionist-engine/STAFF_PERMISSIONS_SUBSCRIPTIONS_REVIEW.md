# Staff permissions and subscription review ? 17 October 2026

Scope: Staff Manager only. No commit, push, deployment, production mutation, Stripe enablement, charges, live subscriptions, or PayChaser/Garage Voice changes.

## Findings

- The customer account template trusted the shared `platform_admin_authenticated` flag. Staff account login retained that flag. The shared platform login also falls back to dashboard credentials, and the original Staff directory accepted that shared flag alone. This explains how a previously set flag could display the link and authorize the directory; the precise production session history has not been independently verified.
- Staff manager pages already authorize business membership from PostgreSQL. The platform directory intentionally aggregates businesses, but does not confer employee/payroll access. New tests exercise other-business reads and writes, ordinary owners, unauthenticated users and dedicated platform administrators.
- Staff Stripe uses isolated credentials, customer/subscription metadata bindings, signed webhooks and verified invoices. Existing paid cancellation is through a validated Stripe portal configured for cancellation at period end. `STAFF_STRIPE_ENABLED=0` prevents provider operations. No programmatic cancellation API exists and none was added.
- No production DATABASE_URL or live provider access was available for this review. Current production subscription counts, provider status and environment settings remain unverified; do not infer the absence of subscriptions from disabled billing.

## Changes

- Every Staff platform route requires a platform-role session matching the explicitly configured PLATFORM_ADMIN_USERNAME, with both dedicated platform credential variables present. Dashboard fallback credentials alone cannot authorize Staff platform management. Customer sign-in removes retained platform identity. Links use the same authorization predicate. Staff responses use no-store caching.
- Settings now exposes Subscription & Billing, including for existing businesses without an onboarding checklist. Owners see original trial expiry, trial/access status, provider subscription snapshots and last verification, available provider actions, local cancellation requests and history.
- A free trial can end immediately through an audited action. Original trial dates remain immutable; access checks honor the end-trial audit event. Records remain available to authorized owners to view.
- Paid cancellation requests require an ongoing recorded subscription. They are explicitly pending provider confirmation and never change provider status or claim to stop charges. Platform administrators can review a request belonging to the selected business and record their reason.
- Platform administrators can deactivate/reactivate businesses, with typed business-ID confirmation and a reason. Ongoing subscriptions, unresolved checkouts and open shifts block deactivation. Checkout business locks serialize creation against deactivation. Inactive businesses reject both credential-based and legacy employee access. Reactivation preserves trial dates and early trial ending.
- Actions are stored transactionally in the existing business-scoped staff_audit ledger. No business records are deleted.

## Billing limits and rollout

Keep STAFF_STRIPE_ENABLED=0. No new dependencies or schema migrations are required. No environment values were changed. Dedicated PLATFORM_ADMIN_USERNAME and PLATFORM_ADMIN_PASSWORD must already be configured for legitimate Staff platform access; operators relying on the dashboard fallback must configure dedicated credentials before rollout. Existing flag-only sessions must authenticate through the dedicated platform login.

While billing is disabled, cancellation requests require a billing operator to reconcile the real Staff subscription with the provider. Local review does not stop billing or confirm cancellation. The existing owner portal and signed webhook/refresh synchronization remain the confirmation path when explicitly enabled in a separately approved rollout. Tax configuration is unchanged.

Rollback caveat: older code ignores end-trial audit events and may restore remaining trial access. Carry the trial access check through a rollback after early trial endings have been used. Deactivation flags and audit records persist.

## Validation

Focused real-PostgreSQL tests run in disposable schemas in a new loopback-only local cluster. Outbound Python network is blocked; Stripe and notification operations are mocked. Passed: 18 billing tests, 14 onboarding tests, 6 platform/polish tests, 11 new subscription/permission tests, and 16 account tests (15 passed in the suite; the route-enumeration test passed after updating it for the separately protected platform routes). The final targeted rerun also passed the Checkout concurrency test. Total: 65 distinct tests, no skips. An initial subscription-template error was corrected before the passing reruns. `git diff --check` passed.
