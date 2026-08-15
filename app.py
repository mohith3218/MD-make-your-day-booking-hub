"""
CineWave - Vizag Movie Ticket Booking
=====================================
Backend: Flask + SQLAlchemy (SQLite)

What is new in this version
---------------------------
1. REAL THEATRE SEATING
   Theater -> Screen -> layout JSON. Every audi in Vizag has its own row
   widths, aisle positions, seat classes and blocked seats. Seeded with
   INOX Varun Beach / CMR Central / Chitralaya, Cinepolis Sreekanya,
   Mukta A2, Jagadamba 70MM, Melody, Sangam Sarat.

2. FULL PAYMENT FLOW
   select seats -> seats locked for 8 min -> checkout (wallet / UPI / card)
   -> gateway order -> signature verification -> seats committed -> e-ticket.
   Razorpay when keys are set, sandbox simulator otherwise.
   Wallet, recharge requests and admin approval are now wired up.

Run:
    pip install -r requirements.txt
    python app.py            ->  http://127.0.0.1:5000
    admin / admin123
"""

import json
import os
import re
import secrets
from datetime import date, datetime, timedelta

import requests
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

import payments
import seat_layout as sl
from vizag_theaters import seed_vizag_theaters

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'vizag-movie-booking-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vizag_movies.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# TMDb API Key
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "329d5f23baebf5312db6f28ab506ce9e")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

# how long selected seats stay held while the user pays
SEAT_LOCK_MINUTES = 8

# every new account starts with this much wallet money (signup bonus)
WELCOME_WALLET_BALANCE = 500

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# ====================== MODELS ======================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    phone = db.Column(db.String(15), nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    poster = db.Column(db.String(500), nullable=True)
    language = db.Column(db.String(50), nullable=True, default='Telugu')
    certificate = db.Column(db.String(10), nullable=True, default='U/A')


class Theater(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    location = db.Column(db.String(200), nullable=True)
    city = db.Column(db.String(80), nullable=True, default='Visakhapatnam')
    address = db.Column(db.String(400), nullable=True)

    screens = db.relationship('Screen', backref='theater', lazy=True,
                              cascade='all, delete-orphan')

    @property
    def display_name(self):
        return f"{self.name} — {self.location}" if self.location else self.name


class Screen(db.Model):
    """One audi. Holds the actual seating arrangement of that hall."""
    id = db.Column(db.Integer, primary_key=True)
    theater_id = db.Column(db.Integer, db.ForeignKey('theater.id'), nullable=False)
    name = db.Column(db.String(80), nullable=False)              # "Screen 1"
    screen_type = db.Column(db.String(40), default='2D')         # 2D/3D/IMAX/Recliner
    layout_json = db.Column(db.Text, nullable=False, default='{}')

    @property
    def layout(self):
        try:
            return json.loads(self.layout_json or '{}')
        except json.JSONDecodeError:
            return {}

    @layout.setter
    def layout(self, value):
        self.layout_json = json.dumps(value, indent=2)

    @property
    def total_seats(self):
        return sl.count_seats(self.layout)

    @property
    def classes_summary(self):
        return ", ".join(c.get('name', '?') for c in self.layout.get('classes', []))

    @property
    def full_name(self):
        return f"{self.theater.name} · {self.name}"


class Showtime(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    screen_id = db.Column(db.Integer, db.ForeignKey('screen.id'), nullable=True)
    theater = db.Column(db.String(100), nullable=False)          # kept for old rows/templates
    show_date = db.Column(db.Date, nullable=False)
    show_time = db.Column(db.String(20), nullable=False)
    price_overrides_json = db.Column(db.Text, default='{}')      # {"RECLINER": 400}

    movie = db.relationship('Movie', backref=db.backref('showtimes', lazy=True))
    screen = db.relationship('Screen', backref=db.backref('showtimes', lazy=True))

    @property
    def price_overrides(self):
        try:
            return json.loads(self.price_overrides_json or '{}')
        except json.JSONDecodeError:
            return {}

    @property
    def screen_label(self):
        return self.screen.name if self.screen else '—'

    @property
    def layout(self):
        return self.screen.layout if self.screen else {}

    # ---- availability -------------------------------------------------
    def booked_seat_ids(self):
        return {b.seat_id for b in BookedSeat.query.filter_by(showtime_id=self.id).all()}

    def held_seat_ids(self, exclude_token=None):
        now = datetime.utcnow()
        held = set()
        q = SeatLock.query.filter(SeatLock.showtime_id == self.id,
                                  SeatLock.expires_at > now)
        for lk in q.all():
            if exclude_token and lk.token == exclude_token:
                continue
            held.update(lk.seat_list)
        return held

    @property
    def seats_left(self):
        taken = self.booked_seat_ids() | self.held_seat_ids()
        return max(0, sl.count_seats(self.layout) - len(taken))

    @property
    def is_past(self):
        return self.show_date < date.today()


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(20), unique=True, nullable=False,
                          default=lambda: 'CW' + secrets.token_hex(4).upper())
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    seats = db.Column(db.String(200), nullable=False)
    seat_meta_json = db.Column(db.Text, default='[]')

    ticket_amount = db.Column(db.Float, default=0)     # seat prices only
    convenience_fee = db.Column(db.Float, default=0)
    gst = db.Column(db.Float, default=0)
    total_amount = db.Column(db.Float, nullable=False, default=0)   # charged amount

    # PENDING -> PAID | FAILED | CANCELLED | EXPIRED
    status = db.Column(db.String(20), default='PENDING', nullable=False)
    lock_token = db.Column(db.String(40), nullable=True)
    booked_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime,
                           default=lambda: datetime.utcnow() + timedelta(minutes=SEAT_LOCK_MINUTES))

    user = db.relationship('User', backref=db.backref('bookings', lazy=True))
    showtime = db.relationship('Showtime', backref=db.backref('bookings', lazy=True))
    payment = db.relationship('Payment', backref='booking', uselist=False,
                              cascade='all, delete-orphan')

    @property
    def seat_list(self):
        return [s for s in (self.seats or '').split(',') if s]

    @property
    def seat_meta(self):
        try:
            return json.loads(self.seat_meta_json or '[]')
        except json.JSONDecodeError:
            return []

    @property
    def seconds_left(self):
        return max(0, int((self.expires_at - datetime.utcnow()).total_seconds()))

    @property
    def is_expired(self):
        return self.status == 'PENDING' and self.expires_at < datetime.utcnow()


