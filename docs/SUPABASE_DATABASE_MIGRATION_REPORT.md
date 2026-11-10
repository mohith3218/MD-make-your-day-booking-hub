# Supabase database migration report

Date: November 10, 2026. Project: MD Make Your Day Booking Hub.

## Status

**Implementation and local rehearsal completed. Live Supabase migration pending
the actual connection URL.** The user explicitly requested that credentials not be
inferred. No `.env` was present during verification. No Supabase connection, remote
schema upgrade, remote copy or remote authentication success is claimed.

The original `instance/vizag_movies.db` was backed up using SQLite's consistent
backup API. Its integrity and foreign keys were checked. A full local rehearsal
verified every table's count and content, and confirmed that the original database
file was byte-for-byte unchanged. Backups and machine-readable evidence remain
under ignored `instance/backups/`, `instance/supabase-migration-result.json` and
`instance/migration-rehearsal.json`.

## Architecture audit

Previously, `app.py` owned a global Flask app, Flask-SQLAlchemy connection, 18 models,
Flask-Login authentication and all booking/payment routes. `DATABASE_URL` already
existed with `sqlite:///vizag_movies.db` as the fallback. `init_db()` used
`create_all()`, a handwritten SQLite column-adder and catalogue/movie seeding.
There was no Alembic history. The original startup reset the admin password on
every invocation and printed it; this behavior has been removed.

The new backend keeps the same Flask application, SQLAlchemy models, relationships,
routes, login system, seat data and payment demonstration. `database_config.py`
normalizes PostgreSQL URLs to Psycopg 3, requires TLS and configures bounded pooling,
pre-ping, recycling and connection timeouts. SQLite remains the local fallback.
`.env.example` now contains placeholders; real credentials belong exclusively in the
Git-ignored backend `.env`. Payment configuration is imported after `.env` is loaded.

PostgreSQL initialization checks connectivity/schema instead of auto-creating or
seeding records. Alembic revision `20261110_01` is a frozen baseline of the existing
18 models, including foreign keys, unique constraints and indexes. PostgreSQL RLS is
enabled with no public policies; this application accesses SQL using its trusted
backend role. Supabase Auth and the Data API are not introduced.

## Schema compatibility

| Area | Finding and handling |
|---|---|
| Models | User, Movie, Watchlist, MovieRating, Theater, Screen, Showtime, Booking, BookedSeat, SeatLock, SeatHold, Payment, SplitContribution, Wallet, WalletTransaction, RechargeRequest, PartySession, PartyMember retained |
| Primary keys | Integer IDs preserved; PostgreSQL SERIAL sequences advanced after copy |
| Relationships | Existing foreign keys and dependency order preserved; source foreign-key check passed |
| Uniqueness | User identity, booking references, wallet ownership, per-show sold/held seats and split-share constraints retained |
| Indexes | Existing model indexes included in frozen baseline |
| JSON | Existing JSON remains TEXT; exact serialized layout/profile strings are verified, with no JSONB conversion |
| Booleans | SQLAlchemy converts SQLite booleans to native PostgreSQL BOOLEAN |
| Dates/times | Existing Date and naive UTC DateTime semantics retained; PostgreSQL uses DATE and TIMESTAMP WITHOUT TIME ZONE |
| Money | Existing Float fields and rounding retained for demo compatibility; no unrequested Decimal conversion |
| Transactions | Copy uses one transaction with target locks; failed rows abort the copy rather than being skipped |
| SQLite-specific migration | DATETIME and BOOLEAN DEFAULT 0/1 legacy SQL is guarded as SQLite-only; PostgreSQL uses Alembic DDL |
| Analytics | Existing SQLAlchemy date/group/aggregate expressions retained; remote runtime verification remains pending |

All 18 model table definitions compile for the PostgreSQL dialect. Source column
sets match the current model schema; no source schema updates were necessary.

## Record counts

