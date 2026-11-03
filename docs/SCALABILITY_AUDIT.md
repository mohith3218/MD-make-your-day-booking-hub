# Scalability audit

**Reviewed:** 2026-11-04

## Findings

- `app.py` contains models, routes, business rules, initialization and reporting in one module. This increases change risk and makes ownership boundaries unclear.
- SQLite is the default local database. The application has no connection pool tuning beyond SQLAlchemy's pool pre-ping, no background worker, and no load-test results.
- Seat availability was derived from comma-separated seat-lock rows, making concurrent check-then-insert requests unsafe.
- Booking history, pending booking, hold expiry and payment order lookups needed indexes.

## Implemented

- Added normalized `SeatHold` rows with a unique `(showtime_id, seat_id)` constraint. A simultaneous request test confirms only one customer can hold a contested seat.
- Kept legacy `SeatLock` records for booking-level expiry and compatibility; active legacy locks are copied to per-seat rows at initialization.
- Added indexes for booking history/status, booking by showtime/status, lock expiry and payment order ID.
- Added a conditional pending-to-processing database update before payment finalization. Wallet submissions are claimed before debit, preventing duplicate wallet charges from parallel submissions.
- Added expired-hold indexes and cleanup for the normalized rows.

## Remaining work

- Replace request-time cleanup and monolithic route logic with a scheduled worker and booking service module.
- Add shared cache only for public catalogue data; seat and payment state must remain database-authoritative.
- Establish PostgreSQL migrations and run repeatable throughput/load tests against the intended deployment size.
- `SeatLock.seats` remains as a compatibility field. It is no longer the source of truth for availability.

No production-scale capacity claim is made from the local SQLite concurrency test.