class BookedSeat(db.Model):
    """Confirmed seats only. The unique constraint is our double-booking guard."""
    id = db.Column(db.Integer, primary_key=True)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    seat_id = db.Column(db.String(10), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('showtime_id', 'seat_id', name='uq_showtime_seat'),
    )


class SeatLock(db.Model):
    """Temporary hold so two users cannot pay for the same seat."""
    id = db.Column(db.Integer, primary_key=True)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    token = db.Column(db.String(40), unique=True, nullable=False,
                      default=lambda: secrets.token_hex(16))
    seats = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime,
                           default=lambda: datetime.utcnow() + timedelta(minutes=SEAT_LOCK_MINUTES))

    @property
    def seat_list(self):
        return [s for s in (self.seats or '').split(',') if s]


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    gateway = db.Column(db.String(30), default='mock')      # razorpay | mock | wallet
    order_id = db.Column(db.String(80), nullable=True)
    payment_id = db.Column(db.String(80), nullable=True)
    signature = db.Column(db.String(200), nullable=True)
    method = db.Column(db.String(40), nullable=True)        # upi / card / netbanking / wallet
    amount = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(10), default='INR')
    status = db.Column(db.String(20), default='CREATED')    # CREATED|CAPTURED|FAILED|REFUNDED
    error_message = db.Column(db.String(300), nullable=True)
    raw_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Wallet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    balance = db.Column(db.Float, default=0)

    user = db.relationship('User', backref=db.backref('wallet', uselist=False))


class WalletTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey('wallet.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(20), nullable=False)   # RECHARGE / PAYMENT / REFUND
    description = db.Column(db.String(200), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    wallet = db.relationship('Wallet', backref=db.backref('transactions', lazy=True))


class RechargeRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='PENDING')   # PENDING/APPROVED/REJECTED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('recharge_requests', lazy=True))


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ====================== HELPERS ======================

def is_valid_email(email):
    return re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email) is not None


def admin_required():
    """Returns a redirect response if the user is not an admin, else None."""
    if not current_user.is_authenticated or not current_user.is_admin:
        flash("Access denied")
        return redirect(url_for('home'))
    return None


def create_wallet(user, balance=WELCOME_WALLET_BALANCE):
    """New wallet with the signup bonus already credited."""
    wallet = Wallet(user_id=user.id, balance=balance)
    db.session.add(wallet)
    db.session.commit()
    if balance:
        db.session.add(WalletTransaction(wallet_id=wallet.id, amount=balance,
                                         type='RECHARGE',
                                         description='Welcome bonus'))
        db.session.commit()
    return wallet


def get_wallet(user):
    wallet = Wallet.query.filter_by(user_id=user.id).first()
    if not wallet:
        wallet = create_wallet(user)
    return wallet


def purge_expired_holds():
    """Release stale locks and expire unpaid bookings. Cheap, safe to call often."""
    now = datetime.utcnow()
    stale = SeatLock.query.filter(SeatLock.expires_at <= now).all()
    for lk in stale:
        db.session.delete(lk)

    dead = Booking.query.filter(Booking.status == 'PENDING',
                                Booking.expires_at <= now).all()
    for b in dead:
        b.status = 'EXPIRED'
    if stale or dead:
        db.session.commit()


def price_seats(showtime, seat_ids):
    """Return (ticket_total, [{'id','class','price'}...]) using the screen layout."""
    layout = showtime.layout
    prices = sl.seat_price_map(layout, showtime.price_overrides)
    classes = sl.seat_class_map(layout)
    meta = [{'id': s, 'class': classes.get(s, 'Standard'),
             'price': float(prices.get(s, 0))} for s in seat_ids]
    return round(sum(m['price'] for m in meta), 2), meta


