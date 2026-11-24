from datetime import datetime, timedelta
import json
import secrets
from ..config import SEAT_LOCK_MINUTES
from ..extensions import db



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
    screen_review_dismissed_at = db.Column(db.DateTime)
    ticket_email_sent_at = db.Column(db.DateTime, nullable=True)
    ticket_email_error = db.Column(db.String(300), nullable=True)
    expires_at = db.Column(db.DateTime,
                           default=lambda: datetime.utcnow() + timedelta(minutes=SEAT_LOCK_MINUTES))

    user = db.relationship('User', backref=db.backref('bookings', lazy=True))
    showtime = db.relationship('Showtime', backref=db.backref('bookings', lazy=True))
    payment = db.relationship('Payment', backref='booking', uselist=False,
                              cascade='all, delete-orphan')

    __table_args__ = (db.Index('ix_booking_user_status_booked', 'user_id', 'status', 'booked_at'),
                      db.Index('ix_booking_showtime_status', 'showtime_id', 'status'))

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

    __table_args__ = (db.Index('ix_seat_lock_showtime_expiry', 'showtime_id', 'expires_at'),)

    @property
    def seat_list(self):
        return [s for s in (self.seats or '').split(',') if s]


class SeatHold(db.Model):
    """Normalized temporary reservation for one seat, guarded by a unique key."""
    id = db.Column(db.Integer, primary_key=True)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    seat_id = db.Column(db.String(10), nullable=False)
    token = db.Column(db.String(40), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('showtime_id', 'seat_id', name='uq_seat_hold_showtime_seat'),
        db.Index('ix_seat_hold_expiry', 'expires_at'),
        db.Index('ix_seat_hold_token', 'token'),
    )


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


class PartySession(db.Model):
    """Watch Together room; clients poll every two seconds (not WebSockets)."""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False, default=lambda: secrets.token_hex(3).upper())
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    host_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='ACTIVE')

    showtime = db.relationship('Showtime', backref=db.backref('parties', lazy=True))
    host = db.relationship('User', foreign_keys=[host_id])


class PartyMember(db.Model):
    """Individual participant in a Watch Together party."""
    id = db.Column(db.Integer, primary_key=True)
    party_id = db.Column(db.Integer, db.ForeignKey('party_session.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user_name = db.Column(db.String(80), nullable=False)
    avatar_color = db.Column(db.String(20), default='#FF2E63')
    selected_seats = db.Column(db.String(200), default='')
    last_ping = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.Index('uq_party_member_user', 'party_id', 'user_id', unique=True),)

    party = db.relationship('PartySession', backref=db.backref('members', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id])
