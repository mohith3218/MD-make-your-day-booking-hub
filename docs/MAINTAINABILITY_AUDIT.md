# Maintainability audit

**Reviewed:** 2026-11-04

## Findings

- `app.py` is a large single-file Flask application. Models, route handlers, payment logic, email delivery, seed data and analytics are coupled.
- Payment functions are in `payments.py`; seat layout logic is in `seat_layout.py`. The Three.js preview remains primarily in one template.
- Existing testing is script-based rather than organized as isolated unit and integration suites.

## Implemented

- Added small focused payment helpers for mock-mode policy and server-side Razorpay payment-detail retrieval.
- Added normalized seat-hold persistence while preserving the existing booking/lock interfaces.
- Isolated `test_flow.py` to `instance/test_flow.db`, so the destructive test setup cannot drop a configured local or deployment database.
- Added a simultaneous hold regression check to the flow script.

## Remaining work

- Incrementally extract Blueprints and booking/payment services, preserving route compatibility.
- Introduce Alembic/Flask-Migrate with a reviewed baseline migration before deploying schema changes to production.
- Split the auditorium renderer into maintainable JavaScript modules and add browser/WebGL automation.
- Add structured logging, centralized settings classes, and a maintained dependency lock strategy.

No broad refactor was attempted in this pass.
