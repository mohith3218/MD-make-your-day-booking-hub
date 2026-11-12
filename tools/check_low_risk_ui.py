"""Render checks and optional localhost QA server, using a fresh disposable database.

Run: .venv/Scripts/python tools/check_low_risk_ui.py [--serve]
No existing database, credentials, or reference profiles are modified.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
(ROOT / 'instance').mkdir(exist_ok=True)
QA_DIR = Path(tempfile.mkdtemp(prefix='low-risk-', dir=ROOT / 'instance'))
database_url = 'sqlite:///' + (QA_DIR / 'qa.db').as_posix()
os.environ.update(APP_ENV='testing', DATABASE_URL=database_url,
                  TEST_DATABASE_URL=database_url,
                  ADMIN_PASSWORD='isolated-ui-test-password',
                  SECRET_KEY='isolated-ui-test-session-key', SESSION_COOKIE_SECURE='0')
os.environ['DEMO_PAYMENTS_ENABLED'] = 'true'
for key in ('SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'TMDB_API_KEY'):
    os.environ[key] = ''

import app as A
from flask import redirect, request, session

A.init_db()
with A.app.app_context():
    admin = A.User.query.filter_by(username='admin').one()
    admin_id = admin.id
    empty_user = A.User(username='ui_empty', email='ui-empty@example.invalid', email_verified=True)
    empty_user.set_password('isolated-ui-test-password')
    A.db.session.add(empty_user)
    movie = A.Movie(title='Cinema demonstration', description='Isolated UI fixture',
                    duration=120, language='Telugu', certificate='U/A')
    A.db.session.add(movie)
    A.db.session.flush()
    empty_user_id = empty_user.id
    show_ids = {}
    for key, theater, screen_name in [
        ('inox', 'INOX Varun Beach', 'Screen 5'),
        ('melody', 'Sri Melody', 'Main Screen'),
        ('jagadamba', 'Jagadamba Theatre', '70MM Main'),
        ('recliner', 'AAA Cinemas', 'Screen 1'),
        ('couple', 'Mukta A2 Cinemas', 'Screen 1'),
    ]:
        screen = A.Screen.query.join(A.Theater).filter(
            A.Theater.name == theater, A.Screen.name == screen_name).one()
        show = A.Showtime(movie_id=movie.id, screen_id=screen.id, theater=theater,
                          show_date=date.today() + timedelta(days=2), show_time='6:30 PM')
        A.db.session.add(show)
        A.db.session.flush()
        show_ids[key] = show.id
    # Deliberately two bookings with multiple seats: labels must describe bookings.
    for i, amount in enumerate((400, 800)):
        when = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=i)
        A.db.session.add(A.Booking(user_id=admin_id, showtime_id=show_ids['inox'],
                                  seats='A1,A2', reference=f'UIFIXTURE{i}', status='PAID',
                                  total_amount=amount, booked_at=when, paid_at=when))
    A.db.session.commit()


@A.app.get('/__qa__/')
def qa_entry():
    """Authentication fixture exists only in this separately launched QA app."""
    session['_user_id'] = str(empty_user_id if request.args.get('empty') else admin_id)
    session['_fresh'] = True
    page = request.args.get('page', 'preview')
    if page == 'analytics':
        return redirect('/admin/analytics?days=' + request.args.get('days', '30'))
    if page == 'dashboard':
        return redirect('/dashboard')
    if page == 'admin':
        return redirect('/admin')
    if page == 'home':
        return redirect('/')
    show_id = show_ids.get(request.args.get('theater'), show_ids['inox'])
    return redirect(f'/book/{show_id}' + ('' if page == 'booking' else '/vr-preview'))


def check_rendered_pages():
    client = A.app.test_client()
    with client.session_transaction() as state:
        state['_user_id'] = str(admin_id)
        state['_fresh'] = True
    routes = ['/', '/dashboard', '/admin']
    routes += [f'/admin/analytics?days={days}' for days in (0, 7, 30, 90)]
    routes += [f'/book/{show_ids["inox"]}']
    routes += [f'/book/{show_id}/vr-preview' for show_id in show_ids.values()]
    blocks = 0
    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, (route, response.status_code)
        html = response.get_data(as_text=True)
        if route.startswith('/admin/analytics'):
            assert 'Paid bookings' in html and 'Avg booking' in html
            assert 'Tickets sold' not in html
            assert '₹1200' in html
            expected = int(route.split('=')[1])
            assert html.count('class="revenue-day"') == expected
        for source in re.findall(r'<script\b[^>]*>(.*?)</script>', html, re.S | re.I):
            if source.strip():
                subprocess.run(['node', '--check'], input=source, text=True,
                               encoding='utf-8', capture_output=True, check=True, timeout=20)
                blocks += 1
    with client.session_transaction() as state:
        state['_user_id'] = str(empty_user_id)
    assert 'Your next movie awaits' in client.get('/dashboard').get_data(as_text=True)
    # The same real aggregate renderer must handle zero revenue and empty tables.
    empty = client.get('/__qa__/?page=analytics&empty=1', follow_redirects=True)
    assert empty.status_code == 200  # non-admin is redirected by the existing guard
    with A.app.app_context():
        A.Booking.query.delete()
        A.db.session.commit()
    with client.session_transaction() as state:
        state['_user_id'] = str(admin_id)
    html = client.get('/admin/analytics?days=7').get_data(as_text=True)
    assert 'No paid revenue recorded' in html and 'No paid bookings in this window' in html
    print(f'PASS: {len(routes) + 3} rendered route cases; {blocks} JavaScript blocks; '
          '7/30/90-day and all-time labels; empty dashboard and zero revenue')


if __name__ == '__main__':
    if '--serve' in sys.argv:
        print('Isolated QA data:', QA_DIR, flush=True)
        print('QA shows:', show_ids, flush=True)
        A.app.run(host='127.0.0.1', port=5014, debug=False, use_reloader=False)
    else:
        check_rendered_pages()
