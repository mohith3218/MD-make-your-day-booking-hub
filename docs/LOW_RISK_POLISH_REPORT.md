# Low-risk polish report

Date: 12 November 2026

## Repository and scope

The starting working tree was clean on `main`, commit
`92b76d03f28e1125ba3c3af189dd6ec1fbc9491e` (`after inserting database`).
The GitHub connector confirmed that remote `main` resolved to the same commit.
Shell access to GitHub initially failed DNS resolution; no pull, reset, push or
commit was performed. Changes remain available locally for review.

The implementation plan was to consolidate demonstrably overlapping styles,
polish the shared shell and existing dashboards, refine the current auditorium's
materials and loading state, and address unnecessary preview execution. Existing
booking and geometry tests were run before and after implementation. Work stayed
within templates and small, dependency-free QA tools.

## Files inspected

Relevant portions of these files were inspected:

- `README.md`, `.gitignore`, `requirements.txt`.
- `app.py`: booking notices, dashboard routes, analytics aggregates and access guards.
- `payments.py`: gateway configuration and amount calculations; no edits.
- `templates/base.html`, `dashboard.html`, `admin.html`, `admin_analytics.html`,
  `index.html`, `book.html`, `vr_seat_preview.html`.
- `test_flow.py`, `test_auditorium_geometry.py`, `test_database_migration.py`,
  `test_chair_assets.cjs`, `test_seat_mapping.cjs`, `test_phase_2_1_4_geometry.cjs`.
- Existing QA helpers: `tools/check_phase_2_1_3_templates.py`,
  `phase_2_1_3_qa.py`, `phase_2_1_3_chrome.cjs`,
  `phase_2_1_3_browser_checks.js`, `test_phase_2_1_4_browser.cjs`,
  `test_phase_2_1_4_sync.cjs`.

This was a targeted inspection, not a claim that every repository file was audited.

## Files changed

| File | Change |
| --- | --- |
| `templates/base.html` | Shared styles, responsive navigation, focus and skip link, accessible notices and resilient theme toggle. |
| `templates/dashboard.html` | Clearer introduction and booking empty state. |
| `templates/admin.html` | Shared KPI card styling. |
| `templates/admin_analytics.html` | Readable chart, accurate labels, responsive tables and filters. |
| `templates/index.html` | Lazy loading and asynchronous decoding for movie posters. |
| `templates/vr_seat_preview.html` | Style consolidation, materials, loading state, rendering lifecycle and screen painting cadence. |
| `tools/check_low_risk_ui.py` (new) | Disposable database fixtures, rendered-page checks and optional local QA server. |
| `tools/test_preview_lifecycle.cjs` (new) | Tests of actual preview lifecycle functions and event handlers without a GPU. |
| `docs/LOW_RISK_POLISH_REPORT.md` (new) | This report. |

## Changes and before/after comparison

| Area | Before | After | Classification |
| --- | --- | --- | --- |
| CSS maintenance | Duplicate glass-card rule and superseded preview panel/button declarations. | Consolidated effective declarations; removed unused preview custom properties; narrowed button transitions to affected properties. | Completed |
| Navigation | Fixed-height header could crowd authenticated links on smaller widths. | Header and navigation wrap below 900px; added labelled navigation, visible keyboard focus and a skip link. | Completed; responsive appearance requires manual verification |
| Dashboard consistency | KPI card presentation repeated separately. | Shared radius, tabular numbers, readable labels and wrapping values. | Completed |
| Booking empty state | A single sentence and browse link. | Cinema icon, clear heading, explanatory copy and the existing browse action. | Completed |
| Success/error presentation | Unlabelled flash-message container with compact padding. | Shared notice styling, comfortable spacing, long-message wrapping, light-theme treatment and status semantics. Existing message text and business logic stay intact. | Completed |
| Theme toggle | Storage errors could interrupt toggling. | Applies the theme even when browser storage is blocked; announces current state and next action. | Completed |
| Analytics accuracy | Booking counts labelled as tickets; average booking amount labelled as average ticket. | Labels say Paid bookings and Avg booking. Window explanation reflects existing booking-date filtering and payment-date grouping. No formulas changed. | Completed |
| Revenue chart | Up to 90 narrow bars and tiny, truncated dates; hover-only detail. | Minimum-width daily columns, horizontal scrolling, peak label, clearer bar scale, keyboard/tap/hover details and zero-revenue copy. | Completed; visual and touch checks require manual verification |
| Analytics layout | Period controls and long table content could crowd mobile layouts. | Wrapping filters, local table scrolling, aligned numeric columns and stacked show details on narrow screens. | Completed; responsive appearance requires manual verification |
| Auditorium loading | Canvas could be blank while initialization completed. | Preparing-your-auditorium status clears on the first rendered frame or the existing fallback. | Completed; transition appearance requires manual verification |
| Auditorium materials | Wall finish comparatively metallic; carpet texture lacked an explicit colour encoding. | More matte walls; explicit sRGB carpet and bounded anisotropy; projection artwork bypasses filmic tone mapping. | Completed; visual approval requires manual verification |
| Seat detail | Existing cloth texture supplied only colour detail. | The same small texture adds subtle cloth relief; leather remains smooth. No new image, chair geometry or seat ID. | Completed; visual/performance review requires manual verification |
| Preview pause | Tab visibility could restart a preview paused by its parent booking page. | A separate parent-pause flag blocks restart until an authorized resume message arrives. | Completed; three lifecycle tests pass |
| Screen drawing | Procedural screen painting followed the scene frame rate. | Screen updates capped independently at 12/20/30 per second for Low/Balanced/High; reduced-motion decoration updates at most twice per second. | Completed; real-device performance requires manual verification |
| Poster loading | All poster tags requested normal eager loading. | Four existing poster groups use native lazy loading and asynchronous decoding. | Completed; network savings not measured |
| Optional auditorium variations | Existing screen-specific architecture and three lighting modes. | Preserved. No additional theme selector or alternative geometry added. | Not implemented: optional expansion deferred to keep scope small |
| Asset deletion/compression | Historical screenshots, videos and backups coexist with active assets. | No binary assets removed or recompressed without proof that removal is safe or quality preserved. | Not implemented |