def release_booking(booking, status='CANCELLED'):
    """Free the held seats for a booking that will not be paid."""
    if booking.lock_token:
        lock = SeatLock.query.filter_by(token=booking.lock_token).first()
        if lock:
            db.session.delete(lock)
    booking.status = status
    db.session.commit()


def commit_seats(booking):
    """
    Final, atomic step after a successful payment: write the seats into
    BookedSeat. The unique(showtime_id, seat_id) constraint means that if
    someone beat us to a seat, this raises and we can refund instead of
    double-selling.
    """
    for seat in booking.seat_list:
        db.session.add(BookedSeat(showtime_id=booking.showtime_id,
                                  seat_id=seat, booking_id=booking.id))
    db.session.flush()


def finalise_paid_booking(booking, payment):
    """Commit seats, mark paid, drop the lock. Returns (ok, message)."""
    try:
        commit_seats(booking)
        booking.status = 'PAID'
        booking.paid_at = datetime.utcnow()
        payment.status = 'CAPTURED'
        if booking.lock_token:
            lock = SeatLock.query.filter_by(token=booking.lock_token).first()
            if lock:
                db.session.delete(lock)
        db.session.commit()
        return True, "Payment successful"
    except IntegrityError:
        db.session.rollback()
        booking.status = 'FAILED'
        payment.status = 'REFUNDED'
        payment.error_message = 'Seat taken before capture - amount refunded'
        # money back: wallet payments are returned instantly
        if payment.method == 'wallet':
            wallet = get_wallet(booking.user)
            wallet.balance += booking.total_amount
            db.session.add(WalletTransaction(wallet_id=wallet.id,
                                             amount=booking.total_amount,
                                             type='REFUND',
                                             description=f'Refund for {booking.reference}'))
        db.session.commit()
        return False, ("Someone completed payment for one of those seats first. "
                       "Your money has been refunded - please pick different seats.")


@app.context_processor
def inject_globals():
    """Available in every template."""
    wallet_balance = None
    if current_user.is_authenticated:
        w = Wallet.query.filter_by(user_id=current_user.id).first()
        wallet_balance = w.balance if w else 0
    return {'wallet_balance': wallet_balance,
            'gateway_live': payments.is_live_gateway(),
            'today': date.today()}


# ====================== PUBLIC ROUTES ======================

