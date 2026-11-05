# TrimTech Control Centre upgrade

This work is local to the `trimtech-control-centre-integration-20261101`
integration worktree. It has not been deployed and no production database or
environment configuration was changed.

## Included

- Control Centre navigation to Staff Manager business administration, registration
  review and the configured PayChaser administration site.
- Complimentary access management remains time-limited, audited and separate from
  Stripe billing.
- Registration review supports batches of up to 100 deactivations/reactivations.
  Deactivation keeps the business and history, checks protections again under
  transaction locks, and records the operator, reason and changes. Verified owners,
  legacy businesses, billing/checkout history, complimentary access, employees,
  shifts and completed setup are not eligible for bulk deactivation.
- Registration and optional verification notices go to the configured platform
  administrator. Notices mask owner addresses, link only to the authenticated
  review page, and are de-duplicated by business and event.
- Cloudflare Turnstile remains fail-closed when configured, as introduced by
  commit `43fef36`.

## Explicit prerequisites

The app does not apply schema changes automatically. Registration review requires
the complimentary-access schema and its own additive `sr_*` migration. In an
approved isolated environment, verify and apply the complimentary-access migration
first if needed, then run:

```powershell
python -m trimtech.modules.staff.registration_review_migration
```

Do not run either migration against production without separate approval.

Configure `PLATFORM_ADMIN_NOTIFY_EMAIL` to receive new-registration notices.
`PLATFORM_ADMIN_NOTIFY_VERIFIED=1` opts in to email-verification notices; it is
disabled by default. Delivery reuses `RESEND_API_KEY`, `RESEND_FROM_EMAIL` and an
HTTPS `STAFF_PUBLIC_BASE_URL` (or `RENDER_EXTERNAL_URL`). Existing dedicated
platform administrator credentials remain required for review actions.

PayChaser reporting remains an aggregate read-only service integration. No customer,
invoice or payment details are exposed in the Control Centre.

## Business details and PayChaser administration (follow-up)

- Staff Manage business now has a platform-owner-only form for the business name and
  an optional contact email. The contact email is stored in a new additive table
  `sd_contacts` and never changes owner login emails. Apply the migration (optional;
  name edits work without it) after the other two:

  ```powershell
  python -m trimtech.modules.staff.business_contact_migration
  ```

- PayChaser businesses (`/staff/platform/paychaser/businesses`) use new service-token
  endpoints in PayChaser (`GET .../v1/businesses`, `GET .../v1/businesses/<id>`,
  `PATCH .../v1/businesses/<id>`) with the existing
  `PAYCHASER_CONTROL_CENTRE_API_URL` and `PAYCHASER_CONTROL_CENTRE_API_TOKEN`. No new
  environment variables. Deploy PayChaser first; the Control Centre pages show an
  "unavailable" notice until then. Editable fields are limited to name, email, phone,
  address and company number; invoices, customers, VAT, currency, invoice numbering
  and billing are neither returned nor writable. Edits are audited in PayChaser's new
  `platform_business_audit` table, created automatically at PayChaser start-up.

## Focused validation

From `ai-receptionist-engine`, run:

```powershell
py -3.12 -m unittest test_trimtech_control_centre test_trimtech_admin_nav_manage test_staff_registration_review test_staff_registration_protection test_staff_accounts
```

Database-backed account tests require `STAFF_TEST_DATABASE_URL`; without that
isolated test database they are skipped. No production tests, migrations or
deployment actions are authorized by this change.
