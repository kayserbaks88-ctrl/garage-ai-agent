# Staff Manager installed-app compatibility rollback

LOCAL CANDIDATE ONLY. No release commit exists and production remains blocked.

Baseline: `4b29900c6705acefc11410d852b060378eb6459f`.

This separate build retains the existing baseline application and adds only a
stable installed-app entry, public branding/manifest/help/offline assets and a
replacement worker. Do not register both pwa_compat and employee_pwa modules.

## Stable contract

- App identity and start URL: `/staff/employee/app`.
- Scope `/staff/`, standalone display, Staff Manager name and existing green S icons.
- Manifest `/staff/employee/app/manifest.webmanifest`.
- Help `/staff/employee/app/install` and public offline page `/staff/employee/app/offline`.
- Worker URL `/staff/employee-sw.js`; serve JavaScript, no redirects, no-store.
- Employee-only opens the existing guarded employee dashboard; manager-only opens
  the existing account/workspace selector. Both sessions prompt for a role.
- Logged-out users choose manager sign-in or a validated employee workplace code.
  Selection is navigation, never authorization. Invalid/expired sessions do not
  authorize access; database errors fail closed. Existing tenant membership,
  business deactivation, credential revocation, CSRF and trial checks still apply.

## Worker and offline behaviour

The replacement worker has only install/activate handlers, skipWaiting and
clients.claim. It has no fetch handler, private storage, queue, background task,
forced reload or origin-wide cleanup. Existing open forms are not reloaded.
Its installation/update timing depends on the browser and network: recovery is
not instantaneous on every device. The old candidate worker is network-only too,
so the compatible server entry works before replacement finishes.

No authenticated data is available offline. Without interception the browser can
show its native offline error. The public offline page remains reachable online
and from an older worker's already embedded fallback. No offline action is
accepted or replayed. Baseline clocking/payroll routes require the live server;
baseline screens do not acquire the full PWA's offline submission banner/guard.
Existing baseline forms may attempt a request while offline, but this build adds
no storage, queue or replay. Do not resubmit an uncertain action without checking
its server-side outcome after reconnecting.

## Future deployment and rollback (separate explicit approval required)

1. Review the file/checksum manifest and isolated tests. Rehearse on installed
   iPhone and Android apps using synthetic accounts and a fixed staging origin.
2. Check real production worker registrations read-only, including overlapping
   root or /staff/ scopes, before introducing any worker.
3. After approval, create a compatibility commit directly on the verified baseline
   and deploy/verify it before the full PWA. Record its exact successful Render
   deploy ID, commit, artifact availability and environment/configuration.
4. Keep origin, session secrets, database, proxy/session settings and
   STAFF_STRIPE_ENABLED=0 unchanged. No migrations or backfills are required.
5. Deploy the separately approved full PWA. If rollback is needed, select the
   recorded COMPATIBILITY deploy; never select the unmodified 4b29900 baseline
   after users have installed the new app. Check retained artifact availability.
6. Render rollback reuses target-deploy environment variables and some settings.
   Verify these match the approved runtime; do not restore an older database,
   change billing, clear sessions or clear all browser/origin data.
7. Confirm existing installed icons still open, both roles sign in, role switching
   and membership restrictions hold, active trials retain their original dates,
   and normal employee/payroll features remain available online. Confirm other
   products remain healthy. Keep Auto-Deploy off.

## Required physical-device rehearsal

Install the full PWA, authenticate employee-only, manager-only and both; swap the
same synthetic staging origin to this compatibility build. Reopen the EXISTING
icon without uninstalling. Repeat with expired/revoked sessions, removed manager
membership, deactivated business and active/expired trial. Check populated rota,
hours, pay, leave and manager screens. Test old worker still active, replacement
active, no worker, offline, reconnect and an open unsaved form. No forced reload,
private cache, offline mutation, replay or permissions bypass is acceptable.

No claim of uninterrupted access during a network/infrastructure outage is made.
Normal session expiry can require sign-in; valid accounts and trial data are not
reset. Android and iPhone installed-app acceptance must precede release approval.
