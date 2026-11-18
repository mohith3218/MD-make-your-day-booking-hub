from .main import bp as main_bp
from .auth import bp as auth_bp
from .movies import bp as movies_bp
from .booking import bp as booking_bp
from .party import bp as party_bp
from .wallet import bp as wallet_bp
from .profile import bp as profile_bp
from .admin import bp as admin_bp
from .theatre import bp as theatre_bp

BLUEPRINTS = (main_bp, auth_bp, movies_bp, theatre_bp, booking_bp, party_bp, wallet_bp, profile_bp, admin_bp)

def register_blueprints(application):
    for blueprint in BLUEPRINTS:
        application.register_blueprint(blueprint)

__all__ = ["BLUEPRINTS", "register_blueprints", "main_bp", "auth_bp", "movies_bp", "booking_bp", "party_bp", "wallet_bp", "profile_bp", "admin_bp", "theatre_bp"]
