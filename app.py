"""CineWave WSGI compatibility entry point. Build new apps with create_app()."""
import csv
import datetime
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import smtplib
import ssl
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import payments
from cinewave.config import *
from cinewave.database import auto_migrate, seed_sample_movies
from cinewave.database import init_db as _initialize_database
from cinewave.extensions import db, login_manager
from cinewave.factory import create_app
from cinewave.hooks import current_csrf_token, validate_production_config
from cinewave.models import *
from cinewave.services import *
from cinewave.data import *
from vizag_theaters import seed_vizag_theaters, correct_jagadamba_levels
from theatre_service import TheatreService
from theatre_discovery import cinema_now, validate_booking_context
import seat_layout as sl

app = create_app()


def init_db():
    """Compatibility wrapper for the existing local setup scripts."""
    return _initialize_database(app)


# Preserve import compatibility for existing scripts that call view functions directly.
from cinewave.routes.main import home
from cinewave.routes.auth import login, forgot_password, reset_password, register, verify_email, resend_email_otp, logout
from cinewave.routes.movies import cine_match, vote_movie_hype, movie_detail, movies_by_mood, toggle_watchlist, watchlist_page, rate_movie
from cinewave.routes.booking import book, vr_seat_preview, checkout, split_pay, start_split_payment, split_payment_confirmation, simulate_split_payment, update_booking_extras, pay_with_wallet, pay_gateway, pay_mock_confirmation, payment_callback, simulate, cancel_booking, refund_booking, resend_ticket_delivery, ticket, ticket_qr
from cinewave.routes.party import party_create, party_join, party_sync, party_leave, party_close
from cinewave.routes.wallet import wallet_page, wallet_convert_points, wallet_recharge
from cinewave.routes.profile import dashboard, profile, edit_profile
from cinewave.routes.admin import admin, add_movie, update_movie_trailer, import_movie, import_movie_add, toggle_movie_status, set_movie_featured_order, fetch_cast, toggle_rerelease, delete_movie, add_theater, seed_vizag, screens, add_screen, edit_layout, edit_auditorium_reference, admin_auditorium_reference_file, add_showtime, admin_recharges, handle_recharge, admin_bookings, admin_analytics, admin_analytics_export
from cinewave.routes.theatre import api_theatres, api_theatre_detail, api_screen_layout, screen_classes, seat_availability, showtime_live_info

if __name__ == '__main__':
    init_db()
    debug_enabled = os.environ.get('FLASK_DEBUG', '').strip().lower() in {'1', 'true', 'yes'}
    app.run(debug=debug_enabled)
