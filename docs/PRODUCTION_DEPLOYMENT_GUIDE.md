# Production deployment guide

**Status:** Configuration gates are present; a production deployment is not yet ready to launch.

## Required settings

Set these in the deployment secret manager (never commit them):

- `APP_ENV=production`
- `SECRET_KEY` with at least 32 random characters
- `DATABASE_URL` for PostgreSQL
- `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`
- SMTP settings for ticket delivery, and `TMDB_API_KEY` if movie metadata lookup is used

Production requests fail closed when required database, session or payment configuration is absent. Secure session cookies and HSTS are enabled automatically. Mock payments are unavailable in production.

## Database and schema changes

SQLite remains the local default. Production currently requires a PostgreSQL URL, but this repository does not yet contain an Alembic baseline or reviewed upgrade scripts. Do not point production at this version until a migration baseline is created and tested against a copy of the actual database.

For a safe future migration: take a verified backup; restore it to a staging PostgreSQL instance; generate and review schema migrations; verify row counts and booking/payment relationships; run regression and concurrency suites; then schedule a controlled production cutover with a tested rollback/restore procedure. Never run `db.drop_all()` against customer data.

`test_flow.py` forces its own ignored `instance/test_flow.db` database before importing the app.

## Operational requirements still open

- Add PostgreSQL driver and tested pool sizing for the deployment worker count.
- Configure HTTPS at the trusted ingress, restricted hostnames, process supervision and log retention.
- Add encrypted, access-restricted backups and rehearse point-in-time restore.
- Add Alembic migrations, health/metrics monitoring, alerting and a background job runner for email/report work.
- Validate Razorpay production and webhook credentials using gateway sandbox/staging before accepting payments.

No deployment, backup restore, live payment or throughput test has been performed in this workspace.
