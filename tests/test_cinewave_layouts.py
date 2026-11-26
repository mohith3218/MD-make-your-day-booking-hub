"""Regression coverage for CineWave's page layout shells and skip link."""
import os
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest
from flask import url_for

_temporary = tempfile.TemporaryDirectory(prefix='cinewave-layouts-')
_database_url = 'sqlite:///' + (Path(_temporary.name) / 'layouts.db').as_posix()
os.environ.update(APP_ENV='testing', DATABASE_URL=_database_url,
                  TEST_DATABASE_URL=_database_url,
                  SECRET_KEY='isolated-cinewave-layouts-fixture', SMTP_HOST='', TMDB_API_KEY='')

import app as A


class CineWaveLayoutTests(unittest.TestCase):
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

        self.admin = A.User(username='layout_admin', password_hash='fixture', is_admin=True)
        self.customer = A.User(username='layout_customer', password_hash='fixture')
        self.unverified = A.User(username='layout_unverified', password_hash='fixture',
                                 email='unverified@example.test', email_verified=False)
        self.movie = A.Movie(title='Layout Fixture Film', description='Layout regression fixture',
                             duration=120, is_upcoming=False)
        self.theater = A.Theater(name='Layout Fixture Cinema', location='Test locality')
        self.screen = A.Screen(theater=self.theater, name='Screen 1', layout_json=(
            '{"classes":[{"code":"STD","name":"Standard","price":100,'
            '"rows":[{"label":"A","seats":["A1","A2"]}]}]}'))
        self.showtime = A.Showtime(movie=self.movie, screen=self.screen,
                                   theater=self.theater.name,
                                   show_date=date.today() + timedelta(days=3),
                                   show_time='7:30 PM')
        A.db.session.add_all([self.admin, self.customer, self.unverified,
                              self.movie, self.theater, self.screen, self.showtime])
        A.db.session.flush()
        self.booking = A.Booking(user=self.customer, showtime=self.showtime, seats='A1',
                                 ticket_amount=100, total_amount=110, status='PENDING')
        A.db.session.add(self.booking)
        A.db.session.commit()
        self.movie_id, self.screen_id = self.movie.id, self.screen.id
        self.showtime_id, self.booking_ref = self.showtime.id, self.booking.reference
        self.client = self.client_for(self.customer)
        self.admin_client = self.client_for(self.admin)

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

    def assert_one_layout(self, html, expected, forbidden):
        self.assertEqual(html.count(expected), 1)
        self.assertNotIn(forbidden, html)
        self.assertEqual(html.count('aria-label="Main navigation"') +
                         html.count('aria-label="Administration"'), 1)

    def test_public_pages_use_customer_navigation(self):
        with A.app.test_request_context():
            theatre_url = url_for('theatre_discovery.index')
        urls = ('/', f'/movie/{self.movie_id}', theatre_url)
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assert_one_layout(response.get_data(as_text=True),
                                       'aria-label="Main navigation"',
                                       'aria-label="Administration"')

    def test_every_admin_get_page_uses_the_admin_shell(self):
        urls = (
            '/admin', '/admin/analytics', '/admin/bookings', '/admin/recharges',
            '/admin/screens', '/admin/add_movie', '/admin/import_movie',
            '/admin/add_theater', '/admin/add_screen', '/admin/add_showtime',
            f'/admin/screen/{self.screen_id}/layout',
            f'/admin/screen/{self.screen_id}/auditorium-reference',
        )
        for url in urls:
            with self.subTest(url=url):
                response = self.admin_client.get(url)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assert_one_layout(html, 'aria-label="Administration"',
                                       'aria-label="Main navigation"')

    def test_auth_pages_use_minimal_auth_shell(self):
        urls = ('/login', '/register', '/forgot-password', '/reset-password')
        for url in urls:
            with self.subTest(url=url):
                response = A.app.test_client().get(url)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn('cw-auth-brandbar', html)
                self.assertNotIn('aria-label="Main navigation"', html)
                self.assertNotIn('aria-label="Administration"', html)
                self.assertNotIn('cw-demo-notice', html)

        pending = A.app.test_client()
        with pending.session_transaction() as state:
            state['pending_email_verification_user_id'] = self.unverified.id
        verify = pending.get('/verify-email')
        self.assertEqual(verify.status_code, 200)
        self.assertIn('cw-auth-brandbar', verify.get_data(as_text=True))

    def test_booking_and_checkout_use_compact_booking_shell(self):
        for url in (f'/book/{self.showtime_id}', f'/checkout/{self.booking_ref}'):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn('cw-booking-header', html)
                self.assertNotIn('aria-label="Main navigation"', html)
                self.assertNotIn('aria-label="Administration"', html)
                self.assertEqual(html.count('class="cw-booking-header"'), 1)

    def test_skip_link_is_a_keyboard_only_focusable_path_to_main(self):
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('<a class="cine-skip" href="#main-content">Skip to content</a>', html)
        self.assertIn('<main id="main-content" tabindex="-1"', html)
        stylesheet = (Path(__file__).resolve().parents[1] / 'static' / 'css' /
                      'coastal.css').read_text(encoding='utf-8')
        self.assertIn('body#app-body .cine-skip:focus-visible', stylesheet)
        self.assertIn('transform:translateY(calc(-100% - 1.5rem))', stylesheet)
        self.assertNotIn('display:none', stylesheet.split('body#app-body .cine-skip {', 1)[1]
                         .split('}', 1)[0])

    def test_admin_dashboard_navigation_has_no_duplicate_route_bar(self):
        html = self.admin_client.get('/admin').get_data(as_text=True)
        self.assertIn('id="cw-main-nav" class="cw-nav cw-admin-nav"', html)
        self.assertEqual(html.count('aria-label="Administration"'), 1)
        self.assertNotIn('aria-label="Main navigation"', html)
        self.assertEqual(html.count('href="/admin/analytics"'), 1)


if __name__ == '__main__':
    unittest.main()
