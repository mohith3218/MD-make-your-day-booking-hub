from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy.exc import IntegrityError

from cinewave.extensions import db
from cinewave.factory import create_app
from cinewave.integrations.tmdb import TMDBClient, TMDBError, best_trailer
from cinewave.models import Booking, Movie, MovieRating, Payment, Screen, ScreenReview, SeatHold, Showtime, Theater, User
from cinewave.services.reviews import completed_booking_source
from cinewave.services.theatre_reviews import venue_review_data
from cinewave.time import cinema_now
from cinewave.workers import movie_sync


def clip(key, *, language='en', official=True, kind='Trailer'):
    return {'key': key, 'site': 'YouTube', 'iso_639_1': language, 'official': official, 'type': kind}


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True, 'SESSION_PROTECTION': None, 'SECRET_KEY': 'isolated-experience-tests',
            'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'SQLALCHEMY_ENGINE_OPTIONS': {},
            'TMDB_API_KEY': 'fixture-key', 'TMDB_READ_TOKEN': '',
        })
        context = self.app.app_context()
        context.push()
        self.addCleanup(context.pop)
        db.create_all()
        self.user = User(username='viewer', password_hash='test')
        self.other = User(username='other', password_hash='test')
        self.staff = User(username='staff', is_admin=True, password_hash='test')
        self.movie = Movie(title='Evening Show', description='Fixture film', duration=100, tmdb_id=77)
        self.venue = Theater(name='Coastal theatre')
        self.screen = Screen(name='Screen One', theater=self.venue)
        self.screen.layout = {'classes': [{'code': 'STD', 'name': 'Standard', 'price': 100,
                                            'rows': [{'label': 'A', 'count': 3}]}]}
        db.session.add_all([self.user, self.other, self.staff, self.movie, self.screen])
        db.session.commit()
        self.client = self.login(self.user)
        self.admin = self.login(self.staff)

    def login(self, user):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = user.alternative_id
            session['_fresh'] = True
            session['_csrf_token'] = 'experience-token'
        return client

    def screening(self, offset, **values):
        show = Showtime(movie=self.movie, screen=self.screen, theater=self.venue.name,
                        show_date=cinema_now().date() + timedelta(days=offset), show_time='16:00', **values)
        db.session.add(show)
        db.session.commit()
        return show

    def paid(self, show, user=None, status='PAID'):
        booking = Booking(user=user or self.user, showtime=show, seats='A1', total_amount=150,
                          status=status, paid_at=datetime.now(timezone.utc).replace(tzinfo=None))
        db.session.add(booking)
        db.session.flush()
        db.session.add(Payment(booking_id=booking.id, gateway='historical-provider', status='CAPTURED'))
        db.session.commit()
        return booking

    def test_trailer_priority_and_resilient_movie_details(self):
        matching = clip('Matching_01', language='te')
        english = clip('English__01')
        fallback = clip('Fallback_01', language='te', official=False)
        teaser = clip('Teaser___01', language='te', kind='Teaser')
        self.assertEqual(best_trailer([teaser, fallback, english, matching], 'te'), matching['key'])
        self.assertEqual(best_trailer([teaser, fallback, english], 'te'), english['key'])
        self.assertEqual(best_trailer([teaser, fallback], 'te'), fallback['key'])
        self.assertEqual(best_trailer([teaser], 'te'), teaser['key'])
        self.assertIsNone(best_trailer([clip('invalid!'), clip('Teaser___01', official=False, kind='Teaser')], 'te'))
        details = {'id': 77, 'title': 'Evening Show', 'overview': 'A meaningful overview.',
                   'poster_path': '/poster.jpg', 'original_language': 'te'}
        with TMDBClient() as client, patch.object(client, 'get', side_effect=[
                details, TMDBError('Temporarily unavailable', status=503)]) as get:
            response = client.details(77)
        self.assertEqual(get.call_args.args, ('/movie/77/videos',))
        self.assertEqual(get.call_args.kwargs, {'attempts': 1, 'language': 'te'})
        self.assertEqual(response['title'], 'Evening Show')
        self.assertIn('trailer_lookup_error', response)

    def test_manual_search_errors_id_and_pagination(self):
        url = '/admin/import_movie'
        item = {'id': 77, 'title': self.movie.title, 'original_language': 'te', 'poster_path': '/valid.jpg'}
        with patch.object(TMDBClient, 'search', return_value={'results': [item], 'total_pages': 3}) as search:
            response = self.admin.get(url, query_string={'query': 'తెలుగు', 'page': 2})
        search.assert_called_once_with('తెలుగు', page=2)
        self.assertIn('Page 2 of 3', response.get_data(as_text=True))
        self.assertIn('Already imported', response.get_data(as_text=True))
        with patch.object(TMDBClient, 'get', return_value=item) as get:
            self.assertIn('Telugu', self.admin.get(url, query_string={'query': '77'}).get_data(as_text=True))
        get.assert_called_once_with('/movie/77', append_to_response='release_dates')
        with patch.object(TMDBClient, 'search', side_effect=TMDBError('TMDB is unavailable.', status=503)):
            response = self.admin.get(url, query_string={'query': 'film'}).get_data(as_text=True)
        self.assertIn('TMDb search could not finish', response)
        self.assertNotIn('No results found', response)

    def test_manual_import_accepts_missing_metadata_and_rejects_duplicates(self):
        endpoint = '/admin/import_movie/add/88'
        detail = {'id': 88, 'title': 'Regional film', 'original_language': 'ml'}
        token = {'csrf_token': 'experience-token', 'query': '88'}
        self.assertEqual(self.client.post(endpoint, data=token).status_code, 302)
        self.assertEqual(self.admin.post(endpoint).status_code, 400)
        with patch.object(TMDBClient, 'details', return_value=detail) as details:
            response = self.admin.post(endpoint, data=token)
            self.assertEqual(response.status_code, 422)
            self.assertIn('Authorised HTTPS poster URL', response.get_data(as_text=True))
            self.assertEqual(self.admin.post(endpoint, data={**token, 'description': 'A family takes a trip.',
                                                            'poster_url': 'javascript:alert(1)'}).status_code, 422)
            response = self.admin.post(endpoint, data={**token, 'description': 'A family takes a trip.',
                                                      'poster_url': 'https://images.example.test/poster.jpg'})
            self.assertEqual(response.status_code, 303)
            self.assertEqual(self.admin.post(endpoint, data=token).headers['Location'], response.headers['Location'])
            self.assertEqual(details.call_count, 3)
        stored = Movie.query.filter_by(tmdb_id=88).one()
        self.assertEqual(set(stored.tmdb_overrides), {'description', 'poster'})
        self.assertEqual(stored.language, 'Malayalam')
        self.assertIn('No screenings scheduled yet.', self.client.get(response.headers['Location']).get_data(as_text=True))

    def test_movie_details_find_translated_synopsis_and_poster(self):
        with TMDBClient() as client, patch.object(client, 'get', side_effect=[
            {'id': 900, 'title': 'Film', 'original_language': 'ta'},
            TMDBError('Original language details temporarily unavailable', status=503),
            {'translations': [{'iso_639_1': 'ta', 'data': {'overview': 'A translated description.'}}]},
            {'posters': [{'file_path': '/real-poster.jpg'}]},
            TMDBError('Videos temporarily unavailable', status=503),
        ]):
            result = client.details(900)
        self.assertEqual(result['overview'], 'A translated description.')
        self.assertEqual(result['images']['posters'][0]['file_path'], '/real-poster.jpg')
        self.assertIn('trailer_lookup_error', result)

    def test_backfill_and_manual_trailer_precedence(self):
        url = f'/admin/movie/{self.movie.id}/trailer'
        manual = 'https://res.cloudinary.com/demo/video/upload/q_auto/dog.mp4'
        form = {'csrf_token': 'experience-token', 'trailer_source': 'cloudinary', 'cloudinary_trailer': manual}
        self.assertEqual(self.admin.post(url, data={**form, 'cloudinary_trailer': manual.replace(
            'res.cloudinary.com', 'res.cloudinary.com.example.test')}).status_code, 303)
        self.assertIsNone(self.movie.trailer)
        self.assertEqual(self.admin.post(url, data=form).status_code, 303)
        self.movie.tmdb_last_checked_at = movie_sync.utc_now()
        db.session.commit()
        details = {'id': 77, 'title': self.movie.title, 'overview': self.movie.description,
                   'poster_path': '/poster.jpg', 'videos': {'results': [clip('Matching_01')]}}
        with patch.object(movie_sync, 'discover', return_value={}), patch.object(
                TMDBClient, 'details', return_value=details) as fetch:
            _, error = movie_sync.run_sync()
        self.assertIsNone(error)
        fetch.assert_called_once_with(77)
        self.assertEqual(self.movie.trailer['url'], manual)
        self.assertEqual(self.movie.automatic_youtube_key, 'Matching_01')
        self.admin.post(url, data={**form, 'trailer_action': 'none'})
        self.assertIsNone(self.movie.trailer)
        self.admin.post(url, data={**form, 'trailer_action': 'auto'})
        self.assertEqual(self.movie.trailer['url'], 'https://www.youtube-nocookie.com/embed/Matching_01')

    def test_auditorium_receives_only_the_selected_validated_trailer(self):
        show = self.screening(1)
        path = f'/book/{show.id}/vr-preview?embed=1'
        edit_path = f'/admin/movie/{self.movie.id}/trailer'
        source = 'https://res.cloudinary.com/demo/video/upload/v42/trailers/film.mp4'
        self.admin.post(edit_path, data={'csrf_token': 'experience-token',
                                        'trailer_source': 'cloudinary', 'cloudinary_trailer': source})
        preview = self.client.get(path).get_data(as_text=True)
        self.assertEqual(preview.count('<option value="now-playing"'), 1)
        self.assertIn('>Now Playing</option>', preview)
        self.assertNotIn('Sci-Fi screen demo', preview)
        self.assertNotIn('Sightline calibration grid', preview)
        self.assertIn(f'data-src="{source}"', preview)
        self.assertIn('/upload/c_limit,h_480,w_960/q_auto/v42/trailers/film.mp4', preview)
        self.assertNotIn('TearsOfSteel', preview)
        self.assertNotIn('id="trailer-modal"', preview)

        self.movie.cloudinary_trailer_url = 'https://example.invalid/film.mp4'
        db.session.commit()
        preview = self.client.get(path).get_data(as_text=True)
        self.assertNotIn('example.invalid/film.mp4', preview)
        self.assertNotIn('id="projection-video"', preview)

        self.admin.post(edit_path, data={'csrf_token': 'experience-token',
                                        'trailer_source': 'youtube', 'youtube_trailer': 'Matching_01'})
        preview = self.client.get(path).get_data(as_text=True)
        self.assertIn('https://www.youtube-nocookie.com/embed/Matching_01', preview)
        self.assertIn('id="trailer-modal"', preview)
        self.assertNotIn('id="projection-video"', preview)

    def test_uploaded_trailer_is_bound_to_the_movie_and_served_with_byte_ranges(self):
        with TemporaryDirectory() as folder:
            self.app.config['TRAILER_UPLOAD_DIR'] = folder
            show = self.screening(2)
            other_film = Movie(title='Second film', description='Fixture', duration=100)
            other_venue = Theater(name='Second theatre')
            other_screen = Screen(name='Screen Two', theater=other_venue, layout_json=self.screen.layout_json)
            other_show = Showtime(movie=other_film, screen=other_screen, theater=other_venue.name,
                                  show_date=show.show_date, show_time=show.show_time)
            db.session.add(other_show)
            db.session.commit()
            url = f'/admin/movie/{self.movie.id}/trailer'
            payload = b'\x00\x00\x00\x18ftypisom' + b'container test bytes'
            def upload(content):
                return BytesIO(content), 'movie.mp4'

            token = {'csrf_token': 'experience-token'}
            self.assertEqual(self.admin.post(url, data={'trailer_video': upload(payload)}).status_code, 400)
            self.assertEqual(self.client.post(url, data={**token, 'trailer_video': upload(payload)}).status_code, 302)
            self.admin.post(url, data={**token, 'trailer_video': upload(b'<html>invalid</html>')})
            self.assertIsNone(self.movie.trailer_video_path)
            self.assertEqual(list(Path(folder).iterdir()), [])
            self.assertEqual(self.admin.post(url, data={**token, 'trailer_video': upload(payload)}).status_code, 303)
            path = self.movie.trailer_video_path
            file = Path(folder, Path(path).name)
            self.assertEqual(file.read_bytes(), payload)
            self.assertEqual(self.movie.trailer_source, 'upload')
            file_url = self.movie.trailer['url']
            with self.client.get(file_url, headers={'Range': 'bytes=0-11'}) as response:
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response.mimetype, 'video/mp4')
                self.assertEqual(response.data, payload[:12])
            self.assertEqual(self.app.test_client().get(file_url).status_code, 302)
            self.assertEqual(self.client.get(file_url.replace(f'/movies/{self.movie.id}/',
                                                             f'/movies/{other_film.id}/')).status_code, 404)
            self.assertEqual(self.client.get('/static/' + path).status_code, 404)
            first = self.client.get(f'/book/{show.id}/vr-preview').get_data(as_text=True)
            second = self.client.get(f'/book/{other_show.id}/vr-preview').get_data(as_text=True)
            self.assertIn(file_url, first)
            self.assertIn('Second film', second)
            self.assertIn('No trailer is available for this movie.', second)
            self.assertNotIn(file_url, second)
            self.admin.post(url, data={**token, 'trailer_action': 'none'})
            self.assertIsNone(self.movie.trailer)
            self.assertEqual(self.client.get(file_url).status_code, 404)
            self.assertEqual(file.read_bytes(), payload)
            self.admin.post(url, data={**token, 'trailer_source': 'upload'})
            self.assertEqual(self.movie.trailer['url'], file_url)

    def test_add_movie_and_tmdb_import_persist_their_own_uploaded_trailers(self):
        with TemporaryDirectory() as folder:
            self.app.config['TRAILER_UPLOAD_DIR'] = folder
            first = b'\x00\x00\x00\x18ftypisom' + b'manual file'
            second = b'\x1a\x45\xdf\xa3\x42\x82\x84webm' + b'import file'
            response = self.admin.post('/admin/add_movie', data={
                'csrf_token': 'experience-token', 'title': 'Manual upload',
                'description': 'Manual movie fixture', 'duration': '95',
                'trailer_video': (BytesIO(first), 'manual.mp4'),
            })
            self.assertEqual(response.status_code, 302)
            detail = {'id': 88, 'title': 'Imported upload', 'overview': 'An imported movie fixture.',
                      'poster_path': '/fixture.jpg', 'original_language': 'en'}
            with patch.object(TMDBClient, 'details', return_value=detail):
                response = self.admin.post('/admin/import_movie/add/88', data={
                    'csrf_token': 'experience-token', 'trailer_video': (BytesIO(second), 'import.webm'),
                })
            self.assertEqual(response.status_code, 303)
            manual = Movie.query.filter_by(title='Manual upload').one()
            imported = Movie.query.filter_by(tmdb_id=88).one()
            self.assertNotEqual(manual.trailer_video_path, imported.trailer_video_path)
            self.assertEqual(Path(folder, Path(manual.trailer_video_path).name).read_bytes(), first)
            self.assertEqual(Path(folder, Path(imported.trailer_video_path).name).read_bytes(), second)
            self.assertEqual(imported.trailer_source, 'upload')
            with self.client.get(imported.trailer['url']) as response:
                self.assertEqual(response.mimetype, 'video/webm')
                self.assertEqual(response.data, second)

    def test_review_prompt_booking_eligibility_and_venue_edit(self):
        completed = self.paid(self.screening(-2))
        upcoming = self.paid(self.screening(1))
        cancelled = self.paid(self.screening(-2, is_cancelled=True))
        other = self.paid(self.screening(-3), self.other)
        refunded = self.paid(self.screening(-2), status='CANCELLED')
        for booking, code in ((upcoming, 403), (cancelled, 403), (other, 404), (refunded, 403)):
            response = self.client.get(f'/booking/{booking.reference}/experience-review')
            self.assertEqual(response.status_code, code)
        prompt = self.client.get('/reviews/pending')
        self.assertIn(b'name="rating"', prompt.data)
        self.assertIn(b'name="theatre_rating"', prompt.data)
        self.assertIn('private', prompt.headers['Cache-Control'])
        path = f'/booking/{completed.reference}/experience-review'
        self.assertEqual(self.client.post(path, data={'rating': 4}).status_code, 400)
        self.assertEqual(self.client.post(path, data={'rating': 4, 'csrf_token': 'experience-token'}).status_code, 303)
        movie_review = MovieRating.query.one()
        self.assertIsNone(movie_review.review)
        self.assertEqual(movie_review.booking_id, completed.id)
        prompt = self.client.get('/reviews/pending').data
        self.assertNotIn(b'name="rating"', prompt)
        self.assertIn(b'name="theatre_rating"', prompt)

        second = self.paid(self.screening(-1))
        venue_path = f'/booking/{second.reference}/theatre-review'
        self.assertEqual(self.client.post(venue_path, data={
            'theatre_rating': '5', 'theatre_review': '<b>Great venue</b>', 'csrf_token': 'experience-token',
        }).status_code, 303)
        review = ScreenReview.query.one()
        self.assertFalse(review.has_screen_feedback)
        self.assertEqual(review.booking_id, second.id)
        self.assertEqual(self.client.get('/reviews/pending').status_code, 204)
        listing = self.app.test_client().get(f'/theatres/{self.venue.id}').data
        self.assertIn(b'&lt;b&gt;Great venue&lt;/b&gt;', listing)
        self.assertNotIn(b'<b>Great venue</b>', listing)
        self.assertIn(b'Verified Booking', listing)
        self.assertNotIn(b'Great venue', self.app.test_client().get(
            f'/theatres/{self.venue.id}/screens/{self.screen.id}/reviews').data)
        self.assertIn(b'Edit Theatre Review', self.client.get('/dashboard').data)

        self.client.post(f'/booking/{completed.reference}/theatre-review', data={
            'theatre_rating': '3', 'theatre_review': 'Changed', 'csrf_token': 'experience-token',
        })
        venue = venue_review_data(self.venue.id, 'highest', 1)
        self.assertEqual((venue['score'].count, venue['score'].overall_rating), (1, 3))
        self.assertEqual(venue['distribution'][3], 1)
        db.session.add(ScreenReview(booking=completed, user_id=self.user.id, screen_id=self.screen.id,
                                    theater_id=self.venue.id, overall_rating=3, theatre_rating=3))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        self.client.post(venue_path, data={'action': 'withdraw', 'csrf_token': 'experience-token'})
        self.assertIsNone(venue_review_data(self.venue.id, 'recent', 1)['score'])

    def test_actual_end_is_required_when_runtime_missing(self):
        self.movie.duration = 0
        show = self.screening(-1)
        booking = self.paid(show)
        self.assertIsNone(completed_booking_source(booking, self.user.id))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        show.actual_ended_at = now + timedelta(hours=1)
        self.assertIsNone(completed_booking_source(booking, self.user.id))
        show.actual_ended_at = now - timedelta(hours=1)
        self.assertEqual(completed_booking_source(booking, self.user.id), 'verified')

    def test_edit_seats_reuses_hold_preserves_reference_and_blocks_other_user(self):
        show = self.screening(2)
        response = self.client.post(f'/book/{show.id}', data={'selected_seats': 'A1'})
        self.assertIn('/checkout/', response.headers['Location'])
        booking = Booking.query.one()
        expires_at = booking.expires_at
        url = f'/book/{show.id}?reservation={booking.reference}'
        self.assertEqual(self.login(self.other).get(url).status_code, 404)
        self.assertEqual(self.client.post(url, data={'selected_seats': 'A2'}).status_code, 400)
        self.assertIn(b'"reservedSeats": ["A1"]', self.client.get(url).data)
        response = self.client.post(url, data={'selected_seats': 'A2', 'csrf_token': 'experience-token'})
        self.assertTrue(response.headers['Location'].endswith(booking.reference))
        self.assertEqual(booking.expires_at, expires_at)
        self.assertEqual(Booking.query.one().seat_list, ['A2'])
        self.assertEqual(SeatHold.query.one().seat_id, 'A2')
