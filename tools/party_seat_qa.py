"""Local browser QA on a read-only snapshot of the configured development data.

Only this disposable process exposes /__qa__/ helpers. Never import from app.py.
Run: .venv/Scripts/python tools/party_seat_qa.py
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
QA_DIR = Path(tempfile.mkdtemp(prefix='party-browser-', dir=ROOT / 'instance'))
sources = [*ROOT.glob('*.db'), *ROOT.joinpath('instance').glob('*.db')]
hashes = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
(QA_DIR / 'database-hashes-before.json').write_text(json.dumps(hashes, indent=2))
snapshot = QA_DIR / 'snapshot.db'
with sqlite3.connect((ROOT / 'instance/vizag_movies.db').resolve().as_uri() + '?mode=ro', uri=True) as source:
    with sqlite3.connect(snapshot) as target:
        source.backup(target)
os.environ.update(APP_ENV='testing', DATABASE_URL='sqlite:///' + snapshot.as_posix(),
                  TEST_DATABASE_URL='sqlite:///' + snapshot.as_posix(), SECRET_KEY=secrets.token_hex(32),
                  SMTP_HOST='', SMTP_USERNAME='', SMTP_PASSWORD='', TMDB_API_KEY='', SESSION_COOKIE_SECURE='0')
import app as A
from flask import redirect, session, url_for, request
from flask_login import login_user
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

with A.app.app_context():
    cfg = Config(str(ROOT / 'alembic.ini'))
    with A.db.engine.begin() as conn:
        cfg.attributes['connection'] = conn
        if 'alembic_version' not in inspect(conn).get_table_names():
            command.stamp(cfg, '20261110_01')
        command.upgrade(cfg, 'head')
    users = {}
    for name in ('host', 'friend'):
        user = A.User(username='QA ' + name + ' ' + secrets.token_hex(3), password_hash='not-a-login-password')
        A.db.session.add(user)
        A.db.session.flush()
        users[name] = user.id
    shows = {}
    for key, venue, screen_name in [('jagadamba', 'Jagadamba Theatre', '70MM Main'),
                                     ('inox', 'INOX Varun Beach', 'Screen 5'),
                                     ('melody', 'Sri Melody', 'Main Screen')]:
        screen = A.Screen.query.join(A.Theater).filter(A.Theater.name == venue, A.Screen.name == screen_name).one()
        show = A.Showtime(movie_id=A.Movie.query.first().id, screen=screen, theater=venue,
                          show_date=date.today() + timedelta(days=2), show_time='6:30 PM')
        A.db.session.add(show)
        A.db.session.flush()
        shows[key] = show.id
    A.db.session.commit()


@A.app.get('/__qa__/start/<name>')
def start(name):
    login_user(A.db.session.get(A.User, users[name]))
    return redirect(url_for('book', showtime_id=shows.get(request.args.get('theater'), shows['jagadamba'])))


@A.app.after_request
def diagnostics(response):
    if response.mimetype != 'text/html' or response.status_code != 200:
        return response
    html = response.get_data(as_text=True)
    error_capture = '''<script>window.qaErrors=[];window.addEventListener('error',e=>qaErrors.push(e.message));
      window.addEventListener('unhandledrejection',e=>qaErrors.push(String(e.reason)));</script>'''
    html = html.replace('<head>', '<head>' + error_capture, 1)
    if request.endpoint == 'vr_seat_preview':
        # Expose read-only observations as DOM text for browser tools. No state changes.
        html = html.replace('</body>', '''<pre id="qa-observations" hidden></pre><script>
          setInterval(()=>{try{document.getElementById('qa-observations').textContent=JSON.stringify({
            errors:qaErrors, metrics:cinewavePreviewMetrics(), selected:[...selectedSeats],
            levels:currentAudi.geometry.levels, rowLevels:currentAudi.geometry.rows.map(r=>r.levelId),
            seatCount:seatRegistry.size, paused:previewPausedByParent, animationFrameId,
            cameraMode, camera:[camera.position.x,camera.position.y,camera.position.z],
            canvases:document.querySelectorAll('#canvas-container canvas').length,
            rendererId:renderer.domElement.dataset.qaRendererId ||= String(performance.timeOrigin)
          });}catch(e){document.getElementById('qa-observations').textContent=JSON.stringify({diagnosticError:String(e),errors:qaErrors});}},400);
          </script></body>''')
    response.set_data(html)
    return response


if __name__ == '__main__':
    print('Disposable QA database:', snapshot, flush=True)
    print('Host: http://127.0.0.1:5017/__qa__/start/host', flush=True)
    print('Friend: http://localhost:5017/__qa__/start/friend', flush=True)
    A.app.run(host='127.0.0.1', port=5017, debug=False, use_reloader=False)
