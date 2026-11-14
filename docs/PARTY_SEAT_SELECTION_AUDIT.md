# Party Code and seat-selection audit — 2026-11-14

Party Code status: **Working in automated workflow tests; interactive browser verification blocked.**

## Scope and findings

Inspected the repository's module/route inventory, booking and payment lifecycle, party models/routes/frontend, saved local screen/party schema, seed and reference profiles, 2D layout engine, Three.js preview, migrations, database configuration/health checks, and existing test/QA tooling before implementation. Unrelated payment, account, and theatre-listing behavior was preserved.

The original feature had a create route and an unauthenticated sync route. Sync trusted JSON names, colors, and arbitrary seat strings; it could update an existing user by name. Membership had no database uniqueness index. Creation committed the party and host separately, without collision recovery. Status/expiry were not enforced; leave/close routes and a code-entry control were absent. Picks were only painted as borders and could overlap. Polling started only for a party code already present at page load, so newly created parties did not continue polling.

The booking page forcibly clicked its 3D button and loaded the iframe at startup. Its separate full-preview iframe could allocate a second renderer. Jagadamba explicitly mapped three pricing sections to three physical floors/decks; the saved local layout confirmed the same three levels.

## Party changes and semantics

- Create, join, sync, leave, and close require authentication, a session CSRF token, and a matching Origin when supplied. The UI obtains the token on the booking page.
- Codes are six hexadecimal characters, validated and normalized server-side. Creation commits the host and party together and retries unique-code collisions up to five times.
- Identity comes from the authenticated user. Repeated joins reuse membership. The migration adds a unique `(party_id, user_id)` index, retaining the newest legacy duplicate for each authenticated identity. Nullable user IDs remain compatible with historical rows; new APIs never create anonymous memberships.
- A database update locks the party before membership/pick operations. SQLite serializes writes; PostgreSQL takes the room row lock. Seat validation uses the existing layout/quantity/blocked-seat checks. Conflicts return HTTP 409 and the conflicting IDs; nonconflicting picks remain selected.
- Parties expire after two hours or once the show ends. Members without a heartbeat for 60 seconds stop appearing and release their picks. Only the host can close; the host leaving also closes the room. Other members can leave and rejoin.
- Joining a code for a different show redirects to that party's actual booking page. Two-second polling starts after creation or joining. The frontend uses text nodes for names, handles errors visibly, serializes in-flight syncs, and forwards friend-seat availability to 3D.
- Picks coordinate **within the party**. They are not showtime-wide reservations. Existing unique SeatHold/BookedSeat constraints remain the final booking authority; another customer outside the room can still book an unheld pick. Checkout revalidates membership, showtime, other members' picks, booked seats, and held seats.
- This uses **HTTP polling, not WebSockets or Socket.IO**. Hidden tabs stop heartbeats; picks can lapse after 60 seconds. Polling is near-live, not instantaneous push delivery.

## 2D/3D behavior

The default is 2D Seat Selection. An explicit 3D request assigns the preview iframe's source for the first time. Switching back hides and pauses 3D and restores the 2D map without replacing the selection Map, booking form, prices, or categories. The same iframe is reused for regular and full preview; the old second iframe was removed. A load/ready event after returning to 2D keeps the viewer paused. Resuming updates viewport dimensions; zero-size viewports do not start a loop. Page teardown releases scene geometry, materials, textures, renderer, and WebGL context once.

Existing seated eye-position calculations, screen-centred directions, camera transitions/presets, gestures, overview framing, lighting, walls, ceilings, floor construction, configurable panel spacing, and per-screen reference handling remain in the renderer. Mode buttons can wrap on narrow screens and the existing responsive 3D sidebar rules remain. Visual and mobile rendering still need a browser check.

## Jagadamba correction and evidence

Only **Jagadamba Theatre / 70MM Main** is corrected. The effective saved-layout reader, normal seed updater, and Alembic data migration all map its existing rows onto two physical levels:

| Existing ticket category | Rows | Seats | Physical level |
| --- | ---: | ---: | --- |
| PREM_UPPER | 12 | 274 | Balcony |
| PREM_LOWER | 12 | 276 | Same continuous balcony |
| NONPREM | 14 | 336 | First Class floor |
| Total | 38 | 886 | Two levels |

The seat count, IDs, row definitions, category names/codes, prices, blocked seats, aisle positions, screen surface/position, and viewing direction are preserved. Both premium sections use one row sequence and one balcony deck/rail configuration; the upper deck is removed from the data rather than merely hidden. Other theatres do not receive this mapping.

