# Phase 2.1.3 — Seat visibility, materials and synchronization

Report finalized: 9 November 2026. Main browser verification: 7 November 2026; additional Recliner inspection: 9 November 2026.

## Result and scope

The real Flask renderer now displays the existing upholstery colours on every tested seat instance. Standard, Premium and Recliner materials are distinct. Both directions of 2D–3D selection passed trusted Chrome pointer tests, including exact seat IDs, prices, categories, camera targets, deselection, mixed carts and rejection of booked/held seats.

This is a verified desktop demonstration with remaining limitations: the Jagadamba overview and bird's-eye views obscure many seats behind the existing balcony decks, and sampled frame rates vary substantially. Neither complete visual inspection of all 886 chairs from one view nor consistently smooth 30 FPS is claimed. Phase 3 was not started.

The initial local tree was clean on `main` at `648b5a8`. Inspected `templates/vr_seat_preview.html`, `seat_layout.py`, `vizag_theaters.py`, `app.py`, `templates/book.html`, and the existing Phase 1, Phase 2 and Phase 2.1 reports. This work continues that local implementation; it does not claim a comparison with a newer remote commit.

## Implemented fixes

1. **r128 runtime compatibility.** The latest tint code called `THREE.Color.clampRGB()`, which does not exist in the bundled r128. The actual browser entered fallback before building seats. Component clamping now uses `THREE.MathUtils.clamp()`.
2. **Complete instance-colour buffers.** The builder reduced `InstancedMesh.count` before the first `setColorAt()`. r128 sizes the colour array from that reduced count, so later chairs had missing/non-finite colours. GPU-input inspection found valid colours for the first chair and non-finite values for following chairs. Upholstery and aisle-marker colour arrays now allocate at full capacity before their draw counts are reduced. Every tested chair's upholstery colour is checked in the browser.
3. **Explicit seat colour management.** Authored profile colours convert from sRGB to linear once, before the existing linear gains and clamping. Selected, active-view and unavailable palette colours convert once, without the available-upholstery gain. Instance colours remain linear. The fabric map and screen canvas use sRGB encoding, and the renderer outputs sRGB with the existing ACES filmic tone mapping and exposure of 1.2.
4. **Actual category roughness.** The previous live upholstery mesh used one roughness of 0.72, bypassing the separate palette values. Three class-shared materials now apply Standard 0.78, Premium 0.76 and Recliner 0.80. Existing leather/vinyl profiles retain their 0.58 setting. Cushion/back geometry and fabric texture remain shared; there are no per-chair materials.
5. **Non-Premium classification.** The old `/premium/` text match classified Jagadamba's `First Class (Non-Premium)` as Premium. The shared classifier explicitly excludes Non-Premium/NONPREM while preserving real Premium and Recliner classes. The fallback map also respects that exclusion.
6. **Restrained screen bounce.** Actual INOX captures showed the full-strength screen point lights overpowering Showtime. Their existing base intensities now use factors of 0.20, 0.45 and 0.65 for Showtime, Preshow and House lights respectively. Ambient/house presets, wall designs and screen-driven light hues are retained. Available seats were not made emissive.
7. **Read-only mapping checks.** `window.cinewavePreviewSeatMapping(seatId)` now identifies batches, component kinds, instance indices, resolved IDs, transforms, category, price and availability. It detects missing seats, out-of-range references, incorrect reverse IDs, unexpected reverse entries, duplicate references, components shared by different IDs, and repeated IDs in row definitions. Multiple legitimate components belonging to one chair are allowed.

Seat IDs, layouts, prices, booking/payment routes, administrator credentials and Phase 1 camera calculations were preserved. No existing database was deleted or reset.

## Browser environment and evidence

Installed desktop **Chrome 157.0.8103.38**, bundled Three.js **128**, project `.venv` / Python 3.14, and Node **24.22.1**. The browser tests use Chrome DevTools Protocol and built-in Node APIs, with no new dependency. Initial desktop-control activation was unreliable; a dedicated installed Chrome process with an isolated profile provided the actual renderer, trusted pointer input and genuine PNG captures.

