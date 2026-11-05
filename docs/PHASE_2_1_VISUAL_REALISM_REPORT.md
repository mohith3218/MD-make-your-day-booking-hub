# Phase 2.1 — Visual realism and browser verification

Date: 6 November 2026
Repository branch: `main`, local commit `b8774fc` (`<phase 2>`)

## Summary

The reported fully black auditorium was not reproducible in the current local application when opened in Chrome with the seeded showtimes. Three.js r128 created a WebGL context, built the auditorium, and rendered seats, walls, ceiling, screen, and lighting without activating the fallback. The default Showtime preset is very dark, however, and the configured seat fabrics remain difficult to distinguish in overview and seat POV screenshots. This is a real visual limitation and is not described here as fixed.

The browser inspection exposed a separate definite defect: the screen texture's horizontal UV flip was also applied to flat screens, making their text read backwards. The flip now applies only to curved screens. The corrected flat-screen text was confirmed in Chrome.

## Implemented

- Limited the screen UV flip to curved screen geometry in `templates/vr_seat_preview.html`.
- Added `window.cinewavePreviewDiagnostics()` alongside the existing metrics API. It reports Three.js revision, renderer and WebGL state, context loss, canvas dimensions and visibility, scene object counts, camera position and target, fallback state, and the existing renderer metrics.
- Preserved the existing auditorium builder, seat instances, camera calculations, booking flow, and the pre-existing staged `app.py` change.

## Automated-test verified

- `test_auditorium_geometry.py`: **9/9 passed**.
- Rendered the authenticated Sri Melody preview and ran `node --check` on both inline JavaScript blocks: **passed**.
- `py_compile` on the application, layout, theater, payment, and test modules: **passed**.
- `git diff --check` and `git diff --cached --check`: **passed**.
- `test_flow.py` is a standalone script, not a unittest suite. Running it as documented passed checks 1–10, then failed at check 11 in wallet recharge. The test sets `ADMIN_PASSWORD=admin123`, while the already-staged `app.py` change sets a different fixed password in `init_db()`. I left that staged change and the authentication configuration untouched. Checks 11–20 therefore remain unverified.

## Browser verified

Environment: installed desktop Google Chrome 157.0.8103.38, local Flask application using the repository `.venv` and existing seeded SQLite database, authenticated preview routes. No migrations or database initialization were run for browser testing.

- Sri Melody, Main Screen, showtime 43: canvas and WebGL context present, no context loss, fallback inactive, 774 seats registered. Overview, lighting controls, side-wall presets, and row navigation were exercised.
- INOX Varun Beach, Screen 5, showtime 42: screen-specific curved profile rendered, including both side walls, ceiling, screen, and 200 seats. Standard seat E8 and Prime seat A8 selection moved the camera and updated the seat details.
- Jagadamba 70MM, showtime 13: 886-seat auditorium loaded in the real browser; the overview screenshot shows the screen, room architecture, and seat rows. The page did not enter fallback mode.
- Showtime, Preshow, and House On controls all changed the visible lighting. House On reveals substantially more ceiling and wall detail. Seat colors remain too dark to distinguish reliably in the wide view, including under Preshow; this remains open.
- Left- and right-wall presets, front and rear seat navigation, seat selection, and first-person camera transitions were exercised. Screen text is correctly oriented on flat and curved screens after the UV change.
- Responsive canvas dimensions and WebGL diagnostics were confirmed at 1920×1080, 1366×768, and 390×844. The mobile overview rendered. The mobile seat POV was not counted as verified because an earlier capture was taken before the camera transition settled and showed a black canvas.
- Browser console review showed no WebGL shader or runtime exceptions. It showed an unrelated missing-resource 404 and a login-field autocomplete advisory.

## Renderer readings

These are readings from `window.cinewavePreviewMetrics()` in Chrome at Balanced quality. FPS is the API's sampled value, not a benchmark estimate.

| Screen | Viewport | Build time | First usable frame | Sampled FPS | Draw calls | Triangles | Seats | Geometries | Textures |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Sri Melody | 1920×1080 | 177.2 ms | 1,253.8 ms | 15.9 | 57 | 3,039,078 | 774 | 48 | 5 |
| INOX Varun Beach Screen 5 | 1920×1080 | 137.1 ms | 945.8 ms | 11.5 during seat-view interaction | 43 | 788,464 | 200 | 46 | 5 |
| Jagadamba 70MM | 1920×1080 | Not retained reliably | Not retained reliably | Not retained reliably | Not retained reliably | Not retained reliably | **886** | Not retained reliably | Not retained reliably |

The Sri Melody FPS figure was sampled during a Chrome screenshot session; later interactive readings varied. The Jagadamba page rendered, but its metrics were not retained from the browser session, so no performance claim is made for its FPS or build time. A stable same-machine, warmed comparison for all three screens is still needed before judging the 886-seat scene's performance.

## Screenshots

All files below are genuine PNG captures from Chrome's screenshot interface, saved under `docs/screenshots/phase-2.1-visual-polish/`.

- Sri Melody overview: `Sri-Melody-overview.png`
- INOX Varun Beach Screen 5 overview: `INOX-Varun-Beach-Screen-5-overview.png`
- Jagadamba 886-seat overview: `Jagadamba-886-seat-overview.png`
- Standard seat E8: `Standard-seat-close-up.png`
- Premium seat A8: `Premium-seat-close-up.png`
- Recliner seat D4: `Recliner-seat-close-up.png`
- Left and right wall views: `Left-side-wall.png`, `Right-side-wall.png`
- Showtime, Preshow, and House On: `Showtime-lighting.png`, `Preshow-lighting.png`, `House-lights.png`
- Front and rear seat POV: `Front-row-seat-POV.png`, `Rear-row-seat-POV.png`
- Mobile overview: `Mobile-auditorium-preview.png`

The recliner close-up uses the seeded AAA Cinemas Screen 1 showtime because the three requested theaters do not expose a recliner class in the tested screen layouts.

## Not verified / remaining limitations

- The reported fully black desktop scene was not reproduced, so there is no evidence for a failed renderer initialization, missing Three.js bundle, lost context, or instancing failure in this checkout. The verified issue is underexposure in the intentional Showtime preset; the seat-color legibility gap remains open.
- Stable warmed FPS and scene build / usable-frame timings for Jagadamba's 886 seats were not retained. Do not treat the rendered seat count alone as proof of acceptable performance.
- The mobile overview rendered, but mobile seat POV still needs a settled-camera capture and review.
- No physical touchscreen was available. Touch rotation and pinch zoom were not tested on real touch hardware.
- The booking/payment smoke script stopped at check 11 as described above; the full 20-check result is not verified.
- The request specified continuing from the latest GitHub `main`. The local branch is `main` at `b8774fc`, but `git ls-remote` could not resolve `github.com` in this environment, so the remote tip could not be checked.
- Geometry/texture disposal behavior was reviewed in source but not exercised through repeated browser rebuilds or a context-loss test.
