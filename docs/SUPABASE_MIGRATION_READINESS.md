# Supabase Migration Readiness – Read‑Only Inspection

---

## SQLite Database
* File: `C:\Code\MD-booking-hub\instance\vizag_movies.db`
### Tables and record counts
- `booked_seat`: 3 rows
- `booking`: 6 rows
- `movie`: 6 rows
- `movie_rating`: 8 rows
- `party_member`: 0 rows
- `party_session`: 0 rows
- `payment`: 5 rows
- `recharge_request`: 1 rows
- `screen`: 127 rows
- `seat_hold`: 0 rows
- `seat_lock`: 0 rows
- `showtime`: 48 rows
- `split_contribution`: 0 rows
- `theater`: 89 rows
- `user`: 6 rows
- `wallet`: 6 rows
- `wallet_transaction`: 7 rows
- `watchlist`: 0 rows

### Schema details
#### booked_seat
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `showtime_id`: INTEGER, nullable=False, default=None
- `seat_id`: VARCHAR(10), nullable=False, default=None
- `booking_id`: INTEGER, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: ['uq_showtime_seat']
**Indexes**: []
**Foreign keys**
- ['showtime_id'] → showtime(['id'])
- ['booking_id'] → booking(['id'])

#### booking
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `reference`: VARCHAR(20), nullable=False, default=None
- `user_id`: INTEGER, nullable=False, default=None
- `showtime_id`: INTEGER, nullable=False, default=None
- `seats`: VARCHAR(200), nullable=False, default=None
- `seat_meta_json`: TEXT, nullable=True, default=None
- `ticket_amount`: FLOAT, nullable=True, default=None
- `convenience_fee`: FLOAT, nullable=True, default=None
- `gst`: FLOAT, nullable=True, default=None
- `total_amount`: FLOAT, nullable=False, default=None
- `is_split_pay`: BOOLEAN, nullable=True, default=None
- `split_token`: VARCHAR(64), nullable=True, default=None
- `snacks_json`: TEXT, nullable=True, default=None
- `points_redeemed`: INTEGER, nullable=True, default=None
- `status`: VARCHAR(20), nullable=False, default=None
- `lock_token`: VARCHAR(40), nullable=True, default=None
- `booked_at`: DATETIME, nullable=True, default=None
- `paid_at`: DATETIME, nullable=True, default=None
- `ticket_email_sent_at`: DATETIME, nullable=True, default=None
- `ticket_email_error`: VARCHAR(300), nullable=True, default=None
- `expires_at`: DATETIME, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: [None, None]
**Indexes**: ['ix_booking_showtime_status', 'ix_booking_user_status_booked']
**Foreign keys**
- ['user_id'] → user(['id'])
- ['showtime_id'] → showtime(['id'])

#### movie
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `title`: VARCHAR(200), nullable=False, default=None
- `description`: TEXT, nullable=False, default=None
- `duration`: INTEGER, nullable=False, default=None
- `poster`: VARCHAR(500), nullable=True, default=None
- `language`: VARCHAR(50), nullable=True, default=None
- `certificate`: VARCHAR(10), nullable=True, default=None
- `rating`: FLOAT, nullable=True, default=None
- `is_upcoming`: BOOLEAN, nullable=True, default=None
- `is_rerelease`: BOOLEAN, nullable=True, default=None
- `release_date`: DATE, nullable=True, default=None
- `moods_json`: TEXT, nullable=True, default=None
- `tmdb_id`: INTEGER, nullable=True, default=None
- `cast_json`: TEXT, nullable=True, default=None
- `youtube_trailer_key`: VARCHAR(20), nullable=True, default=None
- `trailer_video_path`: VARCHAR(300), nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: []
**Indexes**: ['ix_movie_tmdb_id']
**Foreign keys**

#### movie_rating
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `user_id`: INTEGER, nullable=False, default=None
- `movie_id`: INTEGER, nullable=False, default=None
- `rating`: FLOAT, nullable=False, default=None
- `review`: VARCHAR(500), nullable=True, default=None
- `has_spoiler`: BOOLEAN, nullable=True, default=None
- `created_at`: DATETIME, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: ['_user_movie_rating_uc']
**Indexes**: []
**Foreign keys**
- ['user_id'] → user(['id'])
- ['movie_id'] → movie(['id'])

