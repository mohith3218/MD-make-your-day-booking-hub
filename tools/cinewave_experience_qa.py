"""Serve the real app with disposable, clearly labelled browser-test data."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sys import argv
from unittest.mock import patch

database = Path(argv[1]).resolve() / 'browser-test.db'
database_url = f'sqlite:///{database.as_posix()}'
os.environ.update(APP_ENV='testing', DATABASE_URL=database_url, TEST_DATABASE_URL=database_url,
                  SESSION_COOKIE_SECURE='0', SECRET_KEY='local-browser-fixture',
                  SMTP_HOST='qa-mail.example.invalid', SMTP_FROM_EMAIL='qa@example.invalid',
                  TMDB_API_KEY='isolated-browser-fixture', TMDB_READ_TOKEN='', DEMO_PAYMENTS_ENABLED='true')

from alembic import command
from alembic.config import Config
from werkzeug.serving import make_server

from flask import abort
from app import app, db
from cinewave.models import Booking, Movie, Payment, Screen, Showtime, Theater, User
from cinewave.services import movie_sync
from cinewave.services.movies import TMDBClient
from cinewave.time import cinema_now

with app.app_context():
    config = Config('alembic.ini')
    with db.engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')
    user = User(username='qa-viewer', email='qa@example.invalid', email_verified=True, is_admin=True)
    user.set_password('ScreenQaPassword!')
    theater = Theater(name='Seaside Cinema', location='Beach Road', address='12 Beach Road, Visakhapatnam')
    screen = Screen(theater=theater, name='Main Hall', screen_type='2D')
    screen.layout = {
        'classes': [{'name': 'Standard', 'code': 'STD', 'price': 150,
                     'rows': [{'label': label, 'count': 10} for label in 'ABCDE']}],
    }
    extra_screen = Screen(theater=theater, name='Studio Hall', screen_type='3D')
    film = Movie(title='A Night by the Coast', description='An evening screening in the CineWave test catalogue.',
                 duration=120, poster='/static/images/cinewave-hero.jpg', backdrop='/static/images/cinewave-hero.jpg')
    demo_film = Movie(title='The Bay at Dawn', description='A demo screening for the review booking journey.',
                      duration=95, poster='/static/images/cinewave-hero.jpg')
    upcoming = Movie(title='The Next Wave', description='An upcoming release in the CineWave test catalogue.',
                     duration=100, is_upcoming=True, poster='/static/images/cinewave-hero.jpg',
                     backdrop='/static/images/cinewave-hero.jpg', featured_order=1)
    now = cinema_now()
    shows = [Showtime(movie=demo_film if offset == 1 else film, screen=screen, theater=theater.name,
                      show_date=(now + timedelta(days=offset)).date(), show_time='18:30')
             for offset in (-2, -1, 1, 2)]
    references = ('QA-REVIEW-ONE', 'QA-REVIEW-TWO')
    db.session.add_all([upcoming, extra_screen, *shows])
    for reference, show in zip(references, shows):
        db.session.add(Booking(reference=reference, user=user, showtime=show, seats='A1',
                               status='PAID', total_amount=160,
                               payment=Payment(gateway='razorpay', status='CAPTURED')))
    db.session.add(Booking(reference='QA-CHECKOUT', user=user, showtime=shows[-1], seats='A1',
                           status='PENDING', ticket_amount=150, total_amount=160,
                           expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)))
    db.session.commit()
    title = 'Imported Film Fixture'
    details = {'id': 120025, 'title': title, 'overview': 'An imported festival film for browser testing.',
               'poster_path': '/browser-fixture.jpg', 'original_language': 'ta'}
    with patch.object(movie_sync, 'discover', return_value={120025: 'recent'}), \
            patch.object(TMDBClient, 'details', return_value=details):
        counts, error = movie_sync.run_sync()
    assert not error and counts['imported'] == 1
    imported = Movie.query.filter_by(tmdb_id=120025).one()
    demo_show_id = shows[-2].id
    server = make_server('127.0.0.1', 0, app)
    print(json.dumps({'port': server.server_port, 'theater': theater.id,
                      'screen': screen.id, 'screenWithoutReviews': extra_screen.id,
                      'movie': upcoming.id, 'show': shows[-1].id, 'references': references,
                      'reviewMovie': demo_film.id, 'demoShow': demo_show_id,
                      'importedMovie': imported.id, 'importedTitle': title}), flush=True)


@app.post('/__qa__/end-demo-screening')
def end_demo_screening():
    """Advance only the cinema clock in this disposable browser test process."""
    global now
    if not Booking.query.filter_by(showtime_id=demo_show_id, status='PAID').count():
        abort(409)
    show = db.session.get(Showtime, demo_show_id)
    now = show.show_datetime + timedelta(minutes=show.movie.duration + 1)
    return '', 204


with patch('cinewave.routes.auth.password_recovery_is_configured', return_value=True), \
        patch('cinewave.routes.auth.send_password_recovery_email', return_value=False), \
        patch('cinewave.services.seat.dispatch_ticket_delivery', return_value=False), \
        patch('cinewave.models.catalog.cinema_now', side_effect=lambda: now), \
        patch('cinewave.services.movie_reviews.cinema_now', side_effect=lambda: now), \
        patch('theatre_discovery.cinema_now', side_effect=lambda: now):
    server.serve_forever()
