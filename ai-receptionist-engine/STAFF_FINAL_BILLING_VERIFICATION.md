# Staff account UI and billing verification — 15 October 2026

Base: d4971a2d86239dbb31a20af05c99b7b45cfd2e39, branch staff-v2-polish.
Decision: ready for a Stripe sandbox rehearsal; **not ready for live billing activation**.

## Changes

Email verification, password reset, employee invitation and joining forms retain
their email codes as hidden submitted values when a valid email link is present.
Manual entry remains under a collapsed help section, including without JavaScript.
Password-validation retries retain the email code; passwords are never redisplayed.
Employee sign-in shows the existing workplace name instead of the business slug.
Authentication routes, validation, CSRF, rate limiting, session rules and billing
implementation are unchanged. No dependency or schema changes are required.

## Verification

- 62 existing authentication, onboarding, billing, checkout and joining tests passed,
  with no failures or skips. Disposable localhost PostgreSQL schemas only; outbound
  provider networking blocked and StripeClient mocked. Test fixture schema setup
  and migration regression cases never connected to production.
- Four account presentation tests and one additional disabled-billing guard test
  passed: 67 Python cases in total. Two JavaScript suites passed for fragment
  handling, hidden values, retries, invalid links, joining previews and copy fallback.
- Twelve browser/device cases passed: all account modes, employee sign-in and
  joining at 360px; reset also at 1280px; password retry and manual-code fallback.
  Checks covered overflow, visible password fields, submitted codes and CSRF values.
  Reset, invitation and employee mobile screenshots were visually inspected.
- Read-only Stripe GET verified the existing active live price
  `price_1UOQH4PXtngggosB1nIC12jZ`, product `prod_VPEkYJmUGHC7ws`: GBP 4900,
  every one month, licensed per-unit recurring price, inclusive tax behaviour and
  product metadata `application=trimtech_staff_manager`. No Stripe objects changed.
  The service must continue selecting this existing price through STAFF_STRIPE_PRICE_ID;
  the current production environment mapping was not independently inspected.
- The 14-day card-free trial starts on email verification and is not restarted by
  payment, reset or repeated verification. Staff Checkout still sends
  `automatic_tax.enabled=false`, configured price ID and quantity one.
- Billing regressions cover checkout creation/recovery, idempotency, signed raw-body
  webhooks, replay/order handling, status updates, portal isolation, cancellation at
  period end, paid-period expiry and trial expiry without deleting business records.
- PayChaser isolation and shared-dashboard access-denial regressions passed. No
  PayChaser, Garage Voice, shared application, price or billing runtime code changed.
  This is local regression/scope evidence, not a production service smoke test.

## Before live activation

Only the live Stripe account is connected in this session. A real isolated Stripe
sandbox is still needed to verify hosted Checkout, authentication-required and
failed payments, renewal/recovery, real HTTPS webhook delivery/retries, actual
subscription cancellation and Stripe API-version compatibility end to end.
Existing email verification/invitation inbox delivery also remains unverified.

Keep production STAFF_STRIPE_ENABLED=0. No Render setting was read or changed in
this task, so the current effective production flag is not independently verified.
Before any separately approved activation, verify the service's existing price,
account, portal and webhook environment mappings and unchanged billing ledger
prerequisites. No migration is proposed. Automatic tax remains disabled under the
previously agreed pre-registration policy; the completed tax audit was not repeated.

No deployment, production database access/write/migration, billing activation,
Stripe configuration change or real charge was performed. Unrelated marketing
workspace changes are excluded from this release.
