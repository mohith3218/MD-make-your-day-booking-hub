"""Archive and directory-verification regressions against disposable SQLite."""
import os
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
_temporary = tempfile.TemporaryDirectory(prefix='cinewave-catalog-')
_url = 'sqlite:///' + (Path(_temporary.name) / 'test.db').as_posix()
os.environ.update(APP_ENV='testing', DATABASE_URL=_url, TEST_DATABASE_URL=_url,
                  SECRET_KEY='isolated-cinewave-catalog-fixture', SMTP_HOST='', TMDB_API_KEY='')

import app as A


class CatalogFeatureTests(unittest.TestCase):
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
        self.admin = A.User(username='catalog_admin', password_hash='fixture', is_admin=True)
        self.viewer = A.User(username='catalog_viewer', password_hash='fixture')
        self.movie = A.Movie(title='Catalog Archive Fixture', description='Test film',
                             duration=120, is_upcoming=True)
        self.theater = A.Theater(name='Catalog Fixture Cinema', location='Test locality')
        self.screen = A.Screen(theater=self.theater, name='Screen 1', layout_json=(
            '{"classes":[{"code":"STD","name":"Standard","price":100,'
            '"rows":[{"label":"A","seats":["A1","A2"]}]}]}'))
        self.show = A.Showtime(movie=self.movie, screen=self.screen,
                               theater=self.theater.name,
                               show_date=date.today() + timedelta(days=3), show_time='7:30 PM')
        A.db.session.add_all([self.admin, self.viewer, self.movie, self.theater, self.screen, self.show])
        A.db.session.commit()
        self.movie_id, self.show_id = self.movie.id, self.show.id
        self.theater_id, self.screen_id = self.theater.id, self.screen.id
        self.client = self.client_for(self.admin)

    def tearDown(self):
        A.db.session.remove()
        self.context.pop()

    @staticmethod
    def client_for(user):
        client = A.app.test_client()
        with client.session_transaction() as state:
            state['_user_id'] = user.alternative_id
            state['_fresh'] = True
        return client

    def csrf_token(self, client=None):
        client = client or self.client
        self.assertEqual(client.get('/admin').status_code, 200)
        with client.session_transaction() as state:
            return state['_csrf_token']

    def test_archive_is_searchable_reversible_and_preserves_history(self):
        A.db.session.add_all([
            A.MovieHypeVote(movie=self.movie, user=self.viewer, level='SUPER_HYPED'),
            A.MovieRating(movie=self.movie, user=self.viewer, rating=4.5),
            A.Watchlist(movie=self.movie, user=self.viewer),
            A.Booking(user=self.viewer, showtime=self.show, seats='A1',
                      status='PAID', total_amount=100),
        ])
        A.db.session.commit()
        token = self.csrf_token()
        response = self.client.post(f'/admin/movie/{self.movie_id}/archive?q=Catalog+Archive',
                                    data={'csrf_token': token}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(A.db.session.get(A.Movie, self.movie_id).is_archived)
        self.assertIn('Catalog Archive Fixture', self.client.get(
            '/admin?q=Catalog+Archive&visibility=archived').text)
        self.assertNotIn('Catalog Archive Fixture', self.client.get('/').text)
        self.assertEqual(self.client_for(self.viewer).get(f'/movie/{self.movie_id}').status_code, 404)
        self.assertEqual(self.client.get(f'/book/{self.show_id}').status_code, 404)
        self.assertEqual(A.Booking.query.count(), 1)
        self.assertEqual(A.MovieRating.query.count(), 1)
        self.assertEqual(A.MovieHypeVote.query.count(), 1)
        self.assertEqual(A.Watchlist.query.count(), 1)
        self.assertIsNotNone(A.db.session.get(A.Showtime, self.show_id))

        response = self.client.post(f'/admin/movie/{self.movie_id}/archive?q=Catalog+Archive',
                                    data={'csrf_token': token}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertFalse(A.db.session.get(A.Movie, self.movie_id).is_archived)
        self.assertIn('Catalog Archive Fixture', self.client.get(
            '/admin?q=Catalog+Archive&visibility=active').text)

    def test_only_admin_can_archive(self):
        viewer_client = self.client_for(self.viewer)
        self.assertEqual(viewer_client.get('/').status_code, 200)
        with viewer_client.session_transaction() as state:
            token = state['_csrf_token']
        response = viewer_client.post(
            f'/admin/movie/{self.movie_id}/archive', data={'csrf_token': token})
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(A.db.session.get(A.Movie, self.movie_id).is_archived)

    def test_home_uses_each_movies_own_poster(self):
        first = A.Movie(title='Poster Mapping Fixture One', description='Poster test',
                        duration=110, poster='https://image.tmdb.org/t/p/w500/fixture-one.jpg',
                        featured_order=1)
        second = A.Movie(title='Poster Mapping Fixture Two', description='Poster test',
                         duration=115, poster='https://image.tmdb.org/t/p/w500/fixture-two.jpg',
                         featured_order=2)
        A.db.session.add_all([first, second])
        A.db.session.flush()
        A.db.session.add_all([
            A.Showtime(movie=first, screen=self.screen, theater=self.theater.name,
                       show_date=date.today() + timedelta(days=3), show_time='6:00 PM'),
            A.Showtime(movie=second, screen=self.screen, theater=self.theater.name,
                       show_date=date.today() + timedelta(days=3), show_time='9:00 PM'),
        ])
        A.db.session.commit()

        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('src="https://image.tmdb.org/t/p/w500/fixture-one.jpg" alt="Poster Mapping Fixture One poster"', html)
        self.assertIn('src="https://image.tmdb.org/t/p/w500/fixture-two.jpg" alt="Poster Mapping Fixture Two poster"', html)
        self.assertNotIn('coastal-spotlight.jpg', html)

    def test_verification_requires_https_evidence_and_records_reviewer(self):
        token = self.csrf_token()
        endpoint = f'/admin/theater/{self.theater_id}/verify'
        invalid = self.client.post(endpoint, data={
            'csrf_token': token, 'verification_status': 'verified',
            'verification_source_url': '', 'verification_notes': 'No source'}
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(A.db.session.get(A.Theater, self.theater_id).verification_status, 'unverified')

        invalid_url = self.client.post(endpoint, data={
            'csrf_token': token, 'verification_status': 'verified',
            'verification_source_url': 'http://example.test/listing'}
        )
        self.assertEqual(invalid_url.status_code, 400)

        source = 'https://in.bookmyshow.com/vizag-visakhapatnam/cinemas'
        response = self.client.post(endpoint, data={
            'csrf_token': token, 'verification_status': 'verified',
            'verification_source_url': source, 'verification_notes': 'Venue listing checked.'}
        )
        self.assertEqual(response.status_code, 303)
        venue = A.db.session.get(A.Theater, self.theater_id)
        self.assertTrue(venue.is_verified)
        self.assertEqual(venue.verification_source_url, source)
        self.assertEqual(venue.verification_notes, 'Venue listing checked.')
        self.assertEqual(venue.verification_reviewed_by_id, self.admin.id)
        self.assertIsNotNone(venue.verification_reviewed_at)

    def test_screen_review_can_remain_unverified_until_evidence_is_added(self):
        token = self.csrf_token()
        response = self.client.post(f'/admin/screen/{self.screen_id}/verify', data={
            'csrf_token': token, 'verification_status': 'needs_review',
            'verification_source_url': '', 'verification_notes': 'Screen identity still needs checking.'}
        )
        self.assertEqual(response.status_code, 303)
        screen = A.db.session.get(A.Screen, self.screen_id)
        self.assertEqual(screen.verification_status, 'needs_review')
        self.assertFalse(screen.is_verified)
        self.assertEqual(screen.verification_notes, 'Screen identity still needs checking.')


if __name__ == '__main__':
    unittest.main(verbosity=2)
