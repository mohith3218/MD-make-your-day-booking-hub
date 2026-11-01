"""
CineWave - Vizag Movie Ticket Booking
=====================================
Backend: Flask + SQLAlchemy (SQLite)

What is new in this version
---------------------------
1. REAL THEATRE SEATING
   Theater -> Screen -> layout JSON. Every audi in Vizag has its own row
   widths, aisle positions, seat classes and blocked seats. Seeded with
   INOX Varun Beach / CMR Central / Chitralaya, Cinepolis Sreekanya,
   Mukta A2, Jagadamba 70MM, Melody, Sangam Sarat.

2. FULL PAYMENT FLOW
   select seats -> seats locked for 8 min -> checkout (wallet / UPI / card)
   -> gateway order -> signature verification -> seats committed -> e-ticket.
   Razorpay when keys are set, sandbox simulator otherwise.
   Wallet, recharge requests and admin approval are now wired up.

Run:
    pip install -r requirements.txt
    python app.py            ->  http://127.0.0.1:5000
    On first startup, the admin password is printed once; set ADMIN_PASSWORD to choose it.
"""

import csv
import hashlib
import html
import hmac
import io
import json
import os
import re
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func as sa_func

import requests
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import payments
import seat_layout as sl
from vizag_theaters import seed_vizag_theaters


