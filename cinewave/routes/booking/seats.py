import json
from hmac import compare_digest
import payments
import seat_layout as sl
import secrets
from cinewave.extensions import db
from cinewave.models import Booking, PartyMember, SeatHold, SeatLock, Showtime, SplitContribution
from cinewave.routes.theatre_discovery import validate_booking_context
from cinewave.services import load_party, party_snapshot, price_seats, purge_expired_holds
from cinewave.services.seat import can_edit_seat_hold
from flask import abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from math import isfinite
from sqlalchemy.exc import IntegrityError

from . import bp


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

    reference = request.args.get('reservation')
    reservation = lock = None
    if reference:
        query = Booking.query.filter_by(reference=reference, showtime_id=showtime_id, user_id=current_user.id)
        reservation = (query.with_for_update() if request.method == 'POST' else query).first_or_404()
        if not can_edit_seat_hold(reservation):
            return redirect(url_for('booking.checkout', reference=reference))
        lock = SeatLock.query.filter_by(token=reservation.lock_token, user_id=current_user.id,
                                        showtime_id=showtime_id).first_or_404()
        if request.method == 'POST':
            csrf = session.get('_csrf_token')
            if not csrf or not compare_digest(csrf, request.form.get('csrf_token', '')):
                abort(400)
    exclude_token = lock.token if lock else None
    seats_url = url_for('booking.book', showtime_id=showtime_id, reservation=reference)
    layout = showtime.layout
    booked = showtime.booked_seat_ids()
    held = showtime.held_seat_ids(exclude_token=exclude_token)
    dyn = showtime.dynamic_pricing_info

    if request.method == 'POST':
        raw = request.form.get('selected_seats', '')
        seats_list = [s.strip().upper() for s in raw.split(',') if s.strip()]

        ok, msg = sl.validate_seats(layout, seats_list)
        if not ok:
            flash(msg)
            return redirect(seats_url)
        if reservation and set(seats_list) == set(reservation.seat_list):
            return redirect(url_for('booking.checkout', reference=reservation.reference))

        party_member = None
        code = request.args.get('party', '').strip()
        if code:
            party, error = load_party(code)
            if error:
                flash('This party is unavailable. Rejoin or continue without a party.')
                return redirect(seats_url)
            party_member = PartyMember.query.filter_by(party_id=party.id, user_id=current_user.id).first()
            if party.showtime_id != showtime.id or not party_member:
                db.session.rollback()
                flash('Join the party for this showtime before booking with it.')
                return redirect(seats_url)
            squad = party_snapshot(party)['squad_seats']
            if set(seats_list) & set(squad):
                db.session.rollback()
                flash('A party member is selecting one of these seats. Please choose again.')
                return redirect(url_for('booking.book', showtime_id=showtime_id, party=party.code,
                                        reservation=reference))
            # Re-read after the room lock; another member may have checked out.
            booked, held = showtime.booked_seat_ids(), showtime.held_seat_ids(exclude_token=exclude_token)

        clash = sorted(set(seats_list) & (booked | held))
        if clash:
            flash(f"Seat(s) {', '.join(clash)} were just taken. Please choose again.")
            return redirect(seats_url)

        # ---- hold the seats, then create a PENDING booking ----
        ticket_amount, meta = price_seats(showtime, seats_list)
        if any(not isfinite(seat['price']) or seat['price'] <= 0 for seat in meta):
            flash('One or more selected seats are unavailable.')
            return redirect(seats_url)
        amounts = payments.compute_amounts(ticket_amount, len(seats_list))

        if reservation:
            SeatHold.query.filter_by(token=lock.token).delete(synchronize_session=False)
            lock.seats = ','.join(seats_list)
        else:
            lock = SeatLock(showtime_id=showtime.id, user_id=current_user.id, seats=','.join(seats_list))
            db.session.add(lock)
            db.session.flush()
        db.session.add_all(SeatHold(showtime_id=showtime.id, seat_id=seat_id,
                                    token=lock.token, expires_at=lock.expires_at)
                           for seat_id in seats_list)

        booking = reservation or Booking(user_id=current_user.id, showtime_id=showtime.id,
                                         status='PENDING', lock_token=lock.token, expires_at=lock.expires_at)
        booking.seats = ','.join(seats_list)
        booking.seat_meta_json = json.dumps(meta)
        booking.ticket_amount = amounts['ticket_amount']
        booking.convenience_fee = amounts['convenience_fee']
        booking.gst = amounts['gst']
        booking.total_amount = amounts['total']
        if reservation:
            if booking.snacks_list or booking.points_redeemed:
                extras = sum(item['price'] for item in booking.snacks_list)
                total = payments.compute_amounts(ticket_amount + extras, len(seats_list))['total']
                booking.total_amount = round(max(1.0, total - (booking.points_redeemed or 0)), 2)
            SplitContribution.query.filter_by(booking_id=booking.id).delete(synchronize_session=False)
            if len(seats_list) < 2:
                booking.split_token = None
                booking.is_split_pay = False
        else:
            db.session.add(booking)
        if party_member:
            party_member.selected_seats = ''
        try:
            db.session.commit()
        except IntegrityError:
            # The unique (showtime, seat) hold key is the race-safe authority.
            db.session.rollback()
            flash("One or more seats were just held by another customer. Please choose again.")
            return redirect(seats_url)

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
    return render_template('booking/book.html', movie=movie, showtime=showtime,
                           screen=showtime.screen, grid=grid,
                           max_seats=sl.MAX_SEATS_PER_BOOKING,
                           stats=sl.availability(layout, booked | held),
                           dynamic_info=dyn, party_code=party_code,
                           edit_reservation=reservation,
                           discovery_context=discovery_context)
