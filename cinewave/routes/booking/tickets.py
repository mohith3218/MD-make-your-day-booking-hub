import io
from cinewave.extensions import db
from cinewave.models import BookedSeat, Booking, WalletTransaction
from cinewave.services import _load_pending, dispatch_ticket_delivery, get_wallet, release_booking
from cinewave.services.movie_reviews import movie_review_states
from cinewave.services.screen_reviews import review_invitation
from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from . import bp


@bp.route('/booking/<reference>/cancel', methods=['POST'])
@login_required
def cancel_booking(reference):
    booking = _load_pending(reference)
    if booking.status == 'PENDING':
        release_booking(booking, 'CANCELLED')
        flash("Booking cancelled and seats released.")
    return redirect(url_for('profile.dashboard'))


@bp.route('/booking/<reference>/refund', methods=['POST'])
@login_required
def refund_booking(reference):
    booking = Booking.query.filter_by(reference=reference).first_or_404()
    if booking.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    if booking.status != 'PAID':
        flash("Only confirmed, paid bookings are eligible for cancellation and refund.")
        return redirect(url_for('booking.ticket', reference=reference))

    if booking.showtime.is_past:
        flash("⛔ This show has already ended or started. Past shows cannot be cancelled.")
        return redirect(url_for('booking.ticket', reference=reference))

    # Cancellation policy: 90% refund of the ticket amount
    cancellation_fee_rate = 0.10
    refund_amount = round(booking.ticket_amount * (1.0 - cancellation_fee_rate), 2)

    # Free up booked seats
    BookedSeat.query.filter_by(booking_id=booking.id).delete()

    # Credit refund to user's wallet
    wallet = get_wallet(booking.user)
    wallet.balance = round(wallet.balance + refund_amount, 2)
    db.session.add(WalletTransaction(
        wallet_id=wallet.id,
        amount=refund_amount,
        type='REFUND',
        description=f'Self-service cancellation refund for {booking.reference}'
    ))

    booking.status = 'CANCELLED'
    db.session.commit()

    flash(f"✅ Booking {booking.reference} cancelled successfully. ₹{refund_amount:.2f} refunded to your CineWave Wallet!")
    return redirect(url_for('wallet.wallet_page'))


@bp.route('/ticket/<reference>/resend_delivery', methods=['POST'])
@login_required
def resend_ticket_delivery(reference):
    booking = Booking.query.filter_by(reference=reference).first_or_404()
    if booking.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    if booking.status != 'PAID':
        flash('Only confirmed bookings have an e-ticket to send.')
        return redirect(url_for('booking.ticket', reference=reference))
    if dispatch_ticket_delivery(booking):
        flash(f"E-ticket with QR pass sent to {booking.user.email}.")
    else:
        flash('The booking is confirmed, but email delivery failed. Check the mail settings and retry.')
    return redirect(url_for('booking.ticket', reference=reference))


@bp.route('/ticket/<reference>')
@login_required
def ticket(reference):
    booking = Booking.query.filter_by(reference=reference).first_or_404()
    if booking.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    return render_template('booking/ticket.html', booking=booking,
                           showtime=booking.showtime,
                           movie=booking.showtime.movie,
                           screen_review_state=review_invitation(booking, current_user.id),
                           movie_review_state=movie_review_states([booking], current_user.id).get(booking.id),
                           payment=booking.payment)


@bp.route('/ticket/<reference>/qr.png')
@login_required
def ticket_qr(reference):
    """QR code printed on the e-ticket: scanned at the gate to verify the booking."""
    booking = Booking.query.filter_by(reference=reference).first_or_404()
    if booking.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    payload = (f"CINEWAVE|{booking.reference}|{booking.showtime.movie.title}|"
               f"{booking.showtime.theater}|{booking.showtime.show_date}|"
               f"{booking.showtime.show_time}|{booking.seats}")
    if booking.payment and booking.payment.is_demo:
        payload = 'DEMO|' + payload
    try:
        import qrcode
        img = qrcode.make(payload)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue(), 200, {'Content-Type': 'image/png',
                                     'Cache-Control': 'no-store'}
    except ImportError:
        # qrcode not installed - fall back to a 1x1 transparent pixel
        import base64
        pixel = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8'
            '/58BAwAI/AL+4d1cAAAAAElFTkSuQmCC')
        return pixel, 200, {'Content-Type': 'image/png'}