def load_local_dotenv():
    """Load simple KEY=value settings from the project .env without overriding the shell."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    try:
        with open(env_path, encoding='utf-8') as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.startswith('export '):
                    line = line[7:].lstrip()
                key, separator, value = line.partition('=')
                key = key.strip()
                if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
                    continue
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                    value = value[1:-1]
                os.environ.setdefault(key, value)
    except FileNotFoundError:
        pass


load_local_dotenv()

app = Flask(__name__)
# Use a fresh key when one is not configured. Deployments should set SECRET_KEY
# so sessions remain valid across restarts and app workers.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///vizag_movies.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', '').strip().lower() in {'1', 'true', 'yes'}
app.config['MAX_CONTENT_LENGTH'] = 250 * 1024 * 1024
app.config['STARTUP_ID'] = secrets.token_urlsafe(10)
app.config['SMTP_HOST'] = os.environ.get('SMTP_HOST', '').strip()
app.config['SMTP_PORT'] = int(os.environ.get('SMTP_PORT', '587'))
app.config['SMTP_USERNAME'] = os.environ.get('SMTP_USERNAME', '').strip()
app.config['SMTP_PASSWORD'] = os.environ.get('SMTP_PASSWORD', '')
app.config['SMTP_FROM_EMAIL'] = os.environ.get('SMTP_FROM_EMAIL', app.config['SMTP_USERNAME']).strip()
app.config['SMTP_USE_SSL'] = os.environ.get('SMTP_USE_SSL', '').strip().lower() in {'1', 'true', 'yes'}

# TMDb API Key
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "329d5f23baebf5312db6f28ab506ce9e")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

# how long selected seats stay held while the user pays
SEAT_LOCK_MINUTES = 8

# every new account starts with this much wallet money (signup bonus)
WELCOME_WALLET_BALANCE = 500

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# ====================== MODELS ======================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    email_verified = db.Column(db.Boolean, nullable=False, default=True)
    email_otp_hash = db.Column(db.String(256), nullable=True)
    email_otp_expires_at = db.Column(db.DateTime, nullable=True)
    email_otp_sent_at = db.Column(db.DateTime, nullable=True)
    email_otp_attempts = db.Column(db.Integer, nullable=False, default=0)
    phone = db.Column(db.String(15), nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    points = db.Column(db.Integer, default=100)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    bio = db.Column(db.String(250), nullable=True, default='Cinema lover & movie enthusiast.')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def initials(self):
        name = (self.username or 'U').strip()
        parts = re.split(r'[\s._-]+', name)
        if len(parts) >= 2 and parts[0] and parts[1]:
            return f"{parts[0][0]}{parts[1][0]}".upper()
        return (name[:2] if len(name) >= 2 else name).upper()

    @property
    def member_since_formatted(self):
        dt = self.created_at or datetime(2024, 1, 1)
        return dt.strftime('Member since %B %Y')

    @property
    def club_tier(self):
        pts = self.points or 0
        if pts >= 500:
            return "CineWave Club VIP"
        elif pts >= 250:
            return "CineWave Club Gold"
        return "CineWave Club 08"

    @property
    def stats(self):
        paid_bookings = [b for b in self.bookings if b.status == 'PAID']
        distinct_movies = {}
        for b in paid_bookings:
            if b.showtime and b.showtime.movie:
                distinct_movies[b.showtime.movie.id] = b.showtime.movie

        current_year = datetime.utcnow().year
        films_this_year = sum(1 for b in paid_bookings if b.booked_at and b.booked_at.year == current_year)
        total_minutes = sum((m.duration or 120) for m in distinct_movies.values())
        hours_watched = round(total_minutes / 60, 1) if total_minutes else 0.0

        user_ratings = [r.rating for r in self.movie_ratings]
        if user_ratings:
            avg_rating = round(sum(user_ratings) / len(user_ratings), 1)
        elif distinct_movies:
            movie_ratings = [m.display_rating for m in distinct_movies.values()]
            avg_rating = round(sum(movie_ratings) / len(movie_ratings), 1) if movie_ratings else 0.0
        else:
            avg_rating = 0.0

        return {
            'films_this_year': films_this_year,
            'total_films': len(distinct_movies),
            'hours_watched': hours_watched,
            'avg_rating': avg_rating,
            'total_bookings': len(paid_bookings)
        }

    @property
    def film_dna(self):
        paid_bookings = [b for b in self.bookings if b.status == 'PAID']
        mood_counts = {}
        total_tags = 0

        mood_meta = {
            'EMOTIONAL': ('Drama', '#d9979a', 'bg-[#d9979a]'),
            'MIND_BENDING': ('Sci-Fi', '#70b9cc', 'bg-[#70b9cc]'),
            'ROMANCE': ('Romance', '#ef8ba8', 'bg-[#ef8ba8]'),
            'THRILL': ('Action & Thrill', '#f5b942', 'bg-[#f5b942]'),
            'FUN': ('Comedy & Fun', '#82c9a0', 'bg-[#82c9a0]')
        }

        for b in paid_bookings:
            if b.showtime and b.showtime.movie:
                for mood in b.showtime.movie.moods:
                    mood_counts[mood] = mood_counts.get(mood, 0) + 1
                    total_tags += 1

        if not mood_counts or total_tags == 0:
            return []

        dna = []
        for code, count in sorted(mood_counts.items(), key=lambda x: x[1], reverse=True)[:4]:
            meta = mood_meta.get(code, (code.capitalize(), '#f5b942', 'bg-[#f5b942]'))
            pct = round((count / total_tags) * 100)
            dna.append({
                'name': meta[0],
                'pct': pct,
                'color_hex': meta[1],
                'color_class': meta[2]
            })
        return dna

    @property
    def watchlist_movies(self):
        items = sorted(self.watchlist_items, key=lambda x: x.added_at, reverse=True)
        return [item.movie for item in items if item.movie]


class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    poster = db.Column(db.String(500), nullable=True)
    language = db.Column(db.String(50), nullable=True, default='Telugu')
    certificate = db.Column(db.String(10), nullable=True, default='U/A')
    rating = db.Column(db.Float, default=8.5)
    is_upcoming = db.Column(db.Boolean, default=False)
    is_rerelease = db.Column(db.Boolean, default=False)
    release_date = db.Column(db.Date, nullable=True)
    moods_json = db.Column(db.Text, default='[]')
    tmdb_id = db.Column(db.Integer, nullable=True, index=True)
    cast_json = db.Column(db.Text, nullable=True, default=None)
    youtube_trailer_key = db.Column(db.String(20), nullable=True)
    trailer_video_path = db.Column(db.String(300), nullable=True)

    @property
    def cast_info(self):
        """Cast/crew info dict {'director': str|None, 'cast': [...]} or {} if unset."""
        try:
            data = json.loads(self.cast_json or 'null')
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data:
            if isinstance(data[0], dict) and 'cast' in data[0]:
                return data[0]
            return {
                'director': None,
                'cast': [{'name': c.get('name', ''),
                          'character': c.get('character') or c.get('role', ''),
                          'profile': c.get('profile')} for c in data if isinstance(c, dict)]
            }
        return {}

    def is_in_watchlist(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        return any(item.movie_id == self.id for item in user.watchlist_items)

    @property
    def display_rating(self):
        ratings = [r.rating for r in self.user_ratings]
        if ratings:
            return round(sum(ratings) / len(ratings), 1)
        return round(self.rating, 1) if getattr(self, 'rating', None) else 4.5

    def get_user_rating(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return None
        r = MovieRating.query.filter_by(user_id=user.id, movie_id=self.id).first()
        return r.rating if r else None

    @property
    def trailer_video_key(self):
        """Return the admin-selected trailer, or a YouTube trailer found through TMDb."""
        if self.trailer_video_path:
            return None
        if self.youtube_trailer_key:
            return self.youtube_trailer_key
        if self.tmdb_id:
            try:
                url = f"{TMDB_BASE_URL}/movie/{self.tmdb_id}/videos?api_key={TMDB_API_KEY}"
                resp = requests.get(url, timeout=3)
                if resp.status_code == 200:
                    results = resp.json().get('results', [])
                    for v in results:
                        if v.get('site') == 'YouTube' and v.get('type') in ('Trailer', 'Teaser'):
                            return v.get('key')
            except Exception:
                pass
        return None

    @property
    def moods(self):
        """Returns list of mood codes for this movie, falling back to smart keyword tagger."""
        try:
            custom = json.loads(self.moods_json or '[]')
            if custom:
                return custom
        except Exception:
            pass

        text_content = f"{self.title} {self.description}".lower()
        tags = set()

        if any(k in text_content for k in ['comedy', 'fun', 'laugh', 'hilarious', 'hero', 'entertainer', 'game', 'party', 'mass']):
            tags.add('FUN')
        if any(k in text_content for k in ['action', 'thriller', 'chase', 'war', 'police', 'fight', 'crime', 'hunt', 'stunt', 'blast', 'shadow', 'spy']):
            tags.add('THRILL')
        if any(k in text_content for k in ['drama', 'family', 'emotion', 'life', 'story', 'journey', 'struggle', 'father', 'mother', 'brother', 'truth']):
            tags.add('EMOTIONAL')
        if any(k in text_content for k in ['sci-fi', 'future', 'mystery', 'time', 'space', 'universe', 'secret', 'mind', 'alien', 'dimensions', 'kalki', 'devara', 'game changer']):
            tags.add('MIND_BENDING')
        if any(k in text_content for k in ['love', 'romance', 'heart', 'wedding', 'pair', 'romantic', 'song', 'sweet']):
            tags.add('ROMANCE')

        if not tags:
            tags.add('FUN')
            tags.add('THRILL')

        return list(tags)


class Watchlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'movie_id', name='_user_movie_uc'),)

    user = db.relationship('User', backref=db.backref('watchlist_items', lazy=True, cascade='all, delete-orphan'))
    movie = db.relationship('Movie', backref=db.backref('in_watchlists', lazy=True, cascade='all, delete-orphan'))


class MovieRating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    rating = db.Column(db.Float, nullable=False)
    review = db.Column(db.String(500), nullable=True)
    has_spoiler = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'movie_id', name='_user_movie_rating_uc'),)

    user = db.relationship('User', backref=db.backref('movie_ratings', lazy=True, cascade='all, delete-orphan'))
    movie = db.relationship('Movie', backref=db.backref('user_ratings', lazy=True, cascade='all, delete-orphan'))



class Theater(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    location = db.Column(db.String(200), nullable=True)
    city = db.Column(db.String(80), nullable=True, default='Visakhapatnam')
    address = db.Column(db.String(400), nullable=True)

    screens = db.relationship('Screen', backref='theater', lazy=True,
                              cascade='all, delete-orphan')

    @property
    def display_name(self):
        return f"{self.name} — {self.location}" if self.location else self.name


class Screen(db.Model):
    """One audi. Holds the actual seating arrangement of that hall."""
    id = db.Column(db.Integer, primary_key=True)
    theater_id = db.Column(db.Integer, db.ForeignKey('theater.id'), nullable=False)
    name = db.Column(db.String(80), nullable=False)              # "Screen 1"
    screen_type = db.Column(db.String(40), default='2D')         # 2D/3D/IMAX/Recliner
    layout_json = db.Column(db.Text, nullable=False, default='{}')

    @property
    def comfort_score(self):
        """Calculates authentic comfort index rating out of 5."""
        name_lower = (self.name + ' ' + (self.theater.name if self.theater else '')).lower()
        if 'insignia' in name_lower or 'vip' in name_lower or 'lounge' in name_lower:
            return 4.9
        if 'aaa' in name_lower or 'led' in name_lower or 'varun' in name_lower:
            return 4.8
        if 'imax' in name_lower or '70mm' in name_lower:
            return 4.7
        return 4.6

    @property
    def comfort_features(self):
        """Returns acoustic, visual, and seat ergonomics comfort badges."""
        name_lower = (self.name + ' ' + (self.theater.name if self.theater else '')).lower()
        if 'insignia' in name_lower or 'recliner' in name_lower or 'vip' in name_lower:
            return ['160° Motorized Recliners', 'Dolby Atmos 64-Channel', '4K Barco Laser', 'Dedicated Butler Service']
        elif 'aaa' in name_lower or 'led' in name_lower:
            return ['Q-Luxon 70ft Active LED', 'Dolby Atmos Sound', 'Premium Ergonomic Prime Seats', '42-inch Extra Legroom']
        elif 'varun' in name_lower:
            return ['RGB Laser 4K Projection', 'Dolby Atmos Sound', 'Sea Breeze Ambient Lounge', 'Luxury Prime Cushions']
        elif '70mm' in name_lower:
            return ['Giant 70MM Curved Screen', 'Acoustic Sound Array', 'Classic Balcony Experience']
        return ['Dolby 7.1 Surround', 'Plush Pushback Seating', 'Climate Controlled 21°C']

    @property
    def layout(self):
        try:
            return json.loads(self.layout_json or '{}')
        except json.JSONDecodeError:
            return {}

    @layout.setter
    def layout(self, value):
        self.layout_json = json.dumps(value, indent=2)

    @property
    def total_seats(self):
        return sl.count_seats(self.layout)

    @property
    def classes_summary(self):
        return ", ".join(c.get('name', '?') for c in self.layout.get('classes', []))

    @property
    def full_name(self):
        return f"{self.theater.name} · {self.name}"


class Showtime(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    screen_id = db.Column(db.Integer, db.ForeignKey('screen.id'), nullable=True)
    theater = db.Column(db.String(100), nullable=False)          # kept for old rows/templates
    show_date = db.Column(db.Date, nullable=False)
    show_time = db.Column(db.String(20), nullable=False)
    price_overrides_json = db.Column(db.Text, default='{}')      # {"RECLINER": 400}

    movie = db.relationship('Movie', backref=db.backref('showtimes', lazy=True))
    screen = db.relationship('Screen', backref=db.backref('showtimes', lazy=True))

    @property
    def price_overrides(self):
        try:
            return json.loads(self.price_overrides_json or '{}')
        except json.JSONDecodeError:
            return {}

    @property
    def screen_label(self):
        return self.screen.name if self.screen else '—'

    @property
    def layout(self):
        return self.screen.layout if self.screen else {}

    # ---- availability -------------------------------------------------
    def booked_seat_ids(self):
        return {b.seat_id for b in BookedSeat.query.filter_by(showtime_id=self.id).all()}

    def held_seat_ids(self, exclude_token=None):
        now = datetime.utcnow()
        held = set()
        q = SeatLock.query.filter(SeatLock.showtime_id == self.id,
                                  SeatLock.expires_at > now)
        for lk in q.all():
            if exclude_token and lk.token == exclude_token:
                continue
            held.update(lk.seat_list)
        return held

    @property
    def seats_left(self):
        taken = self.booked_seat_ids() | self.held_seat_ids()
        return max(0, sl.count_seats(self.layout) - len(taken))

    @property
    def show_datetime(self):
        """Parse show_date + show_time into a datetime object. Supports HH:MM and H:MM AM/PM formats."""
        for fmt in ('%H:%M', '%I:%M %p', '%I:%M%p'):
            try:
                t = datetime.strptime(self.show_time.strip(), fmt).time()
                return datetime.combine(self.show_date, t)
            except ValueError:
                continue
        return None

    @property
    def is_past(self):
        dt = self.show_datetime
        if dt:
            # consider past only after movie ends (show_datetime + duration)
            end_dt = dt + timedelta(minutes=(self.movie.duration if self.movie else 0))
            return datetime.now() > end_dt
        return self.show_date < date.today()

    @property
    def status(self):
        """Returns 'upcoming', 'live', or 'ended' based on current time."""
        dt = self.show_datetime
        if not dt:
            return 'upcoming'
        now = datetime.now()
        duration = self.movie.duration if self.movie else 0
        end_dt = dt + timedelta(minutes=duration)
        if now < dt:
            return 'upcoming'
        elif now <= end_dt:
            return 'live'
        return 'ended'

    @property
    def dynamic_pricing_info(self):
        """
        Calculates real-time surge or early-bird pricing adjustments based on occupancy and show time.
        """
        total = sl.count_seats(self.layout) or 1
        booked_count = len(self.booked_seat_ids())
        occupancy_pct = (booked_count / max(1, total)) * 100.0

        today = date.today()
        days_ahead = (self.show_date - today).days

        if occupancy_pct >= 60.0:
            return {
                "factor": 1.15,
                "badge": "🔥 High Demand Surge (+15%)",
                "type": "SURGE",
                "color": "rose",
                "discount_pct": 15
            }
        elif days_ahead >= 2:
            return {
                "factor": 0.90,
                "badge": "⚡ Early Bird Deal (-10%)",
                "type": "EARLY_BIRD",
                "color": "emerald",
                "discount_pct": -10
            }
        elif occupancy_pct < 30.0 and days_ahead == 0:
            return {
                "factor": 0.80,
                "badge": "🎉 Last-Minute Flash Deal (-20%)",
                "type": "FLASH",
                "color": "amber",
                "discount_pct": -20
            }
        return {
            "factor": 1.0,
            "badge": None,
            "type": "STANDARD",
            "color": "slate",
            "discount_pct": 0
        }


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(20), unique=True, nullable=False,
                          default=lambda: 'CW' + secrets.token_hex(4).upper())
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    seats = db.Column(db.String(200), nullable=False)
    seat_meta_json = db.Column(db.Text, default='[]')

    ticket_amount = db.Column(db.Float, default=0)     # seat prices only
    convenience_fee = db.Column(db.Float, default=0)
    gst = db.Column(db.Float, default=0)
    total_amount = db.Column(db.Float, nullable=False, default=0)   # charged amount

    is_split_pay = db.Column(db.Boolean, default=False)
    split_token = db.Column(db.String(64), unique=True, nullable=True)
    snacks_json = db.Column(db.Text, default='[]')
    points_redeemed = db.Column(db.Integer, default=0)

    # PENDING -> PAID | FAILED | CANCELLED | EXPIRED
    status = db.Column(db.String(20), default='PENDING', nullable=False)
    lock_token = db.Column(db.String(40), nullable=True)
    booked_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)
    ticket_email_sent_at = db.Column(db.DateTime, nullable=True)
    ticket_email_error = db.Column(db.String(300), nullable=True)
    expires_at = db.Column(db.DateTime,
                           default=lambda: datetime.utcnow() + timedelta(minutes=SEAT_LOCK_MINUTES))

    user = db.relationship('User', backref=db.backref('bookings', lazy=True))
    showtime = db.relationship('Showtime', backref=db.backref('bookings', lazy=True))
    payment = db.relationship('Payment', backref='booking', uselist=False,
                              cascade='all, delete-orphan')

    @property
    def per_person_amount(self):
        count = max(1, len(self.seat_list))
        return round(self.total_amount / count, 2)

    @property
    def snacks_list(self):
        try:
            return json.loads(self.snacks_json or '[]')
        except json.JSONDecodeError:
            return []

    @property
    def seat_list(self):
        return [s for s in (self.seats or '').split(',') if s]

    @property
    def seat_meta(self):
        try:
            return json.loads(self.seat_meta_json or '[]')
        except json.JSONDecodeError:
            return []

    @property
    def seconds_left(self):
        return max(0, int((self.expires_at - datetime.utcnow()).total_seconds()))

    @property
    def is_expired(self):
        return self.status == 'PENDING' and self.expires_at < datetime.utcnow()


class BookedSeat(db.Model):
    """Confirmed seats only. The unique constraint is our double-booking guard."""
    id = db.Column(db.Integer, primary_key=True)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    seat_id = db.Column(db.String(10), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('showtime_id', 'seat_id', name='uq_showtime_seat'),
    )


class SeatLock(db.Model):
    """Temporary hold so two users cannot pay for the same seat."""
    id = db.Column(db.Integer, primary_key=True)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    token = db.Column(db.String(40), unique=True, nullable=False,
                      default=lambda: secrets.token_hex(16))
    seats = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime,
                           default=lambda: datetime.utcnow() + timedelta(minutes=SEAT_LOCK_MINUTES))

    @property
    def seat_list(self):
        return [s for s in (self.seats or '').split(',') if s]


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    gateway = db.Column(db.String(30), default='mock')      # razorpay | mock | wallet
    order_id = db.Column(db.String(80), nullable=True)
    payment_id = db.Column(db.String(80), nullable=True)
    signature = db.Column(db.String(200), nullable=True)
    method = db.Column(db.String(40), nullable=True)        # upi / card / netbanking / wallet
    amount = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(10), default='INR')
    status = db.Column(db.String(20), default='CREATED')    # CREATED|CAPTURED|FAILED|REFUNDED
    error_message = db.Column(db.String(300), nullable=True)
    raw_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SplitContribution(db.Model):
    """One sandbox share from a participant toward a multi-seat booking."""
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    share_index = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default='OPEN')
    gateway = db.Column(db.String(30), nullable=True)
    method = db.Column(db.String(30), nullable=True)
    order_id = db.Column(db.String(80), nullable=True)
    payment_id = db.Column(db.String(80), nullable=True)
    signature = db.Column(db.String(200), nullable=True)
    error_message = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    booking = db.relationship('Booking', backref=db.backref('split_contributions', lazy=True))
    user = db.relationship('User')

    __table_args__ = (
        db.UniqueConstraint('booking_id', 'share_index', name='uq_split_booking_share'),
        db.UniqueConstraint('booking_id', 'user_id', name='uq_split_booking_user'),
    )


class Wallet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    balance = db.Column(db.Float, default=0)

    user = db.relationship('User', backref=db.backref('wallet', uselist=False))


class WalletTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey('wallet.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(20), nullable=False)   # RECHARGE / PAYMENT / REFUND
    description = db.Column(db.String(200), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    wallet = db.relationship('Wallet', backref=db.backref('transactions', lazy=True))


class RechargeRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='PENDING')   # PENDING/APPROVED/REJECTED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('recharge_requests', lazy=True))


class PartySession(db.Model):
    """Watch Together party session for real-time squad seat syncing."""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False, default=lambda: secrets.token_hex(3).upper())
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    host_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='ACTIVE')

    showtime = db.relationship('Showtime', backref=db.backref('parties', lazy=True))


class PartyMember(db.Model):
    """Individual participant in a Watch Together party."""
    id = db.Column(db.Integer, primary_key=True)
    party_id = db.Column(db.Integer, db.ForeignKey('party_session.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user_name = db.Column(db.String(80), nullable=False)
    avatar_color = db.Column(db.String(20), default='#FF2E63')
    selected_seats = db.Column(db.String(200), default='')
    last_ping = db.Column(db.DateTime, default=datetime.utcnow)

    party = db.relationship('PartySession', backref=db.backref('members', lazy=True, cascade='all, delete-orphan'))


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ====================== HELPERS ======================

def is_valid_email(email):
    return re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email) is not None


def safe_local_redirect(target):
    """Return a same-site redirect target, or None for external/unsafe URLs."""
    if not target:
        return None
    if any(ord(char) < 32 for char in target) or '\\' in target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith('/') or target.startswith('//'):
        return None
    return target


def admin_required():
    """Returns a redirect response if the user is not an admin, else None."""
    if not current_user.is_authenticated or not current_user.is_admin:
        flash("Access denied")
        return redirect(url_for('home'))
    return None


def parse_youtube_video_key(value):
    """Accept a YouTube video URL or 11-character video ID; reject other values."""
    value = (value or '').strip()
    if not value:
        return ''
    candidate = value
    if '://' in value:
        parsed = urlparse(value)
        host = (parsed.hostname or '').lower()
        if host in ('youtu.be', 'www.youtu.be'):
            candidate = parsed.path.strip('/').split('/')[0]
        elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'):
            if parsed.path == '/watch':
                candidate = parse_qs(parsed.query).get('v', [''])[0]
            else:
                parts = [part for part in parsed.path.split('/') if part]
                candidate = parts[1] if len(parts) > 1 and parts[0] in ('embed', 'shorts', 'live') else ''
        else:
            return None
    return candidate if re.fullmatch(r'[A-Za-z0-9_-]{11}', candidate) else None


def save_trailer_upload(upload):
    """Save an uploaded MP4/WebM trailer under a random safe name in static files."""
    if not upload or not upload.filename:
        return None
    extension = os.path.splitext(secure_filename(upload.filename))[1].lower()
    if extension not in {'.mp4', '.webm'}:
        raise ValueError('Trailer uploads must be MP4 or WebM video files.')
    relative_path = os.path.join('uploads', 'trailers', f'{secrets.token_hex(16)}{extension}')
    absolute_path = os.path.join(app.static_folder, relative_path)
    os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
    upload.save(absolute_path)
    return relative_path.replace(os.sep, '/')


def create_wallet(user, balance=WELCOME_WALLET_BALANCE):
    """New wallet with the signup bonus already credited."""
    wallet = Wallet(user_id=user.id, balance=balance)
    db.session.add(wallet)
    db.session.commit()
    if balance:
        db.session.add(WalletTransaction(wallet_id=wallet.id, amount=balance,
                                         type='RECHARGE',
                                         description='Welcome bonus'))
        db.session.commit()
    return wallet


def get_wallet(user):
    wallet = Wallet.query.filter_by(user_id=user.id).first()
    if not wallet:
        wallet = create_wallet(user)
    return wallet


def smtp_is_configured():
    return bool(app.config['SMTP_HOST'] and app.config['SMTP_FROM_EMAIL'])


def send_email(message):
    """Send mail through the configured SMTP relay using TLS where available."""
    if not smtp_is_configured():
        raise RuntimeError('Email delivery is not configured. Set SMTP_HOST and SMTP_FROM_EMAIL.')
    context = ssl.create_default_context()
    if app.config['SMTP_USE_SSL']:
        with smtplib.SMTP_SSL(app.config['SMTP_HOST'], app.config['SMTP_PORT'],
                              timeout=15, context=context) as server:
            if app.config['SMTP_USERNAME']:
                server.login(app.config['SMTP_USERNAME'], app.config['SMTP_PASSWORD'])
            server.send_message(message)
    else:
        with smtplib.SMTP(app.config['SMTP_HOST'], app.config['SMTP_PORT'], timeout=15) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            if app.config['SMTP_USERNAME']:
                server.login(app.config['SMTP_USERNAME'], app.config['SMTP_PASSWORD'])
            server.send_message(message)


def _otp_digest(code):
    return hmac.new(app.config['SECRET_KEY'].encode(), code.encode(), hashlib.sha256).hexdigest()


def send_registration_otp(user):
    code = f'{secrets.randbelow(1_000_000):06d}'
    user.email_otp_hash = _otp_digest(code)
    user.email_otp_expires_at = datetime.utcnow() + timedelta(minutes=10)
    user.email_otp_sent_at = datetime.utcnow()
    user.email_otp_attempts = 0
    db.session.commit()

    message = EmailMessage()
    message['Subject'] = 'Your MD CineWave verification code'
    message['From'] = app.config['SMTP_FROM_EMAIL']
    message['To'] = user.email
    message.set_content(
        f'Hello {user.username},\n\nYour email verification code is {code}. '
        'It expires in 10 minutes. If you did not create this account, ignore this email.'
    )
    send_email(message)


def dispatch_ticket_delivery(booking):
    """Email a confirmed ticket and QR pass; return False without undoing payment on mail failure."""
    user = booking.user
    if not user or not user.email:
        booking.ticket_email_error = 'The account has no email address.'
        db.session.commit()
        return False

    showtime = booking.showtime
    movie_title = showtime.movie.title
    date_text = showtime.show_date.strftime('%a, %d %b %Y')
    qr_payload = (f'CINEWAVE|{booking.reference}|{movie_title}|{showtime.theater}|'
                  f'{showtime.show_date}|{showtime.show_time}|{booking.seats}')
    message = EmailMessage()
    message['Subject'] = f'Your MD CineWave ticket: {movie_title} ({booking.reference})'
    message['From'] = app.config['SMTP_FROM_EMAIL']
    message['To'] = user.email
    message.set_content(
        f'Your booking is confirmed.\n\nMovie: {movie_title}\nTheatre: {showtime.theater}\n'
        f'Screen: {showtime.screen_label}\nDate: {date_text}\nTime: {showtime.show_time}\n'
        f'Seats: {booking.seats}\nBooking reference: {booking.reference}\n\n'
        'The attached QR code is your entry pass. Please show it at the theatre.'
    )
    safe_title = html.escape(movie_title)
    message.add_alternative(
        f'<html><body><h2>Booking confirmed</h2><p><b>{safe_title}</b></p>'
        f'<p>{html.escape(showtime.theater)} · {html.escape(showtime.screen_label)}</p>'
        f'<p>{html.escape(date_text)} at {html.escape(showtime.show_time)}</p>'
        f'<p>Seats: <b>{html.escape(booking.seats)}</b></p>'
        f'<p>Reference: <b>{html.escape(booking.reference)}</b></p>'
        '<p>Your QR entry pass is attached to this email.</p></body></html>', subtype='html')
    try:
        import qrcode
        qr_buffer = io.BytesIO()
        qrcode.make(qr_payload).save(qr_buffer, format='PNG')
        message.add_attachment(qr_buffer.getvalue(), maintype='image', subtype='png',
                               filename=f'{booking.reference}-ticket-qr.png')
        send_email(message)
    except Exception:
        app.logger.exception('Ticket email delivery failed for booking %s', booking.reference)
        booking.ticket_email_error = 'Ticket email could not be delivered. Please try resending.'
        db.session.commit()
        return False

    booking.ticket_email_sent_at = datetime.utcnow()
    booking.ticket_email_error = None
    db.session.commit()
    return True


def purge_expired_holds():
    """Release stale locks and expire unpaid bookings. Cheap, safe to call often."""
    now = datetime.utcnow()
    stale = SeatLock.query.filter(SeatLock.expires_at <= now).all()
    for lk in stale:
        db.session.delete(lk)

    dead = Booking.query.filter(Booking.status == 'PENDING',
                                Booking.expires_at <= now).all()
    for b in dead:
        b.status = 'EXPIRED'
    if stale or dead:
        db.session.commit()


def price_seats(showtime, seat_ids):
    """Return (ticket_total, [{'id','class','price'}...]) including dynamic surge/discount."""
    layout = showtime.layout
    dyn = showtime.dynamic_pricing_info
    effective_overrides = {}
    base_overrides = showtime.price_overrides
    for cls in layout.get("classes", []):
        code = cls.get("code", "STD")
        base_p = float(base_overrides.get(code, cls.get("price", 0)))
        effective_overrides[code] = round(base_p * dyn['factor'], 2)

    prices = sl.seat_price_map(layout, effective_overrides)
    classes = sl.seat_class_map(layout)
    meta = [{'id': s, 'class': classes.get(s, 'Standard'),
             'price': float(prices.get(s, 0))} for s in seat_ids]
    return round(sum(m['price'] for m in meta), 2), meta


def release_booking(booking, status='CANCELLED'):
    """Free the held seats for a booking that will not be paid."""
    if booking.lock_token:
        lock = SeatLock.query.filter_by(token=booking.lock_token).first()
        if lock:
            db.session.delete(lock)
    # Split payments are sandbox-only. Mark any captured test shares as returned
    # so an expired or cancelled group cannot leave a stale paid indicator.
    for contribution in SplitContribution.query.filter_by(booking_id=booking.id).all():
        if contribution.status == 'PAID':
            contribution.status = 'REFUNDED'
        elif contribution.status == 'CREATED':
            contribution.status = 'OPEN'
            contribution.user_id = None
    booking.status = status
    db.session.commit()


def commit_seats(booking):
    """
    Final, atomic step after a successful payment: write the seats into
    BookedSeat. The unique(showtime_id, seat_id) constraint means that if
    someone beat us to a seat, this raises and we can refund instead of
    double-selling.
    """
    for seat in booking.seat_list:
        db.session.add(BookedSeat(showtime_id=booking.showtime_id,
                                  seat_id=seat, booking_id=booking.id))
    db.session.flush()


def finalise_paid_booking(booking, payment):
    """Commit seats, mark paid, drop the lock. Returns (ok, message)."""
    try:
        commit_seats(booking)
        booking.status = 'PAID'
        booking.paid_at = datetime.utcnow()
        payment.status = 'CAPTURED'
        if booking.lock_token:
            lock = SeatLock.query.filter_by(token=booking.lock_token).first()
            if lock:
                db.session.delete(lock)

        # Deduct redeemed points first
        if booking.points_redeemed and booking.points_redeemed > 0:
            booking.user.points = max(0, (booking.user.points or 0) - booking.points_redeemed)

        # CinePass points reward: 10 points per ₹100 spent (20 points/₹100 for Rewatch Champion bookings!)
        is_rewatch = False
        if booking.user and booking.showtime and booking.showtime.movie:
            prev_cnt = (Booking.query.filter_by(user_id=booking.user_id, status='PAID')
                        .join(Showtime)
                        .filter(Showtime.movie_id == booking.showtime.movie_id, Booking.id != booking.id)
                        .count())
            if prev_cnt > 0:
                is_rewatch = True

        pts_multiplier = 2 if is_rewatch else 1
        earned_pts = int((booking.total_amount / 10) * pts_multiplier)
        if earned_pts > 0:
            booking.user.points = (booking.user.points or 0) + earned_pts
        db.session.commit()
        # Dispatch digital receipt / e-ticket
        dispatch_ticket_delivery(booking)
        msg = "Payment successful" + (" 🎉 (Rewatch Bonus: 2X CinePass Points Earned!)" if is_rewatch else "")
        return True, msg
    except IntegrityError:
        db.session.rollback()
        booking.status = 'FAILED'
        payment.status = 'REFUNDED'
        payment.error_message = 'Seat taken before capture - amount refunded'
        # money back: wallet payments are returned instantly
        if payment.method == 'wallet':
            wallet = get_wallet(booking.user)
            wallet.balance += booking.total_amount
            db.session.add(WalletTransaction(wallet_id=wallet.id,
                                             amount=booking.total_amount,
                                             type='REFUND',
                                             description=f'Refund for {booking.reference}'))
        if payment.method == 'split':
            for contribution in SplitContribution.query.filter_by(booking_id=booking.id).all():
                if contribution.status == 'PAID':
                    contribution.status = 'REFUNDED'
            if booking.lock_token:
                lock = SeatLock.query.filter_by(token=booking.lock_token).first()
                if lock:
                    db.session.delete(lock)
        db.session.commit()
        return False, ("Someone completed payment for one of those seats first. "
                       "Your money has been refunded - please pick different seats.")


@app.context_processor
def inject_globals():
    """Available in every template."""
    wallet_balance = None
    user_points = 0
    if current_user.is_authenticated:
        w = Wallet.query.filter_by(user_id=current_user.id).first()
        wallet_balance = w.balance if w else 0
        user_points = current_user.points or 0
    return {'wallet_balance': wallet_balance,
            'user_points': user_points,
            'gateway_live': payments.is_live_gateway(),
            'startup_id': app.config['STARTUP_ID'],
            'today': date.today()}


# ====================== PUBLIC ROUTES ======================

@app.route('/')
def home():
    # Now Showing
    now_showing_releases = Movie.query.filter(
        (Movie.is_upcoming.is_(False)) | (Movie.is_upcoming.is_(None)),
        (Movie.is_rerelease.is_(False)) | (Movie.is_rerelease.is_(None))
    ).order_by(Movie.id.desc()).all()
    
    now_showing_rereleases = Movie.query.filter(
        (Movie.is_upcoming.is_(False)) | (Movie.is_upcoming.is_(None)),
        Movie.is_rerelease.is_(True)
    ).order_by(Movie.id.desc()).all()

    # Coming Soon
    coming_soon_releases = Movie.query.filter(
        Movie.is_upcoming.is_(True),
        (Movie.is_rerelease.is_(False)) | (Movie.is_rerelease.is_(None))
    ).order_by(Movie.release_date.asc(), Movie.id.desc()).all()

    coming_soon_rereleases = Movie.query.filter(
        Movie.is_upcoming.is_(True),
        Movie.is_rerelease.is_(True)
    ).order_by(Movie.release_date.asc(), Movie.id.desc()).all()

    return render_template(
        'index.html',
        now_showing_releases=now_showing_releases,
        now_showing_rereleases=now_showing_rereleases,
        coming_soon_releases=coming_soon_releases,
        coming_soon_rereleases=coming_soon_rereleases,
        # backward compat counts
        total_now_showing=len(now_showing_releases) + len(now_showing_rereleases),
        total_coming_soon=len(coming_soon_releases) + len(coming_soon_rereleases)
    )



@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            get_wallet(user)
            return redirect(safe_local_redirect(request.args.get('next')) or url_for('home'))
        flash('Invalid username or password')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        password = request.form['password']

        if not re.fullmatch(r'[A-Za-z0-9_.-]{3,30}', username):
            flash('Username must be 3–30 characters and use only letters, numbers, dots, underscores, or hyphens.')
            return redirect(url_for('register'))
        if not email or not is_valid_email(email):
            flash("Please enter a valid email address.")
            return redirect(url_for('register'))
        if len(password) < 6 or len(password) > 256:
            flash('Use a password between 6 and 256 characters.')
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash('Username already exists!')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists!')
            return redirect(url_for('register'))

        user = User(username=username, email=email, email_verified=True, phone=phone or None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        create_wallet(user)
        login_user(user)
        flash('Your account is ready. Welcome to MD CineWave!')
        return redirect(url_for('home'))
    return render_template('register.html')


@app.route('/verify-email', methods=['GET', 'POST'])
def verify_email():
    user_id = session.get('pending_email_verification_user_id')
    user = db.session.get(User, user_id) if user_id else None
    if not user:
        session.pop('pending_email_verification_user_id', None)
        return redirect(url_for('register'))
    if user.email_verified:
        session.pop('pending_email_verification_user_id', None)
        return redirect(url_for('login'))

    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        now = datetime.utcnow()
        if user.email_otp_attempts >= 5:
            flash('Too many incorrect codes. Request a new code after the resend cooldown.')
        elif (not user.email_otp_hash or not user.email_otp_expires_at
              or user.email_otp_expires_at <= now):
            flash('Your code has expired. Request a new one.')
        else:
            user.email_otp_attempts += 1
            expected = _otp_digest(code) if re.fullmatch(r'\d{6}', code) else ''
            if hmac.compare_digest(user.email_otp_hash, expected):
                user.email_verified = True
                user.email_otp_hash = None
                user.email_otp_expires_at = None
                user.email_otp_attempts = 0
                db.session.commit()
                create_wallet(user)
                session.pop('pending_email_verification_user_id', None)
                flash('Email verified. Your account is ready; please sign in.')
                return redirect(url_for('login'))
            db.session.commit()
            flash('That code is incorrect. Please try again.')
    return render_template('verify_email.html', email=user.email)


@app.route('/verify-email/resend', methods=['POST'])
def resend_email_otp():
    user_id = session.get('pending_email_verification_user_id')
    user = db.session.get(User, user_id) if user_id else None
    if not user or user.email_verified:
        session.pop('pending_email_verification_user_id', None)
        return redirect(url_for('register'))
    if user.email_otp_sent_at and datetime.utcnow() - user.email_otp_sent_at < timedelta(seconds=60):
        flash('Please wait one minute before requesting another code.')
    else:
        try:
            send_registration_otp(user)
            flash('A new verification code has been sent. It expires in 10 minutes.')
        except Exception:
            app.logger.exception('Registration OTP resend failed for user %s', user.id)
            flash('We could not send the email right now. Please try again later.')
    return redirect(url_for('verify_email'))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


@app.route('/movie/<int:movie_id>')
def movie_detail(movie_id):
    purge_expired_holds()
    movie = Movie.query.get_or_404(movie_id)
    all_shows = (Showtime.query.filter_by(movie_id=movie_id)
                 .order_by(Showtime.show_date, Showtime.id).all())

    # Only keep shows that have NOT ended yet (upcoming + live)
    shows = [s for s in all_shows if s.status != 'ended']

    # group by date -> theatre so it reads like a real booking page
    grouped = {}
    for s in shows:
        grouped.setdefault(s.show_date, {}).setdefault(s.theater, []).append(s)

    return render_template('movie.html', movie=movie, showtimes=shows,
                           grouped=grouped)


# ====================== SEAT SELECTION & HOLD ======================

@app.route('/book/<int:showtime_id>', methods=['GET', 'POST'])
@login_required
def book(showtime_id):
    purge_expired_holds()
    showtime = Showtime.query.get_or_404(showtime_id)
    movie = showtime.movie

    if not showtime.screen:
        flash("This showtime has no screen assigned. Ask an admin to fix it.")
        return redirect(url_for('movie_detail', movie_id=movie.id))

    if showtime.status == 'ended':
        flash("⛔ This show has already ended. Please choose another showtime.")
        return redirect(url_for('movie_detail', movie_id=movie.id))

    layout = showtime.layout
    booked = showtime.booked_seat_ids()
    held = showtime.held_seat_ids()
    dyn = showtime.dynamic_pricing_info

    if request.method == 'POST':
        raw = request.form.get('selected_seats', '')
        seats_list = [s.strip().upper() for s in raw.split(',') if s.strip()]

        ok, msg = sl.validate_seats(layout, seats_list)
        if not ok:
            flash(msg)
            return redirect(url_for('book', showtime_id=showtime_id))

        clash = sorted(set(seats_list) & (booked | held))
        if clash:
            flash(f"Seat(s) {', '.join(clash)} were just taken. Please choose again.")
            return redirect(url_for('book', showtime_id=showtime_id))

        # ---- hold the seats, then create a PENDING booking ----
        ticket_amount, meta = price_seats(showtime, seats_list)
        amounts = payments.compute_amounts(ticket_amount, len(seats_list))

        lock = SeatLock(showtime_id=showtime.id, user_id=current_user.id,
                        seats=",".join(seats_list))
        db.session.add(lock)
        db.session.flush()

        booking = Booking(user_id=current_user.id, showtime_id=showtime.id,
                          seats=",".join(seats_list),
                          seat_meta_json=json.dumps(meta),
                          ticket_amount=amounts['ticket_amount'],
                          convenience_fee=amounts['convenience_fee'],
                          gst=amounts['gst'],
                          total_amount=amounts['total'],
                          status='PENDING', lock_token=lock.token,
                          expires_at=lock.expires_at)
        db.session.add(booking)
        db.session.commit()

        return redirect(url_for('checkout', reference=booking.reference))

    effective_overrides = {}
    base_overrides = showtime.price_overrides
    for cls in layout.get("classes", []):
        code = cls.get("code", "STD")
        base_p = float(base_overrides.get(code, cls.get("price", 0)))
        effective_overrides[code] = round(base_p * dyn['factor'], 2)

    grid = sl.build_layout(layout, booked=booked, held=held,
                           price_overrides=effective_overrides)
    party_code = request.args.get('party', '').strip().upper()
    return render_template('book.html', movie=movie, showtime=showtime,
                           screen=showtime.screen, grid=grid,
                           max_seats=sl.MAX_SEATS_PER_BOOKING,
                           stats=sl.availability(layout, booked | held),
                           dynamic_info=dyn, party_code=party_code)


@app.route('/book/<int:showtime_id>/vr-preview')
@login_required
def vr_seat_preview(showtime_id):
    """Render the immersive seat preview from this show's real screen layout."""
    purge_expired_holds()
    showtime = Showtime.query.get_or_404(showtime_id)
    if not showtime.screen:
        abort(404)

    layout = showtime.layout or {}
    unavailable = showtime.booked_seat_ids() | showtime.held_seat_ids()
    dynamic = showtime.dynamic_pricing_info
    row_defs = []
    prices = []
    for cls in layout.get('classes', []):
        code = cls.get('code', 'STD')
        base_price = float(showtime.price_overrides.get(code, cls.get('price', 0)))
        price = round(base_price * dynamic['factor'], 2)
        prices.append(price)
        for row in cls.get('rows', []):
            start = int(row.get('start', 1))
            count = max(0, int(row.get('count', 0)))
            blocked = set(row.get('blocked') or [])
            seats = {}
            for number in range(start, start + count):
                seat_id = f"{row['label']}{number}"
                if seat_id in blocked:
                    continue
                seats[seat_id] = 'unavailable' if seat_id in unavailable else 'available'
            row_defs.append({
                'label': row['label'], 'start': start, 'count': count,
                'aislesAfter': [int(a) for a in row.get('aisles_after', [])],
                'blocked': list(blocked), 'offset': int(row.get('offset', 0)),
                'seatSpan': max(1, int(row.get('seat_span', 1))),
                'classCode': code, 'className': cls.get('name', 'Standard'),
                'price': price, 'seats': seats,
            })

    if not row_defs:
        abort(404)
    max_seat = max((row['start'] + row['count'] - 1 for row in row_defs), default=1)
    screen = layout.get('screen') or {}
    screen_type = (showtime.screen.screen_type or '').upper()
    fallback_aspect = 1.43 if 'IMAX' in screen_type else (2.2 if '70MM' in screen_type else 1.85)
    # Seed layouts contain seat-by-seat arrangements, but most do not include
    # surveyed auditorium dimensions. Keep supplied measurements and estimate
    # screen width proportionally when a layout has no measurement.
    widest_row_seats = max((row['count'] * row['seatSpan'] for row in row_defs), default=0)
    try:
        width = float(screen.get('width_m') or max(8.0, min(24.0, widest_row_seats * 0.62)))
    except (TypeError, ValueError):
        width = max(8.0, min(24.0, widest_row_seats * 0.62))
    try:
        aspect = float(screen.get('aspect_ratio') or fallback_aspect)
        if aspect <= 0:
            aspect = fallback_aspect
    except (TypeError, ValueError):
        aspect = fallback_aspect
    try:
        height = float(screen.get('height_m') or (width / aspect))
    except (TypeError, ValueError):
        height = width / aspect
    all_seat_ids = [seat_id for row in row_defs for seat_id in row['seats']]
    available_ids = [seat_id for row in row_defs for seat_id, state in row['seats'].items() if state == 'available']
    middle_row = row_defs[len(row_defs) // 2]
    middle_seat = middle_row['start'] + max(0, middle_row['count'] - 1) // 2
    preferred_id = f"{middle_row['label']}{middle_seat}"
    default_seat = preferred_id if preferred_id in available_ids else (available_ids[0] if available_ids else (all_seat_ids[0] if all_seat_ids else ''))

    preview = {
        'name': f'{showtime.theater} · {showtime.screen.name}',
        'movieTitle': showtime.movie.title,
        'sub': f'{showtime.screen.screen_type} · {len(row_defs)} rows · {sum(len(r["seats"]) for r in row_defs)} seats',
        'rows': [row['label'] for row in row_defs], 'rowDefs': row_defs,
        'cols': max_seat, 'aislesAfter': [], 'vipRows': [], 'reclinerRows': [],
        'screenWidth': width, 'screenHeight': height,
        'visual': layout.get('visual') or {
            'seat_color': '#51252d', 'wall_color': '#11151d',
            'trim_color': '#c9a84c', 'seat_style': 'standard',
            'verified_at_theater_level': False,
        },
        'rowSpacing': max(1.6, min(3.8, float(screen.get('row_spacing_m', 2.45)))),
        'screenCurve': max(0, min(0.6, float(screen.get('curve', 0.3)))),
        'stadiumSlope': max(0.25, min(1.2, float(screen.get('stadium_slope', 0.55)))),
        'prices': {'standard': min(prices or [0]), 'vip': max(prices or [0]), 'recliner': max(prices or [0])},
        'defaultSeat': default_seat,
    }
    return render_template('vr_seat_preview.html', showtime=showtime,
                           screen_type=showtime.screen.screen_type or 'Cinema screen',
                           movie=showtime.movie, preview=preview,
                           embedded=request.args.get('embed') == '1')


@app.route('/api/movies/by-mood/<mood_code>')
def movies_by_mood(mood_code):
    """Returns list of movies matching a specified mood code."""
    all_movies = Movie.query.all()
    if mood_code.upper() == 'ALL':
        matched = all_movies
    else:
        matched = [m for m in all_movies if mood_code.upper() in m.moods]
    return jsonify({
        'count': len(matched),
        'movies': [{
            'id': m.id,
            'title': m.title,
            'poster': m.poster,
            'duration': m.duration,
            'language': m.language,
            'certificate': m.certificate,
            'is_upcoming': m.is_upcoming,
            'release_date': m.release_date.strftime('%d %b %Y') if m.release_date else None,
            'moods': m.moods
        } for m in matched]
    })


@app.route('/api/party/create/<int:showtime_id>', methods=['POST'])
@login_required
def party_create(showtime_id):
    """Create a Watch Together party room for a showtime."""
    showtime = Showtime.query.get_or_404(showtime_id)
    party = PartySession(showtime_id=showtime.id, host_id=current_user.id)
    db.session.add(party)
    db.session.commit()

    # Host joins automatically
    member = PartyMember(party_id=party.id, user_id=current_user.id,
                         user_name=current_user.username, avatar_color='#FF2E63')
    db.session.add(member)
    db.session.commit()

    return jsonify({
        'success': True,
        'party_code': party.code,
        'party_id': party.id,
        'join_url': url_for('book', showtime_id=showtime.id, party=party.code, _external=True)
    })


@app.route('/api/party/<party_code>/sync', methods=['POST'])
def party_sync(party_code):
    """Real-time sync endpoint: updates current user seats and returns all squad members' picks."""
    party = PartySession.query.filter_by(code=party_code.upper()).first_or_404()
    data = request.get_json() or {}

    user_name = data.get('user_name', 'Guest')
    selected = data.get('selected_seats', '')
    avatar_color = data.get('avatar_color', '#3B82F6')

    uid = current_user.id if current_user.is_authenticated else None

    # Find or create member
    member = None
    if uid:
        member = PartyMember.query.filter_by(party_id=party.id, user_id=uid).first()
    if not member and user_name:
        member = PartyMember.query.filter_by(party_id=party.id, user_name=user_name).first()

    if not member:
        member = PartyMember(party_id=party.id, user_id=uid, user_name=user_name,
                             avatar_color=avatar_color, selected_seats=selected,
                             last_ping=datetime.utcnow())
        db.session.add(member)
    else:
        member.user_name = user_name
        member.selected_seats = selected
        member.avatar_color = avatar_color
        member.last_ping = datetime.utcnow()

    db.session.commit()

    # Fetch all active members in last 60 seconds
    cutoff = datetime.utcnow() - timedelta(seconds=60)
    active_members = PartyMember.query.filter(PartyMember.party_id == party.id,
                                             PartyMember.last_ping >= cutoff).all()

    members_out = []
    squad_seats = {}
    for m in active_members:
        seats = [s.strip() for s in (m.selected_seats or '').split(',') if s.strip()]
        is_me = (m.user_id == uid) if uid else (m.user_name == user_name)
        members_out.append({
            'user_name': m.user_name,
            'color': m.avatar_color,
            'seats': seats,
            'is_me': is_me
        })
        for st in seats:
            if not is_me:
                squad_seats[st] = {'user_name': m.user_name, 'color': m.avatar_color}

    return jsonify({
        'party_code': party.code,
        'members': members_out,
        'squad_seats': squad_seats
    })



@app.route('/api/showtime/<int:showtime_id>/availability')
@login_required
def seat_availability(showtime_id):
    """Polled by the seat page so seats grey out live while you are choosing."""
    purge_expired_holds()
    showtime = Showtime.query.get_or_404(showtime_id)
    return jsonify({'booked': sorted(showtime.booked_seat_ids()),
                    'held': sorted(showtime.held_seat_ids())})


@app.route('/api/showtime/<int:showtime_id>/live-info')
def showtime_live_info(showtime_id):
    """Public endpoint: returns real-time seats left, show status, and countdown seconds."""
    purge_expired_holds()
    showtime = Showtime.query.get_or_404(showtime_id)
    dt = showtime.show_datetime
    seconds_to_start = int((dt - datetime.now()).total_seconds()) if dt else 0
    return jsonify({
        'seats_left': showtime.seats_left,
        'total_seats': sl.count_seats(showtime.layout),
        'status': showtime.status,
        'seconds_to_start': max(0, seconds_to_start),
    })


# ====================== CHECKOUT & PAYMENT ======================

def _load_pending(reference):
    booking = Booking.query.filter_by(reference=reference).first_or_404()
    if booking.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    return booking


def _split_share_amounts(total_amount, count):
    """Split the total into cent-accurate shares whose sum is exact."""
    count = max(1, int(count))
    total_cents = int(round(float(total_amount or 0) * 100))
    base, remainder = divmod(total_cents, count)
    return [(base + (1 if index < remainder else 0)) / 100
            for index in range(count)]


def _ensure_split_invite(booking):
    if len(booking.seat_list) < 2:
        return None
    if not booking.split_token:
        booking.split_token = secrets.token_urlsafe(24)
    booking.is_split_pay = True
    return booking.split_token


def _ensure_split_slots(booking):
    """Create or refresh unclaimed shares; never rewrite a share after payment starts."""
    count = len(booking.seat_list)
    if count < 2:
        return []
    rows = (SplitContribution.query.filter_by(booking_id=booking.id)
            .order_by(SplitContribution.share_index).all())
    if any(row.status in ('CREATED', 'PAID') for row in rows):
        return rows

    amounts = _split_share_amounts(booking.total_amount, count)
    if len(rows) != count:
        for row in rows:
            db.session.delete(row)
        rows = [SplitContribution(booking_id=booking.id, share_index=index,
                                  amount=amount, status='OPEN')
                for index, amount in enumerate(amounts, start=1)]
        db.session.add_all(rows)
    else:
        for row, amount in zip(rows, amounts):
            row.amount = amount
    return rows


def _has_split_progress(booking):
    return SplitContribution.query.filter(
        SplitContribution.booking_id == booking.id,
        SplitContribution.status.in_(('CREATED', 'PAID'))).first() is not None


def _split_invite_url(booking):
    return url_for('split_pay', token=booking.split_token, _external=True)


SNACK_ITEMS = [
    {"id": "popcorn_lg", "name": "Large Butter Popcorn", "price": 180, "icon": "fa-bowl-food", "desc": "Fresh tub with extra butter"},
    {"id": "pepsi_m", "name": "Chilled Pepsi 500ml", "price": 110, "icon": "fa-glass-water", "desc": "Ice-cold cinema beverage"},
    {"id": "combo_sav", "name": "Saver Combo (Popcorn + 2 Pepsi)", "price": 260, "icon": "fa-box-open", "desc": "Best value for 2 viewers"},
    {"id": "nachos_c", "name": "Cheese Nachos Extra Dip", "price": 160, "icon": "fa-stroopwafel", "desc": "Crispy corn chips with warm cheese"}
]


@app.route('/checkout/<reference>')
@login_required
def checkout(reference):
    booking = _load_pending(reference)

    if booking.status == 'PAID':
        return redirect(url_for('ticket', reference=reference))
    if booking.is_expired:
        release_booking(booking, 'EXPIRED')
        flash("Your seat hold expired. Please select seats again.")
        return redirect(url_for('book', showtime_id=booking.showtime_id))
    if booking.status not in ('PENDING',):
        flash("This booking is no longer payable.")
        return redirect(url_for('dashboard'))

    if len(booking.seat_list) > 1:
        _ensure_split_invite(booking)
        _ensure_split_slots(booking)
        db.session.commit()

    wallet = get_wallet(current_user)
    return render_template('checkout.html', booking=booking,
                           showtime=booking.showtime,
                           movie=booking.showtime.movie,
                           wallet=wallet,
                           can_use_wallet=wallet.balance >= booking.total_amount,
                           gateway=payments.gateway_name(),
                           snack_items=SNACK_ITEMS,
                           split_pay_url=_split_invite_url(booking) if booking.split_token else '',
                           split_started=_has_split_progress(booking),
                           user_points=current_user.points or 0)


@app.route('/split-pay/<token>')
def split_pay(token):
    """Public invite view: a random token grants access to the split summary only."""
    booking = Booking.query.filter_by(split_token=token).first_or_404()
    if len(booking.seat_list) < 2:
        abort(404)
    if booking.is_expired:
        release_booking(booking, 'EXPIRED')
    rows = _ensure_split_slots(booking) if booking.status == 'PENDING' else (
        SplitContribution.query.filter_by(booking_id=booking.id)
        .order_by(SplitContribution.share_index).all())
    db.session.commit()
    user_share = None
    if current_user.is_authenticated:
        user_share = SplitContribution.query.filter_by(
            booking_id=booking.id, user_id=current_user.id).first()
    paid_count = sum(row.status == 'PAID' for row in rows)
    open_count = sum(row.status == 'OPEN' and row.user_id is None for row in rows)
    return render_template('split_pay.html', booking=booking,
                           movie=booking.showtime.movie,
                           showtime=booking.showtime,
                           rows=rows, user_share=user_share,
                           paid_count=paid_count, open_count=open_count,
                           share_amount=booking.per_person_amount,
                           split_gateway_available=payments.gateway_name() == 'mock')


@app.route('/split-pay/<token>/start', methods=['POST'])
@login_required
def start_split_payment(token):
    booking = Booking.query.filter_by(split_token=token).first_or_404()
    if payments.gateway_name() != 'mock':
        flash('Split Pay is available in sandbox mode. Use the booking holder’s checkout for live payment.')
        return redirect(url_for('split_pay', token=token))
    if booking.status != 'PENDING' or booking.is_expired:
        if booking.is_expired:
            release_booking(booking, 'EXPIRED')
        flash('This split invite is no longer payable.')
        return redirect(url_for('split_pay', token=token))
    if booking.payment and booking.payment.status == 'CREATED':
        flash('A full booking payment is already in progress. Ask the booking holder to finish or cancel it first.')
        return redirect(url_for('split_pay', token=token))

    rows = _ensure_split_slots(booking)
    contribution = SplitContribution.query.filter_by(
        booking_id=booking.id, user_id=current_user.id).first()
    if contribution and contribution.status == 'PAID':
        flash('Your share has already been paid.')
        return redirect(url_for('split_pay', token=token))
    if not contribution:
        contribution = next((row for row in rows
                             if row.status == 'OPEN' and row.user_id is None), None)
        if not contribution:
            flash('All remaining shares are already being paid or have been completed.')
            db.session.commit()
            return redirect(url_for('split_pay', token=token))
        contribution.user_id = current_user.id
        contribution.status = 'CREATED'

    order = payments.create_order(
        contribution.amount,
        receipt=f'{booking.reference}-S{contribution.share_index}',
        notes={'reference': booking.reference,
               'split_share': str(contribution.share_index),
               'movie': booking.showtime.movie.title})
    contribution.gateway = 'mock'
    contribution.method = 'split'
    contribution.order_id = order['order_id']
    contribution.created_at = datetime.utcnow()
    booking.expires_at = max(booking.expires_at, datetime.utcnow() + timedelta(minutes=15))
    lock = SeatLock.query.filter_by(token=booking.lock_token).first() if booking.lock_token else None
    if lock:
        lock.expires_at = booking.expires_at
    db.session.commit()
    return render_template('split_pay_mock.html', booking=booking,
                           movie=booking.showtime.movie,
                           contribution=contribution, order=order,
                           user=current_user)


@app.route('/split-pay/<token>/simulate/<int:contribution_id>', methods=['POST'])
@login_required
def simulate_split_payment(token, contribution_id):
    booking = Booking.query.filter_by(split_token=token).first_or_404()
    contribution = SplitContribution.query.filter_by(
        id=contribution_id, booking_id=booking.id,
        user_id=current_user.id).first_or_404()
    if (payments.gateway_name() != 'mock' or booking.status != 'PENDING'
            or contribution.status != 'CREATED' or booking.is_expired):
        flash('This split payment is no longer active.')
        return redirect(url_for('split_pay', token=token))

    succeeded = request.form.get('outcome', 'success') == 'success'
    result = payments.simulate_payment(contribution.order_id,
                                       method='split', succeed=succeeded)
    if not result['ok']:
        contribution.status = 'OPEN'
        contribution.user_id = None
        contribution.error_message = result.get('error', 'Payment failed.')[:300]
        db.session.commit()
        flash('That share did not go through. It is available for another attempt.')
        return redirect(url_for('split_pay', token=token))

    if not payments.verify_signature(contribution.order_id,
                                     result['payment_id'], result['signature']):
        contribution.status = 'OPEN'
        contribution.user_id = None
        contribution.error_message = 'Signature verification failed'
        db.session.commit()
        flash('The share payment could not be verified. Please try again.')
        return redirect(url_for('split_pay', token=token))

    contribution.payment_id = result['payment_id']
    contribution.signature = result['signature']
    contribution.status = 'PAID'
    db.session.commit()

    rows = SplitContribution.query.filter_by(booking_id=booking.id).all()
    paid_count = sum(row.status == 'PAID' for row in rows)
    if paid_count == len(booking.seat_list):
        payment = booking.payment or Payment(booking_id=booking.id)
        payment.gateway = 'mock-split'
        payment.method = 'split'
        payment.order_id = f'split_{booking.reference}'
        payment.payment_id = ','.join(row.payment_id or '' for row in rows)
        payment.amount = booking.total_amount
        payment.status = 'CREATED'
        db.session.add(payment)
        db.session.commit()
        ok, message = finalise_paid_booking(booking, payment)
        flash(message)
        return redirect(url_for('ticket', reference=booking.reference) if ok
                        else url_for('split_pay', token=token))

    booking.expires_at = max(booking.expires_at,
                             datetime.utcnow() + timedelta(minutes=15))
    lock = SeatLock.query.filter_by(token=booking.lock_token).first() if booking.lock_token else None
    if lock:
        lock.expires_at = booking.expires_at
    db.session.commit()
    flash(f'Your share is in. {paid_count} of {len(booking.seat_list)} shares paid.')
    return redirect(url_for('split_pay', token=token))


@app.route('/checkout/<reference>/update_extras', methods=['POST'])
@login_required
def update_booking_extras(reference):
    booking = _load_pending(reference)
    if _has_split_progress(booking):
        flash('Extras are locked after a group member starts paying. Finish or cancel the split first.')
        return redirect(url_for('checkout', reference=reference))
    if booking.status != 'PENDING' or booking.is_expired:
        flash("This booking is expired.")
        return redirect(url_for('book', showtime_id=booking.showtime_id))

    selected_snack_ids = set(request.form.getlist('snacks'))
    try:
        requested_points = int(request.form.get('redeem_points', 0))
    except (TypeError, ValueError):
        flash("Enter a valid CinePass points amount.")
        return redirect(url_for('checkout', reference=reference))

    snacks_chosen = []
    snack_total = 0.0
    for s in SNACK_ITEMS:
        if s['id'] in selected_snack_ids:
            snacks_chosen.append(s)
            snack_total += s['price']

    user_pts = max(0, current_user.points or 0)
    # Never let a crafted negative value increase a user's points at payment time.
    redeem_pts = min(max(0, requested_points), user_pts)
    discount = float(redeem_pts)

    base_subtotal = booking.ticket_amount + snack_total
    amounts = payments.compute_amounts(base_subtotal, len(booking.seat_list))
    final_total = max(1.0, amounts['total'] - discount)

    booking.snacks_json = json.dumps(snacks_chosen)
    booking.points_redeemed = redeem_pts
    booking.total_amount = round(final_total, 2)
    db.session.commit()

    flash("Booking updated with selected snacks and CinePass discount!")
    return redirect(url_for('checkout', reference=booking.reference))


@app.route('/pay/wallet/<reference>', methods=['POST'])
@login_required
def pay_with_wallet(reference):
    booking = _load_pending(reference)
    if _has_split_progress(booking):
        flash('A group split is in progress. Finish it from the Squad Pay invite link.')
        return redirect(url_for('checkout', reference=reference))
    if booking.status != 'PENDING' or booking.is_expired:
        flash("This booking can no longer be paid.")
        return redirect(url_for('dashboard'))

    wallet = get_wallet(current_user)
    if wallet.balance < booking.total_amount:
        flash("Not enough wallet balance. Recharge or pay by UPI / card.")
        return redirect(url_for('checkout', reference=reference))

    wallet.balance = round(wallet.balance - booking.total_amount, 2)
    db.session.add(WalletTransaction(wallet_id=wallet.id,
                                     amount=booking.total_amount,
                                     type='PAYMENT',
                                     description=f'Tickets {booking.reference}'))
    payment = Payment(booking_id=booking.id, gateway='wallet', method='wallet',
                      amount=booking.total_amount, status='CREATED',
                      order_id=f'wallet_{booking.reference}',
                      payment_id=f'wal_{secrets.token_hex(6)}')
    db.session.add(payment)
    db.session.commit()

    ok, msg = finalise_paid_booking(booking, payment)
    flash(msg)
    return redirect(url_for('ticket', reference=reference) if ok
                    else url_for('book', showtime_id=booking.showtime_id))


@app.route('/pay/gateway/<reference>', methods=['POST'])
@login_required
def pay_gateway(reference):
    """Creates the Razorpay (or mock) order and opens the payment page."""
    booking = _load_pending(reference)
    if _has_split_progress(booking):
        flash('A group split is in progress. Finish it from the Squad Pay invite link.')
        return redirect(url_for('checkout', reference=reference))
    if booking.status != 'PENDING' or booking.is_expired:
        flash("This booking can no longer be paid.")
        return redirect(url_for('dashboard'))

    method = request.form.get('method', 'upi')
    try:
        order = payments.create_order(
            booking.total_amount,
            receipt=booking.reference,
            notes={'reference': booking.reference,
                   'movie': booking.showtime.movie.title,
                   'seats': booking.seats})
    except payments.PaymentGatewayError as exc:
        flash(str(exc))
        return redirect(url_for('checkout', reference=reference))

    payment = booking.payment or Payment(booking_id=booking.id)
    payment.gateway = order['gateway']
    payment.order_id = order['order_id']
    payment.amount = booking.total_amount
    payment.method = method
    payment.status = 'CREATED'
    payment.raw_response = order.get('raw')
    db.session.add(payment)
    db.session.commit()

    template = 'pay_razorpay.html' if order['gateway'] == 'razorpay' else 'pay_mock.html'
    return render_template(template, booking=booking, order=order,
                           movie=booking.showtime.movie,
                           showtime=booking.showtime, method=method,
                           user=current_user)


@app.route('/pay/callback', methods=['POST'])
@login_required
def payment_callback():
    """
    Where the gateway hands control back. Razorpay Checkout posts
    razorpay_order_id / razorpay_payment_id / razorpay_signature here;
    the mock page posts the same three fields.
    """
    reference = request.form.get('reference', '')
    order_id = request.form.get('razorpay_order_id', '')
    payment_id = request.form.get('razorpay_payment_id', '')
    signature = request.form.get('razorpay_signature', '')
    failed = request.form.get('failed') == '1'
    error_msg = request.form.get('error_message', 'Payment failed at the gateway.')

    booking = _load_pending(reference)
    payment = booking.payment
    if not payment:
        flash("No payment was started for this booking.")
        return redirect(url_for('checkout', reference=reference))

    if order_id != payment.order_id:
        flash("Payment could not be matched to this booking. Please retry checkout.")
        return redirect(url_for('checkout', reference=reference))

    if failed:
        payment.status = 'FAILED'
        payment.error_message = error_msg[:300]
        db.session.commit()
        release_booking(booking, 'FAILED')
        flash(f"{error_msg} Your seats have been released.")
        return redirect(url_for('book', showtime_id=booking.showtime_id))

    # signature check - this is what makes the success real
    if not payments.verify_signature(order_id, payment_id, signature):
        payment.status = 'FAILED'
        payment.error_message = 'Signature verification failed'
        db.session.commit()
        release_booking(booking, 'FAILED')
        flash("Payment could not be verified. Nothing was charged.")
        return redirect(url_for('book', showtime_id=booking.showtime_id))

    if booking.status == 'PAID':                     # double submit guard
        return redirect(url_for('ticket', reference=reference))
    if booking.is_expired:
        release_booking(booking, 'EXPIRED')
        flash("Your hold expired before payment completed. Refund will be processed.")
        return redirect(url_for('book', showtime_id=booking.showtime_id))

    payment.payment_id = payment_id
    payment.signature = signature
    db.session.commit()

    ok, msg = finalise_paid_booking(booking, payment)
    flash(msg)
    return redirect(url_for('ticket', reference=reference) if ok
                    else url_for('book', showtime_id=booking.showtime_id))


@app.route('/pay/simulate/<reference>', methods=['POST'])
@login_required
def simulate(reference):
    """Sandbox 'Pay Now' / 'Simulate failure' buttons on the mock gateway page."""
    booking = _load_pending(reference)
    payment = booking.payment
    if (not payment or not payment.order_id or payment.gateway != 'mock'
            or not payment.order_id.startswith('order_mock_')):
        abort(404)
    if booking.status != 'PENDING' or booking.is_expired:
        flash("This booking can no longer be paid.")
        return redirect(url_for('checkout', reference=reference))
    succeed = request.form.get('outcome', 'success') == 'success'
    result = payments.simulate_payment(payment.order_id,
                                       method=payment.method or 'upi',
                                       succeed=succeed)
    if not result['ok']:
        payment.status = 'FAILED'
        payment.error_message = result['error']
        db.session.commit()
        release_booking(booking, 'FAILED')
        flash(f"{result['error']} Your seats have been released.")
        return redirect(url_for('book', showtime_id=booking.showtime_id))

    payment.payment_id = result['payment_id']
    payment.signature = result['signature']
    db.session.commit()

    ok, msg = finalise_paid_booking(booking, payment)
    flash(msg)
    return redirect(url_for('ticket', reference=reference) if ok
                    else url_for('book', showtime_id=booking.showtime_id))


@app.route('/pay/webhook', methods=['POST'])
def payment_webhook():
    """
    Razorpay webhook (payment.captured). Set RAZORPAY_WEBHOOK_SECRET to enable.
    Makes the booking survive the user closing the tab mid-payment.
    """
    signature = request.headers.get('X-Razorpay-Signature', '')
    if not payments.verify_webhook(request.get_data(), signature):
        return jsonify({'status': 'invalid signature'}), 400

    event = request.get_json(silent=True) or {}
    entity = (event.get('payload', {}).get('payment', {}).get('entity', {}))
    order_id = entity.get('order_id')
    payment = Payment.query.filter_by(order_id=order_id).first()
    if payment and payment.booking.status == 'PENDING':
        payment.payment_id = entity.get('id')
        payment.method = entity.get('method', payment.method)
        finalise_paid_booking(payment.booking, payment)
    return jsonify({'status': 'ok'})


@app.route('/booking/<reference>/cancel', methods=['POST'])
@login_required
def cancel_booking(reference):
    booking = _load_pending(reference)
    if booking.status == 'PENDING':
        release_booking(booking, 'CANCELLED')
        flash("Booking cancelled and seats released.")
    return redirect(url_for('dashboard'))


@app.route('/booking/<reference>/refund', methods=['POST'])
@login_required
def refund_booking(reference):
    booking = Booking.query.filter_by(reference=reference).first_or_404()
    if booking.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    if booking.status != 'PAID':
        flash("Only confirmed, paid bookings are eligible for cancellation and refund.")
        return redirect(url_for('ticket', reference=reference))

    if booking.showtime.is_past:
        flash("⛔ This show has already ended or started. Past shows cannot be cancelled.")
        return redirect(url_for('ticket', reference=reference))

    # Cancellation policy: 90% refund of the ticket amount
    cancellation_fee_rate = 0.10
    refund_amount = round(booking.ticket_amount * (1.0 - cancellation_fee_rate), 2)

    # Free up booked seats
    BookedSeat.query.filter_by(booking_id=booking.id).delete()

    # Credit refund to user's wallet
    wallet = get_wallet(booking.user)
    wallet.balance = round(wallet.balance + refund_amount, 2)
    db.session.add(WalletTransaction(
        wallet_id=wallet.id,
        amount=refund_amount,
        type='REFUND',
        description=f'Self-service cancellation refund for {booking.reference}'
    ))

    booking.status = 'CANCELLED'
    db.session.commit()

    flash(f"✅ Booking {booking.reference} cancelled successfully. ₹{refund_amount:.2f} refunded to your CineWave Wallet!")
    return redirect(url_for('wallet_page'))


@app.route('/ticket/<reference>/resend_delivery', methods=['POST'])
@login_required
def resend_ticket_delivery(reference):
    booking = Booking.query.filter_by(reference=reference).first_or_404()
    if booking.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    if booking.status != 'PAID':
        flash('Only confirmed bookings have an e-ticket to send.')
        return redirect(url_for('ticket', reference=reference))
    if dispatch_ticket_delivery(booking):
        flash(f"E-ticket with QR pass sent to {booking.user.email}.")
    else:
        flash('The booking is confirmed, but email delivery failed. Check the mail settings and retry.')
    return redirect(url_for('ticket', reference=reference))


@app.route('/ticket/<reference>')
@login_required
def ticket(reference):
    booking = Booking.query.filter_by(reference=reference).first_or_404()
    if booking.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    return render_template('ticket.html', booking=booking,
                           showtime=booking.showtime,
                           movie=booking.showtime.movie,
                           payment=booking.payment)


@app.route('/ticket/<reference>/qr.png')
@login_required
def ticket_qr(reference):
    """QR code printed on the e-ticket: scanned at the gate to verify the booking."""
    booking = Booking.query.filter_by(reference=reference).first_or_404()
    if booking.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    payload = (f"CINEWAVE|{booking.reference}|{booking.showtime.movie.title}|"
               f"{booking.showtime.theater}|{booking.showtime.show_date}|"
               f"{booking.showtime.show_time}|{booking.seats}")
    try:
        import qrcode
        img = qrcode.make(payload)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue(), 200, {'Content-Type': 'image/png',
                                     'Cache-Control': 'no-store'}
    except ImportError:
        # qrcode not installed - fall back to a 1x1 transparent pixel
        import base64
        pixel = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8'
            '/58BAwAI/AL+4d1cAAAAAElFTkSuQmCC')
        return pixel, 200, {'Content-Type': 'image/png'}


