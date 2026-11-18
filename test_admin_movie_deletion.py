"""Admin deletion regression tests against disposable SQLite with foreign keys on."""
import os
from pathlib import Path
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
_temporary = tempfile.TemporaryDirectory(prefix='admin-delete-')
_url = 'sqlite:///' + (Path(_temporary.name) / 'test.db').as_posix()
os.environ.update(APP_ENV='testing', DATABASE_URL=_url, TEST_DATABASE_URL=_url,
                  SECRET_KEY='isolated-admin-deletion-fixture', SMTP_HOST='', TMDB_API_KEY='')

import app as A
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AdminMovieDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with A.app.app_context():
            assert Path(A.db.engine.url.database).resolve().is_relative_to(Path(_temporary.name))
            @event.listens_for(A.db.engine, 'connect')
            def foreign_keys(connection, record):
                connection.execute('PRAGMA foreign_keys=ON')

    @classmethod
    def tearDownClass(cls):
        with A.app.app_context():
            A.db.session.remove()
            A.db.engine.dispose()
        _temporary.cleanup()

    def setUp(self):
        self.context = A.app.app_context()
        self.context.push()
        A.db.drop_all()
        A.db.create_all()
        A.app.config.update(TESTING=True, SESSION_PROTECTION='basic')
        self.admin = A.User(username='admin_fixture', password_hash='fixture', is_admin=True)
        self.viewer = A.User(username='viewer_fixture', password_hash='fixture')
        self.movie = A.Movie(title='Deletion fixture', description='Test', duration=120,
                             is_upcoming=True)
        self.other = A.Movie(title='Keep this film', description='Unrelated', duration=120)
        venue = A.Theater(name='Fixture Cinema')
        screen = A.Screen(theater=venue, name='Screen 1', layout_json='{"classes":[]}')
        self.show = A.Showtime(movie=self.movie, screen=screen, theater=venue.name,
                               show_date=date.today() + timedelta(days=2), show_time='7:30 PM')
        A.db.session.add_all([self.admin, self.viewer, self.movie, self.other, self.show])
        A.db.session.commit()
        self.movie_id, self.show_id, self.other_id = self.movie.id, self.show.id, self.other.id
        self.client = self.client_for(self.admin)

    def tearDown(self):
        A.db.session.remove()
        self.context.pop()

    def client_for(self, user):
        client = A.app.test_client()
        with client.session_transaction() as state:
            state['_user_id'] = user.alternative_id
            state['_fresh'] = True
        return client

    def delete(self):
        return self.client.post(f'/admin/delete_movie/{self.movie_id}', follow_redirects=True)

    def assert_preserved(self):
        self.assertIsNotNone(A.db.session.get(A.Movie, self.movie_id))
        self.assertIsNotNone(A.db.session.get(A.Showtime, self.show_id))

    def test_closed_party_members_and_expired_holds_are_cleaned_before_showtimes(self):
        room = A.PartySession(showtime=self.show, host=self.viewer, status='CLOSED')
        room.members.append(A.PartyMember(user=self.viewer, user_name='Viewer'))
        A.db.session.add(room)
        A.db.session.add_all([room,
            A.SeatLock(showtime_id=self.show_id, user_id=self.viewer.id, token='expired',
                       seats='A1', expires_at=now() - timedelta(minutes=1)),
            A.SeatHold(showtime_id=self.show_id, seat_id='A1', token='expired',
                       expires_at=now() - timedelta(minutes=1)),
            A.Watchlist(movie=self.movie, user=self.viewer),
            A.MovieRating(movie=self.movie, user=self.viewer, rating=4),
            A.MovieHypeVote(movie=self.movie, user=self.viewer, level='SUPER_HYPED'),
        ])
        A.db.session.commit()
        self.assertEqual(A.db.session.execute(text('PRAGMA foreign_keys')).scalar(), 1)
        response = self.delete()
        self.assertEqual(response.status_code, 200)
        self.assertIn('has been deleted', response.text)
        self.assertIsNone(A.db.session.get(A.Movie, self.movie_id))
        self.assertIsNone(A.db.session.get(A.Showtime, self.show_id))
        for model in (A.PartyMember, A.PartySession, A.SeatLock, A.SeatHold,
                      A.Watchlist, A.MovieRating, A.MovieHypeVote):
            self.assertEqual(model.query.count(), 0, model.__name__)
        self.assertIsNotNone(A.db.session.get(A.Movie, self.other_id))
        self.assertEqual(A.User.query.count(), 2)

    def test_status_changes_preserve_hype_votes(self):
        A.db.session.add(A.MovieHypeVote(movie=self.movie, user=self.viewer,
                                         level='EXTREME_HYPED'))
        A.db.session.commit()
        response = self.client.get('/admin')
        with self.client.session_transaction() as session:
            csrf = session['_csrf_token']
        response = self.client.post(f'/admin/toggle_movie_status/{self.movie_id}',
                                    data={'csrf_token': csrf}, follow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertFalse(A.db.session.get(A.Movie, self.movie_id).is_upcoming)
        vote = A.MovieHypeVote.query.filter_by(movie_id=self.movie_id).one()
        self.assertEqual(vote.level, 'EXTREME_HYPED')

    def test_paid_booking_payment_and_split_history_are_preserved(self):
        booking = A.Booking(user=self.viewer, showtime=self.show, seats='A1',
                            status='PAID', total_amount=200)
        booking.payment = A.Payment(gateway='mock', status='CAPTURED', amount=200)
        A.db.session.add(booking)
        A.db.session.flush()
        A.db.session.add_all([
            A.BookedSeat(showtime_id=self.show_id, booking_id=booking.id, seat_id='A1'),
            A.SplitContribution(booking_id=booking.id, user_id=self.viewer.id,
                                share_index=1, amount=200, status='PAID'),
        ])
        A.db.session.commit()
        response = self.delete()
        self.assertEqual(response.status_code, 200)
        self.assertIn('has bookings', response.text)
        self.assert_preserved()
        for model in (A.Booking, A.Payment, A.BookedSeat, A.SplitContribution):
            self.assertEqual(model.query.count(), 1)

    def test_cancelled_bookings_are_also_preserved(self):
        A.db.session.add(A.Booking(user=self.viewer, showtime=self.show, seats='A1',
                                  status='CANCELLED', total_amount=200))
        A.db.session.commit()
        response = self.delete()
        self.assertEqual(response.status_code, 200)
        self.assertIn('has bookings', response.text)
        self.assert_preserved()

    def test_active_hold_prevents_deletion(self):
        A.db.session.add(A.SeatHold(showtime_id=self.show_id, seat_id='A1', token='active',
                                   expires_at=now() + timedelta(minutes=5)))
        A.db.session.commit()
        response = self.delete()
        self.assertEqual(response.status_code, 200)
        self.assertIn('active seat holds', response.text)
        self.assert_preserved()
        self.assertEqual(A.SeatHold.query.count(), 1)

    def test_active_watch_party_prevents_deletion(self):
        A.db.session.add(A.PartySession(showtime=self.show, host=self.viewer, status='ACTIVE'))
        A.db.session.commit()
        response = self.delete()
        self.assertEqual(response.status_code, 200)
        self.assertIn('active Watch Together', response.text)
        self.assert_preserved()

    def test_active_lock_without_normalized_hold_prevents_deletion(self):
        A.db.session.add(A.SeatLock(showtime_id=self.show_id, user_id=self.viewer.id,
                                   token='active', seats='A1',
                                   expires_at=now() + timedelta(minutes=5)))
        A.db.session.commit()
        response = self.delete()
        self.assertEqual(response.status_code, 200)
        self.assertIn('active seat holds', response.text)
        self.assert_preserved()

    def test_confirmed_seat_without_booking_link_is_preserved(self):
        A.db.session.add(A.BookedSeat(showtime_id=self.show_id, seat_id='A1'))
        A.db.session.commit()
        response = self.delete()
        self.assertEqual(response.status_code, 200)
        self.assertIn('confirmed seats', response.text)
        self.assert_preserved()
        self.assertEqual(A.BookedSeat.query.count(), 1)

    def test_expired_active_party_does_not_prevent_deletion(self):
        room = A.PartySession(showtime=self.show, host=self.viewer, status='ACTIVE',
                              created_at=now() - A.PARTY_LIFETIME - timedelta(minutes=1))
        room.members.append(A.PartyMember(user=self.viewer, user_name='Viewer'))
        A.db.session.add(room)
        A.db.session.commit()
        self.assertEqual(self.delete().status_code, 200)
        self.assertIsNone(A.db.session.get(A.Movie, self.movie_id))
        self.assertEqual(A.PartyMember.query.count(), 0)

    def test_non_admin_and_get_cannot_delete(self):
        response = self.client_for(self.viewer).post(f'/admin/delete_movie/{self.movie_id}')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(f'/admin/delete_movie/{self.movie_id}').status_code, 405)
        self.assert_preserved()

    def test_empty_movie_can_be_deleted(self):
        response = self.client.post(f'/admin/delete_movie/{self.other_id}')
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(A.db.session.get(A.Movie, self.other_id))
        self.assert_preserved()

    def test_commit_failure_rolls_back_deletion(self):
        room = A.PartySession(showtime=self.show, host=self.viewer, status='CLOSED')
        room.members.append(A.PartyMember(user=self.viewer, user_name='Viewer'))
        A.db.session.add(room)
        A.db.session.commit()
        with patch.object(A.db.session, 'commit', side_effect=IntegrityError('fixture', {}, Exception('fixture'))):
            response = self.client.post(f'/admin/delete_movie/{self.movie_id}')
        self.assertEqual(response.status_code, 302)
        self.assert_preserved()
        self.assertEqual(A.PartySession.query.count(), 1)
        self.assertEqual(A.PartyMember.query.count(), 1)
        self.assertEqual(self.client.get('/admin').status_code, 200)


if __name__ == '__main__':
    unittest.main(verbosity=2)
