"""Actual Flask/SQLite party workflows; never use an operator database.

Run this module in its own process, like the existing migration/flow suites.
"""
import os
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from unittest.mock import patch

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

_temp = tempfile.TemporaryDirectory(prefix='party-', dir=Path(__file__).resolve().parent / 'instance')
_url = 'sqlite:///' + (Path(_temp.name) / 'party-test.db').as_posix()
os.environ.update(APP_ENV='testing', DATABASE_URL=_url, TEST_DATABASE_URL=_url,
                  SECRET_KEY='isolated-party-test-key', SMTP_HOST='', TMDB_API_KEY='')

import app as A
from flask import g
from sqlalchemy.exc import IntegrityError
import vizag_theaters as theaters


@A.app.before_request
def clear_test_context_identity():
    # Tests keep an app context for database assertions. A real request gets a
    # fresh g; discard Flask-Login's cached identity when switching test clients.
    g.pop('_login_user', None)


class PartyTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        with A.app.app_context():
            A.db.session.remove()
            A.db.engine.dispose()
        _temp.cleanup()

    def setUp(self):
        self.context = A.app.app_context()
        self.context.push()
        self.assertEqual(Path(A.db.engine.url.database).resolve(), Path(_temp.name, 'party-test.db').resolve())
        A.db.drop_all()
        A.db.create_all()
        A.app.config['TESTING'] = True
        venue = A.Theater(name='Jagadamba Theatre')
        screen = A.Screen(theater=venue, name='70MM Main', screen_type='70MM')
        layout = theaters.jagadamba_70mm()
        theaters._attach_known_screen_geometry(layout, venue.name, screen.name)
        screen.layout = layout
        movie = A.Movie(title='Party test', description='Fixture only', duration=120)
        self.show = A.Showtime(movie=movie, screen=screen, theater=venue.name,
                               show_date=date.today() + timedelta(days=2), show_time='6:30 PM')
        self.users = [A.User(username=n, password_hash='fixture') for n in ('Host', 'Friend', 'Outsider')]
        A.db.session.add_all([self.show, *self.users])
        A.db.session.commit()
        self.show_id = self.show.id
        self.clients = []
        for user in self.users:
            client = A.app.test_client()
            with client.session_transaction() as session:
                session['_user_id'] = str(user.id)
                session['_fresh'] = True
                session['party_csrf'] = 'fixture-csrf'
            self.clients.append(client)
        self.host, self.friend, self.outsider = self.clients

    def tearDown(self):
        A.db.session.remove()
        self.context.pop()

    def post(self, client, path, data=None):
        return client.post(path, json=data or {}, headers={'X-Party-CSRF':'fixture-csrf'})

    def create(self):
        response = self.post(self.host, f'/api/party/create/{self.show_id}')
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()['party_code']

    def sync(self, client, code, seats):
        return self.post(client, f'/api/party/{code}/sync',
                         {'showtime_id':self.show_id, 'selected_seats':seats})

    def test_full_host_friend_workflow(self):
        code = self.create()
        self.assertRegex(code, r'^[0-9A-F]{6}$')
        party = A.PartySession.query.filter_by(code=code).one()
        self.assertEqual(party.host_id, self.users[0].id)
        self.assertEqual(len(party.members), 1)
        for _ in range(2):
            joined = self.post(self.friend, f'/api/party/{code}/join')
            self.assertEqual(joined.status_code, 200)
            self.assertEqual(joined.json['showtime_id'], self.show_id)
        self.assertEqual(A.PartyMember.query.filter_by(party_id=party.id).count(), 2)
        self.assertEqual(self.sync(self.host, code, ['A1']).status_code, 200)
        other = self.sync(self.friend, code, ['A2'])
        self.assertEqual(other.json['squad_seats']['A1']['user_name'], 'Host')
        clash = self.sync(self.friend, code, ['A1', 'A2'])
        self.assertEqual(clash.status_code, 409)
        self.assertEqual(clash.json['conflicts'], ['A1'])
        self.assertEqual(clash.json['selected_seats'], ['A2'])
        self.assertIn('A2', self.sync(self.host, code, ['A1']).json['squad_seats'])
        self.assertEqual(self.post(self.friend, f'/api/party/{code}/leave').status_code, 200)
        self.assertEqual(self.sync(self.host, code, ['A1']).json['squad_seats'], {})
        self.assertEqual(self.post(self.host, f'/api/party/{code}/close').status_code, 200)
        self.assertEqual(self.post(self.friend, f'/api/party/{code}/join').status_code, 410)
        self.assertEqual(self.sync(self.host, code, []).status_code, 410)

    def test_identity_membership_host_and_csrf_protection(self):
        code = self.create()
        self.assertEqual(A.app.test_client().post(f'/api/party/{code}/sync', json={}).status_code, 401)
        self.assertEqual(self.host.post(f'/api/party/{code}/close').status_code, 403)
        self.assertEqual(self.host.post(f'/api/party/{code}/close', headers={
            'X-Party-CSRF':'fixture-csrf', 'Origin':'https://untrusted.invalid'}).status_code, 403)
        self.assertEqual(self.sync(self.outsider, code, ['A1']).status_code, 403)
        self.assertEqual(self.post(self.outsider, f'/api/party/{code}/leave').status_code, 403)
        self.assertEqual(self.post(self.outsider, f'/api/party/{code}/close').status_code, 403)
        self.post(self.friend, f'/api/party/{code}/join')
        response = self.post(self.friend, f'/api/party/{code}/sync', dict(
            showtime_id=self.show_id, selected_seats=['A1'], user_name='Host', avatar_color='evil'))
        me = next(m for m in response.json['members'] if m['is_me'])
        self.assertEqual(me['user_name'], 'Friend')
        self.assertEqual(me['color'], '#3B82F6')
        self.assertEqual(self.post(self.friend, f'/api/party/{code}/close').status_code, 403)

    def test_invalid_codes_seats_payload_and_showtime(self):
        for code, status in [('bad-code', 400), ('FFFFFF', 404)]:
            self.assertEqual(self.post(self.host, f'/api/party/{code}/join').status_code, status)
        code = self.create()
        for seats in (['Z999'], ['A1','A1'], ['A1']*9, [None], 'A1'):
            response = self.sync(self.host, code, seats)
            self.assertEqual(response.status_code, 400, response.json)
        self.assertEqual(self.post(self.host, f'/api/party/{code}/sync', {
            'showtime_id':self.show_id+1, 'selected_seats':['A1']}).status_code, 400)
        self.assertEqual(self.host.post(f'/api/party/{code}/sync', json=[],
            headers={'X-Party-CSRF':'fixture-csrf'}).status_code, 400)
        self.assertEqual(self.sync(self.host, code, []).status_code, 200)

    def test_unique_codes_and_collision_retry_are_atomic(self):
        code = self.create()
        with patch.object(A.secrets, 'token_hex', side_effect=[code.lower(), '123abc']):
            second = self.create()
        self.assertEqual(second, '123ABC')
        self.assertEqual(A.PartySession.query.count(), 2)
        self.assertEqual(A.PartyMember.query.count(), 2)
        with patch.object(A.secrets, 'token_hex', return_value=code.lower()):
            self.assertEqual(self.post(self.host, f'/api/party/create/{self.show_id}').status_code, 503)
        self.assertEqual(A.PartySession.query.count(), 2)

    def test_database_prevents_duplicate_memberships(self):
        code = self.create()
        party = A.PartySession.query.filter_by(code=code).one()
        A.db.session.add(A.PartyMember(party_id=party.id, user_id=self.users[0].id, user_name='Duplicate'))
        with self.assertRaises(IntegrityError):
            A.db.session.commit()
        A.db.session.rollback()

    def test_expiry_and_ended_show_rejected(self):
        code = self.create()
        party = A.PartySession.query.filter_by(code=code).one()
        party.created_at = datetime.utcnow() - timedelta(hours=3)
        A.db.session.commit()
        self.assertEqual(self.post(self.friend, f'/api/party/{code}/join').status_code, 410)
        self.assertEqual(self.sync(self.host, code, []).status_code, 410)
        code = self.create()
        self.show.show_date = date.today() - timedelta(days=1)
        A.db.session.commit()
        self.assertEqual(self.post(self.friend, f'/api/party/{code}/join').status_code, 410)
        self.assertEqual(self.post(self.host, f'/api/party/create/{self.show_id}').status_code, 410)

    def test_stale_presence_releases_picks_and_host_leave_closes(self):
        code = self.create()
        self.sync(self.host, code, ['A1'])
        self.post(self.friend, f'/api/party/{code}/join')
        host_member = A.PartyMember.query.filter_by(user_id=self.users[0].id).one()
        host_member.last_ping = datetime.utcnow() - timedelta(seconds=61)
        A.db.session.commit()
        self.assertEqual(self.sync(self.friend, code, ['A1']).status_code, 200)
        self.assertEqual(self.post(self.host, f'/api/party/{code}/leave').status_code, 200)
        self.assertEqual(self.sync(self.friend, code, []).status_code, 410)

    def test_concurrent_selections_have_one_winner(self):
        code = self.create()
        self.post(self.friend, f'/api/party/{code}/join')
        barrier = threading.Barrier(2)
        A.db.session.remove()
        def select(client):
            barrier.wait(timeout=10)
            return self.sync(client, code, ['A1']).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(select, [self.host, self.friend]))
        self.assertEqual(sorted(results), [200, 409])

    def test_booked_held_and_checkout_conflicts(self):
        code = self.create()
        self.post(self.friend, f'/api/party/{code}/join')
        self.sync(self.host, code, ['A1'])
        blocked = self.friend.post(f'/book/{self.show_id}?party={code}', data={'selected_seats':'A1'})
        self.assertEqual(blocked.status_code, 302)
        self.assertEqual(A.Booking.query.count(), 0)
        result = self.host.post(f'/book/{self.show_id}?party={code}', data={'selected_seats':'A1'})
        self.assertIn('/checkout/', result.location)
        self.assertEqual(A.SeatHold.query.filter_by(seat_id='A1').count(), 1)
        self.assertEqual(self.sync(self.friend, code, ['A1']).status_code, 409)
        A.db.session.add(A.BookedSeat(showtime_id=self.show_id, seat_id='A2'))
        A.db.session.commit()
        self.assertEqual(self.sync(self.friend, code, ['A2']).status_code, 409)

    def test_real_booking_and_preview_templates(self):
        response = self.host.get(f'/book/{self.show_id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'2D Seat Selection', response.data)
        self.assertIn(b'3D Seat Preview', response.data)
        self.assertNotIn(b'btn-view-3d\')?.click()', response.data)
        self.assertEqual(self.host.get(f'/book/{self.show_id}/vr-preview').status_code, 200)

    def test_rendered_booking_javascript_behavior(self):
        page = Path(_temp.name, 'booking.html')
        page.write_bytes(self.host.get(f'/book/{self.show_id}').data)
        result = subprocess.run(['node', '--test', 'tools/test_booking_ui.cjs'],
                                env=dict(os.environ, BOOKING_QA_HTML=str(page)),
                                capture_output=True, text=True, encoding='utf-8', timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
