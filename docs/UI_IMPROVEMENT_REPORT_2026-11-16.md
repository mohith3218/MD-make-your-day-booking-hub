# MD Make Your Day Booking Hub — improvement report

**Report date:** 16 November 2026 (Asia/Calcutta)  
**Implementation reviewed:** commit `88db33c` (`ui change`)  
**Scope:** the UI redesign requested using two screenshots and their reference HTML, plus integration and regression checks.

The completed work updates the home page, checkout, shared navigation and footer. It connects the new presentation to the existing Flask booking application. It also adds an isolated verification script.

The pasted master improvement prompt describes a much broader project audit. That entire audit has **not** been completed. In particular, this UI change did not implement new 3D geometry, database migrations, Party Code logic or authentication controls. Existing features and older audit reports must not be counted as new work from this change.

## A. Problems discovered

1. **The previous visual design differed from the supplied references.** The existing interface used a dark-and-gold palette and condensed headings; the references used warm cream surfaces, burnt-orange actions and editorial serif headings.
2. **The home-page structure needed changing.** The previous page grouped film releases and mood filters differently. It did not provide the new date-based screening-card layout.
3. **Checkout needed a clearer hierarchy.** The reference grouped concessions and payment choices in the main column, with the movie, seats and itemized bill beside them.
4. **The existing full-flow test contains an outdated iframe assertion.** `test_flow.py:117` expects `id="vr-preview-frame"`. The booking template uses `id="vr-inline-frame"`. Inspection of the parent commit confirms that this mismatch predates the UI change.
5. **Test email delivery is unavailable.** Successful demo payments logged an SMTP configuration error, although the ticket flows being checked completed. Email delivery itself is not verified.
6. **Visual verification could not be completed.** Local browser preview attempts timed out; the available native browser windows did not provide a usable fallback during the attempt.

## B. Improvements implemented and changed files

| File | Implemented change |
|---|---|
| `app.py` | Supplies upcoming screening dates, theatre/show groups, a spotlight movie and database-derived theatre/screen counts to the home page. Excludes shows whose status is no longer upcoming and displays up to five available dates. |
| `templates/base.html` | Replaces the shared header and footer; adds movie search, navigation, wallet access and an account menu; changes typography to EB Garamond with Manrope; defaults to the light presentation while retaining the stored theme preference. |
| `templates/index.html` | Rebuilds the home page with a split hero, date selector, auditorium cards, film grid, category/mood filters, watchlist controls, empty states and platform-experience cards. |
| `templates/checkout.html` | Rebuilds checkout with concession cards, CinePass redemption, payment selection, seat-hold timer, order summary and itemized bill. Connects controls to the existing extras, wallet, gateway, cancellation and split-payment routes. |
| `static/css/coastal.css` | Adds the shared cream/orange design system, responsive layouts, poster/card styling, checkout styling, focus treatment inherited from the shared shell and reduced-motion rules. Harmonizes several existing utility-based pages with the light palette. |
| `static/images/coastal-spotlight.jpg` | Adds the artwork referenced by the supplied HTML as a local asset. The source artwork itself contains a rendered page frame; it is not a newly created film photograph. |
| `tools/check_coastal_ui.py` | Adds checks using a disposable SQLite database for the new pages, booking/payment integration, extras totals, split-payment states, expiry, template compilation and local assets. |

## C. 3D auditorium improvements

**No new camera, geometry, lighting, seat-model or WebGL performance changes were made in this UI work.**

The home page now explains the existing 3D sightline-preview feature and links users toward show selection. Shared light-theme styling also changes the presentation of available, selected and booked seats on the existing 2D map.

The existing render checks returned successful responses for auditorium-preview routes. This verifies template rendering only. It does **not** verify that WebGL rendered correctly, camera angles were accurate, selection synchronized in a browser or mobile performance was acceptable.

## D. Booking and database improvements

The new interface uses existing application records and routes:

