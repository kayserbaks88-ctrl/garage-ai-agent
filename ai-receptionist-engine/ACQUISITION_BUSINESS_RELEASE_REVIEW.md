# Staff business management and acquisition release review

Updated 12 November 2026. Both implementation candidates are committed locally on dedicated release branches. The original checkout and unrelated worktrees were preserved. Production configuration and records were untouched.

## Production evidence and verified local revisions

The operator checked Render on 12 November 2026 and supplied the following deployment settings in the conversation. Treat the supplied screenshot-derived/transcribed settings as operator evidence. No screenshot image files were attached or independently inspected in this turn, and no authenticated Render API inspection is claimed.

| Setting | Staff / Control Centre | Marketing |
| --- | --- | --- |
| Service | `garage-voice-agent` | `trimtech-ai` |
| Repository | `kayserbaks88-ctrl/garage-ai-agent` | `kayserbaks88-ctrl/garage-ai-agent` |
| Live commit supplied | `0ee3cf5` | `d428f81` |
| Linked production branch | `trimtech-control-centre-admin-followup-20261104` | `main` |
| Root directory | `ai-receptionist-engine` | `ai-receptionist-engine/marketing_site` |
| Start command, supplied verbatim | `gunicorn app` | `gunicorn app` |
| Auto-Deploy | Off | Off |

Independent local Git checks resolved both abbreviated commits uniquely, checked the candidate parents and exact changed-file lists, and compared committed runtime/test content with the previously tested working files after Git text line-ending normalization.

| Release | Full deployed baseline resolved locally | Full implementation candidate SHA | Dedicated local release branch |
| --- | --- | --- | --- |
| Staff | `0ee3cf5b8286a5417469f4775d0abffc22a754c0` | `c107c390c24d9548a2853d227aa1e78a8851cda6` | `trimtech-business-acquisition-20261112` |
| Marketing | `d428f8114fd65a287e25c5e68526b042b88f88ab` | `754b6269f146613bdd28ebd617377991340e96e8` | `trimtech-marketing-acquisition-20261112` |

Each implementation candidate is a direct child of its corresponding operator-confirmed deployed baseline. Staff has exactly 13 task runtime/test changes. Marketing has exactly eight changes, all within its service root. This report is committed in a documentation follow-up on the Staff branch. The Staff implementation SHA above is the exact deployable code candidate, while the branch tip also carries this release documentation.

The normalized content checks passed for every candidate file. The original checkout's HEAD, Git status and hashes of modified/untracked files matched before and after the implementation commits. The local evidence manifest is `.release-validation/acquisition-release-seal.json`. The 98 passing results therefore apply to these unchanged implementation candidates.

The reported screen was reconciled to `templates/trimtech_control_centre.html` in the Staff deployed baseline. It labels the card Staff businesses / Recorded workspaces and derives its number from `products.staff.businesses`. Baseline `build_control_centre_summary` counted every directory row, including inactive workspaces. The candidate changes that card to Active businesses and applies the same active/archive predicate as the default Staff list. The runtime number 12 was operator-reported and was not independently queried from production.

The earlier October checkout at `4b29900c6705acefc11410d852b060378eb6459f` is preserved with its existing edits. Its earlier proposed form and dashboard changes are superseded for this release by the isolated candidate built on the operator-confirmed November Control Centre baseline. The existing November business editor, contact validation, registration review and complimentary-access functions are reused.

## Completed business management

- The existing Manage business form edits the selected business name and optional contact email through `business_details.update`, retaining its validation, dedicated-owner authorization and before/after audit records.
- Individual Archive reuses existing subscription/deactivation safeguards. Ongoing subscription records, unresolved checkouts and open shifts prevent archiving. Successful archive sets `active=false` and records an archive event in the existing audit ledger.
- Restore records a restore event and leaves the account inactive. Reactivate remains an explicit subsequent action. Direct subscription reactivation and registration-review reactivation both reject archived accounts until restoration.
- The default Staff list excludes inactive and archived accounts. The Control Centre card is labelled Active businesses and uses the same predicate. Billing issue and cancellation summaries retain their existing recorded-billing scope.
- Inactive / Archived, individual inactive/archived, and all-status filters retain access to historical workspaces. Expired trials remain distinct and keep their original dates.
- Dedicated platform-owner controls can explicitly mark or clear a test-account classification. Each change requires a reason, typed business-ID confirmation, CSRF validation and a transactionally recorded audit entry. Classification changes reporting eligibility. It leaves the account's operational status intact.
- Existing server authorization and Staff CSRF protection cover mutation entry points. History, subscription, checkout, payroll and employee records are retained. No account-name heuristic was added.

