"""Local-only browser verification of the real app against a fresh SQLite snapshot.

Run with .venv/Scripts/python tools/phase_2_1_3_qa.py. Never runs init_db(),
reseeds layouts, changes existing credentials, or opens a production database for writes.
QA endpoints and injected browser helpers exist only in this separate process.
"""
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
QA_DIR = Path(tempfile.mkdtemp(prefix="phase213-", dir=ROOT / 'instance'))
snapshot = QA_DIR / "snapshot.db"
with sqlite3.connect(f"file:{ROOT / 'instance/vizag_movies.db'}?mode=ro", uri=True) as source:
    with sqlite3.connect(snapshot) as target:
        source.backup(target)
os.environ["DATABASE_URL"] = "sqlite:///" + snapshot.as_posix()
os.environ["APP_ENV"] = "testing"
os.environ["SECRET_KEY"] = secrets.token_hex(32)
os.environ["SESSION_COOKIE_SECURE"] = "0"
import app as A
from flask import request, session, Response

OUT = ROOT / "docs/screenshots/phase-2.1.3-seat-materials"
OUT.mkdir(parents=True, exist_ok=True)
with A.app.app_context():
    user = A.User(username="phase213_" + secrets.token_hex(4),
                  email="phase213@example.invalid", email_verified=True)
    user.set_password(secrets.token_urlsafe(24))
    A.db.session.add(user)
    A.db.session.flush()
    qa_user_id = user.id
    # New showtimes in the snapshot keep ended source shows and their bookings intact.
    show_ids = {}
    for key, theater_name, screen_name in [
        ("melody", "Sri Melody", "Main Screen"),
        ("inox", "INOX Varun Beach", "Screen 5"),
        ("jagadamba", "Jagadamba Theatre", "70MM Main"),
        ("recliner", "AAA Cinemas", "Screen 1"),
    ]:
        screen = A.Screen.query.join(A.Theater).filter(
            A.Theater.name == theater_name, A.Screen.name == screen_name).one()
        show = A.Showtime(movie_id=A.Movie.query.first().id, screen_id=screen.id,
                          theater=theater_name, show_date=date.today() + timedelta(days=2),
                          show_time="6:30 PM")
        A.db.session.add(show)
        A.db.session.flush()
        show_ids[key] = show.id
    A.db.session.commit()
    # Explicit unavailable-seat fixtures on the new QA show only.
    expiry = datetime.utcnow() + timedelta(hours=2)
    lock = A.SeatLock(showtime_id=show_ids['inox'], user_id=qa_user_id,
                      seats='E2', expires_at=expiry)
    A.db.session.add(lock)
    A.db.session.flush()
    A.db.session.add(A.SeatHold(showtime_id=show_ids['inox'], seat_id='E2',
                               token=lock.token, expires_at=expiry))
    A.db.session.add(A.BookedSeat(showtime_id=show_ids['inox'], seat_id='E1'))
    A.db.session.commit()


@A.app.get('/__qa__/')
def qa_shell():
    session['_user_id'] = str(qa_user_id)
    session['_fresh'] = True
    key = request.args.get('theater', 'melody')
    show_id = show_ids[key]
    booking = request.args.get('booking') == '1'
    src = f'/book/{show_id}' + ('' if booking else '/vr-preview')
    return Response('''<!doctype html><html><head><title>Phase 2.1.3 — actual Flask renderer QA</title>
<style>body{margin:0;background:#111;color:#eee;font:13px Arial}nav{height:44px;display:flex;align-items:center;gap:12px;padding:0 12px}a,button{color:#eee;background:#263143;border:0;padding:7px;cursor:pointer}iframe{width:100%;height:calc(100vh - 44px);border:0}</style></head><body><nav>
<a href="?theater=melody">Melody</a><a href="?theater=inox">INOX 5</a><a href="?theater=jagadamba">Jagadamba</a><a href="?theater=recliner">Recliner</a><a href="?theater=inox&booking=1">2D–3D tests</a>
<button onclick="v.contentWindow.__qa.light('movie')">Showtime</button><button onclick="v.contentWindow.__qa.light('preshow')">Preshow</button><button onclick="v.contentWindow.__qa.light('house')">House lights</button>
<button onclick="v.contentWindow.__qa.closeup(false)">Standard close</button><button onclick="v.contentWindow.__qa.closeup(true)">Premium / Recliner close</button>
<button onclick="v.contentWindow.__qa.overview()">Overview</button><span id="status">Warming renderer…</span></nav>
<iframe id="v" src="''' + src + '''"></iframe></body></html>''', mimetype='text/html')


@A.app.get('/__qa__/checks.js')
def qa_script():
    return Response((ROOT / 'tools/phase_2_1_3_browser_checks.js').read_text(encoding='utf-8'),
                    mimetype='application/javascript')


@A.app.post('/__qa__/results')
def qa_results():
    data = request.get_json()
    name = ''.join(c for c in data['name'] if c.isalnum() or c in '-_')
    # Browser result payloads are diagnostic data, never executable code.
    (QA_DIR / (name + '.json')).write_text(json.dumps(data, indent=2), encoding='utf-8')
    return {'saved': name}


@A.app.after_request
def inject_qa(response):
    if request.path.startswith('/book/') and response.mimetype == 'text/html' and response.status_code == 200:
        response.set_data(response.get_data(as_text=True).replace(
            '</body>', '<script src="/__qa__/checks.js"></script></body>'))
    return response


if __name__ == '__main__':
    print('QA snapshot:', snapshot, flush=True)
    print('QA shows:', show_ids, flush=True)
    A.app.run(host='127.0.0.1', port=int(os.environ.get('PHASE213_PORT', '5014')), debug=False, use_reloader=False)