- Screening cards link to actual show IDs and show the associated film, screen and remaining-seat count at render time.
- Checkout displays the booking's actual seats, prices, convenience fee, GST, snacks, redeemed points and total.
- Wallet selection is unavailable when the balance is insufficient or demo payments are disabled.
- Full-bill controls are hidden when a Squad Pay contribution is in progress. Extras controls are disabled in that state, matching the existing server-side restriction.
- Changing snacks or point redemption displays an unsaved-extras message. The checkout handler requires applying those changes before continuing through its payment button.
- The timer calculates remaining time from a deadline initialized using the server-supplied hold duration, rather than simply decrementing a counter. Existing server-side expiry checks remain authoritative.
- Expired checkout requests were checked to redirect away from checkout.

These are presentation and integration improvements. **The underlying seat-lock algorithm, pricing rules, payment verification, concurrency controls and migration system were not rewritten.**

No migration files or database models changed. Verification used disposable test databases. This work did not run a production migration or independently audit preservation of every existing user and booking record.

## E. UI improvements

### Home page

- Warm cream background, orange action buttons and serif titles based on the references.
- Spotlight artwork, film metadata and primary booking action.
- Date tabs connected to database-backed screening groups.
- Theatre cards with screen/category information and booking links.
- Poster cards with language, runtime, certificate and watchlist controls.
- Now Showing and Coming Soon categories, including the existing rerelease records.
- Client-side filtering by movie title and mood, plus result counts and an empty-results message.
- Experience cards describing existing Squad Pay, CinePass and 3D-preview capabilities.
- Theatre and screen statistics derived from the database instead of copied reference numbers.

### Checkout

- Two-column desktop layout with concessions/payment choices beside the order and bill.
- Selected-state styling for snacks and payment methods.
- CinePass point selection and a visible extras-update action.
- Squad Pay invite-link copying with a manual-copy fallback.
- A prominent payment action whose label follows the selected method.
- Clear demo-payment wording throughout.

### Shared shell and responsive rules

- Updated brand treatment, navigation, search, account menu and multi-column footer.
- Responsive rules at 1150px, 900px and 650px, plus a large-screen adjustment above 1450px.
- Mobile rules stack the hero and checkout columns, move search onto its own row, reduce film cards to two columns and stack experience cards.
- Existing skip navigation is retained. Controls include labels, selection states and status messages; reduced-motion preferences are respected in the new stylesheet.

**Verification limit:** these responsive rules were implemented but were not visually confirmed at 360, 390, 768, 1024, 1366 or 1920px. Pixel-perfect matching, contrast compliance and complete keyboard usability have not been certified.

## F. Security improvements and boundaries

- Retained Jinja escaping; the new check confirms that a film title containing angle brackets is escaped in the home-page output.
- Retained the application's existing authentication and server-side booking/payment routes.
- Kept payment actions explicitly labelled as simulated; no real payment gateway or credential-collection flow was added.
- Used isolated fixtures for verification instead of modifying the working application's records.

This was **not a comprehensive security audit**. New CSRF protection, rate limiting, authorization hardening, upload validation or session-security changes were not implemented. A passing escaped-title check is not proof that every possible XSS path is safe.

## G. Testing results

The following commands were rerun while preparing this report on 16 November 2026.

