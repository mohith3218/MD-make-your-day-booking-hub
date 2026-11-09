# Phase 2.1.4 — Cinema chair geometry

Date: 9 November 2026. This report distinguishes implementation, automated checks and actual Chrome inspection. The models are procedural diploma-demonstration assets, not surveyed replicas of cinema furniture.

## Implementation

Inspected the current renderer, layout engine, theatre profiles, shared materials, mapping diagnostic and previous verification tools. The starting tree was clean. The existing builder was extended; the auditorium architecture, canonical seat coordinates, database IDs, pricing, booking/payment routes and Phase 1 eye-position calculations were retained.

The old model used oval spheres for cushions/headrests, a largely flat extruded back, solid cup-holder cylinders and a footrest that did not respond to the recline controls.

- **Standard:** a shared superellipsoid padding mesh replaces the oval cushion silhouette with a flatter centre and rounded edges. The back extrusion has an ergonomic depth curve and smoothed coincident normals to hide diagonal triangulation seams. Headrests attach to the back instead of floating above it. Rounded arms, twin supports, an under-seat crossbar and seam strips remain individually mapped components.
- **Premium:** wider class proportions, thicker cushions, taller backs and larger headrest padding distinguish the model structurally. Existing class-scaled frames and armrests remain separate from upholstery.
- **Recliner:** back and headrest move together; the footrest raises and extends with the existing controls. The neutral control retains an ergonomic 8° back tilt; the other controls use 25° and 45°. Footrest local Z changes from −0.62 to −0.76 and Y from 0.28 to 0.48. These are illustrative model coordinates, not venue measurements. Non-Recliner backs remain at their normal ergonomic tilt.
- **Couple:** only existing `seatSpan > 1` layouts receive two cushion pans, two back panels and two headrests, with outer shared armrests. Mukta A2 Screen 1 supplies the existing Couple Sofa layout. Both seating positions retain that layout's original booking ID; no two independent database seats are merged.
- **Cup holders:** hollow torus rims replace capped cylinders. The final rim size fits the armrest spacing more closely. These remain simplified rims rather than complete molded cup wells.

Three class-shared upholstery materials and one shared procedural fabric texture are preserved. The Phase 2.1.3 sRGB-to-linear conversion, linear instance colours, sRGB renderer output, available/state palette separation and roughness values are unchanged. Selection temporarily changes instance tint and restores the category tint on deselection; no per-chair material or emissive fabric was added. Lighting was not increased.

## Instancing and identity

Padding uses a shared 16 × 10 sphere-derived geometry instead of 24 × 18. The back extrusion uses fewer bevel/curve segments, with shared smoothed normals. Components use separate transforms within the existing class batches. Armrests, cup rims, legs and seams remain shared instanced batches.

Variable single/couple/Recliner component counts use compact per-class cushion and back cursors. This avoids unwritten identity-matrix slots appearing as extra geometry at the screen origin. The browser regression checks **every drawn instance**, not only registry entries: each must resolve to a real canonical seat ID. The read-only mapping diagnostic continues to include every component.

Whole-screen integrity checks cover INOX **200**, Sri Melody **774**, Jagadamba **886**, AAA Screen 1 **58**, and Mukta A2 Screen 1 **78** IDs. Detailed mapping samples cover front/middle/rear and left/right positions and available categories. Couple component counts and linked Recliner transforms have additional assertions over retained browser output.

## Actual browser work

Installed Chrome 157, local Flask, project `.venv`, and the existing isolated SQLite-snapshot QA launcher were used. Existing databases and administrator credentials were not reset. The launcher adds future showtimes and unavailable-seat fixtures only to its fresh snapshot.

The three required theatres and separate existing Recliner/Couple screens were rendered. Genuine PNG captures are saved under `docs/screenshots/phase-2.1.4-premium-seats/`. The QA helper can settle an existing camera and render a frame for inspection; it does not generate substitute imagery or create a second chair builder.

Reviewed captures show flatter padded cushions, attached headrests, curved backs, hollow cup rims and distinguishable chair categories. Initial close-ups exposed diagonal face shading, which prompted normal smoothing. The main comparison viewport is 1600 × 900 with a 1585 × 856 preview canvas at Balanced quality and approximately 1.0 render pixel ratio. Additional captures exercise 1920 × 1080, 1366 × 768 and 390 × 844.

The portrait capture exposes a framing/control-overlay limitation: the room is not usefully framed in that test. It is retained as evidence, not described as a successful mobile visual result. No real touchscreen was tested.

## Screenshot inventory

All names below are relative to the Phase 2.1.4 screenshot directory.