# ====================== WALLET ======================

@app.route('/wallet')
@login_required
def wallet_page():
    wallet = get_wallet(current_user)
    txns = (WalletTransaction.query.filter_by(wallet_id=wallet.id)
            .order_by(WalletTransaction.timestamp.desc()).limit(20).all())
    reqs = (RechargeRequest.query.filter_by(user_id=current_user.id)
            .order_by(RechargeRequest.created_at.desc()).limit(10).all())
    return render_template('wallet.html', wallet=wallet, txns=txns, requests=reqs)


@app.route('/wallet/recharge', methods=['POST'])
@login_required
def wallet_recharge():
    try:
        amount = float(request.form['amount'])
    except (KeyError, ValueError):
        flash("Enter a valid amount.")
        return redirect(url_for('wallet_page'))
    if amount <= 0 or amount > 10000:
        flash("Recharge amount must be between ₹1 and ₹10,000.")
        return redirect(url_for('wallet_page'))

    db.session.add(RechargeRequest(user_id=current_user.id, amount=amount))
    db.session.commit()
    flash(f"Recharge request for ₹{amount:.0f} submitted. An admin will approve it shortly.")
    return redirect(url_for('wallet_page'))


# ====================== USER DASHBOARD & PROFILE ======================

@app.route('/dashboard')
@login_required
def dashboard():
    purge_expired_holds()
    bookings = (Booking.query.filter_by(user_id=current_user.id)
                .order_by(Booking.booked_at.desc()).all())
    return render_template('dashboard.html', bookings=bookings)


