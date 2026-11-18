import json
from datetime import datetime
from sqlalchemy.exc import IntegrityError
import seat_layout as sl
from ..extensions import db
from ..models import Booking, BookedSeat, Payment, SeatHold, SeatLock, Showtime, SplitContribution, User, WalletTransaction
from .wallet import get_wallet
from .email import dispatch_ticket_delivery



def purge_expired_holds():
    """Release stale locks and expire unpaid bookings. Cheap, safe to call often."""
    now = datetime.utcnow()
    stale = SeatLock.query.filter(SeatLock.expires_at <= now).all()
    removed_holds = SeatHold.query.filter(SeatHold.expires_at <= now).delete(
        synchronize_session=False)
    for lk in stale:
        db.session.delete(lk)

    dead = Booking.query.filter(Booking.status == 'PENDING',
                                Booking.expires_at <= now).all()
    for b in dead:
        b.status = 'EXPIRED'
    if stale or dead or removed_holds:
        db.session.commit()


def show_seat_prices(showtime, *, pricing_info=None):
    """Trusted seat-price map shared by discovery and checkout."""
    layout = showtime.layout
    dyn = pricing_info if pricing_info is not None else showtime.dynamic_pricing_info
    effective_overrides = {}
    base_overrides = showtime.price_overrides
    for cls in layout.get("classes", []):
        code = cls.get("code", "STD")
        base_p = float(base_overrides.get(code, cls.get("price", 0)))
        effective_overrides[code] = round(base_p * dyn['factor'], 2)

    blocked = {seat for cls in layout.get('classes', []) for row in cls.get('rows', [])
               for seat in (row.get('blocked') or [])}
    return {seat: price for seat, price in sl.seat_price_map(layout, effective_overrides).items()
            if seat not in blocked}


def price_seats(showtime, seat_ids):
    """Return (ticket_total, [{'id','class','price'}...]) including dynamic surge/discount."""
    layout = showtime.layout
    prices = show_seat_prices(showtime)
    classes = sl.seat_class_map(layout)
    meta = [{'id': s, 'class': classes.get(s, 'Standard'),
             'price': float(prices.get(s, 0))} for s in seat_ids]
    return round(sum(m['price'] for m in meta), 2), meta


def release_booking(booking, status='CANCELLED'):
    """Free the held seats for a booking that will not be paid."""
    if booking.lock_token:
        SeatHold.query.filter_by(token=booking.lock_token).delete(synchronize_session=False)
        lock = SeatLock.query.filter_by(token=booking.lock_token).first()
        if lock:
            db.session.delete(lock)
    # Split payments are sandbox-only. Mark any captured test shares as returned
    # so an expired or cancelled group cannot leave a stale paid indicator.
    for contribution in SplitContribution.query.filter_by(booking_id=booking.id).all():
        if contribution.status == 'PAID':
            contribution.status = 'REFUNDED'
        elif contribution.status == 'CREATED':
            contribution.status = 'OPEN'
            contribution.user_id = None
    booking.status = status
    db.session.commit()


def commit_seats(booking):
    """
    Final, atomic step after a successful payment: write the seats into
    BookedSeat. The unique(showtime_id, seat_id) constraint means that if
    someone beat us to a seat, this raises and we can refund instead of
    double-selling.
    """
    for seat in booking.seat_list:
        db.session.add(BookedSeat(showtime_id=booking.showtime_id,
                                  seat_id=seat, booking_id=booking.id))
    db.session.flush()


