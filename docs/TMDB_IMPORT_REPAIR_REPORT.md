# TMDB import repair

## Confirmed causes

- The older scheduled workflow exited successfully after its configuration
  check. Checkout, dependency installation, and the worker were skipped.
  [Original scheduled run](https://github.com/mohith3218/MD-make-your-day-booking-hub/actions/runs/45839691044)
- Sync #6 reached the intended Supabase PostgreSQL database and started the
  worker. TMDB returned HTTP 401. The worker wrote its failed attempt to the same
  Supabase database inspected during this repair.
  [Sync #6](https://github.com/mohith3218/MD-make-your-day-booking-hub/actions/runs/45876983632)
- Sync #7 checked in at 18:45:31 UTC on November 26. The retry from Sync #6 was
  due at 18:49:37 UTC. The database recorded no active lease or rate-limit
  cooldown. Sync #7 therefore made no import attempt.
  [Sync #7](https://github.com/mohith3218/MD-make-your-day-booking-hub/actions/runs/45878410598)
- The manual search combined API failures with the empty-results state and
  showed only eight results. Both import paths previously selected the configured
  read token even when TMDB rejected it and a working API key was available.
  A production manual-import error remains unconfirmed without access to the
  matching Render service.

## Repair

- `.github/workflows/tmdb-sync.yml` fails with the names of missing secrets and
  writes the run outcome to the GitHub Actions summary. The manual **force** input
  invokes the existing `sync-movies --force`. The database lease and rate-limit
  cooldown still apply.
- `cinewave/integrations/tmdb.py` normalizes credential formatting, checks the
  read token first, and tries the configured v3 key after an authentication
  rejection. The same client keeps using the verified method for its lifetime.
  It distinguishes credential, access, rate-limit, network, and upstream errors.
  [TMDB authentication](https://developer.themoviedb.org/docs/authentication-application)
- `cinewave/routes/admin/movies.py` and `templates/admin/import_movie.html`
  support title and ID lookup, original scripts, pagination, existing record
  links, and separate API errors. Import uses local theatrical dates when present.
  The client checks original-language and translated descriptions and other
  TMDB posters. Staff can fill missing descriptions or supply authorized HTTPS
  artwork. [TMDB search](https://developer.themoviedb.org/docs/finding-data) ·
  [TMDB movie images](https://developer.themoviedb.org/reference/movie-images)
- `cinewave/workers/movie_sync.py` persists discovered IDs and the page cursor in
  the existing sync tables. Each run reads at most 16 discovery pages and
  processes up to 40 films, with a 12-minute request budget. Commits and skip
  reasons are recorded incrementally. The admin dashboard shows worker check-in,
  queued work, counts, errors, and the manual Actions link.
- `cinewave/workers/tmdb_doctor.py`, `cinewave/factory.py`, and `cinewave/config.py`
  add read-only diagnostics and enforce PostgreSQL for production. The existing
  Supabase schema was already at Alembic head `20261126_02`. No production
  migration was necessary. The application keeps its existing TMDB ID uniqueness
  constraint and trailer metadata.

## Authentication and deployment

The existing `.env` v3 API key returned HTTP 200 for live TMDB movie details
and search. The local `.env` had no read token to verify separately. GitHub
confirmed the existing database secret and the `CINEWAVE_SYNC_TMDB_API_KEY`
fallback. The forced run log identified `api_key` as the working method.

The signed-in Render workspace listed only a service for `Lehan999/cineverse`.
Render denied access to the CineWave project supplied by the administrator. The
historical public CineWave URL returned HTTP 404. An authorized Render member
must verify the web service configuration and current public URL. On the linked service’s
**Environment** page, verify `APP_ENV=production`, `DATABASE_URL` for the same
Supabase database, and `TMDB_API_KEY` with the existing verified v3 key. Set
`TMDB_REGION=IN` for India. The optional `TMDB_READ_TOKEN` can remain unset if
the API key is configured. Enter secrets in the platform’s environment settings.
[CineWave Render project](https://dashboard.render.com/project/prj-dbqn93ifngtc7384mq0g)

## Commands

```text
python -m alembic current
python -m alembic heads
python -m flask --app app tmdb-doctor
python -m flask --app app sync-movies
python -m flask --app app sync-movies --force
```

Use the appropriate application environment for the database you intend to
inspect. Development uses SQLite. The hosted worker uses PostgreSQL.

## Verification

- The first forced run on `main` verified TMDB authentication, discovered 181
  unique candidates in its batch, imported 27, updated 3, skipped 10, and failed
  0. Read-only queries confirmed 30 distinct TMDB-linked movies in Supabase,
  up from 3. Additional discovered candidates were queued for subsequent runs.
  [First forced run](https://github.com/mohith3218/MD-make-your-day-booking-hub/actions/runs/45879095894)
- The second forced run resumed the queued candidates. It fetched movie
  details for another batch, imported 31, updated 0, skipped 9, and failed 0.
  Supabase rose from 30 to 61 distinct TMDB-linked movies. All 30 previous
  TMDB IDs retained their CineWave record IDs. Examples include *Ranabaali*
  (1389379) and *Crazy Kalyanam* (1610188). A read-only query also found 11
  upcoming records without a screening, including *Hello Kadhal* (1596658).
  [Second forced run](https://github.com/mohith3218/MD-make-your-day-booking-hub/actions/runs/45879617387)
- The live manual test signed in to the Flask administrator interface over
  HTTP with isolated UTF-8 PostgreSQL at the same migration revision as Supabase.
  An intentionally invalid fixture token received a real HTTP 401. The verified
  API key then returned three results for a Telugu-script search. An ID lookup
  and manual import saved *Bāhubali: The Beginning* (TMDB 256040), taking the
  isolated catalogue from zero to one. The same import returned the same record.
  The poster URL delivered an image, and the detail page, admin list, and customer
  catalogue displayed the record with no screening available.
- The isolated suite passed 124 Python tests and the booking integration script.
  Coverage includes force, rate limiting, concurrent lease claims, worker restart,
  resumable discovery, required metadata, manual duplicates, invalid credentials,
  and an unversioned database. Hosted storefront visibility and the hosted manual
  flow remain unverified because Render denied access to the correct project.
