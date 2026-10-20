# Staff Manager Deployment 2

Reconstructed from sealed shared-pwa-candidate-dcf151b021ac on compatibility
commit e9b868ca47bb4b94d3d8173b75318f284fd2d1c1. That compatibility release is
operator-confirmed live and its iPhone launcher is operator-confirmed working.
This document supersedes baseline/rollback instructions in the historical PWA
review and device checklist. Their device acceptance cases remain applicable.

Only employee_pwa is registered. pwa_compat, its template, no-op worker and
rollback tests remain in the tree. The launcher, manifest identity/start URL,
scope, icons, public install/offline routes and worker URL are preserved.
The full PWA's GET navigation fallback replaces the no-op worker at the same
/staff/employee-sw.js URL. It stores no authenticated responses or mutations,
queues no requests and forces no page reloads. Updates require connectivity;
old/offline devices cannot be forced to update instantly.

Existing database/authentication, server-owned trials, deactivation/early-ending
audit checks, payroll calculations and Stripe controls remain baseline code.
No migration, backfill, new dependency or environment change is required.
Preserve origin, secrets, database, proxy trust and STAFF_STRIPE_ENABLED=0.

Rollback target: the successful Render deployment of the exact compatibility
commit above, never unmodified 4b29900. Record its deploy ID and retained artifact
availability. Before artifact rollback privately compare its runtime environment,
environment groups, start command and health check with the approved settings.
If the artifact is unavailable, deploy that exact compatibility SHA using verified
current settings. Preserve the database, session secrets, trial dates, audit
history and installed icons. Do not clear browser data or unregister workers.
Reopen existing icons after reconnecting and verify employee/manager access.

Release remains subject to fresh isolated tests, exact final commit review and
separate push/deploy approval. iPhone launcher confirmation does not establish
full-PWA navigation, VoiceOver, Android installation, populated-screen or
same-origin full-PWA-to-compatibility rollback acceptance. These require physical
device rehearsal with synthetic accounts on an approved isolated staging origin.
Live shared-product health checks and compatibility artifact verification remain
operator checks. No production data mutations belong in release smoke tests.
