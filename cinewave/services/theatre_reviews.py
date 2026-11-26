"""Venue feedback using CineWave's existing booking-linked review records."""
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import Screen, ScreenReview
from .reviews import rating_distribution

EXPLICIT = and_(ScreenReview.theatre_rating.is_not(None), ScreenReview.theatre_withdrawn_at.is_(None))
THEATRE_RATING = case((EXPLICIT, ScreenReview.theatre_rating), else_=ScreenReview.overall_rating)
THEATRE_DATE = case((EXPLICIT, ScreenReview.theatre_updated_at), else_=ScreenReview.created_at)


def venue_reviews(theater_id=None):
    """Count one public review per person and venue, preferring explicit venue feedback."""
    screen = and_(ScreenReview.has_screen_feedback.is_(True), ScreenReview.withdrawn_at.is_(None))
    rows = select(
        ScreenReview.id,
        func.row_number().over(
            partition_by=(ScreenReview.user_id, ScreenReview.theater_id),
            order_by=(case((EXPLICIT, 0), else_=1), THEATRE_DATE.desc(), ScreenReview.id.desc()),
        ).label('position'),
    ).join(Screen, Screen.id == ScreenReview.screen_id).where(
        Screen.theater_id == ScreenReview.theater_id, ScreenReview.hidden.is_(False), or_(EXPLICIT, screen))
    if theater_id is not None:
        rows = rows.where(ScreenReview.theater_id == theater_id)
    ranked = rows.subquery()
    return ScreenReview.query.join(ranked, ranked.c.id == ScreenReview.id).filter(ranked.c.position == 1)


def venue_review_data(theater_id, sort, page_number):
    query = venue_reviews(theater_id)
    order = {'recent': THEATRE_DATE.desc(), 'highest': THEATRE_RATING.desc(), 'lowest': THEATRE_RATING.asc()}
    sort = sort if sort in order else 'recent'
    distribution = rating_distribution(query, THEATRE_RATING)
    count = sum(distribution.values())
    if not count:
        return {'score': None, 'distribution': distribution, 'page': None, 'sort': sort}
    average = sum(stars * quantity for stars, quantity in distribution.items()) / count
    page = query.options(joinedload(ScreenReview.user), joinedload(ScreenReview.screen)).order_by(
        order[sort], THEATRE_DATE.desc(), ScreenReview.id.desc()).paginate(
            page=page_number or 1, per_page=8, count=False)
    page.total = count
    return {'score': SimpleNamespace(count=count, overall_rating=average), 'distribution': distribution,
            'page': page, 'sort': sort}


def venue_averages(venue_ids):
    if not venue_ids:
        return {}
    values = venue_reviews().filter(ScreenReview.theater_id.in_(venue_ids)).with_entities(
        ScreenReview.theater_id, func.count(ScreenReview.id).label('count'),
        func.avg(THEATRE_RATING).label('overall_rating')).group_by(ScreenReview.theater_id)
    return {item.theater_id: item for item in values}


def own_venue_review(theater_id, user_id, *, lock=False):
    query = ScreenReview.query.filter_by(theater_id=theater_id, user_id=user_id).filter(
        ScreenReview.theatre_rating.is_not(None))
    return (query.with_for_update() if lock else query).first()


def store_venue_feedback(booking, source, screen, rating, comment):
    existing = own_venue_review(screen.theater_id, booking.user_id, lock=True)
    review = existing or booking.screen_review
    if review is None:
        review = ScreenReview(booking=booking, user_id=booking.user_id, screen_id=screen.id,
                              theater_id=screen.theater_id, overall_rating=rating, has_screen_feedback=False,
                              verified=source == 'verified', is_demo=source == 'demo')
        db.session.add(review)
    review.theatre_rating = rating
    review.theatre_review_text = comment
    review.theatre_withdrawn_at = None
    review.theatre_updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return review