#### party_member
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `party_id`: INTEGER, nullable=False, default=None
- `user_id`: INTEGER, nullable=True, default=None
- `user_name`: VARCHAR(80), nullable=False, default=None
- `avatar_color`: VARCHAR(20), nullable=True, default=None
- `selected_seats`: VARCHAR(200), nullable=True, default=None
- `last_ping`: DATETIME, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: []
**Indexes**: []
**Foreign keys**
- ['party_id'] → party_session(['id'])
- ['user_id'] → user(['id'])

#### party_session
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `code`: VARCHAR(10), nullable=False, default=None
- `showtime_id`: INTEGER, nullable=False, default=None
- `host_id`: INTEGER, nullable=True, default=None
- `created_at`: DATETIME, nullable=True, default=None
- `status`: VARCHAR(20), nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: [None]
**Indexes**: []
**Foreign keys**
- ['showtime_id'] → showtime(['id'])
- ['host_id'] → user(['id'])

#### payment
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `booking_id`: INTEGER, nullable=False, default=None
- `gateway`: VARCHAR(30), nullable=True, default=None
- `order_id`: VARCHAR(80), nullable=True, default=None
- `payment_id`: VARCHAR(80), nullable=True, default=None
- `signature`: VARCHAR(200), nullable=True, default=None
- `method`: VARCHAR(40), nullable=True, default=None
- `amount`: FLOAT, nullable=True, default=None
- `currency`: VARCHAR(10), nullable=True, default=None
- `status`: VARCHAR(20), nullable=True, default=None
- `error_message`: VARCHAR(300), nullable=True, default=None
- `raw_response`: TEXT, nullable=True, default=None
- `created_at`: DATETIME, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: []
**Indexes**: ['ix_payment_order_id']
**Foreign keys**
- ['booking_id'] → booking(['id'])

#### recharge_request
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `user_id`: INTEGER, nullable=False, default=None
- `amount`: FLOAT, nullable=False, default=None
- `status`: VARCHAR(20), nullable=True, default=None
- `created_at`: DATETIME, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: []
**Indexes**: []
**Foreign keys**
- ['user_id'] → user(['id'])

#### screen
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `theater_id`: INTEGER, nullable=False, default=None
- `name`: VARCHAR(80), nullable=False, default=None
- `screen_type`: VARCHAR(40), nullable=True, default=None
- `layout_json`: TEXT, nullable=False, default=None
**Primary key**: ['id']
**Unique constraints**: []
**Indexes**: []
**Foreign keys**
- ['theater_id'] → theater(['id'])

#### seat_hold
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `showtime_id`: INTEGER, nullable=False, default=None
- `seat_id`: VARCHAR(10), nullable=False, default=None
- `token`: VARCHAR(40), nullable=False, default=None
- `expires_at`: DATETIME, nullable=False, default=None
**Primary key**: ['id']
**Unique constraints**: ['uq_seat_hold_showtime_seat']
**Indexes**: ['ix_seat_hold_expiry', 'ix_seat_hold_token']
**Foreign keys**
- ['showtime_id'] → showtime(['id'])

#### seat_lock
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `showtime_id`: INTEGER, nullable=False, default=None
- `user_id`: INTEGER, nullable=True, default=None
- `token`: VARCHAR(40), nullable=False, default=None
- `seats`: VARCHAR(500), nullable=False, default=None
- `created_at`: DATETIME, nullable=True, default=None
- `expires_at`: DATETIME, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: [None]
**Indexes**: ['ix_seat_lock_showtime_expiry']
**Foreign keys**
- ['showtime_id'] → showtime(['id'])
- ['user_id'] → user(['id'])

#### showtime
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `movie_id`: INTEGER, nullable=False, default=None
- `screen_id`: INTEGER, nullable=True, default=None
- `theater`: VARCHAR(100), nullable=False, default=None
- `show_date`: DATE, nullable=False, default=None
- `show_time`: VARCHAR(20), nullable=False, default=None
- `price_overrides_json`: TEXT, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: []
**Indexes**: []
**Foreign keys**
- ['movie_id'] → movie(['id'])
- ['screen_id'] → screen(['id'])

#### split_contribution
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `booking_id`: INTEGER, nullable=False, default=None
- `user_id`: INTEGER, nullable=True, default=None
- `share_index`: INTEGER, nullable=False, default=None
- `amount`: FLOAT, nullable=False, default=None
- `status`: VARCHAR(20), nullable=False, default=None
- `gateway`: VARCHAR(30), nullable=True, default=None
- `method`: VARCHAR(30), nullable=True, default=None
- `order_id`: VARCHAR(80), nullable=True, default=None
- `payment_id`: VARCHAR(80), nullable=True, default=None
- `signature`: VARCHAR(200), nullable=True, default=None
- `error_message`: VARCHAR(300), nullable=True, default=None
- `created_at`: DATETIME, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: ['uq_split_booking_share', 'uq_split_booking_user']
**Indexes**: []
**Foreign keys**
- ['booking_id'] → booking(['id'])
- ['user_id'] → user(['id'])

