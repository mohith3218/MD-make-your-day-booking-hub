import json
import re
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import current_app, jsonify, request, session, url_for
from flask_login import current_user
from ..extensions import db
from ..models import PartyMember, PartySession
from ..config import PARTY_LIFETIME, PARTY_PRESENCE



def party_api(view):
    @wraps(view)
    def guarded(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify(success=False, error='Please sign in to use Watch Together.'), 401
        origin = request.headers.get('Origin')
        if origin and origin != request.host_url.rstrip('/'):
            return jsonify(success=False, error='Invalid request origin.'), 403
        token = session.get('party_csrf', '')
        supplied_token = request.headers.get('X-Party-CSRF', '')
        if not token or not secrets.compare_digest(token.encode(), supplied_token.encode()):
            return jsonify(success=False, error='Refresh this page before using Watch Together.'), 403
        return view(*args, **kwargs)
    return guarded


def load_party(code):
    code = code.strip().upper()
    if not re.fullmatch(r'[0-9A-F]{6}', code):
        return None, (jsonify(success=False, error='Enter a valid six-character party code.'), 400)
    # This write locks one room on PostgreSQL and serializes writers on SQLite.
    # Every join/sync/leave/close takes this lock before reading membership/picks.
    count = PartySession.query.filter_by(code=code).update(
        {PartySession.status: PartySession.status}, synchronize_session=False)
    if not count:
        db.session.rollback()
        return None, (jsonify(success=False, error='Party code not found.'), 404)
    party = PartySession.query.filter_by(code=code).populate_existing().one()
    if party.status == 'ACTIVE' and (
            not party.created_at or datetime.utcnow() >= party.created_at + PARTY_LIFETIME
            or party.showtime.status == 'ended'):
        party.status = 'EXPIRED'
    if party.status != 'ACTIVE':
        status = str(party.status or 'CLOSED').lower()
        db.session.commit()
        return None, (jsonify(success=False, error=f'This party is {status}.', status=party.status), 410)
    return party, None


def party_snapshot(party):
    cutoff = datetime.utcnow() - PARTY_PRESENCE
    members, squad = [], {}
    unavailable = party.showtime.booked_seat_ids() | party.showtime.held_seat_ids()
    for member in PartyMember.query.filter_by(party_id=party.id).order_by(PartyMember.id):
        # Expired presence releases picks but keeps a stable authenticated membership.
        seats = [s for s in (member.selected_seats or '').split(',') if s and s not in unavailable]
        if not member.last_ping or member.last_ping < cutoff:
            seats = []
        member.selected_seats = ','.join(seats)
        me = member.user_id == current_user.id
        if member.last_ping and member.last_ping >= cutoff:
            members.append(dict(user_name=member.user_name, color=member.avatar_color,
                                seats=seats, is_me=me, is_host=member.user_id == party.host_id))
            if not me:
                squad.update({s: dict(user_name=member.user_name, color=member.avatar_color) for s in seats})
    mine = PartyMember.query.filter_by(party_id=party.id, user_id=current_user.id).first()
    return dict(success=True, party_code=party.code, showtime_id=party.showtime_id,
                is_host=party.host_id == current_user.id, members=members, squad_seats=squad,
                selected_seats=(mine.selected_seats or '').split(',') if mine and mine.selected_seats else [],
                join_url=url_for('booking.book', showtime_id=party.showtime_id, party=party.code),
                expires_at=(party.created_at + PARTY_LIFETIME).isoformat() + 'Z')
