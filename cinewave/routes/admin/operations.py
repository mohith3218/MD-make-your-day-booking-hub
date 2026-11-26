from cinewave.models import Booking
from cinewave.models import RechargeRequest
from cinewave.models import WalletTransaction
from flask import current_app as app
from datetime import datetime
from cinewave.extensions import db
from flask import flash
from flask_login import login_required
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from cinewave.services import _analytics_bookings
from cinewave.services import _collect_analytics
from cinewave.services import admin_required
from cinewave.services import get_wallet
import csv
import io

from . import bp


@bp.route('/admin/recharges')
@login_required
def admin_recharges():
    guard = admin_required()
    if guard:
        return guard
    reqs = RechargeRequest.query.order_by(RechargeRequest.created_at.desc()).all()
    return render_template('admin/admin_recharges.html', requests=reqs)


@bp.route('/admin/recharges/<int:req_id>/<action>', methods=['POST'])
@login_required
def handle_recharge(req_id, action):
    guard = admin_required()
    if guard:
        return guard
    req = RechargeRequest.query.get_or_404(req_id)
    if req.status != 'PENDING':
        flash("Already processed.")
        return redirect(url_for('admin.admin_recharges'))

    if action == 'approve':
        wallet = get_wallet(req.user)
        wallet.balance = round(wallet.balance + req.amount, 2)
        db.session.add(WalletTransaction(wallet_id=wallet.id, amount=req.amount,
                                         type='RECHARGE',
                                         description='Admin approved recharge'))
        req.status = 'APPROVED'
        flash(f"₹{req.amount:.0f} credited to {req.user.username}.")
    elif action == 'reject':
        req.status = 'REJECTED'
        flash("Recharge request rejected.")
    db.session.commit()
    return redirect(url_for('admin.admin_recharges'))


@bp.route('/admin/bookings')
@login_required
def admin_bookings():
    guard = admin_required()
    if guard:
        return guard
    bookings = Booking.query.order_by(Booking.booked_at.desc()).limit(100).all()
    return render_template('admin/admin_bookings.html', bookings=bookings)


@bp.route('/admin/analytics')
@login_required
def admin_analytics():
    guard = admin_required()
    if guard:
        return guard
    try:
        days = int(request.args.get('days', '') or 0)
    except ValueError:
        days = 0
    if days not in (7, 30, 90):
        days = 0
    data = _collect_analytics(days)
    return render_template('admin/admin_analytics.html', a=data, days=days)


@bp.route('/admin/analytics/export.csv')
@login_required
def admin_analytics_export():
    guard = admin_required()
    if guard:
        return guard
    try:
        days = int(request.args.get('days', '') or 0)
    except ValueError:
        days = 0
    if days not in (7, 30, 90):
        days = 0

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['reference', 'booked_at', 'status', 'movie', 'theatre',
                     'screen', 'show_date', 'show_time', 'seats', 'seat_count',
                     'ticket_amount', 'convenience_fee', 'gst', 'total_amount',
                     'method', 'paid_at', 'payment_mode'])
    for b in _analytics_bookings(days):
        payment = b.payment
        writer.writerow([
            b.reference,
            b.booked_at.strftime('%Y-%m-%d %H:%M') if b.booked_at else '',
            b.status,
            b.showtime.movie.title,
            b.showtime.theater,
            b.showtime.screen_label,
            b.showtime.show_date.isoformat(),
            b.showtime.show_time,
            b.seats,
            len(b.seat_list),
            f"{b.ticket_amount:.2f}",
            f"{b.convenience_fee:.2f}",
            f"{b.gst:.2f}",
            f"{b.total_amount:.2f}",
            payment.method if payment else '',
            b.paid_at.strftime('%Y-%m-%d %H:%M') if b.paid_at else '',
            'DEMO - not settled' if payment and payment.is_demo else 'Historical record',
        ])

    stamp = datetime.utcnow().strftime('%Y%m%d_%H%M')
    resp = app.response_class(out.getvalue(), mimetype='text/csv')
    resp.headers['Content-Disposition'] = f'attachment; filename=cinewave_bookings_{stamp}.csv'
    return resp
