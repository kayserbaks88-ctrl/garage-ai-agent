# Mobile attendance and period payroll polish

No schema migration, production change, commit, push or deployment is performed
by this change. It requires the existing Staff v1/v2/payroll v3 schema.

## Mobile attendance

At widths up to 650px, Attendance uses one initially collapsed native details
card per employee. Multiple shifts are grouped inside the same employee card.
The summary shows name, site, clock-in, shift/approval state, current presence
and an alert indicator. Missed-clock-in exceptions without a shift get a card
too. Expanding retains hours, timelines, location evidence, exceptions, existing
review forms, and links to completed-shift editing. It can be collapsed again.

Employee search is immediately available. Site/status/alert filters expand from
a compact filter control; their selections combine. The summary shows filtered
staff / total staff, on-shift staff and staff with alerts. Clear filters restores
all cards. Polling updates presence filters as evidence changes. Stale location
is distinct from departure and never proves absence. Existing pay/approval
logic is untouched. Above 650px the original table and exceptions remain visible;
the mobile cards and controls are hidden.

## Payroll draft rules

The existing generator already selected employees automatically. The new UI
explains this and opens the per-employee draft review after successful creation.
Employee IDs submitted by a client cannot narrow the selection.

The statutory draft includes shifts for the selected business that are complete,
approved, unallocated, and whose Europe/London clock-in date falls within the
inclusive work period. Whole shifts remain allocated by their start date, as
before; overnight shifts are not split. Reviewed employee frequency must match
the selected frequency. Work owed to inactive employees is not silently dropped.

Zero-payable-minute shifts after the existing break calculation are excluded from
statutory drafts and recorded for review. The legacy gross-only generator retains
its previous behaviour. Paid/unpaid break calculations and rate snapshots remain
unchanged. A zero hourly rate is visibly flagged in draft review.

Missing payroll profiles for payable work block the entire draft and identify
employees needing setup. Other tax-code, pension, opening-balance, chronology,
tax-period and unsupported-payroll validation remains unchanged and transactional.
No partial successful payroll is committed when validation fails.

Open, unapproved/rejected, already allocated, zero-payable and other-frequency
shifts are named in the draft exclusion list, recorded in the existing Staff
audit table. This is a creation-time snapshot; later corrections do not silently
add excluded work to that draft. Draft review still shows every included employee
separately. No automatic approval, finalisation, email or HMRC submission occurs.

Employer name/frequency are suggested from the latest saved payroll run visible
in the payroll history. If none exists, frequency is suggested only if the
reviewed employee profiles agree. Unknown values remain blank. There is no new
business settings table, tax-code default, pension default or opening-balance
inference.

## Before deployment

Review the diff and test a representative mixed-frequency period on staging.
Confirm named exclusions before approval; omitted shifts require explicit review
and the existing discard/recreate workflow if they should be added. Existing
unique-period, unique-shift and one-statutory-draft protections remain in place.

Check a real phone with location permission and stopped updates. Synthetic
headless browser checks cover 100 staff, compact/expandable cards, filtering,
live presence filter updates, no horizontal overflow and desktop visibility;
they do not validate a physical phone's GPS or background behaviour.

No migration is needed. Commit/push/merge/deployment still require approval;
check Render auto-deploy before pushing any production-tracked branch. Keep the
previous application commit as rollback. Garage Voice, PayChaser and statutory
calculation code are unchanged.

## Validation

- Final full Staff suite: 104 tests passed, zero skips, using the isolated
  `.release-validation/run_polish.py` runner and Python 3.12. Production database
  connections and outbound Python networking are blocked by that runner.
- Seven new regression tests cover 100-staff grouping, collapsed cards and
  filters, exception-only employees, employee isolation, automatic multi-employee
  drafts, missing setup rollback, mixed frequencies, saved defaults, duplicate
  claims, open/pending/rejected work and fully unpaid shifts.
- Local headless Edge with synthetic 100-staff HTML: 13 mobile checks passed
  (visibility, compact height, no horizontal overflow, expansion/collapse,
  employee/status/alert filtering, stale-vs-left distinction, live filter updates
  and reset); two desktop visibility checks passed.
- `git diff --check` passed. No production data was used or modified.
