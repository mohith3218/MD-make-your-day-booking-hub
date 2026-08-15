"""
End-to-end smoke test for CineWave.
Covers: seed -> movie -> showtime -> seat map -> hold -> wallet pay -> ticket
        -> double-booking block -> gateway pay -> failed payment -> expiry.
Run:  python test_flow.py
"""
import json
import os
import re
from datetime import date, timedelta

os.environ.pop('RAZORPAY_KEY_ID', None)

import app as A


def main():
    if os.path.exists('instance/vizag_movies.db'):
        os.remove('instance/vizag_movies.db')
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
                                       'razorpay_order_id': order_id,
                                       'razorpay_payment_id': 'pay_fake_123',
                                       'razorpay_signature': 'deadbeef'},
                follow_redirects=True)
    assert 'could not be verified' in r.get_data(as_text=True)
    with A.app.app_context():
        assert A.Booking.query.filter_by(reference=ref4).one().status == 'FAILED'
    print("9. signature check OK - forged payment response rejected, nothing charged")

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
    admin.post('/login', data={'username': 'admin', 'password': 'admin123'},
               follow_redirects=True)
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
    print("12. all pages render (admin + user)")

    with A.app.app_context():
        rev = A.db.session.query(A.db.func.sum(A.Booking.total_amount)) \
                          .filter(A.Booking.status == 'PAID').scalar()
        seats = sum(s.total_seats for s in A.Screen.query.all())
        assert A.Theater.query.count() >= 23 and A.Screen.query.count() >= 40
        aaa = A.Theater.query.filter_by(name='AAA Cinemas').one()
        assert sorted(s.total_seats for s in aaa.screens) == \
            [34, 58, 76, 130, 130, 197, 436, 491], 'AAA seat counts drifted'
        print(f"\nSeeded {A.Theater.query.count()} Vizag theatres, "
              f"{A.Screen.query.count()} screens, {seats} total seats")
        print(f"Revenue from paid bookings: ₹{rev:.2f}")
    print("\nALL 13 CHECKS PASSED")


if __name__ == '__main__':
    main()
