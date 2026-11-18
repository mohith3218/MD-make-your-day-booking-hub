from flask import Blueprint
from ._support import *

bp = Blueprint("party", __name__)


@bp.route('/api/party/create/<int:showtime_id>', methods=['POST'])
@party_api
def party_create(showtime_id):
    showtime = db.session.get(Showtime, showtime_id)
    if not showtime or not showtime.screen:
        return jsonify(success=False, error='Showtime not found.'), 404
    if showtime.status == 'ended':
        return jsonify(success=False, error='This show has ended.'), 410
    for _ in range(5):
        party = PartySession(showtime_id=showtime.id, host_id=current_user.id)
        party.members.append(PartyMember(user_id=current_user.id, user_name=current_user.username[:80],
                                         avatar_color='#FF2E63'))
        db.session.add(party)
        try:
            db.session.flush()
            result = party_snapshot(party)
            db.session.commit()
            return jsonify(result)
        except IntegrityError:
            db.session.rollback()  # a code collision never leaves a hostless room
    return jsonify(success=False, error='Could not generate a party code. Please retry.'), 503


@bp.route('/api/party/<party_code>/join', methods=['POST'])
@party_api
def party_join(party_code):
    party, error = load_party(party_code)
    if error:
        return error
    member = PartyMember.query.filter_by(party_id=party.id, user_id=current_user.id).first()
    if not member:
        member = PartyMember(party_id=party.id, user_id=current_user.id,
                             user_name=current_user.username[:80], avatar_color='#3B82F6')
        db.session.add(member)
    member.last_ping = datetime.utcnow()
    result = party_snapshot(party)
    db.session.commit()
    return jsonify(result)


@bp.route('/api/party/<party_code>/sync', methods=['POST'])
@party_api
def party_sync(party_code):
    party, error = load_party(party_code)
    if error:
        return error
    member = PartyMember.query.filter_by(party_id=party.id, user_id=current_user.id).first()
    if not member:
        db.session.rollback()
        return jsonify(success=False, error='Join this party before updating seats.'), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get('showtime_id') != party.showtime_id:
        db.session.rollback()
        return jsonify(success=False, error='Party showtime does not match this booking.'), 400
    raw = data.get('selected_seats', [])
    if not isinstance(raw, list) or any(not isinstance(s, str) for s in raw):
        db.session.rollback()
        return jsonify(success=False, error='Seat selection must be a list of seat IDs.'), 400
    seats = [s.strip().upper() for s in raw]
    ok, message = sl.validate_seats(party.showtime.layout, seats) if seats else (True, '')
    if not ok:
        db.session.rollback()
        return jsonify(success=False, error=message), 400
    result = party_snapshot(party)
    unavailable = party.showtime.booked_seat_ids() | party.showtime.held_seat_ids()
    conflicts = sorted(set(seats) & (set(result['squad_seats']) | unavailable))
    member.last_ping = datetime.utcnow()
    member.user_name = current_user.username[:80]  # identity never comes from JSON
    member.selected_seats = ','.join(s for s in seats if s not in conflicts)
    result = party_snapshot(party)
    if conflicts:
        result.update(success=False, error='Some seats were just taken. Please choose again.', conflicts=conflicts)
    db.session.commit()
    return jsonify(result), 409 if conflicts else 200


@bp.route('/api/party/<party_code>/leave', methods=['POST'])
@party_api
def party_leave(party_code):
    party, error = load_party(party_code)
    if error:
        return error
    member = PartyMember.query.filter_by(party_id=party.id, user_id=current_user.id).first()
    if not member:
        db.session.rollback()
        return jsonify(success=False, error='You are not a member of this party.'), 403
    if party.host_id == current_user.id:
        party.status = 'CLOSED'
        for m in party.members:
            m.selected_seats = ''
    db.session.delete(member)
    db.session.commit()
    return jsonify(success=True)


@bp.route('/api/party/<party_code>/close', methods=['POST'])
@party_api
def party_close(party_code):
    party, error = load_party(party_code)
    if error:
        return error
    if party.host_id != current_user.id:
        db.session.rollback()
        return jsonify(success=False, error='Only the host can close this party.'), 403
    party.status = 'CLOSED'
    for member in party.members:
        member.selected_seats = ''
    db.session.commit()
    return jsonify(success=True)
