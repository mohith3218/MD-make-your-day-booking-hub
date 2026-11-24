from flask import session
from sqlalchemy import case, func

from ..models import ScreenReview
from .reviews import completed_booking_source, published_reviews, rating_distribution

QUESTIONS = (
    ('sound_rating', 'How was the sound quality?'),
    ('ac_rating', 'How was the air conditioning?'),
    ('comfort_rating', 'How comfortable were the seats?'),
    ('overall_rating', 'How would you rate the overall screen experience?'),
)


def eligible_screen(booking, user_id):
    if not completed_booking_source(booking, user_id):
        return None
    show = booking.showtime
    screen = show.screen
    if not screen or not screen.theater:
        return None
    if (show.theater or '').strip().casefold() != screen.theater.name.strip().casefold():
        return None
    return screen


def review_invitation(booking, user_id):
    if not eligible_screen(booking, user_id):
        return None
    if booking.screen_review:
        return 'edit' if booking.screen_review.withdrawn_at is None else None
    if booking.screen_review_dismissed_at or booking.id in session.get('dismissed_screen_reviews', []):
        return None
    return 'invite'


def public_reviews():
    return published_reviews(ScreenReview)


def review_summaries(group, ids):
    """One aggregate query. Each review contributes once to its screen or theatre."""
    if not ids:
        return {}
    selected = (
        group, func.count(ScreenReview.id).label('count'),
        func.sum(case((ScreenReview.verified.is_(True), 1), else_=0)).label('verified'),
        func.sum(case((ScreenReview.is_demo.is_(True), 1), else_=0)).label('demo'),
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
    return rating_distribution(public_reviews().filter_by(screen_id=screen_id), ScreenReview.overall_rating)