## Completed acquisition reporting

Owner report route is `/staff/platform/acquisition`, linked from the Control Centre and protected by its dedicated-owner server decorator.

Dates are inclusive UTC calendar dates. The default is the most recent 30 days, and a selection supports up to 366 days. Daily rows and selected-range totals display the following separately.

| Metric | Definition |
| --- | --- |
| Landing requests | Successfully served GET requests at marketing `/staff-manager` |
| Trial-click requests | GET requests to `/staff-manager/start-trial`, used by the marketing site's Staff trial CTAs |
| Registrations | Self-service workspaces with a trial record, counted on the business creation timestamp |
| Email verifications | Eligible signup administrators counted once on their first stored `verified_at` timestamp |
| Trial activations | Eligible trials counted on their stored `starts_at` timestamp |

Repeated requests, bots and link previews can increase request/click counts. HEAD requests are excluded. These metrics measure HTTP activity. The redirect has a fixed registration destination and discards query parameters, including arbitrary destination and ad parameters. This report supplies no ad attribution or attributed conversion rate.

Account summaries exclude currently archived workspaces, explicitly marked test accounts, and inactive registrations discarded through the existing registration-review workflow. Expired trials and genuine accounts deactivated through ordinary support actions remain eligible for historical acquisition metrics. Explicit restoration or reclassification can revise historical account summaries.

Existing account timestamps provide historical account events. Request counters have no backfill. Dates before first successful collection display Unavailable. The first collection day and current day display Partial. If the counter service is unavailable or unconfigured, account metrics still render while request metrics display Unavailable. Totals over partial ranges are labelled as covering recorded data only.

Request counters hold UTC dates and daily integer totals, plus the collection-start timestamp. They retain no visitor identifier, IP, user agent, cookie, referrer, query string or account binding. Consequently account classifications filter account metrics, while historical anonymous HTTP activity cannot be reassigned to individual test accounts. Tracking outages can cause undercounting, which the report states explicitly.

Marketing counter writes catch storage failures and use a short SQLite lock timeout. The landing response and fixed trial redirect continue during failures. Signup requires no analytics write or network call. The Staff report fetches only aggregate counters through a bearer-protected endpoint, with a two-second timeout and redirects disabled. Malformed responses, bad configuration, unavailable storage and service errors produce unavailable request metrics. Tokens are absent from the rendered report.

## Required storage and configuration

This release adds no PostgreSQL migration or dependency. Archive and test classifications use the existing `staff_audit` ledger. SQLite tables are initialized lazily by the marketing counter, separately from PostgreSQL.

Only marketing service `trimtech-ai` needs persistent SQLite storage. Staff service `garage-voice-agent` uses its existing PostgreSQL database and the HTTPS aggregate endpoint. Staff requires no SQLite file or shared filesystem mount.

An existing persistent disk, mount path and service instance count have not been confirmed. No disk was provisioned and no production settings were changed. The operator must first identify a persistent mount already attached to `trimtech-ai`, confirm the actual mount path and confirm that one service instance owns this SQLite database. Gunicorn workers on that instance can use the same file. Independent replicas with separate files produce separate counters, so instance/storage topology must be confirmed before treating their totals as complete.

| Variable | Configure on | Required value or path rule |
| --- | --- | --- |
| `MARKETING_ACQUISITION_DB` | `trimtech-ai` | Absolute SQLite filename beneath the confirmed persistent mount. Its parent directory must already exist and be writable by the marketing process. If the mount is confirmed as `/var/data`, use `/var/data/staff-acquisition.sqlite3`. `/var/data` is a conditional example, not an observed mount. |
| `MARKETING_DEMO_STATE_DB` | `trimtech-ai`, existing optional fallback | Used only when `MARKETING_ACQUISITION_DB` is empty/absent. Reuse only after checking that its actual absolute path is on a persistent mount and writable. Its current production value and persistence are unconfirmed. |
| `MARKETING_ACQUISITION_REPORT_TOKEN` | Both services | The same private value of at least 32 characters. Set through the existing service secret/environment mechanism. No secret value belongs in Git, this report, screenshots, request URLs or logs. |
| `STAFF_MARKETING_REPORT_URL` | `garage-voice-agent` | `https://trimtechai.com/internal/staff-acquisition`, with no query string or embedded credential. It must reach marketing directly over HTTPS because redirects are rejected. |

