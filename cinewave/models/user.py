from datetime import datetime
import json
import re
import secrets
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash
from ..extensions import db



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
    alternative_id = db.Column(db.String(64), nullable=False,
                               default=lambda: secrets.token_urlsafe(32))

    __table_args__ = (db.UniqueConstraint('alternative_id', name='uq_user_alternative_id'),)

    def get_id(self):
        return self.alternative_id


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
        total_minutes = sum((m.duration or 0) for m in distinct_movies.values())
        hours_watched = round(total_minutes / 60, 1) if total_minutes else 0.0

        user_ratings = [r.rating for r in self.movie_ratings]
        if user_ratings:
            avg_rating = round(sum(user_ratings) / len(user_ratings), 1)
        elif distinct_movies:
            movie_ratings = [rating for m in distinct_movies.values() if (rating := m.display_rating) is not None]
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


class PasswordReset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    token_digest = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)


class PasswordResetThrottle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    throttle_key = db.Column(db.String(64), nullable=False, unique=True)
    window_started = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    attempts = db.Column(db.Integer, nullable=False, default=0)