These are **source versus temporary SQLite rehearsal target**, not Supabase counts.
Every row's typed contents were also verified using SHA-256 digests in primary-key
order; count equality alone was not treated as sufficient evidence.

| Table | Source | Local rehearsal target | Supabase |
|---|---:|---:|---|
| user | 6 | 6 | Pending |
| movie | 6 | 6 | Pending |
| theater | 89 | 89 | Pending |
| screen | 127 | 127 | Pending |
| showtime | 45 | 45 | Pending |
| movie_rating | 8 | 8 | Pending |
| wallet | 6 | 6 | Pending |
| wallet_transaction | 7 | 7 | Pending |
| recharge_request | 1 | 1 | Pending |
| booking | 6 | 6 | Pending |
| booked_seat | 3 | 3 | Pending |
| payment | 5 | 5 | Pending |
| watchlist | 0 | 0 | Pending |
| seat_lock | 0 | 0 | Pending |
| seat_hold | 0 | 0 | Pending |
| split_contribution | 0 | 0 | Pending |
| party_session | 0 | 0 | Pending |
| party_member | 0 | 0 | Pending |

All 127 individual screen JSON profiles were preserved exactly in the rehearsal,
including geometry, wall configurations, reference metadata and confidence labels.
No catalogue regeneration is performed by the transfer utility. Local seed tests
confirmed a second initialization adds zero venues/screens and preserves the admin
hash; catalogue counts remain 89 venues and 127 screens.

## Verification

- Migration/configuration tests exercise typed row preservation, fixture password
  authentication and admin privilege preservation, exact reruns, conflict refusal,
  transaction rollback, health/reconnection, PostgreSQL DDL compilation, baseline
  parity and rejection of remote/development URLs in test configuration.
- Full `test_flow.py` passed: real fixture customer/admin login, seat maps, selection,
  concurrent holds, wallet payment, demo gateway payment, forged-signature rejection,
  confirmation/QR, history/dashboard routes, cancellation/refund, admin analytics and
  existing restrictions against production mock payments.
- Sri Melody, INOX Varun Beach Screen 5 and Jagadamba 70MM persisted-layout seat-map
  and 3D preview routes returned HTTP 200 in isolated fixtures.
- Nine Python auditorium geometry tests passed. JavaScript chair asset (4),
  auditorium geometry/lighting (6) and seat mapping (11) checks passed.
- Existing unrelated renderer/template work in the checkout was preserved. This
  integration did not edit renderer assets or the 3D template.
- Test SMTP is intentionally disabled; ticket email attempts report configuration
  errors while bookings and downloadable tickets still succeed. Actual email
  delivery was not verified.

The migrated source admin password hash was preserved by content verification.
Original account password authentication on PostgreSQL remains pending; local
fixture authentication is not presented as evidence of remote account login.

## Safe cutover and remaining work

Follow [SUPABASE_SETUP.md](SUPABASE_SETUP.md). Once the actual URL is securely
provided: configure ignored `.env`, check connectivity, apply Alembic on the fresh
target, transfer with `--apply`, inspect committed counts/content verification,
then verify existing account logins and the full booking/payment flow against
Supabase. Keep application writes stopped during snapshot/cutover to avoid losing
changes made after the snapshot. Preserve the original SQLite file and backups.

Live PostgreSQL constraint enforcement, sequence resets, RLS, pool recovery and
Supabase authentication have not yet been executed. Browser/WebGL visual inspection
against the migrated backend also remains pending; route and geometry tests do not
substitute for that inspection. No local PostgreSQL server was used in the rehearsal.

The utility is intended for this small demonstration dataset and holds a snapshot
in memory. It rejects differing nonempty targets, unknown source tables and column
mismatches instead of performing an implicit merge. Older SQLite schemas require
reviewed upgrades on a copy before transfer. In-flight transactions are not replayed
automatically after a disconnect. Existing floating-point money and naive UTC time
semantics remain intentional compatibility limitations.