@app.route('/profile')
@login_required
def profile():
    purge_expired_holds()
    user_stats = current_user.stats
    film_dna = current_user.film_dna
    watchlist_movies = current_user.watchlist_movies
    recent_bookings = (Booking.query.filter_by(user_id=current_user.id, status='PAID')
                      .order_by(Booking.booked_at.desc()).limit(6).all())
    return render_template(
        'profile.html',
        stats=user_stats,
        film_dna=film_dna,
        watchlist_movies=watchlist_movies,
        recent_bookings=recent_bookings
    )


@app.route('/profile/edit', methods=['POST'])
@login_required
def edit_profile():
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    bio = request.form.get('bio', '').strip()

    if email and not is_valid_email(email):
        flash('Please enter a valid email address.')
        return redirect(url_for('profile'))

    # Check email uniqueness if changed
    if email and email != current_user.email:
        existing = User.query.filter_by(email=email).first()
        if existing and existing.id != current_user.id:
            flash('This email address is already in use by another account.')
            return redirect(url_for('profile'))
        current_user.email = email

    if phone:
        current_user.phone = phone
    if bio:
        current_user.bio = bio[:250]

    db.session.commit()
    flash('Your profile has been updated!')
    return redirect(url_for('profile'))


@app.route('/api/watchlist/toggle/<int:movie_id>', methods=['POST'])
@login_required
def toggle_watchlist(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    item = Watchlist.query.filter_by(user_id=current_user.id, movie_id=movie_id).first()
    if item:
        db.session.delete(item)
        db.session.commit()
        saved = False
        message = f"Removed '{movie.title}' from your watchlist."
    else:
        new_item = Watchlist(user_id=current_user.id, movie_id=movie_id)
        db.session.add(new_item)
        db.session.commit()
        saved = True
        message = f"Added '{movie.title}' to your watchlist!"

    count = Watchlist.query.filter_by(user_id=current_user.id).count()
    return jsonify({
        'success': True,
        'saved': saved,
        'movie_id': movie_id,
        'message': message,
        'watchlist_count': count
    })


@app.route('/watchlist')
@login_required
def watchlist_page():
    return redirect(url_for('profile') + '#watchlist')


@app.route('/api/movie/<int:movie_id>/rate', methods=['POST'])
@login_required
def rate_movie(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    data = request.get_json(silent=True) or request.form
    try:
        score = float(data.get('rating', 0))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid rating score'}), 400

    if score < 1.0 or score > 5.0:
        return jsonify({'success': False, 'message': 'Rating must be between 1 and 5 stars'}), 400

    review_text = (data.get('review') or '').strip()[:500]
    has_spoiler = bool(data.get('has_spoiler', False))
    # Auto-detect plot spoilers if not explicitly flagged
    if not has_spoiler and review_text:
        spoiler_triggers = ['die', 'dies', 'died', 'death', 'kill', 'kills', 'killed', 'murder',
                            'climax', 'twist', 'ending', 'ends with', 'post credit', 'villain is',
                            'culprit', 'betray', 'killer is']
        if any(trig in review_text.lower() for trig in spoiler_triggers):
            has_spoiler = True

    rating_obj = MovieRating.query.filter_by(user_id=current_user.id, movie_id=movie_id).first()
    is_new = False
    if rating_obj:
        rating_obj.rating = score
        rating_obj.review = review_text
        rating_obj.has_spoiler = has_spoiler
        rating_obj.created_at = datetime.utcnow()
    else:
        rating_obj = MovieRating(user_id=current_user.id, movie_id=movie_id, rating=score,
                                 review=review_text, has_spoiler=has_spoiler)
        db.session.add(rating_obj)
        is_new = True

    if is_new:
        current_user.points = (current_user.points or 0) + 5

    db.session.commit()

    return jsonify({
        'success': True,
        'message': f"You rated '{movie.title}' {score:.1f} ★" + (" (+5 CinePass Pts)" if is_new else ""),
        'rating': score,
        'has_spoiler': has_spoiler,
        'movie_avg_rating': movie.display_rating,
        'user_points': current_user.points
    })


# ====================== ADMIN ROUTES ======================

@app.route('/admin')
@login_required
def admin():
    guard = admin_required()
    if guard:
        return guard
    movies = Movie.query.all()
    showtimes = Showtime.query.order_by(Showtime.show_date.desc()).all()
    theaters = Theater.query.all()
    screens = Screen.query.all()
    pending_recharges = RechargeRequest.query.filter_by(status='PENDING').count()
    revenue = db.session.query(db.func.sum(Booking.total_amount)) \
                        .filter(Booking.status == 'PAID').scalar() or 0
    return render_template('admin.html', movies=movies, showtimes=showtimes,
                           theaters=theaters, screens=screens,
                           pending_recharges=pending_recharges, revenue=revenue,
                           paid_count=Booking.query.filter_by(status='PAID').count())


@app.route('/admin/add_movie', methods=['GET', 'POST'])
@login_required
def add_movie():
    guard = admin_required()
    if guard:
        return guard
    if request.method == 'POST':
        try:
            trailer_path = save_trailer_upload(request.files.get('trailer_video'))
        except ValueError as exc:
            flash(str(exc))
            return render_template('add_movie.html'), 400
        trailer_key = ('' if trailer_path else
                       parse_youtube_video_key(request.form.get('youtube_trailer')))
        if trailer_key is None:
            flash('Enter a valid YouTube video link or 11-character video ID.')
            return render_template('add_movie.html'), 400
        category = request.form.get('category', 'showing')
        is_upcoming = (category == 'upcoming')
        is_rerelease = (request.form.get('release_type', 'fresh') == 'rerelease')

        rel_date_str = request.form.get('release_date', '').strip()
        rel_date = None
        if rel_date_str:
            try:
                rel_date = datetime.strptime(rel_date_str, '%Y-%m-%d').date()
            except ValueError:
                rel_date = None

        movie = Movie(title=request.form['title'],
                      description=request.form['description'],
                      duration=int(request.form['duration']),
                      poster=request.form.get('poster', '').strip() or None,
                      language=request.form.get('language', 'Telugu'),
                      certificate=request.form.get('certificate', 'U/A'),
                      is_upcoming=is_upcoming,
                      is_rerelease=is_rerelease,
                      release_date=rel_date,
                      youtube_trailer_key=trailer_key or None,
                      trailer_video_path=trailer_path)
        db.session.add(movie)
        db.session.commit()
        cat_label = 'Coming Soon' if is_upcoming else 'Now Showing'
        rel_label = ' (Re-Release)' if is_rerelease else ''
        flash(f"Movie '{movie.title}' added to {cat_label}{rel_label}!")
        return redirect(url_for('admin'))
    return render_template('add_movie.html')


@app.route('/admin/movie/<int:movie_id>/trailer', methods=['POST'])
@login_required
def update_movie_trailer(movie_id):
    guard = admin_required()
    if guard:
        return guard
    movie = Movie.query.get_or_404(movie_id)
    try:
        trailer_path = save_trailer_upload(request.files.get('trailer_video'))
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for('admin'))
    trailer_input = request.form.get('youtube_trailer', '').strip()
    trailer_key = parse_youtube_video_key(trailer_input) if trailer_input else None
    if trailer_path:
        movie.trailer_video_path = trailer_path
        movie.youtube_trailer_key = None
        db.session.commit()
        flash(f"Uploaded trailer saved for '{movie.title}'.")
    elif trailer_input and trailer_key is None:
        flash('Trailer not changed: enter a valid YouTube video link or 11-character video ID.')
    elif trailer_input:
        movie.youtube_trailer_key = trailer_key or None
        movie.trailer_video_path = None
        db.session.commit()
        flash(f"YouTube trailer saved for '{movie.title}'.")
    return redirect(url_for('admin'))


@app.route('/admin/import_movie', methods=['GET', 'POST'])
@login_required
def import_movie():
    guard = admin_required()
    if guard:
        return guard
    results, query = [], ""
    if request.method == 'POST':
        query = request.form.get('query', '').strip()
        if query:
            try:
                res = requests.get(f"{TMDB_BASE_URL}/search/movie",
                                   params={'api_key': TMDB_API_KEY, 'query': query},
                                   timeout=10).json()
                for item in res.get('results', [])[:8]:
                    poster_path = item.get('poster_path')
                    release_date = item.get('release_date', '')
                    results.append({'tmdb_id': item['id'], 'title': item['title'],
                                    'overview': item.get('overview', ''),
                                    'poster_url': f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else None,
                                    'release_date': release_date,
                                    'year': release_date[:4] if release_date else ''})
            except Exception as e:
                flash(f"Error fetching from TMDb: {e}")
    return render_template('import_movie.html', results=results, query=query)


def _tmdb_find_id(title):
    """Best-effort TMDb lookup by title; returns the first result's id or None."""
    try:
        res = requests.get(f"{TMDB_BASE_URL}/search/movie",
                           params={'api_key': TMDB_API_KEY, 'query': title},
                           timeout=10).json()
        for item in res.get('results', []):
            if item.get('id'):
                return item['id']
    except Exception:
        pass
    return None


def _tmdb_fetch_credits(tmdb_id):
    """
    Returns (cast_entries, director_name) for a TMDb movie id; ([], None) on any
    failure so callers never hard-fail when TMDb is unreachable.
    """
    try:
        res = requests.get(f"{TMDB_BASE_URL}/movie/{tmdb_id}/credits",
                           params={'api_key': TMDB_API_KEY}, timeout=10).json()
        cast_entries = []
        for c in (res.get('cast') or [])[:12]:
            cast_entries.append({
                'name': c.get('name') or '',
                'character': c.get('character') or '',
                'profile': f"{TMDB_IMAGE_BASE}{c['profile_path']}" if c.get('profile_path') else None,
            })
        director = next((c.get('name') for c in (res.get('crew') or [])
                         if c.get('job') == 'Director'), None)
        return cast_entries, director
    except Exception:
        return [], None


def _store_movie_cast(movie, tmdb_id):
    """Fetch credits for tmdb_id and store them on the movie. Returns True if anything was saved."""
    cast_entries, director = _tmdb_fetch_credits(tmdb_id)
    if not cast_entries and not director:
        return False
    movie.tmdb_id = tmdb_id
    movie.cast_json = json.dumps({'director': director, 'cast': cast_entries})
    db.session.commit()
    return True


@app.route('/admin/import_movie/add/<int:tmdb_id>', methods=['POST'])
@login_required
def import_movie_add(tmdb_id):
    guard = admin_required()
    if guard:
        return guard
    try:
        try:
            trailer_path = save_trailer_upload(request.files.get('trailer_video'))
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for('admin'))
        trailer_key = ('' if trailer_path else
                       parse_youtube_video_key(request.form.get('youtube_trailer')))
        if trailer_key is None and not trailer_path:
            flash('Enter a valid YouTube video link or 11-character video ID.')
            return redirect(url_for('admin'))
        res = requests.get(f"{TMDB_BASE_URL}/movie/{tmdb_id}",
                           params={'api_key': TMDB_API_KEY}, timeout=10).json()
        poster_path = res.get('poster_path')
        category = request.form.get('category', 'showing')
        is_upcoming = (category == 'upcoming')
        is_rerelease = (request.form.get('release_type', 'fresh') == 'rerelease')

        rel_date_str = request.form.get('release_date', '').strip() or res.get('release_date', '')
        rel_date = None
        if rel_date_str:
            try:
                rel_date = datetime.strptime(rel_date_str[:10], '%Y-%m-%d').date()
            except ValueError:
                rel_date = None

        movie = Movie(title=res.get('title', 'Untitled'),
                      description=res.get('overview', 'No overview available.'),
                      duration=res.get('runtime') or 120,
                      poster=f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else None,
                      language=(res.get('original_language') or 'te').upper(),
                      is_upcoming=is_upcoming,
                      is_rerelease=is_rerelease,
                      release_date=rel_date,
                      tmdb_id=tmdb_id,
                      youtube_trailer_key=trailer_key or None,
                      trailer_video_path=trailer_path)
        db.session.add(movie)
        db.session.commit()

        # pull cast + director along with the import (falls back to title search)
        cast_saved = _store_movie_cast(movie, tmdb_id)
        if not cast_saved:
            found = _tmdb_find_id(movie.title)
            if found:
                cast_saved = _store_movie_cast(movie, found)

        cat_label = 'Coming Soon' if is_upcoming else 'Now Showing'
        rel_label = ' (Re-Release)' if is_rerelease else ''
        cast_note = ' with cast' if cast_saved else ''
        flash(f'Imported "{movie.title}" as {cat_label}{rel_label}{cast_note}!')
    except Exception as e:
        flash(f"Failed to import movie: {e}")
    return redirect(url_for('admin'))


