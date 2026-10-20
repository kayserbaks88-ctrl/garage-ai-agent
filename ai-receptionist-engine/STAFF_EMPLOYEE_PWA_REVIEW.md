> Deployment 2 update, 20 October 2026: reconstructed on live compatibility commit e9b868ca47bb4b94d3d8173b75318f284fd2d1c1. See STAFF_PWA_DEPLOYMENT2.md for current ancestry, scope and rollback instructions. The baseline and 27-file counts below describe the sealed historical candidate.

# Staff Manager shared PWA: current isolated release candidate

19 October 2026. Local candidate prepared and tested; PRODUCTION BLOCKED. No release commit exists and no commit, push, merge, migration or deployment is authorised by this record.

Service: garage-voice-agent. Baseline: 4b29900c6705acefc11410d852b060378eb6459f. Branch: staff-permissions-subscriptions-release-20261017. Root: ai-receptionist-engine. Build: pip install -r requirements.txt. Pre-Deploy: empty. Start: gunicorn app:app. Auto-Deploy: Off. These values were visually verified by the operator on 19 October 2026; no settings were changed here.

This candidate is the live baseline plus EXACTLY 27 files: 18 runtime assets/modules/templates, seven tests/tools and two documents; 18 additions and nine modifications. All other 253 files retain the live Git content after the repository's normal Windows line-ending conversion. Marketing changes, local credentials, tunnels, databases and QA artifacts are excluded. The old 23-file employee-only candidate and instructions in the historical record below are superseded.

Fresh candidate tests: 88/88 passed on isolated PostgreSQL 18.6, zero failures/errors/skips. The runner verified 57 Staff/test module paths belonged to this candidate. No test schemas remained and the cluster stopped. Coverage includes PWA role/session routing, expired/revoked access, employee recovery, login/logout, CSRF, cross-business rejection, exact 14-day trials without extension, subscription/platform permissions, payroll and payslip isolation. Earlier full source regression: 290/290 passed; runtime and test files remain byte-identical to that audited source.

Fresh candidate browser tests: 72 navigation/layout checks and 20 worker safety cases passed; 32 Manager page/viewport pairs preserved controls and had no horizontal page overflow; all eight desktop layouts matched the baseline. All 24 mobile menu combinations passed at 375, 393 and 430px with at least 48px targets. An initial QA harness run timed out at 120 seconds; a rerun with bounded command diagnostics and a 360-second overall layout limit passed. No application code was changed to address the harness timeout. The temporary candidate preview stopped. These synthetic browser screenshots do not establish populated-screen or physical-device acceptance.

Employee and Manager PWA use the real Staff blueprint and existing authentication/membership checks. Manifest identity/start URL is /staff/employee/app, scope /staff/, display standalone, Staff Manager name and green S icons. Employee-only opens its dashboard; Manager-only opens the existing authorised business selector; both sessions get an explicit chooser; logged-out users sign in. Test session shortcuts exist only in the synthetic helper, never in the real application entrypoint.

No private cache, offline clocking/payroll submission or queued/replayed actions. Worker uses network fetches and a generic public offline page on allowed navigation failures. All POST, GPS/API, payslip downloads and sensitive non-navigation actions remain network requests. Offline browser tests rejected submission before GPS, showed no private offline content or forms, reconnected successfully and left CacheStorage/IndexedDB empty.

No new dependency, environment variable, schema migration or backfill. Preserve existing session secrets, proxy configuration, database URL, platform credentials and STAFF_STRIPE_ENABLED=0. Stripe, trial/registration implementation, payroll calculations, manager permissions, Garage Voice and PayChaser code remain unchanged. The three existing test-file changes repair fixtures, not live billing/authentication code. Shared service restart still requires other-product smoke checks after any authorised release.

Remaining gates: Android physical install/standalone/navigation/offline acceptance; post-polish iPhone menu/VoiceOver and populated screens; dense rota, approvals, leave, staff and payroll/payslip layouts; real-auth workflows on an isolated synthetic database; read-only production-origin worker registration inspection; installed-app rollback/support decision; and explicit approval of a later exact release commit. The configuration-verification gate is now closed by the operator's visual confirmation above.

Baseline source contains no serviceWorker.register or Service-Worker-Allowed setting. That does not establish existing registrations in production browsers: inspect the actual production HTTPS origin in desktop browser DevTools > Application > Service Workers, recording scopes and script URLs. Do not unregister, update, clear storage or change settings during that check.

After separate approval: use a clean checkout from the reverified live SHA; overlay ONLY this candidate's 27 files, review complete diff and ancestry, test the clean release, then commit/push only when explicitly authorised. Stop for exact-SHA deployment approval. In Render use Manual Deploy > Deploy a specific commit; preserve the verified existing settings and run no migrations/backfills. Do not deploy latest commit or merge unrelated branches. Current candidate hashes and test evidence are in its companion manifest/report, outside the release tree.

Rollback target is the verified pre-release baseline above (recheck it before release). After approval, redeploy that exact baseline with verified current settings; inspect any retained artifact's configuration before using artifact rollback. No database restore or trial reset. Preserve early-trial-ending audit checks and business deactivation safeguards. Baseline lacks the new launcher/worker endpoints: installed icons can open 404 and workers can remain registered. Users can fall back to /staff/account or /staff/<workplace>/employee. Before rollout, explicitly accept this support limitation or separately approve a compatibility/retirement release using the SAME /staff/employee-sw.js URL. No retirement worker or compatibility patch is included here. Offline devices cannot update immediately. Existing ngrok icons remain synthetic; remove them before installing from the production origin after approval.