@app.route('/')
def home():
    movies = Movie.query.order_by(Movie.id.desc()).all()
    return render_template('index.html', movies=movies)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            get_wallet(user)
            return redirect(request.args.get('next') or url_for('home'))
        flash('Invalid username or password')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form['password']

        if not username or not password:
            flash("Username and password are required.")
            return redirect(url_for('register'))
        if email and not is_valid_email(email):
            flash("Please enter a valid email address.")
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash('Username already exists!')
            return redirect(url_for('register'))
        if email and User.query.filter_by(email=email).first():
            flash('An account with this email already exists!')
            return redirect(url_for('register'))

        user = User(username=username, email=email or None, phone=phone or None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        create_wallet(user)

        flash(f'Registered successfully! ₹{WELCOME_WALLET_BALANCE:.0f} welcome '
              f'balance added to your wallet. Please login.')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


@app.route('/movie/<int:movie_id>')
def movie_detail(movie_id):
    purge_expired_holds()
    movie = Movie.query.get_or_404(movie_id)
    shows = (Showtime.query.filter_by(movie_id=movie_id)
             .order_by(Showtime.show_date, Showtime.id).all())

    # group by date -> theatre so it reads like a real booking page
    grouped = {}
    for s in shows:
        grouped.setdefault(s.show_date, {}).setdefault(s.theater, []).append(s)

    return render_template('movie.html', movie=movie, showtimes=shows,
                           grouped=grouped)


# ====================== SEAT SELECTION ======================

@app.route('/book/<int:showtime_id>', methods=['GET', 'POST'])
@login_required
def book(showtime_id):
    purge_expired_holds()
    showtime = Showtime.query.get_or_404(showtime_id)
    movie = showtime.movie

    if not showtime.screen:
        flash("This showtime has no screen assigned. Ask an admin to fix it.")
        return redirect(url_for('movie_detail', movie_id=movie.id))

    layout = showtime.layout
    booked = showtime.booked_seat_ids()
    held = showtime.held_seat_ids()

    if request.method == 'POST':
        raw = request.form.get('selected_seats', '')
        seats_list = [s.strip().upper() for s in raw.split(',') if s.strip()]

        ok, msg = sl.validate_seats(layout, seats_list)
        if not ok:
            flash(msg)
            return redirect(url_for('book', showtime_id=showtime_id))

        clash = sorted(set(seats_list) & (booked | held))
        if clash:
            flash(f"Seat(s) {', '.join(clash)} were just taken. Please choose again.")
            return redirect(url_for('book', showtime_id=showtime_id))

        # ---- hold the seats, then create a PENDING booking ----
        ticket_amount, meta = price_seats(showtime, seats_list)
        amounts = payments.compute_amounts(ticket_amount, len(seats_list))

        lock = SeatLock(showtime_id=showtime.id, user_id=current_user.id,
                        seats=",".join(seats_list))
        db.session.add(lock)
        db.session.flush()

        booking = Booking(user_id=current_user.id, showtime_id=showtime.id,
                          seats=",".join(seats_list),
                          seat_meta_json=json.dumps(meta),
                          ticket_amount=amounts['ticket_amount'],
                          convenience_fee=amounts['convenience_fee'],
                          gst=amounts['gst'],
                          total_amount=amounts['total'],
                          status='PENDING', lock_token=lock.token,
                          expires_at=lock.expires_at)
        db.session.add(booking)
        db.session.commit()

        return redirect(url_for('checkout', reference=booking.reference))

    grid = sl.build_layout(layout, booked=booked, held=held,
                           price_overrides=showtime.price_overrides)
    return render_template('book.html', movie=movie, showtime=showtime,
                           screen=showtime.screen, grid=grid,
                           max_seats=sl.MAX_SEATS_PER_BOOKING,
                           stats=sl.availability(layout, booked | held))


@app.route('/api/showtime/<int:showtime_id>/availability')
@login_required
def seat_availability(showtime_id):
    """Polled by the seat page so seats grey out live while you are choosing."""
    purge_expired_holds()
    showtime = Showtime.query.get_or_404(showtime_id)
    return jsonify({'booked': sorted(showtime.booked_seat_ids()),
                    'held': sorted(showtime.held_seat_ids())})


# ====================== CHECKOUT & PAYMENT ======================

def _load_pending(reference):
    booking = Booking.query.filter_by(reference=reference).first_or_404()
    if booking.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    return booking


@app.route('/checkout/<reference>')
@login_required
def checkout(reference):
    booking = _load_pending(reference)

    if booking.status == 'PAID':
        return redirect(url_for('ticket', reference=reference))
    if booking.is_expired:
        release_booking(booking, 'EXPIRED')
        flash("Your seat hold expired. Please select seats again.")
        return redirect(url_for('book', showtime_id=booking.showtime_id))
    if booking.status not in ('PENDING',):
        flash("This booking is no longer payable.")
        return redirect(url_for('dashboard'))

    wallet = get_wallet(current_user)
    return render_template('checkout.html', booking=booking,
                           showtime=booking.showtime,
                           movie=booking.showtime.movie,
                           wallet=wallet,
                           can_use_wallet=wallet.balance >= booking.total_amount,
                           gateway=payments.gateway_name())


@app.route('/pay/wallet/<reference>', methods=['POST'])
@login_required
def pay_with_wallet(reference):
    booking = _load_pending(reference)
    if booking.status != 'PENDING' or booking.is_expired:
        flash("This booking can no longer be paid.")
        return redirect(url_for('dashboard'))

    wallet = get_wallet(current_user)
    if wallet.balance < booking.total_amount:
        flash("Not enough wallet balance. Recharge or pay by UPI / card.")
        return redirect(url_for('checkout', reference=reference))

    wallet.balance = round(wallet.balance - booking.total_amount, 2)
    db.session.add(WalletTransaction(wallet_id=wallet.id,
                                     amount=booking.total_amount,
                                     type='PAYMENT',
                                     description=f'Tickets {booking.reference}'))
    payment = Payment(booking_id=booking.id, gateway='wallet', method='wallet',
                      amount=booking.total_amount, status='CREATED',
                      order_id=f'wallet_{booking.reference}',
                      payment_id=f'wal_{secrets.token_hex(6)}')
    db.session.add(payment)
    db.session.commit()

    ok, msg = finalise_paid_booking(booking, payment)
    flash(msg)
    return redirect(url_for('ticket', reference=reference) if ok
                    else url_for('book', showtime_id=booking.showtime_id))


@app.route('/pay/gateway/<reference>', methods=['POST'])
@login_required
def pay_gateway(reference):
    """Creates the Razorpay (or mock) order and opens the payment page."""
    booking = _load_pending(reference)
    if booking.status != 'PENDING' or booking.is_expired:
        flash("This booking can no longer be paid.")
        return redirect(url_for('dashboard'))

    method = request.form.get('method', 'upi')
    order = payments.create_order(
        booking.total_amount,
        receipt=booking.reference,
        notes={'reference': booking.reference,
               'movie': booking.showtime.movie.title,
               'seats': booking.seats})

    payment = booking.payment or Payment(booking_id=booking.id)
    payment.gateway = order['gateway']
    payment.order_id = order['order_id']
    payment.amount = booking.total_amount
    payment.method = method
    payment.status = 'CREATED'
    payment.raw_response = order.get('raw')
    db.session.add(payment)
    db.session.commit()

    template = 'pay_razorpay.html' if order['gateway'] == 'razorpay' else 'pay_mock.html'
    return render_template(template, booking=booking, order=order,
                           movie=booking.showtime.movie,
                           showtime=booking.showtime, method=method,
                           user=current_user)


@app.route('/pay/callback', methods=['POST'])
@login_required
def payment_callback():
    """
    Where the gateway hands control back. Razorpay Checkout posts
    razorpay_order_id / razorpay_payment_id / razorpay_signature here;
    the mock page posts the same three fields.
    """
    reference = request.form.get('reference', '')
    order_id = request.form.get('razorpay_order_id', '')
    payment_id = request.form.get('razorpay_payment_id', '')
    signature = request.form.get('razorpay_signature', '')
    failed = request.form.get('failed') == '1'
    error_msg = request.form.get('error_message', 'Payment failed at the gateway.')

    booking = _load_pending(reference)
    payment = booking.payment
    if not payment:
        flash("No payment was started for this booking.")
        return redirect(url_for('checkout', reference=reference))

    if failed:
        payment.status = 'FAILED'
        payment.error_message = error_msg[:300]
        db.session.commit()
        release_booking(booking, 'FAILED')
        flash(f"{error_msg} Your seats have been released.")
        return redirect(url_for('book', showtime_id=booking.showtime_id))

    # signature check - this is what makes the success real
    if not payments.verify_signature(order_id, payment_id, signature):
        payment.status = 'FAILED'
        payment.error_message = 'Signature verification failed'
        db.session.commit()
        release_booking(booking, 'FAILED')
        flash("Payment could not be verified. Nothing was charged.")
        return redirect(url_for('book', showtime_id=booking.showtime_id))

    if booking.status == 'PAID':                     # double submit guard
        return redirect(url_for('ticket', reference=reference))
    if booking.is_expired:
        release_booking(booking, 'EXPIRED')
        flash("Your hold expired before payment completed. Refund will be processed.")
        return redirect(url_for('book', showtime_id=booking.showtime_id))

    payment.payment_id = payment_id
    payment.signature = signature
    db.session.commit()

    ok, msg = finalise_paid_booking(booking, payment)
    flash(msg)
    return redirect(url_for('ticket', reference=reference) if ok
                    else url_for('book', showtime_id=booking.showtime_id))


@app.route('/pay/simulate/<reference>', methods=['POST'])
@login_required
def simulate(reference):
    """Sandbox 'Pay Now' / 'Simulate failure' buttons on the mock gateway page."""
    booking = _load_pending(reference)
    payment = booking.payment
    if not payment or not payment.order_id:
        flash("Start the payment again.")
        return redirect(url_for('checkout', reference=reference))

    succeed = request.form.get('outcome', 'success') == 'success'
    result = payments.simulate_payment(payment.order_id,
                                       method=payment.method or 'upi',
                                       succeed=succeed)
    if not result['ok']:
        payment.status = 'FAILED'
        payment.error_message = result['error']
        db.session.commit()
        release_booking(booking, 'FAILED')
        flash(f"{result['error']} Your seats have been released.")
        return redirect(url_for('book', showtime_id=booking.showtime_id))

    payment.payment_id = result['payment_id']
    payment.signature = result['signature']
    db.session.commit()

    ok, msg = finalise_paid_booking(booking, payment)
    flash(msg)
    return redirect(url_for('ticket', reference=reference) if ok
                    else url_for('book', showtime_id=booking.showtime_id))


@app.route('/pay/webhook', methods=['POST'])
def payment_webhook():
    """
    Razorpay webhook (payment.captured). Set RAZORPAY_WEBHOOK_SECRET to enable.
    Makes the booking survive the user closing the tab mid-payment.
    """
    signature = request.headers.get('X-Razorpay-Signature', '')
    if not payments.verify_webhook(request.get_data(), signature):
        return jsonify({'status': 'invalid signature'}), 400

    event = request.get_json(silent=True) or {}
    entity = (event.get('payload', {}).get('payment', {}).get('entity', {}))
    order_id = entity.get('order_id')
    payment = Payment.query.filter_by(order_id=order_id).first()
    if payment and payment.booking.status == 'PENDING':
        payment.payment_id = entity.get('id')
        payment.method = entity.get('method', payment.method)
        finalise_paid_booking(payment.booking, payment)
    return jsonify({'status': 'ok'})


@app.route('/booking/<reference>/cancel', methods=['POST'])
@login_required
def cancel_booking(reference):
    booking = _load_pending(reference)
    if booking.status == 'PENDING':
        release_booking(booking, 'CANCELLED')
        flash("Booking cancelled and seats released.")
    return redirect(url_for('dashboard'))


@app.route('/ticket/<reference>')
@login_required
def ticket(reference):
    booking = Booking.query.filter_by(reference=reference).first_or_404()
    if booking.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    return render_template('ticket.html', booking=booking,
                           showtime=booking.showtime,
                           movie=booking.showtime.movie,
                           payment=booking.payment)


@app.route('/ticket/<reference>/qr.png')
@login_required
def ticket_qr(reference):
    """QR code printed on the e-ticket: scanned at the gate to verify the booking."""
    booking = Booking.query.filter_by(reference=reference).first_or_404()
    if booking.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    payload = (f"CINEWAVE|{booking.reference}|{booking.showtime.movie.title}|"
               f"{booking.showtime.theater}|{booking.showtime.show_date}|"
               f"{booking.showtime.show_time}|{booking.seats}")
    try:
        import io
        import qrcode
        img = qrcode.make(payload)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue(), 200, {'Content-Type': 'image/png',
                                     'Cache-Control': 'no-store'}
    except ImportError:
        # qrcode not installed - fall back to a 1x1 transparent pixel
        import base64
        pixel = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8'
            '/58BAwAI/AL+4d1cAAAAAElFTkSuQmCC')
        return pixel, 200, {'Content-Type': 'image/png'}


