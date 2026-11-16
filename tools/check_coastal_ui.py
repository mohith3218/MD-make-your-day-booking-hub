"""Verify the coastal UI against a disposable database; never touch user data.

Run: .venv/Scripts/python tools/check_coastal_ui.py
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
QA = tempfile.TemporaryDirectory(prefix='coastal-ui-', ignore_cleanup_errors=True)
os.environ.update(
    APP_ENV='testing',
    DATABASE_URL='sqlite:///' + (Path(QA.name) / 'qa.db').as_posix(),
    TEST_DATABASE_URL='sqlite:///' + (Path(QA.name) / 'qa.db').as_posix(),
    SECRET_KEY='isolated-coastal-ui-check',
    SESSION_COOKIE_SECURE='0',
    DEMO_PAYMENTS_ENABLED='true',
    SMTP_HOST='', SMTP_USERNAME='', SMTP_PASSWORD='', TMDB_API_KEY='',
)

import app as A
from flask import g

A.app.config.update(TESTING=True)


def scripts_are_valid(html):
    for script in re.findall(r'<script\b[^>]*>(.*?)</script>', html, re.S):
        if script.strip():
            result = subprocess.run(
                ['node', '--check'], input=script, text=True, encoding='utf-8',
                capture_output=True, timeout=20,
            )
            assert result.returncode == 0, result.stderr


def check():
    with A.app.app_context():
        assert Path(A.db.engine.url.database).resolve().is_relative_to(Path(QA.name).resolve())
        A.db.create_all()
        # An empty catalogue must still render a usable page.
        client = A.app.test_client()
        empty = client.get('/')
        assert empty.status_code == 200
        assert 'Showtimes will appear here' in empty.text
        scripts_are_valid(empty.text)

        user = A.User(username='coastal_test', email='coastal@example.invalid',
                      email_verified=True, points=100)
        user.set_password('isolated-fixture-password')
        venue = A.Theater(name='Coastal Fixture Cinema', location='Beach Road')
        screen = A.Screen(theater=venue, name='Audi 1', screen_type='2D')
        screen.layout = {
            'classes': [{'code': 'RECLINER', 'name': 'Recliner', 'price': 295,
                         'rows': [{'label': 'A', 'count': 10, 'aisles_after': [5]}]}],
        }
        film = A.Movie(title='Devara: Part 1', description='Fixture action story',
                       duration=178, language='Telugu', rating=9.2)
        upcoming = A.Movie(title='Future <Film>', description='Fixture romance',
                           duration=120, is_upcoming=True,
                           release_date=date.today() + timedelta(days=10))
        A.db.session.add_all([user, venue, screen, film, upcoming])
        A.db.session.flush()
        tomorrow = date.today() + timedelta(days=1)
        show = A.Showtime(movie=film, screen=screen, theater=venue.name,
                          show_date=tomorrow, show_time='7:45 PM')
        second_day = A.Showtime(movie=film, screen=screen, theater=venue.name,
                                show_date=tomorrow + timedelta(days=1), show_time='6:30 PM')
        past = A.Showtime(movie=film, screen=screen, theater=venue.name,
                          show_date=date.today() - timedelta(days=1), show_time='10:00 AM')
        A.db.session.add_all([show, second_day, past, A.Wallet(user=user, balance=450)])
        A.db.session.commit()
        show_id, user_id = show.id, user.id

        html = client.get('/').text
        assert f'data-date="{tomorrow.isoformat()}"' in html
        assert f'data-date="{second_day.show_date.isoformat()}"' in html
        assert f'data-date="{past.show_date.isoformat()}"' not in html
        assert f'/book/{show.id}' in html
        assert 'Future &lt;Film&gt;' in html
        assert '9.2 <small>/ 10</small>' in html
        scripts_are_valid(html)
        print('PASS: empty catalogue, live dates/show links, categories and escaped titles')

        with client.session_transaction() as session:
            session['_user_id'] = str(user_id)
            session['_fresh'] = True
        g.pop('_login_user', None)

        def reserve(seats):
            response = client.post(f'/book/{show_id}', data={'selected_seats': seats})
            assert response.status_code == 302 and '/checkout/' in response.location, (
                response.status_code, response.location,
            )
            reference = response.location.rsplit('/', 1)[1]
            response = client.get(response.location)
            assert response.status_code == 200
            scripts_are_valid(response.text)
            return reference, response.text

        reference, html = reserve('A1,A2')
        booking = A.Booking.query.filter_by(reference=reference).one()
        initial_total = booking.total_amount
        assert 'Settlement &amp; Verification Desk' in html
        assert f'₹{initial_total:.2f}' in html
        assert 'value="squad"' in html
        assert re.search(r'value="wallet"\s+disabled', html)
        assert html.count('name="snacks"') == len(A.SNACK_ITEMS)
        assert 'form="payment-form"' in html
        print('PASS: real seat reservation, checkout totals, split invite and insufficient-wallet state')

        response = client.post(f'/checkout/{reference}/update_extras',
                               data={'snacks': 'popcorn_lg', 'redeem_points': '50'},
                               follow_redirects=True)
        assert response.status_code == 200
        A.db.session.refresh(booking)
        assert booking.total_amount == round(initial_total + 180 - 50, 2)
        assert 'CinePass Points Redeemed' in response.text
        assert 'Large Butter Popcorn' in response.text
        assert 'is-selected' in response.text
        scripts_are_valid(response.text)
        print('PASS: snacks and CinePass redemption persist and recalculate the displayed bill')

        for method, seats in [('upi', 'A3'), ('card', 'A4'), ('netbanking', 'A5')]:
            ref, single = reserve(seats)
            assert 'value="squad"' not in single
            gateway = client.post(f'/pay/gateway/{ref}', data={'method': method})
            assert gateway.status_code == 200
            assert 'DEMO' in gateway.text
            result = client.post(f'/pay/simulate/{ref}', data={'outcome': 'success'})
            assert result.status_code == 302 and '/ticket/' in result.location
            assert client.get(result.location).status_code == 200
        print('PASS: UPI, card and netbanking demo flows issue tickets')

        wallet = A.Wallet.query.filter_by(user_id=user_id).one()
        wallet.balance = 2000
        A.db.session.commit()
        ref, html = reserve('A6')
        assert not re.search(r'value="wallet"\s+disabled', html)
        response = client.post(f'/pay/wallet/{ref}')
        assert response.status_code == 302 and '/ticket/' in response.location
        print('PASS: funded wallet checkout completes through the existing wallet route')

        row = A.SplitContribution.query.filter_by(booking_id=booking.id).first()
        row.user_id, row.status = user_id, 'PAID'
        A.db.session.commit()
        html = client.get(f'/checkout/{reference}').text
        assert 'Your squad has started paying.' in html
        assert 'id="payment-form"' not in html
        assert 'Extras are locked' in html
        scripts_are_valid(html)
        print('PASS: partial Squad Pay hides full-bill controls and locks extras')

        A.Booking.query.filter_by(reference=reference).update({
            A.Booking.expires_at: datetime.utcnow() - timedelta(seconds=1),
        })
        A.db.session.commit()
        assert client.get(f'/checkout/{reference}').status_code == 302
        print('PASS: expired checkout redirects to seat selection')

        for path in ['/static/css/coastal.css', '/static/images/coastal-spotlight.jpg']:
            assert client.get(path).status_code == 200
        # Compile all templates, including account/admin pages using the shared shell.
        for name in A.app.jinja_env.list_templates():
            A.app.jinja_env.get_template(name)
        print('PASS: local assets and all Jinja templates compile')
        A.db.session.remove()
        A.db.engine.dispose()


if __name__ == '__main__':
    try:
        check()
    finally:
        with A.app.app_context():
            A.db.session.remove()
            A.db.engine.dispose()
        QA.cleanup()
