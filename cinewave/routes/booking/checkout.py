import payments
from cinewave.data import SNACK_ITEMS
from cinewave.extensions import db
from cinewave.services import (
    _ensure_split_invite,
    _ensure_split_slots,
    _has_split_progress,
    _load_pending,
    _split_invite_url,
    get_wallet,
    release_booking,
)
from flask import flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from cinewave.services.seat import can_edit_seat_hold

from . import bp


@bp.route('/checkout/<reference>')
@login_required
def checkout(reference):
    booking = _load_pending(reference)

    if booking.status == 'PAID':
        return redirect(url_for('booking.ticket', reference=reference))
    if booking.is_expired:
        release_booking(booking, 'EXPIRED')
        flash("Your seat hold expired. Please select seats again.")
        return redirect(url_for('booking.book', showtime_id=booking.showtime_id))
    if booking.status not in ('PENDING',):
        flash("This booking is no longer payable.")
        return redirect(url_for('profile.dashboard'))

    if len(booking.seat_list) > 1:
        _ensure_split_invite(booking)
        _ensure_split_slots(booking)
        db.session.commit()

    wallet = get_wallet(current_user)
    return render_template('booking/checkout.html', booking=booking,
                           showtime=booking.showtime,
                           movie=booking.showtime.movie,
                           wallet=wallet,
                           can_use_wallet=payments.mock_payments_enabled() and wallet.balance >= booking.total_amount,
                           gateway=payments.gateway_name(),
                           snack_items=SNACK_ITEMS,
                           split_pay_url=_split_invite_url(booking) if booking.split_token else '',
                           split_started=_has_split_progress(booking),
                           can_edit_seats=booking.user_id == current_user.id and can_edit_seat_hold(booking),
                           user_points=current_user.points or 0)