def finalise_paid_booking(booking, payment, *, wallet_debit_uncommitted=False):
    """Commit seats, mark paid, drop the lock. Returns (ok, message)."""
    if not payment.is_demo:
        return False, 'Only demo payments can be completed by this application.'
    try:
        if booking.status == 'PENDING':
            claimed = Booking.query.filter_by(id=booking.id, status='PENDING').update(
                {Booking.status: 'PROCESSING'}, synchronize_session=False)
            if claimed != 1:
                db.session.rollback()
                db.session.refresh(booking)
                if booking.status == 'PAID':
                    return True, 'Payment was already confirmed.'
                return False, 'This booking is already being processed.'
            booking.status = 'PROCESSING'
        commit_seats(booking)
        booking.status = 'PAID'
        booking.paid_at = datetime.utcnow()
        # Legacy state names describe the booking workflow, not bank settlement.
        payment.status = 'CAPTURED'
        metadata = json.loads(payment.raw_response or '{}')
        metadata.update(demo=True, settled=False)
        payment.raw_response = json.dumps(metadata)
        if booking.lock_token:
            SeatHold.query.filter_by(token=booking.lock_token).delete(synchronize_session=False)
            lock = SeatLock.query.filter_by(token=booking.lock_token).first()
            if lock:
                db.session.delete(lock)

        account = User.query.filter_by(id=booking.user_id).with_for_update().first()
        # Deduct redeemed points first while holding the balance row used by conversion.
        if booking.points_redeemed and booking.points_redeemed > 0:
            account.points = max(0, (account.points or 0) - booking.points_redeemed)

        # CinePass points reward: 10 points per ₹100 spent (20 points/₹100 for Rewatch Champion bookings!)
        is_rewatch = False
        if booking.user and booking.showtime and booking.showtime.movie:
            prev_cnt = (Booking.query.filter_by(user_id=booking.user_id, status='PAID')
                        .join(Showtime)
                        .filter(Showtime.movie_id == booking.showtime.movie_id, Booking.id != booking.id)
                        .count())
            if prev_cnt > 0:
                is_rewatch = True

        pts_multiplier = 2 if is_rewatch else 1
        earned_pts = int((booking.total_amount / 10) * pts_multiplier)
        if earned_pts > 0:
            account.points = (account.points or 0) + earned_pts
        db.session.commit()
        # Dispatch digital receipt / e-ticket
        dispatch_ticket_delivery(booking)
        msg = "Demo payment successful — no real money charged" + (" 🎉 (Rewatch Bonus: 2X CinePass Points Earned!)" if is_rewatch else "")
        return True, msg
    except IntegrityError:
        db.session.rollback()
        if wallet_debit_uncommitted and payment.method == 'wallet':
            failed_booking = db.session.get(Booking, booking.id)
            if failed_booking:
                failed_booking.status = 'FAILED'
                failed_payment = db.session.get(Payment, payment.id) if payment.id else None
                if not failed_payment:
                    failed_payment = Payment(booking_id=failed_booking.id, gateway='wallet',
                        method='wallet', amount=failed_booking.total_amount, status='FAILED',
                        order_id=f'wallet_{failed_booking.reference}',
                        error_message='Seat became unavailable; wallet debit was rolled back')
                    db.session.add(failed_payment)
                else:
                    failed_payment.status = 'FAILED'
                    failed_payment.error_message = 'Seat became unavailable; wallet debit was rolled back'
                db.session.commit()
            return False, 'A selected seat was taken. Your wallet was not charged; please choose again.'
        booking.status = 'FAILED'
        payment.status = 'REFUNDED'
        payment.error_message = 'Seat taken before capture - amount refunded'
        # money back: wallet payments are returned instantly
        if payment.method == 'wallet':
            wallet = get_wallet(booking.user)
            wallet.balance += booking.total_amount
            db.session.add(WalletTransaction(wallet_id=wallet.id,
                                             amount=booking.total_amount,
                                             type='REFUND',
                                             description=f'Refund for {booking.reference}'))
        if payment.method == 'split':
            for contribution in SplitContribution.query.filter_by(booking_id=booking.id).all():
                if contribution.status == 'PAID':
                    contribution.status = 'REFUNDED'
            if booking.lock_token:
                SeatHold.query.filter_by(token=booking.lock_token).delete(synchronize_session=False)
                lock = SeatLock.query.filter_by(token=booking.lock_token).first()
                if lock:
                    db.session.delete(lock)
        db.session.commit()
        return False, ("Someone completed payment for one of those seats first. "
                       "Your money has been refunded - please pick different seats.")