Authoritative file list relative to ai-receptionist-engine (A added; M modified):

```text
A STAFF_EMPLOYEE_PWA_DEVICE_CHECKLIST.md
A STAFF_EMPLOYEE_PWA_REVIEW.md
A static/staff-pwa/apple-touch-icon.png
A static/staff-pwa/icon-192.png
A static/staff-pwa/icon-512.png
A static/staff-pwa/maskable-512.png
A static/staff-pwa/offline.html
A static/staff_pwa.css
A static/staff_pwa.js
A static/staff_pwa_sw.js
M templates/staff_account.html
M templates/staff_agency.html
M templates/staff_base.html
A templates/staff_employee_app.html
M templates/staff_employee_base.html
M templates/staff_employee_login.html
A templates/staff_manager_mobile_nav.html
A templates/staff_pwa_head.html
M test_staff_checkout_tax.py
M test_staff_employee_recovery.py
M test_staff_launch_checks.py
A test_staff_pwa.py
A test_staff_pwa_integration.py
A tests/check_staff_pwa.ps1
A tests/staff_pwa_preview.py
A trimtech/modules/staff/employee_pwa.py
M trimtech/modules/staff/routes.py
```

---

# Historical development evidence (superseded release/settings instructions)

# Staff Manager shared Employee + Manager PWA â€” local review

## Current shared implementation â€” 19 October 2026

**LOCAL DEVELOPMENT ONLY. Production release BLOCKED.** The sections below this current update retain earlier employee-only evidence and the historical sealed candidate; that 23-file candidate/whitelist is not the current shared release and must not be deployed or staged unchanged.

One manifest retains identity/start URL `/staff/employee/app`, scope `/staff/`, standalone display, and the existing green S icons. The installed name is **Staff Manager**. Shared Apple metadata and `crossorigin="use-credentials"` incorporate the physical iPhone mock lessons. Existing installations may require removal and reinstallation to replace their help-page launch snapshot.

The real launcher has no hardcoded workplace or mock credentials. It validates employee identity using the existing active-status, credential-version, expiry and tenant checks. Manager-only launch delegates to the existing account/business selector. Simultaneous validated sessions get an explicit role chooser; logged-out users choose a sign-in path. Role and workplace URL parameters only select destinations: destination guards still enforce authentication and membership. Manager and employee cookies/sessions, expiry, CSRF, subscription restrictions and audit implementations are unchanged. An unavailable identity lookup returns 503 rather than opening a dashboard.

Manager PWA metadata and mobile help/workspace navigation are additive. Existing desktop controls, forms, reports, payroll and administration remain present. `staff_agency.html` has an independent head; the operator separately approved adding that template to scope. Its forms and desktop layout are preserved. No registration template, Stripe logic, schema, payroll calculation or manager permission code was changed.

Offline safety: no CacheStorage, IndexedDB, localStorage or action queue was added. The worker only returns the embedded public offline document for allowlisted HTML navigations when the network fails. Every POST, GPS/API request, payslip/download, subscription/platform route and onboarding mutation remains a network operation. Offline submit handlers block forms before GPS/submit handlers. The preview CSP remains enforced; the test harness was adjusted rather than allowing unsafe-eval.

### Verification and evidence

**Follow-up scope confirmation, 19 October 2026:** `staff_agency.html` remains within the explicitly approved scope. Reversing only its shared-head include, hidden offline status and mobile navigation additions reproduces the baseline template exactly; its original assignments, rota, work-site forms, scripts and desktop markup are unchanged. All 36 protected file fingerprints still match.

The reported PostgreSQL failure was `test_staff_pwa_integration.EmployeePwaIntegrationTests.test_expired_and_inactive_sessions_never_open_a_dashboard`, with `AssertionError: 302 != 200`. The fixture changed a nested session dictionary without marking the Flask session as modified, so the browser retained an unexpired session and correctly received a dashboard redirect. Reassigning the session value persists the intended expired timestamp. A fresh follow-up run on PostgreSQL 18.6 passed **21/21 tests, zero failures/errors/skips**, including this case. The disposable cluster stopped and no test schemas remained. Evidence: `.release-validation/pwa-integration-6a800b3d3898416eb8fe6004cf4a42de/report.json` and `tests.log`. No further application-code correction was needed. No production access, commit, push, application migration command or deployment occurred. Physical iPhone testing has not been started for the shared build.

