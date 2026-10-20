# Staff Manager navigation and performance review

Prepared on live PWA commit bec7cc7f330d30d2c6259d6c1fe9768265df981f.
Local review only: no push, deployment, production connection, migration,
Stripe activation, Render setting or plan change is authorised by this document.

## Changes

- Add a visible, 48px-minimum Back to Dashboard anchor above the collapsed menu
  on business manager pages, including inherited payroll/payslip/setup details.
  It uses the tenant's explicit dashboard URL, never browser history. The employee
  bottom navigation, workspace selection, manifest and worker are unchanged.
- Reuse one connection for Staff GET/HEAD fetch helpers within a request. Each
  query executes in autocommit mode and reads fresh committed data; no rows or
  credentials are cached. Teardown and errors close it. Every new request starts
  with a new connection. POST/CLI/other blueprints and explicit write transactions
  retain their previous transaction behavior. Auth, trials, GPS and mutation
  handlers are unchanged.
- Only compute setup checklist facts for the five manager templates which display
  them. Access checks and the fresh trial banner remain independent and unchanged.
- Apply selected IDs to the indexed shift side of the approved-estimate break
  join using a bigint array. Preserve business/employee join checks, exact break
  rows, existing per-shift payroll rounding and all calculations.

## Local measurements

Two disposable PostgreSQL 18.6 clusters, identical synthetic data: 100 additional
workers, 2,000 completed shifts and 2,000 breaks, active trial, ANALYZE after seed.
Figures are instrumented Flask response medians of five warm requests per page
after one first request. They exclude browser/WAN/Render startup time. This is a
local diagnostic sample, not a production latency promise or load test. Host
timings vary; connection/query counts are the deterministic regression evidence.

| Page | Before ms | After ms | Connections/request | SQL statements/request |
|---|---:|---:|---:|---:|
| dashboard | 5266 | 1270 | 23 → 4 | 32 → 32 |
| employees | 1014 | 490 | 11 → 3 | 20 → 17 |
| employee_home | 894 | 102 | 12 → 1 | 12 → 12 |
| clocking | 1178 | 96 | 12 → 1 | 12 → 12 |
| payroll | 1499 | 454 | 16 → 3 | 25 → 25 |

No external provider calls were needed: all benchmark Python outbound sockets
were blocked and database access restricted to the disposable loopback cluster.
An initial probe had a synthetic-session persistence mistake; it was corrected
before both final measurement runs. All old measurements/logs are retained.

The initial unanalysed schema exposed a poor nested-loop plan (2,001 repeated
break scans; approximately 8 seconds in EXPLAIN). With fresh statistics, the old
join was already fast (approximately 4.9ms); the typed shift-side join measured
approximately 2.5ms. Do not attribute the entire page improvement to this query
change: fewer connections are the main deterministic improvement. No production
ANALYZE, index or migration is included.

Static CSS/JS checked: approximately 1.6–10.1KB each, ETags present, conditional
requests return 304. Existing no-cache revalidation is retained for public static
assets. Authenticated HTML/API/payroll responses stay no-store/private. No worker
storage, sensitive cache, prefetch, offline mutation or replay is introduced.

## Remaining bottlenecks and operator observations

The dashboard still runs fresh wage/attendance aggregates and request-time schema
fingerprint checks. These costs and dense employee lists can grow with business
history. Schema drift detection and payroll rounding are intentionally preserved.
Persistent pooling or pagination would need separate measurement/design.

Render instance type, CPU/RAM pressure, actual worker count, database latency and
production response times were not inspected. If this is a Free service, Render
documents spin-down after 15 idle minutes and about one minute to resume:
https://render.com/docs/free . This could explain a slow first opening, not every
warm navigation. CPU saturation, memory pressure/restarts or a single busy sync
worker could also contribute; correlate the incident with Render Metrics and logs:
https://render.com/docs/service-metrics . Some latency graphs require Pro.
No plan/settings change was made or proposed as part of this release.

## Verification and release scope

Fresh tests cover request connection counts, per-query freshness, cross-request
and cross-tenant isolation, cleanup after disconnects, unchanged POST/other-product
transactions, approved-break scope/equivalence, all main manager pages and 16
manager main/detail URLs, employee navigation and workspace switching. The full
relevant Staff suite and four-width browser checks are recorded in the local
release evidence. Final counts and exact commit are in result.json outside the
application tree. A physical iPhone smoke check remains appropriate after a
separately approved deployment.

Runtime scope: static/staff_pwa.css; templates/staff_manager_mobile_nav.html;
trimtech/modules/staff/database.py, routes.py, onboarding_routes.py,
wages_estimate.py. Tests: test_staff_read_performance.py,
test_staff_manager_return.py, test_staff_estimate_query.py. This review is the
tenth file. No billing, migration, Garage Voice, PayChaser, employee-navigation,
GPS, service-worker, session-secret, business/employee record or payroll data change.

Final verification: 315 distinct relevant tests passed across isolated processes.
The long-process run passed 308 tests, then hit the legacy synthetic login
rate-limit bucket (429) because fixtures reuse alpha/the same IP. The failed
case and six unfinished cases passed in a fresh process; production rate limits
were not altered. A strengthened active-trial checklist query-budget assertion
also passed. This is split-run coverage, not a claim that the original long
process completed without a failure. Browser checks passed 72 layouts, 24
explicit dashboard-return clicks, and 20 worker safety cases per viewport.
The failed CDP timeout and narrow harness-filter correction are retained in the
evidence; passed checks were retained and only missing/unfinished checks rerun.
The 393px Employees back-link screenshot was visually inspected. All local
database clusters and synthetic preview servers stopped.
