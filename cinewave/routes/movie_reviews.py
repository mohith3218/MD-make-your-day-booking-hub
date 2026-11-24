from datetime import datetime

from flask import Blueprint, abort, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from theatre_discovery import validate_booking_context
from ._reviews import moderate_review, moderation_context, report_review, reported_ids
from ..extensions import db
from ..models import Booking, Movie, MovieRating, MovieReviewModeration, MovieReviewReport, User
from ..services.movie_reviews import (ACCESS_MESSAGE, booked_movie_reviews, eligible_booking,
                                      published_movie_reviews)
from ..services.reviews import completed_booking_source, filtered_reviews, plain_text, rating_distribution

bp = Blueprint('movie_reviews', __name__)


def owned_completed_booking(reference):
    booking = Booking.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    source = completed_booking_source(booking, current_user.id)
    if not source:
        abort(403, description=ACCESS_MESSAGE)
    validate_booking_context(booking.showtime)
    return booking, source


def own_rating(movie_id):
    return MovieRating.query.filter_by(movie_id=movie_id, user_id=current_user.id).first()


def review_values(data):
    errors = {}
    rating = str(data.get('rating', ''))
    values = {'rating': None, 'has_spoiler': data.get('has_spoiler') in (True, '1', 'on')}
    if rating not in ('1', '2', '3', '4', '5') or (
            hasattr(data, 'getlist') and len(data.getlist('rating')) != 1):
        errors['rating'] = 'Choose a whole-star rating from 1 to 5.'
    else:
        values['rating'] = int(rating)
    for field, limit in (('title', 120), ('review', 500)):
        submitted = data.get(field, '')
        try:
            if not isinstance(submitted, str):
                raise ValueError('Enter plain text.')
            values[field] = plain_text(submitted, limit) or None
        except ValueError as error:
            errors[field] = str(error)
            values[field] = submitted[:limit] if isinstance(submitted, str) else ''
    if not values['review']:
        errors.setdefault('review', 'Write a review before publishing.')
    return values, errors


def save_review(booking, source, review, values):
    created = review is None
    if created:
        # Preserve the first-rating CinePass reward and serialize point updates.
        account = db.session.get(User, current_user.id, with_for_update=True, populate_existing=True)
        account.points = (account.points or 0) + 5
        review = MovieRating(user_id=current_user.id, movie_id=booking.showtime.movie_id)
        db.session.add(review)
    if review.booking_id is None:
        review.created_at = datetime.utcnow()
        review.booking_id = booking.id
        review.verified = source == 'verified'
        review.is_demo = source == 'demo'
    review.updated_at = datetime.utcnow()
    for field, value in values.items():
        setattr(review, field, value)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if not created or own_rating(booking.showtime.movie_id) is None:
            raise
        return None
    return review


@bp.get('/movies/<int:movie_id>/reviews')
def detail(movie_id):
    movie = db.get_or_404(Movie, movie_id)
    booking = eligible_booking(movie_id, current_user.id if current_user.is_authenticated else None)
    if not booking:
        response = make_response(render_template('movie_reviews.html', movie=movie, access_message=ACCESS_MESSAGE), 403)
    else:
        query = published_movie_reviews().filter_by(movie_id=movie_id)
        score = query.with_entities(db.func.count(MovieRating.id).label('count'),
                                    db.func.avg(MovieRating.rating).label('overall_rating')).one()
        filtered, filters = filtered_reviews(query, MovieRating, MovieRating.rating, spoilers=True)
        page = filtered.options(joinedload(MovieRating.user)).paginate(per_page=10)
        response = make_response(render_template(
            'movie_reviews.html', movie=movie, booking=booking, page=page, filters=filters,
            score=score if score.count else None, distribution=rating_distribution(query, MovieRating.rating),
            reported=reported_ids(MovieReviewReport, page.items),
            reveal=request.args.get('reveal', type=int),
            review_state=movie_review_states_for_detail(movie_id)))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def movie_review_states_for_detail(movie_id):
    review = own_rating(movie_id)
    if review is None or review.booking_id is None:
        return 'invite'
    return 'withdrawn' if review.withdrawn_at else 'edit'


@bp.route('/booking/<reference>/movie-review', methods=['GET', 'POST'])
@login_required
def edit(reference):
    booking, source = owned_completed_booking(reference)
    movie = booking.showtime.movie
    existing = own_rating(movie.id)
    if existing and existing.withdrawn_at:
        abort(409, description='This movie review was withdrawn.')
    # Older ratings lack eligibility evidence. Start a fresh draft with a completed ticket.
    review = existing if existing and existing.booking_id is not None else None
    fields = ('rating', 'title', 'review', 'has_spoiler')
    values = {field: getattr(review, field, None) for field in fields}
    errors = {}
    if request.method == 'POST':
        if review and request.form.get('intent') == 'create':
            abort(409, description='You already reviewed this movie. Reopen the form to edit it.')
        values, errors = review_values(request.form)
        if not errors:
            saved = save_review(booking, source, existing, values)
            if saved is None:
                flash('You already reviewed this movie. You can edit your review here.')
                return redirect(url_for('.edit', reference=reference), code=303)
            flash('Your review was saved. It is currently hidden.' if saved.hidden else 'Your movie review was saved.')
            return redirect(url_for('.detail', movie_id=movie.id), code=303)
    return render_template('movie_review_form.html', booking=booking, movie=movie, review=review,
                           values=values, errors=errors), 422 if errors else 200


@bp.post('/booking/<reference>/movie-review/withdraw')
@login_required
def withdraw(reference):
    booking, _ = owned_completed_booking(reference)
    review = booked_movie_reviews().filter_by(movie_id=booking.showtime.movie_id,
                                              user_id=current_user.id).first_or_404()
    if review.withdrawn_at is None:
        review.withdrawn_at = datetime.utcnow()
        review.updated_at = review.withdrawn_at
        db.session.commit()
    flash('Your movie review was withdrawn.')
    return redirect(url_for('.detail', movie_id=review.movie_id), code=303)


@bp.post('/movie-reviews/<int:review_id>/report')
@login_required
def report(review_id):
    review = published_movie_reviews().filter_by(id=review_id).first_or_404()
    if not eligible_booking(review.movie_id, current_user.id):
        abort(403, description=ACCESS_MESSAGE)
    report_review(MovieReviewReport, review)
    return redirect(url_for('.detail', movie_id=review.movie_id), code=303)


@bp.get('/admin/movie-reviews')
@login_required
def moderation():
    if not current_user.is_admin:
        abort(403)
    context = moderation_context(MovieRating, booked_movie_reviews(), MovieReviewReport,
                                 MovieReviewModeration, joinedload(MovieRating.movie))
    return render_template('admin_screen_reviews.html', review_type='movie', **context)


@bp.post('/admin/movie-reviews/<int:review_id>/moderate')
@login_required
def moderate(review_id):
    if not current_user.is_admin:
        abort(403)
    moderate_review(booked_movie_reviews(), MovieReviewReport, MovieReviewModeration, review_id)
    return redirect(url_for('.moderation'), code=303)
