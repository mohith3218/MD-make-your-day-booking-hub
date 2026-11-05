# Phase 1 3D Camera Report

## Status

The latest camera changes are implemented and browser-checked for the viewports and auditoriums listed below. Phase 1 remains incomplete because touch gestures were not testable in this browser session and the browser screenshot API did not provide a permitted way to save image files into the repository. No Phase 2 work has started.

## Implemented

- `applyOverviewFieldOfView()` now uses one responsive target for camera position fitting, final frustum fitting, and the live overview look direction. It updates `desiredLookAtTarget` whenever overview is active.
- `setCameraMode('overview')` recalculates responsive framing before setting the transition target. Returning from a seat POV therefore uses the current viewport's camera and target.
- The resize handler reapplies overview framing and synchronizes its target while overview is active.
- Bird's-eye framing is derived from seat bounds. It places the camera inside the rear of the auditorium, below its ceiling, aims at the seating centre, and computes FOV from the projected seat envelope and current canvas aspect ratio. The FOV remains capped at 72°.
- Bird's-eye framing recalculates on viewport resize. A slight horizontal offset avoids a vertical look-at singularity.
- Booking routes, seat availability, and payment integration were not changed. No booking or payment transaction was submitted.

## Environment and startup

- `requirements.txt` declares Flask and Flask-SQLAlchemy. SQLAlchemy and Flask-SQLAlchemy imports and a SQLite `SELECT 1` connection check were verified in the existing `.venv`.
- Flask started through the README `app.py` path with the pre-seeded `instance/cinewave_flow_qa.db` and debug mode off. Startup succeeded and left the app on its mock payment gateway.
- Startup logs included the existing Python 3.14 `datetime.utcnow()` deprecation warning and Flask's development-server notice.

## Browser-tested

Browser checks used `/book/2`, `/book/15`, and `/book/15/vr-preview` on the local app.

| Viewport | Checks and observations |
|---|---|
| 1920×1080 | Overview and bird's-eye rendered. Screen, room, and seating envelope were visible. |
| 1366×768 | Overview and bird's-eye rendered; the small auditorium's screen, side walls, and seating were visible. |
| 390×844 | Portrait overview and bird's-eye rendered. The embedded booking canvas measured 333×520 in the 58-seat case and the view recalculated after resize. The booking page has horizontal overflow at this width; the camera canvas itself remains within the viewport. |

Two seeded auditorium shapes were exercised:

- AAA Cinemas Screen 1: 7 rows, 58 seats.
- Jagadamba Theatre 70MM Main: 38 rows, 886 available seats. Its bird's-eye view rendered at desktop and mobile sizes; the seating envelope remained inside the camera view. Individual seats are very dark in this auditorium render, which limits visual verification of seat-by-seat gaps.

For the 38-row auditorium, the selected-seat preview opened at Row V, Seat 12 and showed its screen sightline. The displayed distance was 24.3 m, with a 0° horizontal and 0° vertical screen-centre angle. The booking page displayed 886 / 886 seats available. Switching between bird's-eye and overview was exercised in the smaller auditorium. Browser console inspection showed the existing Tailwind CDN production warning and no JavaScript errors.

## Regression checks

- `python -m unittest test_auditorium_geometry.py`: **9 tests passed**.
- `git diff --check`: **passed**.
- `test_flow.py` was not run because it drops and recreates tables in `instance/test_flow.db`; that destructive integration test was not needed for the camera template change.

## Unverified and remaining limits

- One-finger touch rotation, two-finger pinch-to-zoom, and touch drag seat-selection suppression remain unverified. This browser session exposes no touchscreen gesture API; the earlier in-app browser touch dispatch attempt was unsupported. Mouse and seat interaction results from the earlier report do not substitute for touch testing.
- Genuine browser screenshots were captured and visually inspected during this run, but no image files were written to `docs/screenshots/phase-1-camera/`. The supported browser screenshot call returns image bytes for display and offers no file path. A previous browser safety refusal also disallowed saving the same capture through a workaround. The requested folder exists and is empty.
- The large auditorium's dark materials make individual-seat visibility difficult to judge, even though the projected seat envelope is in frame.
- The Python app still emits the existing `datetime.utcnow()` deprecation warning and the normal development-server notice.

Do not mark Phase 1 complete until touch interactions and saved screenshots are verified through an available permitted workflow, or those deliverables are explicitly waived.
