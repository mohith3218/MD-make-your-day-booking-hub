import json
import payments
import secrets
from cinewave.data import SNACK_ITEMS
from cinewave.extensions import db
from cinewave.models import Booking, Payment, User, WalletTransaction
from cinewave.services import (
    _has_split_progress,
    _load_pending,
    finalise_paid_booking,
    get_wallet,
    release_booking,
)
from datetime import datetime
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func as sa_func

from . import bp


@bp.route('/checkout/<reference>/update_extras', methods=['POST'])
@login_required
def update_booking_extras(reference):
    booking = _load_pending(reference)
    if _has_split_progress(booking):
        flash('Extras are locked after a group member starts paying. Finish or cancel the split first.')
        return redirect(url_for('booking.checkout', reference=reference))
    if booking.status != 'PENDING' or booking.is_expired:
        flash("This booking is expired.")
        return redirect(url_for('booking.book', showtime_id=booking.showtime_id))

    selected_snack_ids = set(request.form.getlist('snacks'))
    try:
        requested_points = int(request.form.get('redeem_points', 0))
    except (TypeError, ValueError):
        flash("Enter a valid CinePass points amount.")
        return redirect(url_for('booking.checkout', reference=reference))

    snacks_chosen = []
    snack_total = 0.0
    for s in SNACK_ITEMS:
        if s['id'] in selected_snack_ids:
            snacks_chosen.append(s)
            snack_total += s['price']

    user = User.query.filter_by(id=current_user.id).with_for_update().first()
    reserved_elsewhere = (db.session.query(sa_func.coalesce(sa_func.sum(Booking.points_redeemed), 0))
        .filter(Booking.user_id == user.id, Booking.status == 'PENDING',
                Booking.expires_at > datetime.utcnow(), Booking.id != booking.id).scalar() or 0)
    user_pts = max(0, (user.points or 0) - reserved_elsewhere)
    # Never let a crafted negative value increase a user's points at payment time.
    redeem_pts = min(max(0, requested_points), user_pts)
    discount = float(redeem_pts)

    base_subtotal = booking.ticket_amount + snack_total
    amounts = payments.compute_amounts(base_subtotal, len(booking.seat_list))
    final_total = max(1.0, amounts['total'] - discount)

    booking.snacks_json = json.dumps(snacks_chosen)
    booking.points_redeemed = redeem_pts
    booking.total_amount = round(final_total, 2)
    db.session.commit()

    flash("Booking updated with selected snacks and CinePass discount!")
    return redirect(url_for('booking.checkout', reference=booking.reference))


@bp.route('/pay/wallet/<reference>', methods=['POST'])
@login_required
def pay_with_wallet(reference):
    booking = _load_pending(reference)
    if _has_split_progress(booking):
        flash('A group split is in progress. Finish it from the Squad Pay invite link.')
        return redirect(url_for('booking.checkout', reference=reference))
    if booking.status != 'PENDING' or booking.is_expired:
        flash("This booking can no longer be paid.")
        return redirect(url_for('profile.dashboard'))

    claimed = Booking.query.filter_by(id=booking.id, status='PENDING').update(
        {Booking.status: 'PROCESSING'}, synchronize_session=False)
    if claimed != 1:
        db.session.rollback()
        db.session.refresh(booking)
        if booking.status == 'PAID':
            return redirect(url_for('booking.ticket', reference=reference))
        flash('This payment is already being processed. Please refresh shortly.')
        return redirect(url_for('profile.dashboard'))
    booking.status = 'PROCESSING'

    wallet = get_wallet(current_user)
    if wallet.balance < booking.total_amount:
        db.session.rollback()
        flash("Not enough wallet balance. Recharge or pay by UPI / card.")
        return redirect(url_for('booking.checkout', reference=reference))

    wallet.balance = round(wallet.balance - booking.total_amount, 2)
    db.session.add(WalletTransaction(wallet_id=wallet.id,
                                     amount=booking.total_amount,
                                     type='PAYMENT',
                                     description=f'Tickets {booking.reference}'))
    payment = Payment(booking_id=booking.id, gateway='wallet', method='wallet',
                      amount=booking.total_amount, status='CREATED',
                      order_id=f'wallet_{booking.reference}',
                      payment_id=f'wal_{secrets.token_hex(6)}')
    db.session.add(payment)
    ok, msg = finalise_paid_booking(booking, payment, wallet_debit_uncommitted=True)
    flash(msg)
    return redirect(url_for('booking.ticket', reference=reference) if ok
                    else url_for('booking.book', showtime_id=booking.showtime_id))


@bp.route('/pay/gateway/<reference>', methods=['POST'])
@login_required
def pay_gateway(reference):
    """Create a local demo order and open the simulator; never contact a provider."""
    booking = _load_pending(reference)
    if _has_split_progress(booking):
        flash('A group split is in progress. Finish it from the Squad Pay invite link.')
        return redirect(url_for('booking.checkout', reference=reference))
    if booking.status != 'PENDING' or booking.is_expired:
        flash("This booking can no longer be paid.")
        return redirect(url_for('profile.dashboard'))
    existing_payment = booking.payment
    if (existing_payment and existing_payment.gateway == 'mock'
            and existing_payment.status == 'CREATED'
            and existing_payment.amount == booking.total_amount):
        return redirect(url_for('booking.pay_mock_confirmation', reference=reference), code=303)

    method = request.form.get('method', 'upi')
    if method not in payments.DEMO_METHODS - {'split'}:
        abort(400, description='Unsupported demo payment method.')
    try:
        order = payments.create_order(
            booking.total_amount,
            receipt=booking.reference,
            notes={'reference': booking.reference,
                   'movie': booking.showtime.movie.title,
                   'seats': booking.seats})
    except payments.PaymentGatewayError as exc:
        flash(str(exc))
        return redirect(url_for('booking.checkout', reference=reference))

    payment = booking.payment or Payment(booking_id=booking.id)
    payment.gateway = order['gateway']
    payment.order_id = order['order_id']
    payment.amount = booking.total_amount
    payment.method = method
    payment.status = 'CREATED'
    payment.raw_response = order.get('raw')
    db.session.add(payment)
    db.session.commit()
    return redirect(url_for('booking.pay_mock_confirmation', reference=reference), code=303)


