# Staff trial launch check — 16 October 2026

Decision: **NO-GO for a reliable public launch until the reported iPhone manager
session loss and a real employee recovery email are confirmed.** This candidate
is tested locally; it does not establish the production causes of those reports.
No onboarding rebuild or seven-step rehearsal was performed.

## Changes and evidence

- Employee login accepts registered email or phone through the existing tenant
  portal and form field. Canonical email/phone matching rejects missing/ambiguous
  identities rather than picking an employee. Legacy payroll-number passwords
  remain supported. No cross-business lookup is performed.
- Confirmed recovery defect: submitted phones were normalized, but stored phones
  were compared verbatim. Formatting such as spaces could prevent eligibility
  and therefore prevent dispatch. Login and recovery now share UK phone
  normalization, including the database predicate. This has not been proven to
  be the cause of the particular production request on 15–16 October.
- Added server-only recovery reasons for invalid input, rate limiting, queue
  saturation, invalid public URL, no eligible/ambiguous match, dispatch attempt,
  sanitized provider failure and provider acceptance. Background exceptions log
  their class only. No addresses, phones, passwords, tokens or cookie values
  are logged or added to public responses.
- Manager code already uses a persistent Secure/HttpOnly/SameSite=Lax host-only
  cookie with an eight-hour lifetime and an eight-hour PostgreSQL session.
  Employee authentication also expires after eight hours. No one-minute expiry,
  automatic dashboard logout, host-changing public login redirect or unintended
  employee-reset deletion of manager authentication was found. Session policy
  has not been changed speculatively. New diagnostic reasons distinguish a
  missing/malformed cookie from an unavailable server session.

## Verification

49 focused Python tests passed with database/network access blocked. Coverage:
identifier ambiguity and tenant isolation, phone formats, recovery token/session
guards, manager return after 61 seconds and an hour in the local session model,
logout/expiry/revocation, independent employee and manager authentication, public
registration gating, exact 336-hour trial activation and expiry write blocking.
Both JavaScript suites and 14 mobile/desktop browser cases passed. A 360px
employee-login screenshot was visually inspected. Browser emulation was Chromium,
not the reporting iPhone Safari. Guarded app:app startup made no database/network
connections and started no background threads. No migrations were executed.

Read-only public GETs to https://garage-voice.onrender.com confirmed HTTP 200 for
the login and registration pages; registration already displays the public form.
No flag was changed. No registration, login, recovery POST or production database
query/write was performed. Oakfield/TrimTech production rows were not inspected
or changed; isolation evidence is local code and tests. Existing successful
registration, activation, onboarding and Staff feature tests supplied by the
operator were not repeated.

## Remaining launch steps

1. Obtain authenticated Render log/configuration access or the operator's
   equivalent evidence. It is not available in this session. Verify the live SHA,
   STAFF_STRIPE_ENABLED=0, existing email/public-URL settings and public flag.
   Registration is already publicly accessible; do not enable it again by assumption.
2. After approval to push and manually deploy this exact candidate, keep existing
   build/start commands, empty pre-deploy and Auto-deploy Off. No migrations,
   dependency changes or new environment settings are required. Do not change
   Garage Voice, PayChaser or billing.
3. Perform only an approved manager sign-in/leave/return check on the reporting
   iPhone. Use the safe authentication reason to identify browser-cookie loss
   versus server-session loss; fix that verified cause before declaring GO.
4. Perform one approved employee recovery check against the recorded tenant,
   email and phone. Confirm dispatch/provider acceptance, actual inbox delivery,
   reset and email/phone sign-in. If dispatch is skipped, use its reason to verify
   eligibility/configuration rather than weakening activation or anti-enumeration.
5. Once those checks pass and billing is confirmed disabled, the existing sign-up
   page is https://garage-voice.onrender.com/staff/account/register. Announce/link
   that page; no onboarding rebuild or payment activation is needed.

All local changes are limited to Staff authentication, recovery, diagnostics,
focused tests and this report. Unrelated marketing edits are excluded. The
candidate is to be committed locally and held for approval before push/deployment.
