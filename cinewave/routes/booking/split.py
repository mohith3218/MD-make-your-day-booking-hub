import payments
from cinewave.config import timedelta
from cinewave.extensions import db
from cinewave.models import Booking, Payment, SeatHold, SeatLock, SplitContribution
from cinewave.services import _ensure_split_slots, finalise_paid_booking, release_booking
from datetime import datetime
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp


@bp.route('/split-pay/<token>')
def split_pay(token):
    """Public invite view: a random token grants access to the split summary only."""
    booking = Booking.query.filter_by(split_token=token).first_or_404()
    if len(booking.seat_list) < 2:
        abort(404)
    if booking.is_expired:
        release_booking(booking, 'EXPIRED')
    rows = _ensure_split_slots(booking) if booking.status == 'PENDING' else (
        SplitContribution.query.filter_by(booking_id=booking.id)
        .order_by(SplitContribution.share_index).all())
    db.session.commit()
    user_share = None
    if current_user.is_authenticated:
        user_share = SplitContribution.query.filter_by(
            booking_id=booking.id, user_id=current_user.id).first()
    paid_count = sum(row.status == 'PAID' for row in rows)
    open_count = sum(row.status == 'OPEN' and row.user_id is None for row in rows)
    return render_template('booking/split_pay.html', booking=booking,
                           movie=booking.showtime.movie,
                           showtime=booking.showtime,
                           rows=rows, user_share=user_share,
                           paid_count=paid_count, open_count=open_count,
                           share_amount=booking.per_person_amount,
                           split_gateway_available=payments.gateway_name() == 'mock')


@bp.route('/split-pay/<token>/start', methods=['POST'])
@login_required
def start_split_payment(token):
    booking = Booking.query.filter_by(split_token=token).first_or_404()
    if not payments.mock_payments_enabled():
        flash('Demo split payments are disabled.')
        return redirect(url_for('booking.split_pay', token=token))
    if booking.status != 'PENDING' or booking.is_expired:
        if booking.is_expired:
            release_booking(booking, 'EXPIRED')
        flash('This split invite is no longer payable.')
        return redirect(url_for('booking.split_pay', token=token))
    if booking.payment and booking.payment.status == 'CREATED':
        flash('A full booking payment is already in progress. Ask the booking holder to finish or cancel it first.')
        return redirect(url_for('booking.split_pay', token=token))

    rows = _ensure_split_slots(booking)
    contribution = SplitContribution.query.filter_by(
        booking_id=booking.id, user_id=current_user.id).first()
    if contribution and contribution.status == 'PAID':
        flash('Your share has already been paid.')
        return redirect(url_for('booking.split_pay', token=token))
    if (contribution and contribution.status == 'CREATED' and contribution.gateway == 'mock'
            and contribution.order_id):
        return redirect(url_for('booking.split_payment_confirmation', token=token,
                                contribution_id=contribution.id), code=303)
    if not contribution:
        contribution = next((row for row in rows
                             if row.status == 'OPEN' and row.user_id is None), None)
        if not contribution:
            flash('All remaining shares are already being paid or have been completed.')
            db.session.commit()
            return redirect(url_for('booking.split_pay', token=token))
        contribution.user_id = current_user.id
        contribution.status = 'CREATED'

    order = payments.create_order(
        contribution.amount,
        receipt=f'{booking.reference}-S{contribution.share_index}',
        notes={'reference': booking.reference,
               'split_share': str(contribution.share_index),
               'movie': booking.showtime.movie.title})
    contribution.gateway = 'mock'
    contribution.method = 'split'
    contribution.order_id = order['order_id']
    contribution.created_at = datetime.utcnow()
    booking.expires_at = max(booking.expires_at, datetime.utcnow() + timedelta(minutes=15))
    lock = SeatLock.query.filter_by(token=booking.lock_token).first() if booking.lock_token else None
    if lock:
        lock.expires_at = booking.expires_at
        SeatHold.query.filter_by(token=booking.lock_token).update(
            {SeatHold.expires_at: booking.expires_at}, synchronize_session=False)
    db.session.commit()
    return redirect(url_for('booking.split_payment_confirmation', token=token,
                            contribution_id=contribution.id), code=303)


