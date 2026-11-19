"""Featured home carousel and admin ordering regressions on disposable SQLite."""
import json
import os
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

from theatre_discovery import cinema_now

ROOT = Path(__file__).resolve().parent
_temporary = tempfile.TemporaryDirectory(prefix='cinewave-featured-')
_url = 'sqlite:///' + (Path(_temporary.name) / 'test.db').as_posix()
os.environ.update(APP_ENV='testing', DATABASE_URL=_url, TEST_DATABASE_URL=_url,
                  SECRET_KEY='isolated-cinewave-featured-fixture', SMTP_HOST='', TMDB_API_KEY='')

import app as A


class FeaturedMovieTests(unittest.TestCase):
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
        self.admin = A.User(username='featured_admin', password_hash='fixture', is_admin=True)
        self.viewer = A.User(username='featured_viewer', password_hash='fixture')
        self.theater = A.Theater(name='Featured Fixture Cinema', location='Test locality')
        self.screen = A.Screen(theater=self.theater, name='Screen 1', layout_json=(
            '{"classes":[{"code":"STD","name":"Standard","price":100,'
            '"rows":[{"label":"A","start":1,"count":2}]}]}'))
        A.db.session.add_all([self.admin, self.viewer, self.theater, self.screen])
        A.db.session.commit()
        self.admin_client = self.client_for(self.admin)
        self.viewer_client = self.client_for(self.viewer)

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

    def csrf_token(self):
        self.assertEqual(self.admin_client.get('/admin').status_code, 200)
        with self.admin_client.session_transaction() as state:
            return state['_csrf_token']

    def make_movie(self, title, order=None, **fields):
        movie = A.Movie(title=title, description=f'{title} synopsis', duration=120,
                        featured_order=order, **fields)
        A.db.session.add(movie)
        A.db.session.flush()
        return movie

    def add_show(self, movie, time):
        show = A.Showtime(movie=movie, screen=self.screen, theater=self.theater.name,
                          show_date=cinema_now().date() + timedelta(days=2), show_time=time)
        A.db.session.add(show)
        A.db.session.flush()
        return show

    def test_home_uses_ordered_records_matched_artwork_trailer_and_booking(self):
        first = self.make_movie(
            'First Feature Fixture', 1, poster='https://images.test/first-poster.jpg',
            backdrop='https://images.test/first-backdrop.jpg', youtube_trailer_key='abcdefghijk',
            cast_json=json.dumps({'director': 'First Director', 'cast': []}), rating=8.2)
        second = self.make_movie(
            'Second Feature Fixture', 2, poster='https://images.test/second-poster.jpg',
            is_upcoming=True, rating=7.6)
        archived = self.make_movie('Archived Feature Fixture', 0, is_archived=True,
                                   poster='https://images.test/archived.jpg')
        first_show = self.add_show(first, '6:00 PM')
        A.db.session.commit()

        html = self.viewer_client.get('/').get_data(as_text=True)
        self.assertLess(html.index('First Feature Fixture'), html.index('Second Feature Fixture'))
        self.assertNotIn('Archived Feature Fixture', html)
        first_slide = html.split('data-slide-index="0"', 1)[1].split('</article>', 1)[0]
        second_slide = html.split('data-slide-index="1"', 1)[1].split('</article>', 1)[0]
        self.assertIn('First Director', first_slide)
        self.assertIn('https://images.test/first-backdrop.jpg', first_slide)
        self.assertNotIn('second-poster.jpg', first_slide)
        self.assertIn('https://www.youtube.com/watch?v=abcdefghijk', first_slide)
        self.assertIn(f'href="/book/{first_show.id}"', first_slide)
        self.assertIn('https://images.test/second-poster.jpg', second_slide)
        self.assertIn('is-poster', second_slide)
        self.assertIn('Coming soon', second_slide)
        self.assertNotIn('/book/', second_slide)
        self.assertIn('data-feature-next', html)

    def test_empty_featured_list_has_a_clean_fallback_without_fabricated_movie(self):
        self.make_movie('Not Featured Fixture', poster='https://images.test/not-featured.jpg')
        A.db.session.commit()
        html = self.viewer_client.get('/').get_data(as_text=True)
        self.assertIn('cw-feature-empty', html)
        self.assertIn('Stories made for the big screen.', html)
        self.assertNotIn('data-feature-slide', html)
        self.assertNotIn('Not Featured Fixture', html.split('cw-feature-empty', 1)[1].split('</section>', 1)[0])
        self.assertNotIn('Browse screenings', html.split('cw-feature-empty', 1)[1].split('</section>', 1)[0])

    def test_missing_artwork_uses_that_movies_title_placeholder(self):
        movie = self.make_movie('Artwork Missing Fixture', 1)
        A.db.session.commit()
        html = self.viewer_client.get('/').get_data(as_text=True)
        slide = html.split('data-slide-index="0"', 1)[1].split('</article>', 1)[0]
        self.assertIn('cw-feature-art is-missing', slide)
        self.assertNotIn('data-feature-image', slide)
        self.assertIn('<span>Artwork Missing Fixture</span>', slide)

    def test_admin_can_rank_remove_and_archive_featured_movies(self):
        first = self.make_movie('Rank Fixture One', 1)
        second = self.make_movie('Rank Fixture Two')
        third = self.make_movie('Rank Fixture Three')
        A.db.session.commit()
        token = self.csrf_token()

        response = self.admin_client.post(f'/admin/movie/{second.id}/feature',
            data={'csrf_token': token, 'featured_order': '1'}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(A.db.session.get(A.Movie, second.id).featured_order, 1)
        self.assertEqual(A.db.session.get(A.Movie, first.id).featured_order, 2)

        response = self.admin_client.post(f'/admin/movie/{third.id}/feature',
            data={'csrf_token': token, 'featured_order': '2'}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual([m.title for m in A.Movie.query.filter(
            A.Movie.featured_order.isnot(None)).order_by(A.Movie.featured_order).all()],
            ['Rank Fixture Two', 'Rank Fixture Three', 'Rank Fixture One'])

        response = self.admin_client.post(f'/admin/movie/{third.id}/feature',
            data={'csrf_token': token, 'featured_order': ''}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIsNone(A.db.session.get(A.Movie, third.id).featured_order)
        self.assertEqual(A.db.session.get(A.Movie, first.id).featured_order, 2)

        response = self.admin_client.post(f'/admin/movie/{second.id}/archive',
            data={'csrf_token': token}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIsNone(A.db.session.get(A.Movie, second.id).featured_order)
        self.assertEqual(A.db.session.get(A.Movie, first.id).featured_order, 1)

    def test_feature_list_caps_at_five_and_clears_the_displaced_rank(self):
        movies = [self.make_movie(f'Cap Fixture {index}') for index in range(1, 7)]
        A.db.session.commit()
        token = self.csrf_token()
        for movie in movies:
            response = self.admin_client.post(f'/admin/movie/{movie.id}/feature',
                data={'csrf_token': token, 'featured_order': '5'}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
        ranked = A.Movie.query.filter(A.Movie.featured_order.isnot(None)).all()
        self.assertEqual(len(ranked), 5)
        self.assertEqual(sorted(movie.featured_order for movie in ranked), [1, 2, 3, 4, 5])
        self.assertIsNone(A.db.session.get(A.Movie, movies[4].id).featured_order)

    def test_feature_assignment_requires_admin_and_valid_position(self):
        movie = self.make_movie('Protected Feature Fixture')
        A.db.session.commit()
        viewer_response = self.viewer_client.post(
            f'/admin/movie/{movie.id}/feature', data={'featured_order': '1'})
        self.assertNotEqual(viewer_response.status_code, 200)
        token = self.csrf_token()
        invalid = self.admin_client.post(f'/admin/movie/{movie.id}/feature',
            data={'csrf_token': token, 'featured_order': '6'})
        self.assertEqual(invalid.status_code, 400)
        self.assertIsNone(A.db.session.get(A.Movie, movie.id).featured_order)
        missing_csrf = self.admin_client.post(
            f'/admin/movie/{movie.id}/feature', data={'featured_order': '1'})
        self.assertEqual(missing_csrf.status_code, 400)

    def test_add_movie_can_store_backdrop_and_assign_feature_order(self):
        response = self.admin_client.post('/admin/add_movie', data={
            'title': 'Added Feature Fixture', 'description': 'Added movie description',
            'duration': '118', 'category': 'upcoming', 'release_type': 'fresh',
            'language': 'Telugu', 'certificate': 'U/A',
            'poster': 'https://images.test/added-poster.jpg',
            'backdrop': 'https://images.test/added-backdrop.jpg',
            'featured_order': '1', 'youtube_trailer': ''}, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        movie = A.Movie.query.filter_by(title='Added Feature Fixture').one()
        self.assertEqual(movie.featured_order, 1)
        self.assertTrue(movie.is_upcoming)
        self.assertEqual(movie.backdrop, 'https://images.test/added-backdrop.jpg')


if __name__ == '__main__':
    unittest.main()
