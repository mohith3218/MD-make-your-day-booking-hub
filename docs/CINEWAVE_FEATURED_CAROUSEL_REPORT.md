# CineWave Featured Movies Update

Date: 2026-11-19

## Root cause

The homepage selected one film automatically and rendered its portrait poster in a tall 2:3 frame. Older and newer CSS rules also disagreed about whether the artwork should be hidden or shown on small screens. That left no supported way to choose multiple homepage features and made image sizing vary by breakpoint.

## Changes

- Replaced the single spotlight with a responsive two-column carousel sourced from active `Movie` records. It displays at most five admin-ranked films; before an admin ranks any films, it automatically uses live showings first, then other active and upcoming records.
- Added optional movie backdrop artwork and an ordered feature rank. TMDb imports save the backdrop from the same movie record; manually added movies can provide a backdrop URL.
- Admins set ranks from the movie table or while adding/importing a movie. Moving/removing/archiving a film compacts ranks, and the list remains capped at five.
- The landscape artwork frame uses the matching backdrop with `cover`, the matching poster with `contain`, and a title placeholder when no image is available. The track reserves the tallest slide's dimensions to keep navigation from jumping.
- Added previous/next buttons, accessible indicators, keyboard navigation, touch swiping, reduced-motion handling, and lazy loading for non-first images. There is no autoplay.
- Booking actions point to an actual upcoming show with seats remaining. Without one, the action opens the movie page. Trailer actions use only the movie's stored trailer.
- Added the additive `20261119_01` migration and the SQLite development migration fields. Existing records remain unranked; the live-catalogue fallback populates the hero until admins save an explicit order.
- Implemented the trailer upload helper already called by admin movie forms; this stores randomly named MP4/WebM files under static media and keeps the form's 50 MB limit accurate.

## Verification

Passed:

- `python -m unittest test_featured_movies` — 7 tests.
- `node --test test_featured_carousel.cjs` — 3 tests.
- `python -m unittest test_cinewave_catalog_features` — 5 tests.
- `python -m unittest test_cinewave_layouts` — 6 tests.
- `python -m unittest test_database_migration` — 11 tests.
- `python -m unittest test_theatre_discovery` — 23 tests.
- `python -m unittest test_demo_payments` — 5 tests.
- `python test_flow.py` — booking and demo payment integration checks passed.

The catalog/layout suites must be run in separate Python processes. Loading both modules in one process makes their isolated SQLite fixture paths conflict; each suite passes on its own.

## Browser screenshots

Not captured. Browser automation was unavailable in this session: the built-in computer-use browser tool was not exposed, and the local runtime had no Playwright or Puppeteer package. The requested desktop/mobile screenshot comparison therefore remains unverified; automated rendering, carousel interaction, and booking-flow tests passed.

## Production migration

Review and back up the production database before applying the additive migration. Run `alembic upgrade head` as an operator step, then `python database_health.py`. The expected schema head is `20261119_01`. The update has not been committed, pushed, or deployed.
