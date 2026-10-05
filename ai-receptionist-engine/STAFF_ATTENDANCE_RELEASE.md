# Attendance evidence update

This change reuses the v2 presence tables and the existing assignment/shift
records. No migration or backfill is required. The current application still
requires the already-existing v1, v2 and payroll v3 migrations.

## Behaviour

- Attendance shows On site (including a confirmed return), Left site, or
  Location unavailable/stale, with the last confirmed GPS capture in UK time.
- Existing accuracy, repeated-sample and elapsed-grace checks still govern
  departures. A timestamp is evidence of a confirmed observation, not an exact
  physical boundary-crossing time. Pending/uncertain samples do not refresh the
  last confirmed time. Permission denial or stopped updates is never a departure.
- Timelines collapse repeated samples into departure/return events, retain
  unavailable-location intervals and show scheduled/actual clocking times.
  Timelines and exceptions refresh on page reload; live presence polls every
  30 seconds while the manager page is visible.
- Lateness uses the saved assignment start snapshot where available. Fixed-mode
  shifts without a snapshot use an unambiguous matching scheduled assignment
  for the same business, employee and site. Unscheduled/ambiguous shifts are not
  labelled late. Existing snapshots are not changed by roster edits.
- `STAFF_LATE_GRACE_MINUTES` defaults to 5, accepts whole minutes from 0 to 120
  (values outside that range are clamped; invalid values use 5). Exactly the
  grace period is not late. Beyond it, the displayed delay is the total time
  since scheduled start, rounded up to the next whole minute, not delay minus
  grace. This is service-level configuration; no environment change is required
  to use the default.
- Flags and GPS events never change shift times, approved hours, break deductions
  or payroll. Explicit manager correction/approval remains the existing workflow.
- Presence remains optional, foreground-only GPS evidence. This does not add
  background tracking or guarantee evidence during a locked/hidden mobile session.

## Deployment (requires separate approval)

1. Review the Staff-only diff and run the isolated Staff regression suite.
2. On staging, verify mobile GPS permission/on-site, confirmed departure, return,
   stopped updates, and late/unscheduled shifts in Attendance and Shift Approval.
   Check fixed/agency clocking, breaks, leave and existing payroll review.
3. Before promotion, check the actual production SHA, branch and auto-deploy
   setting. Confirm existing v3 verification passes. Do not rerun migrations for
   this update. Keep a recent backup and record the prior application SHA/config.
4. Commit/push/merge only after approval. A push to an auto-deployed branch can
   itself deploy; coordinate that approval before pushing. If auto-deploy is off,
   deploy the approved commit to the existing service after deployment approval.
5. Verify the same workflows after deployment. Revert to the recorded previous
   application SHA if needed; this update has no database schema rollback.

No Garage Voice, PayChaser, HMRC integration, or payroll calculation changes.

## Local validation

- Full isolated Staff suite: 95 tests passed, zero skips.
- After final stale-gap/review-key refinements: 7 attendance tests and 12 existing
  operations tests passed, zero skips. These include two additional attendance
  regressions introduced after the full-suite run.
- `git diff --check` passed. Template compilation is covered by the Staff suite.
- The runner `.release-validation/run_polish.py` forces disposable local schemas
  on `127.0.0.1:55449`, blocks other database connections and outbound Python
  networking, and disables real email delivery. No production tests were run.
- Browser/device GPS acceptance testing remains pending; server integration tests
  use timestamped GPS samples and mocked time.