- Full isolated PostgreSQL 18.6 run: **289 tests, 288 passed, one new expiry-fixture failure, no errors/skips**. The test mutated a nested Flask session dictionary without persisting it; corrected by assigning the session value. No authentication defect was implicated.
- Focused PostgreSQL rerun: **21 passed, zero failures/errors/skips**, including real separate sessions, simultaneous roles, expired/inactive employees, expired managers, revoked business membership, cross-business denial, recovery, clocking, breaks and existing employee tools. Fresh loopback-only cluster/database identities were asserted; outbound provider connections were blocked; test schemas were removed and clusters stopped. Fixture schema setup was confined to disposable test databases; no production migrations or database operations occurred.
- Final focused unit run: **48 tests, zero failures, six database-dependent skips**; those cases were covered by the broader PostgreSQL run. Employee/PWA unit subset: **17 passed**.
- Eight baseline/shared manager page pairs rendered with synthetic fixtures. Desktop browser measurements matched all eight at 1440px; existing form/action/link contracts matched all sixteen mobile/desktop pairs; no page overflow at 393px or 1440px. Readiness checks were corrected for cold browser startup and the independent Assignments main element.
- HTTPS synthetic tunnel: all four role states returned their expected destinations; ten unauthenticated resources/entry points (including in-scope synthetic mode links) returned 401; another business returned 404; submissions returned 409. Database/Stripe blocks and disabled optional traffic inspection were confirmed. No real accounts, records or provider calls are exposed.
- Final fresh-browser run: **72 layout/navigation checks and 20 worker safety cases passed**. Worker activated and controlled the page; offline submission was blocked with zero GPS calls; offline navigation returned a generic page with no forms/private employee content; reconnect recovered; CacheStorage and IndexedDB were empty. Evidence: `.release-validation/shared-browser-results.json`. The older PowerShell/CDP harness hit startup/event/diagnostics issues; final validation used a separate timeout-protected fresh-browser driver. No preview CSP was weakened. Physical shared-app iPhone and Android acceptance remains pending.
- Thirty-six previously fingerprinted protected marketing, other-product and billing/script files matched their recorded hashes. `git diff --check` passed. Existing unrelated working-tree changes were retained and must not be staged wholesale.

Local evidence: `.release-validation/pwa-integration-be77e24a995f4d8f9d469197eab20236/report.json` (broad run), `.release-validation/pwa-integration-83bbb97d93b24da1a9fbbb997067f16a/report.json` (focused rerun), `.release-validation/shared-pwa-layouts/summary.json`, `.release-validation/shared-tunnel-verification.json`, `.release-validation/shared-pwa-protected-check.json`. Ignored logs/profiles/test clusters are QA artifacts, not release files.

### Exact files edited in this shared implementation

All paths are relative to `ai-receptionist-engine/`:

```text
trimtech/modules/staff/employee_pwa.py
templates/staff_pwa_head.html
templates/staff_employee_app.html
templates/staff_employee_base.html
templates/staff_employee_login.html
templates/staff_base.html
templates/staff_account.html
templates/staff_agency.html
static/staff_pwa.css
static/staff_pwa.js
static/staff_pwa_sw.js
test_staff_pwa.py
test_staff_pwa_integration.py
tests/staff_pwa_preview.py
tests/check_staff_pwa.ps1
STAFF_EMPLOYEE_PWA_REVIEW.md
STAFF_EMPLOYEE_PWA_DEVICE_CHECKLIST.md
```

### Remaining release gates

Reconfirm the **current** Render full SHA; the last operator-confirmed live baseline and current local HEAD remain `4b29900c6705acefc11410d852b060378eb6459f`. Record the exact Build Command and confirm Pre-Deploy is empty. Preserve Auto-Deploy OFF, `STAFF_STRIPE_ENABLED=0`, root/start settings and existing credentials. No new environment variable, dependency, migration or backfill is required by the PWA.

Finish fresh-install/standalone/logout/session-expiry/offline/reconnect acceptance for employees and managers on physical iPhone and Android. Synthetic preview mutations are deliberately blocked; real mutation/regression coverage belongs in isolated PostgreSQL tests, not a public tunnel. Re-review dense forms, populated shift evidence and payroll records on devices; empty-state screenshots do not establish every populated layout.

After separate authorization, regenerate a clean release candidate and complete baseline diff/whitelist, excluding unrelated work and all mock helpers from production imports. There is no proposed shared release commit yet. Commit/push/deploy require further approval. Deploy only a specifically approved SHA. Preserve the earlier permissions/subscriptions rollback caveat and the same-worker-URL installed-app retirement/compatibility plan below; a web rollback cannot instantly remove an installed worker or repair a saved icon. No database restore belongs to a PWA rollback.

## Historical employee-only phase evidence

Updated 18 October 2026. **Production baseline and principal Render settings confirmed by the operator; production release remains BLOCKED pending Build Command review, final empty Pre-Deploy confirmation, physical-device validation and release approval.** No PWA commit, push, deployment or production environment/data change was performed. No migrations ran during final cleanup, candidate preparation or this settings/device-plan update. Earlier fresh local test clusters and fixture migrations were used only for the previously authorized isolated PostgreSQL tests.

## Baseline and scope