`tools/phase_2_1_3_qa.py` starts the actual Flask application on loopback port 5014 using a fresh SQLite backup of the existing database. It does not run `init_db()` or reseed the source. It adds a QA-only user, future showtimes and two unavailable-seat fixtures to that snapshot. QA authentication, capture controls and injected helpers exist only in this separate test process, not the production application.

The shell viewport is **1600 × 900**. The full preview canvas is **1585 × 856**, with effective render pixel ratio approximately **1.0**, at **Balanced** quality for all measurements. Lighting comparisons assert equal camera position, target, quaternion and FOV. Close-ups use QA camera positions to inspect the existing geometry. The synchronization image arranges the actual application iframe and actual 2D map side by side; this temporary QA arrangement is not a production layout change.

## Material and lighting inspection

| Subject | Browser observation |
|---|---|
| Sri Melody | Blue upholstery and blue architectural accents are recognizable. Showtime keeps dark outlines; Preshow and House lights reveal backrests, headrests and row separation. All 774 canonical seat mappings and upholstery colours passed. |
| INOX Varun Beach Screen 5 | Its curved screen and individual wall profile render. Standard/Classic upholstery is charcoal, warmed by the screen light; Prime upholstery is gold. Cushions, larger Premium silhouettes, dark armrests and cup-holder positions are visible in close-ups. All 200 seat mappings and colours passed. |
| Jagadamba 70MM | All 886 seats are registered with matching component IDs and finite correct colours. Premium and Non-Premium now use the proper category batches. Three lighting modes render, without WebGL fallback or context loss. Existing balcony decks significantly obstruct the overview and bird's-eye view. |
| Recliner comparison | The three requested screen layouts have no Recliner class. The existing AAA Cinemas Screen 1 provides a separate 58-seat comparison: green Recliners, wider/deeper cushions, headrests and paired cup-holder positions. Its existing footrest component remains screen-facing. |

The available-upholstery gains remain **2.1 Standard**, **1.45 Premium** and **1.9 Recliner**; they are applied in linear space after conversion, not repeatedly to state colours. The fabric canvas remains one shared 128 × 128 texture. The browser verified encoding values **3001** for fabric and renderer output, tone mapping **4**, and the class-specific live roughness values.

This is a procedural fabric approximation rather than a calibrated physical material. Architecture retains its existing artist-authored material values; this work does not claim a physically calibrated colour migration of every wall, light and decorative texture. Cup holders remain simplified solid geometry from the existing renderer.

## Seat mapping results

The application's canonical IDs are row/number strings, also stored in `BookedSeat.seat_id` and `SeatHold.seat_id`. They are distinct from those tables' numeric primary keys. No IDs were changed to make these checks pass.

Whole-auditorium forward/reverse checks passed for **774 Melody**, **200 INOX**, **886 Jagadamba** and **58 AAA** seats. Detailed diagnostic examples cover the nearest-screen row, middle depth, rear row, extreme left/right positions, Premium and Recliner where present:

| Screen | Representative IDs with valid detailed diagnostics |
|---|---|
| Melody | HH1, R7, A26, GG1, GG26 |
| INOX 5 | L1, F5, A14, J1, J20, A1 |
| Jagadamba | PP1, V16, A24, PP24, A1 |
| AAA 1 | G1, D4, A8, G9, A1 |

Examples of real captured batch/index pairs: Melody HH1 → cushion batch 0 / index 2295; INOX A1 → Premium cushion batch 2 / index 0; Jagadamba PP1 → Standard cushion batch 0 / index 936; AAA D4 → Recliner cushion batch 4 / index 81. Each chair has several legitimate component mappings, all resolving back to that same canonical ID.

The synchronization run additionally passes the actual database-backed fixture IDs **E1** (booked) and **E2** (held) through the diagnostic, confirming `mappingValid: true` and unavailable state. Unknown IDs return `found: false`, `mappingValid: false`, and `missing-seat`. Corrupted/duplicate cases are isolated unit fixtures, never changes to live layouts or booking records.

