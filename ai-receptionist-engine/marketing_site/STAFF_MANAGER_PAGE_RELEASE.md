# Dedicated Staff Manager marketing page — 18 October 2026

Parent: `5ed022e7c4f484d5b1d7652c13510a1de0ebf967` on website branch `main`.
Commit/push is authorized. Deployment and Render settings changes are not.

## Change scope

- `app.py`: add GET `/staff-manager` and render the homepage through Flask's
  existing Jinja engine, using this marketing directory as the template folder.
- `landing.html`: shared layout blocks and links to `/staff-manager`; navigation
  to other products uses homepage URLs so it works from either page.
- `staff_manager_content.html`: approved Staff section moved unchanged into one
  shared include; its copy, photos, features, credits and trial button are reused.
- `staff_manager.html`: dedicated title/description, shared product section,
  closing trial invitation, and mobile trial button.
- `test_staff_marketing.py`: direct-route, shared-content, trial-link, navigation
  and preserved-section checks now use rendered pages.
- `test_demo_security.py`: only the route-inventory expectation/name changes to
  account for the new marketing route; security behavior is untouched.
- This release note.

All trial buttons link to
`https://garage-voice.onrender.com/staff/account/register`.
No photos, dependencies, database tables, environment settings, Stripe code,
Staff application code or demo-security implementation change. Garage Voice,
PayChaser, their features and the existing demos retain their approved content.

## Focused validation

Final result: **30 Python tests passed with no skips; all ten browser checks
passed (two pages at five widths); git diff --check passed.**

From `ai-receptionist-engine`:

```text
python -m unittest marketing_site.test_staff_marketing marketing_site.test_demo_security -v
```

The suite includes 30 tests, with provider calls mocked or blocked and disposable
demo-security state. Browser QA covers both `/` and `/staff-manager` at 360, 393,
768, 1024 and 1440 pixels, decoded local images, responsive layout, trial URLs
and horizontal overflow. `/staff-manager` is a direct HTTP route, not a fragment
or client-side fallback. The homepage's existing product-section hashes remain
unchanged. `git diff --check` and a marketing-only commit-scope check are required.

## Manual release after approval

Hosting remains the existing Render service `trimtech-ai`, branch `main`, root
`ai-receptionist-engine/marketing_site`, start `gunicorn app:app`, empty pre-deploy
command and Auto-Deploy Off, as last confirmed by the operator. The commit also
includes `[skip render]` to prevent automatic Render deployment on push.

After approval, choose `trimtech-ai` > Deploys > Manual Deploy > Deploy a specific
commit and enter the exact SHA from the handoff. Preserve all existing settings;
run no migrations. Confirm the deployed SHA, `/health`, direct `/staff-manager`,
homepage navigation, photos and trial destinations on mobile and desktop. Keep
demo requests, registrations, payments and other production mutations out of
read-only smoke checks. Roll back only the marketing service to its recorded
previous deployment after checking Render's target environment snapshot.