- Local base: `4b29900c6705acefc11410d852b060378eb6459f` on `staff-permissions-subscriptions-release-20261017`.
- Operator-confirmed production baseline: Render service **`garage-voice-agent`**, latest successful live commit **`4b29900`**, deployed **17 October 2026 at 18:08 UK time**. Git resolves that abbreviation uniquely to **`4b29900c6705acefc11410d852b060378eb6459f`**. This is the Staff application baseline, not the marketing website's revision. No authenticated Render API check was performed; deployment identity/time are operator-provided evidence.
- Current local HEAD equals the full production baseline. `git merge-base --is-ancestor 4b29900 HEAD` succeeds and `git rev-list --count 4b29900..HEAD` is zero. The candidate is built by exporting that exact commit and overlaying only the approved 23-file whitelist into an isolated snapshot. **No proposed PWA release commit exists yet** because committing is prohibited. Its intended direct parent is the verified baseline; ancestry to the eventual release SHA must be checked again after a commit is separately authorized and created. A content fingerprint is not a commit SHA.
- Whole-repository comparison: 262 baseline files, 279 candidate files, **6 modified and 17 added**, no deletions, and **256 existing files byte-for-byte identical**. Files are compared in checkout-independent form with Git-compatible text line-ending normalization. Garage Voice, PayChaser, Staff billing/webhooks/pricing, subscription/permission modules, payroll calculations, manager authentication, registration, onboarding, existing GPS handlers and deployment/dependency files are unchanged. The existing Staff route implementations are identical; only the PWA module registration is added.
- The operator has now confirmed this Staff service's branch, root, Start Command, Auto-Deploy state and billing flag as recorded below. Build Command is still unverified; Pre-Deploy appears empty but needs final confirmation. No settings were read through authenticated Render access or changed here. Do not execute historical joining-migration instructions for this PWA delta.
- Existing unrelated marketing and Stripe-script working-tree changes were left untouched.

### Render settings recorded from the operator

| Setting | Recorded value | Evidence/status |
| --- | --- | --- |
| Service | `garage-voice-agent` | Operator confirmed |
| Live commit | `4b29900c6705acefc11410d852b060378eb6459f` | Operator confirmed short SHA; full SHA resolved locally |
| Linked branch | `staff-permissions-subscriptions-release-20261017` | Operator confirmed |
| Auto-Deploy | **Off** | Operator confirmed for this Staff service |
| Root directory | `ai-receptionist-engine` | Operator confirmed |
| Start Command | `gunicorn app:app` | Operator confirmed; preserve |
| Pre-Deploy Command | Appears empty | Final blank-field confirmation pending; do not edit it |
| Build Command | **Not yet verified** | Copy exact text from Render Settings and review it, including any script it invokes; do not assume a standard pip command |
| `STAFF_STRIPE_ENABLED` | **`0`** | Operator confirmed; preserve |

Build review must establish that the command installs/builds only the existing app and does not invoke migrations, backfills, provisioning, unrelated Stripe scripts or production data operations. Also check whether it calls another script with those side effects. Do not modify the command or run it to discover its behavior. No PWA dependency/build step is required. No deployment can be approved while this evidence is missing.

This settings/staging-plan update changes only this review and `STAFF_EMPLOYEE_PWA_DEVICE_CHECKLIST.md`; the other 21 approved release files are unchanged. The previous sealed manifests/patch and document versions are archived under the candidate folder's `revisions/before-render-settings-record/`. The candidate is resealed with updated documentation; the earlier 67 passing regressions and 32/11 browser checks remain evidence for identical runtime/test logic and were not rerun for Markdown-only edits. No HTTPS setup, certificate generation, phone configuration, firewall modification, database operation or migration was performed. The local operator settings record is workspace `.release-validation/pwa-render-settings-record.json`.

## Employee experience

- Launch URL: `/staff/employee/app`. Enter the workplace code supplied by the manager; continue to the existing tenant employee login. This public page does not identify accounts, query a business or create sessions. It does not remember workplace codes.
- Install guidance: `/staff/employee/app/install`. iPhone Safari instructions and Android browser instructions; Android install button appears only when the browser offers installation.
- Manifest: `/staff/employee/app/manifest.webmanifest`. Standalone display, navy theme, branded 192/512 PNG icons, maskable icon and Apple touch icon. Operating-system splash presentation is derived from the manifest/icons; the app itself opens the branded launch page.
- Employee pages retain their existing forms and routes, with install help and a small-screen Clock / Rota / Hours / Pay / Leave navigation bar. Existing tools remain available.
- Login credentials, eight-hour employee sessions, credential-version checks, CSRF and logout behavior are unchanged. Installing may require signing in again in the installed app.

## Security decisions

- No CacheStorage, IndexedDB, localStorage, background sync or action queue is introduced. The browser stores the public worker code and install metadata as required for installation; that code contains only the generic offline document.
- Worker `/staff/employee-sw.js` has default `/staff/` scope because existing employee URLs span business slugs. Registration is only added to employee pages and the public app pages. The fetch handler has a narrow URL allowlist, GET-only and navigation-only checks.
- Employee page navigation uses `fetch(..., {cache: 'no-store'})`. Existing server-side `Cache-Control: no-store` remains. Failed network navigation produces an embedded generic 503 reconnect screen containing no employee data.
- Payslip view/download requests, GPS/presence calls, all POSTs, manager pages, registration, onboarding and billing are not intercepted by the worker. Existing payslip privacy headers and tenant/employee SQL predicates remain.
- The client blocks forms when the browser reports offline, before existing GPS handlers. It never records or replays an action. A connection loss during a request still requires checking the server's current shift state before retrying; no automatic retry was added.
- Existing GPS freshness, accuracy/radius rules, server timestamps, manager approvals and payroll calculations are unchanged. Existing optional foreground presence behavior is unchanged. Photo-required sites retain their existing portal restriction.
- No new environment variables, packages, schema changes or backfills are needed for this PWA code. Stripe and its existing flag were not changed; the operator has confirmed the production flag is `0`, without disclosing secrets or an independent runtime inspection by this agent.

## Validation

