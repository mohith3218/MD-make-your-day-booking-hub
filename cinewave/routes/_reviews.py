from collections import defaultdict
from datetime import datetime

from flask import abort, flash, request
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..services.reviews import plain_text


def reported_ids(report_model, reviews):
    if not current_user.is_authenticated or not reviews:
        return set()
    return {row.review_id for row in report_model.query.with_entities(report_model.review_id)
            .filter(report_model.user_id == current_user.id,
                    report_model.review_id.in_([review.id for review in reviews]))}


def report_review(report_model, review):
    if review.user_id == current_user.id:
        abort(403)
    try:
        reason = plain_text(request.form.get('reason', ''), 300)
    except ValueError as error:
        abort(400, description=str(error))
    if not reason:
        abort(400, description='Enter a reason for reporting this review.')
    review_id = review.id
    db.session.add(report_model(review_id=review_id, user_id=current_user.id, reason=reason))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if not report_model.query.filter_by(review_id=review_id, user_id=current_user.id).first():
            raise
        flash('You already reported this review.')
    else:
        flash('Your report was sent to the moderation team.')


def moderation_context(model, query, report_model, event_model, *options):
    statuses = {
        'visible': db.and_(model.hidden.is_(False), model.withdrawn_at.is_(None)),
        'reported': model.id.in_(db.select(report_model.review_id).where(report_model.resolved_at.is_(None))),
        'hidden': db.and_(model.hidden.is_(True), model.withdrawn_at.is_(None)),
        'withdrawn': model.withdrawn_at.is_not(None),
        'verified': db.and_(model.verified.is_(True), model.is_demo.is_(False)),
        'demo': model.is_demo.is_(True),
        'unverified': db.and_(model.verified.is_(False), model.is_demo.is_(False)),
    }
    view = request.args.get('view', 'all')
    if view not in statuses:
        view = 'all'
    counts = query.with_entities(db.func.count(model.id).label('total'), *(
        db.func.count(db.case((condition, 1))).label(name) for name, condition in statuses.items()
    )).one()
    if view in statuses:
        query = query.filter(statuses[view])
    page = query.options(joinedload(model.user), *options).order_by(
        model.created_at.desc(), model.id.desc()).paginate(per_page=15)
    ids = [review.id for review in page.items]
    reports, history = defaultdict(list), defaultdict(list)
    for item in report_model.query.filter(report_model.review_id.in_(ids), report_model.resolved_at.is_(None)):
        reports[item.review_id].append(item)
    for event in event_model.query.options(joinedload(event_model.admin)).filter(
            event_model.review_id.in_(ids)).order_by(event_model.id.desc()):
        history[event.review_id].append(event)
    return dict(page=page, view=view, counts=counts, reports=reports, history=history)


def moderate_review(query, report_model, event_model, review_id):
    action = request.form.get('action')
    if action not in ('hide', 'restore', 'resolve'):
        abort(400)
    review = query.filter_by(id=review_id).with_for_update().first_or_404()
    if review.withdrawn_at and action != 'resolve':
        abort(409, description='The author withdrew this review.')
    if action != 'resolve':
        review.hidden = action == 'hide'
    if action != 'restore':
        report_model.query.filter_by(review_id=review.id, resolved_at=None).update(
            {'resolved_at': datetime.utcnow()})
    db.session.add(event_model(review_id=review.id, admin_id=current_user.id, action=action))
    db.session.commit()
    flash('Moderation decision saved.')
