import os
os.environ.setdefault('ADMIN_PASSWORD', 'admin123')
import app as A

with A.app.app_context():
    A.db.drop_all()
A.app.config['WTF_CSRF_ENABLED'] = False
A.init_db()

with A.app.app_context():
    m = A.Movie(title='Pushpa 3 - The Rampage', description='Test movie', duration=165, language='Telugu', certificate='U/A')
    A.db.session.add(m)
    screen = (A.Screen.query.join(A.Theater).filter(A.Theater.name == 'INOX Varun Beach', A.Screen.name == 'Screen 1').first())
    A.db.session.flush()
    st = A.Showtime(movie_id=m.id, screen_id=screen.id, theater=screen.theater.name, show_date=A.date.today() + A.timedelta(days=1), show_time='6:30 PM', price_overrides_json=A.json.dumps({'RECLINER': 400}))
    A.db.session.add(st)
    A.db.session.commit()
    show_id = st.id
    print('SHOW_ID', show_id)
    print('SCREEN', screen.full_name, 'SEATS', screen.total_seats)
