from math import isfinite

from flask import Blueprint
from ._support import *
from ..services.screen_reviews import review_invitation

bp = Blueprint("booking", __name__)


@bp.route('/book/<int:showtime_id>', methods=['GET', 'POST'])
@login_required
def book(showtime_id):
    showtime = Showtime.query.get_or_404(showtime_id)
    if showtime.movie.is_archived:
        abort(404)
    discovery_context = validate_booking_context(showtime)
    purge_expired_holds()
    movie = showtime.movie

    if not showtime.screen:
        flash("This showtime has no screen assigned. Ask an admin to fix it.")
        return redirect(url_for('movies.movie_detail', movie_id=movie.id))

    if not showtime.accepts_bookings:
        flash("This show has started or is unavailable. Please choose an upcoming showtime.")
        return redirect(url_for('movies.movie_detail', movie_id=movie.id))

    layout = showtime.layout
    booked = showtime.booked_seat_ids()
    held = showtime.held_seat_ids()
    dyn = showtime.dynamic_pricing_info

    if request.method == 'POST':
        raw = request.form.get('selected_seats', '')
        seats_list = [s.strip().upper() for s in raw.split(',') if s.strip()]

        ok, msg = sl.validate_seats(layout, seats_list)
        if not ok:
            flash(msg)
            return redirect(url_for('booking.book', showtime_id=showtime_id))

        party_member = None
        code = request.args.get('party', '').strip()
        if code:
            party, error = load_party(code)
            if error:
                flash('This party is unavailable. Rejoin or continue without a party.')
                return redirect(url_for('booking.book', showtime_id=showtime_id))
            party_member = PartyMember.query.filter_by(party_id=party.id, user_id=current_user.id).first()
            if party.showtime_id != showtime.id or not party_member:
                db.session.rollback()
                flash('Join the party for this showtime before booking with it.')
                return redirect(url_for('booking.book', showtime_id=showtime_id))
            squad = party_snapshot(party)['squad_seats']
            if set(seats_list) & set(squad):
                db.session.rollback()
                flash('A party member is selecting one of these seats. Please choose again.')
                return redirect(url_for('booking.book', showtime_id=showtime_id, party=party.code))
            # Re-read after the room lock; another member may have checked out.
            booked, held = showtime.booked_seat_ids(), showtime.held_seat_ids()

        clash = sorted(set(seats_list) & (booked | held))
        if clash:
            flash(f"Seat(s) {', '.join(clash)} were just taken. Please choose again.")
            return redirect(url_for('booking.book', showtime_id=showtime_id))

        # ---- hold the seats, then create a PENDING booking ----
        ticket_amount, meta = price_seats(showtime, seats_list)
        if any(not isfinite(seat['price']) or seat['price'] <= 0 for seat in meta):
            flash('One or more selected seats are unavailable.')
            return redirect(url_for('booking.book', showtime_id=showtime_id))
        amounts = payments.compute_amounts(ticket_amount, len(seats_list))

        lock = SeatLock(showtime_id=showtime.id, user_id=current_user.id,
                        seats=",".join(seats_list))
        db.session.add(lock)
        db.session.flush()
        db.session.add_all(SeatHold(showtime_id=showtime.id, seat_id=seat_id,
                                    token=lock.token, expires_at=lock.expires_at)
                           for seat_id in seats_list)

        booking = Booking(user_id=current_user.id, showtime_id=showtime.id,
                          seats=",".join(seats_list),
                          seat_meta_json=json.dumps(meta),
                          ticket_amount=amounts['ticket_amount'],
                          convenience_fee=amounts['convenience_fee'],
                          gst=amounts['gst'],
                          total_amount=amounts['total'],
                          status='PENDING', lock_token=lock.token,
                          expires_at=lock.expires_at)
        db.session.add(booking)
        if party_member:
            party_member.selected_seats = ''
        try:
            db.session.commit()
        except IntegrityError:
            # The unique (showtime, seat) hold key is the race-safe authority.
            db.session.rollback()
            flash("One or more seats were just held by another customer. Please choose again.")
            return redirect(url_for('booking.book', showtime_id=showtime_id))

        return redirect(url_for('booking.checkout', reference=booking.reference))

    effective_overrides = {}
    base_overrides = showtime.price_overrides
    for cls in layout.get("classes", []):
        code = cls.get("code", "STD")
        base_p = float(base_overrides.get(code, cls.get("price", 0)))
        effective_overrides[code] = round(base_p * dyn['factor'], 2)

    grid = sl.build_layout(layout, booked=booked, held=held,
                           price_overrides=effective_overrides)
    session.setdefault('party_csrf', secrets.token_urlsafe(32))
    party_code = request.args.get('party', '').strip().upper()
    return render_template('book.html', movie=movie, showtime=showtime,
                           screen=showtime.screen, grid=grid,
                           max_seats=sl.MAX_SEATS_PER_BOOKING,
                           stats=sl.availability(layout, booked | held),
                           dynamic_info=dyn, party_code=party_code,
                           discovery_context=discovery_context)