The SQLite parent directory needs write permission for the database and SQLite journal files. The application creates `acquisition_daily` and `acquisition_collection` transactionally on its first successful counter write. The file itself need not exist in advance. No directories or disks are created by the code. Preserve the database file through redeployments and rollback. A relative path, missing parent or unwritable file makes counter data unavailable while the page and trial redirect continue to work. Collection starts at the first successful write, with no historical request backfill.

If no existing persistent mount is available, the operator must decide whether to approve storage provision or another durable storage approach separately. No paid-storage action is part of this local preparation. Persistent mounts and the shared token are configuration prerequisites for reliable request reporting. Existing database and dedicated platform-owner credentials remain in place.

### Existing business-contact schema check

The deployed baseline already contains `business_contact_migration`, version `20261104_staff_business_contact_v1`. Name edits work without `sd_contacts`. Contact-email editing requires that table and a valid `sd_schema_migrations` record/fingerprint. This release does not add or change that migration.

Production schema status remains unverified. The current environment exposes no authenticated production database connection. The browser access host was also unavailable on the read-only access check. The precise remaining operator check is to run the following read-only code in the existing Staff service environment, using its existing connection settings and tenant schema/search path. It prints only schema availability/verification status and executes no migration.

```python
from trimtech.modules.staff.database import transaction
from trimtech.modules.staff import business_contact_migration

with transaction() as connection:
    connection.set_session(readonly=True)
    with connection.cursor() as cursor:
        present = business_contact_migration.present(cursor)
        print("Contact table present:", present)
        if present:
            business_contact_migration.verify(cursor)
            print("Contact migration checksum and schema fingerprint verified")
```

If the table is absent, report that contact-email editing requires the existing migration `python -m trimtech.modules.staff.business_contact_migration` in a separately authorized migration step. If it is present but verification fails, inspect that inconsistency before any migration decision. No production migration is authorized by this preparation. Existing complimentary/registration-review migration SQL is unchanged.

## Validation

All final checks passed across focused runs, with 98 distinct tests and no skips.

- 35 marketing tests passed, including five new counter tests, existing Staff-page checks and demo-security regressions. Checks cover real SQLite writes, concurrency, restart persistence through new connections, storage failure, authenticated reporting, date coverage, GET/HEAD behavior, fixed redirect, route inventory and preserved product sections.
- 43 Staff checks passed across the initial run and a focused rerun of the changed count expectation. These include eight initial acquisition tests, existing business-editor/contact-migration checks, complimentary access, registration review, Control Centre summaries/authorization, subscription safeguards and access isolation. The count expectation was corrected while the original test process had already loaded its earlier value. Its focused rerun passed.
- 18 existing registration-protection checks passed, including successful signup, replay/duplicate rejection, challenge behavior and email verification gating. They reuse the unchanged signup code.
- Two additional focused tests passed for authenticated cross-service aggregate reporting and one verification shared by multiple workspaces.
- After moving malformed-URL validation inside the reporting failure handler, its three unit tests and the normal owner-report/date/CSRF test passed again. These reruns are included in the 98 distinct-test total.
- Both candidate worktrees passed `git diff --check`. The Staff route-registration diff contains only three added lines, preserving baseline line endings. Garage AI, PayChaser and other unrelated source changes are excluded from these diffs.

Initial marketing test attempts exposed an incorrect working directory, Windows test-only SQLite handles left open, and existing route-inventory expectations. Those test harness issues were corrected before the 35-test passing rerun. Production data was never used. Local PostgreSQL tests use disposable schemas on loopback port 55449. The runner blocks non-test PostgreSQL connections and outbound Python sockets, with provider calls mocked or disabled.

Reproduction from the main workspace uses `.release-validation/venv/Scripts/python.exe .release-validation/run_acquisition_checks.py` followed by the desired Staff test modules. Marketing tests run from the marketing candidate's `ai-receptionist-engine` directory with the same interpreter and `-m unittest marketing_site.test_acquisition marketing_site.test_staff_marketing marketing_site.test_demo_security`.

A live authenticated production UI check and real-browser layout validation remain unperformed because browser access failed. Local normal-entry Flask route tests cover rendering, filtering and authorization.

