# CineWave theme, hype and screen reviews

The implementation extends the existing Flask application and database. Work began at `80d6897`, which matched GitHub `main` when compared.

## Theme and account pages

- `static/css/coastal.css` defines warm Light and Dark tokens for text, fields, focus indicators, actions, surfaces and status colors. The shell uses translucent navigation and menus with an opaque fallback. Cards and summaries use raised gradient surfaces. `static/css/cinematch.css` uses those tokens for selected moods, film placeholders and empty states.
- `templates/base.html` applies the saved theme before the app styles load. The theme selector continues to offer Light, Dark and System Default. Account pages now offer the same selector.
- `static/css/auth.css` and `templates/auth_base.html` supply shared styling for sign-in, registration, email verification, recovery and password reset. Password fields start masked. The existing Show/Hide script also controls the two reset-password fields.

## Movie hype

- `cinewave/routes/movies.py` writes to the existing `MovieHypeVote` model through a SQLite or PostgreSQL upsert on the current user and movie. The same choice preserves the vote. A different choice moves it to that level. The server returns persisted counts, and the route accepts the three existing levels with a valid session and CSRF token.
- `templates/partials/movie_hype.html` renders the same three reactions on upcoming movie cards and movie detail pages. `static/js/movie-hype.js` updates the count and selection after the server responds. Standard form submission is available when JavaScript is unavailable.

## Screen reviews and moderation

- `cinewave/models/reviews.py`, `cinewave/services/screen_reviews.py` and `cinewave/routes/screen_reviews.py` implement screen-level reviews with one record per booking. The server checks the authenticated owner, paid booking, linked screen, and scheduled end time in Visakhapatnam. Known demo payment gateways and non-captured payment records are ineligible. Historical bookings with a recorded `PAID` status can qualify when no separate payment row exists. “Verified Booking” describes the booking record and scheduled screening. The app has no admission-scan records.
- Tickets and My Bookings show eligible review actions. Dismissing the invitation suppresses the prompt for that signed-in browser session while keeping the action available on the ticket. Reviewers must supply an overall rating and can skip sound, AC, seat comfort or comments. The owner can edit their review or withdraw it from public display. Withdrawal keeps the historical record and prevents a replacement for the same booking.
- The existing Theatres flow shows actual screen ratings, verified counts, distribution, dates, written comments and filters. The theatre rating uses the total of the underlying review scores divided by the review count. An unrated screen or theatre displays “Not rated yet.” Movie ratings are stored in their existing model.
- The screen review pages replace the generated comfort claims previously displayed on movie and seat-selection pages. The seat inspector identifies its modeled audio values as estimates based on seat position. Portal admins can find reports, hide or restore a review, and resolve reports. Moderation stores the action, admin and time. Review ratings remain author-controlled, and hidden or withdrawn reviews are excluded from customer scores.

## Migration

Revision `20261123_01` follows `20261119_01` and adds `screen_review`, `screen_review_report` and `screen_review_moderation`. The migration adds foreign keys, the booking and report uniqueness constraints, rating checks and visibility indexes. The production schema health check now expects `20261123_01`.

On an existing Alembic-managed database, the operator applies `alembic upgrade head` and runs `python database_health.py`. The deployment guide describes the backup and migration workflow. Downgrade removes the three newly added tables, so export any accumulated reviews and moderation history first.

## Automated verification

### Booking, payments and 3D regressions

- The isolated Python runner passed all 94 tests, plus the end-to-end booking and demo-payment flow. It covered seat conflicts, wallet and gateway demo payments, split payments, refunds, archived movies, auditorium routes and seat geometry.
- The standalone Node runs passed 31 checks across auth controls, featured movie interaction, seat mapping, chair assets, auditorium geometry and preview lifecycle. The isolated runner also executed seven browser-script unit checks for booking and preview sync.
- The catalogue, featured-movie and layout-shell suites passed.

### Review and hype behavior

- `test_screen_reviews.py` passed seven route and database tests covering eligibility, ownership, screen and theatre IDs, rating validation, review withdrawal, reports, moderation, genuine counts, weighted aggregates and Hype vote updates.
- Chrome exercised password masking, System Default and saved themes, login feedback, Hype success and error feedback, review creation, keyboard star selection, empty screens and the admin moderation view.

