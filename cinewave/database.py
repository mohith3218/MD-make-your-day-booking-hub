import json
import os
import secrets
from datetime import date, datetime, timedelta
from sqlalchemy import inspect, text
from flask import current_app
from .extensions import db
from .models import *
from .services import create_wallet
from .data import SAMPLE_LAYOUT
from vizag_theaters import seed_vizag_theaters
import payments
def auto_migrate():
    """
    Adds any newly introduced column to an existing SQLite file so your old
    vizag_movies.db keeps working instead of throwing OperationalError.
    """
    if db.engine.dialect.name != 'sqlite':
        raise RuntimeError('Legacy migration is SQLite-only. Run alembic upgrade head for PostgreSQL.')
    insp = inspect(db.engine)
    # These indexes are safe to add to existing installations and speed up the
    # booking history, pending-booking and expired-hold paths.
    for index in (Booking.__table__.indexes | SeatLock.__table__.indexes
                  | SeatHold.__table__.indexes | Payment.__table__.indexes):
        index.create(bind=db.engine, checkfirst=True)
    wanted = {
        'user': [('phone', 'VARCHAR(15)'), ('points', 'INTEGER DEFAULT 100'),
                 ('email_verified', 'BOOLEAN DEFAULT 1'),
                 ('email_otp_hash', 'VARCHAR(256)'),
                 ('email_otp_expires_at', 'DATETIME'),
                 ('email_otp_sent_at', 'DATETIME'),
                 ('email_otp_attempts', 'INTEGER DEFAULT 0'),
                 ('alternative_id', 'VARCHAR(64)'),
                 ('created_at', 'DATETIME'), ('bio', "VARCHAR(250) DEFAULT 'Cinema lover & movie enthusiast.'")],
        'movie': [('language', "VARCHAR(50)"), ('certificate', "VARCHAR(10)"),
                  ('rating', 'FLOAT DEFAULT 8.5'),
                  ('backdrop', 'VARCHAR(500)'), ('featured_order', 'INTEGER'),
                  ('is_upcoming', 'BOOLEAN DEFAULT 0'), ('release_date', 'DATE'),
                  ('is_rerelease', 'BOOLEAN DEFAULT 0'), ('moods_json', "TEXT DEFAULT '[]'"),
                  ('is_archived', 'BOOLEAN NOT NULL DEFAULT 0'),
                  ('tmdb_id', 'INTEGER'), ('cast_json', 'TEXT'),
                  ('youtube_trailer_key', 'VARCHAR(20)'),
                  ('trailer_video_path', 'VARCHAR(300)'),
                  ('tmdb_legacy_id', 'INTEGER'), ('tmdb_metadata', 'JSON'),
                  ('tmdb_snapshot', 'JSON'), ('tmdb_overrides', 'JSON'),
                  ('tmdb_managed', 'BOOLEAN NOT NULL DEFAULT 0'),
                  ('tmdb_original_release_date', 'DATE'), ('tmdb_regional_release_date', 'DATE'),
                  ('tmdb_rating', 'FLOAT'), ('tmdb_last_checked_at', 'DATETIME')],
        'theater': [('city', "VARCHAR(80)"), ('address', "VARCHAR(400)"),
                    ('verification_status', "VARCHAR(20) NOT NULL DEFAULT 'unverified'"),
                    ('verification_source_url', 'VARCHAR(500)'), ('verification_notes', 'TEXT'),
                    ('verification_reviewed_at', 'DATETIME'), ('verification_reviewed_by_id', 'INTEGER')],
        'screen': [('verification_status', "VARCHAR(20) NOT NULL DEFAULT 'unverified'"),
                   ('verification_source_url', 'VARCHAR(500)'), ('verification_notes', 'TEXT'),
                   ('verification_reviewed_at', 'DATETIME'), ('verification_reviewed_by_id', 'INTEGER')],
        'showtime': [('screen_id', 'INTEGER'), ('price_overrides_json', 'TEXT'),
                     ('is_cancelled', 'BOOLEAN NOT NULL DEFAULT 0')],
        'booking': [('reference', 'VARCHAR(20)'), ('seat_meta_json', 'TEXT'),
                    ('ticket_amount', 'FLOAT'), ('convenience_fee', 'FLOAT'),
                    ('gst', 'FLOAT'), ('status', "VARCHAR(20)"),
                    ('lock_token', 'VARCHAR(40)'), ('paid_at', 'DATETIME'),
                    ('ticket_email_sent_at', 'DATETIME'),
                    ('ticket_email_error', 'VARCHAR(300)'),
                    ('expires_at', 'DATETIME'), ('is_split_pay', 'BOOLEAN DEFAULT 0'),
                    ('split_token', 'VARCHAR(64)'),
                    ('snacks_json', 'TEXT'), ('points_redeemed', 'INTEGER DEFAULT 0')],
        'booked_seat': [('booking_id', 'INTEGER')],
        'movie_rating': [('has_spoiler', 'BOOLEAN DEFAULT 0')],
    }
    for table, cols in wanted.items():
        if table not in insp.get_table_names():
            continue
        existing = {c['name'] for c in insp.get_columns(table)}
        for col, coltype in cols:
            if col not in existing:
                db.session.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {coltype}'))
                print(f"  migrated: {table}.{col}")
    index = next((item for item in insp.get_indexes('movie') if item['name'] == 'ix_movie_tmdb_id'), None)
    if not index or not index['unique']:
        db.session.execute(text("""
            UPDATE movie SET tmdb_legacy_id = tmdb_id, tmdb_id = NULL
            WHERE tmdb_id IS NOT NULL AND EXISTS (
                SELECT 1 FROM movie AS canonical
                WHERE canonical.tmdb_id = movie.tmdb_id AND canonical.id < movie.id
            )
        """))
        db.session.execute(text('DROP INDEX IF EXISTS ix_movie_tmdb_id'))
        db.session.execute(text('CREATE UNIQUE INDEX ix_movie_tmdb_id ON movie (tmdb_id)'))
    db.session.execute(text(
        'CREATE INDEX IF NOT EXISTS ix_movie_tmdb_refresh ON movie (tmdb_last_checked_at)'))
    for account in User.query.filter((User.alternative_id.is_(None)) | (User.alternative_id == '')).all():
        account.alternative_id = secrets.token_urlsafe(32)
    db.session.commit()
    inspector = inspect(db.engine)
    if not any(set(item.get('column_names') or ()) == {'alternative_id'}
               for item in inspector.get_unique_constraints('user')):
        db.session.execute(text(
            'CREATE UNIQUE INDEX IF NOT EXISTS uq_user_alternative_id ON "user" (alternative_id)'))
        db.session.commit()

    # Backfill active legacy CSV locks into normalized per-seat holds. If old
    # overlapping locks exist, the first hold wins and the unique key preserves safety.
    for lock in SeatLock.query.filter(SeatLock.expires_at > datetime.utcnow()).all():
        for seat_id in lock.seat_list:
            exists = SeatHold.query.filter_by(showtime_id=lock.showtime_id,
                                              seat_id=seat_id).first()
            if not exists:
                db.session.add(SeatHold(showtime_id=lock.showtime_id, seat_id=seat_id,
                                        token=lock.token, expires_at=lock.expires_at))
    db.session.commit()

    # backfill references + status for pre-existing bookings
    for b in Booking.query.filter((Booking.reference.is_(None))).all():
        b.reference = 'CW' + secrets.token_hex(4).upper()
        b.status = 'PAID'
    db.session.commit()


