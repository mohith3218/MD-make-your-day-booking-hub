# CineWave — what was added

Two features, wired into your existing Flask app: **real theatre seating** and a **full payment flow**.
Everything is Vizag-only (Visakhapatnam theatres seeded on first run).

## 1. Run it

```bash
pip install -r requirements.txt
python app.py           # http://127.0.0.1:5000
```

On a fresh local database, set `ADMIN_PASSWORD` before first startup to create the admin account. Passwords are never printed and existing credentials are preserved. Set `SECRET_KEY` to a long random value to keep sessions valid across restarts. For an HTTPS deployment, also set `SESSION_COOKIE_SECURE=1`. Flask debug mode is off by default; set `FLASK_DEBUG=1` only for local development.
Your old `vizag_movies.db` keeps working — `auto_migrate()` adds the new columns on startup.
Keep the original database and its backups. For Supabase PostgreSQL configuration, versioned schema migrations and safe data transfer, see [the Supabase setup guide](docs/SUPABASE_SETUP.md) and [migration verification report](docs/SUPABASE_DATABASE_MIGRATION_REPORT.md).

### Email verification and ticket delivery

Current demo registration creates accounts immediately; the existing verification
helpers are retained. Confirmed demo bookings generate an on-screen ticket and QR
marked DEMO. Optional email delivery failure never undoes the booking.

Configure SMTP only if ticket email delivery is needed. Copy `.env.example` to
`.env`, then fill in the real settings for your mail provider. The app loads this
file at startup; restart the server after editing it. For Gmail, use a Google
App Password rather than your normal account password. Keep `.env` private and
never commit it:

```powershell
Copy-Item .env.example .env
notepad .env
```

Use port `587` with `SMTP_USE_SSL=0` for STARTTLS, or an implicit TLS port such as
`465` with `SMTP_USE_SSL=1`. Existing accounts are preserved during database migration. The current demo
registration route creates accounts immediately without sending an OTP.

Verify everything at once:

```bash
python test_flow.py     # isolated booking, demo payment, wallet, split, refund and analytics checks
```

## 2. Files

| File | What it is |
|---|---|
| `app.py` | Your app, extended (models + all routes) |
| `seat_layout.py` | Seat layout engine — turns layout JSON into a seat grid |
| `vizag_theaters.py` | 8 real Vizag theatres, 22 screens, ~4,995 seats |
| `payments.py` | Local demo simulator, fee/GST math, private response signatures |
| `test_flow.py` | End-to-end test of the whole booking + payment flow |
| `templates/base.html` | Shared shell (header, wallet balance, flash messages) |
| `templates/book.html` | New seat map |
| `templates/checkout.html`, `pay_mock.html`, `ticket.html` | Payment flow + e-ticket |
| `templates/wallet.html`, `admin_recharges.html`, `admin_bookings.html` | Wallet & admin |
| `templates/screens.html`, `add_screen.html`, `edit_layout.html` | Seating arrangement admin |
| `app_original_backup.py` | Your original file, untouched, just in case |

New templates extend `base.html`, so the header/nav lives in one place now.

## 3. Real theatre seating

`Theater → Screen → layout JSON`. A screen is one audi and it owns its own seating,
so INOX Varun Beach Screen 1 and Jagadamba 70MM look nothing alike — which is the point.

```json
{
  "screen_label": "Screen 1 - INSIGNIA",
  "classes": [
    {"code": "RECLINER", "name": "Recliner", "price": 350,
     "rows": [{"label": "A", "count": 12, "aisles_after": [6], "blocked": ["A7"]},
              {"label": "B", "count": 13, "aisles_after": [6]}]},
    {"code": "PRIME", "name": "Prime", "price": 220,
     "rows": [{"label": "C", "count": 16, "aisles_after": [4, 12]}]}
  ]
}
```

| Row key | Meaning |
|---|---|
| `label` | Row letter shown on both sides ("A", "AA") |
| `count` | Seats in that row — rows can differ, that's how real halls are |
| `aisles_after` | Walkway after these seat numbers |
| `blocked` | Seats that don't physically exist (`["A7"]`) |
| `offset` | Shift a short row to centre it |
| `seat_span` | `2` for couple/sofa seats (drawn double width) |