### Candidate verification against the confirmed production baseline

An isolated snapshot at workspace `.release-validation/pwa-release-candidate-4e5c64c465a24096bd33cae400ed2570/candidate/` contains the complete production-baseline repository plus only the 23 approved files. It is not a Git checkout with a new commit. Its parent baseline is `4b29900c6705acefc11410d852b060378eb6459f`; no intervening commits, deletions, unrelated edits or untracked source assets were included.

Fresh checks executed from that isolated candidate: **67/67 regression tests passed**, zero failures/errors/skips, with database and external application network connections blocked; **32 responsive browser checks** at 360/393/768/1440 pixels and **11 worker isolation checks** passed. Offline form submission was blocked before GPS capture, navigation displayed the generic no-data reconnect screen, and CacheStorage/IndexedDB were empty. No migrations ran and no production entrypoint or production service was accessed. After these checks, the final review text was synchronized and one redundant blank line at the browser test helper's end of file was removed. Runtime and test logic are unchanged.

The same workspace candidate folder contains `regressions.log`, `regressions.json`, `browser-results/results.json`, `release-files.txt`, `release-files.json`, `proposed.patch` and the final `scope-audit.json` with content fingerprints. These are local review artifacts excluded from the release tree. The exact proposed Git commit SHA remains unavailable until committing is separately authorized; the eventual SHA must pass the ancestry and full-diff checks in the deployment plan.

Excluded working-tree work includes all modified/untracked marketing website pages, photos, demo-form security changes/tests and credits, plus `staff-stripe-corrections.ps1`. Baseline marketing/product files remain intact. Ignored recovery archives, databases, credentials, browser profiles, logs and candidate-building tools are not included in the proposed release.

Migration-free tests: from `ai-receptionist-engine`, run with an interpreter that has the project's existing test dependencies:

```text
python -m unittest test_staff_checkout_tax test_staff_billing.GatewayTests test_staff_pwa test_staff_payroll test_staff_locations test_staff_account_ui test_staff_employee_recovery test_staff_launch_checks
```

Latest focused result: **67 tests passed, zero failures/errors/skips** after the employee login and checkout-tax fixture corrections described below. This includes both checkout-tax tests, both mocked Stripe gateway tests and the previous 63-case PWA/authentication/payroll regression set. This run blocked both PostgreSQL connections and external application network access, ensuring these are migration-free unit/mocked-route checks. All 13 PWA tests passed, as did payroll, location, account presentation, recovery and launch/session checks. They cover secure employee login/password matching, logout/CSRF, valid and invalid GPS clock-in, clock-out, breaks, hours/rota/pay/leave rendering, tenant isolation, scoped payslip access and pending holiday/shift approval. Evidence: workspace `.release-validation/checkout-tax-after.log` and `.release-validation/checkout-tax-after.json`; the prior 63-case result remains in `.release-validation/pwa-focused-tests.log`.

Recovery failure investigation: `EmployeeRecoveryRouteTests.test_new_password_sign_in_uses_employee_credentials_in_the_same_tenant` expected a redirect but got 401. Its catch-all lookup mock returned an ID for the `NOT active` business query, so login correctly rejected the simulated inactive business. The same failure was reproduced using unchanged HEAD routes and templates loaded in memory. **Resolved in the test only:** return no inactive-business row, return the active-business row explicitly, assert the tenant parameter, and fail on unexpected SQL. A new negative test confirms that a valid recovered password still cannot log in to a deactivated business. Production authentication code was not changed.

The broader run found the same fixture defect in `EmployeeIdentifierTests.test_email_and_phone_login_create_the_same_employee_session` (`test_staff_launch_checks.py`). Its catch-all business mock was corrected in the same way. The entire launch-check module was then rerun with external network access blocked: **12/12 passed**, including manager cookie persistence, expiry, revocation, logout/employee-session separation, employee identifier normalization and trial gates. This fixes test setup only; it does not bypass inactive-business rejection. The broader run had already loaded the old fixture before this correction, so its original failure and the successful targeted rerun are reported separately.

New real-database coverage: both tests in `test_staff_pwa_integration.py` passed on PostgreSQL 18.6 using synthetic data in a fresh localhost-only database. They verify password recovery, wrong-tenant token rejection, replay rejection, old-session invalidation, old/new password behavior, logout and manager boundaries, plus GPS clocking, breaks, hours, rota, pay and leave rendering with PWA links. Email transport was mocked. An initial failure in this new test's nested Flask session setup was fixed by explicitly assigning the updated session dictionary; no application change was needed.

Isolation: connection guards allow only the exact generated local database/role at `127.0.0.1` and the allocated test port. Dotenv loading and outbound Python application connections are blocked. There was no restored production dataset. Fixture schema creation/migrations occurred inside the disposable test clusters only. Disposable clusters use non-durable settings for test speed; crash recovery/durability is not being validated. Both completed runs removed all their test schemas and stopped their clusters.

Full PostgreSQL-backed Staff regression run: **282 tests, 280 passed, one failure, one error, zero skips**. This includes both real-database and unit tests; it is not a claim that every case performs SQL. The failure was the already-loaded old launch fixture subsequently corrected and verified in the green 63-case focused rerun. The error was the outdated checkout-tax fixture subsequently corrected in the green 67-case focused rerun described below. The two new database tests were added after full-suite discovery, so they ran separately and both passed. The full database suite was not repeated after these fixture corrections; affected tests and focused regressions were rerun instead. No migrations were run during final checkout fixture cleanup.

