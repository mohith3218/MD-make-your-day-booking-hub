# Theatre-Based Movie Discovery Implementation Report

**Project:** MD Make Your Day Booking Hub  
**Date:** 16 November 2026  
**Scope:** Local implementation only. No commit, push, or deployment was made.

## Summary

Implemented an “Explore by Theatre” discovery journey using the project’s existing Flask app, database models, seat layouts, pricing rules, and booking flow. A customer can search for a theatre, open its scheduled movies, filter actual screenings, and continue to the current seat reservation and payment process.

No new database tables or migration were needed. The existing `Theater → Screen → Showtime → Movie` relationships are used to decide which movies and screenings belong to a theatre.

## What changed

- Added a responsive theatre directory at `/theatres`, linked from the site navigation and home page. It supports theatre name, neighbourhood, and address search, plus city and area filters. Cards show the theatre’s location, address when present, screens and formats, and counts derived from upcoming screenings.
- Added theatre schedule pages at `/theatres/<theatre_id>` and movie-specific pages at `/theatres/<theatre_id>/movies/<movie_id>`. They show only movies with upcoming show records tied to one of that theatre’s screens. Film cards use existing poster, language, genre/mood, duration, and certification data where available.
- Added date, language, format, screen, and start-time filters. Show rows include the screen, format, start and estimated end time, current lowest available seat price, remaining-seat count, and an unavailable/sold-out state.
- Added helpful empty and schedule-error states, accessible form labels and status messages, poster fallbacks, and responsive layouts for smaller screens. Theatre cards use a locally styled cinema illustration because the current theatre model has no image field.
- Added a show-selection route that confirms the show belongs to the selected theatre and is upcoming and bookable before redirecting to the existing seat map.
- Added server-side validation of theatre, screen, and movie IDs supplied when entering the existing booking route. The IDs must match the persisted show and its screen. Existing seat reservation, payment, and ticket paths remain in use.
- Reused the existing server-side seat-price calculation. Availability accounts for booked seats and unexpired holds in batched queries, and the displayed price is the least expensive seat still available for that show.
- Interpreted show dates and times in the cinema’s IST time zone for discovery and booking status, avoiding host-UTC differences for Vizag schedules.
- Added regression coverage in `test_theatre_discovery.py`. Updated the existing booking-flow test to check the actual inline VR preview frame ID.

## Main files

- `theatre_discovery.py` — discovery routes, filters, availability, and booking-context checks.
- `templates/theatres.html` and `templates/theatre_detail.html` — directory and schedule UI.
- `templates/theatre_discovery_error.html` — validation and service error states.
- `static/css/theatre-discovery.css` and `static/js/theatre-discovery.js` — responsive styling and progressive enhancement.
- `templates/base.html`, `templates/index.html`, and `templates/book.html` — navigation, home entry, and booking-context integration.
- `app.py` — blueprint registration, shared pricing, IST show status, and booking validation.
- `test_theatre_discovery.py` and `test_flow.py` — feature and booking regression checks.

## Verification

The following checks completed successfully during implementation:

- `python -m unittest test_theatre_discovery` — 23 tests passed. Includes search and filters, theatre/screen/show associations, dates and time zone, sold-out and held seats, server-calculated prices, query batching, invalid IDs, and the booking handoff.
- `test_flow.py` — full existing booking and demo-payment flow passed through ticket generation.
- Regression suites: `test_party` (11), `test_database_migration` (11), `test_demo_payments` (5), and `test_auditorium_geometry` (10) passed.
- Browser and UI checks: 16 rendered route cases and 25 script syntax checks passed; 21 JavaScript tests passed. Theatre directory and detail pages were also opened for local visual inspection.
- Python compilation and `git diff --check` passed.

The current final re-run of the focused tests also passed all 23 tests. The suite logged one intentional database-unavailable case used to verify the graceful error response. The app’s pre-existing SQLAlchemy and `datetime.utcnow()` deprecation warnings remain outside this feature’s scope.

## Data and deployment notes

- No schema change, migration, seed data, or production database change is part of this feature.
- The directory can list a theatre without upcoming shows; its card explains that new screenings will appear when scheduled. A theatre’s films only come from real upcoming show records joined through its screens.
- End times are estimated from the existing movie duration. The price shown is the lowest currently available seat price; seat selection and checkout recalculate and validate against current server data.
- The changes are local to the workspace. They have not been pushed to GitHub or deployed to Render, so the hosted site will not show this feature until the user deploys these changes.
- The workspace already contained deletions under `.tmp.driveupload`; those unrelated files were left untouched.