def seed_sample_movies():
    """Seed popular Vizag blockbusters and showtimes for local development."""
    inox_screen = Screen.query.filter(Screen.name.contains('1')).first()
    jag_theater = Theater.query.filter(Theater.name.contains('Jagadamba')).first()
    jag_screen = jag_theater.screens[0] if (jag_theater and jag_theater.screens) else inox_screen
    cine_theater = Theater.query.filter(Theater.name.contains('Cinepolis')).first()
    cine_screen = cine_theater.screens[0] if (cine_theater and cine_theater.screens) else inox_screen

    samples = [
        {
            'title': 'Pushpa 2: The Rule',
            'description': 'The unstoppable rise of Pushpa Raj as he rules the syndicate and clashes with SP Bhanwar Singh Shekhawat in an explosive showdown.',
            'duration': 195,
            'poster': 'https://image.tmdb.org/t/p/w500/bQ2vHspz5K2f7wD0H92z6u6z4oG.jpg',
            'language': 'Telugu',
            'certificate': 'U/A',
            'rating': 9.1,
            'is_upcoming': False,
            'release_date': date.today() - timedelta(days=14),
            'moods_json': json.dumps(['MASS', 'THRILL']),
            'cast_json': json.dumps([
                {'name': 'Allu Arjun', 'role': 'Pushpa Raj'},
                {'name': 'Rashmika Mandanna', 'role': 'Srivalli'},
                {'name': 'Fahadh Faasil', 'role': 'SP Bhanwar Singh'}
            ]),
            'screen': inox_screen,
            'times': ['10:30 AM', '02:00 PM', '06:15 PM', '09:45 PM']
        },
        {
            'title': 'Devara: Part 1',
            'description': 'An epic coastal mass action saga of fear, courage, and legacy starring Jr NTR as a fearsome sea guardian.',
            'duration': 178,
            'poster': 'https://image.tmdb.org/t/p/w500/A73FvW30bK1h6Wl8l5Fp9y7v1Bf.jpg',
            'language': 'Telugu',
            'certificate': 'U/A',
            'rating': 8.7,
            'is_upcoming': False,
            'release_date': date.today() - timedelta(days=10),
            'moods_json': json.dumps(['THRILL', 'MASS']),
            'cast_json': json.dumps([
                {'name': 'Jr. NTR', 'role': 'Devara / Varadha'},
                {'name': 'Janhvi Kapoor', 'role': 'Thangam'},
                {'name': 'Saif Ali Khan', 'role': 'Bhaira'}
            ]),
            'screen': jag_screen,
            'times': ['02:15 PM', '06:45 PM', '10:15 PM']
        },
        {
            'title': 'Kalki 2898 AD',
            'description': 'A mythological sci-fi extravaganza set in post-apocalyptic Kasi where the battle for the future begins.',
            'duration': 181,
            'poster': 'https://image.tmdb.org/t/p/w500/87IVFtX1LzJ51m8N25C4kQJd1rZ.jpg',
            'language': 'Telugu',
            'certificate': 'U/A',
            'rating': 8.9,
            'is_upcoming': False,
            'release_date': date.today() - timedelta(days=20),
            'moods_json': json.dumps(['THRILL', 'ACTION']),
            'cast_json': json.dumps([
                {'name': 'Prabhas', 'role': 'Bhairava'},
                {'name': 'Amitabh Bachchan', 'role': 'Ashwatthama'},
                {'name': 'Kamal Haasan', 'role': 'Supreme Yaskin'}
            ]),
            'screen': inox_screen,
            'times': ['11:00 AM', '03:30 PM', '07:30 PM']
        },
        {
            'title': 'Game Changer',
            'description': 'A high-stakes political action thriller featuring an honest IAS officer taking down election corruption.',
            'duration': 165,
            'poster': 'https://image.tmdb.org/t/p/w500/1X78jG80R1x1L19kM0R2Q1.jpg',
            'language': 'Telugu',
            'certificate': 'U/A',
            'rating': 8.4,
            'is_upcoming': False,
            'release_date': date.today() - timedelta(days=5),
            'moods_json': json.dumps(['THRILL', 'DRAMA']),
            'cast_json': json.dumps([
                {'name': 'Ram Charan', 'role': 'Ram Nandan IAS'},
                {'name': 'Kiara Advani', 'role': 'Jabilamma'},
                {'name': 'SJ Suryah', 'role': 'Minister'}
            ]),
            'screen': cine_screen,
            'times': ['01:30 PM', '06:00 PM', '09:45 PM']
        }
    ]

    for m_data in samples:
        movie = Movie.query.filter_by(title=m_data['title']).first()
        if not movie:
            movie = Movie(
                title=m_data['title'],
                description=m_data['description'],
                duration=m_data['duration'],
                poster=m_data['poster'],
                language=m_data['language'],
                certificate=m_data['certificate'],
                rating=m_data['rating'],
                is_upcoming=m_data['is_upcoming'],
                release_date=m_data['release_date'],
                moods_json=m_data['moods_json'],
                cast_json=m_data['cast_json']
            )
            db.session.add(movie)
            db.session.flush()

        # Add showtimes if none exist
        if not movie.showtimes:
            target_screen = m_data['screen'] or inox_screen
            for t in m_data['times']:
                for day_offset in [0, 1, 2]:
                    s_date = date.today() + timedelta(days=day_offset)
                    st = Showtime(
                        movie_id=movie.id,
                        screen_id=target_screen.id if target_screen else None,
                        theater=target_screen.theater.name if target_screen else 'INOX Varun Beach',
                        show_date=s_date,
                        show_time=t
                    )
                    db.session.add(st)

    db.session.commit()