#### theater
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `name`: VARCHAR(120), nullable=False, default=None
- `location`: VARCHAR(200), nullable=True, default=None
- `city`: VARCHAR(80), nullable=True, default=None
- `address`: VARCHAR(400), nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: [None]
**Indexes**: []
**Foreign keys**

#### user
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `username`: VARCHAR(100), nullable=False, default=None
- `email`: VARCHAR(120), nullable=True, default=None
- `email_verified`: BOOLEAN, nullable=False, default=None
- `email_otp_hash`: VARCHAR(256), nullable=True, default=None
- `email_otp_expires_at`: DATETIME, nullable=True, default=None
- `email_otp_sent_at`: DATETIME, nullable=True, default=None
- `email_otp_attempts`: INTEGER, nullable=False, default=None
- `phone`: VARCHAR(15), nullable=True, default=None
- `password_hash`: VARCHAR(200), nullable=False, default=None
- `is_admin`: BOOLEAN, nullable=True, default=None
- `points`: INTEGER, nullable=True, default=None
- `created_at`: DATETIME, nullable=True, default=None
- `bio`: VARCHAR(250), nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: [None, None]
**Indexes**: []
**Foreign keys**

#### wallet
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `user_id`: INTEGER, nullable=False, default=None
- `balance`: FLOAT, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: [None]
**Indexes**: []
**Foreign keys**
- ['user_id'] → user(['id'])

#### wallet_transaction
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `wallet_id`: INTEGER, nullable=False, default=None
- `amount`: FLOAT, nullable=False, default=None
- `type`: VARCHAR(20), nullable=False, default=None
- `description`: VARCHAR(200), nullable=True, default=None
- `timestamp`: DATETIME, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: []
**Indexes**: []
**Foreign keys**
- ['wallet_id'] → wallet(['id'])

#### watchlist
**Columns**
- `id`: INTEGER, nullable=False, default=None
- `user_id`: INTEGER, nullable=False, default=None
- `movie_id`: INTEGER, nullable=False, default=None
- `added_at`: DATETIME, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: ['_user_movie_uc']
**Indexes**: []
**Foreign keys**
- ['user_id'] → user(['id'])
- ['movie_id'] → movie(['id'])

---
## Supabase PostgreSQL Database
### Tables and record counts
- `alembic_version`: 1 rows
- `booked_seat`: 0 rows
- `booking`: 0 rows
- `movie`: 0 rows
- `movie_rating`: 0 rows
- `party_member`: 0 rows
- `party_session`: 0 rows
- `payment`: 0 rows
- `recharge_request`: 0 rows
- `screen`: 127 rows
- `seat_hold`: 0 rows
- `seat_lock`: 0 rows
- `showtime`: 0 rows
- `split_contribution`: 0 rows
- `theater`: 89 rows
- `user`: 0 rows
- `wallet`: 0 rows
- `wallet_transaction`: 0 rows
- `watchlist`: 0 rows

### Schema details
#### alembic_version
**Columns**
- `version_num`: VARCHAR(32), nullable=False, default=None
**Primary key**: ['version_num']
**Unique constraints**: []
**Indexes**: []
**Foreign keys**

#### booked_seat
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('booked_seat_id_seq'::regclass)
- `showtime_id`: INTEGER, nullable=False, default=None
- `seat_id`: VARCHAR(10), nullable=False, default=None
- `booking_id`: INTEGER, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: ['uq_showtime_seat']
**Indexes**: ['uq_showtime_seat']
**Foreign keys**
- ['booking_id'] → booking(['id'])
- ['showtime_id'] → showtime(['id'])

