# Phase 2.1.4 audit — 10 November 2026

Starting tree: clean `main...origin/main`, HEAD `af30945` (`<seat improve 2 >`). Ran `git status -sb`, `git log -1 --oneline` and `git show --stat --oneline HEAD` before editing. Existing renderer, layout engine, venue profiles, state helper, diagnostics and synchronization tools were inspected.

## Pre-edit findings

- Multiple armrests, supports and cup holders lacked unique component names in the public mapping diagnostic. Batch/index mappings already existed and were not assumed to match across batches.
- `refreshAllSeatMaterials()` tinted upholstery and state bands, but did not tint armrests, supports or cup holders on selection.
- Recliner controls rotated geometry inside a nonuniformly scaled chair group. Its local 45° rotation therefore produced approximately 57° in world space.
- Recliner tests asserted transform values/travel, without neighbour or aisle-clearance assertions.
- The backrest extrusion contained 332 triangles per back; cushions, arms and cups also had reducible tessellation.
- Earlier evidence was explicitly headless Chrome. New evidence must use desktop Chrome.
- The existing Couple configuration books each span-2 sofa under one original ID. Splitting its visual cushions into new IDs would violate the data-preservation requirement. Adjacent original bookable IDs must remain independent.

## Additional findings confirmed during rendering

- The desktop QA connector closed the last QA tab before creating its replacement, which could close the desktop browser. Target creation order was corrected.
- Conservative transformed-box tests found overlaps at strongly fanned row ends and in some reclining poses. Chair-centre positions were retained while fan angles, class proportions and hinge travel were corrected.
- Premium's inherited 1.45 compensation washed gold fabric toward pale yellow in House lighting. Compensation was reduced while retaining configured colour strings and all auditorium lighting values.
- A single seam across the two sofa headrests crossed their centre gap. Each existing visual seating position now receives its own seams.

The implementation and current verification results are recorded in `PHASE_2_1_4_PREMIUM_SEAT_REPORT.md`. No database IDs, customer bookings, production credentials or administrator/payment implementation were changed.
