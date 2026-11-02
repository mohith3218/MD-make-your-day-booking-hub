# Vizag 3D auditorium reference audit

Updated 2026-11-03. Photo links are reference-only; they are not downloaded or used as public textures. `review_required` photos remain administrator-only and unapproved.

The seed contains 89 venues and 127 screens across Visakhapatnam city and the wider district. Every screen receives an individual `reference_profile`. Only interior auditorium photographs were considered for visual matching. Exterior, lobby, and ambiguous multiplex-screen images are excluded.

## Screen coverage

| Theatre / screen | Photo evidence | Match status | Confirmed observations | Estimated / unresolved |
|---|---|---|---|---|
| Sri Melody / Main Screen | [Rahul R, 2025-07-18](https://x.com/rahool360/status/1946268195947724868); [CineMinds, 2025-05-01](https://x.com/siddhu_viva/status/1917967279054311734) | Screen-identified; single-screen listing corroborates the mapping | Tiered seating, blue geometric accent lighting, dark side walls, visible speakers; front screen in second view | Room dimensions, ceiling geometry, currentness, and photo permissions |
| Sarat Theatre / Main Screen | [BookMyShow auditorium photo](https://assets-in.bmscdn.com/moviesmaster/assets/sttr/sarat-seat1_1761032356359.jpg) and [venue page](https://in.bookmyshow.com/buytickets/sarat-theater-a-c-4k-dolby-atmos-vizag/cinema-viza-sttr-MT) | Screen-identified; seeded as a single-screen venue and address matches | Purple tiered seats, central aisle, tall patterned side panels, horizontal side light band, dark gridded ceiling | Capture date/currentness, room dimensions, exact screen surface, and photo permission |
| INOX Varun Beach / Screen 5 | [Screen 5 interior thumbnail](https://i.ytimg.com/vi/Q9NEzBk8vzA/hq720.jpg) and [source video](https://www.youtube.com/watch?v=Q9NEzBk8vzA) | Screen-identified; thumbnail visibly labels Vizag Varun INOX Screen 5 | Dark branded seats, tiered rows, horizontal side-wall lighting, paneled ceiling | Video date/currentness, dimensions, and photo permission |
| Jagadamba Theatre / 70MM Main | [Thyview, 2021-10-25](https://x.com/Thyview/status/1452617243959836674) | Venue-level historical photo; screen match unverified | Historical photo shows auditorium, red ribbed upper wall treatment, dark lower panels, classic seats | Present-day finish, balcony visibility/shape, screen match, permissions |
| AAA Cinemas / Screen 7 | No verified interior photo assigned | Estimated model; screen identity and LED dimensions supported by operator | Operator identifies Screen 7 as a 71 × 29.6 ft LED screen ([Asian Cinemas](https://www.linkedin.com/posts/asiancinemas_a-new-aaa-joins-the-asian-cinemas-family-activity-7494655804206411776-dV9k)) | Wall finish, ceiling, upholstery, room proportions; 1.05 m row pitch and 0.25 m risers are model estimates |

Coverage summary: 127 profiles total; 3 have screen-identified interior photos (Sri Melody, Sarat Theatre, and INOX Varun Beach Screen 5); 1 has only historical venue-level imagery with screen match unverified (Jagadamba); 123 are labeled `estimated_model` (including AAA Screen 7); 122 additional profiles have no mapped interior photo. Room dimensions and geometry remain estimated wherever no screen survey or exact layout evidence is published. Other multiplex screens do not inherit these photos.

## Rejected or limited sources

- [Qube's Melody image](https://www.qubecinema.com/sites/default/files/Melody-Cinema---Vizag.jpg) was inspected and rejected because it shows the exterior, not the auditorium. Qube's text remains a technical source only.
- The [INOX Varun Beach lobby image](https://files.yappe.in/place/full/varun-inox-2132582.webp) was excluded because it is a lobby, not an auditorium.
- The [Cinepolis Sreekanya opening image](https://pbs.twimg.com/media/EN4dcLiU4AAlV1T.jpg) shows an interior but does not identify which of the multiplex's screens it depicts, so it was not mapped to an individual screen.
- The [Sarat BookMyShow image](https://assets-in.bmscdn.com/moviesmaster/assets/sttr/sarat-seat1_1761032356359.jpg) was inspected directly; it shows seating and wall/ceiling details but not the projection screen itself.
- The user-supplied `melodycinemas.com` page currently shows unrelated casino content; it was not used as a photo source.
- AAA community first-look photos (for example [this Reddit post](https://www.reddit.com/r/Theatres_vizag/comments/1uiv3u1/some-first-look-photos-of-aaa-cinemas-vizag/)) show interiors but do not establish which exact screen is shown; they were not assigned to Screen 7.
- A separate published source gives AAA's LED as approximately 70 × 30 ft ([ThirdEye](https://thirdeyecinemas.com/aaa-cinemas-vizag-introduces-indias-first-led-projection-q-luxon-screen/)); the profile uses the operator's more specific 71 × 29.6 ft figure.

## Licensing and verification

All third-party photo references use `license: review_required` and `approved_for_use: false`. No copyrighted photo is redistributed as a production asset. Administrators can inspect the references, correct view/screen metadata, update confidence and approval fields, and upload authorized interior photos through the screen reference editor. Uploaded images are stored in the private instance directory and served only through the admin-guarded route.

## Rendering and evidence limits

Seat IDs and per-screen row layouts remain sourced from each saved screen layout. Screen 7's flat LED geometry uses the operator-published dimensions; its steeper row pitch is explicitly estimated. Jagadamba's existing upper/lower balcony divisions remain in the saved layout and are not attributed to the 2021 photograph.

The saved screen seat layouts remain authoritative, and each profile labels whether appearance/geometry is evidenced or estimated. The browser preview rendered with WebGL and no fallback on the checked INOX Varun Beach Screen 1, Screen 5, and Sarat Theatre pages. Camera overview, screen-centered, left/right wall presets, mouse drag, wheel zoom, and rear-row A8 eye-level view were checked; the A8 screen remained visible above the row backs. Mobile viewport (390 × 844) rendered the canvas without fallback and automatically collapsed the seat-details and map bodies while preserving their toggles. Touch drag and pinch were not verified because the in-app browser does not support the needed touch-event command. The desktop browser viewport and touch emulation were restored after the mobile check.

Seat synchronization was checked on the booking page: selecting A1 in the saved 2D booking map updated the parent cart to one seat / ₹320 and highlighted A1 in the embedded 3D minimap. The temporary selection was then cleared; no checkout or payment was submitted. This verifies the map-to-preview direction. Embedded seat picking via the minimap could not be directly clicked in the embedded viewport because that map is visually hidden there, so the reverse direction remains unverified.

Visual evidence is saved under `docs/screenshots/3d-auditorium/`: desktop overview, screen view, left/right wall presets, three seat POVs, Sarat Theatre, Varun Screen 5, and mobile preview. Browser console showed no JavaScript or WebGL errors in the inspected pages. Automated verification: `test_auditorium_geometry.py` (9 passed), Python compilation passed, and `test_flow.py` (all 20 checks passed using a separate isolated SQLite database). Test logs include expected email-delivery-not-configured warnings because SMTP is not configured; booking/payment flow checks passed through the mock test gateway.
