# Phase 2.1.4 — Advanced cinema chairs

10 November 2026. Diploma demonstration; procedural furniture, not surveyed cinema specifications.

## Audit and scope

Started from clean `main...origin/main`, commit `af30945` (`<seat improve 2 >`). Ran the three requested Git audit commands and inspected the renderer, `seat_layout.py`, `vizag_theaters.py`, screen profiles, shared materials, fabric, component batches, mapping diagnostics and 2D–3D logic. The pre-edit findings and later confirmed defects are recorded in [PHASE_2_1_4_AUDIT.md](PHASE_2_1_4_AUDIT.md).

The starting implementation already had rounded padding, category proportions, curved backs, molded cups, separate headrests, fabric colour conversion, state bands, compact instance cursors and camera improvements. Those were retained. This continuation fixes missing component names/highlights, excessive tessellation, nonuniform-scale recline errors, row-end/aisle overlaps, pale Premium compensation and seams crossing the sofa gap.

No production database IDs, booking records, admin credentials, payment code, venue layouts or theatre dimensions were changed. Python layout and profile modules were inspected and tested, not rewritten. Camera controls, presets, seated eye height and auditorium architecture remain. Chair rotations/proportions now fit their existing centres and row pitch. No dependencies were added.

## Implemented geometry

`static/js/cinema-seat-geometry.js` supplies reusable assets to the existing builder. It does not replace the renderer.

| Category | Recognizable geometry |
|---|---|
| Standard | Rounded thick pan, closed ergonomic upholstered back, attached headrest, rounded arms, cup wells, twin legs and supporting crossbar. |
| Premium | Wider pan/arms, thicker padding, taller back, larger headrest and a low-profile lumbar roll. |
| Recliner | Longer pan, separate lumbar/back/head pads, wide arms, cup wells, support frame and raising/extending footrest. |
| Couple | Two distinct pans, back panels and headrests within each existing sofa, outer arms/cups and separate seams for each visual position. |

The new indexed back uses seven shaped cross-sections, tapered shoulders/crown, lumbar curvature and closed caps: **168 triangles versus 332** for the old extrusion. The shared rounded padding uses **168 versus 224** triangles; arms use 100 versus 140; cups use 96 versus 120. Smooth normals and face-based fabric UVs retain rounded shading and avoid texture pinching. These normalized model dimensions are illustrative, not venue measurements.

Row-end chairs previously fanned steeply toward screen centre. Tests found component-box overlaps around those ends. Fan angles are now restrained; Recliners and aisle-edge chairs remain parallel to the aisle. Premium/Recliner class scaling is bounded without moving seat centres, widening aisles or changing bookable positions.

The existing **0°, 25°, 45° controls** remain. The 0° label retains the existing ergonomic 8° neutral lean. Nonuniform group scaling previously made a local 45° back lean approximately 57° in world space. Rotation now compensates that scale; browser matrices measure approximately **8°, 25°, 45°**. Back, headrest, lumbar roll and head seams share the hinge. Restrained forward hinge travel and footrest travel preserve the tested row clearances. This is an illustrative reclining motion, not a simulated mechanical linkage. Existing transform caching is retained.

## Implemented materials and identity

One shared procedural fabric and category-shared rough PBR materials remain. Profile-specific upholstery strings and overrides are preserved. Premium's inherited 1.45 gain was reduced to 0.95 for the fallback gold palette, avoiding the pale yellow compensation seen during inspection; explicit Premium overrides use gain 1. Auditorium lighting/emissive settings were not increased. Upholstery is not made emissive or glossy.

The existing r128 upholstery pipeline still converts authored sRGB tints once, passes linear instance colours, samples the fabric as an sRGB colour texture, and outputs sRGB. Gains reset from the authored colour on rebuild rather than reconverting already-linear values. Existing procedural weave, planar UVs and roughness are retained.

Each seat now stores `componentIndices[componentName] = {batch,index}`. Names such as `cushion-1`, `headrest-1`, `armrest-1`, `armrest-2`, `cup-holder-1` and `footrest-1` are independent of slots in other batches. Couple and class-specific parts use their own compact cursors, including variable seam counts. The read-only diagnostic exposes these names and rejects duplicate names or stale named indices, in addition to the existing forward/reverse checks.