## Tests executed

| Command/check | Result |
| --- | --- |
| `.venv/Scripts/python.exe test_flow.py` | Passed before and after changes: ALL 20 CHECKS PASSED. Includes reservation concurrency, locks, wallet, sandbox gateway signatures, expiry, refunds, analytics, CSV and access guards. |
| `.venv/Scripts/python.exe -m unittest test_auditorium_geometry test_database_migration` | Passed before and after changes: 19 tests. |
| `node --test test_chair_assets.cjs test_seat_mapping.cjs` | Passed before and after changes: 15 tests. |
| `.venv/Scripts/python.exe tools/check_low_risk_ui.py` | Passed: 16 rendered route cases and 25 rendered inline JavaScript blocks checked with `node --check`; covers five auditorium configurations, booking page, dashboard, home, admin and 7/30/90-day/all-time analytics. Includes empty dashboard and zero-revenue cases. |
| `node --test tools/test_preview_lifecycle.cjs` | Passed: 3 tests covering parent pause across visibility changes, duplicate-loop prevention, hidden/detached/destroyed previews and rejection of untrusted messages. |
| Python compilation | Passed for application/payment/geometry/database modules and the new Python QA tool. |
| `git diff --check` | Passed; Git reported only normal LF/CRLF conversion warnings. |

The flow suite deliberately disables SMTP and real gateway keys. Its expected
ticket-email-delivery errors did not fail the suite. Existing Python UTC-time and
SQLAlchemy legacy-API deprecation warnings remain outside this UI-focused scope.
No live charge or real email was sent.

### Browser attempt: partially completed

A dedicated headless Chrome profile, software WebGL and a fresh SQLite QA server
were used. The INOX Screen 5 preview reached its first rendered frame, its 200
seat mappings passed inspection, stereo state toggled, and no uncaught runtime
JavaScript errors were recorded before the lifecycle timing assertion.

The parent-pause portion of that assertion succeeded, but a resumed frame was
not observed within its 400ms wait. The software-rendered session subsequently
became slow enough to stall screenshot and timing work. That result is
**inconclusive**, not a passed browser regression gate. The temporary browser
runner was removed; the focused lifecycle test remains and passes without a GPU.
The test Chrome processes are no longer running. No completed screenshot review,
full multi-auditorium browser pass, mobile verification, headset verification or
hardware performance benchmark is claimed.

## Performance findings

No reliable before/after FPS, GPU-memory, startup-time or network benchmark was
completed. Rendering and asset changes are bounded implementation improvements,
not measured speedup claims. Existing instancing, quality controls, frame-rate
limits and WebGL disposal paths were retained. No real-time shadow maps, extra
lights, high-resolution textures or external dependencies were introduced.

## Deliberately unchanged

Flask backend and routes, database schema, theatre/screen/seat identifiers,
reference profiles, seating layouts, pricing, seat locks and reservation
concurrency, authentication/authorization, booking workflow, the then-existing payment verification,
wallet and refund calculations, analytics calculations, seat selection, camera
controls, seat POV, recliners, VR stereo and existing resource cleanup.

No application Python file, configuration, requirements file or existing data
file was modified. QA fixtures live only in new ignored `instance/low-risk-*`
directories. The optional QA server binds only to localhost and is separate from
the production app; it should be started only for local verification.

## Remaining issues and manual verification

1. Check desktop and 390px-wide navigation, analytics scrolling and chart details
   in both themes; confirm there is no whole-page horizontal overflow.
2. On a hardware-accelerated browser, inspect cloth/leather seats, the floor and
   projection artwork in Showtime, Preshow and House On modes.
3. Verify 2D/3D cart synchronization, front/middle/rear seat POV, recliners, stereo
   entry/exit and cleanup after closing the preview.
4. Switch back to 2D, hide and restore the browser tab, and confirm the inactive
   preview stays paused. Then reopen 3D and confirm it resumes.
5. Review loading/fallback transitions, reduced-motion mode and blocked browser
   storage. Browser timing failure described above remains unresolved pending
   this hardware-assisted check.
6. Benchmark actual laptop/mobile hardware before making performance claims.

Overall classification: **Partially completed verification**. The scoped source
improvements and automated non-browser checks are complete; the remaining visual,
mobile, real-device performance and full WebGL checks require manual verification.