def init_db(application):
    with application.app_context():
        # Production guard: ensure schema is healthy before serving traffic.
        if current_app.config['APP_ENV'] == 'production':
            if db.engine.dialect.name != 'postgresql':
                raise RuntimeError(
                    'Production must use PostgreSQL. SQLite startup is not allowed.'
                )
            from database_health import check_database
            health = check_database(db.engine, db.metadata)
            if not health['ok']:
                raise RuntimeError(
                    'Database is unavailable or schema is outdated. '
                    'Run alembic upgrade head; '
                    'use python database_health.py for diagnostics.'
                )
            return
        db.create_all()
        auto_migrate()
        seed_vizag_theaters(db, Theater, Screen)
        seed_sample_movies()

        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            admin_password = os.environ.get('ADMIN_PASSWORD')
            if not admin_password:
                raise RuntimeError('Set ADMIN_PASSWORD to create the initial local administrator. '
                                   'Existing administrator credentials are never changed.')
            admin_user = User(username='admin', email='admin@cinewave.com', is_admin=True)
            admin_user.set_password(admin_password)
            db.session.add(admin_user)
            db.session.commit()
            create_wallet(admin_user, balance=10000)

        # make sure every existing account has a wallet with the signup bonus
        for u in User.query.all():
            if not Wallet.query.filter_by(user_id=u.id).first():
                create_wallet(u)

        # attach a screen to any legacy showtime that has none
        for s in Showtime.query.filter(Showtime.screen_id.is_(None)).all():
            t = Theater.query.filter_by(name=s.theater).first()
            screen = (Screen.query.filter_by(theater_id=t.id).first() if t
                      else Screen.query.first())
            if screen:
                s.screen_id = screen.id
                s.theater = screen.theater.name
        db.session.commit()

        mode = 'DEMO — no real money' if payments.mock_payments_enabled() else 'DEMO disabled'
        print(f"Payments: {mode}")
