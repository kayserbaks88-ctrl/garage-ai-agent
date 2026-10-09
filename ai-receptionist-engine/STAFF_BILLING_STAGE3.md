# Staff Manager Stage 3: Stripe billing validation

Local work on `staff-v2-polish`, 8 October 2026. This report supersedes the earlier Stage 2 statement that online billing is unavailable. All existing Stage 1, Stage 2 and Stage 3 work is retained. Nothing was committed, pushed, deployed or run against production. Garage Voice, PayChaser and the deployed payroll migration were not edited.

## Fix made during resumed validation

The interrupted isolated run recorded eight errors because Stripe SDK 16.0.0 removed the public `to_dict_recursive()` method. The Staff gateway now uses public `to_dict()`, which recursively serializes by default, for every API response and verified webhook. Adapter test mocks use the same method. The existing `stripe==16.0.0` dependency pin is retained. Real SDK webhook signature verification now passes.

## Database and network safeguards

Runner: `.release-validation/run_stage3_resume.py`, using `.release-validation/venv/Scripts/python.exe` (Python 3.12.8).
Database: fresh `staff_stage3_resume_20261008`, role `staff_release_test`, server `127.0.0.1:55449`, existing local `.release-validation/pgdata` cluster. Every integration test creates a UUID `staff_test_` schema and cleans up only that schema.

The runner forces both database environment variables to this test database, rejects psycopg2 connections outside the loopback test port, disables dotenv loading, clears email and Staff Stripe credentials, and blocks outbound Python socket connections. Tests inject fake Stripe credentials and mock API calls; no real Stripe, email or production connection was used.

## Verification

- Isolated billing: **18 passed, 0 failures, 0 errors, 0 skips**, 70.631 seconds. Output: `.release-validation/stage3-resume-billing.log`.
- Full Staff regression (`test_staff*.py`): **171 passed, 0 failures, 0 errors, 0 skips**, 631.618 seconds. Includes all 18 billing tests. Output: `.release-validation/stage3-resume-regression.log`.
- `git diff --check` passed; `payroll_migration.py` matches HEAD. All disposable test schemas were removed (final count: zero). PowerShell labeled redirected unittest stderr as NativeCommandError and returned a shell status of 1; both retained unittest summaries finish with OK and no skips/failures/errors. This is the same stderr wrapper behavior noted in the Stage 2 report.

Billing coverage includes raw-body SDK signatures, missing/invalid/old signatures, body limits, live/test and connected-account rejection; CSRF and explicit recurring-payment consent; verified current provider state rather than browser return parameters or old event payloads; webhook duplicate/concurrency protection and transaction rollback/retry; customer and checkout idempotency/recovery; active plus paid-invoice entitlement bounded by its paid period; preserved trial dates and business records; scheduled cancellation, canceled/unpaid/paused states; owner-only tenant authorization and server-selected prices; rejection of foreign application/customer/subscription bindings and unrelated portal invoices; repeatable migrations, fingerprint preservation and transactional migration rollback.

## Launch requirements and outstanding limitations

1. Separately approve deployment and production migrations. Back up and rehearse restoration first. Verify the existing operational Staff v3 schema, then explicitly apply `accounts_migration`, `onboarding_migration`, and `billing_migration` in order. These additive migrations do not run automatically at startup. Preserve all new tables and account/entitlement enforcement in any application rollback.
2. Complete existing-owner provisioning and review privately created Stage 1 accounts and grandfathered employee credentials. Existing legacy businesses are not automatically put on subscriptions; legacy employee payroll-number login remains a known limitation. Retain the Stage 1/2 release prerequisites.
3. Configure Staff-specific `STAFF_STRIPE_ENABLED`, `STAFF_STRIPE_MODE`, `STAFF_STRIPE_SECRET_KEY`, `STAFF_STRIPE_WEBHOOK_SECRET`, `STAFF_STRIPE_ACCOUNT_ID`, `STAFF_STRIPE_PRICE_ID`, `STAFF_STRIPE_PRODUCT_ID`, `STAFF_STRIPE_PORTAL_CONFIGURATION_ID`, and HTTPS `STAFF_PUBLIC_BASE_URL`. Never substitute shared integration keys. Verify the Stripe account's legal company name is TrimTech AI LTD and charges are enabled.
4. Verify an active GBP recurring licensed per-unit price, quantity one, monthly or annual interval with interval_count one, no provider trial, explicit tax behavior, and active product metadata `application=trimtech_staff_manager`. Confirm the commercial price and tax setup; Checkout enables automatic tax and collects billing address.
5. Configure a dedicated active portal with the same application metadata and mode: payment-method updates enabled, cancellation at period end enabled; subscription updates, customer updates, invoice history and public portal login disabled. Staff customers must contain only their own Staff subscriptions and associated invoices.
6. Register the dedicated HTTPS `/staff/billing/webhook` endpoint with its own signing secret and the event types in `billing.EVENTS`; use an API version compatible with the pinned SDK (installed SDK default: `2026-09-30.endive`). Preserve raw request bytes and Stripe-Signature through the proxy. Monitor retry_later/503 responses and reconcile failures. Stripe endpoint API versions determine event payload shapes: https://docs.stripe.com/api/webhook_endpoints
7. Perform an approved end-to-end Stripe sandbox rehearsal: Checkout, authentication-required payment, renewal/failure/recovery, webhook delivery/retries, portal cancellation and paid-period expiry. Local mocked tests do not verify Dashboard settings, real checkout/tax behavior or live provider delivery. Verify email inbox delivery, HTTPS cookies, stable Flask secret and narrowly configured trusted proxies before opening registration.
8. Establish support reconciliation for lost customer creation older than 23 hours, unresolved checkout outcomes, configuration changes and histories exceeding the 100-record page. These cases intentionally block rather than risk duplicate subscriptions or expose another product's billing; no automated operator reconciliation tool or scheduled Stripe resync is supplied. Owners can refresh securely; paid access expires locally even if a webhook is missed.

Keep public registration closed until these requirements are completed and the release is approved. No production migration or live Stripe verification was performed by this validation.