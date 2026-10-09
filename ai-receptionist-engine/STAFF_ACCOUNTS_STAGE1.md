# Staff accounts: Stage 1 release notes

This change is local implementation only. Do not deploy or migrate without approval.

## Scope

Staff-only business registration, email verification, password recovery, administrator
sessions and tenant membership enforcement. No trials, Stripe, wizard, employee
invitation or payroll-calculation changes. Existing employee authentication is unchanged.

Public registration is closed by default (`STAFF_REGISTRATION_ENABLED=0`). Set it to
`1` only in an approved test environment until later onboarding stages are ready.
Accounts created here have no trial or subscription entitlement yet; do not enable
public registration as a commercial launch.

Endpoints: `/staff/account/register`, `/login`, `/verify`, `/resend`, `/recover`,
`/reset`, `/logout`, with each suffix under `/staff/account`; `/staff/account` lists
only the signed-in administrator's active businesses. All mutations require POST
and the existing Staff CSRF token. A separate Secure, HttpOnly, SameSite=Lax,
__Host-prefixed cookie contains a random session secret; PostgreSQL stores its hash.
Sessions expire after eight hours and reset/logout revoke them server-side.

Verification/reset tokens expire after one hour, are stored hashed and consumed
transactionally. The verification page sets the email owner's chosen password,
preventing someone who pre-registers another person's email from retaining access.
Email URL tokens use fragments, which are not sent to HTTP servers. GET never consumes
a token. Resend/recovery handles failed email delivery without exposing account existence
in the response wording. Email dispatch is synchronous and generic responses are not a
constant-time guarantee. Database-backed account/IP limits bound abuse across workers.

## Migration and existing accounts (release blockers)

New explicit migration: `20261008_staff_identity_v1`, implemented in
`trimtech/modules/staff/accounts_migration.py`. It adds only `sm_businesses`,
`sm_administrators`, `sm_memberships`, `sm_tokens`, `sm_sessions`, `sm_rate_limits`, `sm_owner_provisions`
and `sm_schema_migrations`, in the existing PostgreSQL database. It requires a verified
v3 operational Staff schema and uses one transaction and an advisory transaction lock.
It verifies its own checksum/fingerprint and is repeatable. No startup path applies it.
The existing v1-v3 SQL, checksums and operational schema fingerprint are untouched.

When separately approved, its module entry point is
`python -m trimtech.modules.staff.accounts_migration` from `ai-receptionist-engine`,
with the intended DATABASE_URL already set. This has not been run against production.

Existing business IDs and records are not claimed through public registration.
An approved ownership-provisioning procedure must establish administrator memberships
for every existing business before deployment. There is deliberately no shared Garage
login bypass: a dashboard session alone no longer grants Staff manager access.
No automatic SQLite account import or guessed email-to-business matching occurs.

Schema-only rollback: the new sm_* tables can remain if application code is reverted;
old v3 schema verification still passes. However, old code restores the shared Staff
manager login. Once customer accounts exist, do not expose that old authorization to
subscribers. A release rollback plan must close public account routes and preserve
new account records; do not drop or restore tables to roll back application code.

## Platform prerequisites and remaining work

- HTTPS is required for the administrator cookie. Preserve the application's existing
  secure Flask session settings and stable secret key.
- Reuse RESEND_API_KEY and RESEND_FROM_EMAIL. Verification/recovery links require an
  HTTPS STAFF_PUBLIC_BASE_URL (or RENDER_EXTERNAL_URL). Do not log tokens or request bodies.
- Confirm Render's trusted proxy topology before enabling public registration. Code
  intentionally does not trust arbitrary X-Forwarded-For values. If remote_addr is a
  shared proxy, per-address limiting can affect unrelated customers. Configure trusted
  proxy handling narrowly in a separately reviewed deployment change.
- Existing employee phone/payroll-number login remains a security limitation; replacing
  it with secure invitations/credentials is a subsequent stage, not completed here.
- No MFA or distributed email worker is added in Stage 1. Email failures can be retried
  through resend/recovery; no live delivery verification was performed.
- No trial/access-expiry or billing enforcement exists yet. Those await Stage 2+ approval.

## Tests

Use the existing isolated `.release-validation/run_polish.py` runner from the repository
root with the verified Python 3.12 test environment. It forces local PostgreSQL,
blocks outbound Python network connections and disables live email credentials.
Fixtures use disposable UUID schemas. Account tests mock Resend, exercise real SQL,
concurrent duplicate registration/token consumption, tenant guards, revocation,
CSRF/rate limits and migration compatibility. No production tests are authorized.

## Existing-owner provisioning (implemented locally)

`trimtech.modules.staff.provision_owners` is an operator-only tool, not a public route.
It never changes old SQLite users, existing Staff data, passwords, verification state,
active flags or existing sessions. Existing Staff administrators are reused by exact
normalized email. New administrators remain unverified and cannot log in until they
request verification and choose their own password. No emails or secret tokens are
emitted by the command.