| Evidence | Files |
|---|---|
| Standard / Premium close-ups | `inox-standard-close.png`, `inox-premium-close.png` |
| Recliner close-up and controls | `recliner-premium-close.png`, `recliner-0.png`, `recliner-1.png`, `recliner-2.png` |
| Existing couple sofa | `Couple-seat-close-up.png` |
| Three theatre overviews | `after-inox-overview.png`, `after-melody-overview.png`, `after-jagadamba-overview.png` |
| Required viewport sizes | `overview-1920.png`, `overview-1366.png`, `overview-390.png` |
| Front / middle / rear POV | `front-seat-POV.png`, `middle-seat-POV.png`, `rear-seat-POV.png` |
| Selection and synchronization | `Selected-seat-highlighting.png`, `2D-3D-seat-synchronization.png` |
| Before comparison | `before-jagadamba-overview.png` |

Additional close-ups for each tested screen are also retained. Earlier Phase 2.1.3 screenshots were not used as Phase 2.1.4 proof.

## Performance evidence

The baseline was captured before geometry changes in this task: Jagadamba build **158.9 ms**, first usable **944.1 ms**, mean of five warmed FPS readings **22.1**, **66** draw calls, **3,492,152** triangles, **51** geometries, **5** textures and **886** seats.

The raw files `before.json` and `after.json` retain measurements. Each normal measurement uses an eight-second warm-up and five API readings roughly 1.1 seconds apart, with the same installed browser, computer, viewport, quality and House lighting. Capture overhead and machine load affect FPS. An intermediate pass returned zero FPS and null usable time because rendering was paused: those values are invalid for a performance comparison and must not be treated as a working benchmark. The final runner rejects such samples and restores the dedicated Chrome window.

Available comparison results and the final verification failure are recorded below. Responsiveness is not inferred solely from a successful route or registry count.

| Jagadamba reading | Before | After compact geometry (inspection frame) |
|---|---:|---:|
| Build time | 158.9 ms | 582.0 ms |
| Time usable | 944.1 ms | Not verified: paused animation |
| Mean warmed FPS | 22.1 | Not verified: zero readings rejected |
| Draw calls | 66 | 68 |
| Triangles | 3,492,152 | 1,370,432 |
| Geometries | 51 | 53 |
| Textures | 5 | 5 |
| Canonical seats | 886 | 886 |

The after draw counters come from a genuine manually settled/rendered inspection frame. They show about **60.8% fewer submitted triangles**, but do not prove improved runtime responsiveness. Build time increased in this capture; the run is not a stable timing comparison. Final benchmark retries failed with `ECONNREFUSED` on the dedicated Chrome port 9214 after interruptions. No usable final FPS or usable-time result is claimed.

**Final verification boundary:** the last cup-rim radius reduction was source/syntax checked after the retained visual pass; Chrome could not be reconnected to visually recheck that small fit adjustment. The screenshot set shows the earlier, wider hollow rims. Earlier real-click tests passed six groups; the latest retry failed before browser connection, and its error output must not be presented as another passing run.

## Regression checks

- Existing auditorium/layout geometry suite: **9/9 passed**.
- Existing seat-mapping suite: **10/10 passed**.
- Booking/payment flow: **all 20 checks passed** in its unique temporary test database.
- Phase 2.1.4 browser-output assertions: **3/3 passed** for all-instance identity, couple component grouping and linked Recliner motion.
- Earlier trusted Chrome pointer tests: **six scenario groups passed**, covering 2D → 3D, 3D → 2D, deselection, category/prices, mixed cart and rejection of booked/held seats.
- Rendered-template JavaScript: **12 inline blocks passed** syntax validation across the five preview fixtures and booking page.
- Python compilation, standalone JavaScript syntax and `git diff --check`: passed.

The final browser-output assertions must be run after generating fresh output with `node tools/test_phase_2_1_4_browser.cjs` and `node tools/test_phase_2_1_4_browser.cjs integrity`. Use `node tools/test_phase_2_1_4_sync.cjs` for real pointer tests, then `node --test test_phase_2_1_4_geometry.cjs`. The QA server and dedicated Chrome debugging port remain the same as the Phase 2.1.3 tooling.

## Remaining limitations

- Mobile portrait framing/control overlays need further work; that viewport is not signed off.
- Existing Jagadamba balcony decks still obscure many rows in the overview. Registry/component checks establish correct instances and IDs, not simultaneous unobstructed visibility of all 886 chairs.
- Footrest translation is deliberately restrained. There is no inverse-kinematic linkage, articulated mechanism or exhaustive collision test against every customized auditorium profile. Neighboring chairs can obscure feet in close-ups.
- These are low-poly demonstration models; fabric, seams and cup holders remain approximations. No exact present-day venue furniture specification is claimed.
- Smooth frame rates and final benchmark acceptance depend on valid warmed measurements, not manually rendered inspection frames. Any paused run is rejected.

Phase 3 was not started. Desktop geometry and selection work has implementation and browser evidence; the mobile, occlusion and collision limitations above remain open rather than being declared solved.
