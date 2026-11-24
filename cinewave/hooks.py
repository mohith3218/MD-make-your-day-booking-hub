"""Request policy, CSRF, response hardening, and template context hooks."""
import hmac
import os
import secrets
from datetime import date
from flask import abort, current_app, flash, g, jsonify, redirect, request, session, url_for
from flask_login import current_user
from .extensions import db
from .models import Wallet
from .services import safe_local_redirect
import payments


def validate_production_config():
    if current_app.config['APP_ENV'] != 'production':
        return
    required = {'SECRET_KEY': current_app.config.get('SECRET_KEY'),
                'DATABASE_URL': os.environ.get('DATABASE_URL')}
    missing = [name for name, value in required.items() if not value]
    if current_app.config.get('SECRET_KEY') and len(current_app.config['SECRET_KEY']) < 32:
        missing.append('SECRET_KEY (at least 32 characters)')
    if missing:
        raise RuntimeError('Production configuration is incomplete: ' + ', '.join(missing))
    if db.engine.dialect.name == 'sqlite':
        raise RuntimeError('Production requires PostgreSQL; SQLite is supported for development and tests only.')


def current_csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


def register_hooks(application):
    @application.before_request
    def enforce_production_configuration():
        validate_production_config()

    @application.before_request
    def require_sign_in_for_application_routes():
        g.pop('_login_user', None)
        public = {'static', 'auth.login', 'auth.register', 'auth.verify_email',
                  'auth.resend_email_otp', 'auth.forgot_password', 'auth.reset_password',
                  'theatre_discovery.index', 'theatre_discovery.detail', 'screen_reviews.detail',
                  'movie_reviews.detail'}
        if request.endpoint is None or request.endpoint in public or current_user.is_authenticated:
            return None
        if request.path.startswith('/api/') or request.is_json or (
                request.endpoint == 'movies.vote_movie_hype' and
                request.accept_mimetypes.best == 'application/json'):
            return jsonify({'error': 'authentication_required', 'message': 'Sign in to continue.'}), 401
        next_url = safe_local_redirect(request.full_path.rstrip('?'))
        return redirect(url_for('auth.login', next=next_url) if next_url else url_for('auth.login'))

    @application.before_request
    def enforce_demo_payment_setting():
        protected = {'booking.pay_with_wallet', 'booking.pay_gateway', 'booking.pay_mock_confirmation',
                     'booking.payment_callback', 'booking.simulate', 'booking.start_split_payment',
                     'booking.simulate_split_payment', 'wallet.wallet_recharge',
                     'wallet.wallet_convert_points', 'admin.handle_recharge'}
        if request.endpoint in protected and not payments.mock_payments_enabled():
            abort(403, description='Demo payments are disabled. No real payment is available.')

    @application.before_request
    def protect_account_forms():
        protected = {'auth.login', 'auth.register', 'auth.verify_email', 'auth.resend_email_otp',
                     'auth.logout', 'auth.forgot_password', 'auth.reset_password',
                     'wallet.wallet_convert_points', 'admin.import_movie_add',
                     'admin.set_movie_featured_order', 'admin.queue_movie_sync', 'admin.edit_movie',
                     'admin.update_movie_trailer', 'admin.toggle_movie_status', 'admin.fetch_cast',
                     'admin.add_showtime', 'admin.add_movie', 'admin.toggle_rerelease', 'admin.delete_movie',
                     'admin.verify_theater', 'admin.verify_screen', 'admin.archive_movie',
                     'movies.vote_movie_hype', 'screen_reviews.edit', 'screen_reviews.dismiss',
                     'screen_reviews.withdraw', 'screen_reviews.report', 'screen_reviews.moderate',
                     'movie_reviews.edit', 'movie_reviews.withdraw', 'movie_reviews.report',
                     'movie_reviews.moderate', 'movies.rate_movie'}
        if request.method == 'POST' and request.endpoint in protected:
            expected = session.get('_csrf_token', '')
            supplied = request.form.get('csrf_token', '')
            if request.endpoint == 'movies.rate_movie' and request.is_json:
                supplied = request.headers.get('X-CSRF-Token', '')
            if not expected or not supplied or not hmac.compare_digest(expected, supplied):
                abort(400, description='Your form session expired. Reload the page and try again.')

    @application.after_request
    def add_security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        if current_app.config['APP_ENV'] == 'production':
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        if request.endpoint in {'auth.forgot_password', 'auth.reset_password'}:
            response.headers['Cache-Control'] = 'no-store, max-age=0'
            response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @application.context_processor
    def inject_globals():
        wallet_balance = None
        user_points = 0
        if current_user.is_authenticated:
            wallet = Wallet.query.filter_by(user_id=current_user.id).first()
            wallet_balance = wallet.balance if wallet else 0
            user_points = current_user.points or 0
        return {'wallet_balance': wallet_balance, 'user_points': user_points,
                'demo_payments_enabled': payments.mock_payments_enabled(),
                'startup_id': current_app.config['STARTUP_ID'],
                'today': date.today(), 'csrf_token': current_csrf_token()}