# ====================== WALLET ======================

@app.route('/wallet')
@login_required
def wallet_page():
    wallet = get_wallet(current_user)
    txns = (WalletTransaction.query.filter_by(wallet_id=wallet.id)
            .order_by(WalletTransaction.timestamp.desc()).limit(20).all())
    reqs = (RechargeRequest.query.filter_by(user_id=current_user.id)
            .order_by(RechargeRequest.created_at.desc()).limit(10).all())
    return render_template('wallet.html', wallet=wallet, txns=txns, requests=reqs)


@app.route('/wallet/recharge', methods=['POST'])
@login_required
def wallet_recharge():
    try:
        amount = float(request.form['amount'])
    except (KeyError, ValueError):
        flash("Enter a valid amount.")
        return redirect(url_for('wallet_page'))
    if amount <= 0 or amount > 10000:
        flash("Recharge amount must be between ₹1 and ₹10,000.")
        return redirect(url_for('wallet_page'))

    db.session.add(RechargeRequest(user_id=current_user.id, amount=amount))
    db.session.commit()
    flash(f"Recharge request for ₹{amount:.0f} submitted. An admin will approve it shortly.")
    return redirect(url_for('wallet_page'))


# ====================== USER DASHBOARD ======================

@app.route('/dashboard')
@login_required
def dashboard():
    purge_expired_holds()
    bookings = (Booking.query.filter_by(user_id=current_user.id)
                .order_by(Booking.booked_at.desc()).all())
    return render_template('dashboard.html', bookings=bookings)