## Deployment order for a future authorized release

All steps below describe a future release. No push, merge, deployment, production migration or environment update was performed during this preparation.

1. Use the full candidate SHAs recorded above and inspect their scoped diffs against the full baselines. The operator supplied Auto-Deploy Off on both services. Preserve the supplied roots and `gunicorn app` start commands. Preserve existing build settings. Before a future deployment, check whether either live baseline has advanced since the operator's 12 November evidence and reconcile only if it has.
2. Resolve the outstanding marketing mount/path and instance-count checks, shared-token configuration, Staff report URL and read-only contact-schema check. Contact-table absence gates contact-email editing. It does not gate name editing, archive controls or acquisition reporting. Any storage purchase, production setting update or migration remains a separately authorized operator action.
3. After separate push/deploy authorization, release marketing candidate `754b6269f146613bdd28ebd617377991340e96e8` first. This installs the fixed redirect, SQLite counters and authenticated aggregate endpoint. Confirm the selected persistent path survives service restarts through the normal storage controls. A successful collection request creates its first collection timestamp. Use isolated staging for write-based validation before production release.
4. Release Staff implementation candidate `c107c390c24d9548a2853d227aa1e78a8851cda6` second. The owner report reads the newly available marketing aggregate endpoint. Either service can be deployed independently without blocking signup, and Staff displays unavailable request metrics while marketing is unconfigured or absent. Marketing-first is the chosen order so the report can have a functioning source at Staff rollout.
5. Record each successful deployed full SHA. Verify ordinary public pages, fixed redirect destination, owner-only report access, date filters and unavailable-history labels. Confirm unauthorized sessions are denied and check Garage AI, Staff Manager and PayChaser entry points after the shared Staff service restarts. Exercise business edits, archiving/restoration and signup mutations on isolated staging data. A production smoke test must follow the operator's separately authorized scope.

## Rollback steps for a future authorized release

1. The recorded preceding marketing revision is `d428f8114fd65a287e25c5e68526b042b88f88ab` and the preceding Staff revision is `0ee3cf5b8286a5417469f4775d0abffc22a754c0`, based on the operator's 12 November Render evidence. Preserve the current database, secrets, storage file and effective service settings when selecting a rollback mechanism. An artifact rollback can carry its older settings, so check those against the recorded service configuration before executing it.
2. Marketing can roll back to its recorded baseline. Retain the persistent SQLite database and its history. The old marketing page uses its original direct registration links. If the aggregate endpoint disappears, Staff renders request metrics as Unavailable.
3. Before reverting Staff after any archive actions, prepare a compatible fallback revision from the recorded Staff baseline that retains archive interpretation and the registration-review archive-reactivation guard. Baseline code counts inactive rows again and its review action can reactivate an archived account. Existing early-trial-ending and deactivation enforcement must also be retained. When no archive actions have occurred, document that fact before choosing the unmodified baseline as a rollback target.
4. Retain business records, operational active flags, trial timestamps, billing records and the audit ledger. Application rollback requires no database restore or row deletion. Existing `sd_contacts` can remain if its pre-existing migration was separately applied. No rollback step drops its table or the SQLite counter tables.
5. If collection must pause, the operator can remove/disable counter configuration through the normal authorized settings process while retaining the history file. Verify ordinary login and product health after the rollback.

## Release readiness and remaining operator checks

Local implementation, scoped commits, baseline reconciliation and test reuse are complete. Production revisions are established on operator-provided Render evidence and independently mapped to full local Git SHAs. They are not being described as a fresh authenticated Render API inspection.

The remaining operator inputs are specific.

- Confirm a persistent mount already available to `trimtech-ai`, its actual path, marketing process write permission and service instance count. If none exists, decide separately whether durable storage provision is approved.
- Confirm/configure the marketing SQLite filename, the shared secret on both services and the Staff-only aggregate report URL. Existing production values were not read or changed. Secret values should be entered through service settings without posting them in the conversation.
- Provide the read-only contact-schema check result. If absent, contact-email editing needs a separately authorized application of the existing migration. Name edits and the other release features do not require that table.
- Authorize any later push, merge, configuration action or deployment separately. This preparation stops with local commits.

No current-baseline rebase is required on the supplied evidence. The implementation candidates match their respective deployed baselines and contain only this task's scoped changes. Browser layout/device validation remains unperformed. Normal-entry local Flask route rendering, authorization and the existing 98 checks passed.
