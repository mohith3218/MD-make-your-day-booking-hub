from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from cinewave.extensions import db
from cinewave.factory import create_app
from cinewave.models import (
    Booking, Movie, MovieRating, MovieSyncCandidate, MovieSyncState, Screen, Showtime, Theater, User, Wallet,
)
from cinewave.services import movie_sync
from cinewave.services.movies import TMDBClient, TMDBError, movie_metadata
from cinewave.time import cinema_now


def detail(movie_id, **overrides):
    return {
        'id': movie_id,
        'title': f'Fixture film {movie_id}',
        'overview': 'A young filmmaker returns to their seaside hometown.',
        'poster_path': f'/poster{movie_id}.jpg',
        **overrides,
    }


class MovieSyncTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = {
            'TESTING': True, 'SESSION_PROTECTION': None, 'SECRET_KEY': 'local-test-secret',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + (Path(self.directory.name) / 'sync.db').as_posix(),
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'TMDB_API_KEY': 'test-key', 'TMDB_READ_TOKEN': '', 'TMDB_REGION': 'IN',
        }
        self.app = create_app(self.settings)
        self.context = self.app.app_context()
        self.context.push()
        self.addCleanup(self.close_database)
        db.create_all()

    def close_database(self):
        engine = db.engine
        self.context.pop()
        engine.dispose()

    def mocked_run(self, movies, *, force=True):
        def get(client, path, **params):
            if path == '/movie/now_playing':
                return {'total_pages': 1, 'results': [{'id': movie_id} for movie_id in movies]}
            if path in {'/movie/upcoming', '/discover/movie'}:
                return {'total_pages': 1, 'results': []}
            return movies[int(path.rsplit('/', 1)[1])]
        with patch.object(TMDBClient, 'get', get):
            return movie_sync.run_sync(force=force)

    def age_movie(self, movie):
        movie.tmdb_last_checked_at = movie_sync.utc_now() - timedelta(days=2)
        db.session.commit()

    def test_mandatory_fields_and_incomplete_movies_are_retried_without_discovery(self):
        movies = {
            1: detail(1), 2: detail(2, title=' '), 3: detail(3, overview='No overview available.'),
            4: detail(4, poster_path='https://example.test/poster.jpg'),
        }
        counts, error = self.mocked_run(movies)
        self.assertIsNone(error)
        self.assertEqual(counts, {'imported': 1, 'skipped': 3, 'updated': 0, 'failed': 0})
        self.assertEqual(MovieSyncCandidate.query.count(), 3)
        movie = Movie.query.filter_by(tmdb_id=1).one()
        self.assertEqual(movie.duration, 0)
        self.assertTrue(all(value is None for value in (
            movie.rating, movie.tmdb_rating, movie.language, movie.certificate, movie.release_date,
        )))

        for candidate in MovieSyncCandidate.query.all():
            candidate.next_attempt_at = movie_sync.utc_now() - timedelta(minutes=1)
        db.session.commit()
        with patch.object(movie_sync, 'discover', return_value={}), patch.object(
                TMDBClient, 'details', side_effect=lambda movie_id: detail(movie_id)):
            self.assertEqual(movie_sync.run_sync(force=True)[0]['imported'], 3)
        self.assertEqual(MovieSyncCandidate.query.count(), 0)
        self.assertEqual(self.mocked_run(movies)[0]['imported'], 0)
        self.assertEqual(Movie.query.count(), 4)
        db.session.add(Movie(tmdb_id=1, title='Duplicate', description='Duplicate', duration=1))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_metadata_refresh_preserves_overrides_visibility_reviews_and_bookings(self):
        today = cinema_now().date()
        initial = detail(10, original_language='te', release_date=today.isoformat(),
                         runtime=105, backdrop_path='/old.jpg', vote_average=8.1, vote_count=8,
                         genres=[{'name': 'Drama'}], credits={'crew': [{'job': 'Director', 'name': 'Director A'}]})
        self.mocked_run({10: initial})
        movie = Movie.query.filter_by(tmdb_id=10).one()
        movie.title = 'Locally programmed title'
        movie.poster = None
        movie.lock_tmdb_fields('poster')
        movie.is_archived = True
        movie.featured_order = 2
        customer = User(username='reviewer', password_hash='test')
        show = Showtime(movie=movie, theater='Original venue', show_date=today, show_time='10:00',
                        price_overrides_json='{"STD":230}')
        booking = Booking(user=customer, showtime=show, seats='A1', status='PAID', total_amount=230)
        review = MovieRating(movie=movie, user=customer, rating=4, review='A customer review')
        db.session.add_all([booking, review])
        self.age_movie(movie)

        changed = detail(10, original_language='te', release_date=today.isoformat(),
                         overview='A longer synopsis with details about the film.',
                         runtime=112, vote_average=8.6, vote_count=10,
                         videos={'results': [{'site': 'YouTube', 'type': 'Trailer', 'key': 'a1B2c3D4e5F'}]},
                         credits={'cast': [{'name': 'Actor A', 'character': 'Lead'}]})
        self.assertEqual(self.mocked_run({10: changed})[0]['updated'], 1)
        self.assertEqual(movie.title, 'Locally programmed title')
        self.assertIsNone(movie.poster)
        self.assertTrue(movie.is_archived)
        self.assertEqual(movie.featured_order, 2)
        self.assertEqual(movie.description, changed['overview'])
        self.assertEqual(movie.backdrop, 'https://image.tmdb.org/t/p/w1280/old.jpg')
        self.assertEqual(movie.tmdb_rating, 8.6)
        self.assertEqual(movie.display_rating, 4.0)
        self.assertEqual(movie.duration, 112)
        self.assertEqual(movie.trailer_video_key, 'a1B2c3D4e5F')
        self.assertEqual(movie.cast_info['director'], 'Director A')
        self.assertEqual(movie.tmdb_metadata['genres'], ['Drama'])
        self.assertEqual((booking.status, booking.seats, booking.total_amount), ('PAID', 'A1', 230))
        self.assertEqual((show.theater, show.price_overrides['STD']), ('Original venue', 230))
        self.assertEqual(review.review, 'A customer review')

    def test_regional_release_and_manual_match_require_independent_evidence(self):
        today = cinema_now().date()
        recent = today + timedelta(days=12)
        old = today - timedelta(days=1000)
        linked = Movie(title='Same title', description='Existing synopsis', duration=120,
                       language='Hindi', release_date=old)
        other = Movie(title='Same title', description='Different film', duration=160,
                      language='Tamil', release_date=old)
        db.session.add_all([linked, other])
        db.session.commit()
        india = {'results': [{'iso_3166_1': 'IN', 'release_dates': [
            {'release_date': recent.isoformat(), 'type': 3, 'certification': 'UA'},
            {'release_date': old.isoformat(), 'type': 4},
        ]}]}
        payload = {
            11: detail(11, title='Same title', original_language='hi',
                       release_date=old.isoformat(), release_dates=india),
            12: detail(12, release_date=old.isoformat(), status='Released'),
        }
        sync_count, _ = self.mocked_run(payload)
        self.assertEqual(sync_count['updated'], 1)
        self.assertEqual(Movie.query.count(), 2)
        self.assertEqual(linked.tmdb_id, 11)
        self.assertIsNone(other.tmdb_id)
        self.assertEqual(linked.description, 'Existing synopsis')
        self.assertEqual(linked.tmdb_original_release_date, old)
        self.assertEqual(linked.tmdb_regional_release_date, recent)
        self.assertTrue(movie_metadata(payload[11], 'IN')['is_upcoming'])
        self.assertFalse(movie_metadata(payload[12], 'IN', source='upcoming')['is_upcoming'])

    def test_discovery_paginates_without_an_original_language_filter(self):
        calls = []

        def get(path, **params):
            calls.append((path, params))
            return {'total_pages': 2, 'results': [{'id': params['page']}]}

        with TMDBClient() as client, patch.object(client, 'get', get):
            today = cinema_now().date()
            results = movie_sync.discover(client, today, today, today + timedelta(days=1), page_limit=3)
        self.assertEqual(set(results), {1, 2})
        self.assertEqual(len(calls), 8)
        self.assertTrue(all(params['region'] == 'IN' and 'with_original_language' not in params
                            for _, params in calls))
        self.assertTrue(all(params['with_release_type'] == '3|2'
                            for path, params in calls if path == '/discover/movie'))

    def test_rate_limit_honors_retry_after_and_never_exposes_credentials(self):
        response = MagicMock(status_code=429, headers={'Retry-After': '4'})
        response.__enter__.return_value = response
        success = MagicMock(status_code=200, headers={})
        success.__enter__.return_value = success
        success.json.return_value = {'id': 1}
        with TMDBClient() as client, patch.object(client.session, 'get', side_effect=[response, success]), patch(
                'cinewave.services.movies.sleep') as wait:
            self.assertEqual(client.get('/movie/1'), {'id': 1})
            wait.assert_called_once_with(4)
        response.headers = {'Retry-After': '120'}
        with TMDBClient() as client, patch.object(client.session, 'get', return_value=response) as get:
            with self.assertRaises(TMDBError) as caught:
                client.get('/movie/1')
            self.assertEqual(caught.exception.retry_after, 120)
            self.assertNotIn('test-key', str(caught.exception))
            get.assert_called_once()

    def test_rate_limited_worker_cannot_be_forced_until_retry(self):
        with patch.object(TMDBClient, 'get', side_effect=TMDBError(
                'TMDB returned HTTP 429.', status=429, retry_after=1200)):
            _, error = movie_sync.run_sync()
        self.assertIn('429', error)
        state = db.session.get(MovieSyncState, 1)
        self.assertEqual(state.throttle_until, state.next_run_at)
        movie_sync.request_movie_sync()
        self.assertIsNone(movie_sync.run_sync(force=True))
        self.assertIsNotNone(state.requested_at)

    def test_outages_preserve_catalogue_and_a_restarted_worker_recovers(self):
        self.mocked_run({1: detail(1)})
        with patch.object(TMDBClient, 'get', side_effect=TMDBError('TMDB returned HTTP 503.', status=503)):
            _, error = movie_sync.run_sync(force=True)
        state = db.session.get(MovieSyncState, 1)
        self.assertIn('503', error)
        self.assertIsNotNone(state.last_success_at)
        self.assertGreater(state.next_run_at, state.last_attempt_at)
        self.assertIsNotNone(Movie.query.filter_by(tmdb_id=1).first())
        db.session.remove()
        restarted = create_app(self.settings)
        with restarted.app_context():
            engine = db.engine
            self.assertIsNone(movie_sync.run_sync())
            movie_sync.request_movie_sync()
            with patch.object(movie_sync, 'discover', return_value={}):
                result = restarted.test_cli_runner().invoke(args=['sync-movies'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIsNone(db.session.get(MovieSyncState, 1).error)
        engine.dispose()

    def test_concurrent_claims_and_fencing_an_expired_worker(self):
        entered, resume = Event(), Event()

        def first_discovery(*args):
            entered.set()
            if not resume.wait(5):
                raise AssertionError('Concurrent worker did not return')
            return {1: 'recent'}

        def worker():
            with self.app.app_context():
                return movie_sync.run_sync(force=True)

        with patch.object(movie_sync, 'discover', side_effect=first_discovery) as discovery, patch.object(
                TMDBClient, 'details', return_value=detail(1)), ThreadPoolExecutor() as pool:
            first = pool.submit(worker)
            try:
                self.assertTrue(entered.wait(5))
                self.assertIsNone(worker())
            finally:
                resume.set()
            self.assertEqual(first.result(5)[0]['imported'], 1)
            self.assertEqual(discovery.call_count, 1)
        abandoned = movie_sync.claim(force=True)
        state = db.session.get(MovieSyncState, 1)
        state.lease_until = movie_sync.utc_now() - timedelta(seconds=1)
        db.session.commit()
        self.assertIsNotNone(movie_sync.claim(force=False))
        with self.assertRaises(movie_sync.LeaseLost):
            movie_sync.heartbeat(abandoned)
        self.assertEqual(Movie.query.count(), 1)

    def logged_in(self, user):
        client = self.app.test_client()
        with client.session_transaction() as state:
            state['_user_id'] = user.alternative_id
            state['_fresh'] = True
            state['_csrf_token'] = 'form-token'
        return client

    def test_discovery_to_admin_scheduling_booking_and_review_eligibility(self):
        self.mocked_run({25: detail(25, runtime=90, original_language='ml', vote_average=7.1, vote_count=4)})
        movie = Movie.query.filter_by(tmdb_id=25).one()
        admin = User(username='admin', is_admin=True, password_hash='test')
        customer = User(username='customer', password_hash='test')
        theatre = Theater(name='Fixture Cinema')
        screen = Screen(theater=theatre, name='Screen 1', layout_json=(
            '{"classes":[{"code":"STD","name":"Standard","price":100,'
            '"rows":[{"label":"A","count":3}]}]}'))
        db.session.add_all([admin, customer, screen, Wallet(user=customer, balance=500)])
        db.session.commit()
        admin_client, customer_client = self.logged_in(admin), self.logged_in(customer)
        movie_url = f'/movie/{movie.id}'
        review_url = f'/api/movie/{movie.id}/rate'

        self.assertIn('No screenings scheduled yet.', customer_client.get(movie_url).get_data(as_text=True))
        self.assertEqual(customer_client.post(review_url, json={'rating': 5}).status_code, 403)
        for client in (self.app.test_client(), customer_client):
            self.assertEqual(client.post('/admin/movies/sync', data={'csrf_token': 'form-token'}).status_code, 302)
        self.assertIsNone(db.session.get(MovieSyncState, 1).requested_at)
        self.assertEqual(admin_client.post('/admin/movies/sync').status_code, 400)
        self.assertEqual(admin_client.post('/admin/movies/sync', data={'csrf_token': 'form-token'}).status_code, 303)
        self.assertIsNotNone(db.session.get(MovieSyncState, 1).requested_at)
        self.assertIn(movie.title, admin_client.get('/admin?source=tmdb&language=Malayalam&schedule=unscheduled')
                      .get_data(as_text=True))

        response = admin_client.post('/admin/add_showtime', data={
            'csrf_token': 'form-token', 'movie_id': movie.id, 'screen_id': screen.id,
            'show_date': (cinema_now().date() + timedelta(days=2)).isoformat(), 'show_time': '17:00',
            'price_STD': 140,
        })
        self.assertEqual(response.status_code, 302)
        show = Showtime.query.filter_by(movie_id=movie.id).one()
        self.assertIn('Book Screening', customer_client.get('/').get_data(as_text=True))
        self.assertIn(f'/book/{show.id}', customer_client.get(movie_url).get_data(as_text=True))
        self.assertEqual(customer_client.get(f'/book/{show.id}').status_code, 200)
        response = customer_client.post(f'/book/{show.id}', data={'selected_seats': 'A1'})
        self.assertIn('/checkout/', response.headers['Location'])
        booking = db.session.scalars(select(Booking).where(Booking.showtime_id == show.id)).one()
        self.assertEqual(booking.status, 'PENDING')
        self.assertEqual(booking.seats, 'A1')
        with patch('payments.mock_payments_enabled', return_value=True):
            paid = customer_client.post(f'/pay/wallet/{booking.reference}')
            self.assertIn('/ticket/', paid.headers['Location'])
            self.assertEqual(customer_client.get(paid.headers['Location']).status_code, 200)
        self.assertEqual(booking.status, 'PAID')

        show.is_cancelled = True
        db.session.commit()
        self.assertNotIn(f'/book/{show.id}', customer_client.get(movie_url).get_data(as_text=True))
        self.assertEqual(customer_client.get(f'/book/{show.id}').status_code, 302)
        show.is_cancelled = False
        show.show_date = cinema_now().date() - timedelta(days=1)
        db.session.add(Booking(user=customer, showtime=show, seats='A2', status='PAID', total_amount=140))
        db.session.commit()
        self.assertEqual(customer_client.get(f'/book/{show.id}').status_code, 302)
        self.assertEqual(customer_client.post(review_url, json={'rating': 4, 'review': 'Eligible review'}).status_code, 200)
        self.assertIn('Eligible review', customer_client.get(movie_url).get_data(as_text=True))
        self.assertNotIn('Eligible review', admin_client.get(movie_url).get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