@app.route('/admin/toggle_movie_status/<int:movie_id>', methods=['POST'])
@login_required
def toggle_movie_status(movie_id):
    guard = admin_required()
    if guard:
        return guard
    movie = Movie.query.get_or_404(movie_id)
    movie.is_upcoming = not movie.is_upcoming
    db.session.commit()
    status_str = "Coming Soon" if movie.is_upcoming else "Now Showing"
    flash(f"Movie '{movie.title}' status changed to {status_str}!")
    return redirect(url_for('admin'))


@app.route('/admin/fetch_cast/<int:movie_id>', methods=['POST'])
@login_required
def fetch_cast(movie_id):
    """Pull cast + director from TMDb for an existing movie (admin action)."""
    guard = admin_required()
    if guard:
        return guard
    movie = Movie.query.get_or_404(movie_id)

    tmdb_id = movie.tmdb_id or _tmdb_find_id(movie.title)
    if not tmdb_id:
        flash(f"Could not find '{movie.title}' on TMDb. Try adding the TMDb id manually.")
        return redirect(url_for('admin'))

    if _store_movie_cast(movie, tmdb_id):
        flash(f"Cast updated for '{movie.title}'!")
    else:
        flash(f"TMDb reachable but no cast found for '{movie.title}'.")
    return redirect(url_for('admin'))


