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
                  TMDB_API_KEY='')

from alembic import command
from alembic.config import Config
from werkzeug.serving import make_server

from app import app, db
from cinewave.models import Booking, Movie, Screen, Showtime, Theater, User
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
                 duration=120, backdrop='/static/images/cinewave-hero.jpg')
    upcoming = Movie(title='The Next Wave', description='An upcoming release in the CineWave test catalogue.',
                     duration=100, is_upcoming=True, poster='/static/images/cinewave-hero.jpg',
                     backdrop='/static/images/cinewave-hero.jpg', featured_order=1)
    now = cinema_now()
    shows = [Showtime(movie=film, screen=screen, theater=theater.name,
                      show_date=(now + timedelta(days=offset)).date(), show_time='18:30')
             for offset in (-2, -1, 2)]
    references = ('QA-REVIEW-ONE', 'QA-REVIEW-TWO')
    db.session.add_all([upcoming, extra_screen, *shows])
    for reference, show in zip(references, shows):
        db.session.add(Booking(reference=reference, user=user, showtime=show, seats='A1',
                               status='PAID', total_amount=160))
    db.session.add(Booking(reference='QA-CHECKOUT', user=user, showtime=shows[-1], seats='A1',
                           status='PENDING', ticket_amount=150, total_amount=160,
                           expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)))
    db.session.commit()
    server = make_server('127.0.0.1', 0, app)
    print(json.dumps({'port': server.server_port, 'theater': theater.id,
                      'screen': screen.id, 'screenWithoutReviews': extra_screen.id,
                      'movie': upcoming.id, 'show': shows[-1].id, 'references': references}), flush=True)

with patch('cinewave.routes.auth.password_recovery_is_configured', return_value=True), \
        patch('cinewave.routes.auth.send_password_recovery_email', return_value=False):
    server.serve_forever()
