# Phase 2.1.4 — Realistic cinema chairs

9 November 2026. Procedural assets for a diploma demonstration, not surveyed replicas of venue furniture.

## Starting tree and preserved work

The clean local tree already contained substantial Phase 2.1.4 work: rounded padding, extruded curved backs, category scaling, cup rims, shared fabric, compact instance batches, a mapping diagnostic and moving Recliner parts. This continuation inspected the renderer, `seat_layout.py`, `vizag_theaters.py`, screen profiles, shared state helper and previous browser tools before editing. Existing problems included pinched fabric on cushion tops, ribbed/diagonal shading, minimal Premium arm differences, rim-only cup holders, opposite back/headrest tilt calculations and a combined Booked/Held state. The previous report also lacked accepted final FPS measurements.

The auditorium builder, architecture, camera presets, seated eye positions, canonical coordinates, aisles, prices, booking data and database IDs are retained. No dependencies were added. QA uses a fresh SQLite snapshot; the original database and credentials are unchanged.

## Geometry and material changes

| Category | Geometry |
|---|---|
| Standard | Rounded padded pan, curved upholstered front/back, attached headrest, rounded arms, molded cup wells, twin legs and under-seat frame. |
| Premium | Existing wider/taller proportions, thicker pan/headrest, more substantial arms, plus a separate upholstered lumbar bolster. |
| Recliner | Extended pan, thick head/lumbar padding, wide arms, cup wells, supporting frame and linked back/headrest/footrest movement. |
| Couple | Two distinct pans, back panels and headrests inside each existing span-2 sofa, with outer arms and cup wells. |

Cup holders now use a shared 10-segment lathed bowl with inner wall, lip, exterior and underside, replacing open torus rims with fewer triangles per holder. Premium/Recliner arms have thicker padding without changing seat centres. Shared 16 × 8 padding offsets the added lumbar pads. Analytic padding/back-face normals remove ribbed highlights and diagonal patches. Face-based padding UVs remove the star-shaped fabric pinching at former sphere poles. The head seam follows the headrest.

The existing 0°, 25°, 45° controls remain. Neutral retains an ergonomic 8° back lean; the other controls use 25° and 45°. Positive local X rotation now moves the back away from the screen, and headrest, lumbar pad, seam and rear state band use the same hinge calculation. At full recline the hinge slides forward by 0.28 local units. Footrest Z changes from −0.36 to −0.46, Y from 0.28 to 0.48, with half-depth 0.18 and a small lifting rotation. These are illustrative coordinates, not venue specifications. Only the active Recliner articulates. Transform caching avoids rewriting every component matrix when cart colours change.

One shared procedural fabric texture is preserved, including during rebuild disposal. A lighter neutral texture base and quieter weave retain more of the configured upholstery colour. Three category-shared PBR materials remain rough fabric, with no emissive upholstery. A trial bump-map pass was removed before final capture to avoid fragment-shader overhead.

Colour pipeline: authored sRGB class/state colours convert once to linear; the canvas colour texture uses sRGB encoding; instance colours are linear; output remains sRGB. Tint resets from the authored string on rebuild, avoiding cumulative conversion. Optional `seat_profile.colors`, `architecture.upholstery_colors` or `visual.upholstery_colors` accept separate `standard`, `premium`, `recliner` values; existing seat/trim colours remain fallback values.

## Booking states and identity

Front/rear instanced bands distinguish gold Selected, jade Active POV, rose Booked and amber Held, with a subdued Available band. Selection adds a small reversible upholstery tint while preserving category fabric. Unavailable upholstery is muted. Flask and parent selection messages now distinguish Booked/Held; the minimap does too. Blocked locations remain non-bookable physical gaps rather than invented chair IDs.

All components, including lumbar pads, cup wells and state bands, retain `instanceId → seatId` mappings. The read-only diagnostic reports original ID, row, number, category, component batch/index, resolved ID and component position. Whole-screen checks inspect every registered seat and every drawn instance: INOX 200, Sri Melody 774, Jagadamba 886, AAA Screen 1 58 and Mukta A2 Screen 1 78. Detailed samples include front/middle/rear, left/right, Premium and Recliner wherever present.

**Couple data semantics:** the existing Mukta layout stores each span-2 sofa under one original booking ID. Two visual cushions are not two existing database IDs. That model is preserved. Two adjacent original sofa IDs remain independently selectable/deselectable; no IDs were merged, split or invented.

The Chrome pointer suite checks exact 2D → 3D IDs/details/category/price/camera, deselection, mixed-category cart totals, rejection of Booked/Held seats on both surfaces, canvas raycast → exact 2D highlight, independent selection of two original Couple IDs, and both directions on the full Jagadamba 886-seat page. Raw evidence is `synchronization-results.json`.

## Actual browser evidence

Installed Chrome 157 runs with a dedicated **headless Chrome** profile, DevTools protocol, localhost Flask and actual WebGL. PNGs are browser screenshots of the existing application renderer, not generated images. QA helpers settle its camera and use its lighting/selection functions; they do not create substitute chairs. Principal viewport: 1600 × 900, Balanced quality, render pixel ratio 1. Additional captures use 1920 × 1080, 1366 × 768 and 390 × 844.

All paths below are inside `docs/screenshots/phase-2.1.4-premium-seats/`:

