"""Flask application factory and extension/blueprint composition."""
from flask import Flask
from .config import PROJECT_ROOT, configure_app
from .extensions import db, login_manager
from .hooks import register_hooks
from . import models as _models


def create_app(config=None):
    application = Flask('cinewave', template_folder=str(PROJECT_ROOT / 'templates'),
                        static_folder=str(PROJECT_ROOT / 'static'))
    configure_app(application, config)
    db.init_app(application)
    login_manager.init_app(application)
    login_manager.login_view = 'auth.login'
    login_manager.session_protection = 'strong'
    register_hooks(application)
    from types import SimpleNamespace
    from theatre_discovery import create_theatre_blueprint
    from .services import show_seat_prices
    from .models import Theater, Screen, Showtime, Movie, BookedSeat, SeatHold
    application.register_blueprint(create_theatre_blueprint(db, SimpleNamespace(
        Theater=Theater, Screen=Screen, Showtime=Showtime, Movie=Movie,
        BookedSeat=BookedSeat, SeatHold=SeatHold), show_seat_prices))
    from .routes import register_blueprints
    register_blueprints(application)
    return application