@app.route('/admin/toggle_rerelease/<int:movie_id>', methods=['POST'])
@login_required
def toggle_rerelease(movie_id):
    guard = admin_required()
    if guard:
        return guard
    movie = Movie.query.get_or_404(movie_id)
    movie.is_rerelease = not movie.is_rerelease
    db.session.commit()
    rel_label = "Re-Release" if movie.is_rerelease else "Fresh Release"
    flash(f"'{movie.title}' is now marked as {rel_label}!")
    return redirect(url_for('admin'))



@app.route('/admin/delete_movie/<int:movie_id>', methods=['POST'])
@login_required
def delete_movie(movie_id):
    guard = admin_required()
    if guard:
        return guard
    movie = Movie.query.get_or_404(movie_id)
    title = movie.title
    # Cascade: delete bookings (and payments) tied to this movie's showtimes
    showtime_ids = [s.id for s in Showtime.query.filter_by(movie_id=movie_id).all()]
    if showtime_ids:
        Booking.query.filter(Booking.showtime_id.in_(showtime_ids)).delete(synchronize_session=False)
    Showtime.query.filter_by(movie_id=movie_id).delete()
    db.session.delete(movie)
    db.session.commit()
    flash(f"Movie '{title}' has been deleted.")
    return redirect(url_for('admin'))


