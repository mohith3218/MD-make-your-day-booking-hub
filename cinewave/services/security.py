from datetime import datetime
import re
from urllib.parse import parse_qs, urlparse
from flask import current_app, flash, redirect, url_for
from flask_login import current_user
from ..extensions import login_manager
from ..models import User



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


def parse_youtube_video_key(value):
    """Accept a YouTube video URL or 11-character video ID; reject other values."""
    value = (value or '').strip()
    if not value:
        return ''
    candidate = value
    if '://' in value:
        parsed = urlparse(value)
        host = (parsed.hostname or '').lower()
        if host in ('youtu.be', 'www.youtu.be'):
            candidate = parsed.path.strip('/').split('/')[0]
        elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'):
            if parsed.path == '/watch':
                candidate = parse_qs(parsed.query).get('v', [''])[0]
            else:
                parts = [part for part in parsed.path.split('/') if part]
                candidate = parts[1] if len(parts) > 1 and parts[0] in ('embed', 'shorts', 'live') else ''
        else:
            return None
    return candidate if re.fullmatch(r'[A-Za-z0-9_-]{11}', candidate) else None
