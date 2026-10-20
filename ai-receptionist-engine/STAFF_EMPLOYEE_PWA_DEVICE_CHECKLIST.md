> Deployment 2 update, 20 October 2026: reconstructed on live compatibility commit e9b868ca47bb4b94d3d8173b75318f284fd2d1c1. See STAFF_PWA_DEPLOYMENT2.md for current ancestry, scope and rollback instructions. The baseline and 27-file counts below describe the sealed historical candidate.

# Staff Manager Employee + Manager PWA: current device acceptance gates

19 October 2026. Production BLOCKED. Existing physical iPhone testing confirmed installation of both synthetic role previews; it does not establish final Manager-menu, dense populated-screen or Android acceptance. The current candidate runtime/tests are unchanged from the audited implementation.

Service: garage-voice-agent. Baseline: 4b29900c6705acefc11410d852b060378eb6459f. Branch: staff-permissions-subscriptions-release-20261017. Root: ai-receptionist-engine. Build: pip install -r requirements.txt. Pre-Deploy: empty. Start: gunicorn app:app. Auto-Deploy: Off. These values were visually verified by the operator on 19 October 2026; no settings were changed here.

Use synthetic Employee/Manager accounts only. Use the existing approved protected HTTPS mock after verifying its URL and Basic Authentication again. Do not enter real account credentials into the synthetic preview. Mock POSTs are deliberately blocked; state-changing real-auth tests require an approved isolated synthetic database, never production. Do not add paid services, change firewall/security settings or install certificates as part of these checks.

Record device/OS/browser, candidate hash, role, expected and observed results for each case:

- Android: authenticated manifest/icons/worker load; Chrome install/menu fallback; Staff Manager name and green S icon; Home Screen standalone launch into employee dashboard, Manager authorised business selector or logged-out sign-in as appropriate. Confirm address-bar-free ordinary internal navigation. Do not accept a mere browser bookmark as standalone acceptance.
- iPhone after Manager polish: collapsed Manager menu, touch/VoiceOver/keyboard focus, every required link, scrolling and safe-area layout; employee navigation unchanged. Check reinstall behavior and Safari-versus-installed session separation.
- Both systems: employee-only, Manager-only, simultaneous and logged-out sessions; expiry, logout, revoked membership and inactive employees. Role selection must never grant access to another business. Backend authorization is already covered by the isolated PostgreSQL tests.
- Populate synthetic Staff, Attendance, Assignments, weekly Rota, Approvals, Leave, Payroll and payslip screens. Include long names, many rows, overnight shifts, unpaid breaks, statuses, validation messages and dense payroll amounts. Check 375/393/430px portrait plus landscape/tablet as available; allow intentional table scrolling without page-level overflow. Empty-state browser screenshots are not sufficient.
- In an authorised isolated database setup, exercise actual sign-in/out, GPS clocking, breaks, approvals, holidays and payroll workflows using synthetic records. Test permissions/errors and cross-business denial. Do not use actual customer accounts or live payroll as a mutation smoke test.
- Offline: reconnect message, no new private records fetched/stored, no clocking/submission/replay; restore connection and verify no deferred action runs. Excluded settings/download pages may show the native browser offline error. Directions and genuine PDF downloads may open their existing external/native viewer; ordinary page navigation should remain within the app.
- Production worker inspection is a separate READ-ONLY gate: open the actual service HTTPS origin (the existing GET / health page is sufficient), inspect DevTools > Application > Service Workers, and record all scopes/script URLs. Do not press Update/Unregister/Clear site data. Repository inspection found no baseline registration code, but existing clients may have older registrations.
- Installed-app rollback: operator must accept the baseline's possible launcher 404/persistent worker and support users through /staff/account or their existing /staff/<workplace>/employee URL, OR approve a separate compatibility/retirement change. No database restore, trial reset or unrelated cache/session deletion. Keep end-trial audit and deactivation safeguards. Retiring a worker requires the SAME script URL; offline devices cannot update immediately.

No physical Android or populated-device acceptance is claimed by the candidate's passing desktop browser/SQL tests. Production needs explicit exact-commit approval after these gates. Current trial dates, existing accounts and billing settings must remain unchanged. Test ngrok Home Screen icons do not convert into production apps: remove them and install from the verified production origin only after release approval.

