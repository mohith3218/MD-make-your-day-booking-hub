import re
from urllib.parse import urlparse
from flask import flash, redirect, url_for
from flask_login import current_user
from .extensions import login_manager
from .integrations.trailers import parse_youtube_video_key
from .models import User



@login_manager.user_loader
def load_user(user_id):
    return User.query.filter_by(alternative_id=user_id).first()


def is_valid_email(email):
    return re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email) is not None


def safe_local_redirect(target):
    """Return a same-site redirect target, or None for external/unsafe URLs."""
    if not target:
        return None
    if any(ord(char) < 32 for char in target) or '\\' in target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith('/') or target.startswith('//'):
        return None
    return target


def admin_required():
    """Returns a redirect response if the user is not an admin, else None."""
    if not current_user.is_authenticated or not current_user.is_admin:
        flash("Access denied")
        return redirect(url_for('main.home'))
    return None


