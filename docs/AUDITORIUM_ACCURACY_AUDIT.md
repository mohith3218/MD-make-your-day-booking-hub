# Auditorium accuracy audit

**Reviewed:** 2026-11-04

## Existing evidence

The repository contains screen-level layout/configuration data, a reference audit at [VIZAG_3D_AUDITORIUM_REFERENCE_AUDIT.md](VIZAG_3D_AUDITORIUM_REFERENCE_AUDIT.md), and saved preview images under `docs/screenshots/3d-auditorium/`. The existing audit distinguishes identified venue references from estimated configurations and records source URLs and confidence for the documented cases.

## Work and verification in this pass

- Preserved the existing Three.js geometry, individual screen layouts, booking seat map and reference profiles.
- Ran the auditorium geometry suite: 9 tests passed.
- Did not claim new photographic verification, screen measurements, browser rendering, mobile rendering or WebGL interaction.

## Remaining work

- Review every currently seeded venue and individual screen against current, attributable interior references.
- Record source date and licensing status consistently; keep unsupported screens explicitly estimated.
- Add browser tests for seat-to-3D synchronization, camera controls, mobile layout and WebGL fallback.
- Produce fresh screenshots from the running app after browser verification.
