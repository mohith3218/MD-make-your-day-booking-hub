"""Authentication regression tests using a disposable, explicitly isolated SQLite DB."""
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
_temporary = tempfile.TemporaryDirectory(prefix='auth-audit-', dir=ROOT / 'instance')
_database_url = 'sqlite:///' + (Path(_temporary.name) / 'auth-test.db').as_posix()
os.environ.update(
    APP_ENV='testing', DATABASE_URL=_database_url, TEST_DATABASE_URL=_database_url,
    SECRET_KEY='isolated-auth-audit-test-key-2026', SESSION_COOKIE_SECURE='0',
    SMTP_HOST='', SMTP_USERNAME='', SMTP_PASSWORD='', TMDB_API_KEY='',
)

import app as A


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with A.app.app_context():
            configured = Path(A.db.engine.url.database).resolve()
            assert configured.is_relative_to(Path(_temporary.name).resolve())

    @classmethod
    def tearDownClass(cls):
        with A.app.app_context():
            A.db.session.remove()
            A.db.engine.dispose()
        _temporary.cleanup()

    def setUp(self):
        self.context = A.app.app_context()
        self.context.push()
        A.app.config.update(TESTING=True)
        A.app.config.update(BREVO_API_KEY='', BREVO_SENDER_EMAIL='',
                            PASSWORD_RESET_ORIGIN='')
        A.db.drop_all()
        A.db.create_all()
        self.client = A.app.test_client()

    def tearDown(self):
        A.db.session.remove()
        self.context.pop()

    def csrf(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            token = session.get('_csrf_token')
        self.assertTrue(token)
        self.assertIn(f'name="csrf_token" value="{token}"'.encode(), response.data)
        return token

    def add_user(self, username='cine_user', email='cine@example.test', password='correct-horse'):
        user = A.User(username=username, email=email, email_verified=True)
        user.set_password(password)
        A.db.session.add(user)
        A.db.session.commit()
        return user

    def test_registration_persists_validated_profile_hashes_password_and_logs_in(self):
        token = self.csrf('/register')
        response = self.client.post('/register', data={
            'csrf_token': token, 'username': 'new_cine_user', 'email': 'New@Example.test',
            'phone': '9876543210', 'password': 'long-enough-password',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/')
        user = A.User.query.filter_by(username='new_cine_user').one()
        self.assertEqual(user.email, 'new@example.test')
        self.assertEqual(user.phone, '9876543210')
        self.assertNotEqual(user.password_hash, 'long-enough-password')
        self.assertTrue(user.check_password('long-enough-password'))
        self.assertIsNotNone(A.Wallet.query.filter_by(user_id=user.id).one())
        with self.client.session_transaction() as session:
            self.assertEqual(session.get('_user_id'), user.alternative_id)

    def test_registration_rejects_invalid_username_email_phone_and_password(self):
        valid = {'username': 'new_user', 'email': 'new@example.test', 'phone': '', 'password': '123456'}
        invalid_cases = [
            {'username': ''}, {'username': 'x'}, {'email': 'not-an-email'},
            {'phone': '123abc'}, {'password': '12345'},
        ]
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid):
                self.client = A.app.test_client()
                token = self.csrf('/register')
                self.client.post('/register', data={**valid, **invalid, 'csrf_token': token})
                self.assertEqual(A.User.query.count(), 0)

    def test_registration_rejects_duplicate_username_and_email(self):
        self.add_user(username='taken_user', email='taken@example.test')
        for payload in (
            {'username': 'taken_user', 'email': 'other@example.test'},
            {'username': 'other_user', 'email': 'taken@example.test'},
        ):
            client = A.app.test_client()
            response = client.get('/register')
            with client.session_transaction() as session:
                token = session['_csrf_token']
            response = client.post('/register', data={
                **payload, 'phone': '', 'password': '123456', 'csrf_token': token,
            })
            self.assertEqual(response.status_code, 302)
        self.assertEqual(A.User.query.count(), 1)

    def test_login_uses_generic_error_and_accepts_valid_credentials(self):
        user = self.add_user()
        token = self.csrf('/login')
        failed = self.client.post('/login', data={'csrf_token': token, 'username': user.username, 'password': 'wrong'})
        self.assertEqual(failed.status_code, 302)
        self.assertIn(b'Invalid username or password', self.client.get(failed.location).data)
        token = self.csrf('/login')
        unknown = self.client.post('/login', data={'csrf_token': token, 'username': 'missing', 'password': 'wrong'})
        self.assertEqual(unknown.status_code, 302)
        self.assertIn(b'Invalid username or password', self.client.get(unknown.location).data)

        token = self.csrf('/login?next=/dashboard')
        success = self.client.post('/login?next=/dashboard', data={
            'csrf_token': token, 'username': user.username, 'password': 'correct-horse',
        })
        self.assertEqual(success.status_code, 302)
        self.assertTrue(success.location.endswith('/dashboard'))
        with self.client.session_transaction() as session:
            self.assertEqual(session.get('_user_id'), user.alternative_id)

    def test_upcoming_hype_vote_changes_in_place_and_renders_counts(self):
        user = self.add_user()
        movie = A.Movie(title='Upcoming test', description='A new film', duration=110,
                        is_upcoming=True)
        A.db.session.add(movie)
        A.db.session.commit()
        with self.client.session_transaction() as session:
            session['_user_id'] = user.alternative_id
            session['_fresh'] = True
        page = self.client.get('/?category=upcoming')
        self.assertEqual(page.status_code, 200)
        with self.client.session_transaction() as session:
            csrf = session['_csrf_token']
        for level in ('HYPED', 'EXTREME_HYPED'):
            response = self.client.post(f'/movies/{movie.id}/hype', data={
                'csrf_token': csrf, 'level': level,
            })
            self.assertEqual(response.status_code, 303)
        vote = A.MovieHypeVote.query.filter_by(user_id=user.id, movie_id=movie.id).one()
        self.assertEqual(vote.level, 'EXTREME_HYPED')
        self.assertEqual(A.MovieHypeVote.query.filter_by(movie_id=movie.id).count(), 1)
        page = self.client.get('/?category=upcoming')
        self.assertIn(b'Extreme Hyped <span>1</span>', page.data)

    def test_unsafe_login_redirect_falls_back_to_home(self):
        user = self.add_user()
        token = self.csrf('/login?next=https://example.test/')
        response = self.client.post('/login?next=https://example.test/', data={
            'csrf_token': token, 'username': user.username, 'password': 'correct-horse',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/')

    def test_authentication_and_email_posts_reject_missing_or_forged_csrf(self):
        self.assertEqual(self.client.post('/register', data={'username': 'x'}).status_code, 400)
        token = self.csrf('/login')
        self.assertEqual(self.client.post('/login', data={'csrf_token': 'forged'}).status_code, 400)
        self.assertEqual(self.client.post('/verify-email', data={'csrf_token': 'forged'}).status_code, 400)

    def test_logout_is_post_only_and_clears_authenticated_session(self):
        user = self.add_user()
        token = self.csrf('/login')
        self.client.post('/login', data={'csrf_token': token, 'username': user.username, 'password': 'correct-horse'})
        self.assertEqual(self.client.get('/logout').status_code, 405)
        self.csrf('/')
        self.assertEqual(self.client.post('/logout').status_code, 400)
        with self.client.session_transaction() as session:
            token = session['_csrf_token']
        response = self.client.post('/logout', data={'csrf_token': token})
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn('_user_id', session)

    def test_remembered_login_uses_revocable_id_and_logout_clears_cookie(self):
        user = self.add_user()
        token = self.csrf('/login')
        response = self.client.post('/login', data={
            'csrf_token': token, 'username': user.username, 'password': 'correct-horse', 'remember': 'on',
        })
        self.assertEqual(response.status_code, 302)
        cookie = self.client.get_cookie('remember_token')
        self.assertIsNotNone(cookie)
        self.assertIn(user.alternative_id, cookie.value)
        self.assertTrue(cookie.value.startswith(user.alternative_id + '|'))
        csrf = self.client.get('/')
        self.assertEqual(csrf.status_code, 200)
        with self.client.session_transaction() as session:
            logout_token = session['_csrf_token']
        self.client.post('/logout', data={'csrf_token': logout_token})
        self.assertIsNone(self.client.get_cookie('remember_token'))

    def test_direct_pages_redirect_and_apis_return_structured_401(self):
        response = self.client.get('/?category=upcoming')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login?next=', response.location)
        api = self.client.get('/api/showtime/1/availability')
        self.assertEqual(api.status_code, 401)
        self.assertEqual(api.json['error'], 'authentication_required')
        login_page = self.client.get('/login')
        self.assertNotIn(b'CineMatch', login_page.data)
        self.assertNotIn(b'Theatres', login_page.data)

    def test_password_reset_is_digest_backed_single_use_and_invalidates_sessions(self):
        user = self.add_user()
        A.app.config.update(BREVO_API_KEY='fake-brevo-key',
            BREVO_SENDER_EMAIL='cinema@example.test', PASSWORD_RESET_ORIGIN='https://cinewave.example')
        token_value = {}
        def capture(account, token):
            token_value['token'] = token
            return True
        with patch.object(A, 'send_password_recovery_email', side_effect=capture):
            csrf = self.csrf('/forgot-password')
            response = self.client.post('/forgot-password', data={'csrf_token': csrf, 'email': user.email})
        self.assertEqual(response.status_code, 303)
        self.assertIn('token', token_value)
        reset_row = A.PasswordReset.query.one()
        old_alternative_id = user.alternative_id
        # Preview GETs display the form and do not consume the one-time token.
        page = self.client.get('/reset-password#' + token_value['token'])
        self.assertEqual(page.status_code, 200)
        self.assertIsNone(reset_row.used_at)
        self.assertEqual(page.headers['Cache-Control'], 'no-store, max-age=0')
        csrf = self.csrf('/reset-password')
        response = self.client.post('/reset-password', data={
            'csrf_token': csrf, 'token': token_value['token'],
            'password': 'a-new-strong-password', 'confirm_password': 'a-new-strong-password',
        })
        self.assertEqual(response.status_code, 303)
        self.assertTrue(user.check_password('a-new-strong-password'))
        self.assertNotEqual(user.alternative_id, old_alternative_id)
        self.assertIsNotNone(reset_row.used_at)
        new_csrf = self.csrf('/reset-password')
        retry = self.client.post('/reset-password', data={
            'csrf_token': new_csrf, 'token': token_value['token'],
            'password': 'another-new-password', 'confirm_password': 'another-new-password',
        })
        self.assertEqual(retry.status_code, 303)

    def test_recovery_unavailable_is_honest_and_never_shows_a_token(self):
        page = self.client.get('/forgot-password')
        self.assertEqual(page.status_code, 200)
        with self.client.session_transaction() as state:
            csrf = state['_csrf_token']
        response = self.client.post('/forgot-password', data={
            'csrf_token': csrf, 'email': 'cine@example.test',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'not configured', response.data)
        self.assertNotIn(b'recovery instructions will be sent', response.data)

    def test_wallet_points_conversion_is_atomic_idempotent_and_respects_pending_checkout(self):
        user = self.add_user()
        user.points = 50
        A.db.session.add(A.Wallet(user_id=user.id, balance=100))
        A.db.session.commit()
        token = self.csrf('/login')
        self.client.post('/login', data={'csrf_token': token, 'username': user.username,
            'password': 'correct-horse'})
        wallet_page = self.client.get('/wallet')
        key_match = re.search(rb'name="idempotency_key" value="([^"]+)"', wallet_page.data)
        self.assertIsNotNone(key_match)
        key = key_match.group(1).decode()
        token = self.csrf('/wallet')
        data = {'csrf_token': token, 'idempotency_key': key, 'points': '20'}
        self.assertEqual(self.client.post('/wallet/convert-points', data=data).status_code, 303)
        A.db.session.refresh(user)
        wallet = A.Wallet.query.filter_by(user_id=user.id).one()
        self.assertEqual(user.points, 30)
        self.assertEqual(wallet.balance, 120)
        self.assertEqual(A.WalletTransaction.query.filter_by(type='CONVERT').count(), 1)
        self.assertEqual(self.client.post('/wallet/convert-points', data=data).status_code, 303)
        A.db.session.refresh(user)
        self.assertEqual(user.points, 30)
        self.assertEqual(wallet.balance, 120)

        A.db.session.add(A.Booking(user_id=user.id, showtime_id=1, seats='A1',
            points_redeemed=25, total_amount=10, status='PENDING',
            expires_at=A.datetime.utcnow() + A.timedelta(minutes=8)))
        A.db.session.commit()
        token = self.csrf('/wallet')
        reserve_attempt = self.client.post('/wallet/convert-points', data={
            'csrf_token': token, 'idempotency_key':'another-idempotency-key-001', 'points':'6'})
        self.assertEqual(reserve_attempt.status_code, 303)
        A.db.session.refresh(user)
        self.assertEqual(user.points, 30)


if __name__ == '__main__':
    unittest.main()