Edit any of it at **Admin → Theatres & Screens → Edit layout**, with a live preview of
exactly what customers see. Prices are per class, and each showtime can override them
(weekend/premiere pricing) from **Add Showtime**.

Seeded cinemas: **23 Vizag theatres, 53 screens, 15,149 seats.**

| Cinema | Area | Screens |
|---|---|---|
| AAA Cinemas | Inorbit Mall, Madhurawada | 8 (1,552 seats) |
| INOX Varun Beach | Beach Road | 6 (incl. the 37-recliner INSIGNIA audi) |
| INOX CMR Central | Maddilapalem | 4 |
| INOX CMR Central | Gajuwaka | 3 |
| INOX Chitralaya Mall | Suryabagh | 3 |
| Cinepolis Sreekanya Cineglitz | Madhurawada | 4 |
| Mukta A2 Cinemas | Town Main Road | 3 (recliners + couple sofas only) |
| STBL Cine World | Madhurawada | 3 |
| STBL Cinemas Multiplex | Sheela Nagar | 2 |
| Miraj Cinemas, Bhupathi Surya Central | Dwaraka Nagar | 3 |
| Kameswari & Kinnera | Maddilapalem | 2 |
| Jagadamba Theatre 70MM | Jagadamba Junction | 1 (886 seats) |
| Sri Melody | Suryabagh | 1 (774 seats) |
| Sarat · Sangam · Sree Rama · Sree Kanya · Leelamahal · Mohini · Annapurna · Natraj · Sri Lakshmi Narasimha · SVC Likitha | across the city | 1 each |

**AAA Cinemas** (Allu Arjun x Asian Cinemas, opened 9 Aug 2026 at Inorbit Mall) is seeded
with its published per-screen capacities — Screen 1 VIP 58, Screen 2 76, Screen 3 130,
Screen 4 130, Screen 5 436 (the 57 ft one), Screen 6 197, Screen 7 Q-Luxon LED 491,
Screen 8 Lounge 34 — and its real pricing, ₹177 Platinum / ₹295 Recliner.