| Evidence | Actual screenshot(s) |
|---|---|
| Standard front / side | `Standard-seat-front-view.png`, `Standard-seat-side-view.png` |
| Premium | `inox-premium-close.png` |
| Recliner / controls | `recliner-0.png`, `recliner-1.png`, `recliner-2.png` |
| Couple | `Couple-seat-close-up.png` |
| Fabric detail | `Seat-material-details.png` |
| Selection | `Selected-seat-highlighting.png` |
| Required theatre overviews | `after-melody-overview.png`, `after-inox-overview.png`, `after-jagadamba-overview.png` |
| All three lighting modes | `{melody,inox,jagadamba}-{movie,preshow,house}-overview.png` |
| Front / middle / rear POV | `front-seat-POV.png`, `middle-seat-POV.png`, `rear-seat-POV.png` |
| Shared 2D/3D selection | `2D-3D-seat-synchronization.png` |
| Starting-tree comparison | `before-jagadamba-overview.png` |

`movie` is the application's Showtime mode. Records include capture timestamp and browser identity. Older Phase 2.1.3 screenshots are not used as current proof.

## Performance

| Screen / pass | Build ms | Usable ms | Mean FPS | Calls | Triangles | Seats | Geometries | Textures |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Jagadamba before | 271.9 | 1421.9 | 24.6 | 66 | 1,370,272 | 886 | 51 | 5 |
| inox final | 112.3 | 988 | 24.6 | 56 | 297,252 | 200 | 45 | 5 |
| melody final | 198.8 | 1164.9 | 21.3 | 58 | 1,079,310 | 774 | 48 | 5 |
| jagadamba final | 237.5 | 1318.9 | 22.8 | 66 | 1,358,800 | 886 | 51 | 5 |
| recliner final | 160.2 | 884 | 20.2 | 58 | 103,344 | 58 | 45 | 5 |
| couple final | 80.8 | 741.1 | 22.1 | 58 | 150,040 | 78 | 45 | 5 |

Jagadamba final mean FPS was 22.8 versus 24.6 in the starting-tree capture (-7.4%). This measured decrease is recorded rather than claimed as an improvement. Machine load and headless rendering affect the comparison; smooth 60 FPS is not claimed. Build/usable times improved in this capture; draw calls, geometry count and texture count stayed constant, with slightly fewer submitted triangles. The actual 886-seat booking page also passed trusted pointer selection in both directions.

`before.json` measures the actual starting tree of this continuation; `after.json` records final `window.cinewavePreviewMetrics()` readings. Each principal measurement has an eight-second warm-up and five readings about 1.1 seconds apart. FPS is their mean. Lighting records require positive FPS and usable time. Zero-FPS/paused runs are rejected. Scene triangles include auditorium architecture. State bands share the existing seam batch, adding no draw call; no per-seat materials/meshes are introduced. These machine-specific results are not a 60 FPS guarantee.

## Regression checks

- Auditorium/layout geometry: **9/9 passed**.
- Pure seat-mapping tests: **10/10 passed**.
- Isolated booking/payment flow: **all 20 checks passed**.
- Fresh browser-output assertions: **5/5 passed** (all drawn mappings, Couple grouping, Recliner motion, state colours/restoration, three lighting modes).
- Trusted Chrome pointer input: **8 scenario groups passed**, including independent Couple IDs and Jagadamba 886-seat selection in both directions.
- Rendered-template JavaScript: **12 inline blocks passed** across five previews and the booking page.
- Python compilation, standalone JavaScript syntax, and `git diff --check`: **passed**.

The new Booked/Held colour assertion initially failed because a stale QA worker served the old Python payload. Duplicate QA workers were stopped and one fresh snapshot server started before final verification. The failed run is not counted as a pass. Inspection also prompted fabric-UV, normal, attached-seam and Recliner camera-framing fixes.

## Remaining limitations

- These are low-poly demonstration models; upholstery, cups, seams and supporting mechanisms are approximations.
- Existing Jagadamba balcony decks obscure some rows from rear overview. All 886 entries/components are verified; simultaneous unobstructed visibility is not claimed. Architecture was preserved.
- Hinge/footrest travel is restrained to the existing seating envelope. No exhaustive mesh collision proof for every custom layout or aisle is claimed.
- Existing mobile portrait framing and control-overlay crowding remain; no physical touchscreen was tested.
- Real SMTP delivery and live payment transactions were not exercised. The isolated payment test uses its mock gateway; missing SMTP is logged while booking remains confirmed.
- Frame rate depends on GPU/driver and load. Successful mappings and still screenshots alone do not establish responsiveness.

## Reproduction

Start one isolated QA server with `.venv/Scripts/python.exe tools/phase_2_1_3_qa.py` and installed Chrome with a dedicated profile and debug port 9214 (Flask port 5014). Run `node tools/test_phase_2_1_4_browser.cjs`, then `node tools/test_phase_2_1_4_browser.cjs integrity`, `node tools/test_phase_2_1_4_sync.cjs`, and `node --test test_phase_2_1_4_geometry.cjs`. Other checks: `node --test test_seat_mapping.cjs`, `.venv/Scripts/python.exe -m unittest test_auditorium_geometry.py`, `.venv/Scripts/python.exe test_flow.py`, and `.venv/Scripts/python.exe tools/check_phase_2_1_3_templates.py`.