# ====================== ADMIN ROUTES ======================

@app.route('/admin')
@login_required
def admin():
    guard = admin_required()
    if guard:
        return guard
    movies = Movie.query.all()
    showtimes = Showtime.query.order_by(Showtime.show_date.desc()).all()
    theaters = Theater.query.all()
    screens = Screen.query.all()
    pending_recharges = RechargeRequest.query.filter_by(status='PENDING').count()
    revenue = db.session.query(db.func.sum(Booking.total_amount)) \
                        .filter(Booking.status == 'PAID').scalar() or 0
    return render_template('admin.html', movies=movies, showtimes=showtimes,
                           theaters=theaters, screens=screens,
                           pending_recharges=pending_recharges, revenue=revenue,
                           paid_count=Booking.query.filter_by(status='PAID').count())


@app.route('/admin/add_movie', methods=['GET', 'POST'])
@login_required
def add_movie():
    guard = admin_required()
    if guard:
        return guard
    if request.method == 'POST':
        movie = Movie(title=request.form['title'],
                      description=request.form['description'],
                      duration=int(request.form['duration']),
                      poster=request.form.get('poster', '').strip() or None,
                      language=request.form.get('language', 'Telugu'),
                      certificate=request.form.get('certificate', 'U/A'))
        db.session.add(movie)
        db.session.commit()
        flash("Movie added successfully!")
        return redirect(url_for('admin'))
    return render_template('add_movie.html')


@app.route('/admin/import_movie', methods=['GET', 'POST'])
@login_required
def import_movie():
    guard = admin_required()
    if guard:
        return guard
    results, query = [], ""
    if request.method == 'POST':
        query = request.form.get('query', '').strip()
        if query:
            try:
                res = requests.get(f"{TMDB_BASE_URL}/search/movie",
                                   params={'api_key': TMDB_API_KEY, 'query': query},
                                   timeout=10).json()
                for item in res.get('results', [])[:8]:
                    poster_path = item.get('poster_path')
                    release_date = item.get('release_date', '')
                    results.append({'tmdb_id': item['id'], 'title': item['title'],
                                    'overview': item.get('overview', ''),
                                    'poster_url': f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else None,
                                    'year': release_date[:4] if release_date else ''})
            except Exception as e:
                flash(f"Error fetching from TMDb: {e}")
    return render_template('import_movie.html', results=results, query=query)


@app.route('/admin/import_movie/add/<int:tmdb_id>', methods=['POST'])
@login_required
def import_movie_add(tmdb_id):
    guard = admin_required()
    if guard:
        return guard
    try:
        res = requests.get(f"{TMDB_BASE_URL}/movie/{tmdb_id}",
                           params={'api_key': TMDB_API_KEY}, timeout=10).json()
        poster_path = res.get('poster_path')
        movie = Movie(title=res.get('title', 'Untitled'),
                      description=res.get('overview', 'No overview available.'),
                      duration=res.get('runtime') or 120,
                      poster=f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else None,
                      language=(res.get('original_language') or 'te').upper())
        db.session.add(movie)
        db.session.commit()
        flash(f'Imported "{movie.title}" successfully!')
    except Exception as e:
        flash(f"Failed to import movie: {e}")
    return redirect(url_for('admin'))


