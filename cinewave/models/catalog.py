from datetime import date, datetime, timedelta
import json
import requests
from sqlalchemy import func as sa_func
import seat_layout as sl
from vizag_theaters import correct_jagadamba_levels
from ..extensions import db
from ..time import cinema_now
from .booking import BookedSeat, SeatHold
from ..config import TMDB_API_KEY, TMDB_BASE_URL, TMDB_IMAGE_BASE



class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    poster = db.Column(db.String(500), nullable=True)
    backdrop = db.Column(db.String(500), nullable=True)
    featured_order = db.Column(db.Integer, nullable=True)
    language = db.Column(db.String(50), nullable=True, default='Telugu')
    certificate = db.Column(db.String(10), nullable=True, default='U/A')
    rating = db.Column(db.Float, default=8.5)
    is_upcoming = db.Column(db.Boolean, default=False)
    is_rerelease = db.Column(db.Boolean, default=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
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


class MovieHypeVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    level = db.Column(db.String(20), nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                            onupdate=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'movie_id',
                         name='uq_movie_hype_user_movie'),)
    user = db.relationship('User', backref=db.backref('movie_hype_votes', lazy=True,
                           cascade='all, delete-orphan'))
    movie = db.relationship('Movie', backref=db.backref('hype_votes', lazy=True,
                            cascade='all, delete-orphan'))

    @classmethod
    def counts_for(cls, movie_id):
        counts = {level: 0 for level in ('HYPED', 'SUPER_HYPED', 'EXTREME_HYPED')}
        for level, count in db.session.query(cls.level, sa_func.count(cls.id)).filter_by(
                movie_id=movie_id).group_by(cls.level):
            if level in counts:
                counts[level] = count
        return counts


class DirectoryVerificationMixin:
    """Evidence-backed review metadata for a venue or individual screen."""
    verification_status = db.Column(db.String(20), nullable=False, default='unverified',
                                    server_default='unverified')
    verification_source_url = db.Column(db.String(500), nullable=True)
    verification_notes = db.Column(db.Text, nullable=True)
    verification_reviewed_at = db.Column(db.DateTime, nullable=True)
    verification_reviewed_by_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', name='fk_directory_verification_reviewed_by_user'),
        nullable=True)

    @property
    def is_verified(self):
        return self.verification_status == 'verified' and bool(self.verification_source_url)


class Theater(DirectoryVerificationMixin, db.Model):
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


class Screen(DirectoryVerificationMixin, db.Model):
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
            layout = json.loads(self.layout_json or '{}')
            return correct_jagadamba_levels(layout, self.theater.name, self.name)
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
        q = SeatHold.query.filter(SeatHold.showtime_id == self.id,
                                  SeatHold.expires_at > now)
        if exclude_token:
            q = q.filter(SeatHold.token != exclude_token)
        return {hold.seat_id for hold in q.all()}

    @property
    def seats_left(self):
        taken = self.booked_seat_ids() | self.held_seat_ids()
        return max(0, sl.count_seats(self.layout) - len(taken))

    @property
    def show_datetime(self):
        """Parse show_date + show_time into a datetime object. Supports HH:MM and H:MM AM/PM formats."""
        for fmt in ('%H:%M', '%I:%M %p', '%I:%M%p'):
            try:
                t = datetime.strptime((self.show_time or '').strip(), fmt).time()
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
            return cinema_now() > end_dt
        return self.show_date < cinema_now().date()

    @property
    def status(self):
        """Returns 'upcoming', 'live', or 'ended' based on current time."""
        dt = self.show_datetime
        if not dt:
            return 'unavailable'
        now = cinema_now()
        duration = self.movie.duration if self.movie else 0
        end_dt = dt + timedelta(minutes=duration)
        if now < dt:
            return 'upcoming'
        elif now <= end_dt:
            return 'live'
        return 'ended'

    @property
    def dynamic_pricing_info(self):
        return self.pricing_info()

    def pricing_info(self, *, booked_count=None):
        """
        Calculates real-time surge or early-bird pricing adjustments based on occupancy and show time.
        """
        total = sl.count_seats(self.layout) or 1
        if booked_count is None:
            booked_count = len(self.booked_seat_ids())
        occupancy_pct = (booked_count / max(1, total)) * 100.0

        today = cinema_now().date()
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
