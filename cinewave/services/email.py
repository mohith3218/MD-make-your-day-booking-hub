import hashlib
import hmac
import html
import io
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlparse
import requests
from flask import current_app
from ..extensions import db
from ..models import Booking, PasswordResetThrottle



def smtp_is_configured():
    return bool(current_app.config['SMTP_HOST'] and current_app.config['SMTP_FROM_EMAIL'])


def send_email(message):
    """Send mail through the configured SMTP relay using TLS where available."""
    if not smtp_is_configured():
        raise RuntimeError('Email delivery is not configured. Set SMTP_HOST and SMTP_FROM_EMAIL.')
    context = ssl.create_default_context()
    if current_app.config['SMTP_USE_SSL']:
        with smtplib.SMTP_SSL(current_app.config['SMTP_HOST'], current_app.config['SMTP_PORT'],
                              timeout=15, context=context) as server:
            if current_app.config['SMTP_USERNAME']:
                server.login(current_app.config['SMTP_USERNAME'], current_app.config['SMTP_PASSWORD'])
            server.send_message(message)
    else:
        with smtplib.SMTP(current_app.config['SMTP_HOST'], current_app.config['SMTP_PORT'], timeout=15) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            if current_app.config['SMTP_USERNAME']:
                server.login(current_app.config['SMTP_USERNAME'], current_app.config['SMTP_PASSWORD'])
            server.send_message(message)


def password_recovery_is_configured():
    origin = current_app.config.get('PASSWORD_RESET_ORIGIN', '')
    parsed = urlparse(origin)
    return bool(current_app.config.get('BREVO_API_KEY') and current_app.config.get('BREVO_SENDER_EMAIL')
                and parsed.scheme == 'https' and parsed.netloc and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment)


def send_password_recovery_email(user, token):
    if not password_recovery_is_configured():
        return False
    recovery_url = current_app.config['PASSWORD_RESET_ORIGIN'] + '/reset-password#' + token
    response = requests.post('https://api.brevo.com/v3/smtp/email',
        headers={'api-key': current_app.config['BREVO_API_KEY'], 'accept': 'application/json',
                 'content-type': 'application/json'},
        json={'sender': {'name': current_app.config.get('BREVO_SENDER_NAME') or 'CineWave',
                         'email': current_app.config['BREVO_SENDER_EMAIL']},
              'to': [{'email': user.email}], 'subject': 'Reset your CineWave password',
              'textContent': ('Use this link within 30 minutes to choose a new password. '
                              'If you did not request this, ignore this email.\n\n' + recovery_url)},
        timeout=(3.05, 8))
    return 200 <= response.status_code < 300


def password_reset_throttled(account_key, client_key):
    now = datetime.utcnow()
    for category, value in (('account', account_key), ('client', client_key)):
        key = hashlib.sha256((category + ':' + value).encode()).hexdigest()
        row = PasswordResetThrottle.query.filter_by(throttle_key=key).with_for_update().first()
        if not row:
            row = PasswordResetThrottle(throttle_key=key, window_started=now, attempts=0)
            db.session.add(row)
            db.session.flush()
        if now - row.window_started >= timedelta(minutes=15):
            row.window_started, row.attempts = now, 0
        row.attempts += 1
        if row.attempts > 5:
            db.session.commit()
            return True
    db.session.commit()
    return False


def _otp_digest(code):
    return hmac.new(current_app.config['SECRET_KEY'].encode(), code.encode(), hashlib.sha256).hexdigest()


def send_registration_otp(user):
    code = f'{secrets.randbelow(1_000_000):06d}'
    user.email_otp_hash = _otp_digest(code)
    user.email_otp_expires_at = datetime.utcnow() + timedelta(minutes=10)
    user.email_otp_sent_at = datetime.utcnow()
    user.email_otp_attempts = 0
    db.session.commit()

    message = EmailMessage()
    message['Subject'] = 'Your MD CineWave verification code'
    message['From'] = current_app.config['SMTP_FROM_EMAIL']
    message['To'] = user.email
    message.set_content(
        f'Hello {user.username},\n\nYour email verification code is {code}. '
        'It expires in 10 minutes. If you did not create this account, ignore this email.'
    )
    send_email(message)


def dispatch_ticket_delivery(booking):
    """Email a confirmed ticket and QR pass; return False without undoing payment on mail failure."""
    user = booking.user
    if not user or not user.email:
        booking.ticket_email_error = 'The account has no email address.'
        db.session.commit()
        return False

    showtime = booking.showtime
    movie_title = showtime.movie.title
    date_text = showtime.show_date.strftime('%a, %d %b %Y')
    qr_payload = (f'CINEWAVE|{booking.reference}|{movie_title}|{showtime.theater}|'
                  f'{showtime.show_date}|{showtime.show_time}|{booking.seats}')
    message = EmailMessage()
    demo = bool(booking.payment and booking.payment.is_demo)
    notice = 'DEMO — No real money charged. Not valid for theatre admission.\n\n' if demo else ''
    if demo:
        qr_payload = 'DEMO|' + qr_payload
    message['Subject'] = ('DEMO — ' if demo else '') + f'Your MD CineWave ticket: {movie_title} ({booking.reference})'
    message['From'] = current_app.config['SMTP_FROM_EMAIL']
    message['To'] = user.email
    message.set_content(
        notice + f'Your booking is confirmed.\n\nMovie: {movie_title}\nTheatre: {showtime.theater}\n'
        f'Screen: {showtime.screen_label}\nDate: {date_text}\nTime: {showtime.show_time}\n'
        f'Seats: {booking.seats}\nBooking reference: {booking.reference}\n\n'
        + ('The attached QR code is a demonstration only.' if demo else 'The attached QR code is your entry pass.')
    )
    safe_title = html.escape(movie_title)
    message.add_alternative(
        f'<html><body><p>{html.escape(notice)}</p><h2>Booking confirmed</h2><p><b>{safe_title}</b></p>'
        f'<p>{html.escape(showtime.theater)} · {html.escape(showtime.screen_label)}</p>'
        f'<p>{html.escape(date_text)} at {html.escape(showtime.show_time)}</p>'
        f'<p>Seats: <b>{html.escape(booking.seats)}</b></p>'
        f'<p>Reference: <b>{html.escape(booking.reference)}</b></p>'
        '<p>Your QR ticket is attached to this email.</p></body></html>', subtype='html')
    try:
        import qrcode
        qr_buffer = io.BytesIO()
        qrcode.make(qr_payload).save(qr_buffer, format='PNG')
        message.add_attachment(qr_buffer.getvalue(), maintype='image', subtype='png',
                               filename=f'{booking.reference}-ticket-qr.png')
        send_email(message)
    except Exception:
        current_app.logger.exception('Ticket email delivery failed for booking %s', booking.reference)
        booking.ticket_email_error = 'Ticket email could not be delivered. Please try resending.'
        db.session.commit()
        return False

    booking.ticket_email_sent_at = datetime.utcnow()
    booking.ticket_email_error = None
    db.session.commit()
    return True
