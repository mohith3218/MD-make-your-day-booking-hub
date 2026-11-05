# Phase 1: 3D Camera Verification Report

## Status

Phase 1 is **not yet complete**. The Flask app and 3D scene were verified in a real browser, and the selected-seat camera works for the seven requested seats. Screenshot files could not be saved through the available browser workflow, and touchscreen rotation and pinch-to-zoom could not be exercised. See limitations below.

## Environment and startup

- Project dependencies are declared in `requirements.txt`; it includes Flask and Flask-SQLAlchemy. No additional dependency manifest was found.
- Used the existing `.venv` (Python 3.14.6) and installed the pinned-by-range project requirements rather than choosing unrelated latest packages. Verified imports for SQLAlchemy, Flask-SQLAlchemy, and the Flask application.
- Installed versions included Flask 3.1.3, Flask-SQLAlchemy 3.1.1, SQLAlchemy 2.1.8, Flask-Login 0.6.3, requests 2.34.2, qrcode 8.2, and razorpay 2.0.1.
- A SQLite connection check (`SELECT 1`) succeeded. The application was started using the README's `app.py` startup path and an existing seeded test database (`instance/test_flow.db`), with Flask debug mode disabled. The app reported successful startup and no new demo-data rows needed seeding.
- The test database contains demo movies, showtimes, screens, and a test account. The destructive test-flow script was not run because it drops database tables.
- Startup emitted a Python 3.14 deprecation warning for `datetime.utcnow()` in `app.py`, plus Flask's normal development-server notice.

## Routes and rendering

- Logged into the local demo account and loaded the booking page at `/book/2`.
- Confirmed its embedded preview route `/book/2/vr-preview?embed=1` and the standalone route `/book/2/vr-preview` both load.
- Confirmed WebGL 2 is available and the scene renders. No JavaScript errors or WebGL errors appeared in the browser console. The only console warnings were for the Tailwind CDN script being intended for development use.

## Camera and seat checks

Camera positions were compared against the selected seat coordinates and aim direction after transitions settled. All seven selected-seat cameras settled at realistic eye height (1.16 m), aimed at the screen centre, and matched their selected seat:

| Seat | Layout position | Distance to screen | Horizontal angle | Vertical angle |
|---|---|---:|---:|---:|
| G5 | Front centre | 7.0 m | +3.5° | +12.1° |
| D4 | Middle centre | 10.2 m | -4.0° | +5.2° |
| A4 | Rear centre | 13.7 m | -3.0° | +1.6° |
| G1 | Front left | 7.5 m | -22.5° | +11.2° |
| G9 | Front right | 7.5 m | +22.5° | +11.2° |
| A1 | Rear left | 13.9 m | -10.6° | +1.6° |
| A8 | Rear right | 13.9 m | +10.6° | +1.6° |

The seeded auditorium's row lettering places G nearest the screen and A at the rear. Camera position errors after settling were negligible; aim direction had a dot product of 1.0 with the screen-centre direction in the measured cases. The selected seat remained synchronized during drag rotation. Seat transitions were observed; one intermediate sample was taken before a longer rear-right transition had settled, and a follow-up confirmed exact final alignment.

The camera eye is above the seating and floor in all tested positions, with no observed seat or wall clipping in the rendered views. Mouse drag changed camera yaw and pitch while retaining seat A8. Mouse-wheel input changed camera distance. Screen, left, right, stage, and overview presets were exercised. The stage preset faces the screen. Bird's-eye now uses an interior camera below the opaque ceiling; it renders the auditorium, though the embedded framing only shows part of the seating. This auditorium has no balcony rows, so its balcony control falls back to the overview.

## Camera adjustment made

Adjusted overview framing in `templates/vr_seat_preview.html` to back the camera away and fit the auditorium at a practical field of view, with recalculation on resize and a maximum field of view of 72°. Updated field-of-view control synchronization and corrected the auditorium label shown in camera metrics. Moved the bird's-eye camera below the opaque ceiling so it can see into the room. Existing booking behavior was preserved during route and seat-selection checks.

## Desktop and mobile

| Viewport | Result |
|---|---|
| 1920×1080 | Scene and full auditorium overview rendered; screen, seats, side walls, and roof were visible. Overview field of view settled near 62.7°. Mouse drag and wheel zoom responded. |
| 1366×768 | Canvas matched the viewport and overview rendered with the room in view. |
| 390×844 | Canvas matched the portrait viewport and rendered the screen and seats. Field of view reached its 72° cap; side walls are partly outside the portrait framing. Collapsing the map overlay makes the view clearer. |

The mobile viewport was tested, but the in-app browser did not support the touch-event dispatch needed to exercise touchscreen rotation or pinch-to-zoom. Those touch gestures remain unverified. Mouse-based camera dragging did not accidentally change the selected seat.

## Screenshots

Browser screenshots were visually captured during the live checks, including overview and seat/preset views at desktop and mobile sizes. The requested folder `docs/screenshots/phase-1-camera/` was created, but no screenshot files were saved there. The browser explicitly blocked navigating to a data URL for the purpose of saving the captured image and disallowed workaround attempts. As a result, this report does not present screenshot files as evidence and the requested screenshot deliverable remains outstanding.

## Remaining limitations

- Genuine browser screenshots still need to be saved into `docs/screenshots/phase-1-camera/` through an allowed screenshot-saving workflow.
- Touchscreen rotation and pinch-to-zoom remain untested because the browser did not support touch-event dispatch.
- Portrait framing shows less of the side walls, and the bird's-eye embedded view shows only part of the seating.
- Python 3.14 reports the existing `datetime.utcnow()` deprecation warning.

Do not mark Phase 1 complete until the screenshot files are captured and touch interactions are verified or the verification scope is explicitly revised.