The two-level requirement comes from the project owner. Row placement and balcony/floor measurements remain **estimated**, using the existing lower-balcony/floor measurements where present. The [existing TheatresDB reference](https://theatresdb.com/screen/jagadamba-complex-jagadamba/) was opened during this audit; it lists 886 seats and a 77.0 × 32.2 ft screen but explicitly calls its plan illustrative. It does not independently establish the exact two-level row distribution or surveyed room dimensions. Historical venue-photo approval/confidence flags and per-screen visual profiles remain intact. No new real-world seat count or dimension has been invented.

## Actual verification results

Commands use the project's `.venv/Scripts/python.exe`; the generic Windows `python` alias was unavailable. Database suites run in separate processes, as their existing configuration/import design requires.

| Check | Final result |
| --- | --- |
| `python -W ignore test_party.py` | 11 Python tests passed, including 7 child Node tests |
| `python -m unittest test_auditorium_geometry -v` | 10 passed |
| `python -W ignore -m unittest test_database_migration -v` | 11 passed |
| `python -m unittest test_demo_payments -v` | 5 passed |
| `python -W ignore test_flow.py` | All booking/demo-payment workflow checks passed |
| `python -W ignore tools/check_low_risk_ui.py` | 16 rendered route cases and 25 rendered JavaScript blocks passed |
| `node --test tools/test_preview_lifecycle.cjs test_seat_mapping.cjs test_chair_assets.cjs` | 20 passed |
| Python compilation | 32 project Python files compiled |
| `git diff --check` | Passed |
| Existing database preservation | Eight existing database files had identical before/after SHA-256 hashes |

The party suite exercises host creation/association, collision retries/exhaustion, repeated joins, invalid/unknown codes, matching showtime, invalid/duplicate/excess seats, authentication/CSRF/origin checks, identity spoof rejection, member/host permissions, participant snapshots, simultaneous conflicting selections (one 200 and one 409), stale presence, expiry, leaving, closing, and checkout/held/booked-seat conflicts.

The rendered frontend tests execute the actual handlers in a small DOM test surface: lazy iframe creation, repeated mode/full-preview reuse, late-load pausing, shared 2D/3D seat state, totals/categories, quantity/availability restrictions, trusted-message checks, party timer startup, and conflict reconciliation/text-only roster rendering. Lifecycle tests also exercise zero-size guards and idempotent disposal. These are unit tests, not full browser/WebGL tests.

Migration tests upgrade a legacy baseline with duplicate party members and three-level Jagadamba JSON, assert two-level stored data, retain all seat IDs/prices/categories, preserve unrelated screen JSON, compare head schema with ORM metadata, and compile model DDL for PostgreSQL. The migration also ran successfully on a disposable copy of the real local database. No live PostgreSQL migration or concurrency test was performed.

The existing `test_phase_2_1_4_geometry.cjs` also passed its six assertions, but reads **historical checked-in browser output**. This is not evidence that the revised renderer was browser-tested. Older screenshot reports similarly describe their historical revisions only.

Earlier test runs exposed test-harness identity caching, Windows URL escaping, and stdout encoding issues; these were corrected. Final executable checks have no failures. The flow test emits the existing expected SMTP-not-configured messages; booking/payment assertions pass. Email delivery itself was not tested.

## Browser results and remaining work

The Flask QA server started successfully on `127.0.0.1:5017`, using only a disposable snapshot and QA accounts/showtimes. The in-app browser timed out reaching it. Local Windows Chrome inspection was attempted with the computer-use tool; the tool stopped because it could not determine the current browser URL confidently enough to enforce its policy. No browser-controlled booking workflow completed, and no new screenshots were captured. The QA server was then stopped.

Consequently, live mobile/desktop visual layout, GPU rendering/console errors, actual camera animations/gestures, and a two-browser participant UI workflow remain unverified. Automated tests cannot establish these visual results. The standalone `tools/party_seat_qa.py` helper can recreate the isolated server for a later manual check; its QA routes and observations are never imported into the normal application.

Migration `20261114_02` is included and tested but **not applied to the user's existing databases**. Apply the normal reviewed Alembic upgrade to the intended database before production startup; production health now expects this revision. For an existing unversioned database, first verify its baseline schema and establish its Alembic baseline through the existing migration procedure. Do not run initial table creation against a populated, unversioned database. No production database configuration was replaced.

## Files changed

- `app.py`: party routes/security/lifecycle, membership index/relationships, party checkout checks, Jagadamba layout read adapter.
- `templates/book.html`: party controls/polling/roster, 2D default, lazy single-iframe preview and fullscreen reuse, responsive mode controls.
- `templates/vr_seat_preview.html`: resume resize guards, zero-size guard, full/idempotent resource cleanup.
- `vizag_theaters.py`: Jagadamba-only two-level adapter, seed correction, profile truthfulness.
- `migrations/versions/20261114_02_party_and_jagadamba.py`: membership uniqueness and stored Jagadamba correction.
- `database_health.py`: expected migration head.
- `test_party.py`, `tools/test_booking_ui.cjs`: new isolated route and rendered-JavaScript regression coverage.
- `test_auditorium_geometry.py`, `test_database_migration.py`, `tools/test_preview_lifecycle.cjs`: geometry, legacy migration, rendering lifecycle regression coverage.
- `tools/party_seat_qa.py`: disposable local browser QA helper.
- `docs/VIZAG_3D_AUDITORIUM_REFERENCE_AUDIT.md`: current two-level correction and evidence caveat.
- `docs/PARTY_SEAT_SELECTION_AUDIT.md`, `docs/test-results/party-seat-database-preservation.json`: audit and database-preservation result.