No regressions were detected in the exercised employee/manager functionality: login/logout and sessions, GPS clocking, breaks, timesheets, weekly rota, payslip viewing/downloading, holidays and approvals, manager navigation/registration/onboarding, tenant isolation, payroll calculations, trial/deactivation controls and preserved owner credentials/memberships. This is local synthetic-data evidence, not verification of live customer accounts or physical-device behavior.

Evidence folders (relative to the workspace):

- `.release-validation/pwa-integration-44696013189942c283ebee6399190063/`: full-suite `tests.log` and `report.json`, PostgreSQL 18.6, `127.0.0.1:55528`, database `staff_pwa_5d7948694d12444b8e03ae20c6c97774`.
- `.release-validation/pwa-integration-9754d8663fc143c9843a0b2e9e942bda/`: successful two-case integration `tests.log` and `report.json`, PostgreSQL 18.6, `127.0.0.1:55529`, database `staff_pwa_8cbde7443253425da84fcf492d8a65a5`.
- `.release-validation/pwa-focused-tests.log`: successful 63-case rerun with database and outbound network connections blocked.

The ignored `.release-validation/run_pwa_integration.py` local harness creates a fresh cluster/database for each run and pins database connections to that identity before discovering tests. No application production entrypoint was started. Initial sandbox startup was refused by Windows token restrictions and was retried with permission for the isolated local process. An initial new integration-test session-fixture mistake was corrected before the successful targeted run; failed-run logs were retained separately for audit.

### Checkout-tax fixture cleanup: resolved locally

Exact test: `test_staff_checkout_tax.CheckoutTaxTests.test_unregistered_staff_checkout_preserves_billing_parameters`.

Reproduced before editing with PostgreSQL and external network access blocked. The original traceback is retained in workspace `.release-validation/checkout-tax-before.log`:

```text
File "test_staff_checkout_tax.py", line 42, in test_unregistered_staff_checkout_preserves_billing_parameters
    billing.checkout('alpha', 'owner')
File "trimtech/modules/staff/billing.py", line 182, in checkout
    _checkout_business_lock(cursor,business_id)
File "trimtech/modules/staff/billing.py", line 170, in _checkout_business_lock
    if not business or not business['active']:
KeyError: 'active'
```

Finding: **outdated database cursor fixture, not a Stripe response mismatch or application defect**. Both checkout transactions first execute `SELECT active FROM sm_businesses WHERE id=%s FOR SHARE`. A real result therefore contains `active`; the old mock supplied checkout-attempt dictionaries for every `fetchone()` call. Its two-item sequence also omitted the second transaction's business row.

| Cursor fetch | Application expects | Corrected fixture |
| --- | --- | --- |
| 1 | Business row, first transaction | `{'active': True}` |
| 2 | Checkout attempt, first transaction | Existing `attempt` |
| 3 | Business row, second transaction | `{'active': True}` |
| 4 | Checkout attempt, second transaction | Existing `attempt` |

Compared with the installed Stripe SDK **16.0.0** and the existing gateway response handling: a Checkout Session exposes `id`, `status` (`open`/`complete`/`expired`), `url`, `mode`, `customer`, `livemode`, metadata and subscription. Its model does not define `active`; that field does exist on Stripe Price, which is a separate object. The existing `FakeStripe.create_checkout()` returns the session fields consumed by this flow, including `status='open'` and a Checkout URL. Neither its response nor the Stripe price fixture needed changing. This comparison used the installed SDK locally; no Stripe account/API call or SDK upgrade was performed.

Smallest correction: change only `cursor.fetchone.side_effect` from `[attempt, attempt]` to `[{'active': True}, attempt, {'active': True}, attempt]`, with a comment explaining the transaction order. Do not add `active` to the Stripe session, weaken the inactive-business check or mock out the business-lock helper. All original checkout parameter assertions remain, including automatic tax disabled, subscription mode, server-chosen price, metadata bindings, address collection and idempotency key.

Results: **67/67 passed**, zero errors/failures/skips, including the two affected checkout-tax tests and two gateway tests. PostgreSQL connections, external Python network connections and dotenv loading were blocked throughout the run. No database was started, no migrations ran, and no live checkout, pricing, subscription or webhook behavior was modified. Only `test_staff_checkout_tax.py` and this review changed during final cleanup. The earlier full PostgreSQL evidence remains valid for unchanged application code, but its historical failed result is not rewritten as a newly executed all-green full suite.

Browser QA: **32 page/viewport checks passed**, at 360, 393, 768 and 1440 pixels, using real templates with mocked employee data. **11 worker interception/isolation cases passed**. Real worker-controlled offline navigation showed the generic document; offline form submission was cancelled before GPS; CacheStorage and IndexedDB were empty. Login was checked while signed out. Desktop Chromium mobile emulation does not establish physical iPhone/Android install or GPS accuracy.

Reproduction tools: `tests/staff_pwa_preview.py` starts the loopback-only mocked preview on port 55510. It adds test-only `/qa/*` shortcuts and must never be used as the production entrypoint. Start a separate disposable headless Edge profile with remote debugging on port 55511, then run `tests/check_staff_pwa.ps1`. The browser script closes that browser instance. It requires Windows PowerShell and Edge; permit script execution for that invocation if local policy requires it. The preview uses no database and runs no migrations.

