# Staff Manager marketing publication candidate

Design and commit/push approved on 17 October 2026. Live deployment is not approved.

## Scope and hosting evidence

Repository: `kayserbaks88-ctrl/garage-ai-agent`. Website deployment branch: `main`,
confirmed by the operator for this release. The direct parent is the confirmed
live commit `ffa0b6d84d0369345e4008b03fb60a1c32c07521`. Remote main was fetched at
`df648cf9ffb8775b1054037dcaae96cfd936b7ce`; the push therefore includes the already-live
security commit ffa0b6d unchanged, followed by one new marketing-design commit.

The operator has confirmed a **Render web service named
`trimtech-ai`**, with root `ai-receptionist-engine/marketing_site`, build command
`pip install -r requirements.txt`, start command `gunicorn app:app`, and blank
pre-deploy command. Service, branch, root, start command, empty pre-deploy,
**Auto-Deploy OFF**, and live commit ffa0b6d are operator-confirmed. Build command
is retained from earlier operator configuration and should be reconfirmed before
deployment. This is separate from `garage-voice-agent`. Dashboard evidence is
operator-supplied, not independent API inspection. Do not substitute the
application service or change the existing service configuration.

The release commit uses **[skip render]** to suppress Render automatic deployment
on push without editing settings. No repository GitHub Actions workflows were
present in the website parent. Do not remove the skip marker by amending
or merging with an unmarked commit before live approval.

Only marketing files change: landing page, photo MIME handling, 15 responsive
photo exports, photo credits, marketing tests and this handoff. Garage Voice,
PayChaser, their feature/demo sections and existing poster remain unchanged.
No Staff application changes, migrations, backfills, dependencies or environment
changes are required. All trial links use exactly:

`https://garage-voice.onrender.com/staff/account/register`

The 20 files added/modified by the design commit, all relative to the marketing root:

```text
app.py
landing.html
STAFF_MANAGER_PUBLICATION.md
STOCK_PHOTO_CREDITS.md
test_staff_marketing.py
static/staff-manager/mobile-clock-in-320.webp
static/staff-manager/mobile-clock-in-640.webp
static/staff-manager/mobile-clock-in-960.webp
static/staff-manager/mobile-clock-in-1440.webp
static/staff-manager/mobile-clock-in-960.jpg
static/staff-manager/shift-planning-320.webp
static/staff-manager/shift-planning-640.webp
static/staff-manager/shift-planning-960.webp
static/staff-manager/shift-planning-1440.webp
static/staff-manager/shift-planning-960.jpg
static/staff-manager/workplace-team-320.webp
static/staff-manager/workplace-team-640.webp
static/staff-manager/workplace-team-960.webp
static/staff-manager/workplace-team-1440.webp
static/staff-manager/workplace-team-960.jpg
```

Demo security is preserved from the live baseline: demo.html, demo_security.py,
DEMO_SECURITY.md and both existing demo-security tests are unchanged. The only
app.py change adds WebP MIME handling. The empty source screenshot archive and
staff-stripe-corrections.ps1 are excluded. If live changes again before deployment,
reconcile that new baseline before approving this exact SHA.

## Validation

Final isolated candidate result: **26 Python tests passed, zero skips; all five
browser viewport checks passed; git diff --check passed.**

From `ai-receptionist-engine`:

```text
python -m unittest marketing_site.test_staff_marketing marketing_site.test_demo_security -v
```

Seven new release tests cover exact trial links, preserved product-section hashes, serving
all 16 referenced images with image MIME types, responsive/accessible stock-photo
markup, navigation targets, unchanged route inventory and public GET routes with
provider network calls blocked. The 19 existing demo-security tests are also run
unchanged with mocked providers and disposable state. Browser checks cover 360, 393, 768, 1024 and 1440
pixels, decoded stock photos, responsive source selection and no horizontal overflow.
No live email, WhatsApp, registration, payment or database operation is part of QA.

## Manual deployment — after separate live approval

1. Open Render > `trimtech-ai` > Settings. Reconfirm repository, branch `main`,
   marketing root, existing build/start commands and empty pre-deploy command.
   Record the currently successful deployment's full SHA and available rollback
   artifact. Resolve any baseline mismatch described above before proceeding.
2. Open Deploys > Manual Deploy > **Deploy a specific commit**. Paste the exact
   full release SHA from the handoff. Do not select Deploy latest commit, trigger
   a deploy hook or deploy the Staff application service. The dashboard's
   specific-commit action disables automatic deploys as part of that approved
   deployment; no settings are changed during preparation/push.
3. After live approval, select Deploy Commit. Preserve all environment variables,
   databases and service commands. Run no migrations or provisioning commands.
4. Confirm Render reports that exact SHA and healthy startup. On the actual
   configured website hostname, check GET `/health`, GET `/`, GET `/demo`, photos,
   existing video/demo links, mobile/desktop layouts and the trial link's exact
   destination. Do not submit demo requests, register customers or make payments
   as smoke tests. Verify Garage Voice and PayChaser health separately.

## Rollback

After approval, use the previously recorded successful marketing deployment's
rollback artifact. Inspect its environment snapshot first: Render rollback reuses
the target deployment's environment variables. Do not overwrite saved settings,
restore databases or redeploy the Staff service. If the snapshot is unsuitable,
prepare a compatible corrective marketing commit with the current verified
configuration. Verify restored SHA and repeat read-only website health checks.

References: https://render.com/docs/deploys and https://render.com/docs/rollbacks.
Photo licence and photographer sources are recorded in STOCK_PHOTO_CREDITS.md.