@app.route('/admin/add_theater', methods=['GET', 'POST'])
@login_required
def add_theater():
    guard = admin_required()
    if guard:
        return guard
    if request.method == 'POST':
        name = request.form['name'].strip()
        if not name:
            flash("Theater name is required")
            return redirect(url_for('add_theater'))
        if Theater.query.filter_by(name=name).first():
            flash(f'A theater named "{name}" already exists')
            return redirect(url_for('add_theater'))
        db.session.add(Theater(name=name,
                               location=request.form.get('location', '').strip(),
                               city=request.form.get('city', 'Visakhapatnam').strip(),
                               address=request.form.get('address', '').strip()))
        db.session.commit()
        flash(f'Theater "{name}" added. Now add its screens and seat layout.')
        return redirect(url_for('screens'))
    return render_template('add_theater.html')


@app.route('/admin/seed_vizag', methods=['POST'])
@login_required
def seed_vizag():
    guard = admin_required()
    if guard:
        return guard
    t, s = seed_vizag_theaters(db, Theater, Screen, verbose=False)
    flash(f"Loaded Vizag theatres: +{t} theatres, +{s} screens with real seat layouts.")
    return redirect(url_for('screens'))


@app.route('/admin/screens')
@login_required
def screens():
    guard = admin_required()
    if guard:
        return guard
    return render_template('screens.html', theaters=Theater.query.all())


@app.route('/admin/add_screen', methods=['GET', 'POST'])
@login_required
def add_screen():
    guard = admin_required()
    if guard:
        return guard
    theaters = Theater.query.all()
    if request.method == 'POST':
        theater_id = int(request.form['theater_id'])
        name = request.form['name'].strip()
        raw = request.form.get('layout_json', '').strip() or '{"classes": []}'
        try:
            layout = json.loads(raw)
        except json.JSONDecodeError as e:
            flash(f"Layout JSON is invalid: {e}")
            return redirect(url_for('add_screen'))
        screen = Screen(theater_id=theater_id, name=name,
                        screen_type=request.form.get('screen_type', '2D'))
        screen.layout = layout
        db.session.add(screen)
        db.session.commit()
        flash(f"Screen '{name}' added with {screen.total_seats} seats.")
        return redirect(url_for('edit_layout', screen_id=screen.id))
    return render_template('add_screen.html', theaters=theaters,
                           sample=json.dumps(SAMPLE_LAYOUT, indent=2))


@app.route('/admin/screen/<int:screen_id>/layout', methods=['GET', 'POST'])
@login_required
def edit_layout(screen_id):
    """Edit a screen's seating arrangement and preview it exactly as users see it."""
    guard = admin_required()
    if guard:
        return guard
    screen = Screen.query.get_or_404(screen_id)

    if request.method == 'POST':
        try:
            layout = json.loads(request.form['layout_json'])
        except json.JSONDecodeError as e:
            flash(f"Layout JSON is invalid: {e}")
            return redirect(url_for('edit_layout', screen_id=screen_id))
        screen.layout = layout
        db.session.commit()
        flash(f"Layout saved — {screen.total_seats} seats.")
        return redirect(url_for('edit_layout', screen_id=screen_id))

    grid = sl.build_layout(screen.layout)
    return render_template('edit_layout.html', screen=screen, grid=grid,
                           layout_json=json.dumps(screen.layout, indent=2))


@app.route('/admin/add_showtime', methods=['GET', 'POST'])
@login_required
def add_showtime():
    guard = admin_required()
    if guard:
        return guard
    movies = Movie.query.all()
    theaters = Theater.query.all()
    screens_list = Screen.query.all()

    if request.method == 'POST':
        screen = Screen.query.get_or_404(int(request.form['screen_id']))
        overrides = {}
        for cls in screen.layout.get('classes', []):
            val = request.form.get(f"price_{cls['code']}", '').strip()
            if val:
                try:
                    overrides[cls['code']] = float(val)
                except ValueError:
                    pass

        show = Showtime(movie_id=int(request.form['movie_id']),
                        screen_id=screen.id,
                        theater=screen.theater.name,
                        show_date=datetime.strptime(request.form['show_date'], '%Y-%m-%d').date(),
                        show_time=request.form['show_time'],
                        price_overrides_json=json.dumps(overrides))
        db.session.add(show)
        db.session.commit()
        flash("Showtime added successfully!")
        return redirect(url_for('admin'))

    return render_template('add_showtime.html', movies=movies, theaters=theaters,
                           screens=screens_list)


@app.route('/api/screen/<int:screen_id>/classes')
@login_required
def screen_classes(screen_id):
    """Used by add_showtime.html to show per-class price boxes for a screen."""
    screen = Screen.query.get_or_404(screen_id)
    return jsonify({'screen': screen.name, 'seats': screen.total_seats,
                    'classes': [{'code': c.get('code'), 'name': c.get('name'),
                                 'price': c.get('price')}
                                for c in screen.layout.get('classes', [])]})


@app.route('/admin/recharges')
@login_required
def admin_recharges():
    guard = admin_required()
    if guard:
        return guard
    reqs = RechargeRequest.query.order_by(RechargeRequest.created_at.desc()).all()
    return render_template('admin_recharges.html', requests=reqs)


@app.route('/admin/recharges/<int:req_id>/<action>', methods=['POST'])
@login_required
def handle_recharge(req_id, action):
    guard = admin_required()
    if guard:
        return guard
    req = RechargeRequest.query.get_or_404(req_id)
    if req.status != 'PENDING':
        flash("Already processed.")
        return redirect(url_for('admin_recharges'))

    if action == 'approve':
        wallet = get_wallet(req.user)
        wallet.balance = round(wallet.balance + req.amount, 2)
        db.session.add(WalletTransaction(wallet_id=wallet.id, amount=req.amount,
                                         type='RECHARGE',
                                         description='Admin approved recharge'))
        req.status = 'APPROVED'
        flash(f"₹{req.amount:.0f} credited to {req.user.username}.")
    elif action == 'reject':
        req.status = 'REJECTED'
        flash("Recharge request rejected.")
    db.session.commit()
    return redirect(url_for('admin_recharges'))


@app.route('/admin/bookings')
@login_required
def admin_bookings():
    guard = admin_required()
    if guard:
        return guard
    bookings = Booking.query.order_by(Booking.booked_at.desc()).limit(100).all()
    return render_template('admin_bookings.html', bookings=bookings)


# ====================== ADMIN ANALYTICS ======================

def _analytics_window(days):
    """(start_of_window, end) datetimes for a `days` lookback; None start = all time."""
    end = datetime.utcnow()
    start = (end - timedelta(days=days)).replace(hour=0, minute=0, second=0,
                                                 microsecond=0) if days else None
    return start, end


def _analytics_bookings(days):
    """All bookings in the window as plain Booking objects, freshest first."""
    q = (Booking.query.join(Showtime, Booking.showtime_id == Showtime.id)
         .join(Movie, Showtime.movie_id == Movie.id))
    start, _ = _analytics_window(days)
    if start:
        q = q.filter(Booking.booked_at >= start)
    return q.order_by(Booking.booked_at.desc()).all()