@bp.route('/pay/mock/<reference>')
@login_required
def pay_mock_confirmation(reference):
    """Read-only continuation for an order already created by the POST route."""
    booking = _load_pending(reference)
    if booking.status == 'PAID':
        return redirect(url_for('booking.ticket', reference=reference))
    payment = booking.payment
    if (booking.status != 'PENDING' or booking.is_expired or not payment
            or payment.gateway != 'mock' or payment.status != 'CREATED'
            or payment.amount != booking.total_amount
            or not (payment.order_id or '').startswith('order_mock_')):
        flash('This demo payment is no longer active. Review checkout to continue.')
        return redirect(url_for('booking.checkout', reference=reference), code=303)
    order = {'order_id': payment.order_id, 'amount_paise': int(round(payment.amount * 100)),
             'currency': 'INR', 'gateway': payment.gateway}
    return render_template('booking/pay_mock.html', booking=booking, order=order,
        movie=booking.showtime.movie, showtime=booking.showtime, method=payment.method,
        user=current_user)


@bp.route('/pay/callback', methods=['POST'])
@login_required
def payment_callback():
    """Compatibility endpoint for signed local demo responses only."""
    reference = request.form.get('reference', '')
    order_id = request.form.get('order_id', '')
    payment_id = request.form.get('payment_id', '')
    signature = request.form.get('signature', '')
    failed = request.form.get('failed') == '1'
    error_msg = request.form.get('error_message', 'Payment failed at the gateway.')

    booking = _load_pending(reference)
    payment = booking.payment
    if not payment:
        flash("No payment was started for this booking.")
        return redirect(url_for('booking.checkout', reference=reference))

    if payment.gateway != 'mock' or not (payment.order_id or '').startswith('order_mock_'):
        abort(404)
    if booking.status == 'PAID':
        return redirect(url_for('booking.ticket', reference=reference))
    if booking.status != 'PENDING' or booking.is_expired:
        if booking.is_expired:
            release_booking(booking, 'EXPIRED')
        return redirect(url_for('profile.dashboard'))
    if payment.status != 'CREATED' or payment.amount != booking.total_amount:
        abort(400, description='Demo order does not match the booking.')

    if order_id != payment.order_id:
        flash("Payment could not be matched to this booking. Please retry checkout.")
        return redirect(url_for('booking.checkout', reference=reference))

    if failed:
        payment.status = 'FAILED'
        payment.error_message = error_msg[:300]
        db.session.commit()
        release_booking(booking, 'FAILED')
        flash(f"{error_msg} Your seats have been released.")
        return redirect(url_for('booking.book', showtime_id=booking.showtime_id))

    # Authenticate a demo response; this is not evidence of financial settlement.
    if not payments.verify_signature(order_id, payment_id, signature):
        payment.status = 'FAILED'
        payment.error_message = 'Signature verification failed'
        db.session.commit()
        release_booking(booking, 'FAILED')
        flash("Payment could not be verified. Nothing was charged.")
        return redirect(url_for('booking.book', showtime_id=booking.showtime_id))

    payment.payment_id = payment_id
    payment.signature = signature
    db.session.commit()

    ok, msg = finalise_paid_booking(booking, payment)
    flash(msg)
    return redirect(url_for('booking.ticket', reference=reference) if ok
                    else url_for('booking.book', showtime_id=booking.showtime_id))


@bp.route('/pay/simulate/<reference>', methods=['POST'])
@login_required
def simulate(reference):
    """Sandbox 'Pay Now' / 'Simulate failure' buttons on the mock gateway page."""
    if not payments.mock_payments_enabled():
        abort(404)
    booking = _load_pending(reference)
    payment = booking.payment
    if (not payment or not payment.order_id or payment.gateway != 'mock'
            or not payment.order_id.startswith('order_mock_')):
        abort(404)
    if payment.amount != booking.total_amount:
        abort(400, description='Demo order does not match the booking.')
    if booking.status != 'PENDING' or booking.is_expired:
        flash("This booking can no longer be paid.")
        return redirect(url_for('booking.checkout', reference=reference))
    if request.form.get('outcome', 'success') not in {'success', 'fail'}:
        abort(400, description='Unsupported demo outcome.')
    succeed = request.form.get('outcome', 'success') == 'success'
    result = payments.simulate_payment(payment.order_id,
                                       method=payment.method or 'upi',
                                       succeed=succeed)
    if not result['ok']:
        payment.status = 'FAILED'
        payment.error_message = result['error']
        db.session.commit()
        release_booking(booking, 'FAILED')
        flash(f"{result['error']} Your seats have been released.")
        return redirect(url_for('booking.book', showtime_id=booking.showtime_id))

    if not payments.verify_signature(payment.order_id, result['payment_id'], result['signature']):
        abort(400, description='Invalid demo response.')
    payment.payment_id = result['payment_id']
    payment.signature = result['signature']
    db.session.commit()

    ok, msg = finalise_paid_booking(booking, payment)
    flash(msg)
    return redirect(url_for('booking.ticket', reference=reference) if ok
                    else url_for('booking.book', showtime_id=booking.showtime_id))
