from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from theatre_discovery import validate_booking_context
from ._reviews import moderate_review, moderation_context, report_review, reported_ids
from ..extensions import db
from ..models import Booking, Screen, ScreenReview, ScreenReviewModeration, ScreenReviewReport
from ..services.screen_reviews import (QUESTIONS, eligible_screen, public_reviews,
                                       review_distribution, review_summaries)

from ..services.reviews import completed_booking_source, filtered_reviews, plain_text

bp = Blueprint('screen_reviews', __name__)


def owned_booking(reference):
    booking = Booking.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if booking.showtime is not None:
        validate_booking_context(booking.showtime)
    return booking


@bp.route('/booking/<reference>/screen-review', methods=['GET', 'POST'])
@login_required
def edit(reference):
    booking = owned_booking(reference)
    screen = eligible_screen(booking, current_user.id)
    if screen is None:
        abort(403, description='Screen reviews require an eligible paid booking after the show ends.')
    review = booking.screen_review
    if review and (review.withdrawn_at or review.user_id != current_user.id
                   or review.screen_id != screen.id or review.theater_id != screen.theater_id):
        abort(409, description='This review is no longer editable.')

    values = {field: getattr(review, field, None) for field, _ in QUESTIONS}
    values['review_text'] = (review.review_text or '') if review else ''
    errors = {}
    if request.method == 'POST':
        for field, _ in QUESTIONS:
            submitted = request.form.getlist(field)
            raw = submitted[0] if submitted else ''
            if len(submitted) > 1 or (raw == '' and field == 'overall_rating') or (
                    raw and raw not in ('1', '2', '3', '4', '5')):
                errors[field] = 'Choose a whole-star rating from 1 to 5.'
            values[field] = int(raw) if raw in ('1', '2', '3', '4', '5') else None
        values['review_text'] = request.form.get('review_text', '')
        try:
            values['review_text'] = plain_text(values['review_text'], 1000) or None
        except ValueError as error:
            errors['review_text'] = str(error)
            values['review_text'] = values['review_text'][:1000]
        if not errors:
            creating = review is None
            source = completed_booking_source(booking, current_user.id)
            if creating:
                review = ScreenReview(booking_id=booking.id, user_id=current_user.id,
                                      theater_id=screen.theater_id, screen_id=screen.id)
                db.session.add(review)
            review.verified = source == 'verified'
            review.is_demo = source == 'demo'
            for field, value in values.items():
                setattr(review, field, value)
            review.updated_at = datetime.utcnow()
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                if not creating or not ScreenReview.query.filter_by(booking_id=booking.id).first():
                    raise
                flash('A review already exists for this ticket. You can edit it here.')
                return redirect(url_for('.edit', reference=reference), code=303)
            flash('Your review was saved. It is currently hidden.' if review.hidden else 'Your screen review was saved.')
            return redirect(url_for('booking.ticket', reference=reference), code=303)
    return render_template('screen_review_form.html', booking=booking, screen=screen,
                           review=review, questions=QUESTIONS, values=values, errors=errors), 422 if errors else 200


@bp.post('/booking/<reference>/screen-review/dismiss')
@login_required
def dismiss(reference):
    booking = owned_booking(reference)
    if eligible_screen(booking, current_user.id) is None or booking.screen_review:
        abort(403)
    booking.screen_review_dismissed_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for('booking.ticket', reference=reference), code=303)


@bp.post('/booking/<reference>/screen-review/withdraw')
@login_required
def withdraw(reference):
    review = owned_booking(reference).screen_review
    if review is None or review.user_id != current_user.id:
        abort(404)
    if review.withdrawn_at is None:
        review.withdrawn_at = datetime.utcnow()
        review.updated_at = review.withdrawn_at
        db.session.commit()
    flash('Your review was removed from public view.')
    return redirect(url_for('booking.ticket', reference=reference), code=303)


@bp.get('/theatres/<int:theatre_id>/screens/<int:screen_id>/reviews')
def detail(theatre_id, screen_id):
    screen = Screen.query.filter_by(id=screen_id, theater_id=theatre_id).first_or_404()
    query, filters = filtered_reviews(
        public_reviews().filter_by(screen_id=screen.id), ScreenReview, ScreenReview.overall_rating)
    page = query.options(joinedload(ScreenReview.user)).paginate(per_page=10)
    score = review_summaries(ScreenReview.screen_id, [screen.id]).get(screen.id)
    return render_template('screen_reviews.html', screen=screen, score=score, page=page, filters=filters,
                           reported=reported_ids(ScreenReviewReport, page.items),
                           distribution=review_distribution(screen.id))


@bp.post('/screen-reviews/<int:review_id>/report')
@login_required
def report(review_id):
    review = public_reviews().filter_by(id=review_id).first_or_404()
    report_review(ScreenReviewReport, review)
    return redirect(url_for('.detail', theatre_id=review.theater_id, screen_id=review.screen_id), code=303)


@bp.get('/admin/screen-reviews')
@login_required
def moderation():
    if not current_user.is_admin:
        abort(403)
    context = moderation_context(
        ScreenReview, ScreenReview.query, ScreenReviewReport, ScreenReviewModeration,
        joinedload(ScreenReview.screen), joinedload(ScreenReview.theater))
    return render_template('admin_screen_reviews.html', review_type='screen', **context)


@bp.post('/admin/screen-reviews/<int:review_id>/moderate')
@login_required
def moderate(review_id):
    if not current_user.is_admin:
        abort(403)
    moderate_review(ScreenReview.query, ScreenReviewReport, ScreenReviewModeration, review_id)
    return redirect(url_for('.moderation'), code=303)
