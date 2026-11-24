"""Screen review and hype regressions, using an isolated in-memory SQLite app."""
from datetime import datetime, timedelta
from os import environ
import unittest
from unittest.mock import patch

from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import MultiDict

from cinewave.extensions import db
from cinewave.factory import create_app
from cinewave.models import (Booking, Movie, MovieHypeVote, MovieRating, MovieReviewModeration,
                             MovieReviewReport, Payment, Screen, ScreenReview, ScreenReviewModeration,
                             ScreenReviewReport, Showtime, Theater, User)
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
    def book(user, show, status='PAID', gateway='razorpay', payment_status='CAPTURED'):
        booking = Booking(user=user, showtime=show, seats='A1', status=status, total_amount=150)
        if status == 'PAID' and gateway:
            booking.paid_at = datetime.utcnow()
            booking.payment = Payment(gateway=gateway, status=payment_status)
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
        demo = self.book(self.viewer, self.ended, gateway='mock')
        demo.paid_at = None
        refunded = self.book(self.viewer, self.ended, payment_status='REFUNDED')
        unpaid_capture = self.book(self.viewer, self.ended, payment_status='CREATED')
        missing_payment = self.book(self.viewer, self.ended, gateway=None)
        cancelled_show = self.show(cinema_now() - timedelta(days=1))
        cancelled_show.is_cancelled = True
        cancelled_screening = self.book(self.viewer, cancelled_show)
        wrong_theatre = self.show(cinema_now() - timedelta(days=1))
        wrong_theatre.theater = self.other_theater.name
        mismatched = self.book(self.viewer, wrong_theatre)
        no_screen = self.show(cinema_now() - timedelta(days=1))
        no_screen.screen = None
        legacy = self.book(self.viewer, no_screen)
        db.session.commit()
        for booking in (pending, canceled, ongoing, future, demo, refunded, unpaid_capture,
                        missing_payment, cancelled_screening, mismatched, legacy):
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
        self.assertNotIn('How was your movie experience?', self.client_for(self.viewer).get(ticket).text)
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
        self.assertEqual(self.submit(intent='create', overall_rating=2, sound_rating=3).status_code, 303)
        self.assertEqual(self.submit(intent='create', overall_rating=5).status_code, 409)
        original = ScreenReview.query.one()
        ticket = self.client.get(f'/ticket/{self.booking.reference}').text
        self.assertIn('Edit Screen Review', ticket)
        self.assertIn(f'href="{self.detail_url()}">Read Screen Reviews', ticket)
        self.assertNotIn('How was your movie experience?', ticket)
        self.assertEqual(self.submit(intent='edit', overall_rating=5, sound_rating='').status_code, 303)
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
        self.assertIn('Be the first to review', listing)
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
        self.assertIn('Read Reviews', self.app.test_client().get('/theatres').text)
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

    def test_guests_can_find_and_read_screen_reviews_and_demo_is_never_verified(self):
        guest = self.app.test_client()
        self.assertIn('href="/theatres"', guest.get('/login').text)
        listing = guest.get('/theatres')
        self.assertEqual(listing.status_code, 200)
        self.assertIn(f'/theatres/{self.theater.id}#theatre-screens', listing.text)
        self.assertIn('Be the first to review', listing.text)
        detail = guest.get(f'/theatres/{self.theater.id}')
        self.assertEqual(detail.status_code, 200)
        for screen in (self.screen, self.other_screen):
            self.assertIn(f'href="{self.detail_url(screen)}">View Screen Reviews', detail.text)
        empty = guest.get(self.detail_url())
        self.assertEqual(empty.status_code, 200)
        self.assertIn('Watched a movie here?', empty.text)
        self.assertEqual(guest.post(self.edit_url(), data={'overall_rating': 5}).status_code, 302)
        demo = self.book(self.viewer, self.ended, gateway='mock')
        db.session.flush()
        db.session.add(Payment(booking_id=demo.id, gateway='wallet', status='FAILED'))
        db.session.commit()
        self.assertIn('Review This Screen', self.client.get(f'/ticket/{demo.reference}').text)
        self.assertEqual(self.submit(demo, overall_rating=4, review_text='Demo sound check').status_code, 303)
        review = ScreenReview.query.one()
        self.assertTrue(review.is_demo)
        self.assertFalse(review.verified)
        listing = guest.get(self.detail_url() + '?source=demo&rating=4')
        self.assertIn('Demo Booking Review</p>', listing.text)
        self.assertNotIn('Verified Booking</p>', listing.text)
        self.assertIn('0 verified booking reviews', listing.text)
        self.assertIn('1 demo booking review', listing.text)
        self.assertIn('Demo sound check', listing.text)
        self.assertNotIn(demo.reference, listing.text)
        self.assertNotIn('Report review', listing.text)
        self.assertNotIn('Demo sound check', guest.get(self.detail_url() + '?verified=1').text)
        self.assertNotIn('Demo sound check', guest.get(self.detail_url() + '?rating=5').text)
        report_path = f'/screen-reviews/{review.id}/report'
        self.assertEqual(guest.post(report_path, data={'reason': 'Guest report'}).status_code, 302)

    def test_movie_reviews_require_owned_paid_screenings_and_are_independent(self):
        url = f'/movies/{self.movie.id}/reviews'
        edit_url = f'/booking/{self.booking.reference}/movie-review'
        guest = self.app.test_client()
        other = self.client_for(self.second)
        message = 'Movie reviews become available after you complete your booked screening.'
        for client in (guest, other):
            response = client.get(url)
            self.assertEqual(response.status_code, 403)
            self.assertIn(message, response.text)
        self.assertEqual(self.post(guest, edit_url, rating=4, review='Guest').status_code, 302)
        self.assertEqual(self.post(other, edit_url, rating=4, review='Wrong owner').status_code, 404)
        for show, status, proof in ((self.in_progress, 'PAID', 'CAPTURED'), (self.future, 'PAID', 'CAPTURED'),
                                    (self.ended, 'PAID', 'REFUNDED'), (self.ended, 'CANCELLED', 'CAPTURED'),
                                    (self.ended, 'PENDING', 'CAPTURED')):
            booking = self.book(self.second, show, status, payment_status=proof)
            db.session.commit()
            self.assertEqual(other.get(url).status_code, 403)
            path = f'/booking/{booking.reference}/movie-review'
            self.assertEqual(self.post(other, path, rating=5, review='Too early').status_code, 403)
        self.assertEqual(self.client.get(f'/movies/{self.upcoming.id}/reviews').status_code, 403)
        self.assertEqual(self.client.post(edit_url, data={'rating': 4, 'review': 'No token'}).status_code, 400)
        self.assertEqual(self.post(self.client, edit_url, rating=4, review='  ').status_code, 422)
        self.assertEqual(self.post(self.client, edit_url, rating=4, review='Wrong movie',
                                   movie_id=self.upcoming.id).status_code, 404)
        ticket = f'/ticket/{self.booking.reference}'
        for body in (self.client.get(ticket).text, self.client.get('/dashboard').text,
                     self.client.get('/profile').text):
            for action in ('Review This Screen', 'Review This Movie', 'Read Movie Reviews'):
                self.assertIn(action, body)
        legacy = MovieRating(user=self.viewer, movie=self.movie, rating=4.5, review='Legacy unbacked text')
        db.session.add(legacy)
        db.session.commit()
        self.assertNotIn('Legacy unbacked text', self.client.get(url).text)
        self.assertNotIn('Legacy unbacked text', self.client.get(edit_url).text)
        self.assertEqual(self.post(self.client, edit_url, rating=4, title='My review',
                                   review='Hidden plot detail', has_spoiler=1).status_code, 303)
        self.assertEqual(MovieRating.query.one().id, legacy.id)
        self.assertTrue(legacy.verified)
        self.assertEqual(legacy.booking_id, self.booking.id)
        self.assertIn('Edit Movie Review', self.client.get(ticket).text)
        self.assertIn('Review This Screen', self.client.get(ticket).text)
        self.assertEqual(self.submit(overall_rating=2, review_text='Screen experience').status_code, 303)
        self.assertIn('Edit Screen Review', self.client.get(ticket).text)
        self.assertIn('Edit Movie Review', self.client.get(ticket).text)
        self.assertIn('2.0/5', guest.get(self.detail_url()).text)
        self.assertNotIn('Hidden plot detail', self.client.get(url).text)
        self.assertNotIn('My review', self.client.get(url).text)
        self.assertEqual(self.client.get(url).headers['Cache-Control'], 'private, no-store')
        self.assertIn('Hidden plot detail', self.client.get(url + f'?reveal={legacy.id}').text)
        self.assertNotIn('Hidden plot detail', other.get(url + f'?reveal={legacy.id}').text)

    def test_movie_demo_filter_edit_report_moderate_and_withdraw(self):
        url = f'/movies/{self.movie.id}/reviews'
        demo_screen = Screen(theater=self.other_theater, name='Another cinema screen')
        demo_show = self.show(cinema_now() - timedelta(days=2), demo_screen)
        demo = self.book(self.second, demo_show, gateway='wallet')
        other = self.client_for(self.second)
        admin = self.client_for(self.admin)
        db.session.commit()
        demo_url = f'/booking/{demo.reference}/movie-review'
        real_url = f'/booking/{self.booking.reference}/movie-review'
        self.assertEqual(self.post(other, demo_url, intent='create', rating=2, review='Demo opinion').status_code, 303)
        self.assertEqual(self.post(other, demo_url, intent='create', rating=5, review='Duplicate').status_code, 409)
        self.assertEqual(self.post(self.client, real_url, rating=5, review='Real opinion').status_code, 303)
        review = MovieRating.query.filter_by(user_id=self.second.id).one()
        self.assertFalse(review.verified)
        self.assertTrue(review.is_demo)
        self.assertIn('3.5/5', self.client.get(url).text)
        self.assertIn('2 reviews', self.client.get(url).text)
        self.assertIn('value="1" aria-label="5-star reviews"', other.get(url).text)
        for order, first, second in (('oldest', 'Demo', 'Real'), ('recent', 'Real', 'Demo'),
                                     ('highest', 'Real', 'Demo'), ('lowest', 'Demo', 'Real')):
            body = other.get(url + '?sort=' + order).text
            self.assertLess(body.index(first + ' opinion'), body.index(second + ' opinion'))
        filtered = self.client.get(url + '?source=demo&rating=2&spoiler=no').text
        self.assertIn('Demo Booking Review</p>', filtered)
        self.assertNotIn('Verified Booking</p>', filtered)
        self.assertIn('Demo opinion', filtered)
        self.assertNotIn('Demo opinion', self.client.get(url + '?spoiler=yes').text)
        self.assertNotIn('Demo opinion', self.client.get(url + '?source=verified').text)
        self.assertNotIn('Demo opinion', self.client.get(url + '?rating=5').text)
        report = f'/movie-reviews/{review.id}/report'
        moderate = f'/admin/movie-reviews/{review.id}/moderate'
        self.assertEqual(self.post(other, report, reason='Cannot report own review').status_code, 403)
        self.assertEqual(self.post(admin, report, reason='No booking for this film').status_code, 403)
        self.assertEqual(self.client.post(report, data={'reason': 'Missing CSRF'}).status_code, 400)
        for _ in range(2):
            self.assertEqual(self.post(self.client, report, reason='Please check this review.').status_code, 303)
        self.assertEqual(MovieReviewReport.query.count(), 1)
        self.assertEqual(other.get('/admin/movie-reviews').status_code, 403)
        self.assertEqual(self.post(other, moderate, action='hide').status_code, 403)
        self.assertEqual(admin.post(moderate, data={'action': 'hide'}).status_code, 400)
        self.assertIn('Please check this review.', admin.get('/admin/movie-reviews?view=reported').text)
        self.assertEqual(self.post(admin, moderate, action='hide').status_code, 303)
        self.assertEqual(MovieReviewModeration.query.one().action, 'hide')
        self.assertIsNotNone(MovieReviewReport.query.one().resolved_at)
        self.assertIn('5.0/5', self.client.get(url).text)
        self.assertNotIn('Demo opinion', self.client.get(url).text)
        repeat = self.book(self.second, self.ended)
        db.session.commit()
        edit = f'/booking/{repeat.reference}/movie-review'
        self.assertIn('Edit your movie review', other.get(edit).text)
        self.assertEqual(self.post(other, edit, rating=3, review='Updated opinion').status_code, 303)
        self.assertEqual(MovieRating.query.filter_by(user_id=self.second.id).count(), 1)
        self.assertEqual(review.booking_id, demo.id)
        self.assertNotIn('Updated opinion', self.client.get(url).text)
        self.assertEqual(self.post(admin, moderate, action='restore').status_code, 303)
        self.assertIn('Updated opinion', self.client.get(url).text)
        self.assertEqual(self.post(other, edit + '/withdraw').status_code, 303)
        self.assertEqual(self.post(other, edit, rating=3, review='Duplicate').status_code, 409)
        self.assertEqual(self.post(admin, moderate, action='restore').status_code, 409)
        self.assertNotIn('Updated opinion', self.client.get(url).text)
        db.session.add(MovieRating(user=self.second, movie=self.movie, booking=repeat, rating=4, review='Duplicate'))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

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
