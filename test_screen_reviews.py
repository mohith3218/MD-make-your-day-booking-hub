"""Screen review and hype regressions, using an isolated in-memory SQLite app."""
from datetime import timedelta
from os import environ
import unittest
from unittest.mock import patch

from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import MultiDict

from cinewave.extensions import db
from cinewave.factory import create_app
from cinewave.models import (Booking, Movie, MovieHypeVote, MovieRating, Payment, Screen, ScreenReview,
                             ScreenReviewModeration, ScreenReviewReport, Showtime, Theater, User)
from cinewave.time import cinema_now


class CineWaveExperienceTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(environ, APP_ENV='development'):
            self.app = create_app({
                'APP_ENV': 'testing', 'TESTING': True, 'SESSION_COOKIE_SECURE': False,
                'SESSION_PROTECTION': 'basic',
                'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'SQLALCHEMY_ENGINE_OPTIONS': {},
            })
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        self.addCleanup(lambda: db.engine.dispose())
        self.addCleanup(db.session.remove)
        db.create_all()
        self.viewer = User(username='Screen Viewer', password_hash='fixture')
        self.second = User(username='Other Viewer', password_hash='fixture')
        self.admin = User(username='Review Admin', password_hash='fixture', is_admin=True)
        self.movie = Movie(title='Now Showing', description='Fixture', duration=120)
        self.upcoming = Movie(title='Coming Soon', description='Fixture', duration=100, is_upcoming=True)
        self.theater = Theater(name='Seaside Cinema', location='Beach Road', address='Main Road')
        self.other_theater = Theater(name='Other Cinema')
        self.screen = Screen(theater=self.theater, name='Main Hall', screen_type='2D')
        self.screen.layout = {'classes': [{'name': 'Standard', 'code': 'STD', 'price': 150,
                                           'rows': [{'label': 'A', 'count': 4}]}]}
        self.other_screen = Screen(theater=self.theater, name='Small Hall', screen_type='3D')
        db.session.add_all([self.viewer, self.second, self.admin, self.screen, self.other_screen,
                            self.other_theater, self.upcoming])
        self.ended = self.show(cinema_now() - timedelta(days=1))
        self.in_progress = self.show(cinema_now() - timedelta(minutes=20))
        self.future = self.show(cinema_now() + timedelta(days=2))
        self.booking = self.book(self.viewer, self.ended)
        db.session.commit()
        self.client = self.client_for(self.viewer)

    def client_for(self, user):
        client = self.app.test_client()
        with client.session_transaction() as state:
            state['_user_id'] = user.alternative_id
            state['_fresh'] = True
            state['_csrf_token'] = 'test-form-token'
        return client

    def show(self, start, screen=None):
        screen = screen or self.screen
        show = Showtime(movie=self.movie, screen=screen, theater=screen.theater.name,
                        show_date=start.date(), show_time=start.strftime('%H:%M'))
        db.session.add(show)
        return show

    @staticmethod
    def book(user, show, status='PAID'):
        booking = Booking(user=user, showtime=show, seats='A1', status=status, total_amount=150)
        db.session.add(booking)
        return booking

    def edit_url(self, booking=None):
        return f'/booking/{(booking or self.booking).reference}/screen-review'

    def detail_url(self, screen=None):
        screen = screen or self.screen
        return f'/theatres/{screen.theater_id}/screens/{screen.id}/reviews'

    @staticmethod
    def post(client, url, **values):
        return client.post(url, data={'csrf_token': 'test-form-token', **values})

    def submit(self, booking=None, client=None, **values):
        return self.post(client or self.client, self.edit_url(booking), **values)

    def test_invites_only_eligible_bookings_and_dismisses_without_blocking_review(self):
        pending = self.book(self.viewer, self.ended, 'PENDING')
        canceled = self.book(self.viewer, self.ended, 'CANCELLED')
        ongoing = self.book(self.viewer, self.in_progress)
        future = self.book(self.viewer, self.future)
        demo = self.book(self.viewer, self.ended)
        demo.payment = Payment(gateway='mock', status='CAPTURED')
        refunded = self.book(self.viewer, self.ended)
        refunded.payment = Payment(gateway='historical', status='REFUNDED')
        no_screen = self.show(cinema_now() - timedelta(days=1))
        no_screen.screen = None
        legacy = self.book(self.viewer, no_screen)
        db.session.commit()
        for booking in (pending, canceled, ongoing, future, demo, refunded, legacy):
            with self.subTest(status=booking.status, ref=booking.reference):
                self.assertNotIn('Review This Screen', self.client.get(f'/ticket/{booking.reference}').text)
                self.assertEqual(self.client.get(self.edit_url(booking)).status_code, 403)
                self.assertEqual(self.submit(booking, overall_rating='5').status_code, 403)
        ticket = f'/ticket/{self.booking.reference}'
        self.assertIn('How was your movie experience?', self.client.get(ticket).text)
        self.assertIn('Review This Screen', self.client.get('/dashboard').text)
        self.assertEqual(self.client.get(self.edit_url()).status_code, 200)
        self.assertEqual(self.client.post(self.edit_url() + '/dismiss').status_code, 400)
        self.assertEqual(self.post(self.client, self.edit_url() + '/dismiss').status_code, 303)
        self.assertNotIn('How was your movie experience?', self.client.get(ticket).text)
        self.assertNotIn('Review This Screen', self.client.get('/dashboard').text)
        self.assertEqual(self.client.get(self.edit_url()).status_code, 200)

    def test_review_ownership_context_csrf_and_input_validation(self):
        self.assertEqual(self.client.post(self.edit_url(), data={'overall_rating': 4}).status_code, 400)
        self.assertEqual(self.client_for(self.second).get(self.edit_url()).status_code, 404)
        self.assertEqual(self.submit(client=self.client_for(self.second), overall_rating=4).status_code, 404)
        self.assertEqual(self.submit(overall_rating=4, screen_id=self.other_screen.id).status_code, 404)
        self.assertEqual(self.submit(overall_rating=4, theatre_id=self.other_theater.id).status_code, 404)
        self.assertEqual(self.client.get(f'/theatres/{self.other_theater.id}/screens/{self.screen.id}/reviews').status_code, 404)
        for values in ({}, {'overall_rating': '0'}, {'overall_rating': '6'}, {'overall_rating': '3.5'},
                       {'overall_rating': '1', 'ac_rating': '0'},
                       {'overall_rating': '1', 'review_text': 'a' * 1001},
                       {'overall_rating': '1', 'review_text': 'bad\x00text'}):
            response = self.submit(**values)
            self.assertEqual(response.status_code, 422)
            self.assertIn('Check the highlighted questions', response.text)
        self.assertEqual(self.client.post(self.edit_url(), data=MultiDict([
            ('csrf_token', 'test-form-token'), ('overall_rating', '2'), ('overall_rating', '3'),
        ])).status_code, 422)
        self.assertEqual(ScreenReview.query.count(), 0)
        markup = '<img src=x onerror=alert(1)>'
        response = self.submit(overall_rating=4, user_id=self.admin.id, verified='0', review_text=markup)
        self.assertEqual(response.status_code, 303)
        review = ScreenReview.query.one()
        self.assertEqual((review.user_id, review.booking_id, review.theater_id, review.screen_id),
                         (self.viewer.id, self.booking.id, self.theater.id, self.screen.id))
        self.assertTrue(review.verified)
        self.assertIsNone(review.sound_rating)
        rendered = self.client.get(self.detail_url()).text
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', rendered)
        self.assertNotIn(markup, rendered)

    def test_edit_updates_same_review_and_withdrawal_removes_it_from_public_view(self):
        self.assertEqual(self.submit(overall_rating=2, sound_rating=3).status_code, 303)
        original = ScreenReview.query.one()
        ticket = self.client.get(f'/ticket/{self.booking.reference}').text
        self.assertIn('Edit screen review', ticket)
        self.assertNotIn('How was your movie experience?', ticket)
        self.assertEqual(self.submit(overall_rating=5, sound_rating='').status_code, 303)
        review = ScreenReview.query.one()
        self.assertEqual(original.id, review.id)
        self.assertEqual(review.overall_rating, 5)
        self.assertIsNone(review.sound_rating)
        self.assertEqual(self.post(self.client_for(self.second), self.edit_url() + '/withdraw').status_code, 404)
        self.assertEqual(self.post(self.client, self.edit_url() + '/withdraw').status_code, 303)
        self.assertEqual(self.client.get(self.edit_url()).status_code, 409)
        self.assertEqual(ScreenReview.query.count(), 1)
        self.assertIsNotNone(ScreenReview.query.one().withdrawn_at)
        self.assertIn('Not rated yet', self.client.get(self.detail_url()).text)

    def test_review_database_enforces_booking_uniqueness_and_integer_bounds(self):
        values = dict(booking_id=self.booking.id, user_id=self.viewer.id,
                      theater_id=self.theater.id, screen_id=self.screen.id)
        for invalid in (0, 5.1, 1.5, 6):
            db.session.add(ScreenReview(**values, overall_rating=invalid))
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()
        self.submit(overall_rating=4)
        db.session.add(ScreenReview(**values, overall_rating=3))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_theatre_weights_reviews_and_screen_filters_preserve_real_scores(self):
        db.session.add(MovieRating(user=self.viewer, movie=self.movie, rating=1))
        db.session.commit()
        listing = self.client.get('/theatres').text
        self.assertIn('Not rated yet', listing)
        self.assertIn('Explore Screens', listing)
        self.assertIn('Main Road', listing)

        low = self.book(self.second, self.ended)
        second_show = self.show(cinema_now() - timedelta(days=2), self.other_screen)
        unverified = self.book(self.second, second_show)
        db.session.flush()
        db.session.add(ScreenReview(booking=unverified, user=self.second, theater=self.theater,
                                    screen=self.other_screen, overall_rating=5, review_text='Imported note'))
        high = self.book(self.viewer, self.ended)
        db.session.commit()
        self.submit(overall_rating=5, sound_rating=4, ac_rating=3, comfort_rating=5, review_text='Clear sound')
        self.submit(low, client=self.client_for(self.second), overall_rating=1, review_text='Low score')
        self.submit(high, overall_rating=1, review_text='Another review')

        theatre = self.client.get(f'/theatres/{self.theater.id}').text
        self.assertIn('3.0/5</strong> theatre rating', theatre)
        self.assertIn('2.3/5</strong> overall screen rating', theatre)
        self.assertIn('5.0/5</strong> overall screen rating', theatre)
        self.assertIn('4 reviews', theatre)
        self.assertIn('3 verified booking reviews', theatre)
        self.assertIn('3.0/5</strong> theatre rating', self.client.get('/theatres').text)
        details = self.client.get(self.detail_url() + '?sort=lowest').text
        self.assertLess(details.index('Low score'), details.index('Clear sound'))
        self.assertIn('Verified Booking', details)
        self.assertIn('<dt>Sound</dt><dd>4.0/5', details)
        self.assertIn('<dt>AC</dt><dd>3.0/5', details)
        self.assertIn('<dt>Seat comfort</dt><dd>5.0/5', details)
        self.assertIn('value="2" aria-label="1-star reviews"', details)
        highest = self.client.get(self.detail_url() + '?sort=highest').text
        self.assertLess(highest.index('Clear sound'), highest.index('Low score'))
        recent = self.client.get(self.detail_url()).text
        self.assertLess(recent.index('Another review'), recent.index('Clear sound'))
        other_detail = self.detail_url(self.other_screen)
        self.assertIn('Imported note', self.client.get(other_detail).text)
        self.assertNotIn('Verified Booking</p>', self.client.get(other_detail).text)
        self.assertNotIn('Imported note', self.client.get(other_detail + '?verified=1').text)
        self.assertEqual(self.client.get(f'/theatres/{self.theater.id}/shows/{self.future.id}/book').status_code, 302)

    def test_reports_and_admin_hide_restore_leave_ratings_and_history_intact(self):
        self.submit(overall_rating=5, review_text='A genuine experience')
        review = ScreenReview.query.one()
        report_path = f'/screen-reviews/{review.id}/report'
        admin_path = f'/admin/screen-reviews/{review.id}/moderate'
        reporter = self.client_for(self.second)
        admin = self.client_for(self.admin)
        self.assertEqual(self.post(self.client, report_path, reason='My own review').status_code, 403)
        self.assertEqual(reporter.post(report_path, data={'reason': 'Existing content'}).status_code, 400)
        self.assertEqual(self.post(reporter, report_path, reason='Inappropriate content').status_code, 303)
        self.assertEqual(self.post(reporter, report_path, reason='Repeated report').status_code, 303)
        self.assertEqual(ScreenReviewReport.query.count(), 1)
        self.assertEqual(reporter.get('/admin/screen-reviews').status_code, 403)
        self.assertEqual(self.post(reporter, admin_path, action='hide').status_code, 403)
        self.assertIn('Inappropriate content', admin.get('/admin/screen-reviews?view=reported').text)
        self.assertEqual(self.post(admin, admin_path, action='hide', overall_rating=1).status_code, 303)
        self.assertEqual(review.overall_rating, 5)
        self.assertIsNotNone(ScreenReviewReport.query.one().resolved_at)
        self.assertIn('Not rated yet', reporter.get(self.detail_url()).text)
        self.assertIn('Not rated yet', reporter.get('/theatres').text)
        self.assertEqual(self.submit(overall_rating=4, hidden='0', review_text='Edited').status_code, 303)
        self.assertTrue(review.hidden)
        self.assertEqual(self.post(admin, admin_path, action='restore').status_code, 303)
        self.assertIn('Edited', reporter.get(self.detail_url() + '?verified=1').text)
        self.assertEqual([row.action for row in ScreenReviewModeration.query.order_by(ScreenReviewModeration.id)],
                         ['hide', 'restore'])

    def test_hype_json_updates_all_counts_and_same_vote_is_idempotent(self):
        url = f'/movies/{self.upcoming.id}/hype'
        accept_json = {'Accept': 'application/json'}
        data = {'csrf_token': 'test-form-token', 'level': 'HYPED'}
        self.assertEqual(self.app.test_client().post(url, data=data, headers=accept_json).status_code, 401)
        self.assertEqual(self.client.post(url, data={'level': 'HYPED'}, headers=accept_json).status_code, 400)
        self.assertEqual(self.post(self.client, url, level='invalid').status_code, 400)
        self.assertEqual(self.post(self.client, f'/movies/{self.movie.id}/hype', level='HYPED').status_code, 404)
        self.post(self.client_for(self.second), url, level='SUPER_HYPED')
        for level in ('HYPED', 'SUPER_HYPED', 'EXTREME_HYPED', 'EXTREME_HYPED'):
            response = self.client.post(url, data={**data, 'level': level}, headers=accept_json)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {'selected': level, 'counts': {
                choice: int(choice == level) + int(choice == 'SUPER_HYPED')
                for choice in ('HYPED', 'SUPER_HYPED', 'EXTREME_HYPED')
            }})
        self.assertEqual(MovieHypeVote.query.filter_by(movie_id=self.upcoming.id).count(), 2)
        page = self.client.get(f'/movie/{self.upcoming.id}').text
        self.assertIn('value="EXTREME_HYPED" aria-pressed="true"', page)
        self.assertTrue(self.post(self.client, url, level='HYPED', return_to='movie').location.endswith('#movie-hype'))