Selection now reversibly highlights armrests, cups and support structures as well as every upholstery component and the existing state bands. Booked/Held colours and exclusions remain. Available category colour is restored exactly after deselection. Geometry/material resources are shared; no per-chair materials or meshes were introduced and no new draw-call batch was added.

**Couple ID constraint:** the existing Mukta layout stores one original bookable ID per span-2 sofa. Its two visual cushions are not two pre-existing database IDs. That data model was preserved. Two original entries, A1 and A2, were selected together and A1 deselected while A2 remained selected in both views. No IDs were merged, split or invented. Independent booking of the two internal cushions would require a separate data/layout change and is not claimed here.

## Automated verification

- **9/9** auditorium/layout geometry tests.
- **11/11** pure seat-mapping regressions, including independent component indices, duplicate names and stale named indices.
- **2/2** reusable mesh tests: bounded triangles, finite vertices/normals/UVs, closed indexed back and outward winding.
- **6/6** assertions over fresh browser output: all drawn mappings, Couple grouping, world-space recline, state/hardware restoration, lighting and clearance.
- **All 20** existing booking/payment checks passed in their temporary database. Missing SMTP is logged; real ticket email and live payments were not tested.
- **12** rendered inline JavaScript blocks passed syntax validation. New/shared JavaScript syntax, Python compilation and `git diff --check` passed.

These are distinct from the live browser checks below. The Node browser-output tests read newly saved observations; an older committed artifact was not treated as a fresh browser run.

## Browser-verified work — built-in Codex browser

At the user's request, final verification used the **built-in Codex browser**, with the real Flask app on `127.0.0.1:5014` and actual WebGL. A dedicated SQLite snapshot supplies test-only future shows, one Booked seat and one Held seat. Production data and credentials are not reset.

The initial desktop Chrome attempt encountered a screenshot timeout; it is not final sign-off. Its raw attempt is retained separately. The desktop connector was also corrected to create a replacement tab before closing the last old QA tab. Final evidence is the new `codex-*.jpg` set and Codex-labelled JSON. Earlier PNGs were retained as prior-phase evidence, not presented as this run's final screenshots.

Main measurements/captures use a controlled 1600 × 900 viewport, Balanced quality and approximately 1.0 renderer pixel ratio. Captures use the full CSS viewport to avoid host-DPI clipping. The temporary viewport override was reset afterward. The live Recliner preview is left open in the Codex browser. Camera/lighting helpers only inspect the existing models in the isolated QA view; they do not build replacement scenes or generated evidence.

All **1,996** original entries across five screens passed component-to-ID integrity checks: INOX 200, Sri Melody 774, Jagadamba 886, AAA 58 and Mukta 78. Detailed diagnostic samples cover front/middle/rear, left/right and available categories. Every drawn component must resolve to a registered original ID and its named index.

**Eight real-input scenario groups passed:** exact 2D → 3D ID/category/price, deselection/category changes, mixed-category total without duplicates, Booked exclusion, Held exclusion, actual canvas click → exact 2D highlight, independent original Couple IDs, and both selection directions on Jagadamba's full 886-seat booking page. Tests used Playwright button clicks and scoped canvas pointer input in the Codex browser. They did not replace selection with a fabricated result.

Neighbour/aisle verification covers **419 poses** across the five screens, including every configured aisle-edge entry, representative row/side/category seats and all three supported poses for the included Recliners. A separating-axis test uses transformed component bounding boxes, including affine shear, with a 0.003 scene-unit tolerance. **No box-overlap or aisle-boundary failures** were reported. This is conservative evidence for those tested poses, not an exhaustive guarantee for every administrator-created layout or a mechanical collision simulation.

## Actual performance

| Screen / browser | Build ms | Usable ms | Mean FPS | Calls | Triangles | Seats | Geometries | Textures |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Jagadamba / desktop before | 740.1 | 5851.5 | 17.9 | 66 | 1358800 | 886 | 52 | 5 |
| inox / Codex final | 679.7 | 7067.6 | 16.8 | 56 | 212868 | 200 | 49–50 | 6 |
| melody / Codex final | 220.9 | 1388.1 | 20.4 | 58 | 766614 | 774 | 48 | 5 |
| jagadamba / Codex final | 297.9 | 1484.8 | 19.7 | 66 | 970056 | 886 | 51 | 5 |
| recliner / Codex final | 60.2 | 861.5 | 21.3 | 58 | 75432 | 58 | 45 | 5 |
| couple / Codex final | 278.1 | 1049.8 | 21.6 | 58 | 108952 | 78 | 45 | 5 |