Sources for names, localities, screen counts and seat data:
[Vizag cinema list with addresses](https://in.bookmyshow.com/vizag-visakhapatnam/cinemas),
[AAA Cinemas 8 screens / 1,556 seats](https://www.m9.news/movienews/aaa-cinemas-vizag-allu-arjun-raaka-update/),
[AAA per-screen seat counts](https://www.gulte.com/shorts/424741/70x30-led-screen-biggest-in-aaa-vizag),
[AAA screen roles and tech](https://www.ntvenglish.com/movie-news/allu-arjun-aaa-cinemas-visakhapatnam-barcosp4k-dolby-atmos-quluxon.html),
[AAA ticket prices](https://www.yovizag.com/allu-arjun-inaugurates-aaa-cinemas-at-inorbit-mall-in-vizag/amp/),
[INOX Varun Beach launch](https://businessofcinema.com/bollywood-news/inox-leisure-launches-multiplex-in-vizag/),
[Jagadamba / Melody capacities](https://vizagsmartcityin.blogspot.com/2026/06/best-movie-theatres-in-visakhapatnam.html).

Published capacities are matched where they exist; row-by-row detail is a reconstruction,
so fine-tune each row in the layout editor until it matches the hall seat-for-seat.
If you're on an older database, the seeder renames the four theatres that changed names
instead of duplicating them, and adds the 15 new cinemas on next startup — or hit
**Admin → Reseed Vizag theatres**.

### Auditorium photo references

Each researched screen can store a `reference_profile` alongside its static layout: interior-photo URLs, view direction, screen-match and approval state, visible architecture, and confidence. This metadata is separate from bookings and live seat availability. The customer preview receives only visual parameters; it does not fetch reference photos.

Open **Admin → Theatres & Screens → Edit layout → Photo reference & 3D comparison** to compare reference interiors with the screen's interactive preview, edit the profile, mark a match/permission review, or upload an authorized auditorium photo. Uploaded references stay in the private instance folder and require administrator review. Reference images are not production textures.

The initial Visakhapatnam profiles include an identified Main Screen reference for Sri Melody (the venue is documented as single-screen), a historical venue-level reference for Jagadamba, and an estimated room profile for AAA Screen 7. The Melody photo's present-day match still needs administrator review. AAA Screen 7 has its operator-published 71 × 29.6 ft LED dimensions, but no photograph is assigned to it without a reliable Screen 7 match. Unsupported venue photos are rejected explicitly.

## 4. Payment flow

```
select seats
  → SeatLock (8 min hold)  +  Booking(status=PENDING)
  → /checkout            wallet OR UPI / card / netbanking
  → gateway order        local DEMO order (amounts in paise; no settlement)
  → signature verified   private HMAC-SHA256 demo response signature
  → BookedSeat rows committed, status=PAID, lock released
  → /ticket/<ref>        e-ticket + QR
```

Money math, all in `payments.py`:

```
tickets (sum of seat prices)
+ convenience fee  ₹20 per seat
+ GST              18% of the fee
= simulated amount
```

DEMO — No real money is charged or transferred. Wallet balances are virtual,
UPI/card/netbanking are simulations, and generated demo tickets are not valid for
admission. No card numbers, UPI PINs or bank credentials are collected.

- **Wallet:** existing virtual credits, recharge approval and refund calculations.
- **Demo simulator:** choose UPI/card/netbanking, then simulate success or failure.
  Orders and signed responses are created locally; no payment gateway is contacted.
- **Squad Pay:** participants simulate their shares using authenticated accounts.

Local development and testing enable the simulator by default unless explicitly
disabled. Production disables it by default. Set `DEMO_PAYMENTS_ENABLED=true` to
allow the hosted academic demo. Internal `PAID`/`CAPTURED` states preserve the
booking workflow; they do not represent real financial settlement. New payment
metadata records `demo=true` and `settled=false`; CSV rows identify demo amounts.

For one-service Render Free hosting, see [the deployment guide](docs/PRODUCTION_DEPLOYMENT_GUIDE.md).

### Why it can't double-book

1. `SeatLock` holds your seats for 8 minutes; other users see them greyed out as
   "being booked", and the seat page re-polls availability every 10 seconds.
2. Seats are only written to `BookedSeat` **after** payment succeeds, and
   `UNIQUE(showtime_id, seat_id)` is the last line of defence — if someone somehow got
   there first, the insert fails, the booking is marked `FAILED` and wallet money is
   refunded instead of selling the same seat twice.
3. Unpaid holds expire on their own (`purge_expired_holds()`), so abandoned checkouts
   never lock seats forever.
4. A forged success callback is rejected because the signature won't verify.

## 5. Routes added

| Route | Purpose |
|---|---|
| `GET/POST /book/<showtime_id>` | Seat map, hold seats, create pending booking |
| `GET /api/showtime/<id>/availability` | Live seat status (polled by the seat page) |
| `GET /checkout/<reference>` | Order summary, fees, hold countdown |
| `POST /pay/wallet/<reference>` | Pay from wallet |
| `POST /pay/gateway/<reference>` | Create a local demo order |
| `POST /pay/callback` | Verify signature, confirm booking |
| `POST /pay/simulate/<reference>` | Sandbox success/failure |
| `POST /booking/<reference>/cancel` | Release held seats |
| `GET /ticket/<reference>` + `/qr.png` | E-ticket and QR |
| `GET /wallet`, `POST /wallet/recharge` | Wallet + recharge request |
| `/admin/screens`, `/admin/add_screen`, `/admin/screen/<id>/layout` | Seating admin |
| `/admin/analytics` | Analytics dashboard: KPIs, revenue trend, top movies/theatres, payment split, occupancy heat strip (`?days=7/30/90`, omit for all-time) |
| `/admin/analytics/export.csv` | CSV download of every booking in the same window |
| `POST /admin/fetch_cast/<movie_id>` | Pull cast + director from TMDb onto a movie (auto-done on TMDb import) |
| `/admin/recharges`, `/admin/bookings`, `POST /admin/seed_vizag` | Admin tools |

## 6. Nice-to-haves if you want to keep going

- Email/SMS the ticket after payment (Flask-Mail or Twilio)
- Movie pages show cast & crew, fetched from TMDb on import (or via **Admin → Fetch cast**)
- Cancellation with partial refund to wallet, before showtime
- Food & beverage add-ons at checkout
- Coupon codes applied before GST
- Occupancy report per screen for the admin dashboard — **done, see `/admin/analytics`**