The diagnostic only reads renderer/layout state. It does not reserve seats, alter availability or call a booking endpoint. Detailed raw mappings and positions are retained in the JSON evidence alongside the screenshots.

## 2D–3D synchronization results

`tools/test_phase_2_1_3_sync.cjs` exercises the real booking page with trusted Chrome mouse events:

- **2D → 3D:** click E8; both carts contain E8, details show Row E / Seat 8 / Classic, and the seat camera target equals E8's computed eye position.
- **Deselect and category change:** click E8 again to remove it, then A8. Both views switch to A8 / Prime / ₹189.
- **Mixed cart:** add E8 alongside A8. The total is ₹324, with exactly two unique IDs.
- **Unavailable seats:** actual disabled 2D clicks and actual 3D canvas hits on E1 and E2 leave the cart unchanged. The test first verifies that the raycast actually hits the intended unavailable fixture.
- **3D → 2D:** a real canvas click resolves through `instanceId` to a canonical seat ID; that exact source 2D button acquires `seat-sel`, both carts agree, and the active details use that ID. The retained run selected K2, producing A8 / E8 / K2 and a total of ₹486.
- **QA surface rearrangement:** after the evidence iframe reloads, the production state bridge restores the same three selected IDs before the side-by-side screenshot.

All six scenario groups passed. No checkout, booking hold or payment was submitted by the browser selection tests. Separate isolated integration tests cover the actual booking/payment writes.

## Performance measurements

These are actual `window.cinewavePreviewMetrics()` readings from the retained main run, at the same browser, computer, viewport and Balanced settings. After an eight-second warm-up, five readings were taken approximately 1.1 seconds apart. FPS below is the arithmetic mean of those five API readings, not a claimed 30/60 FPS benchmark. Build/usable times and render counters come directly from the captured readings.

| Screen | Build ms | Usable ms | Mean sampled FPS | Draw calls | Triangles | Seats | Geometries | Textures |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Sri Melody | 213.3 | 1679.2 | 12.3 | 57 | 3,039,078 | 774 | 48 | 5 |
| INOX Varun Beach 5 | 262.4 | 2137.0 | 22.7 | 56 | 790,852 | 200 | 45 | 5 |
| Jagadamba 70MM | 465.1 | 1489.5 | 19.2 | 66 | 3,492,152 | 886 | 51 | 5 |
| AAA Screen 1 comparison | 306.5 | 1198.7 | 15.9 | 58 | 233,240 | 58 | 45 | 5 |

Melody samples varied from **3.6–20.4 FPS**, INOX from **17.5–26.6**, Jagadamba from **13.6–21.2**, and AAA from **7.8–27.0** in that run. Some earlier attempts captured paused/hidden rendering or an unsettled view; those were rejected and recaptured. Machine load and capture overhead remain limitations. The 886-seat scene rendered and remained usable during this pass, but consistently smooth animation is not established.

The class materials add only fixed shared batches, with class-sized buffers and shared cushion/back geometry. Existing high triangle counts were retained rather than rebuilding the chairs or dropping visual quality. The prior report's different viewport and incomplete Jagadamba measurements are not treated as an apples-to-apples baseline.

## Screenshot paths

All paths below are relative to `docs/screenshots/phase-2.1.3-seat-materials/`. These are new PNG captures from the running application, not generated images or copied Phase 2.1 screenshots.

| Required evidence | File |
|---|---|
| Sri Melody — Showtime | `melody-Showtime.png` |
| Sri Melody — Preshow | `melody-Preshow.png` |
| Sri Melody — House lights | `melody-House-lights.png` |
| INOX — Showtime | `inox-Showtime.png` |
| INOX — Preshow | `inox-Preshow.png` |
| INOX — House lights | `inox-House-lights.png` |
| Jagadamba — Showtime | `jagadamba-Showtime.png` |
| Jagadamba — Preshow | `jagadamba-Preshow.png` |
| Jagadamba — House lights | `jagadamba-House-lights.png` |
| Standard close-up | `Standard-seat-close-up.png` |
| Premium close-up | `Premium-seat-close-up.png` |
| Recliner close-up | `Recliner-seat-close-up.png` |
| Selected-seat highlighting | `Selected-seat-highlighting.png` |
| 2D–3D synchronization | `2D-3D-seat-synchronization.png` |

