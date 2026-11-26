from datetime import datetime

from ..extensions import db


class ScreenReview(db.Model):
    """An experience review tied to the booking that establishes eligibility."""

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    theater_id = db.Column(db.Integer, db.ForeignKey('theater.id'), nullable=False)
    screen_id = db.Column(db.Integer, db.ForeignKey('screen.id'), nullable=False)
    overall_rating = db.Column(db.Integer, nullable=False)
    sound_rating = db.Column(db.Integer)
    ac_rating = db.Column(db.Integer)
    comfort_rating = db.Column(db.Integer)
    review_text = db.Column(db.String(1000))
    has_screen_feedback = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    theatre_rating = db.Column(db.Integer)
    theatre_review_text = db.Column(db.String(1000))
    theatre_updated_at = db.Column(db.DateTime)
    theatre_withdrawn_at = db.Column(db.DateTime)
    verified = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    is_demo = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    hidden = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    withdrawn_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    booking = db.relationship('Booking', backref=db.backref('screen_review', uselist=False))
    user = db.relationship('User')
    theater = db.relationship('Theater')
    screen = db.relationship('Screen')

    __table_args__ = (
        db.UniqueConstraint('booking_id', name='uq_screen_review_booking'),
        db.Index('ix_screen_review_screen_visibility', 'screen_id', 'hidden', 'withdrawn_at'),
        db.Index('ix_screen_review_theater_visibility', 'theater_id', 'hidden', 'withdrawn_at'),
        db.Index('uq_theatre_review_user_venue', 'user_id', 'theater_id', unique=True,
                 sqlite_where=db.text('theatre_rating IS NOT NULL'),
                 postgresql_where=db.text('theatre_rating IS NOT NULL')),
        *(db.CheckConstraint(f'{field} BETWEEN 1 AND 5 AND {field} = CAST({field} AS INTEGER)',
                             name=f'ck_screen_review_{field}')
          for field in ('overall_rating', 'sound_rating', 'ac_rating', 'comfort_rating')),
        db.CheckConstraint('length(review_text) <= 1000', name='ck_screen_review_text_length'),
    )


class ScreenReviewReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey('screen_review.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)

    __table_args__ = (
        db.UniqueConstraint('review_id', 'user_id', name='uq_screen_review_report_user'),
        db.Index('ix_screen_review_report_pending', 'resolved_at', 'review_id'),
    )


class ScreenReviewModeration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey('screen_review.id'), nullable=False, index=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    admin = db.relationship('User')


class MovieReviewReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey('movie_rating.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)

    __table_args__ = (
        db.UniqueConstraint('review_id', 'user_id', name='uq_movie_review_report_user'),
        db.Index('ix_movie_review_report_pending', 'resolved_at', 'review_id'),
    )


class MovieReviewModeration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey('movie_rating.id'), nullable=False, index=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    admin = db.relationship('User')
