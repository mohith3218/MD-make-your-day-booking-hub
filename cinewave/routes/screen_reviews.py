from collections import defaultdict
from datetime import datetime
from unicodedata import category

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from theatre_discovery import validate_booking_context
from ..extensions import db
from ..models import Booking, Screen, ScreenReview, ScreenReviewModeration, ScreenReviewReport
from ..services.screen_reviews import (QUESTIONS, eligible_screen, public_reviews,
                                       review_distribution, review_summaries)

bp = Blueprint('screen_reviews', __name__)


def owned_booking(reference):
    booking = Booking.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    validate_booking_context(booking.showtime)
    return booking


def plain_text(value, limit):
    text = value.replace('\r\n', '\n').replace('\r', '\n').strip()
    if len(text) > limit or any(category(char) in {'Cc', 'Cs'} and char not in '\n\t' for char in text):
        raise ValueError(f'Use up to {limit} characters of plain text.')
    return text


@bp.route('/booking/<reference>/screen-review', methods=['GET', 'POST'])
@login_required
def edit(reference):
    booking = owned_booking(reference)
    screen = eligible_screen(booking, current_user.id)
    if screen is None:
        abort(403, description='Screen reviews require an eligible paid booking after the show ends.')
    review = booking.screen_review
    if review and (review.withdrawn_at or review.screen_id != screen.id or review.theater_id != screen.theater_id):
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
            if creating:
                review = ScreenReview(booking_id=booking.id, user_id=current_user.id,
                                      theater_id=screen.theater_id, screen_id=screen.id, verified=True)
                db.session.add(review)
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
    dismissed = session.get('dismissed_screen_reviews', [])
    session['dismissed_screen_reviews'] = ([item for item in dismissed if item != booking.id] + [booking.id])[-50:]
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
@login_required
def detail(theatre_id, screen_id):
    screen = Screen.query.filter_by(id=screen_id, theater_id=theatre_id).first_or_404()
    orders = {
        'recent': (ScreenReview.created_at.desc(),),
        'highest': (ScreenReview.overall_rating.desc(), ScreenReview.created_at.desc()),
        'lowest': (ScreenReview.overall_rating.asc(), ScreenReview.created_at.desc()),
    }
    sort = request.args.get('sort', 'recent')
    if sort not in orders:
        sort = 'recent'
    verified_only = request.args.get('verified') == '1'
    query = public_reviews().filter(ScreenReview.screen_id == screen.id)
    if verified_only:
        query = query.filter(ScreenReview.verified.is_(True))
    page = query.options(joinedload(ScreenReview.user)).order_by(
        *orders[sort], ScreenReview.id.desc()).paginate(per_page=10)
    reported = {row.review_id for row in ScreenReviewReport.query.with_entities(ScreenReviewReport.review_id)
                .filter(ScreenReviewReport.user_id == current_user.id,
                        ScreenReviewReport.review_id.in_([review.id for review in page.items]))}
    score = review_summaries(ScreenReview.screen_id, [screen.id]).get(screen.id)
    return render_template('screen_reviews.html', screen=screen, score=score, page=page, sort=sort,
                           verified_only=verified_only, reported=reported,
                           distribution=review_distribution(screen.id))


@bp.post('/screen-reviews/<int:review_id>/report')
@login_required
def report(review_id):
    review = public_reviews().filter_by(id=review_id).first_or_404()
    if review.user_id == current_user.id:
        abort(403)
    try:
        reason = plain_text(request.form.get('reason', ''), 300)
    except ValueError as error:
        abort(400, description=str(error))
    if not reason:
        abort(400, description='Enter a reason for reporting this review.')
    target = url_for('.detail', theatre_id=review.theater_id, screen_id=review.screen_id)
    db.session.add(ScreenReviewReport(review_id=review.id, user_id=current_user.id, reason=reason))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if not ScreenReviewReport.query.filter_by(review_id=review_id, user_id=current_user.id).first():
            raise
        flash('You already reported this review.')
    else:
        flash('Your report was sent to the moderation team.')
    return redirect(target, code=303)


@bp.get('/admin/screen-reviews')
@login_required
def moderation():
    if not current_user.is_admin:
        abort(403)
    statuses = {
        'visible': db.and_(ScreenReview.hidden.is_(False), ScreenReview.withdrawn_at.is_(None)),
        'hidden': db.and_(ScreenReview.hidden.is_(True), ScreenReview.withdrawn_at.is_(None)),
        'withdrawn': ScreenReview.withdrawn_at.is_not(None),
        'verified': ScreenReview.verified.is_(True),
        'unverified': ScreenReview.verified.is_(False),
        'reported': ScreenReview.id.in_(db.select(ScreenReviewReport.review_id)
                                       .where(ScreenReviewReport.resolved_at.is_(None))),
    }
    view = request.args.get('view', 'all')
    query = ScreenReview.query
    if view in statuses:
        query = query.filter(statuses[view])
    page = query.options(joinedload(ScreenReview.user), joinedload(ScreenReview.screen),
                         joinedload(ScreenReview.theater)).order_by(
        ScreenReview.created_at.desc(), ScreenReview.id.desc()).paginate(per_page=15)
    counts = db.session.query(db.func.count().label('total'), *(
        db.func.count(db.case((condition, 1))).label(name) for name, condition in statuses.items()
    )).select_from(ScreenReview).one()
    ids = [review.id for review in page.items]
    reports, history = defaultdict(list), defaultdict(list)
    for item in ScreenReviewReport.query.filter(ScreenReviewReport.review_id.in_(ids),
                                                ScreenReviewReport.resolved_at.is_(None)):
        reports[item.review_id].append(item)
    for event in ScreenReviewModeration.query.options(joinedload(ScreenReviewModeration.admin)).filter(
            ScreenReviewModeration.review_id.in_(ids)).order_by(ScreenReviewModeration.id.desc()):
        history[event.review_id].append(event)
    return render_template('admin_screen_reviews.html', page=page, view=view, counts=counts,
                           reports=reports, history=history)


@bp.post('/admin/screen-reviews/<int:review_id>/moderate')
@login_required
def moderate(review_id):
    if not current_user.is_admin:
        abort(403)
    action = request.form.get('action')
    if action not in ('hide', 'restore', 'resolve'):
        abort(400)
    review = ScreenReview.query.filter_by(id=review_id).with_for_update().first_or_404()
    if review.withdrawn_at and action != 'resolve':
        abort(409, description='The author withdrew this review.')
    if action != 'resolve':
        review.hidden = action == 'hide'
    if action != 'restore':
        ScreenReviewReport.query.filter_by(review_id=review.id, resolved_at=None).update(
            {'resolved_at': datetime.utcnow()})
    db.session.add(ScreenReviewModeration(review_id=review.id, admin_id=current_user.id, action=action))
    db.session.commit()
    flash('Moderation decision saved.')
    return redirect(url_for('.moderation'), code=303)
