# Phase 2: 3D Auditorium Architecture

Updated 2026-11-05.

## Implemented

- Added per-screen seat, left/right wall, and lighting profile fields to the existing reference-profile schema. Curated details are limited to screen-matched visual references; inferred appearance remains labeled estimated. Third-party images remain reference links only and are not redistributed, downloaded as textures, or fetched by booking requests.
- Extended profile data for Sri Melody, Sarat Theatre, INOX Varun Beach Screen 5, Jagadamba Theatre, AAA Screen 7, and generated screen profiles. Generated profiles explicitly say their finishes are estimates and preserve each saved booking layout.
- The renderer now consumes nested left/right wall styles and material colors while retaining support for older flat profile keys.
- Refined instanced seat construction with dark support legs and optional paired cup holders. These additions use shared instanced meshes rather than one mesh per accessory per seat.
- Fixed couple-seat width being multiplied by seat span twice. Moved recliner footrests to the screen-facing side.
- Wall accent materials now dim and brighten with the existing movie, preshow, and house-light control.
- Booking routes, prices, seat states, seat IDs, seat selection, payment handling, screen geometry, and camera controls were not changed.

## Reference research and confidence

- [Qube's Melody article](https://www.qubecinema.com/node/194), published 2017-12-01, documents stadium-style seating, a baffle wall, and screen/AV specifications. Its linked image shows the exterior, so it is not used as interior evidence.
- Screen-specific visitor images for [Sri Melody](https://x.com/rahool360/status/1946268195947724868) and [INOX Varun Beach Screen 5](https://www.youtube.com/watch?v=Q9NEzBk8vzA), and the [Sarat Theatre auditorium photo](https://assets-in.bmscdn.com/moviesmaster/assets/sttr/sarat-seat1_1761032356359.jpg), inform restrained visual profile values. Their currentness and reuse permissions remain unverified; all remain `review_required` and `approved_for_use: false`.
- The [Jagadamba image](https://x.com/Thyview/status/1452617243959836674) is historical venue-level evidence only. It does not confirm a current finish or a specific screen.
- AAA Screen 7 has operator-published screen dimensions, but no verified interior. Its room finishes and seat appearance remain low-confidence estimates.
- No actual auditorium survey or reliable per-seat physical measurement was available. Procedural seat dimensions, room finishes, wall spacing, and unreferenced screens remain illustrative estimates; they are not claims of exact real-world replication.

## Verification

### Automated checks

- `.venv\Scripts\python.exe -m py_compile vizag_theaters.py app.py seat_layout.py`: passed.
- `.venv\Scripts\python.exe -m unittest test_auditorium_geometry.py`: 9 tests passed.
- `test_flow.py`: all 20 booking, seat hold, payment, refund, and related checks passed using its isolated `instance/test_flow.db` and mock payment gateway. Ticket email delivery emitted expected SMTP-not-configured errors; payment and booking checks still passed.
- `git diff --check`: passed.

### Application and browser checks

- Started Flask through `app.py` using the existing `instance/cinewave_visual_qa.db`; the app seeded/updated its 127 screen profiles and returned HTTP 200 at the home page.
- Signed into the local seeded demo account and opened the actual preview route for INOX Varun Beach Screen 5 (`/book/44/vr-preview`). Browser UI showed 11 rows / 200 seats, 3D canvas content, saved seat map, selected-seat panel, and preview controls.
- Opened Jagadamba Theatre 70MM (`/book/13/vr-preview`). The browser showed 38 rows / 886 seats, its existing lower-balcony seat and seat-to-screen metrics, and the rendered scene. This large page was noticeably slow. Switching to the Sarat route exceeded the browser tool's execution limit, so Sarat and the other requested auditoriums were not browser-verified in this run.
- No booking or payment was submitted. Seat availability and payment integration passed through the separate automated regression test.

## Unverified and remaining limitations

- Browser coverage is partial: only Varun Beach Screen 5 and Jagadamba 70MM were opened in this run. AAA, Sarat, Sri Melody, and a fifth auditorium still require an interactive browser pass. In particular, the performance of the large Jagadamba page limited further route testing.
- No actual touchscreen device or touch-event capable browser session was available. One-finger rotation, pinch zoom, and touch drag seat-selection suppression remain unverified.
- Genuine screenshots were visually inspected in the browser, but the available screenshot method returned display-only image bytes. A prior browser safety refusal specifically disallowed saving those same captures through another route. Therefore no new screenshots have been written to `docs/screenshots/phase-2-auditorium/`; the requested screenshot set remains outstanding.
- This report separates source-backed appearance cues from generated geometry. Exact present-day interiors, dimensions, acoustics, and seat construction remain unverified until surveyed or approved references are supplied.

Phase 2 has implementation progress, but visual verification and screenshot deliverables are incomplete. Do not treat the phase as fully verified until the remaining browser and screenshot work is completed or explicitly waived.
