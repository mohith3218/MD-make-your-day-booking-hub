import secrets
from flask import abort, url_for
from flask_login import current_user
from ..extensions import db
from ..models import Booking, SplitContribution



def _load_pending(reference):
    booking = Booking.query.filter_by(reference=reference).first_or_404()
    if booking.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    return booking


def _split_share_amounts(total_amount, count):
    """Split the total into cent-accurate shares whose sum is exact."""
    count = max(1, int(count))
    total_cents = int(round(float(total_amount or 0) * 100))
    base, remainder = divmod(total_cents, count)
    return [(base + (1 if index < remainder else 0)) / 100
            for index in range(count)]


def _ensure_split_invite(booking):
    if len(booking.seat_list) < 2:
        return None
    if not booking.split_token:
        booking.split_token = secrets.token_urlsafe(24)
    booking.is_split_pay = True
    return booking.split_token


def _ensure_split_slots(booking):
    """Create or refresh unclaimed shares; never rewrite a share after payment starts."""
    count = len(booking.seat_list)
    if count < 2:
        return []
    rows = (SplitContribution.query.filter_by(booking_id=booking.id)
            .order_by(SplitContribution.share_index).all())
    if any(row.status in ('CREATED', 'PAID') for row in rows):
        return rows

    amounts = _split_share_amounts(booking.total_amount, count)
    if len(rows) != count:
        for row in rows:
            db.session.delete(row)
        rows = [SplitContribution(booking_id=booking.id, share_index=index,
                                  amount=amount, status='OPEN')
                for index, amount in enumerate(amounts, start=1)]
        db.session.add_all(rows)
    else:
        for row, amount in zip(rows, amounts):
            row.amount = amount
    return rows


def _has_split_progress(booking):
    return SplitContribution.query.filter(
        SplitContribution.booking_id == booking.id,
        SplitContribution.status.in_(('CREATED', 'PAID'))).first() is not None


def _split_invite_url(booking):
    return url_for('booking.split_pay', token=booking.split_token, _external=True)