#### booking
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('booking_id_seq'::regclass)
- `reference`: VARCHAR(20), nullable=False, default=None
- `user_id`: INTEGER, nullable=False, default=None
- `showtime_id`: INTEGER, nullable=False, default=None
- `seats`: VARCHAR(200), nullable=False, default=None
- `seat_meta_json`: TEXT, nullable=True, default=None
- `ticket_amount`: DOUBLE PRECISION, nullable=True, default=None
- `convenience_fee`: DOUBLE PRECISION, nullable=True, default=None
- `gst`: DOUBLE PRECISION, nullable=True, default=None
- `total_amount`: DOUBLE PRECISION, nullable=False, default=None
- `is_split_pay`: BOOLEAN, nullable=True, default=None
- `split_token`: VARCHAR(64), nullable=True, default=None
- `snacks_json`: TEXT, nullable=True, default=None
- `points_redeemed`: INTEGER, nullable=True, default=None
- `status`: VARCHAR(20), nullable=False, default=None
- `lock_token`: VARCHAR(40), nullable=True, default=None
- `booked_at`: TIMESTAMP, nullable=True, default=None
- `paid_at`: TIMESTAMP, nullable=True, default=None
- `ticket_email_sent_at`: TIMESTAMP, nullable=True, default=None
- `ticket_email_error`: VARCHAR(300), nullable=True, default=None
- `expires_at`: TIMESTAMP, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: ['booking_reference_key', 'booking_split_token_key']
**Indexes**: ['booking_reference_key', 'booking_split_token_key', 'ix_booking_showtime_status', 'ix_booking_user_status_booked']
**Foreign keys**
- ['showtime_id'] → showtime(['id'])
- ['user_id'] → user(['id'])

#### movie
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('movie_id_seq'::regclass)
- `title`: VARCHAR(200), nullable=False, default=None
- `description`: TEXT, nullable=False, default=None
- `duration`: INTEGER, nullable=False, default=None
- `poster`: VARCHAR(500), nullable=True, default=None
- `language`: VARCHAR(50), nullable=True, default=None
- `certificate`: VARCHAR(10), nullable=True, default=None
- `rating`: DOUBLE PRECISION, nullable=True, default=None
- `is_upcoming`: BOOLEAN, nullable=True, default=None
- `is_rerelease`: BOOLEAN, nullable=True, default=None
- `release_date`: DATE, nullable=True, default=None
- `moods_json`: TEXT, nullable=True, default=None
- `tmdb_id`: INTEGER, nullable=True, default=None
- `cast_json`: TEXT, nullable=True, default=None
- `youtube_trailer_key`: VARCHAR(20), nullable=True, default=None
- `trailer_video_path`: VARCHAR(300), nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: []
**Indexes**: ['ix_movie_tmdb_id']
**Foreign keys**

#### movie_rating
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('movie_rating_id_seq'::regclass)
- `user_id`: INTEGER, nullable=False, default=None
- `movie_id`: INTEGER, nullable=False, default=None
- `rating`: DOUBLE PRECISION, nullable=False, default=None
- `review`: VARCHAR(500), nullable=True, default=None
- `has_spoiler`: BOOLEAN, nullable=True, default=None
- `created_at`: TIMESTAMP, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: ['_user_movie_rating_uc']
**Indexes**: ['_user_movie_rating_uc']
**Foreign keys**
- ['movie_id'] → movie(['id'])
- ['user_id'] → user(['id'])

#### party_member
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('party_member_id_seq'::regclass)
- `party_id`: INTEGER, nullable=False, default=None
- `user_id`: INTEGER, nullable=True, default=None
- `user_name`: VARCHAR(80), nullable=False, default=None
- `avatar_color`: VARCHAR(20), nullable=True, default=None
- `selected_seats`: VARCHAR(200), nullable=True, default=None
- `last_ping`: TIMESTAMP, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: []
**Indexes**: []
**Foreign keys**
- ['party_id'] → party_session(['id'])
- ['user_id'] → user(['id'])

#### party_session
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('party_session_id_seq'::regclass)
- `code`: VARCHAR(10), nullable=False, default=None
- `showtime_id`: INTEGER, nullable=False, default=None
- `host_id`: INTEGER, nullable=True, default=None
- `created_at`: TIMESTAMP, nullable=True, default=None
- `status`: VARCHAR(20), nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: ['party_session_code_key']
**Indexes**: ['party_session_code_key']
**Foreign keys**
- ['host_id'] → user(['id'])
- ['showtime_id'] → showtime(['id'])

