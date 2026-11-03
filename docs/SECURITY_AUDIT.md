# Security audit

**Reviewed:** 2026-11-04

## Findings

- When gateway keys were missing, mock checkout was selected without an environment boundary.
- The TMDb API key had a committed source-code fallback.
- A payment callback verified the Razorpay HMAC but did not retrieve the payment from Razorpay to confirm captured status, order, amount and currency.
- Seat and wallet payment completion needed stronger duplicate-request handling.
- Flask sessions used HTTP-only and SameSite cookies, but production cookie enforcement and response security headers were incomplete.

## Implemented

- Mock order creation, signature acceptance and simulation are restricted to `APP_ENV=development` or `testing`. Production fails closed without live gateway settings.
- Production requests require a stable 32-character secret, PostgreSQL URL, Razorpay key ID/secret and webhook secret. Production sessions use secure cookies and HTTPS Strict-Transport-Security is emitted.
- Razorpay callback signatures are followed by a server-side payment fetch. Confirmation requires the matching order, captured status, INR currency and expected paise amount.
- Webhooks accept only `payment.captured` events with matching order, captured status, currency and amount. Booking state prevents repeat confirmation.
- Added common content-type, framing, referrer and permissions headers; cleared the session before login.
- Removed the hard-coded TMDb key fallback; TMDb access now requires `TMDB_API_KEY`.
- Added a 50 MiB request size limit and ignored `.env` files remain excluded by `.gitignore`.

## Remaining risks and work

- CSRF protection and distributed login/payment rate limiting are not implemented.
- Payment amounts and wallet balances still use floating-point database columns; a migration to integer paise and an idempotent financial ledger is required.
- Razorpay refund execution, webhook event-ID persistence, password reset controls and upload content sniffing require a dedicated review.
- Production validation was not performed against live gateway credentials or a deployed HTTPS/PostgreSQL stack.
- Repository history was not scanned for leaked active credentials; operators should review/rotate any credential previously committed.

This is a code review summary, not a security certification.
