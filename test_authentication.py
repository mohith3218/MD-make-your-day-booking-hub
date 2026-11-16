"""Authentication regression tests using a disposable, explicitly isolated SQLite DB."""
import os
from pathlib import Path
import tempfile
import unittest

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
            self.assertEqual(session.get('_user_id'), str(user.id))

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
        self.assertEqual(failed.status_code, 200)
        self.assertIn(b'Invalid username or password', failed.data)
        token = self.csrf('/login')
        unknown = self.client.post('/login', data={'csrf_token': token, 'username': 'missing', 'password': 'wrong'})
        self.assertEqual(unknown.status_code, 200)
        self.assertIn(b'Invalid username or password', unknown.data)

        token = self.csrf('/login?next=/dashboard')
        success = self.client.post('/login?next=/dashboard', data={
            'csrf_token': token, 'username': user.username, 'password': 'correct-horse',
        })
        self.assertEqual(success.status_code, 302)
        self.assertTrue(success.location.endswith('/dashboard'))
        with self.client.session_transaction() as session:
            self.assertEqual(session.get('_user_id'), str(user.id))

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


if __name__ == '__main__':
    unittest.main()