#### payment
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('payment_id_seq'::regclass)
- `booking_id`: INTEGER, nullable=False, default=None
- `gateway`: VARCHAR(30), nullable=True, default=None
- `order_id`: VARCHAR(80), nullable=True, default=None
- `payment_id`: VARCHAR(80), nullable=True, default=None
- `signature`: VARCHAR(200), nullable=True, default=None
- `method`: VARCHAR(40), nullable=True, default=None
- `amount`: DOUBLE PRECISION, nullable=True, default=None
- `currency`: VARCHAR(10), nullable=True, default=None
- `status`: VARCHAR(20), nullable=True, default=None
- `error_message`: VARCHAR(300), nullable=True, default=None
- `raw_response`: TEXT, nullable=True, default=None
- `created_at`: TIMESTAMP, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: []
**Indexes**: ['ix_payment_order_id']
**Foreign keys**
- ['booking_id'] → booking(['id'])

#### recharge_request
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('recharge_request_id_seq'::regclass)
- `user_id`: INTEGER, nullable=False, default=None
- `amount`: DOUBLE PRECISION, nullable=False, default=None
- `status`: VARCHAR(20), nullable=True, default=None
- `created_at`: TIMESTAMP, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: []
**Indexes**: []
**Foreign keys**
- ['user_id'] → user(['id'])

#### screen
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('screen_id_seq'::regclass)
- `theater_id`: INTEGER, nullable=False, default=None
- `name`: VARCHAR(80), nullable=False, default=None
- `screen_type`: VARCHAR(40), nullable=True, default=None
- `layout_json`: TEXT, nullable=False, default=None
**Primary key**: ['id']
**Unique constraints**: []
**Indexes**: []
**Foreign keys**
- ['theater_id'] → theater(['id'])

#### seat_hold
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('seat_hold_id_seq'::regclass)
- `showtime_id`: INTEGER, nullable=False, default=None
- `seat_id`: VARCHAR(10), nullable=False, default=None
- `token`: VARCHAR(40), nullable=False, default=None
- `expires_at`: TIMESTAMP, nullable=False, default=None
**Primary key**: ['id']
**Unique constraints**: ['uq_seat_hold_showtime_seat']
**Indexes**: ['ix_seat_hold_expiry', 'ix_seat_hold_token', 'uq_seat_hold_showtime_seat']
**Foreign keys**
- ['showtime_id'] → showtime(['id'])

#### seat_lock
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('seat_lock_id_seq'::regclass)
- `showtime_id`: INTEGER, nullable=False, default=None
- `user_id`: INTEGER, nullable=True, default=None
- `token`: VARCHAR(40), nullable=False, default=None
- `seats`: VARCHAR(500), nullable=False, default=None
- `created_at`: TIMESTAMP, nullable=True, default=None
- `expires_at`: TIMESTAMP, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: ['seat_lock_token_key']
**Indexes**: ['ix_seat_lock_showtime_expiry', 'seat_lock_token_key']
**Foreign keys**
- ['showtime_id'] → showtime(['id'])
- ['user_id'] → user(['id'])

#### showtime
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('showtime_id_seq'::regclass)
- `movie_id`: INTEGER, nullable=False, default=None
- `screen_id`: INTEGER, nullable=True, default=None
- `theater`: VARCHAR(100), nullable=False, default=None
- `show_date`: DATE, nullable=False, default=None
- `show_time`: VARCHAR(20), nullable=False, default=None
- `price_overrides_json`: TEXT, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: []
**Indexes**: []
**Foreign keys**
- ['movie_id'] → movie(['id'])
- ['screen_id'] → screen(['id'])

#### split_contribution
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('split_contribution_id_seq'::regclass)
- `booking_id`: INTEGER, nullable=False, default=None
- `user_id`: INTEGER, nullable=True, default=None
- `share_index`: INTEGER, nullable=False, default=None
- `amount`: DOUBLE PRECISION, nullable=False, default=None
- `status`: VARCHAR(20), nullable=False, default=None
- `gateway`: VARCHAR(30), nullable=True, default=None
- `method`: VARCHAR(30), nullable=True, default=None
- `order_id`: VARCHAR(80), nullable=True, default=None
- `payment_id`: VARCHAR(80), nullable=True, default=None
- `signature`: VARCHAR(200), nullable=True, default=None
- `error_message`: VARCHAR(300), nullable=True, default=None
- `created_at`: TIMESTAMP, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: ['uq_split_booking_share', 'uq_split_booking_user']
**Indexes**: ['uq_split_booking_share', 'uq_split_booking_user']
**Foreign keys**
- ['booking_id'] → booking(['id'])
- ['user_id'] → user(['id'])