Local evidence: workspace `.release-validation/pwa-preview/results.json` and PNG previews. These are ignored QA artifacts, not product assets.

## Remaining release prerequisites and rollback risks

1. Verify the exact Build Command and any invoked scripts, and finally confirm the Pre-Deploy field is empty. Branch/root/start command, Auto-Deploy Off and billing flag `0` are now operator-confirmed. No settings changes are authorized. Recheck baseline/settings for drift immediately before any later push/deploy. No release branch or commit has been created for this PWA work, so eventual commit ancestry/SHA checks remain pending separate commit authorization.
2. Complete both stages of the local HTTPS device-test plan in `STAFF_EMPLOYEE_PWA_DEVICE_CHECKLIST.md`: mock installation/offline testing first, then real employee workflows against a disposable database after separately authorized test-only setup. Physical iPhone/Android acceptance is not yet complete. No HTTPS server, certificate, phone profile, firewall rule, test database or paid service was created by this planning update.
3. Confirm HTTPS delivers the manifest, icons and worker with correct content types, no login redirects and worker `no-store`; check for any existing same-origin worker/scope conflict in the real deployed browser environment.
4. Obtain release approval. Do not deploy as part of this local preparation.

## Exact deployment plan â€” future operator action only

No step below authorizes a commit, push, deployment, migration, database operation or settings change now. The isolated candidate is a review artifact, not a Render-deployable commit.

| Render item | Required action before a future release |
| --- | --- |
| Service | `garage-voice-agent`, operator-confirmed; use its existing Staff public domain |
| Linked branch | `staff-permissions-subscriptions-release-20261017`, operator-confirmed; do not advance it as part of preparing/pushing a separate PWA candidate |
| Root / start | `ai-receptionist-engine` / `gunicorn app:app`, operator-confirmed; preserve both |
| Build Command | Unverified: record and review exact text plus invoked scripts before approval; the PWA adds no build step or dependency |
| Pre-deploy and other commands | Pre-Deploy appears empty: confirm it is fully blank. No command may unexpectedly run a migration/backfill. If one would, stop for separate review; do not silently clear or edit it |
| Auto-Deploy | Off, operator-confirmed; preserve and recheck before any later authorized push |
| `STAFF_STRIPE_ENABLED` | `0`, operator-confirmed; preserve |
| `PLATFORM_ADMIN_USERNAME`, `PLATFORM_ADMIN_PASSWORD` | Preserve existing operator-confirmed credentials exactly; do not create, replace or rotate them |
| Database URL, session secrets, proxy trust, mail/public URLs, registration and other product/Stripe settings | Preserve all existing values. No PWA environment variables are required |

1. Finish physical iPhone/Android acceptance in an approved isolated HTTPS test environment using `STAFF_EMPLOYEE_PWA_DEVICE_CHECKLIST.md`. Review the known installed-app rollback limitation below. Confirm the Render settings above and record the verified current baseline.
2. Only after separate commit/push authorization, create a clean, dedicated release branch (proposed name `staff-employee-pwa-release-20261018`) directly from `4b29900c6705acefc11410d852b060378eb6459f`. Copy only the 23 whitelisted files from the sealed candidate, verify their content against its manifest, and commit using a Render skip marker as an additional safeguard. Do not stage the primary working tree wholesale or merge unrelated commits. This step has not been performed.
3. Record the full new release SHA. Require `git merge-base --is-ancestor 4b29900c6705acefc11410d852b060378eb6459f <release-sha>` to succeed; require the release's first parent to equal that baseline. Check `git diff --name-status <baseline> <release-sha>` against the exact 23-file list and rerun relevant checks if content changes. Push only the authorized dedicated branch after Auto-Deploy safety is verified; do not advance the live-linked branch. Stop for the operator's approval of the full SHA before deploying.
4. After explicit deployment approval, the operator opens **Render â†’ garage-voice-agent â†’ Deploys â†’ Manual Deploy â†’ Deploy a specific commit**, pastes the approved **full release SHA**, verifies it, then chooses **Deploy Commit**. Do not select Deploy latest commit. Render documents that this specific-commit dashboard action disables Auto-Deploy; that side effect must be included in the operator's approval. Use existing build/start settings; run no migrations/backfills and do not change environment variables. [Render deployment documentation](https://render.com/docs/deploys).
5. Verify the deploy shows the exact SHA and healthy startup. Read-only HTTP checks: health endpoint, `/staff/employee/app`, `/staff/employee/app/install`, `/staff/employee/app/manifest.webmanifest`, `/staff/employee-sw.js`, icon URLs, MIME types and no-store headers. Complete authorized owner-controlled sign-ins: Oakfield opens only its normal business dashboard, no platform link/access; the dedicated TrimTech administrator can open platform controls; employee sign-in, existing pay/rota pages and logout work. Confirm subscription settings load without starting provider actions. Check Garage Voice and PayChaser health and normal authorized access, since the shared service restarts even though their code is unchanged.
6. Do not use real clocking, payroll edits, trial cancellation, business deactivation, checkout creation or webhook replay as production smoke tests. Use synthetic non-production businesses for mutation/permission tests. Record results and stop/roll back on a regression.

