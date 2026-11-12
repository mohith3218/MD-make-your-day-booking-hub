# Demo payment and hosting preparation report

12 November 2026. Starting branch: `main`, commit `9c0653e`.
The starting working tree was clean. No push, deployment, remote database query,
account-setting change or schema migration was performed.

## Implementation

- Removed the live provider SDK dependency, clients, provider environment variables,
  checkout template, script, API verification and webhook route. Removed the same
  variables from the private ignored `.env` without logging their values.
- Kept existing mock order IDs and gateway values for stored-record compatibility.
  The simulator never contacts an external provider. Production requires explicit
  `DEMO_PAYMENTS_ENABLED=true`; otherwise all payment/recharge entry points reject
  attempts. Private session keys, HTTPS cookies and authorization remain required.
- Demo signatures use the private app secret. The server rejects unknown methods,
  invalid amounts/outcomes, wrong booking owners, external order types and forged
  signatures. Completed-booking callback replays cannot change a success to failure.
- Preserved seat layouts/IDs, locking, concurrency protections, expiry, calculations,
  wallet credits, split shares, cancellation, refund and booking history workflows.
- New demo payment metadata says `demo=true` and `settled=false`; legacy workflow
  states remain compatible. Historical records are not rewritten. Unknown historical
  provider values remain readable but cannot be completed by the simulator.
- Checkout, virtual wallets, booking history, analytics and ticket pages identify
  demo amounts. Demo QR payloads begin `DEMO|`; optional email notices and CSV rows
  also identify demo records. No sensitive payment inputs are collected.
- Added Gunicorn and a read-only production startup preflight. The same Flask/Jinja
  service serves the frontend, backend and existing Three.js assets.

## Files changed

- Core: `app.py`, `payments.py`, `requirements.txt`, `.env.example` and the ignored
  private `.env` (only retired provider settings and comments removed).
- Added: `gunicorn.conf.py`, `test_demo_payments.py`, this report.
- Tests: `test_flow.py`, `tools/check_low_risk_ui.py`.
- Templates: `base.html`, `checkout.html`, `pay_mock.html`, `split_pay.html`,
  `split_pay_mock.html`, `ticket.html`, `wallet.html`, `dashboard.html`,
  `admin_analytics.html`.
- Documentation: `README.md`, `.freebuff/run.md`, `docs/PRODUCTION_DEPLOYMENT_GUIDE.md`,
  `SECURITY_AUDIT.md`, `SUPABASE_SETUP.md`, `MAINTAINABILITY_AUDIT.md`,
  `IMPROVEMENT_TEST_RESULTS.md`, `LOW_RISK_POLISH_REPORT.md`.
- Removed: obsolete live-provider checkout template, `app.py.bak-20261111` and
  `27d2201.patch`. The latter two were tracked source snapshots containing retired
  implementation, not database backups. Git history remains intact.

Database configuration, health implementation, Alembic files, theatre/seat data,
static chair assets and the auditorium renderer were not changed.

## Verification

- `python test_flow.py`: passed the complete booking regression plus new demo
  ownership, replay, disabled-mode, split failure/retry/success and ticket-label
  checks. Includes registration/login, browsing, locks, concurrent reservation,
  wallet payments, e-ticket/QR, cancellation/refunds, analytics and CSV.
- `python -m unittest test_demo_payments test_auditorium_geometry test_database_migration`:
  24 tests passed. Production WSGI probes use a dummy loopback PostgreSQL URI with
  network connections prohibited and health results mocked. The real read-only
  startup branch is exercised with DDL/seeding forbidden. No live PostgreSQL
  connectivity or Gunicorn process launch is implied.
- Additional malformed-input checks passed in the 5-test demo suite, including
  non-ASCII/missing signatures and invalid/overflowing amounts.
- `python tools/check_low_risk_ui.py`: 16 rendered route cases and 25 rendered
  JavaScript syntax checks passed, including five auditorium configurations.
- `node --test test_chair_assets.cjs test_seat_mapping.cjs tools/test_preview_lifecycle.cjs`:
  18 tests passed.
- Python compilation and `git diff --check`: passed.
- Case-insensitive project scan found zero retired-provider name/key/prefix
  references in source, dependencies, configuration, documentation and tests.
  Git history, third-party environments, binary data/backups, logs and generated
  instance artifacts are excluded from this source scan and are not rewritten.

Initial regression runs found a changed caption assertion and a detached test
fixture object; both were corrected before the successful regression pass.
Expected unconfigured-SMTP errors and existing deprecation warnings remain.
No actual email, payment, remote database access or new browser/WebGL verification
was performed. Gunicorn requires a Unix runtime; its actual server command was not
executed on this Windows host.

## Render configuration

Build: `pip install -r requirements.txt`

Start: `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 app:app`

Required settings for the functioning hosted demo:

```dotenv
APP_ENV=production
DATABASE_URL=<existing private Supabase PostgreSQL connection URI>
DATABASE_SSLMODE=require
SECRET_KEY=<private random value with at least 32 characters>
DEMO_PAYMENTS_ENABLED=true
```

`TMDB_API_KEY` is optional for import/cast lookup. Existing production accounts do
not require ADMIN_PASSWORD. No payment provider secrets are used. Do not execute
reseed, transfer or baseline-migration scripts as part of the build.

## Remaining deployment checks and limitations

Actual Render deployment and existing Supabase connectivity/schema health must be
verified when deployment is separately authorized. The app refuses unhealthy
production startup instead of mutating the database. Standard SMTP ticket delivery
is blocked by Render Free; on-screen tickets and current demo registration work
without it. Uploaded local media is not durable on an ephemeral filesystem. Free
services can sleep. See the deployment guide for official sources and details.

Existing CSRF/rate-limiting gaps noted in the security audit remain outside this
focused provider-removal task. No real-money use is supported or implied.