def _collect_analytics(days):
    """
    All aggregates for the analytics dashboard, in one pass over the window's
    bookings plus grouped queries. Kept independent of templates so tests can
    assert on the numbers directly.
    """
    start, end = _analytics_window(days)

    def in_window(q):
        return q.filter(Booking.booked_at >= start) if start else q

    # ---- headline KPIs -----------------------------------------------------
    rows = (in_window(Booking.query)
            .with_entities(Booking.status,
                           sa_func.count(Booking.id),
                           sa_func.coalesce(sa_func.sum(Booking.total_amount), 0.0))
            .group_by(Booking.status).all())
    status_counts = {status: {'count': cnt, 'amount': float(amount or 0.0)}
                     for status, cnt, amount in rows}
    paid = status_counts.get('PAID', {'count': 0, 'amount': 0.0})
    lost = (status_counts.get('CANCELLED', {'count': 0, 'amount': 0})['count']
            + status_counts.get('FAILED', {'count': 0, 'amount': 0})['count']
            + status_counts.get('EXPIRED', {'count': 0, 'amount': 0})['count'])
    all_count = sum(v['count'] for v in status_counts.values())

    active_buyers = in_window(Booking.query.filter(Booking.status == 'PAID')) \
        .with_entities(sa_func.count(sa_func.distinct(Booking.user_id))).scalar() or 0

    # ---- daily revenue trend (last `days` days, zero-filled) ---------------
    trend = []
    if days:
        daily = (in_window(Booking.query.filter(Booking.status == 'PAID'))
                 .with_entities(sa_func.date(Booking.paid_at).label('d'),
                                sa_func.coalesce(sa_func.sum(Booking.total_amount), 0.0),
                                sa_func.count(Booking.id))
                 .group_by('d').all())
        by_day = {str(d): {'amount': float(a or 0.0), 'tickets': int(n)} for d, a, n in daily}
        today = date.today()
        for i in range(days - 1, -1, -1):
            day = today - timedelta(days=i)
            info = by_day.get(day.isoformat(), {'amount': 0.0, 'tickets': 0})
            trend.append({'date': day, 'label': day.strftime('%d %b'),
                          'amount': info['amount'], 'tickets': info['tickets']})

    # ---- top movies / theatres (PAID only) ---------------------------------
    movie_stats = (in_window(Booking.query.filter(Booking.status == 'PAID'))
                   .join(Showtime, Booking.showtime_id == Showtime.id)
                   .with_entities(Showtime.movie_id,
                                  sa_func.count(Booking.id),
                                  sa_func.coalesce(sa_func.sum(Booking.total_amount), 0.0))
                   .group_by(Showtime.movie_id).all())
    movie_stats = {mid: {'count': int(cnt), 'revenue': float(rev or 0.0)}
                   for mid, cnt, rev in movie_stats}

    theatre_stats = (in_window(Booking.query.filter(Booking.status == 'PAID'))
                     .join(Showtime, Booking.showtime_id == Showtime.id)
                     .join(Screen, Showtime.screen_id == Screen.id)
                     .join(Theater, Screen.theater_id == Theater.id)
                     .with_entities(Theater.id,
                                    sa_func.count(Booking.id),
                                    sa_func.coalesce(sa_func.sum(Booking.total_amount), 0.0))
                     .group_by(Theater.id).all())
    theatre_stats = {tid: {'count': int(cnt), 'revenue': float(rev or 0.0)}
                     for tid, cnt, rev in theatre_stats}

    # ---- occupancy: booked seats per showtime ------------------------------
    q = (Booking.query.filter(Booking.status == 'PAID')
         .join(Showtime, Booking.showtime_id == Showtime.id)
         .with_entities(Showtime.id,
                        sa_func.sum(Booking.total_amount),
                        sa_func.count(Booking.id)))
    if start:
        q = q.filter(Booking.booked_at >= start)
    per_show_paid = {sid: {'revenue': float(rev or 0.0), 'bookings': int(n)}
                     for sid, rev, n in q.group_by(Showtime.id).all()}
    seats_paid_rows = (in_window(Booking.query.filter(Booking.status == 'PAID'))
                       .join(BookedSeat, BookedSeat.booking_id == Booking.id)
                       .with_entities(BookedSeat.showtime_id, sa_func.count(BookedSeat.id))
                       .group_by(BookedSeat.showtime_id).all())
    seats_paid = {sid: int(n) for sid, n in seats_paid_rows}

    # ---- payment method split (PAID) ---------------------------------------
    method_rows = (in_window(Payment.query.filter(Payment.status == 'CAPTURED'))
                   .join(Booking, Payment.booking_id == Booking.id)
                   .with_entities(Payment.method,
                                  sa_func.count(Payment.id),
                                  sa_func.coalesce(sa_func.sum(Payment.amount), 0.0))
                   .group_by(Payment.method).all())
    pay_split = [{'method': (m or 'unknown'), 'count': int(n), 'amount': float(a or 0.0)}
                 for m, n, a in method_rows]
    pay_split.sort(key=lambda x: x['amount'], reverse=True)
    pay_total = sum(m['amount'] for m in pay_split)

    # ---- top movies & theatres joined with names + occupancy ---------------
    movies = Movie.query.all()
    movie_names = {m.id: m.title for m in movies}
    top_movies = sorted(
        ({'id': mid, 'title': movie_names.get(mid, f'Movie #{mid}'), **st}
         for mid, st in movie_stats.items()),
        key=lambda x: x['revenue'], reverse=True)

    theatres = Theater.query.all()
    theatre_names = {t.id: t for t in theatres}
    showtimes = Showtime.query.all()
    layout_cache = {}
    for s in showtimes:
        layout_cache[s.id] = s.layout

    top_theatres = []
    for tid, st in sorted(theatre_stats.items(), key=lambda kv: kv[1]['revenue'], reverse=True):
        th = theatre_names.get(tid)
        if not th:
            continue
        top_theatres.append({'id': tid, 'name': th.name, 'location': th.location or '', **st})

    # ---- upcoming showtimes heat strip (today + next 7 days) ---------------
    upcoming = [s for s in showtimes
                if s.show_date >= date.today() and s.show_date <= date.today() + timedelta(days=7)
                and s.layout]
    upcoming.sort(key=lambda s: (s.show_date, s.show_time))
    heat = []
    for s in upcoming[:24]:
        total = sl.count_seats(layout_cache[s.id]) or 1
        sold = seats_paid.get(s.id, 0)
        pct = min(100, round(100.0 * sold / total))
        heat.append({'showtime': s, 'sold': sold, 'total': total, 'pct': pct,
                     'revenue': per_show_paid.get(s.id, {}).get('revenue', 0.0)})

    overall_total_seats = sum(sl.count_seats(layout_cache[s.id]) or 0
                              for s in showtimes if s.show_date >= date.today())
    overall_sold = sum(seats_paid.values())
    occupancy_overall = round(100.0 * overall_sold / overall_total_seats, 1) \
        if overall_total_seats else 0.0

    return {
        'days': days,
        'paid': paid,
        'all_count': all_count,
        'lost_count': lost,
        'cancel_rate': round(100.0 * lost / all_count, 1) if all_count else 0.0,
        'avg_ticket': round(paid['amount'] / paid['count'], 0) if paid['count'] else 0,
        'active_buyers': active_buyers,
        'trend': trend,
        'trend_max': max((t['amount'] for t in trend), default=0.0),
        'trend_total': round(sum(t['amount'] for t in trend), 2),
        'top_movies': top_movies[:8],
        'top_theatres': top_theatres[:8],
        'pay_split': pay_split,
        'pay_total': pay_total,
        'heat': heat,
        'occupancy_overall': occupancy_overall,
    }


@app.route('/admin/analytics')
@login_required
def admin_analytics():
    guard = admin_required()
    if guard:
        return guard
    try:
        days = int(request.args.get('days', '') or 0)
    except ValueError:
        days = 0
    if days not in (7, 30, 90):
        days = 0
    data = _collect_analytics(days)
    return render_template('admin_analytics.html', a=data, days=days)


@app.route('/admin/analytics/export.csv')
@login_required
def admin_analytics_export():
    guard = admin_required()
    if guard:
        return guard
    try:
        days = int(request.args.get('days', '') or 0)
    except ValueError:
        days = 0
    if days not in (7, 30, 90):
        days = 0

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['reference', 'booked_at', 'status', 'movie', 'theatre',
                     'screen', 'show_date', 'show_time', 'seats', 'seat_count',
                     'ticket_amount', 'convenience_fee', 'gst', 'total_amount',
                     'method', 'paid_at'])
    for b in _analytics_bookings(days):
        payment = b.payment
        writer.writerow([
            b.reference,
            b.booked_at.strftime('%Y-%m-%d %H:%M') if b.booked_at else '',
            b.status,
            b.showtime.movie.title,
            b.showtime.theater,
            b.showtime.screen_label,
            b.showtime.show_date.isoformat(),
            b.showtime.show_time,
            b.seats,
            len(b.seat_list),
            f"{b.ticket_amount:.2f}",
            f"{b.convenience_fee:.2f}",
            f"{b.gst:.2f}",
            f"{b.total_amount:.2f}",
            payment.method if payment else '',
            b.paid_at.strftime('%Y-%m-%d %H:%M') if b.paid_at else '',
        ])

    stamp = datetime.utcnow().strftime('%Y%m%d_%H%M')
    resp = app.response_class(out.getvalue(), mimetype='text/csv')
    resp.headers['Content-Disposition'] = f'attachment; filename=cinewave_bookings_{stamp}.csv'
    return resp


# ====================== INITIALIZATION ======================

SAMPLE_LAYOUT = {
    "screen_label": "Screen 1",
    "screen": {"width_m": 18, "height_m": 9.7},
    "classes": [
        {"code": "RECLINER", "name": "Recliner", "price": 320,
         "rows": [{"label": "A", "count": 10, "aisles_after": [5], "blocked": []},
                  {"label": "B", "count": 10, "aisles_after": [5], "blocked": []}]},
        {"code": "EXECUTIVE", "name": "Executive", "price": 220,
         "rows": [{"label": "C", "count": 16, "aisles_after": [4, 12], "blocked": []},
                  {"label": "D", "count": 16, "aisles_after": [4, 12], "blocked": []}]},
        {"code": "NORMAL", "name": "Normal", "price": 150,
         "rows": [{"label": "E", "count": 18, "aisles_after": [4, 14], "blocked": []},
                  {"label": "F", "count": 18, "aisles_after": [4, 14], "blocked": []}]},
    ],
}


def auto_migrate():
    """
    Adds any newly introduced column to an existing SQLite file so your old
    vizag_movies.db keeps working instead of throwing OperationalError.
    """
    insp = inspect(db.engine)
    wanted = {
        'user': [('phone', 'VARCHAR(15)'), ('points', 'INTEGER DEFAULT 100'),
                 ('email_verified', 'BOOLEAN DEFAULT 1'),
                 ('email_otp_hash', 'VARCHAR(256)'),
                 ('email_otp_expires_at', 'DATETIME'),
                 ('email_otp_sent_at', 'DATETIME'),
                 ('email_otp_attempts', 'INTEGER DEFAULT 0'),
                 ('created_at', 'DATETIME'), ('bio', "VARCHAR(250) DEFAULT 'Cinema lover & movie enthusiast.'")],
        'movie': [('language', "VARCHAR(50)"), ('certificate', "VARCHAR(10)"),
                  ('rating', 'FLOAT DEFAULT 8.5'),
                  ('is_upcoming', 'BOOLEAN DEFAULT 0'), ('release_date', 'DATE'),
                  ('is_rerelease', 'BOOLEAN DEFAULT 0'), ('moods_json', "TEXT DEFAULT '[]'"),
                  ('tmdb_id', 'INTEGER'), ('cast_json', 'TEXT'),
                  ('youtube_trailer_key', 'VARCHAR(20)'),
                  ('trailer_video_path', 'VARCHAR(300)')],
        'theater': [('city', "VARCHAR(80)"), ('address', "VARCHAR(400)")],
        'showtime': [('screen_id', 'INTEGER'), ('price_overrides_json', 'TEXT')],
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
    db.session.commit()

    # backfill references + status for pre-existing bookings
    for b in Booking.query.filter((Booking.reference.is_(None))).all():
        b.reference = 'CW' + secrets.token_hex(4).upper()
        b.status = 'PAID'
    db.session.commit()


def seed_sample_movies():
    """Seeds popular Vizag blockbusters with showtimes and reviews if not present."""
    admin = User.query.filter_by(username='admin').first()
    inox_screen = Screen.query.filter(Screen.name.contains('1')).first()
    jag_theater = Theater.query.filter(Theater.name.contains('Jagadamba')).first()
    jag_screen = jag_theater.screens[0] if (jag_theater and jag_theater.screens) else inox_screen
    cine_theater = Theater.query.filter(Theater.name.contains('Cinepolis')).first()
    cine_screen = cine_theater.screens[0] if (cine_theater and cine_theater.screens) else inox_screen

    u1 = User.query.filter_by(username='rahul_vizag').first()
    if not u1:
        u1 = User(username='rahul_vizag', email='rahul@vizag.com')
        u1.set_password('pass123')
        db.session.add(u1)
    u2 = User.query.filter_by(username='ananya_k').first()
    if not u2:
        u2 = User(username='ananya_k', email='ananya@vizag.com')
        u2.set_password('pass123')
        db.session.add(u2)
    db.session.commit()

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
            'times': ['10:30 AM', '02:00 PM', '06:15 PM', '09:45 PM'],
            'reviews': [
                {'user': u1, 'rating': 5.0, 'review': 'Peak mass cinema! The Jathara sequence is pure goosebumps. Allu Arjun national award worthy performance.', 'has_spoiler': False},
                {'user': u2, 'rating': 4.5, 'review': 'Shekhawat revenge plan in the climax sets up Pushpa 3 Rampage perfectly! Watch out for the truck chase scene.', 'has_spoiler': True}
            ]
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
            'times': ['02:15 PM', '06:45 PM', '10:15 PM'],
            'reviews': [
                {'user': u1, 'rating': 5.0, 'review': 'Mind-blowing interval block and Anirudh BGM shook Jagadamba 70MM!', 'has_spoiler': False},
                {'user': u2, 'rating': 4.5, 'review': 'Major plot twist at the climax when Bhaira discovers who actually survived the sea fight! Do not leave before post-credits.', 'has_spoiler': True}
            ]
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
            'times': ['11:00 AM', '03:30 PM', '07:30 PM'],
            'reviews': [
                {'user': u1, 'rating': 5.0, 'review': 'World-class visuals! Amitabh Bachchan as Ashwatthama steals the whole show.', 'has_spoiler': False},
                {'user': u2, 'rating': 5.0, 'review': 'The Karna reveal in the climax battle was absolute goosebumps! Prabhas transformation is insane.', 'has_spoiler': True}
            ]
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
            'times': ['01:30 PM', '06:00 PM', '09:45 PM'],
            'reviews': [
                {'user': u1, 'rating': 4.5, 'review': 'Shankar style grandeur and Ram Charan in top form. Thaman songs are energetic.', 'has_spoiler': False}
            ]
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

        # Add sample ratings if none exist
        if not movie.user_ratings:
            for r in m_data['reviews']:
                mr = MovieRating(
                    user_id=r['user'].id,
                    movie_id=movie.id,
                    rating=r['rating'],
                    review=r['review'],
                    has_spoiler=r['has_spoiler']
                )
                db.session.add(mr)

    db.session.commit()


def init_db():
    with app.app_context():
        db.create_all()
        auto_migrate()
        seed_vizag_theaters(db, Theater, Screen)
        seed_sample_movies()

        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            admin_user = User(username='admin', email='admin@cinewave.com', is_admin=True)
            admin_password = os.environ.get('ADMIN_PASSWORD') or secrets.token_urlsafe(18)
            admin_user.set_password(admin_password)
            db.session.add(admin_user)
            db.session.commit()
            create_wallet(admin_user, balance=10000)
            if os.environ.get('ADMIN_PASSWORD'):
                print("Admin account created from ADMIN_PASSWORD environment setting.")
            else:
                print(f"Admin account created. One-time password: {admin_password}")

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

        mode = "LIVE Razorpay" if payments.is_live_gateway() else "MOCK gateway (no keys set)"
        print(f"Payments: {mode}")


if __name__ == '__main__':
    init_db()
    debug_enabled = os.environ.get('FLASK_DEBUG', '').strip().lower() in {'1', 'true', 'yes'}
    app.run(debug=debug_enabled)
