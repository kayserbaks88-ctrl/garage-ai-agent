# Marketing demo spam protection

The affected Render service is `trimtech-ai`; its marketing app accepts demo
enquiries at `POST /demo`. Previously it only required nonempty fields, then
called `send_lead_notification` and `send_customer_confirmation`, each using
Resend. WhatsApp contact preference additionally called Twilio.

## Emergency closure

The safest service-specific emergency fix is the new early server-side gate:

```text
MARKETING_DEMO_ENABLED=false
```

This rejects all demo POSTs with HTTP 503 before parsing the form or contacting
Cloudflare, Resend or Twilio. Missing, invalid or non-true values also close it.
The landing page, health endpoint and demo information page remain available;
the demo form displays a temporary closure and its fields/button are disabled.

This switch takes effect only after this code is deployed. These changes are
local: no Render settings, deployments, pushes or provider accounts were changed.
Production continues to run the previous code until a separate authorized rollout
or service-specific request block is applied. Do not revoke a shared Resend key
or change other products' email settings as part of this marketing-only fix.

## Protection required before reopening

Keep both enablement flags false during setup. Configure only on the marketing
service, using real Cloudflare keys, exact approved hostnames and a private random
state secret:

```text
MARKETING_DEMO_ENABLED=false
MARKETING_DEMO_PROTECTION_TESTED=false
MARKETING_TURNSTILE_SITE_KEY=<real public site key>
MARKETING_TURNSTILE_SECRET_KEY=<real private secret key>
MARKETING_TURNSTILE_HOSTNAMES=<exact marketing hostname,optional second hostname>
MARKETING_DEMO_STATE_SECRET=<random secret of at least 32 characters>
MARKETING_DEMO_STATE_DB=<absolute path on a marketing-only persistent disk>/demo.sqlite3
```

All values and the explicit testing acknowledgement are required to accept a
submission. Cloudflare dummy keys are rejected. No secret is rendered in the form.
The state file must be writable by all marketing Gunicorn workers. It uses
SQLite atomic transactions and survives worker restarts on the persistent disk.
Use this implementation on **one Render service instance**; multiple replicas
or ephemeral files would not share durable quotas/deduplication. Before scaling,
replace the isolated state store with a shared atomic store. Do not point it at
any existing application data file, delete it to reset quotas, or rotate its
state secret to evade limits.

Optional `MARKETING_DEMO_TRUSTED_PROXY_CIDRS` is a comma-separated list of the
actual immediate proxy networks. Leave it empty unless those networks have been
verified. Untrusted forwarding headers are ignored. A trusted chain is walked
from right to left to the first untrusted address. Trusting all addresses is
rejected. With no trusted proxy configuration, a shared reverse proxy address
may conservatively share the IP limit; check genuine client addressing in the
nonproduction verification before enabling. Never blindly trust the leftmost
`X-Forwarded-For` or a visitor-supplied Cloudflare header.

## Enforcement

- Maximum 16 KiB form POST body; unknown or repeated fields are rejected.
- Honeypot, field lengths, Unicode/control character checks, strict name and
  business-name validation rejecting links/markup, email and phone validation,
  and allowlisted contact method/business size.
- Shared limits: five attempts per IP per fixed 15-minute window and 100 total
  attempts per fixed 15-minute window. Invalid requests also consume limits.
- Server-side Turnstile Siteverify must return boolean success, the exact
  approved hostname, action `marketing_demo` and a fresh challenge timestamp.
  Missing/expired tokens, malformed responses and network failures reject.
- Atomic 24-hour reservations prevent repeated normalized email addresses,
  phone numbers and tokens from triggering delivery, including concurrent POSTs.
- Emergency global ceiling: ten accepted enquiries per UTC day, hence at most
  twenty Resend email attempts through this endpoint. This is a marketing budget,
  not a promise about the account-wide quota consumed by other services.
- Storage failure rejects the request. Reservations are committed before any
  delivery and retained on delivery failure, so retries cannot send again.

No validation can prove that a plausible business name or mailbox is genuine.
Turnstile, quotas, the honeypot and duplicate reservations operate together to
reduce abuse. Existing marketing delivery helpers are unchanged; no subscription,
login, verification, Staff Manager, Garage Voice or PayChaser code was modified.

## Verification and later authorized rollout

Local tests use temporary SQLite files and mocked Cloudflare/delivery responses;
they do not send mail or assert that real production keys already work.

From `ai-receptionist-engine`:

```sh
python -X utf8 -m unittest discover -s marketing_site -p test_demo_security.py -v
node --test marketing_site/test_demo_form.cjs
```

In an isolated nonproduction marketing instance, test real widget completion and
server verification with approved staging keys/hostname and safe test recipients.
Exercise missing/invalid/expired tokens, wrong hostname/action, honeypot, link
names, duplicate requests, rate limits and storage/Cloudflare failure. Confirm
the normal enquiry delivers once and the rest of the site remains available.
Only after these checks set the testing acknowledgement and enablement to true
on the intended instance. Keep production disabled until its separate rollout
and genuine protected enquiry check are authorized. Re-close immediately by
setting `MARKETING_DEMO_ENABLED=false` if spam or quota pressure returns.

Cloudflare's server verification requirements are documented at
https://developers.cloudflare.com/turnstile/get-started/server-side-validation/.