#### theater
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('theater_id_seq'::regclass)
- `name`: VARCHAR(120), nullable=False, default=None
- `location`: VARCHAR(200), nullable=True, default=None
- `city`: VARCHAR(80), nullable=True, default=None
- `address`: VARCHAR(400), nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: ['theater_name_key']
**Indexes**: ['theater_name_key']
**Foreign keys**

#### user
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('user_id_seq'::regclass)
- `username`: VARCHAR(100), nullable=False, default=None
- `email`: VARCHAR(120), nullable=True, default=None
- `email_verified`: BOOLEAN, nullable=False, default=None
- `email_otp_hash`: VARCHAR(256), nullable=True, default=None
- `email_otp_expires_at`: TIMESTAMP, nullable=True, default=None
- `email_otp_sent_at`: TIMESTAMP, nullable=True, default=None
- `email_otp_attempts`: INTEGER, nullable=False, default=None
- `phone`: VARCHAR(15), nullable=True, default=None
- `password_hash`: VARCHAR(200), nullable=False, default=None
- `is_admin`: BOOLEAN, nullable=True, default=None
- `points`: INTEGER, nullable=True, default=None
- `created_at`: TIMESTAMP, nullable=True, default=None
- `bio`: VARCHAR(250), nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: ['user_email_key', 'user_username_key']
**Indexes**: ['user_email_key', 'user_username_key']
**Foreign keys**

#### wallet
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('wallet_id_seq'::regclass)
- `user_id`: INTEGER, nullable=False, default=None
- `balance`: DOUBLE PRECISION, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: ['wallet_user_id_key']
**Indexes**: ['wallet_user_id_key']
**Foreign keys**
- ['user_id'] → user(['id'])

#### wallet_transaction
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('wallet_transaction_id_seq'::regclass)
- `wallet_id`: INTEGER, nullable=False, default=None
- `amount`: DOUBLE PRECISION, nullable=False, default=None
- `type`: VARCHAR(20), nullable=False, default=None
- `description`: VARCHAR(200), nullable=True, default=None
- `timestamp`: TIMESTAMP, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: []
**Indexes**: []
**Foreign keys**
- ['wallet_id'] → wallet(['id'])

#### watchlist
**Columns**
- `id`: INTEGER, nullable=False, default=nextval('watchlist_id_seq'::regclass)
- `user_id`: INTEGER, nullable=False, default=None
- `movie_id`: INTEGER, nullable=False, default=None
- `added_at`: TIMESTAMP, nullable=True, default=None
**Primary key**: ['id']
**Unique constraints**: ['_user_movie_uc']
**Indexes**: ['_user_movie_uc']
**Foreign keys**
- ['movie_id'] → movie(['id'])
- ['user_id'] → user(['id'])

---
## Comparison Summary
* Tables only in SQLite (would need creation in Supabase): []
* Tables only in PostgreSQL (pre‑existing data): ['alembic_version']

### Potential schema gaps

### Duplicate / conflicting records
No data modifications were performed. Duplicate checks would require row‑by‑row comparison, which is beyond this read‑only audit.

### Foreign‑key dependencies & migration order
- Table `booked_seat` depends on ['showtime', 'booking']
- Table `booking` depends on ['user', 'showtime']
- Table `movie_rating` depends on ['user', 'movie']
- Table `party_member` depends on ['party_session', 'user']
- Table `party_session` depends on ['showtime', 'user']
- Table `payment` depends on ['booking']
- Table `recharge_request` depends on ['user']
- Table `screen` depends on ['theater']
- Table `seat_hold` depends on ['showtime']
- Table `seat_lock` depends on ['showtime', 'user']
- Table `showtime` depends on ['movie', 'screen']
- Table `split_contribution` depends on ['booking', 'user']
- Table `wallet` depends on ['user']
- Table `wallet_transaction` depends on ['wallet']
- Table `watchlist` depends on ['user', 'movie']

### Overwrite risk
Supabase already contains data in tables listed under "extra in PostgreSQL". Importing SQLite rows into those tables could cause primary‑key or unique‑constraint conflicts. A merge strategy or fresh schema creation is recommended.

---

**Next steps** (manual, no automated actions taken):
1. Verify that missing tables/columns are acceptable to create in Supabase.
2. Generate Alembic migration scripts (`alembic revision --autogenerate`) in `--sql` mode and review.
3. Backup both databases (SQLite copy, `pg_dump` for PostgreSQL).
4. Plan data import order based on foreign‑key dependencies (leaf tables first, then parents).
5. Decide on conflict resolution (skip existing rows, upsert, or truncate target tables if safe).