Additional evidence: `Jagadamba-886-seat-birdseye.png`, three `recliner-*.png` lighting captures, `Recliner-footrest-detail.png`, and `baseline-Melody-Showtime.png`. The lower-angle Recliner image examines the footrest region with the detail/minimap panels hidden for QA, but neighboring chairs still limit isolation of that component. The baseline was captured after the clamp compatibility fix and before the final colour-buffer correction; it documents the dark-seat problem rather than the completed result.

Raw measurements and mapping evidence: `browser-results.json`, `synchronization-results.json`, and `renderer-49.json`. The latter retains the 7 November AAA samples used in the comparison table. `browser-results.json` retains the three main-screen results and the latest additional Recliner run from 9 November; its newer AAA readings are a separate repeat, not a replacement for the table's comparison run.

## Automated regression results

| Check | Result |
|---|---|
| `python -m unittest test_auditorium_geometry.py` | **9/9 passed**, including existing layout/geometry coverage |
| `node --test test_seat_mapping.cjs` | **10/10 passed**, including duplicate/missing/wrong/shared mappings, empty component mappings and Non-Premium classification |
| `python test_flow.py` | **All 20 checks passed**, including layout/seat map, holds, races, wallet, gateway verification, failures, expiry, refunds and analytics |
| Browser material/mapping suite | Four screens passed; every chair's upholstery colour is finite and matches its class/state |
| Browser synchronization suite | **6 scenario groups passed** with real 2D/canvas pointer input |
| `python tools/check_phase_2_1_3_templates.py` | **10 rendered inline JS blocks passed** `node --check` across four previews and booking |
| Python compilation | Passed for application, layout, theatre, payment, test and QA modules |
| Standalone JavaScript syntax | Passed for state helper and browser test scripts |
| `git diff --check` | Passed |

The integration test now uses a unique temporary database instead of dropping the existing `instance/test_flow.db`. Its admin authorization fixture uses a test-client session, avoiding a hard-coded-password mismatch without changing administrator credentials. Existing databases remain untouched. SMTP-not-configured messages in the isolated payment test are expected; live email delivery is not claimed.

## Reproduction

Use the existing `.venv`; no package installation is needed. Start `python tools/phase_2_1_3_qa.py` in a dedicated terminal. Start installed Chrome with a disposable profile under `instance/`, loopback debugging port **9214**, and `http://127.0.0.1:5014/__qa__/`. The test driver fixes the viewport and brings that dedicated browser window to the foreground. Keep the QA browser available during the pass.

Then run `node tools/test_phase_2_1_3_browser.cjs` and `node tools/test_phase_2_1_3_sync.cjs` sequentially. The driver closes only QA tabs on the dedicated debugging port. Use `node --test test_seat_mapping.cjs` for fast pure mapping regressions and `python tools/check_phase_2_1_3_templates.py` for rendered-template syntax checks without a running browser.

## Remaining limitations and milestone boundary

- Jagadamba's existing balcony decks obscure many rows in both overview and bird's-eye captures. Registry/colour checks prove component data is present; they do not prove every chair is visually unobstructed. Geometry/camera redesign was deliberately outside this milestone.
- Frame rates vary and do not establish a consistently smooth 30 FPS. Large scenes retain roughly three million triangles; further performance work needs a controlled benchmark before changing geometry.
- Fabric, cup holders, footrests and architecture remain procedural demonstration geometry. The main Recliner close-up does not isolate every footrest from surrounding chairs; no claim of surveyed real-world dimensions is made.
- Current physical interiors and reference-image reuse permissions remain as qualified in the previous reports. This task did not invent new venue facts or fetch reference photos.
- No real touch hardware, mobile interaction, live payment gateway or real SMTP delivery was verified in this pass.

Core desktop material rendering, mapping and synchronization are browser-verified. The limitations above remain documented Phase 2.1.3 work; they must not be presented as fully solved or silently carried into Phase 3.