### Migration preservation

- The SQLite upgrade from `20261119_01` preserved representative account, catalogue, booking, payment, movie rating and Hype records exactly. The schema comparison and health check also passed.
- The PostgreSQL dialect generated the additive DDL successfully, and hosted driver, TLS and pooling configuration tests passed. Execution against a live Supabase database remains unverified.

### Browser verification

- Headless Chrome verified Light and Dark at 360, 390, 430, 768, 1024, 1366 and 1920 CSS pixels. The 14 views cover sign-in, registration, the home hero, Hype cards, movie detail, CineWatch, theatre listing and detail, screen reviews, the review form, moderation, tickets, seat selection and checkout.
- The runs produced 196 theme and viewport screenshots. Checks included document width, sampled text contrast at 4.5:1 or better, keyboard star controls, the 1024px admin menu and a mobile seat map with its own horizontal scrolling. Native password-manager autofill remains unverified. The browser checks inspected the autofill CSS declaration and exercised typed values, disabled values, placeholders and keyboard focus.
- The 3D auditorium rendered its first frame in Chrome at 1366px. The browser runs used disposable SQLite fixtures and the actual Flask routes and templates.
- The full screenshot set is in `instance/cinewave-visual-qa/`. Run `node tools/test_cinewave_experience_browser.cjs` from the repository root to recreate the matrix with Chrome and the project virtual environment.

| Preview | Light | Dark |
| --- | --- | --- |
| Sign-in at 390px | [Screenshot](../instance/cinewave-visual-qa/390-light-login.png) | [Screenshot](../instance/cinewave-visual-qa/390-dark-login.png) |
| Hype at 1366px | [Screenshot](../instance/cinewave-visual-qa/1366-light-movie.png) | [Screenshot](../instance/cinewave-visual-qa/1366-dark-movie.png) |
| Theatre details at 1366px | [Screenshot](../instance/cinewave-visual-qa/1366-light-theatre.png) | [Screenshot](../instance/cinewave-visual-qa/1366-dark-theatre.png) |
| Screen review form at 390px | [Screenshot](../instance/cinewave-visual-qa/390-light-form.png) | [Screenshot](../instance/cinewave-visual-qa/390-dark-form.png) |
| 3D auditorium at 1366px | [Screenshot](../instance/cinewave-visual-qa/1366-3d-preview.png) | |

## Changed files

| Area | Files |
| --- | --- |
| Theme and accounts | `static/css/coastal.css`, `static/css/auth.css`, `static/css/cinematch.css`, `static/js/cinewave-shell.js`, `templates/base.html`, `templates/auth_base.html`, `templates/login.html`, `templates/register.html`, `templates/verify_email.html`, `templates/reset_password.html` |
| Hype | `cinewave/routes/movies.py`, `static/js/movie-hype.js`, `templates/partials/movie_hype.html`, `templates/index.html`, `templates/movie.html` |
| Reviews and moderation | `cinewave/models/reviews.py`, `cinewave/models/__init__.py`, `cinewave/models/catalog.py`, `cinewave/services/screen_reviews.py`, `cinewave/routes/screen_reviews.py`, `cinewave/routes/__init__.py`, `cinewave/hooks.py`, `templates/screen_review_form.html`, `templates/screen_reviews.html`, `templates/admin_screen_reviews.html`, `templates/partials/screen_review_ui.html`, `templates/partials/cw_admin_header.html` |
| Theatre discovery and booking entry points | `theatre_discovery.py`, `cinewave/routes/booking.py`, `cinewave/routes/profile.py`, `templates/theatres.html`, `templates/theatre_detail.html`, `templates/dashboard.html`, `templates/ticket.html`, `templates/book.html` |
| Migration and deployment documentation | `migrations/versions/20261123_01_screen_reviews.py`, `database_health.py`, `docs/PRODUCTION_DEPLOYMENT_GUIDE.md` |
| Regression tests and browser fixtures | `test_screen_reviews.py`, `test_authentication.py`, `test_database_migration.py`, `test_flow.py`, `tools/run_isolated_python_tests.py`, `tools/cinewave_experience_qa.py`, `tools/test_cinewave_experience_browser.cjs` |