---

# Historical device plans (superseded where they conflict with the current gates above)

# Staff Manager shared Employee + Manager device checklist

## Current shared build â€” 19 October 2026

Previous physical iPhone employee-mock results confirmed installation, standalone launch, employee dashboard, mobile data, safe offline screen and reconnection. These results are not physical acceptance of the new shared implementation. Fresh shared-build iPhone and Android acceptance remains pending.

The approved temporary ngrok endpoint now serves only the synthetic shared preview, behind the existing Basic Authentication. Use the existing temporary gateway credentials; do not enter real manager or employee credentials. The development helper is loopback-only, blocks database/provider connections and every submission, and is not imported by production. Free-plan Visit Site may be required before installation/worker activation.

Base URL: `https://johnette-reproofless-josue.ngrok-free.dev` (valid only while the approved test tunnel/laptop runs).

| Synthetic test mode | Test-only URL | Expected result |
| --- | --- | --- |
| Logged out | `/staff/employee/app/preview/login` | Shared sign-in/workplace chooser |
| Employee | `/staff/employee/app/preview/employee` | Synthetic employee dashboard |
| Manager | `/staff/employee/app/preview/manager` | Authorised synthetic business selector; choose Synthetic workplace |
| Both | `/staff/employee/app/preview/both` | Explicit employee/manager workspace choice |

1. Remove the previous Staff Manager Home Screen icon. In Safari, open the original HTTPS domain above, authenticate, and acknowledge Visit Site if present. Do not install the ngrok warning page or app-help page.
2. Select a synthetic mode, then open `/staff/employee/app`. Add the dashboard/sign-in page to Home Screen, with Open as Web App enabled if offered. Confirm **Staff Manager** name and green S icon. For Android, use Chrome's Install app/Add to Home screen.
3. Launch from the icon. Check employee-only, manager-only, both and logged-out cases using the synthetic test-mode links at the bottom of each page. These test-only links stay within `/staff/` so the installed app can select its own synthetic session without opening an outside-scope browser. Safari and the installed app may have separate authentication/storage contexts; never assume Safari's session transferred.
4. Employee navigation: Clock, Rota, Hours, Pay, Leave, Jobs, Profile, app help and return links stay within the standalone Staff scope. PDF previews/downloads may use operating-system UI; confirm a clear path back.
5. Manager navigation: business dashboard, employees, attendance/GPS evidence, approvals, Assignments/weekly rota/sites, leave, payroll and settings remain reachable. All existing authorised controls must remain available; horizontal table scrolling is acceptable. Detailed payroll/PDF behaviour needs populated isolated-test fixtures as well as empty previews.
6. Switch roles with both sessions present. An employee must not gain manager access; a manager without membership must not access another business. Synthetic preview alpha/beta checks are supplementary to real isolated PostgreSQL membership tests.
7. Disable connectivity in the installed app. Allowlisted page navigation shows only the generic offline document. No private data appears from cache. Clocking, approvals, payroll and other forms must not submit or queue. Restore connectivity and reload; no prior action may replay.
8. Test actual login/logout, expiry, password reset/revocation, manager membership revocation, GPS failures, breaks and approval/payroll mutations using isolated integration fixtures. The public synthetic preview deliberately rejects all submissions, including login/logout, with 409; use `/qa/login` to simulate its logged-out presentation. It cannot prove real device GPS clock-in or real login mutation behaviour.
9. Repeat on iPhone cellular data and Android where available. Record device/iOS/Android/browser version, standalone state, steps and outcome. Recheck manager desktop layouts and all controls at 1280/1440 widths before release.
10. Verify unauthenticated and incorrect gateway credentials cannot access any preview route or asset. Keep optional inspection disabled. Stop the tunnel after testing; no purchase, production deployment or production settings change is authorised.

Release remains blocked pending physical shared-build acceptance, current Render SHA/settings verification, final clean release diff and explicit release approval. No paid ngrok upgrade is approved.

## Historical employee-only acceptance plan

