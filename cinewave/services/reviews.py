from datetime import datetime, timezone
from unicodedata import category

from flask import request
from sqlalchemy import func
from ..time import CINEMA_TIMEZONE


def completed_booking_source(booking, user_id):
    """Return the source of an owned booking after its screening has ended."""
    if user_id is None or booking.user_id != user_id or booking.status != 'PAID':
        return None
    show = booking.showtime
    if not show or show.is_cancelled or not show.movie or not show.show_datetime:
        return None
    if show.actual_ended_at:
        start_utc = show.show_datetime.replace(tzinfo=CINEMA_TIMEZONE).astimezone(timezone.utc).replace(tzinfo=None)
        if not start_utc < show.actual_ended_at <= datetime.now(timezone.utc).replace(tzinfo=None):
            return None
    elif not show.movie.duration or show.movie.duration < 1 or show.status != 'ended':
        return None
    # Checkout can retain an earlier CREATED or FAILED payment when the method changes.
    if len(booking.captured_payments) != 1:
        return None
    payment = booking.captured_payments[0]
    if not (payment.gateway or '').strip():
        return None
    if payment.is_demo:
        return 'demo' if booking.paid_at else None
    return 'verified'


def plain_text(value, limit):
    value = value.replace('\r\n', '\n').replace('\r', '\n').strip()
    if len(value) > limit or any(category(char) in {'Cc', 'Cs'} and char not in '\n\t' for char in value):
        raise ValueError(f'Use up to {limit} characters of plain text.')
    return value


def published_reviews(model):
    return model.query.filter(model.hidden.is_(False), model.withdrawn_at.is_(None))


def rating_distribution(query, rating):
    counts = dict(query.with_entities(rating, func.count()).group_by(rating))
    return {stars: counts.get(stars, 0) for stars in range(5, 0, -1)}


def filtered_reviews(query, model, rating, *, spoilers=False):
    orders = {
        'recent': (model.created_at.desc(), model.id.desc()),
        'oldest': (model.created_at.asc(), model.id.asc()),
        'highest': (rating.desc(), model.created_at.desc(), model.id.desc()),
        'lowest': (rating.asc(), model.created_at.desc(), model.id.desc()),
    }
    filters = {'sort': request.args.get('sort', 'recent')}
    if filters['sort'] not in orders:
        filters['sort'] = 'recent'
    filters['rating'] = request.args.get('rating', '', type=int)
    if filters['rating'] in range(1, 6):
        query = query.filter(rating == filters['rating'])
    else:
        filters['rating'] = None
    filters['source'] = request.args.get('source') or ('verified' if request.args.get('verified') == '1' else '')
    if filters['source'] == 'verified':
        query = query.filter(model.verified.is_(True), model.is_demo.is_(False))
    elif filters['source'] == 'demo':
        query = query.filter(model.is_demo.is_(True))
    else:
        filters['source'] = None
    if spoilers:
        filters['spoiler'] = request.args.get('spoiler')
        if filters['spoiler'] in ('yes', 'no'):
            query = query.filter(model.has_spoiler.is_(filters['spoiler'] == 'yes'))
        else:
            filters['spoiler'] = None
    return query.order_by(*orders[filters['sort']]), filters