@bp.route('/book/<int:showtime_id>/vr-preview')
@login_required
def vr_seat_preview(showtime_id):
    """Render the immersive seat preview from this show's real screen layout."""
    admin_screen_id = request.args.get('admin_screen', type=int)
    if admin_screen_id is not None:
        guard = admin_required()
        if guard:
            return guard
        screen_for_preview = Screen.query.get_or_404(admin_screen_id)
        showtime = SimpleNamespace(
            screen=screen_for_preview, layout=screen_for_preview.layout or {},
            theater=screen_for_preview.theater.name,
            movie=SimpleNamespace(title='Auditorium profile comparison'),
            show_date=date.today(), show_time='Admin preview',
            price_overrides={}, dynamic_pricing_info={'factor': 1},
            booked_seat_ids=lambda: set(), held_seat_ids=lambda: set(),
        )
    else:
        purge_expired_holds()
        showtime = Showtime.query.get_or_404(showtime_id)
    if not showtime.screen:
        abort(404)

    layout = showtime.layout or {}
    geometry_errors = sl.validate_auditorium_geometry(layout)
    if geometry_errors:
        abort(422, description="This screen layout needs correction before the 3D preview can safely render it: " + geometry_errors[0])
    booked = showtime.booked_seat_ids()
    held = showtime.held_seat_ids()
    dynamic = showtime.dynamic_pricing_info
    row_defs = []
    prices = []
    for cls in layout.get('classes', []):
        code = cls.get('code', 'STD')
        base_price = float(showtime.price_overrides.get(code, cls.get('price', 0)))
        price = round(base_price * dynamic['factor'], 2)
        prices.append(price)
        for row in cls.get('rows', []):
            start = int(row.get('start', 1))
            count = max(0, int(row.get('count', 0)))
            blocked = set(row.get('blocked') or [])
            seats = {}
            for number in range(start, start + count):
                seat_id = f"{row['label']}{number}"
                if seat_id in blocked:
                    continue
                seats[seat_id] = 'booked' if seat_id in booked else ('held' if seat_id in held else 'available')
            row_defs.append({
                'label': row['label'], 'start': start, 'count': count,
                'aislesAfter': [int(a) for a in row.get('aisles_after', [])],
                'blocked': list(blocked), 'offset': int(row.get('offset', 0)),
                'seatSpan': max(1, int(row.get('seat_span', 1))),
                'classCode': code, 'className': cls.get('name', 'Standard'),
                'price': price, 'seats': seats,
                'level_id': row.get('level_id'),
            })

    if not row_defs:
        abort(404)
    max_seat = max((row['start'] + row['count'] - 1 for row in row_defs), default=1)
    screen = layout.get('screen') or {}
    screen_type = (showtime.screen.screen_type or '').upper()
    fallback_aspect = 1.43 if 'IMAX' in screen_type else (2.2 if '70MM' in screen_type else 1.85)
    # Seed layouts contain seat-by-seat arrangements, but most do not include
    # surveyed auditorium dimensions. Keep supplied measurements and estimate
    # screen width proportionally when a layout has no measurement.
    widest_row_seats = max((row['count'] * row['seatSpan'] for row in row_defs), default=0)
    try:
        width = float(screen.get('width_m') or max(8.0, min(24.0, widest_row_seats * 0.62)))
    except (TypeError, ValueError):
        width = max(8.0, min(24.0, widest_row_seats * 0.62))
    try:
        aspect = float(screen.get('aspect_ratio') or fallback_aspect)
        if aspect <= 0:
            aspect = fallback_aspect
    except (TypeError, ValueError):
        aspect = fallback_aspect
    try:
        height = float(screen.get('height_m') or (width / aspect))
    except (TypeError, ValueError):
        height = width / aspect
    geometry = sl.auditorium_geometry(layout, row_defs, fallback_aspect)
    reference_profile = layout.get('reference_profile') or {}
    reference_status = reference_profile.get('reference_status', 'estimated_model')
    reference_status_label = {
        'verified_reference': 'screen-identified photo reference · currentness/permission review pending',
        'venue_reference': 'venue reference · screen match unverified',
        'estimated_model': 'estimated auditorium appearance',
    }.get(reference_status, 'administrator-defined appearance profile')
    surface = str(geometry.get('screen', {}).get('surface', '')).lower()
    screen_label = 'Flat LED screen' if surface == 'led' else ('Flat screen' if surface == 'flat' else 'Curved cinema screen')
    all_seat_ids = [seat_id for row in row_defs for seat_id in row['seats']]
    available_ids = [seat_id for row in row_defs for seat_id, state in row['seats'].items() if state == 'available']
    middle_row = row_defs[len(row_defs) // 2]
    middle_seat = middle_row['start'] + max(0, middle_row['count'] - 1) // 2
    preferred_id = f"{middle_row['label']}{middle_seat}"
    default_seat = preferred_id if preferred_id in available_ids else (available_ids[0] if available_ids else (all_seat_ids[0] if all_seat_ids else ''))

    preview = {
        'name': f'{showtime.theater} · {showtime.screen.name}',
        'movieTitle': showtime.movie.title,
        'sub': f'{showtime.screen.screen_type} · {len(row_defs)} rows · {sum(len(r["seats"]) for r in row_defs)} seats' + (' · dimensions estimated' if geometry.get('estimated') else ''),
        'rows': [row['label'] for row in row_defs], 'rowDefs': row_defs,
        'cols': max_seat, 'aislesAfter': [], 'vipRows': [], 'reclinerRows': [],
        'screenWidth': width, 'screenHeight': height,
        'geometry': geometry,
        # Only visual parameters and confidence are sent to customer pages.
        # Photo URLs remain in the administrator reference workflow and are
        # never requested by the ordinary preview renderer.
        'referenceProfile': {
            'architecture': reference_profile.get('architecture') or {},
            'confidence': reference_profile.get('confidence') or {},
        },
        'reference_status_label': reference_status_label,
        'screen_label': screen_label,
        'visual': layout.get('visual') or {
            'seat_color': '#51252d', 'wall_color': '#11151d',
            'trim_color': '#c9a84c', 'seat_style': 'standard',
            'verified_at_theater_level': False,
        },
        'rowSpacing': max(1.6, min(3.8, float(screen.get('row_spacing_m', 2.45)))),
        'screenCurve': max(0, min(0.6, float(screen.get('curve', 0.3)))),
        'stadiumSlope': max(0.25, min(1.2, float(screen.get('stadium_slope', 0.55)))),
        'prices': {'standard': min(prices or [0]), 'vip': max(prices or [0]), 'recliner': max(prices or [0])},
        'defaultSeat': default_seat,
    }
    return render_template('vr_seat_preview.html', showtime=showtime,
                           screen_type=showtime.screen.screen_type or 'Cinema screen',
                           movie=showtime.movie, preview=preview,
                           embedded=request.args.get('embed') == '1')


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
    return render_template('checkout.html', booking=booking,
                           showtime=booking.showtime,
                           movie=booking.showtime.movie,
                           wallet=wallet,
                           can_use_wallet=payments.mock_payments_enabled() and wallet.balance >= booking.total_amount,
                           gateway=payments.gateway_name(),
                           snack_items=SNACK_ITEMS,
                           split_pay_url=_split_invite_url(booking) if booking.split_token else '',
                           split_started=_has_split_progress(booking),
                           user_points=current_user.points or 0)


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
    return render_template('split_pay.html', booking=booking,
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
    return render_template('split_pay_mock.html', booking=booking,
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
    return render_template('pay_mock.html', booking=booking, order=order,
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
    return render_template('ticket.html', booking=booking,
                           showtime=booking.showtime,
                           movie=booking.showtime.movie,
                           screen_review_state=review_invitation(booking, current_user.id),
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
