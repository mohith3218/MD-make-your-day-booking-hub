"""Runtime configuration for development, tests, and hosted PostgreSQL."""
import os
import secrets
from datetime import timedelta
from pathlib import Path
from database_config import database_settings

APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
TMDB_BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280"
SEAT_LOCK_MINUTES = 8
WELCOME_WALLET_BALANCE = 500
PARTY_LIFETIME = timedelta(hours=2)
PARTY_PRESENCE = timedelta(seconds=60)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def configure_app(application, overrides=None):
    """Apply environment-backed settings, then explicit factory overrides."""
    environment = os.environ.get("APP_ENV", "development").strip().lower()
    application.config.update(
        APP_ENV=environment,
        SECRET_KEY=os.environ.get("SECRET_KEY") or (None if environment == "production" else secrets.token_hex(32)),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TEMPLATES_AUTO_RELOAD=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=environment == "production" or os.environ.get("SESSION_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes"},
        REMEMBER_COOKIE_DURATION=timedelta(days=30),
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,
        STARTUP_ID=secrets.token_urlsafe(10),
        SMTP_HOST=os.environ.get("SMTP_HOST", "").strip(),
        SMTP_PORT=int(os.environ.get("SMTP_PORT", "587")),
        SMTP_USERNAME=os.environ.get("SMTP_USERNAME", "").strip(),
        SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD", ""),
        SMTP_FROM_EMAIL=os.environ.get("SMTP_FROM_EMAIL", os.environ.get("SMTP_USERNAME", "")).strip(),
        SMTP_USE_SSL=os.environ.get("SMTP_USE_SSL", "").strip().lower() in {"1", "true", "yes"},
        BREVO_API_KEY=os.environ.get("BREVO_API_KEY", "").strip(),
        BREVO_SENDER_EMAIL=os.environ.get("BREVO_SENDER_EMAIL", "").strip(),
        BREVO_SENDER_NAME=os.environ.get("BREVO_SENDER_NAME", "CineWave").strip(),
        PASSWORD_RESET_ORIGIN=os.environ.get("PASSWORD_RESET_ORIGIN", "").strip().rstrip("/"),
    )
    env = dict(os.environ)
    if environment == "development":
        env["DATABASE_URL"] = "sqlite:///vizag_movies.db"
    if environment == "production" and not env.get("DATABASE_URL"):
        raise RuntimeError("Production requires DATABASE_URL pointing to Supabase PostgreSQL.")
    database_url, engine_options = database_settings(env)
    application.config["SQLALCHEMY_DATABASE_URI"] = database_url
    application.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_options
    application.config["REMEMBER_COOKIE_SECURE"] = application.config["SESSION_COOKIE_SECURE"]
    if overrides:
        application.config.update(overrides)
    return application