| Check | Status | Actual result / evidence |
|---|---|---|
| `.venv/Scripts/python.exe tools/check_coastal_ui.py` | Passed | Exit code 0; eight printed verification groups completed. |
| Empty catalogue and live screening data | Passed | Home page rendered with no movies; fixture dates and booking links appeared; past-date tabs were excluded; an HTML-like movie title was escaped. |
| Reservation and checkout integration | Passed | A real test reservation redirected to checkout; the booking total and Squad Pay option appeared; insufficient-wallet selection was disabled. |
| Snacks and CinePass redemption | Passed | Adding the test popcorn item and redeeming 50 points persisted and changed the booking total by the expected amount. |
| UPI, card and netbanking demo flows | Passed | Each fixture payment completed through the existing simulator, redirected to a ticket and returned a successful ticket-page response. QR decoding was not separately checked. |
| Funded-wallet checkout | Passed | The wallet option became available and the existing wallet route redirected to the ticket. |
| Partial Squad Pay and expiry | Passed | A seeded paid-share state hid the full-bill form and displayed locked-extras messaging; an expired booking redirected away from checkout. This is not a two-browser group-payment test. |
| Local assets and template compilation | Passed | New CSS/artwork endpoints returned HTTP 200; all Jinja templates compiled. |
| `.venv/Scripts/python.exe -m unittest test_demo_payments` | Passed | Five tests passed. These cover demo enablement, signature binding, invalid amounts/methods, simulation/fee rules and the existing production preflight behavior. |
| `.venv/Scripts/python.exe tools/check_low_risk_ui.py` | Passed | Reported 16 rendered route cases and syntax checks for 25 inline JavaScript blocks, including dashboard/analytics empty-state cases. |
| `.venv/Scripts/python.exe -m py_compile app.py tools/check_coastal_ui.py` | Passed | Exit code 0. |
| `git diff --check` | Passed | No whitespace errors reported. |
| `.venv/Scripts/python.exe test_flow.py` | Failed | Stopped at line 117 on the outdated `vr-preview-frame` assertion. The remainder of that suite did not run. |
| Actual browser layout and interactions | Blocked | Preview attempts timed out; no successful visual sign-off was obtained. JavaScript syntax checks do not establish browser interaction correctness. |
| WebGL rendering, camera behavior and performance | Not run | No successful browser-based 3D inspection during this change. |
| Migration/data-preservation and PostgreSQL checks | Not run | Outside the completed UI scope. |

The coastal test logged expected email-delivery errors because SMTP was not configured. It also emitted a `datetime.utcnow()` deprecation warning. Neither caused that check to fail. These results do not establish real email delivery, real payment settlement or production readiness.

## H. Remaining limitations and pending work

1. Complete desktop/mobile visual review and browser interaction checks.
2. Correct the stale full-flow assertion against the intended current iframe contract, then run the entire flow suite. Other failures may be discovered after that assertion is resolved.
3. Perform the wider 3D, migration, concurrency, Party Code, account-security and admin-authorization audit requested in the master prompt if that work is commissioned.
4. Search currently filters **movie titles**. It does not implement theatre or experience search despite the broader placeholder wording.
5. Screening cards show up to four show links per theatre/date card, with film-detail navigation for more showtimes; this is not a complete theatre-specific schedule browser.
6. The reference hero artwork contains a baked-in page frame and may need a cleaner replacement for final presentation.
7. Several templates retain older styling beneath the shared stylesheet. A dedicated visual pass is still needed for every account/admin/booking page.
8. The new home-page queries have not been load-tested or optimized for N+1 access patterns.
9. No new production deployment was performed by the assistant during this work. The implementation is now present in local commit `88db33c`; the current Render deployment state was not checked for this report.

## I. Final project evaluation

| Area | Evidence-based assessment |
|---|---|
| Backend | Home-page data integration changed; relevant booking/payment routes passed the scoped checks. No complete backend audit. |
| Database | Schema and migrations unchanged. Isolated test operations passed; production migration state not assessed. |
| Booking system | Scoped reservation, extras, demo payment, wallet and expiry checks passed. The complete flow suite remains failing at an earlier stale assertion. |
| 3D auditorium | Existing implementation retained. No new realism or performance improvements can be claimed from this change. |
| UI/UX | Reference-inspired home and checkout redesign implemented; actual browser and viewport validation remains incomplete. |
| Security | Existing controls retained; escaped-title and demo-payment checks passed. No broad security assessment. |
| Testing | A dedicated isolated UI/integration checker was added, with passes and failures explicitly recorded. |
| Overall diploma-project quality | This change improves presentation and integrates it with working demo flows. A project-wide readiness judgement requires the remaining visual, 3D, database and reliability verification. |

**Numerical scores are not assigned:** this scoped UI change and its tests do not provide enough evidence to honestly score the entire backend, database, 3D scene, security or overall project out of 10.