@app.route('/admin/add_theater', methods=['GET', 'POST'])
@login_required
def add_theater():
    guard = admin_required()
    if guard:
        return guard
    if request.method == 'POST':
        name = request.form['name'].strip()
        if not name:
            flash("Theater name is required")
            return redirect(url_for('add_theater'))
        if Theater.query.filter_by(name=name).first():
            flash(f'A theater named "{name}" already exists')
            return redirect(url_for('add_theater'))
        db.session.add(Theater(name=name,
                               location=request.form.get('location', '').strip(),
                               city=request.form.get('city', 'Visakhapatnam').strip(),
                               address=request.form.get('address', '').strip()))
        db.session.commit()
        flash(f'Theater "{name}" added. Now add its screens and seat layout.')
        return redirect(url_for('screens'))
    return render_template('add_theater.html')


@app.route('/admin/seed_vizag', methods=['POST'])
@login_required
def seed_vizag():
    guard = admin_required()
    if guard:
        return guard
    t, s = seed_vizag_theaters(db, Theater, Screen, verbose=False)
    flash(f"Loaded Vizag theatres: +{t} theatres, +{s} screens with real seat layouts.")
    return redirect(url_for('screens'))


@app.route('/admin/screens')
@login_required
def screens():
    guard = admin_required()
    if guard:
        return guard
    return render_template('screens.html', theaters=Theater.query.all())


@app.route('/admin/add_screen', methods=['GET', 'POST'])
@login_required
def add_screen():
    guard = admin_required()
    if guard:
        return guard
    theaters = Theater.query.all()
    if request.method == 'POST':
        theater_id = int(request.form['theater_id'])
        name = request.form['name'].strip()
        raw = request.form.get('layout_json', '').strip() or '{"classes": []}'
        try:
            layout = json.loads(raw)
        except json.JSONDecodeError as e:
            flash(f"Layout JSON is invalid: {e}")
            return redirect(url_for('add_screen'))
        screen = Screen(theater_id=theater_id, name=name,
                        screen_type=request.form.get('screen_type', '2D'))
        screen.layout = layout
        db.session.add(screen)
        db.session.commit()
        flash(f"Screen '{name}' added with {screen.total_seats} seats.")
        return redirect(url_for('edit_layout', screen_id=screen.id))
    return render_template('add_screen.html', theaters=theaters,
                           sample=json.dumps(SAMPLE_LAYOUT, indent=2))


@app.route('/admin/screen/<int:screen_id>/layout', methods=['GET', 'POST'])
@login_required
def edit_layout(screen_id):
    """Edit a screen's seating arrangement and preview it exactly as users see it."""
    guard = admin_required()
    if guard:
        return guard
    screen = Screen.query.get_or_404(screen_id)

    if request.method == 'POST':
        try:
            layout = json.loads(request.form['layout_json'])
        except json.JSONDecodeError as e:
            flash(f"Layout JSON is invalid: {e}")
            return redirect(url_for('edit_layout', screen_id=screen_id))
        screen.layout = layout
        db.session.commit()
        flash(f"Layout saved — {screen.total_seats} seats.")
        return redirect(url_for('edit_layout', screen_id=screen_id))

    grid = sl.build_layout(screen.layout)
    return render_template('edit_layout.html', screen=screen, grid=grid,
                           layout_json=json.dumps(screen.layout, indent=2))


@app.route('/admin/add_showtime', methods=['GET', 'POST'])
@login_required
def add_showtime():
    guard = admin_required()
    if guard:
        return guard
    movies = Movie.query.all()
    theaters = Theater.query.all()
    screens_list = Screen.query.all()

    if request.method == 'POST':
        screen = Screen.query.get_or_404(int(request.form['screen_id']))
        overrides = {}
        for cls in screen.layout.get('classes', []):
            val = request.form.get(f"price_{cls['code']}", '').strip()
            if val:
                try:
                    overrides[cls['code']] = float(val)
                except ValueError:
                    pass

        show = Showtime(movie_id=int(request.form['movie_id']),
                        screen_id=screen.id,
                        theater=screen.theater.name,
                        show_date=datetime.strptime(request.form['show_date'], '%Y-%m-%d').date(),
                        show_time=request.form['show_time'],
                        price_overrides_json=json.dumps(overrides))
        db.session.add(show)
        db.session.commit()
        flash("Showtime added successfully!")
        return redirect(url_for('admin'))

    return render_template('add_showtime.html', movies=movies, theaters=theaters,
                           screens=screens_list)


@app.route('/api/screen/<int:screen_id>/classes')
@login_required
def screen_classes(screen_id):
    """Used by add_showtime.html to show per-class price boxes for a screen."""
    screen = Screen.query.get_or_404(screen_id)
    return jsonify({'screen': screen.name, 'seats': screen.total_seats,
                    'classes': [{'code': c.get('code'), 'name': c.get('name'),
                                 'price': c.get('price')}
                                for c in screen.layout.get('classes', [])]})


