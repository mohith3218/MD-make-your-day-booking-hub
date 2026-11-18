from flask import Blueprint
from ._support import *

bp = Blueprint("wallet", __name__)


@bp.route('/wallet')
@login_required
def wallet_page():
    wallet = get_wallet(current_user)
    txns = (WalletTransaction.query.filter_by(wallet_id=wallet.id)
            .order_by(WalletTransaction.timestamp.desc()).limit(20).all())
    reqs = (RechargeRequest.query.filter_by(user_id=current_user.id)
            .order_by(RechargeRequest.created_at.desc()).limit(10).all())
    reserved_points = (db.session.query(sa_func.coalesce(sa_func.sum(Booking.points_redeemed), 0))
        .filter(Booking.user_id == current_user.id, Booking.status == 'PENDING',
                Booking.expires_at > datetime.utcnow()).scalar() or 0)
    available_points = max(0, (current_user.points or 0) - reserved_points)
    return render_template('wallet.html', wallet=wallet, txns=txns, requests=reqs,
                           available_points=available_points,
                           conversion_key=secrets.token_urlsafe(24))


@bp.route('/wallet/convert-points', methods=['POST'])
@login_required
def wallet_convert_points():
    raw_key = request.form.get('idempotency_key', '')
    key = raw_key.strip()
    try:
        points = int(request.form.get('points', ''))
    except (TypeError, ValueError):
        flash('Enter a whole number of CinePass points to convert.')
        return redirect(url_for('wallet.wallet_page'), code=303)
    if not re.fullmatch(r'[A-Za-z0-9_-]{24,64}', key) or points <= 0 or points > 100000:
        flash('Enter a valid conversion amount and retry from your wallet.')
        return redirect(url_for('wallet.wallet_page'), code=303)

    db.session.rollback()
    try:
        with db.session.begin():
            existing = WalletPointConversion.query.filter_by(
                user_id=current_user.id, idempotency_key=key).first()
            if existing:
                result = existing
            else:
                user = User.query.filter_by(id=current_user.id).with_for_update().first()
                reserved = (db.session.query(sa_func.coalesce(sa_func.sum(Booking.points_redeemed), 0))
                    .filter(Booking.user_id == user.id, Booking.status == 'PENDING',
                            Booking.expires_at > datetime.utcnow()).scalar() or 0)
                available = max(0, (user.points or 0) - reserved)
                if points > available:
                    raise ValueError(f'Only {available} unreserved points are available. Review checkout and retry.')
                deducted = User.query.filter(User.id == user.id,
                    User.points >= reserved + points).update(
                        {User.points: User.points - points}, synchronize_session=False)
                if deducted != 1:
                    raise ValueError('Your points changed during conversion. Review your wallet and retry.')
                wallet = Wallet.query.filter_by(user_id=user.id).with_for_update().first()
                if not wallet:
                    wallet = Wallet(user_id=user.id, balance=0)
                    db.session.add(wallet)
                    db.session.flush()
                wallet.balance = round((wallet.balance or 0) + points, 2)
                result = WalletPointConversion(user_id=user.id, idempotency_key=key,
                    points=points, credit=float(points), balance_after=wallet.balance)
                db.session.add(result)
                db.session.add(WalletTransaction(wallet_id=wallet.id, amount=float(points),
                    type='CONVERT', description=f'{points} CinePass points converted to wallet credit'))
        flash(f'{result.points} points converted to ₹{result.credit:.0f}. Wallet balance: ₹{result.balance_after:.2f}.')
    except ValueError as error:
        db.session.rollback()
        flash(str(error))
    except IntegrityError:
        db.session.rollback()
        result = WalletPointConversion.query.filter_by(
            user_id=current_user.id, idempotency_key=key).first()
        if result:
            flash(f'Request already completed: {result.points} points became ₹{result.credit:.0f}.')
        else:
            flash('The conversion could not be completed. Refresh your wallet and try again.')
    return redirect(url_for('wallet.wallet_page'), code=303)


@bp.route('/wallet/recharge', methods=['POST'])
@login_required
def wallet_recharge():
    try:
        amount = float(request.form['amount'])
    except (KeyError, ValueError):
        flash("Enter a valid amount.")
        return redirect(url_for('wallet.wallet_page'))
    if amount <= 0 or amount > 10000:
        flash("Recharge amount must be between ₹1 and ₹10,000.")
        return redirect(url_for('wallet.wallet_page'))

    db.session.add(RechargeRequest(user_id=current_user.id, amount=amount))
    db.session.commit()
    flash(f"Recharge request for ₹{amount:.0f} submitted. An admin will approve it shortly.")
    return redirect(url_for('wallet.wallet_page'))