Prepare a private JSON manifest outside version control, using independently verified
ownership records (never infer ownership merely from a business name):

```json
{
  "operator": "approved-operator",
  "reason": "Owner email checked against authorised customer records",
  "owners": [{
    "business_id": "existing-exact-staff-id",
    "business_name": "Example Ltd",
    "contact_name": "Example Owner",
    "email": "owner@example.test"
  }]
}
```

From the application directory, the default command is strictly read-only:

```powershell
python -m trimtech.modules.staff.provision_owners --manifest C:\Private\staff-owners.json
```

It requires the separately approved identity migration to exist. Review the plan and
manifest SHA-256. Only after separate approval, run the same command with
`--apply --confirm-sha256 <reviewed-hash>`. Reusing an identical manifest is safe;
retries do not duplicate memberships or overwrite credentials. Entire batches roll
back on any conflict. Differing existing owners, inactive identities/memberships,
role elevation, duplicate IDs and unknown Staff businesses are rejected. An audit
row records operator, reason and manifest hash. Do not commit the private manifest.

Pre-provision before switching application code: the old Staff v3 fingerprint still
passes with these added tables. After the approved code rollout, the owner can use
`/staff/account/resend` and set a password through verification, or sign in using an
already verified Staff account. Existing Garage/PayChaser credentials remain untouched.
There is no automatic ownership transfer or account reactivation path.

## Trusted proxy configuration (local implementation verified, production values pending)

`STAFF_TRUSTED_PROXY_CIDRS` defaults to empty. Empty means ignore all forwarded IP
headers. When explicitly configured with verified proxy CIDRs, only a request whose
transport peer belongs to those networks may use X-Forwarded-For. The chain is walked
right-to-left, stopping at the first untrusted address. Left-hand client-supplied
values cannot replace that address. Invalid/incomplete chains fall back to the
transport peer's bucket. Invalid configuration fails the authentication operation
closed with 503. IPv4-mapped IPv6 is normalized; malformed/scoped addresses are rejected.

This resolver is used only by the new Staff account limiter. It does not install
ProxyFix globally, change shared REMOTE_ADDR or affect Garage Voice/PayChaser.
Existing employee login's limiter remains unchanged in this stage.

No production CIDRs or hop counts have been guessed or installed. Public Render docs
confirm Cloudflare/load balancers and X-Forwarded-For, but not this service's exact
trusted peer ranges or complete chain. Before deployment, obtain Render confirmation
of the inbound proxy networks and header append/overwrite behaviour for this service,
including its custom domain and onrender.com address. Outbound service IP ranges are
NOT inbound proxy ranges. Do not configure 0.0.0.0/0, ::/0, * or all private networks.
The parser requires IPv4 /16-or-narrower and IPv6 /48-or-narrower ranges; use confirmed
narrow ranges, not a guessed broad network. Keep registration closed until validated.

Validate in an approved staging environment that normal and forged-prefix requests
from the same real client share one rate-limit bucket, distinct clients resolve as
expected, and direct/untrusted requests cannot use forwarded headers. Production
configuration requires separate approval; none has been changed by this task.

Sources checked 8 October 2026:
- https://render.com/articles/how-render-handles-ddos-attacks
- https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/

## Manual release sequence (not executed)

1. Approve backup/pre-flight and the additive identity migration separately.
2. Review verified owner manifest; approve provisioning dry run, then apply separately.
3. Obtain confirmed Render proxy ranges/topology; approve environment configuration.
4. Approve application deployment with public registration still disabled.
5. Have owners verify/sign in, and approve isolated production access/email smoke tests.
6. Stage 2 requires separate approval. Do not expose a trial promise or billing flow yet.

## Verification result ? 8 October 2026

Full repository unittest discovery (`test*.py`) through the isolated runner:
**138 passed, 0 failures, 0 skips**, 526.775 seconds. This includes account,
provisioning, spoof-resistant proxy resolution and all available Staff regressions.
The stricter exact-error migration rollback test also passed in a focused rerun
(1 test, 2.610 seconds). Both legacy registry smoke scripts passed independently,
including all four service-name resolutions, with network and SQLite access blocked.
`git diff --check` passed.

Earlier test failures were corrected: Beta payroll settings now require explicit
Beta membership, and invalid proxy configuration returns 503 instead of being
misclassified as incorrect credentials. No payroll calculation changes were made.

Production remains NO-GO until actual Render inbound proxy trust is confirmed and
existing owners are provisioned/activation at cutover is planned. New Staff login
requires owner email verification; preserving old accounts does not mean the shared
Garage login remains a Staff authorization bypass. No production migration,
provisioning, email, environment update, push, commit or deployment was performed.
Stage 2 has not begun.
