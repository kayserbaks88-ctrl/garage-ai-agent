# Staff Manager final polish and platform directory

Based on reviewed Staff commit 8d26d960 on staff-v2-polish. No new database
migration is required: all features use existing sm_*, so_*, sb_* and staff_*
tables/columns. Existing migration SQL and database connector are unchanged.
No production records, settings, emails or provider accounts were modified.

## Result

Platform-wide Staff directory: /staff/platform/businesses, protected by the
existing TrimTech platform-admin login. Reads all sm_businesses independently of
Staff membership, including public onboarding businesses. Ordinary Your businesses
remains membership-scoped. Reports recorded dates/trial/subscription status,
employee counts, setup review and shift activity. No tenant impersonation,
employee/payroll details or Stripe creation. Directory views record a hashed actor
in server logs; existing mutation audit controls remain intact.

Manager dashboard shows the business name, compact summaries and six navigation
sections. Settings owns the checklist; payroll explanations and HMRC/NI/pension
profiles collapse behind Payroll Settings. Employee cards are compact; activation,
authentication, payslip viewing/download routes are unchanged.

GPS display uses the latest timestamped accurate sample with its accuracy buffer:
On site, Outside site or Location unverified. Missing, stale, invalid and
boundary-overlapping samples never prove departure. Existing grace/consecutive
confirmation states and historical timeline/audit records are preserved. Confirmed
departures and latest sample display are distinct; no pay, approval or shift
mutation is triggered by this presentation. Foreground-only browser limitations
remain explicit. Polling updates manager break start/duration separately from GPS
and approval status. Clocking evidence becomes labelled cards on phones with
expandable technical coordinates and a normal desktop table.

Approved gross estimates exclude pending/open/rejected shifts and deduct recorded
unpaid breaks at current rates; the broader recorded-hours estimate is labelled
separately. No fabricated tax/deductions/net pay or payroll records. Currency
renders £ correctly. Invitation acceptance explicitly says delivery unconfirmed;
known failed invitations remain failures. No unverified delivery claims or real
test emails were introduced.

## Validation

Complete Python discovery executed 203 tests (197 existing plus six new). Six
presentation/navigation failures were fixed: restored compact access to invitation
counts, employee directory, setup resumption and payroll deferral, and updated two
expected location labels. All six failed cases and all six new cases then passed
in a 12-test rerun, with no errors or skips. Other discovered cases passed,
including payroll calculations, PDF/delivery mocks, joining/activation, tenant
security and record-preserving migration regressions. Three JavaScript suites
passed: address selector, joining, and GPS/break polling. External Python/provider
network was blocked, database access restricted to loopback disposable schemas.

Five synthetic pages checked at iPhone 393x852 and desktop 1280x900, including
manager, employee, attendance, shift review and platform directory. Final layout
report/screenshots are local .release-validation/final-polish-previews artifacts.
No real iPhone/device or live provider delivery check is claimed. Git whitespace
check passed. Garage Voice and PayChaser source, shared app.py, dependencies,
provider integrations and deployment files are unchanged.

## Controlled release, pending explicit approval

No push/deploy is authorized. Keep Auto-Deploy Off. Reconfirm the current live SHA,
root/build/start settings and existing Pre-Deploy Command in garage-voice-agent
before publishing. User reports the previous joining release was deployed, but
the current exact SHA/pre-deploy value has not been independently inspected here.

This release must not rerun joining or any other migration. If the previous
Pre-Deploy Command is still python -m trimtech.modules.staff.joining_migration,
obtain explicit approval to clear that service-only command to blank using a
non-deploying save option before the controlled deployment. Do not silently
change it, run it during build/start or replace another reviewed command blindly.

After approval, push only the reviewed staff-v2-polish commit, then use Render
Manual Deploy > Deploy a specific commit with its exact SHA. Verify deployed SHA,
platform permissions/Oakfield reporting, normal manager tenant access, mobile
clocking/breaks/location evidence, payroll/payslip reads and controlled Garage
Voice/PayChaser smoke checks. Do not send test email without explicit authorization.

Rollback: redeploy the recorded preceding live SHA (expected base 8d26d960 only
if independently reconfirmed). No down migration or data restore is required.
Retain all joining records, businesses, payroll and invoices. Production database
and environment settings are otherwise unchanged.

## Changed files (excluding this release note)

- `ai-receptionist-engine/static/staff_attendance.js`
- `ai-receptionist-engine/static/staff_manager.css`
- `ai-receptionist-engine/static/staff_presence.js`
- `ai-receptionist-engine/templates/staff_account.html`
- `ai-receptionist-engine/templates/staff_approvals.html`
- `ai-receptionist-engine/templates/staff_attendance.html`
- `ai-receptionist-engine/templates/staff_attendance_mobile.html`
- `ai-receptionist-engine/templates/staff_base.html`
- `ai-receptionist-engine/templates/staff_dashboard.html`
- `ai-receptionist-engine/templates/staff_employee_base.html`
- `ai-receptionist-engine/templates/staff_employee_onboarding.html`
- `ai-receptionist-engine/templates/staff_employees.html`
- `ai-receptionist-engine/templates/staff_leave.html`
- `ai-receptionist-engine/templates/staff_payroll_page.html`
- `ai-receptionist-engine/templates/staff_platform.html`
- `ai-receptionist-engine/templates/staff_settings.html`
- `ai-receptionist-engine/templates/staff_shift_evidence.html`
- `ai-receptionist-engine/test_staff_attendance.py`
- `ai-receptionist-engine/test_staff_mobile_payroll.py`
- `ai-receptionist-engine/test_staff_platform_polish.py`
- `ai-receptionist-engine/test_staff_presence.cjs`
- `ai-receptionist-engine/trimtech/modules/staff/attendance.py`
- `ai-receptionist-engine/trimtech/modules/staff/onboarding_routes.py`
- `ai-receptionist-engine/trimtech/modules/staff/platform_control.py`
- `ai-receptionist-engine/trimtech/modules/staff/presence.py`
- `ai-receptionist-engine/trimtech/modules/staff/routes.py`
- `ai-receptionist-engine/trimtech/modules/staff/wages_estimate.py`
