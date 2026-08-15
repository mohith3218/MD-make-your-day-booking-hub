# CineWave — what was added

Two features, wired into your existing Flask app: **real theatre seating** and a **full payment flow**.
Everything is Vizag-only (Visakhapatnam theatres seeded on first run).

## 1. Run it

```bash
pip install -r requirements.txt
python app.py           # http://127.0.0.1:5000
```

Admin login: `admin` / `admin123`.
Your old `vizag_movies.db` keeps working — `auto_migrate()` adds the new columns on startup.
If you'd rather start clean, delete `instance/vizag_movies.db` and run again.

Verify everything at once:

```bash
python test_flow.py     # 13 checks: seat map, locks, wallet, gateway, refunds, expiry
```

## 2. Files

| File | What it is |
|---|---|
| `app.py` | Your app, extended (models + all routes) |
| `seat_layout.py` | Seat layout engine — turns layout JSON into a seat grid |
| `vizag_theaters.py` | 8 real Vizag theatres, 22 screens, ~4,995 seats |
| `payments.py` | Razorpay + sandbox gateway, fee/GST math, signature checks |
| `test_flow.py` | End-to-end test of the whole booking + payment flow |
| `templates/base.html` | Shared shell (header, wallet balance, flash messages) |
| `templates/book.html` | New seat map |
| `templates/checkout.html`, `pay_mock.html`, `pay_razorpay.html`, `ticket.html` | Payment flow + e-ticket |
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

## 4. Payment flow

```
select seats
  → SeatLock (8 min hold)  +  Booking(status=PENDING)
  → /checkout            wallet OR UPI / card / netbanking
  → gateway order        Razorpay order OR sandbox order (amounts in paise)
  → signature verified   HMAC-SHA256 of "order_id|payment_id"
  → BookedSeat rows committed, status=PAID, lock released
  → /ticket/<ref>        e-ticket + QR
```

Money math, all in `payments.py`:

```
tickets (sum of seat prices)
+ convenience fee  ₹20 per seat
+ GST              18% of the fee
= amount charged
```

Three payment methods:

- **Wallet** — uses the `Wallet` / `WalletTransaction` / `RechargeRequest` models you'd
  already defined but never wired up. Users request a recharge, admin approves it at
  **Admin → Recharges**, balance credits instantly. **Every new account now starts with
  ₹500 welcome balance** (`WELCOME_WALLET_BALANCE` in `app.py`), recorded as a wallet transaction.
- **Razorpay** — real Razorpay Checkout. Set the keys and it switches over automatically:
  ```bash
  export RAZORPAY_KEY_ID=rzp_test_xxxxxxxx
  export RAZORPAY_KEY_SECRET=yyyyyyyy
  export RAZORPAY_WEBHOOK_SECRET=zzzzzzzz   # optional, enables /pay/webhook
  ```
- **Sandbox** — no keys, no problem. Creates a real order record, returns a signed
  response and verifies the signature exactly like live mode, plus a
  "Simulate a failed payment" button. Good for demoing to your reviewer.

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
| `POST /pay/gateway/<reference>` | Create Razorpay/sandbox order |
| `POST /pay/callback` | Verify signature, confirm booking |
| `POST /pay/simulate/<reference>` | Sandbox success/failure |
| `POST /pay/webhook` | Razorpay webhook (survives a closed tab) |
| `POST /booking/<reference>/cancel` | Release held seats |
| `GET /ticket/<reference>` + `/qr.png` | E-ticket and QR |
| `GET /wallet`, `POST /wallet/recharge` | Wallet + recharge request |
| `/admin/screens`, `/admin/add_screen`, `/admin/screen/<id>/layout` | Seating admin |
| `/admin/recharges`, `/admin/bookings`, `POST /admin/seed_vizag` | Admin tools |

## 6. Nice-to-haves if you want to keep going

- Email/SMS the ticket after payment (Flask-Mail or Twilio)
- Cancellation with partial refund to wallet, before showtime
- Food & beverage add-ons at checkout
- Coupon codes applied before GST
- Occupancy report per screen for the admin dashboard