The requested historical ~3.5 million triangles / 14.8 FPS was rechecked rather than assumed. The actual starting tree already submitted **1,358,800** triangles. The current Jagadamba overview submits **970,056**, a **28.6% reduction** from that measured starting tree, while retaining all 886 entries and 66 draw calls.

The before sample is desktop Chrome; final samples use the user-requested Codex browser. Consequently FPS and startup timings are observations, **not a controlled same-browser A/B speedup claim**. Principal FPS is the mean of five real readings spaced about 1.1 seconds apart after an eight-second warm-up. The first INOX session included resource-count/startup variation, retained in the raw data. No 60 FPS guarantee is made. Actual 886-seat pointer selection was separately verified.

Settled lighting checks use three readings per mode after a four-second settling interval:

| Screen | Showtime mean FPS | Preshow mean FPS | House mean FPS |
|---|---:|---:|---:|
| inox | 22.4 | 20.9 | 21.3 |
| melody | 20.9 | 20.0 | 19.4 |
| jagadamba | 21.3 | 22.0 | 22.2 |

One earlier transition reading was 0.9 FPS. It remains in `transitionLighting`; it was not silently replaced or called a stable result. The settled rerun above distinguishes transition/frame-pacing variation from the later sustained readings. Model visibility was inspected in all nine theatre/mode captures without globally brightening the auditorium.

## Saved screenshots and raw evidence

All paths below are inside `docs/screenshots/phase-2.1.4-premium-seats/`:

| Evidence | Current Codex-browser file |
|---|---|
| Standard chair | `codex-standard-close.jpg` |
| Premium chair | `codex-premium-close.jpg` |
| Recliner at its three controls | `codex-recliner-0.jpg`, `codex-recliner-1.jpg`, `codex-recliner-2.jpg` |
| Couple seating | `codex-couple-close.jpg` |
| Seat POV | `codex-seat-pov.jpg` |
| Selected-chair components | `codex-selected-seat.jpg` |
| Sri Melody overview | `codex-melody-overview.jpg` |
| INOX overview | `codex-inox-overview.jpg` |
| Jagadamba overview | `codex-jagadamba-overview.jpg` |
| Showtime / Preshow / House | `codex-{melody,inox,jagadamba}-{movie,preshow,house}.jpg` |
| Selection on the booking page | `codex-2d-3d-synchronization.jpg` |
| Default-size live preview | `codex-final-preview.jpg` |
| Measured starting-tree comparison | `desktop-baseline-overview.png` (desktop Chrome, before edits) |

`codex-browser-results.json` / `after.json` contain final metrics, component mappings, material restoration, lighting and recliner matrices. `integrity.json`, `clearance.json` and `codex-synchronization-results.json` / `synchronization-results.json` retain the current observed checks. `before.json` is the fresh desktop baseline; `desktop-capture-attempt.json` is a separate non-sign-off attempt. JPEGs are genuine browser captures, not generated images.

## Remaining limits and reproduction

- Furniture is a low-poly demonstration, not measured venue furniture or an engineering recliner mechanism.
- Existing Jagadamba balcony decks still obscure some rows from rear overview. All 886 entries/mappings were checked; simultaneous unobstructed visibility is not claimed. Architecture was preserved.
- Default/narrow browser widths still crowd existing control overlays. Panels can be collapsed; the application UI was not redesigned. No physical touchscreen was tested.
- The 419-pose clearance check has the scope and tolerance stated above. Unseen custom layouts need their own validation.
- Browser/machine load and capture overhead affect frame pacing. The measured main FPS and transition variation are reported explicitly.
- Real SMTP delivery, live payment transactions and production-data mutations were outside this demonstration verification.

Start one snapshot server with `.venv/Scripts/python.exe tools/phase_2_1_3_qa.py`. Final UI work in this run used the Codex browser's local-development/CDP capability; the standalone Chrome runner remains available for separate runs. Regenerate observations before `node --test test_chair_assets.cjs test_seat_mapping.cjs test_phase_2_1_4_geometry.cjs`. Other checks are `.venv/Scripts/python.exe -m unittest test_auditorium_geometry.py`, `.venv/Scripts/python.exe test_flow.py`, `.venv/Scripts/python.exe tools/check_phase_2_1_3_templates.py`, Python compilation, JavaScript syntax checks and `git diff --check`.
