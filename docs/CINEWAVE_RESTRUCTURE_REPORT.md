# CineWave restructuring

## Project layout

The checkout mixed maintenance scripts, tests, saved previews, slide decks, and
application code at the repository root. Its largest booking and admin route
files also combined several unrelated operations. Templates used a flat
namespace, and the TMDB client and scheduler shared the general services folder.

```text
cinewave/
  config.py, database.py, extensions.py, factory.py
  hooks.py, security.py, time.py
  models/
  routes/admin/, routes/booking/, routes/
  services/
  integrations/
  workers/
templates/
  account/, admin/, auth/, booking/, movies/, reviews/, theatres/, components/
static/
  css/, js/, images/
migrations/
tests/
tools/
scripts/
  database/, development/
docs/
artifacts/
```

The booking blueprint is split into seats, previews, checkout, split payment,
payments, and tickets. Admin routes are grouped into the dashboard, movie
management, venues, and operations. The TMDB client moved to
`cinewave/integrations/tmdb.py`, the scheduler to `cinewave/workers/movie_sync.py`,
and seat selection assets to `static/css/booking.css` and `static/js/booking.js`.
Flask endpoint names, `app:app`, Alembic, and `sync-movies` retain their entry points.
Historical presentation and preview artifacts moved into `artifacts/`. The
duplicate database initializer and duplicate demo scripts that reset the
database were removed. Isolated fixtures replace those reset scripts for testing.

## Trailer sources

TMDB metadata and its video endpoint supply validated YouTube IDs. The movie's
original language takes priority among official trailers, then other official
trailers, other trailers, and official teasers. Missing trailers are reconsidered
in batches of up to 30 and checked again after seven days. Existing API retry
and rate-limit handling remains in the worker. In Admin → Edit Movie → Trailer,
staff can preview the current selection, choose an authorized Cloudinary MP4
or WebM, save a YouTube override, hide playback, or restore automatic results.

The film page creates a 16:9 YouTube privacy-enhanced iframe or a native
Cloudinary player only when opened. Closing the dialog unloads the player.
The original viewing link remains available if an embed fails. The migration
preserves how existing YouTube choices were selected and keeps the legacy
upload paths for reference. Administrators can replace those uploads with
authorized hosted URLs. [TMDB videos API](https://developer.themoviedb.org/reference/movie-videos) · [YouTube player documentation](https://developers.google.com/youtube/player_parameters) · [Cloudinary video delivery](https://cloudinary.com/documentation/video_manipulation_and_delivery)

## Reviews and booking

Theatre pages now have an integrated review list, one rating per reviewer and
venue, a distribution, sorting, pagination, and a no-review state. An explicit
theatre review takes priority over that member's most recent published screen
review. Screen scores use screen feedback. Movie pages keep CineWave's five-star
ratings separate from TMDB ratings and show written reviews to eligible viewers.

Review submission requires an owned, confirmed booking with captured payment
evidence. The server uses an actual UTC ending time when recorded, or a valid
cinema-local start and runtime. There is no live feed of actual showing end times.
Movie and theatre reviews can be submitted
independently. Dismissal lasts for the browser tab session. My Bookings retains
pending and editable reviews. Demo bookings are labeled separately.

The booking journey now displays progress, places the seat map prominently,
and moves party and seat exploration tools into expandable sections. Wide seat
maps scroll within the map on mobile, with a sticky selection summary. Checkout
keeps snacks and CinePass points behind an optional section. Returning to seats
reopens the same hold and reference while they remain valid, and the server
rechecks seat availability before saving a change. Unsaved choices in a tab are
scoped to one screening. Payment and the 2D/3D preview use the existing booking
system.

## Schema and dependencies

- `20261126_01` separates automatic trailer metadata from manual selections
  and stores Cloudinary URLs.
- `20261126_02` adds optional UTC show endings and theatre fields to the
  existing screen review table, with a unique explicit review per user and
  venue. It also allows rating-only movie reviews while retaining the star-range
  check.
- SQLAlchemy was pinned to its supported 2.0 line as an existing dependency.
  The Windows virtual environment was rebuilt with the pure-Python build.
  PostgreSQL verification used the workstation's installed libpq through
  Psycopg's Python implementation. Cloudinary needs no API credentials.

## Start and operate

Run these commands from the repository root in PowerShell.

```powershell
$env:APP_ENV = 'development'
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe app.py
```

Set `ADMIN_PASSWORD` when initializing a fresh development database. For an
existing versioned database, the operator should back up the intended database
and run these commands with that environment configured before starting the app.

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe database_health.py
```

The expected head is `20261126_02`. Both upgrades were exercised on isolated
databases. Production still requires an authorized rollout and migration.

Run the existing worker after configuring TMDB credentials and migrating the
target database:

```powershell
.\.venv\Scripts\python.exe -m flask --app app sync-movies
```

The existing scheduler configuration remains in
[the deployment guide](PRODUCTION_DEPLOYMENT_GUIDE.md#schedule-the-tmdb-catalogue-worker).
Before deploying, staff should replace any still-needed legacy uploads with
authorized hosted trailers. Compressed 360p or 480p Cloudinary videos can reduce
mobile bandwidth. Some YouTube videos disable embedding and can still be opened
through the original viewing link.

## Verification

- Rebuilt the Python 3.12 environment and passed `pip check`. Started Flask and
  checked the `sync-movies` command. Tests exercised worker discovery, trailer
  backfill, restart recovery, and administrator override protection. A live,
  read-only TMDB request returned Telugu video metadata and selected a trailer.
- `python tools/run_isolated_python_tests.py` passed 115 unit tests and the
  booking and payment integration script. Three additional catalogue, layout,
  and featured-movie suites passed 19 tests. The standalone Node run passed 31
  tests across carousel, authentication, seat mapping, and 3D preview behavior.
- Migrated isolated SQLite and PostgreSQL 18 databases from `20261125_02` to
  `20261126_02`. Checks covered legacy trailer metadata, existing reviews and
  moderation reports, SQLite foreign keys, and PostgreSQL schema health.
- `node tools/test_cinewave_experience_browser.cjs home imported-movie theatre
  seats checkout admin-movies` ran against a local Flask server. Chrome verified
  seat selection, returning from checkout to the same hold, demo payment, the
  post-show prompt, both review forms, and the 3D auditorium's first frame.
  Cloudinary video played and displayed an error fallback. The YouTube check
  verified lazy loading, the privacy-enhanced iframe, unloading, and the
  original link. Playback from YouTube itself remains unverified.
- Checked viewport overflow and sampled contrast across six pages in both themes.
  Captured 84 screenshots at seven sizes, including all five requested sizes.
  Inspected rendered phone and desktop examples. Screenshots and logs are in
  the ignored `instance/` directory.

The browser run used demo payments. Live payment processing and outbound email
delivery were outside the verification environment. No production migration or
deployment was performed.
