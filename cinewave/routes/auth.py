from flask import Blueprint
from ._support import *

bp = Blueprint("auth", __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        next_url = safe_local_redirect(request.args.get('next'))
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session.clear()
            login_user(user, remember=request.form.get('remember') == 'on')
            get_wallet(user)
            return redirect(next_url or url_for('main.home'))
        flash('Invalid username or password')
        login_args = {'next': next_url} if next_url else {}
        return redirect(url_for('auth.login', **login_args))
    return render_template('login.html')


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        address = request.form.get('email', '').strip().casefold()[:120]
        client_ip = request.remote_addr or 'unknown'
        if password_reset_throttled(address, client_ip):
            flash('If an account matches that address, recovery instructions will be sent when available.')
            return redirect(url_for('auth.forgot_password'), code=303)
        user = User.query.filter(db.func.lower(User.email) == address).first() if address else None
        if not password_recovery_is_configured():
            return render_template('forgot_password.html', unavailable=True)
        if user and user.email:
            token = secrets.token_urlsafe(32)
            db.session.query(PasswordReset).filter_by(user_id=user.id, used_at=None).update(
                {'used_at': datetime.utcnow()}, synchronize_session=False)
            reset = PasswordReset(user_id=user.id,
                token_digest=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=datetime.utcnow() + timedelta(minutes=30))
            db.session.add(reset)
            db.session.commit()
            try:
                delivered = send_password_recovery_email(user, token)
            except requests.RequestException as error:
                app.logger.warning('Password recovery mail delivery failed (%s)', type(error).__name__)
                delivered = False
            if not delivered:
                reset.used_at = datetime.utcnow()
                db.session.commit()
                return render_template('forgot_password.html', unavailable=True)
        flash('If an account matches that address, recovery instructions will be sent. Check your inbox shortly.')
        return redirect(url_for('auth.forgot_password'), code=303)
    return render_template('forgot_password.html', unavailable=not password_recovery_is_configured())


@bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'GET':
        return render_template('reset_password.html', token='')
    token = request.form.get('token', '')
    digest = hashlib.sha256(token.encode()).hexdigest() if re.fullmatch(r'[A-Za-z0-9_-]{40,60}', token) else ''
    reset = PasswordReset.query.filter_by(token_digest=digest, used_at=None).with_for_update().first() if digest else None
    now = datetime.utcnow()
    if not reset or reset.expires_at <= now:
        flash('That reset link is invalid or expired. Request a new one to continue.')
        return redirect(url_for('auth.forgot_password'), code=303)
    password = request.form.get('password', '')
    confirmation = request.form.get('confirm_password', '')
    if len(password) < 10 or len(password) > 256 or password != confirmation:
        return render_template('reset_password.html', token=token,
            error='Use a password of at least 10 characters and enter it the same way twice.'), 400
    user = db.session.get(User, reset.user_id)
    if not user:
        flash('That reset link is invalid or expired. Request a new one to continue.')
        return redirect(url_for('auth.forgot_password'), code=303)
    user.set_password(password)
    user.alternative_id = secrets.token_urlsafe(32)
    reset.used_at = now
    db.session.query(PasswordReset).filter(PasswordReset.user_id == user.id,
        PasswordReset.id != reset.id, PasswordReset.used_at.is_(None)).update(
            {'used_at': now}, synchronize_session=False)
    db.session.commit()
    logout_user()
    session.clear()
    flash('Your password has been reset. Sign in with your new password.')
    return redirect(url_for('auth.login'), code=303)


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')

        if not re.fullmatch(r'[A-Za-z0-9_.-]{3,30}', username):
            flash('Username must be 3–30 characters and use only letters, numbers, dots, underscores, or hyphens.')
            return redirect(url_for('auth.register'))
        if not email or len(email) > 120 or not is_valid_email(email):
            flash("Please enter a valid email address.")
            return redirect(url_for('auth.register'))
        if phone and not re.fullmatch(r'\d{10}', phone):
            flash('Enter a 10-digit mobile number, or leave the field blank.')
            return redirect(url_for('auth.register'))
        if len(password) < 6 or len(password) > 256:
            flash('Use a password between 6 and 256 characters.')
            return redirect(url_for('auth.register'))
        if User.query.filter_by(username=username).first():
            flash('Username already exists!')
            return redirect(url_for('auth.register'))
        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists!')
            return redirect(url_for('auth.register'))

        user = User(username=username, email=email, email_verified=True, phone=phone or None)
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('That username or email is already registered. Please sign in or use different details.')
            return redirect(url_for('auth.register'))
        create_wallet(user)
        login_user(user)
        flash('Your account is ready. Welcome to MD CineWave!')
        return redirect(url_for('main.home'))
    return render_template('register.html')


@bp.route('/verify-email', methods=['GET', 'POST'])
def verify_email():
    user_id = session.get('pending_email_verification_user_id')
    user = db.session.get(User, user_id) if user_id else None
    if not user:
        session.pop('pending_email_verification_user_id', None)
        return redirect(url_for('auth.register'))
    if user.email_verified:
        session.pop('pending_email_verification_user_id', None)
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        now = datetime.utcnow()
        if user.email_otp_attempts >= 5:
            flash('Too many incorrect codes. Request a new code after the resend cooldown.')
        elif (not user.email_otp_hash or not user.email_otp_expires_at
              or user.email_otp_expires_at <= now):
            flash('Your code has expired. Request a new one.')
        else:
            user.email_otp_attempts += 1
            expected = _otp_digest(code) if re.fullmatch(r'\d{6}', code) else ''
            if hmac.compare_digest(user.email_otp_hash, expected):
                user.email_verified = True
                user.email_otp_hash = None
                user.email_otp_expires_at = None
                user.email_otp_attempts = 0
                db.session.commit()
                create_wallet(user)
                session.pop('pending_email_verification_user_id', None)
                flash('Email verified. Your account is ready; please sign in.')
                return redirect(url_for('auth.login'))
            db.session.commit()
            flash('That code is incorrect. Please try again.')
    return render_template('verify_email.html', email=user.email)


@bp.route('/verify-email/resend', methods=['POST'])
def resend_email_otp():
    user_id = session.get('pending_email_verification_user_id')
    user = db.session.get(User, user_id) if user_id else None
    if not user or user.email_verified:
        session.pop('pending_email_verification_user_id', None)
        return redirect(url_for('auth.register'))
    if user.email_otp_sent_at and datetime.utcnow() - user.email_otp_sent_at < timedelta(seconds=60):
        flash('Please wait one minute before requesting another code.')
    else:
        try:
            send_registration_otp(user)
            flash('A new verification code has been sent. It expires in 10 minutes.')
        except Exception:
            app.logger.exception('Registration OTP resend failed for user %s', user.id)
            flash('We could not send the email right now. Please try again later.')
    return redirect(url_for('auth.verify_email'))


@bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.home'))