The confirmed baseline is also the candidate web rollback target: **`4b29900c6705acefc11410d852b060378eb6459f`**. After explicit rollback approval, prefer a standard specific-commit deployment of that SHA with verified current settings. It retains the existing permissions/subscriptions safeguards because those modules are unchanged by the PWA. Do not restore a database, delete audits, reverse migrations or choose an older unrelated release. An artifact rollback can reuse old deployment settings; inspect them first. [Render rollback documentation](https://render.com/docs/rollbacks).

Installed-app limitation: the baseline has no new `/staff/employee/app` launcher, so installed icons may open a 404 after a baseline rollback, and an already installed worker is not removed immediately. Existing business employee URLs continue to work; operators may need to guide affected users to their existing employee URL or remove the home-screen shortcut. A reviewed forward fix/retirement worker is preferable when installed-app continuity is required. No such retirement release has been created or deployed here.

There is no PWA database rollback. A code rollback can leave installed icons and an already registered worker on devices; simply removing templates does not instantly remove those registrations. If retiring the PWA, prepare a replacement worker at the **same `/staff/employee-sw.js` URL** that unregisters itself on activation, with no fetch interception, and let clients update before removing the endpoint. Keep login and employee routes working while clients transition; offline devices cannot update immediately. Do not clear unrelated same-origin caches or sessions.

The existing permissions/subscriptions rollback caveat in `STAFF_PERMISSIONS_SUBSCRIPTIONS_REVIEW.md` still applies: older code can ignore early-trial cancellation audit events and restore remaining trial access. Preserve that trial access check if rolling back after early cancellations; deactivation flags and audit records persist. Do not roll back across unrelated Staff releases without reviewing this behavior.

## Changed files for this task

Paths are relative to `ai-receptionist-engine/`.

`A` means added; `M` means modified relative to the verified production baseline.

```text
A STAFF_EMPLOYEE_PWA_DEVICE_CHECKLIST.md
A STAFF_EMPLOYEE_PWA_REVIEW.md
A static/staff-pwa/apple-touch-icon.png
A static/staff-pwa/icon-192.png
A static/staff-pwa/icon-512.png
A static/staff-pwa/maskable-512.png
A static/staff-pwa/offline.html
A static/staff_pwa.css
A static/staff_pwa.js
A static/staff_pwa_sw.js
A templates/staff_employee_app.html
M templates/staff_employee_base.html
M templates/staff_employee_login.html
A templates/staff_pwa_head.html
M test_staff_checkout_tax.py
M test_staff_employee_recovery.py
M test_staff_launch_checks.py
A test_staff_pwa.py
A test_staff_pwa_integration.py
A tests/check_staff_pwa.ps1
A tests/staff_pwa_preview.py
A trimtech/modules/staff/employee_pwa.py
M trimtech/modules/staff/routes.py
```

Exact release scope: **23 files: 6 modified and 17 added; 14 runtime assets/modules/templates, 7 test files/tools and 2 review/checklist documents**. The three existing test edits repair fixture rows; no production authentication or Stripe implementation changes are included. The loopback preview helpers remain test-only and are not imported by the production entrypoint. The machine-readable whitelist is workspace `.release-validation/pwa-release-files.json`. Ignored local QA scripts, logs and disposable database files are additional local test artifacts, not release files. The pre-existing unrelated marketing changes are excluded. Thirty-six protected marketing, PayChaser/Stripe/billing and Stripe-script files matched their previously recorded hashes. Full-tree comparison against the verified live commit now additionally proves all 256 unchanged baseline files match, including subscription permissions and existing product/application implementations. The only change to the existing Staff routes module remains the three-line PWA module registration.

No Garage Voice, PayChaser, billing, database schema, business registration, payroll calculation or manager approval implementation files were changed by this task.


### Manager mobile navigation polish ? 19 October 2026

Local presentation change only: shared `staff_manager_mobile_nav.html` partial included by `staff_base.html` and `staff_agency.html`; mobile-only styling in `static/staff_pwa.css`. Native details/summary provides a compact, keyboard-accessible Manager menu at widths up to 650px. All requested destinations, plus Leave, account, employee portal and installation help remain accessible. Sign Out remains POST with the existing CSRF token. Existing desktop header is unchanged and remains visible above 650px; Employee navigation, authentication, permissions, worker and backend logic were not edited.

Verification: focused `test_staff_pwa.py` 17/17 passed, including synthetic Manager routes, menu destinations, CSRF/logout and tenant rejection. Headless Edge checked eight Manager pages at 375, 393, 430 and 1440 pixels: 32/32 preserved existing controls/links and had no horizontal page overflow; 8/8 desktop layouts had identical measured control geometry. At all 24 mobile page/width combinations the menu began closed, opened successfully and every menu link/button measured at least 48px high. Synthetic snapshot form/link comparisons exclude the intentionally added mobile menu. Dashboard screenshot reviewed at 393px. Evidence: `.release-validation/shared-pwa-layouts/summary.json` and `browser-results.json`. `git diff --check` passed (pre-existing CRLF notices only).

Files changed for this polish: the new partial, two Manager templates, shared PWA CSS, `test_staff_pwa.py`, and this review. No production, database, Stripe, Garage Voice, PayChaser, commit, push or deployment operations. Physical iPhone menu usability/VoiceOver review remains pending. Production remains BLOCKED.
