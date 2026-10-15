# Staff Manager final release candidate — 15 October 2026

Status: NO-GO for billing activation. Local application candidate only; no push,
deployment, billing flag change, production write or migration is authorized.

## Scope and validation

Only the approved wage-estimate correction and its regression tests change code.
Approved weekly estimates reuse the existing payroll calculator for whole-minute
shift/break rounding and per-shift penny rounding. Existing payslips and payroll
records are not changed. No dependencies or schema changes are required.

Current run: 17 tests passed, zero failures/errors/skips, with dotenv disabled,
database URLs cleared, and network/database connections blocked. Coverage:
wage rounding, payroll calculations, gateway configuration, statutory calculations
and location classification. The 13 October retained report records 29 passing
isolated local cases including 18 mocked billing tests and six platform/database
cases. Those database integration cases were not rerun today: the local test
PostgreSQL service is unavailable. No Stripe sandbox is connected.

Unrelated marketing edits and the local Stripe setup PowerShell script are excluded.
The release parent/rollback target is 5d86125607c1b94e58c81cc158e44cb9355605e6.
This matches the user-supplied baseline in the retained 13 October report; confirm
the actual Render deployed commit before deployment. Do not deploy this candidate
if the live service contains additional unreviewed changes.

## Remaining launch blockers

- Render configuration cannot be privately inspected: this process has no
  RENDER_API_KEY, confirmed Render resource ID, or production database credential.
  This does not establish that any Render variable is absent.
- Current production billing ledger/schema has not been queried. Backup evidence
  contains the existing sb_* tables and matching 20261008_staff_billing_v1 ledger,
  but its source mapping is unverified. Verify current checksums/fingerprints in an
  authenticated, read-only transaction; never run migrate() or application startup
  as a substitute. Any missing/mismatched schema stops this release.
- Read-only live Stripe Tax results: status=pending, missing head_office; no tax
  registrations; Staff product tax_code and account default tax_code are null.
  Complete settings and establish an appropriate verified product classification.
  Record only registrations corresponding to confirmed legal tax obligations.
  Tax settings can affect other integrations: review PayChaser impact before any
  separate authorized changes. No tax configuration changes were made here.
- Sandbox lifecycle rehearsal is outstanding: successful/3DS checkout, failed
  payment, renewal/recovery, duplicate/out-of-order webhook deliveries, signature
  rejection, period-end cancellation and paid-access expiry. Use an isolated
  sandbox, sandbox-specific identifiers/signing secret and separate disposable DB.
- Actual HTTPS webhook delivery/signature processing has not been verified.
  Preserve raw bytes and Stripe-Signature. Review compatibility of destination
  API version 2026-08-26.dahlia with pinned stripe==16.0.0. Never send synthetic
  live billing events against production records to satisfy a test.

The already verified inclusive GBP 4900 monthly Price keeps the single-unit
customer total at GBP 49 when tax applies, without discounts/other adjustments.
Inclusive pricing alone does not establish correct VAT calculation or reporting.

## Private configuration checks

Inspect names/presence without logging credentials. Compare non-secret IDs privately:

- STAFF_STRIPE_ENABLED=0 (must remain 0 for this release).
- STAFF_STRIPE_MODE=live.
- STAFF_STRIPE_SECRET_KEY: dedicated live Staff key, with permissions required by
  the existing gateway, including account retrieval. A key with only Product/Price
  and portal permissions is insufficient for the runtime checkout lifecycle.
- STAFF_STRIPE_WEBHOOK_SECRET: exact live Staff destination's signing secret.
- STAFF_STRIPE_ACCOUNT_ID=acct_1UCcbVPXtngggosB.
- STAFF_STRIPE_PRODUCT_ID=prod_VPEkYJmUGHC7ws.
- STAFF_STRIPE_PRICE_ID=price_1UOQH4PXtngggosB1nIC12jZ.
- STAFF_STRIPE_PORTAL_CONFIGURATION_ID=bpc_1UQbS2PXtngggosBlH8XA0Su.
- STAFF_PUBLIC_BASE_URL=https://garage-voice.onrender.com (canonical application
  origin; verify it still matches the intended production host).

Do not call configuration() expecting success while ENABLED=0: the intentional
feature gate rejects it. Inspect/validate without changing the flag.

## Deployment sequence — only after separate approval

1. Close the blockers above and record private configuration/schema verification.
   No migration is part of this release. Keep STAFF_STRIPE_ENABLED=0.
2. Confirm Render service garage-voice-agent, configured staff-v2-polish branch,
   actual deployed baseline and existing build/start commands. Prevent an automatic
   deploy when the separately approved push occurs; do not change commands or env
   settings as part of the application release.
3. After explicit push approval, push only the reviewed release commit to the
   configured branch. After explicit deployment approval, use Render Manual Deploy
   / Deploy a specific commit and select the full candidate SHA reported by git.
   Do not deploy an unrelated later branch tip or marketing changes.
4. Verify Render reports that exact SHA and healthy startup. Perform read-only
   existing Staff dashboard/subscription/payslip checks and read-only Garage Voice
   and PayChaser health checks. Confirm billing remains disabled. Do not submit
   checkout, refresh or payroll actions as deployment smoke checks.
5. Billing activation requires a later explicit approval after tax and sandbox
   readiness are complete. With flag 0, the webhook intentionally returns 503;
   this application deployment does not activate payment processing.

## Rollback

Use Render's rollback to the verified previous deployment at
5d86125607c1b94e58c81cc158e44cb9355605e6, or deploy that exact existing SHA after
approval. Keep all environment settings, billing ledger tables and business/payroll
records intact. Do not run reverse migrations, restore a database or git reset the
shared workspace. The only runtime delta being reverted is the wage estimate.
Confirm the restored SHA and read-only health checks. Billing stays disabled.
