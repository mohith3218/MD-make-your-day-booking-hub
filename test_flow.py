"""
End-to-end smoke test for CineWave.
Covers: seed -> movie -> showtime -> seat map -> hold -> wallet pay -> ticket
        -> double-booking block -> gateway pay -> failed payment -> expiry.
Run:  python test_flow.py
"""
import json
import os
import re
import sys
import threading
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

os.environ.pop('RAZORPAY_KEY_ID', None)
# Keep this integration test isolated from the app's local or
# deployment database, even when DATABASE_URL is present in the shell.
_test_instance = Path(__file__).resolve().parent / 'instance'
_test_instance.mkdir(exist_ok=True)
_test_dir = tempfile.TemporaryDirectory(prefix='flow-', dir=_test_instance)
os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(_test_dir.name) / 'flow.db').as_posix()
os.environ['APP_ENV'] = 'testing'

import app as A


def main():
    A.app.config['WTF_CSRF_ENABLED'] = False
    A.init_db()

    with A.app.app_context():
        # movie + showtime on INOX Varun Beach Screen 1 (the recliner audi)
        m = A.Movie(title='Pushpa 3 - The Rampage', description='Test movie',
                    duration=165, language='Telugu', certificate='U/A')
        A.db.session.add(m)
        screen = (A.Screen.query.join(A.Theater)
                  .filter(A.Theater.name == 'INOX Varun Beach',
                          A.Screen.name == 'Screen 1').first())
        A.db.session.flush()
        st = A.Showtime(movie_id=m.id, screen_id=screen.id, theater=screen.theater.name,
                        show_date=date.today() + timedelta(days=1), show_time='6:30 PM',
                        price_overrides_json=json.dumps({'RECLINER': 400}))
        A.db.session.add(st)

        u1 = A.User(username='mohith', email='m@x.com')
        u1.set_password('pass123')
        u2 = A.User(username='rahul', email='r@x.com')
        u2.set_password('pass123')
        A.db.session.add_all([u1, u2])
        A.db.session.commit()
        A.db.session.add_all([A.Wallet(user_id=u1.id, balance=2000),
                              A.Wallet(user_id=u2.id, balance=2000)])
        A.db.session.commit()
        show_id, sid = st.id, screen.id
        print(f"screen '{screen.full_name}' has {screen.total_seats} seats "
              f"in classes: {screen.classes_summary}")

    c1 = A.app.test_client()
    c2 = A.app.test_client()

    def login(c, who):
        r = c.post('/login', data={'username': who, 'password': 'pass123'},
                   follow_redirects=True)
        assert r.status_code == 200, r.status_code

    login(c1, 'mohith')
    login(c2, 'rahul')

    # ---- 1. seat map renders with real rows -------------------------------
    r = c1.get(f'/book/{show_id}')
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'Recliner' in html and 'data-seat="A1"' in html
    assert '₹400' in html, 'per-show price override not applied'
    assert 'function toggleSeatSelection' in html and 'toggleSeatSelection(seatEl)' in html
    assert 'id="vr-preview-frame"' in html and 'class="seat' in html
    vr_preview = c1.get(f'/book/{show_id}/vr-preview')
    assert vr_preview.status_code == 200
    preview_html = vr_preview.get_data(as_text=True)
    assert 'INOX Varun Beach' in preview_html and 'Live screen layout' not in preview_html
    assert 'currentAudi.rowDefs' in preview_html and 'jagadamba' not in preview_html
    assert 'Acoustic Ribbed Side Walls' in preview_html and 'Rear Projection Booth Wall' in preview_html
    assert 'sideWall.position' in preview_html and 'backWall.position' in preview_html
    assert 'const rowPositions = geometry.rows || []' in preview_html
    assert 'const screenSurfaceZ = 0' in preview_html
    assert 'screenMesh.position.set(0, screenY, thetaLength ? screenSurfaceZ - radius : screenSurfaceZ)' in preview_html
    assert 'auditoriumRearWallZ = Math.max(Number(physicalRoom.depth || farthestRowZ + 8), farthestRowZ + 5)' in preview_html
    assert 'auditoriumOverviewFov' in preview_html and 'new THREE.InstancedMesh' in preview_html
    assert 'cameraTargetPos.copy(auditoriumOverviewCamera)' in preview_html
    inline_preview = c1.get(f'/book/{show_id}/vr-preview?embed=1')
    assert inline_preview.status_code == 200
    assert 'preview-embedded' in inline_preview.get_data(as_text=True)
    assert 'id="vr-inline-frame"' in html and 'data-src=' in html
    assert 'postVRPreviewState(true, inlineVrFrame)' in html
    assert 'grid-template-columns: minmax(270px,1fr) auto minmax(180px,1fr)' in preview_html
    assert 'Theater seat map' in preview_html and 'Seat details' in preview_html
    assert 'color: 0x4a2029' in preview_html and 'color: 0x205247' in preview_html
    seats_rendered = len(re.findall(r'data-seat="', html))
    print(f"1. seat map OK - {seats_rendered} selectable seats, override ₹400 applied")

    # ---- 2. hold seats -> pending booking + checkout ----------------------
    r = c1.post(f'/book/{show_id}', data={'selected_seats': 'A1,A2'},
                follow_redirects=False)
    assert r.status_code == 302 and '/checkout/' in r.headers['Location']
    ref1 = r.headers['Location'].rsplit('/', 1)[1]
    with A.app.app_context():
        b = A.Booking.query.filter_by(reference=ref1).one()
        assert b.status == 'PENDING'
        assert b.ticket_amount == 800                    # 2 x 400
        assert b.convenience_fee == 40 and round(b.gst, 2) == 7.2
        assert b.total_amount == 847.2
        assert A.SeatLock.query.count() == 1
    print(f"2. hold OK - {ref1}: tickets 800 + fee 40 + gst 7.20 = 847.20, seats locked")

    # ---- 3. another user cannot take the held seats -----------------------
    html2 = c2.get(f'/book/{show_id}').get_data(as_text=True)
    assert 'seat-held' in html2, 'held seats not shown as unavailable'
    r = c2.post(f'/book/{show_id}', data={'selected_seats': 'A2,A3'},
                follow_redirects=True)
    assert 'just taken' in r.get_data(as_text=True)
    print("3. seat lock OK - second user blocked from A2 with a clear message")

    # ---- 3b. simultaneous requests race for the same seat ----------------
    barrier = threading.Barrier(2)
    def try_concurrent_hold(client):
        barrier.wait(timeout=5)
        return client.post(f'/book/{show_id}', data={'selected_seats': 'D1'},
                           follow_redirects=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        simultaneous = list(pool.map(try_concurrent_hold, (c1, c2)))
    winners = [response for response in simultaneous
               if '/checkout/' in response.headers.get('Location', '')]
    with A.app.app_context():
        d1_holds = A.SeatHold.query.filter_by(showtime_id=show_id, seat_id='D1').all()
        d1_bookings = [b for b in A.Booking.query.filter_by(showtime_id=show_id)
                       if 'D1' in b.seat_list]
        assert len(winners) == 1 and len(d1_holds) == 1 and len(d1_bookings) == 1
        d1_reference = d1_bookings[0].reference
        winner_user_id = d1_bookings[0].user_id
        client_by_user = {A.User.query.filter_by(username=name).one().id: client
                          for name, client in (('mohith', c1), ('rahul', c2))}
        winner_client = client_by_user[winner_user_id]
    winner_client.post(f'/booking/{d1_reference}/cancel')
    print("3b. concurrent reservation OK - exactly one customer holds D1")

    # ---- 4. wallet payment ------------------------------------------------
    r = c1.post(f'/pay/wallet/{ref1}', follow_redirects=False)
    assert f'/ticket/{ref1}' in r.headers['Location'], r.headers['Location']
    with A.app.app_context():
        b = A.Booking.query.filter_by(reference=ref1).one()
        w = A.Wallet.query.filter_by(user_id=b.user_id).one()
        assert b.status == 'PAID' and b.paid_at
        assert round(w.balance, 2) == round(2000 - 847.2, 2)
        assert A.BookedSeat.query.filter_by(showtime_id=show_id).count() == 2
        assert A.SeatLock.query.count() == 0
        assert b.payment.status == 'CAPTURED' and b.payment.method == 'wallet'
    print("4. wallet payment OK - seats committed, wallet debited, lock released")

    # ---- 5. ticket + QR ---------------------------------------------------
    t = c1.get(f'/ticket/{ref1}').get_data(as_text=True)
    assert 'Booking confirmed' in t and ref1 in t and 'A1,A2' in t
    q = c1.get(f'/ticket/{ref1}/qr.png')
    assert q.status_code == 200 and q.data[:4] == b'\x89PNG' and len(q.data) > 300
    print(f"5. e-ticket OK - QR generated ({len(q.data)} bytes)")

    # ---- 6. sold seats are gone for everyone -----------------------------
    r = c2.post(f'/book/{show_id}', data={'selected_seats': 'A1'}, follow_redirects=True)
    assert 'just taken' in r.get_data(as_text=True)
    print("6. double-booking blocked after payment")

    # ---- 7. gateway (mock) payment path ---------------------------------
    r = c2.post(f'/book/{show_id}', data={'selected_seats': 'D5,D6,D7'},
                follow_redirects=False)
    ref2 = r.headers['Location'].rsplit('/', 1)[1]
    r = c2.post(f'/pay/gateway/{ref2}', data={'method': 'upi'})
    body = r.get_data(as_text=True)
    assert 'order_mock_' in body and 'Sandbox gateway' in body
    with A.app.app_context():
        p = A.Booking.query.filter_by(reference=ref2).one().payment
        assert p.status == 'CREATED' and p.order_id.startswith('order_mock_')
        amount_paise = int(round(p.amount * 100))
    assert str(amount_paise) in body, 'amount must be in paise for the gateway'
    r = c2.post(f'/pay/simulate/{ref2}', data={'outcome': 'success'},
                follow_redirects=False)
    assert f'/ticket/{ref2}' in r.headers['Location']
    with A.app.app_context():
        b2 = A.Booking.query.filter_by(reference=ref2).one()
        assert b2.status == 'PAID' and b2.payment.status == 'CAPTURED'
        assert b2.payment.payment_id.startswith('pay_mock_') and b2.payment.signature
    print(f"7. UPI gateway OK - {ref2} paid, signature verified, {amount_paise} paise")

    # ---- 8. failed payment releases the seats ---------------------------
    r = c2.post(f'/book/{show_id}', data={'selected_seats': 'E1,E2'},
                follow_redirects=False)
    ref3 = r.headers['Location'].rsplit('/', 1)[1]
    c2.post(f'/pay/gateway/{ref3}', data={'method': 'card'})
    r = c2.post(f'/pay/simulate/{ref3}', data={'outcome': 'fail'}, follow_redirects=True)
    assert 'declined' in r.get_data(as_text=True)
    with A.app.app_context():
        b3 = A.Booking.query.filter_by(reference=ref3).one()
        assert b3.status == 'FAILED' and b3.payment.status == 'FAILED'
        assert A.BookedSeat.query.filter_by(showtime_id=show_id, seat_id='E1').count() == 0
    html = c1.get(f'/book/{show_id}').get_data(as_text=True)
    assert 'data-seat="E1"' in html
    print("8. failed payment OK - E1/E2 released back to the seat map")

    # ---- 9. tampered signature is rejected ------------------------------
    r = c2.post(f'/book/{show_id}', data={'selected_seats': 'E5'}, follow_redirects=False)
    ref4 = r.headers['Location'].rsplit('/', 1)[1]
    c2.post(f'/pay/gateway/{ref4}', data={'method': 'upi'})
    with A.app.app_context():
        order_id = A.Booking.query.filter_by(reference=ref4).one().payment.order_id
    r = c2.post('/pay/callback', data={'reference': ref4,
                                       'razorpay_order_id': 'order_mock_unrelated',
                                       'razorpay_payment_id': 'pay_fake_123',
                                       'razorpay_signature': 'deadbeef'},
                follow_redirects=True)
    assert 'could not be matched' in r.get_data(as_text=True)
    with A.app.app_context():
        assert A.Booking.query.filter_by(reference=ref4).one().status == 'PENDING'
    r = c2.post('/pay/callback', data={'reference': ref4,
                                       'razorpay_order_id': order_id,
                                       'razorpay_payment_id': 'pay_fake_123',
                                       'razorpay_signature': 'deadbeef'},
                follow_redirects=True)
    assert 'could not be verified' in r.get_data(as_text=True)
    with A.app.app_context():
        assert A.Booking.query.filter_by(reference=ref4).one().status == 'FAILED'
    print("9. signature check OK - forged payment response rejected, nothing charged")

    # A live Razorpay order must never be markable as paid through the sandbox route.
    r = c1.post(f'/book/{show_id}', data={'selected_seats': 'F5'}, follow_redirects=False)
    ref_live = r.headers['Location'].rsplit('/', 1)[1]
    c1.post(f'/pay/gateway/{ref_live}', data={'method': 'upi'})
    with A.app.app_context():
        live_booking = A.Booking.query.filter_by(reference=ref_live).one()
        live_booking.payment.gateway = 'razorpay'
        live_booking.payment.order_id = 'order_live_security_check'
        A.db.session.commit()
    r = c1.post(f'/pay/simulate/{ref_live}', data={'outcome': 'success'},
                follow_redirects=False)
    assert r.status_code == 404
    with A.app.app_context():
        live_booking = A.Booking.query.filter_by(reference=ref_live).one()
        assert live_booking.status == 'PENDING'
        assert A.BookedSeat.query.filter_by(booking_id=live_booking.id).count() == 0
        A.release_booking(live_booking, 'CANCELLED')
    print("9b. live payment protected - sandbox route cannot capture a Razorpay order")

    previous_env = os.environ.get('APP_ENV')
    os.environ['APP_ENV'] = 'production'
    try:
        assert not A.payments.mock_payments_enabled()
        assert not A.payments.verify_signature('order_mock_fake', 'pay_fake',
                                                A.payments.mock_signature('order_mock_fake', 'pay_fake'))
        try:
            A.payments.create_order(100, 'production-guard')
            raise AssertionError('Production unexpectedly created a mock payment order')
        except A.payments.PaymentGatewayError:
            pass
    finally:
        if previous_env is None:
            os.environ.pop('APP_ENV', None)
        else:
            os.environ['APP_ENV'] = previous_env
    print("9c. production payment guard OK - mock order and signature rejected")

    # ---- 10. hold expiry -------------------------------------------------
    r = c1.post(f'/book/{show_id}', data={'selected_seats': 'F1'}, follow_redirects=False)
    ref5 = r.headers['Location'].rsplit('/', 1)[1]
    with A.app.app_context():
        b5 = A.Booking.query.filter_by(reference=ref5).one()
        past = A.datetime.utcnow() - A.timedelta(minutes=1)
        b5.expires_at = past
        A.SeatLock.query.filter_by(token=b5.lock_token).one().expires_at = past
        A.db.session.commit()
    r = c1.get(f'/checkout/{ref5}', follow_redirects=True)
    assert 'hold expired' in r.get_data(as_text=True)
    with A.app.app_context():
        assert A.Booking.query.filter_by(reference=ref5).one().status == 'EXPIRED'
        assert A.SeatLock.query.count() == 0
    print("10. expiry OK - unpaid hold expired and seat F1 freed")

    # ---- 11. wallet recharge approval flow -------------------------------
    c1.post('/wallet/recharge', data={'amount': 500}, follow_redirects=True)
    admin = A.app.test_client()
    # Authenticate the isolated fixture without coupling the business-flow
    # checks to an operator's admin password or changing any credentials.
    with A.app.app_context():
        admin_id = A.User.query.filter_by(username='admin').one().id
    with admin.session_transaction() as admin_session:
        admin_session['_user_id'] = str(admin_id)
        admin_session['_fresh'] = True
    with A.app.app_context():
        req_id = A.RechargeRequest.query.filter_by(status='PENDING').one().id
    admin.post(f'/admin/recharges/{req_id}/approve', follow_redirects=True)
    with A.app.app_context():
        u = A.User.query.filter_by(username='mohith').one()
        w = A.Wallet.query.filter_by(user_id=u.id).one()
        assert round(w.balance, 2) == round(2000 - 847.2 + 500, 2)
        assert A.RechargeRequest.query.get(req_id).status == 'APPROVED'
    print("11. wallet recharge OK - admin approval credited ₹500")

    # ---- 13. signup gives a 500 welcome balance --------------------------
    c3 = A.app.test_client()
    c3.post('/register', data={'username': 'newuser', 'email': 'n@x.com',
                               'phone': '9876543210', 'password': 'pass123'},
            follow_redirects=True)
    with A.app.app_context():
        nu = A.User.query.filter_by(username='newuser').one()
        nw = A.Wallet.query.filter_by(user_id=nu.id).one()
        assert nw.balance == 500, nw.balance
        assert A.WalletTransaction.query.filter_by(wallet_id=nw.id).one().description == 'Welcome bonus'
    print("13. signup bonus OK - new account starts with ₹500 in the wallet")

    # ---- 12. admin pages render -----------------------------------------
    for path in ['/admin', '/admin/screens', '/admin/add_screen', '/admin/add_showtime',
                 '/admin/bookings', '/admin/recharges', f'/admin/screen/{sid}/layout']:
        res = admin.get(path)
        assert res.status_code == 200, f'{path} -> {res.status_code}'
    for path in ['/', f'/movie/1', '/dashboard', '/wallet']:
        assert c1.get(path).status_code == 200, path
    assert not any(rule.rule.startswith('/api/ai') for rule in A.app.url_map.iter_rules())
    home_html = c1.get('/').get_data(as_text=True).lower()
    assert 'cinebot-widget' not in home_html and 'ai booking assistant' not in home_html
    assert 'cinewave-hero.jpg' in home_html
    print("12. all pages render (admin + user)")

    # ---- 14. admin analytics page + CSV export ---------------------------
    r = admin.get('/admin/analytics?days=30', follow_redirects=False)
    assert r.status_code == 200, r.status_code
    html = r.get_data(as_text=True)
    assert 'Analytics' in html and 'Revenue trend' in html
    with A.app.app_context():
        a = A._collect_analytics(30)
        assert a['paid']['count'] == 2, a['paid']            # ref1 + ref2 from this flow
        assert abs(a['paid']['amount'] - 847.2 - b2.total_amount) < 0.01, a['paid']
        assert a['active_buyers'] == 2, a['active_buyers']
        assert a['pay_split'], 'payment split must not be empty'
        assert a['pay_split'][0]['amount'] > 0
        assert any(m['title'] == 'Pushpa 3 - The Rampage' for m in a['top_movies'])
        assert a['occupancy_overall'] >= 0
    print("14. analytics OK - KPIs computed: "
          f"{a['paid']['count']} paid, ₹{a['paid']['amount']:.2f}, "
          f"occ {a['occupancy_overall']}%")

    r = admin.get('/admin/analytics/export.csv?days=30', follow_redirects=False)
    assert r.status_code == 200 and 'text/csv' in r.headers['Content-Type']
    assert 'attachment' in r.headers.get('Content-Disposition', '')
    csv_body = r.get_data(as_text=True)
    assert csv_body.startswith('reference,booked_at,status')
    assert ref1 in csv_body and ref2 in csv_body
    assert 'Pushpa 3 - The Rampage' in csv_body
    print("14b. CSV export OK - header + both paid bookings present")

    # non-admin is kept out of analytics, same as every other admin page
    r = c1.get('/admin/analytics', follow_redirects=False)
    assert r.status_code == 302, r.status_code
    r = c1.get('/admin/analytics/export.csv?days=30', follow_redirects=False)
    assert r.status_code == 302, r.status_code
    print("14c. analytics guarded - non-admin redirected")

    # ---- 15. movie cast section + fetch-cast admin action ----------------
    with A.app.app_context():
        m1 = A.Movie.query.filter_by(title='Pushpa 3 - The Rampage').one()
        m_id = m1.id
        m1.cast_json = A.json.dumps({
            'director': 'Sukumar',
            'cast': [{'name': 'Allu Arjun', 'character': 'Pushpa Raj', 'profile': None},
                     {'name': 'Rashmika Mandanna', 'character': 'Srivalli', 'profile': None}]})
        A.db.session.commit()

    r = c1.get(f'/movie/{m_id}').get_data(as_text=True)
    assert 'Cast &amp; Crew' in r
    assert 'Sukumar' in r and 'Allu Arjun' in r and 'Pushpa Raj' in r
    print("15. cast OK - director + actors render on the movie page")

    # admin fetch-cast action answers gracefully with or without TMDb access
    r = admin.post(f'/admin/fetch_cast/{m_id}', follow_redirects=True)
    assert r.status_code == 200, r.status_code
    r = c1.get('/admin/analytics', follow_redirects=False)  # sanity: nothing broke
    assert r.status_code == 302
    print("15b. fetch-cast route OK - admin action handled without error")

    # ---- 16. Self-Service Cancellation with Wallet Refund --------------
    with A.app.app_context():
        u = A.User.query.filter_by(username='mohith').one()
        w_before = A.Wallet.query.filter_by(user_id=u.id).one().balance
        b_cancel = A.Booking.query.filter_by(reference=ref1).one()
        expected_refund = round(b_cancel.ticket_amount * 0.90, 2)
    
    r = c1.post(f'/booking/{ref1}/refund', follow_redirects=True)
    assert r.status_code == 200, r.status_code
    with A.app.app_context():
        u = A.User.query.filter_by(username='mohith').one()
        b_after = A.Booking.query.filter_by(reference=ref1).one()
        w_after = A.Wallet.query.filter_by(user_id=u.id).one().balance
        assert b_after.status == 'CANCELLED'
        assert round(w_after, 2) == round(w_before + expected_refund, 2)
        # Seats should be freed up
        assert A.BookedSeat.query.filter_by(booking_id=b_after.id).count() == 0
    print(f"16. Self-service Cancellation & Refund OK - ₹{expected_refund:.2f} credited to wallet, seats freed")

    # ---- 19. Spoiler Shield & Keyword Auto-Detection ------------------
    with A.app.app_context():
        m_id = A.Movie.query.first().id
    # Test review with explicit spoiler flag
    r = c1.post(f'/api/movie/{m_id}/rate', json={'rating': 5, 'review': 'Awesome film!', 'has_spoiler': True})
    assert r.status_code == 200 and r.get_json()['has_spoiler'] is True
    # Test review with auto-detected spoiler keyword 'climax twist'
    r = c1.post(f'/api/movie/{m_id}/rate', json={'rating': 4.5, 'review': 'The climax twist where the hero dies was shocking'})
    assert r.status_code == 200 and r.get_json()['has_spoiler'] is True
    print("19. Spoiler Shield OK - explicit and NLP keyword triggers detected")

    # ---- 20. Theater & Screen Comfort Scores ---------------------------
    with A.app.app_context():
        sc = A.Screen.query.filter(A.Screen.name.like('%Screen 1%')).first()
        assert sc.comfort_score >= 4.5
        assert len(sc.comfort_features) >= 2
    print(f"20. Comfort Score OK - {sc.full_name} scored {sc.comfort_score}/5.0 with {len(sc.comfort_features)} features")

    with A.app.app_context():
        rev = A.db.session.query(A.db.func.sum(A.Booking.total_amount)) \
                          .filter(A.Booking.status == 'PAID').scalar() or 0.0
        seats = sum(s.total_seats for s in A.Screen.query.all())
        assert A.Theater.query.count() >= 23 and A.Screen.query.count() >= 40
        aaa = A.Theater.query.filter_by(name='AAA Cinemas').one()
        assert sorted(s.total_seats for s in aaa.screens) == \
            [34, 58, 76, 130, 130, 197, 436, 491], 'AAA seat counts drifted'
        print(f"\nSeeded {A.Theater.query.count()} Vizag theatres, "
              f"{A.Screen.query.count()} screens, {seats} total seats")
        print(f"Revenue from active paid bookings: ₹{rev:.2f}")
    print("\nALL 20 CHECKS PASSED")


if __name__ == '__main__':
    try:
        main()
    finally:
        with A.app.app_context():
            A.db.session.remove()
            A.db.engine.dispose()
        _test_dir.cleanup()
