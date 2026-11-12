# Supabase PostgreSQL setup

The application remains Flask + Flask-SQLAlchemy. Supabase supplies PostgreSQL;
there is no Supabase Python client, Supabase Auth replacement or frontend database key.

## Configure the backend

1. Install dependencies in the project's virtual environment:
   `python -m pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` only if `.env` does not already exist.
3. In Supabase's Connect panel, copy the **Session pooler** URI on port 5432
   (useful on IPv4 networks), or the direct PostgreSQL URI if IPv6 is available.
4. Store the actual URI as `DATABASE_URL` in `.env`. Encode the password component
   with `urllib.parse.quote(password, safe='')` exactly once, before inserting it
   into the URL. Do not encode the entire URI or double-encode an existing encoded
   password. Replace password placeholder brackets with the encoded actual password.

Example with placeholders only:

```dotenv
APP_ENV=development
DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:ENCODED_PASSWORD@POOLER_HOST:5432/postgres?sslmode=require
SECRET_KEY=YOUR_PRIVATE_RANDOM_SESSION_SECRET
```

`postgres://` and `postgresql://` are normalized to `postgresql+psycopg://`.
TLS defaults to `require`; weaker modes are rejected. For certificate and hostname
verification, download the database CA from Supabase and use
`sslmode=verify-full&sslrootcert=/absolute/path/to/ca.crt` in the URI.

The shell takes precedence over `.env`: remove a stale shell `DATABASE_URL` before
expecting `.env` changes to take effect. Restart Flask after configuration changes.
Never paste the actual URI into tracked files, screenshots, frontend code or logs.
`.env`, instance databases, backups and local migration results are Git-ignored.

The application uses a small SQLAlchemy pool (3 connections, 2 overflow per worker),
15-second pool wait, 10-second connection timeout, pre-ping, and 300-second recycle.
Prepared statements are disabled for pooler compatibility. Budget connections across
all workers. This guide uses session mode; transaction-mode poolers are not verified.

## Migrate existing records

Stop application writes during the transfer and final cutover. The source is always
opened read-only; SQLite's backup API creates a consistent independent snapshot.
The transfer does not seed or regenerate venues or screen layouts.

```powershell
# First back up and validate the source, without accessing a remote database.
python migrate_sqlite_to_postgres.py

# Create the versioned schema on a fresh target using the configured DATABASE_URL.
python run_create_db.py

# Schema, version, connectivity and fresh reconnection checks.
python database_health.py

# Transfer, verify every table's count and content, and commit atomically.
python migrate_sqlite_to_postgres.py --apply
```

`run_create_db.py` runs `alembic upgrade head`. The baseline creates 18 tables,
foreign keys, unique constraints and indexes. It does not drop existing tables,
seed data, change credentials or silently adopt an existing unversioned schema.
If application tables already exist on the target, investigate their provenance;
do not delete them or blindly stamp the baseline. Existing local SQLite installations
retain the legacy SQLite-only upgrade path; the transfer requires source columns
to match the current models and fails explicitly on mismatches.

The transfer requires an empty application dataset or an exact rerun of the same
snapshot. A different nonempty target is rejected; it never merges conflicting
records, overwrites rows or silently skips errors. It locks application tables during
the transaction, copies in foreign-key order with original IDs, verifies counts and
SHA-256 content digests, and advances PostgreSQL ID sequences. Exact reruns verify
without inserting duplicates. Sequence changes can leave harmless gaps on rollback.

Results and backup locations are written to `instance/supabase-migration-result.json`.
`snapshot_verified` means only the source was checked; only
`committed_and_verified` reports a completed PostgreSQL copy. Retain the backup
until application verification is complete. Never delete the original SQLite file.

## Run and verify

Use `APP_ENV=development` for local SQLite, or `APP_ENV=production` with
`DEMO_PAYMENTS_ENABLED=true` for the hosted demo. Production startup checks the schema and never seeds or resets
the migrated administrator. Run `python app.py`, sign in using the existing admin
and customer passwords, inspect the catalogue and history, then perform a demo
booking and payment. Check Sri Melody, INOX Varun Beach Screen 5 and Jagadamba 70MM
seat maps and interactive 3D previews in a browser.

SMTP and payment settings remain in `.env.example`. Configure SMTP for actual OTP
and ticket email delivery. For a production deployment, existing validation also
requires a stable secret (at least 32 characters) and PostgreSQL. Set
`DEMO_PAYMENTS_ENABLED=true` explicitly to enable demo checkout in production.
No payment provider secrets are used. See the Render deployment guide for commands.

```powershell
python test_database_migration.py
python test_flow.py
python -m unittest test_auditorium_geometry
node test_chair_assets.cjs
node test_phase_2_1_4_geometry.cjs
node test_seat_mapping.cjs
```

Run these commands separately. Both database test scripts allocate temporary SQLite
files under `instance/`, overriding any remote URL. `test_flow.py` also clears live
payment, SMTP and TMDb credentials before import. It never drops a remote database.

## Security and troubleshooting

The baseline enables RLS on all application tables in PostgreSQL with no public Data
API policies. Flask uses the trusted SQL database role; do not replace it with an
anonymous API key. Before any future Data API integration, design and test explicit
policies and grants. No service-role key is needed by this application.

For connection failures, run `python database_health.py`. It reports safe diagnostics,
the database version, missing tables/columns and schema revision without returning
driver exception details. Check project status, network restrictions, URI encoding,
TLS certificates, and the chosen direct/session-pooler endpoint privately. Re-run the
health check after recovery; pre-ping recovers stale pooled connections on checkout.
Failed in-flight transactions are not automatically replayed.

References: [Supabase database connections](https://supabase.com/docs/guides/database/connecting-to-postgres),
[SSL enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement),
[Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html).
