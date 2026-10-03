# Staff payroll and attendance exceptions - review before deployment

Branch: `staff-v2-polish`. Deployment approved by the user after final checks.
HMRC/RTI submissions and HMRC API connections remain prohibited.

## Implemented workflow

Managers review each employee's tax code/basis, NI category eligibility, regular pay
frequency, pension enrolment/method/rates and opening taxable-pay/PAYE balances.
Opening balances explicitly cover earlier payroll, including external and legacy
gross-only records. Balances and frequency lock once the employee has a calculation.
Later profile changes flag affected drafts for recalculation.

Draft generation uses approved, completed, unclaimed shifts, recording payment date,
employer name, 2026/27 engine version, employee/profile snapshots and calculation
breakdowns. It calculates PAYE, employee/employer Class 1 NI, pension contributions,
net pay, employer cost and tax-year-to-date balances. PAYE refunds are supported.
The business transaction lock, unique allocation and earnings-period constraint
prevent duplicate or out-of-order payroll. One statutory draft is allowed per
business at a time; approve it or discard it with an audited reason.

The manager reviews individual deductions and contributions before approval.
Approved records are immutable in this workflow. Shift corrections keep the
existing external-adjustment process. Discarded drafts release shifts and retain
their snapshot in the audit trail. No bank transfer is performed.

Employees see only their approved records and can download a PDF payslip. Employer
NI stays in the manager payroll breakdown; employee payslips show employer pension
separately and omit employer NI, as requested. Managers can download draft previews.
Downloads are authenticated, business/employee scoped,
private and non-cacheable. No public PDF URL or payroll login credential is placed
in a document. Email is an explicit manager action, uses the existing Staff Resend
transport, and sends a portal sign-in link without salary details. Queueing commits
before dispatch, concurrent sends use row locks, and a stable provider idempotency
key avoids duplicate sends. Sent means provider acceptance, not inbox delivery.
Failed/disabled notices are visible; they are not automatically retried. A pending
notice can be dispatched by repeating the explicit send action. No real email was
sent during development.

Attendance shows late starts (>5 minutes), missed starts (>=15 minutes), long/open
shifts, confirmed departures, stale location, inactive assigned sites and approved
leave conflicts. Exceptions refresh on page load, cover the recent 14 days plus
all open shifts, and support manager notes. Missed/late starts need a recorded
assignment; no fixed-workplace schedule is invented. Fixed clocking can match its
scheduled site/window without requiring agency mode. Location alerts never establish
absence automatically or change pay. Existing presence polling is preserved.

## Supported payroll scope

- Tax year 2026/27 only; regular weekly and monthly employees paid from approved
  hourly shifts. Week 53 uses the HMRC non-cumulative treatment.
- England/NI, Welsh and Scottish suffix/K codes, BR, D/SD/CD and NT; cumulative
  and W1/M1 basis. A manager must use the actual issued code; no allowance taper
  or tax-code update is inferred from earnings.
- Employee NI categories A, B, C, D, E, F, H, I, J, K, L, M, N, S, V, X and Z,
  with manager confirmation of category eligibility.
- No pension, net-pay arrangement or relief at source; qualifying earnings or
  all gross pay. Employer contributions are separate from net deductions.

Not supported: directors, other/irregular pay frequencies, salary sacrifice,
student/postgraduate loans, attachment orders, benefits in kind, statutory payments,
automatic-enrolment assessment, automatic bank payments or correction runs for
finalized periods. Managers must confirm none apply before saving a profile.
These cases require external payroll review; this is not a universal payroll engine.
No claim of HMRC recognition/certification is made.

**TrimTech has no HMRC submission integration. Subscribers remain responsible for
all HMRC/RTI submissions, payments and pension reporting.**

## Deployment preparation (only after approval)

Install the pinned requirements, including ReportLab for PDF generation. Apply the
versioned migration using `python -m trimtech.modules.staff.migrations` to a backed-up
staging copy first. It creates payroll/profile/notice/review tables and adds run
metadata; only the deduction non-negativity constraints are relaxed for tax refunds.
Old calculation records remain gross-only. Migration checksums and schema drift
verification remain enforced. Runtime startup does not migrate automatically.

Before production: review representative payroll with the subscriber's payroll
professional, enter reconciled opening balances, and verify browser/device use and
an explicitly approved real inbox-delivery test. Use `STAFF_PAYSLIP_EMAIL_ENABLED=0`
to disable notices. Email needs the existing `RESEND_API_KEY`, `RESEND_FROM_EMAIL`
and trusted HTTPS `STAFF_PUBLIC_BASE_URL` (or `RENDER_EXTERNAL_URL`). No new HMRC keys
or service are needed.

Rollback must account for approved statutory payroll and refunds; do not run old
gross-only code against newly calculated records. Prefer a reviewed forward fix or
restore the matching application and database backup together. No migration has
been run on production.

Official calculation sources and synthetic-fixture provenance are in
`testdata/PAYROLL_SOURCES.md`.
