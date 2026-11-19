# CineWave layout and accessibility fix

## Root causes

- The skip link was present in `base.html`, but its CSS only assigned its stacking order, text color, and orange background. It had no off-screen default position, so it appeared as a bar during ordinary browsing.
- `base.html` emitted the full customer header for every endpoint except a hard-coded list of authentication endpoints. Admin, booking, payment, and other focused pages therefore inherited the customer navigation. Authentication pages also depended on CSS to hide parts of that shared header.

## Layout structure

`base.html` now provides the document shell, theme assets, skip link, main landmark, flash messages, and template blocks. Four small layout templates compose the appropriate page chrome:

- `public_base.html`: customer header, search, theme controls, demo notice, and customer footer.
- `admin_base.html`: compact CineWave administration navigation, theme control, site link, sign-out, and a small admin footer.
- `auth_base.html`: centered CineWave brand bar and minimal account form space.
- `booking_base.html`: focused booking header, theme control, demo notice, and booking content.

Header, footer, and theme controls live in reusable partials under `templates/partials/`. `vr_seat_preview.html` remains a standalone immersive page with its own controls and exit links.

## Page assignments

- **Customer navigation:** homepage, movie list and details, CineMatch, theatre discovery, profile, dashboard, and wallet.
- **Admin navigation:** dashboard, analytics, bookings, recharges, movie import and management, theatre and screen management, showtime management, seat layout, and auditorium reference.
- **Minimal authentication:** login, registration, email verification, password recovery, and password reset.
- **Focused booking:** seat selection, checkout, split-pay, demo payment, and ticket pages.

The admin dashboard's repeated section links were reduced to creation shortcuts; the shared admin header owns section navigation. The auditorium reference template now uses a section inside the shell's main landmark, avoiding nested `<main>` elements.

## Accessibility and responsive behavior

The skip link stays in the document and is positioned above the viewport during normal browsing. `:focus-visible` brings it into view for keyboard navigation, and its fragment targets `<main id="main-content" tabindex="-1">`. Regression tests check the link, target, off-screen default, and focus-visible rule. The existing focus indicators, reduced-motion rule, mobile public menu, and theme controller remain in place. Admin navigation uses the same responsive menu controller and theme system.

The new admin and booking headers use the existing warm CineWave theme tokens and responsive breakpoints. The project’s in-app browser could not reach the local preview (`127.0.0.1:5055` timed out, and `host.docker.internal` did not resolve). No desktop, tablet, or mobile screenshots were captured, and actual keyboard focus movement was not browser-verified.

## Files changed

- Shared shell: `templates/base.html`, `templates/public_base.html`, `templates/admin_base.html`, `templates/auth_base.html`, `templates/booking_base.html`.
- Reusable chrome: `templates/partials/cw_public_header.html`, `templates/partials/cw_admin_header.html`, `templates/partials/cw_booking_header.html`, `templates/partials/cw_public_footer.html`, and `templates/partials/theme_menu.html`.
- Page templates: all existing templates that extended `base.html` now extend the appropriate page layout. `templates/admin.html` has one admin navigation and the correct movies anchor; `templates/admin_auditorium_reference.html` avoids a nested main landmark.
- Styling: `static/css/coastal.css`.
- Regression coverage: `test_cinewave_layouts.py`.

## Tests

- `test_cinewave_layouts`: 6 passed. Covers customer, admin, auth, booking, checkout, skip-link markup/styles, and duplicate navigation.
- `test_admin_movie_deletion`: 12 passed.
- `test_theatre_discovery`: 23 passed.
- `test_party`: 11 passed; its embedded JavaScript suite passed 7 checks.
- `test_demo_payments`: 5 passed.
- `test_database_migration`: 11 passed.
- `test_cinewave_catalog_features`: 5 passed.
- `test_authentication`: 13 passed.
- `test_auditorium_geometry`: 10 passed.
- `test_flow.py`: booking and demo-payment flow checks passed, including admin and user page rendering.

Existing SQLAlchemy datetime/query deprecation warnings remain. The flow checks also log expected ticket-email delivery errors because SMTP is not configured in the test environment.

## Remaining limitation

Browser-level screenshots and direct keyboard-focus verification remain unverified because the built-in browser could not connect to the isolated local preview. No deployment, commit, or push was performed.