@bp.route('/split-pay/<token>/confirm/<int:contribution_id>')
@login_required
def split_payment_confirmation(token, contribution_id):
    booking = Booking.query.filter_by(split_token=token).first_or_404()
    contribution = SplitContribution.query.filter_by(id=contribution_id,
        booking_id=booking.id, user_id=current_user.id).first_or_404()
    if (booking.status != 'PENDING' or booking.is_expired
            or contribution.status != 'CREATED' or contribution.gateway != 'mock'
            or not (contribution.order_id or '').startswith('order_mock_')):
        flash('This split payment is no longer active. Review the invite to continue.')
        return redirect(url_for('booking.split_pay', token=token), code=303)
    order = {'order_id': contribution.order_id,
             'amount_paise': int(round(contribution.amount * 100)), 'currency': 'INR'}
    return render_template('booking/split_pay_mock.html', booking=booking,
        movie=booking.showtime.movie, contribution=contribution,
        order=order, user=current_user)


@bp.route('/split-pay/<token>/simulate/<int:contribution_id>', methods=['POST'])
@login_required
def simulate_split_payment(token, contribution_id):
    booking = Booking.query.filter_by(split_token=token).first_or_404()
    contribution = SplitContribution.query.filter_by(
        id=contribution_id, booking_id=booking.id,
        user_id=current_user.id).first_or_404()
    if (payments.gateway_name() != 'mock' or booking.status != 'PENDING'
            or contribution.status != 'CREATED' or booking.is_expired):
        flash('This split payment is no longer active.')
        return redirect(url_for('booking.split_pay', token=token))

    if request.form.get('outcome', 'success') not in {'success', 'fail'}:
        abort(400, description='Unsupported demo outcome.')
    succeeded = request.form.get('outcome', 'success') == 'success'
    result = payments.simulate_payment(contribution.order_id,
                                       method='split', succeed=succeeded)
    if not result['ok']:
        contribution.status = 'OPEN'
        contribution.user_id = None
        contribution.error_message = result.get('error', 'Payment failed.')[:300]
        db.session.commit()
        flash('That share did not go through. It is available for another attempt.')
        return redirect(url_for('booking.split_pay', token=token))

    if not payments.verify_signature(contribution.order_id,
                                     result['payment_id'], result['signature']):
        contribution.status = 'OPEN'
        contribution.user_id = None
        contribution.error_message = 'Signature verification failed'
        db.session.commit()
        flash('The share payment could not be verified. Please try again.')
        return redirect(url_for('booking.split_pay', token=token))

    contribution.payment_id = result['payment_id']
    contribution.signature = result['signature']
    contribution.status = 'PAID'
    db.session.commit()

    rows = SplitContribution.query.filter_by(booking_id=booking.id).all()
    paid_count = sum(row.status == 'PAID' for row in rows)
    if paid_count == len(booking.seat_list):
        payment = booking.payment or Payment(booking_id=booking.id)
        payment.gateway = 'mock-split'
        payment.method = 'split'
        payment.order_id = f'split_{booking.reference}'
        payment.payment_id = ','.join(row.payment_id or '' for row in rows)
        payment.amount = booking.total_amount
        payment.status = 'CREATED'
        db.session.add(payment)
        db.session.commit()
        ok, message = finalise_paid_booking(booking, payment)
        flash(message)
        return redirect(url_for('booking.ticket', reference=booking.reference) if ok
                        else url_for('booking.split_pay', token=token))

    booking.expires_at = max(booking.expires_at,
                             datetime.utcnow() + timedelta(minutes=15))
    lock = SeatLock.query.filter_by(token=booking.lock_token).first() if booking.lock_token else None
    if lock:
        lock.expires_at = booking.expires_at
        SeatHold.query.filter_by(token=booking.lock_token).update(
            {SeatHold.expires_at: booking.expires_at}, synchronize_session=False)
    db.session.commit()
    flash(f'Your share is in. {paid_count} of {len(booking.seat_list)} shares paid.')
    return redirect(url_for('booking.split_pay', token=token))
