from flask import session
from sqlalchemy import case, func

from ..extensions import db
from ..models import ScreenReview

QUESTIONS = (
    ('sound_rating', 'How was the sound quality?'),
    ('ac_rating', 'How was the air conditioning?'),
    ('comfort_rating', 'How comfortable were the seats?'),
    ('overall_rating', 'How would you rate the overall screen experience?'),
)


def eligible_screen(booking, user_id):
    if booking.user_id != user_id or booking.status != 'PAID':
        return None
    show = booking.showtime
    if not show or not show.screen or not show.movie or not show.movie.duration or show.movie.duration < 1:
        return None
    if show.status != 'ended':
        return None
    payment = booking.payment
    if payment and (payment.is_demo or payment.status != 'CAPTURED'):
        return None
    return show.screen


def review_invitation(booking, user_id):
    if not eligible_screen(booking, user_id):
        return None
    if booking.screen_review:
        return 'edit' if booking.screen_review.withdrawn_at is None else None
    if booking.id in session.get('dismissed_screen_reviews', []):
        return 'dismissed'
    return 'invite'


def public_reviews():
    return ScreenReview.query.filter(ScreenReview.hidden.is_(False), ScreenReview.withdrawn_at.is_(None))


def review_summaries(group, ids):
    """One aggregate query. Each review contributes once to its screen or theatre."""
    if not ids:
        return {}
    selected = (
        group, func.count(ScreenReview.id).label('count'),
        func.sum(case((ScreenReview.verified.is_(True), 1), else_=0)).label('verified'),
        func.sum(ScreenReview.overall_rating).label('overall_total'),
        *(func.avg(getattr(ScreenReview, field)).label(field) for field, _ in QUESTIONS),
    )
    return {row[0]: row for row in public_reviews().with_entities(*selected)
            .filter(group.in_(ids)).group_by(group)}


def combined_theatre_score(screen_scores):
    count = sum(score.count for score in screen_scores.values())
    if not count:
        return None
    return {'count': count,
            'overall_rating': sum(score.overall_total for score in screen_scores.values()) / count}


def review_distribution(screen_id):
    counts = dict(public_reviews().with_entities(ScreenReview.overall_rating, func.count(ScreenReview.id))
                  .filter(ScreenReview.screen_id == screen_id).group_by(ScreenReview.overall_rating))
    return {rating: counts.get(rating, 0) for rating in range(5, 0, -1)}
