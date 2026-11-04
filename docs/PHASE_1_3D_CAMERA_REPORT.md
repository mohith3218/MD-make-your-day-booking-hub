# Phase 1: 3D Camera and Seat Viewing Report

Date: 2026-11-04

## Implementation

Updated `templates/vr_seat_preview.html`, preserving the existing renderer, seat IDs, booking messages, and camera presets.

- Retained the existing geometry-derived elevated rear overview and screen/seating frustum fit. It sizes the overview to the room and adapts its field of view to the viewport aspect ratio.
- Set the selected-seat eye point to 1.16 m above the seat origin and 0.24 m forward of the backrest. The camera aims at the configured screen centre, so row, seat, and aisle location affect the view.
- Kept exponential, delta-time-based camera interpolation, wrapped yaw interpolation, and pitch/zoom bounds. A new camera target replaces the current target during an in-flight transition.
- The seat information panel reports the theater and screen identity, row, seat, category, price, distance to screen centre, and signed horizontal and vertical angles. Distance and angles derive from the seat eye point and screen centre. Estimated geometry is labeled as approximate.
- Retained the prior working-tree changes that replace the invented relative audio score with geometry provenance and improve pointer/pinch gesture handling.

## Camera problems identified

- Seat viewpoints needed a more plausible position relative to the seat back while keeping the sightline clear of the adjacent row.
- Measurements needed to state when room and screen dimensions are estimates; the previous relative score was not a measured acoustic value.
- Existing camera framing and controls had already been adjusted in the working tree to use auditorium dimensions, but needed verification against the live renderer.

## Verification

The requested browser verification could not be completed. Starting `run_server.py` reached the application import, then stopped with:

```text
ModuleNotFoundError: No module named 'sqlalchemy'
```

As a result, there was no live booking preview to inspect, no WebGL or browser-console result, no viewport run at 1920×1080, 1366×768, or 390×844, and no new before/after screenshots. No screenshots are claimed as captured. The existing images in `docs/screenshots/3d-auditorium/` predate this verification and are not presented as evidence for this change.

## Requested layout coverage

Small, wide, deep, aisle, balcony, and recliner layouts, including front, middle, rear, left, and right seats, still require a live browser run. Geometry calculations use each auditorium's supplied layout data, but visual behavior across these profiles remains unverified in this environment.

## Remaining limitations

- Install the project dependencies, including SQLAlchemy, in the intended project environment, then launch the Flask app and repeat the requested browser checks.
- Capture overview, screen-centred, side views, front/middle/rear seat views, and mobile screenshots under `docs/screenshots/phase-1-camera/` after the preview can run.
- Room and screen measurements remain estimates whenever the auditorium profile marks geometry as estimated.
