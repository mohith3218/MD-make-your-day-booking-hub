# Security notes: demo-only application

Updated 12 November 2026. No real-money payment integration remains.

- Production requires PostgreSQL and a private SECRET_KEY of at least 32 characters.
  Secure session cookies, HSTS and existing authorization checks remain in place.
- Demo payments are disabled by default in production. Explicitly enable them with
  DEMO_PAYMENTS_ENABLED=true. All checkout methods and wallet credits are virtual.
- Orders and responses are generated locally. Response HMACs use the private app
  secret and bind both order and payment IDs. Unknown external order types, wrong
  owners, invalid amounts/methods and forged responses are rejected.
- The generic compatibility callback accepts only demo fields and stored demo orders.
  No external callback SDK, live verification API or webhook endpoint remains.
- Booking ownership, seat locks, expiry and unique sold-seat constraints are retained.
  Completed-booking callbacks cannot turn an existing success into a failure.
- New demo payment records carry demo=true and settled=false metadata. The existing
  PAID/CAPTURED workflow states do not represent bank settlement. Tickets, QR codes,
  email notices and exported rows identify demo records.
- No database history is rewritten. Existing gateway values remain readable, but
  historical external orders cannot be simulated or newly confirmed.

Existing limitations outside this focused task: CSRF protection and distributed
rate limiting are not implemented; monetary display calculations retain the old
Float columns and rounding; password reset and upload content validation need
separate review. Repository history and untracked binary backups are not rewritten.
No remote deployment, real SMTP delivery or live database test is claimed.