@app.route('/admin/recharges')
@login_required
def admin_recharges():
    guard = admin_required()
    if guard:
        return guard
    reqs = RechargeRequest.query.order_by(RechargeRequest.created_at.desc()).all()
    return render_template('admin_recharges.html', requests=reqs)


@app.route('/admin/recharges/<int:req_id>/<action>', methods=['POST'])
@login_required
def handle_recharge(req_id, action):
    guard = admin_required()
    if guard:
        return guard
    req = RechargeRequest.query.get_or_404(req_id)
    if req.status != 'PENDING':
        flash("Already processed.")
        return redirect(url_for('admin_recharges'))

    if action == 'approve':
        wallet = get_wallet(req.user)
        wallet.balance = round(wallet.balance + req.amount, 2)
        db.session.add(WalletTransaction(wallet_id=wallet.id, amount=req.amount,
                                         type='RECHARGE',
                                         description='Admin approved recharge'))
        req.status = 'APPROVED'
        flash(f"₹{req.amount:.0f} credited to {req.user.username}.")
    elif action == 'reject':
        req.status = 'REJECTED'
        flash("Recharge request rejected.")
    db.session.commit()
    return redirect(url_for('admin_recharges'))


@app.route('/admin/bookings')
@login_required
def admin_bookings():
    guard = admin_required()
    if guard:
        return guard
    bookings = Booking.query.order_by(Booking.booked_at.desc()).limit(100).all()
    return render_template('admin_bookings.html', bookings=bookings)


# ====================== INITIALIZATION ======================

SAMPLE_LAYOUT = {
    "screen_label": "Screen 1",
    "classes": [
        {"code": "RECLINER", "name": "Recliner", "price": 320,
         "rows": [{"label": "A", "count": 10, "aisles_after": [5], "blocked": []},
                  {"label": "B", "count": 10, "aisles_after": [5], "blocked": []}]},
        {"code": "EXECUTIVE", "name": "Executive", "price": 220,
         "rows": [{"label": "C", "count": 16, "aisles_after": [4, 12], "blocked": []},
                  {"label": "D", "count": 16, "aisles_after": [4, 12], "blocked": []}]},
        {"code": "NORMAL", "name": "Normal", "price": 150,
         "rows": [{"label": "E", "count": 18, "aisles_after": [4, 14], "blocked": []},
                  {"label": "F", "count": 18, "aisles_after": [4, 14], "blocked": []}]},
    ],
}


def auto_migrate():
    """
    Adds any newly introduced column to an existing SQLite file so your old
    vizag_movies.db keeps working instead of throwing OperationalError.
    """
    insp = inspect(db.engine)
    wanted = {
        'user': [('phone', 'VARCHAR(15)')],
        'movie': [('language', "VARCHAR(50)"), ('certificate', "VARCHAR(10)")],
        'theater': [('city', "VARCHAR(80)"), ('address', "VARCHAR(400)")],
        'showtime': [('screen_id', 'INTEGER'), ('price_overrides_json', 'TEXT')],
        'booking': [('reference', 'VARCHAR(20)'), ('seat_meta_json', 'TEXT'),
                    ('ticket_amount', 'FLOAT'), ('convenience_fee', 'FLOAT'),
                    ('gst', 'FLOAT'), ('status', "VARCHAR(20)"),
                    ('lock_token', 'VARCHAR(40)'), ('paid_at', 'DATETIME'),
                    ('expires_at', 'DATETIME')],
        'booked_seat': [('booking_id', 'INTEGER')],
    }
    for table, cols in wanted.items():
        if table not in insp.get_table_names():
            continue
        existing = {c['name'] for c in insp.get_columns(table)}
        for col, coltype in cols:
            if col not in existing:
                db.session.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {coltype}'))
                print(f"  migrated: {table}.{col}")
    db.session.commit()

    # backfill references + status for pre-existing bookings
    for b in Booking.query.filter((Booking.reference.is_(None))).all():
        b.reference = 'CW' + secrets.token_hex(4).upper()
        b.status = 'PAID'
    db.session.commit()


def init_db():
    with app.app_context():
        db.create_all()
        auto_migrate()

        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            admin_user = User(username='admin', email='admin@cinewave.com', is_admin=True)
            admin_user.set_password('admin123')
            db.session.add(admin_user)
            db.session.commit()
            create_wallet(admin_user, balance=10000)
            print("Default admin created (admin / admin123)")

        # make sure every existing account has a wallet with the signup bonus
        for u in User.query.all():
            if not Wallet.query.filter_by(user_id=u.id).first():
                create_wallet(u)

        # Vizag theatres + real seat layouts
        seed_vizag_theaters(db, Theater, Screen)

        # attach a screen to any legacy showtime that has none
        for s in Showtime.query.filter(Showtime.screen_id.is_(None)).all():
            t = Theater.query.filter_by(name=s.theater).first()
            screen = (Screen.query.filter_by(theater_id=t.id).first() if t
                      else Screen.query.first())
            if screen:
                s.screen_id = screen.id
                s.theater = screen.theater.name
        db.session.commit()

        mode = "LIVE Razorpay" if payments.is_live_gateway() else "MOCK gateway (no keys set)"
        print(f"Payments: {mode}")


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