Historical status at initial preparation: **not yet performed on physical devices**. See the current shared-build status above. Do not use production data for these tests or deploy to perform them without approval.

## Staging/device-test plan without changing production

Plan only: no local HTTPS server, certificate, trust profile, firewall rule or database is being created now. No cloud staging service or paid service is needed. Keep production `garage-voice-agent` on `4b29900`, its confirmed linked branch unchanged, Auto-Deploy Off and Stripe disabled. The remaining production configuration checks are the Build Command and final confirmation of the apparently blank Pre-Deploy field.

Use this computer as a temporary private-Wi-Fi test host, with a distinct HTTPS origin and the reviewed candidate snapshot. Do not point the iPhone test icon at the production domain. Service-worker registration is origin-specific; a separate LAN origin keeps the test worker and portal separate from production. A phone opening `localhost` reaches the phone itself, not this computer. Plain HTTP to a computer's LAN IP does not provide the secure context required for service workers: use trusted HTTPS. [MDN secure contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Secure_Contexts), [service workers](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API).

### Stage A: install/navigation/offline testing, no database

1. After authorization for local test setup, use an isolated copy of the approved candidate. Start the existing employee mock harness from `tests/staff_pwa_preview.py`, with a small local-only HTTPS wrapper. The current harness binds to loopback and serves HTTP; running that script unchanged does **not** make an iPhone-installable LAN test service. The wrapper must bind to the chosen private LAN address and load an explicit TLS certificate, rather than use an untrusted ad-hoc certificate. Werkzeug supports a certificate/key SSL context for a local test server; this is a private development test, not a public production server. [Werkzeug serving documentation](https://werkzeug.palletsprojects.com/en/stable/serving/).
2. Generate a short-lived dedicated development CA and a server certificate for this computer's actual test hostname/IP, including that hostname/IP in the certificate SAN and server-auth usage. Use new local test keys; never reuse production credentials. Keep private keys outside the app's static tree and release files. Deliver only the public CA certificate to the phone through a trusted local transfer and verify its fingerprint. Certificate generation and device trust installation are future setup steps, not actions taken in this plan.
3. Put the computer and phone on the same trusted private Wi-Fi, with client-to-client access. Temporarily allow the chosen TLS port (proposed **5443**) only from the test phone/private network. No router port-forward, public tunnel, production DNS, Render change or internet-facing debug server. Keep Flask debug/reloader off. Restrict the mock harness's test-only `/qa/*` shortcuts to this private test setup.
4. Install the development CA profile on the iPhone, then explicitly enable trust for that named CA at **Settings â†’ General â†’ About â†’ Certificate Trust Settings**. Manually installed profiles do not automatically gain TLS trust. If the phone's management policy prevents this, stop; do not bypass certificate warnings or disable browser security. Trust only the CA created for this test and remove it after testing. [Apple certificate trust instructions](https://support.apple.com/en-us/102390).
5. Open **`https://<computer-LAN-IP>:5443/staff/employee/app`** in Safari, replacing the placeholder with the actual SAN-matched LAN address. This is a URL template, **not a running test link**. Confirm there is no certificate warning, `window.isSecureContext` is true and the service worker activates. Keep the computer awake and the test server running during online checks.
6. In Safari, use **Share â†’ Add to Home Screen**, choose a visible test name such as **Staff Manager TEST**, enable **Open as Web App** if offered, and tap Add. Open the icon, close/reopen it, and check icon, launch screen, standalone display, keyboard and safe-area layout. This is a Safari home-screen installation; no production deployment is involved. [Apple home-screen web-app instructions](https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/ios).
7. Exercise mock employee navigation with synthetic test identities only. Check offline reload, reconnect screen, no-data storage, offline form blocking and no automatic replay. Test location-permission behavior through the controlled test harness without treating a mock result as a recorded shift. Never enter a production password. Block PostgreSQL connections and outbound Python/provider calls, disable dotenv loading, and use a new test session secret. No real payroll data or GPS records are written in this stage.
8. Repeat on Android/Chrome on the same private HTTPS origin. Establish certificate trust using that device's supported settings, verify secure-context/worker activation, then use Install app/Add to Home screen. Android browser/device support for user-installed certificates must be checked; do not bypass a trust failure. Record actual OS/browser versions and whether the result is a standalone installed app rather than only a shortcut.

Stage A can validate installation and the shell, but **cannot prove successful secure employee login, persisted clocking/breaks, real timesheets/payslips, holiday approvals or SQL tenant isolation**. The current preview mocks those dependencies and its QA shortcuts are not genuine authentication. The localhost desktop browser checks already completed do not replace this physical-device stage.

### Stage B: full employee workflows, disposable PostgreSQL only

This stage needs separately authorized local test-database setup. The earlier integration schemas were cleaned up; do not assume a populated staging database still exists. Initializing fresh synthetic schemas/fixtures may require **test-only migrations**, which remain prohibited in the current instruction and will not be run now. The production PWA delta itself requires no migration or backfill.

- Use the same private HTTPS approach with an employee/manager test Flask harness that loads the candidate's actual authentication, routes, templates and services. Use genuine test sign-in, not the `/qa/*` shortcut, for acceptance. Do not launch the shared `app.py` with copied production environment variables.
- Pin every database connection to one newly created localhost-only test cluster/database/role and verify its identity/data directory before writes. No production database URL, restore of production data, production environment groups or secret reuse. Keep the existing connection guard and outbound-provider block in place.
- Seed only synthetic businesses A/B, employees A1/A2/B1, their managers, test credentials, sites, rota entries, payroll/payslip fixtures and holidays. Test manager approvals/payroll changes only there. Use a consented test location and a synthetic site centred there; never change a real business's geofence or use production clocking records.
- Set the **test process only** to `STAFF_STRIPE_ENABLED=0`, no live Stripe/webhook/payment credentials, no Twilio/calendar/real mail credentials, an independent session secret and a staging-only public base URL. Email/recovery links go to a local test sink/mock, never to real recipients or the production origin. Do not replay production webhooks or use real customer Stripe IDs.
- Follow every applicable checklist item below, comparing employee and manager results with the synthetic database. Verify no effect on business B, manager/employee session separation, CSRF, GPS errors/retry, breaks, rota, hours, payslips, leave, offline blocking and reconnect without queued actions. Record pass/fail and evidence per physical device.

### Completion and cleanup

Record the tested candidate fingerprint (a commit SHA only if subsequently authorized), URL/origin, phone model, OS/browser versions, results and remaining failures. Stop the local servers, close the temporary firewall exception, remove the TEST home-screen icons and downloaded synthetic payslips, and remove the dedicated certificate trust profiles. Remove only test-origin browser data if needed; do not clear production cookies or accounts. Stop the disposable PostgreSQL cluster after test cleanup. Keep non-sensitive test evidence, not private keys or test credentials, with the local review artifacts.

Production remains blocked until Build/Pre-Deploy review, both physical-device stages, final release-commit verification and explicit deployment approval are complete. A reviewed rollback must also account for installed workers/icons surviving a server rollback and the baseline lacking the new launch route. No staging setup, device configuration, commit, push, deployment or migration is authorized merely by this plan.

## Test setup and evidence

- [ ] Record approved test release SHA, HTTPS test URL, tester/date, phone model, OS version and Safari/Chrome version. Verify the Render live Staff SHA separately before considering a production release.
- [ ] Use an approved isolated HTTPS test environment with synthetic businesses A and B, employees A1/A2/B1 and separate managers. Keep Stripe disabled and mail directed to a test sink or mocked delivery. Do not provision a paid service.
- [ ] Prepare a GPS-enabled test site, weekly rota, approved payslip, draft payslip, pending holiday and known pay/break policy. Record expected results before testing.
- [ ] Confirm there is no conflicting same-origin service worker. Check manifest/icons/worker return successfully with correct MIME types. Worker and authenticated pages must return `Cache-Control: no-store`.

## iPhone / Safari installation

- [ ] Open `/staff/employee/app` in Safari; confirm navy/green branding and readable layout without horizontal overflow.
- [ ] Follow Install / app help: Share â†’ Add to Home Screen; enable Open as Web App if offered, then Add. Record actual menu wording on the tested OS.
- [ ] Confirm icon/name, launch presentation, standalone window and safe-area spacing with the home indicator and on-screen keyboard.
- [ ] Close/reopen the installed app; enter workplace code and sign in. Confirm any need to sign in again after installing is explained. No personal data should appear before authentication.

## Android / Chrome installation

- [ ] Open the same launch URL in Chrome; follow Install app if offered, or the browser menu's Install app / Add to Home screen.
- [ ] Confirm name, branded icon (including the launcher mask), launch presentation and standalone display.
- [ ] Close/reopen from the launcher and sign in using the existing employee credentials. Check keyboard, orientation and small-screen navigation.
- [ ] If installation is unavailable, confirm guidance remains useful and the online employee portal works normally. Do not classify a browser shortcut alone as verified standalone installation.

## Run on both installed apps

- [ ] Sign in using supported phone/email credentials. Wrong password stays rejected. Manager credentials and employee credentials retain their separate access boundaries.
- [ ] Follow the recovery flow using only a test inbox: reset, sign in with the new password, reject the old password and replayed link. Confirm older sessions expire after credential rotation. A deactivated business must still reject login.
- [ ] Allow GPS and clock in at the prepared site. Confirm site/radius/accuracy/freshness rules, one open shift only, server timestamp and pending manager approval.
- [ ] Deny location, then retry after granting permission in device/browser settings. Check iPhone Precise Location / Android precise versus approximate access where available. Test unavailable/poor-accuracy GPS and an outside-radius location. No rejected attempt may create a shift. Do not bypass validation to make a device test pass.
- [ ] At a photo-required site, confirm the existing portal restriction and manager guidance remain; this PWA phase does not add photo upload or bypass that policy.
- [ ] Start/end a break; repeat submission/back navigation; verify only the intended open shift/break changes. Check the configured paid/unpaid policy remains unchanged.
- [ ] Clock out with a fresh location; verify open breaks close correctly and the completed shift still requires manager review. Confirm the manager approval screen and authoritative pay calculation retain expected results.
- [ ] Open weekly rota, change weeks and return via mobile navigation. Check hours/timesheet history and approval labels against the prepared records.
- [ ] View/download the approved payslip with correct employee and amounts. Draft and another employee's/business's payslips must remain inaccessible, including by copied URLs. Verify iOS download/view/back behavior. A deliberately downloaded file is an OS-managed document, not an offline PWA cache; remove synthetic downloads after QA.
- [ ] Submit/cancel a pending holiday; verify manager approval is required and another employee's request cannot be changed.
- [ ] As A1, try A2/B1 IDs and business B URLs/forms. No disclosure or mutation is permitted. Confirm manager A can manage A but cannot manage B; employee A1 cannot enter manager controls.
- [ ] Sign out, use Back, reopen, and test a copied employee URL. Private pages must require authentication. Test session expiry and confirm the existing eight-hour policy is unchanged.
- [ ] Switch applications, lock/unlock, then return. No new background tracking is expected. Existing optional foreground presence remains separate from clocking and payroll.

## Offline and reconnect on both devices

- [ ] First visit online so the public worker is installed. Then enable airplane mode and reload an employee page. See only the generic reconnect screen, with no employee name, hours, payslip or location records.
- [ ] While already on a clocking page, disconnect and submit. It must not clock in/out, acquire a new GPS reading through the form handler, or queue the action. Repeat for breaks, holidays and logout; do not claim successful logout while offline.
- [ ] Reconnect. Nothing submits automatically. Refresh and inspect current server state before retrying an interrupted action, to avoid duplicate user attempts.
- [ ] Attempt payslip access offline. Previously fetched payslip responses must not be served from a PWA cache. Previously user-downloaded files are outside this test's cache claim.
- [ ] Inspect worker storage with Safari Web Inspector / Chrome remote debugging where available: no employee responses in CacheStorage or IndexedDB; no employee data introduced into localStorage. Confirm manager, onboarding, billing and other-product requests are not intercepted.

## Acceptance

- [ ] Record pass/fail and evidence for each device, any OS-specific limitations and retest results.
- [ ] Resolve failures before release approval. Complete live SHA verification and compare the approved release diff. No checklist completion authorizes deployment automatically.
