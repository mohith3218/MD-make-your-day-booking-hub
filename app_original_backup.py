import re
from datetime import date, datetime
import requests
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
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
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'vizag-movie-booking-secret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vizag_movies.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# TMDb API Key
TMDB_API_KEY = "329d5f23baebf5312db6f28ab506ce9e"
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# ====================== MODELS ======================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
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


class Theater(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    location = db.Column(db.String(200), nullable=True)


class Showtime(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    theater = db.Column(db.String(100), nullable=False)
    show_date = db.Column(db.Date, nullable=False)
    show_time = db.Column(db.String(20), nullable=False)

    movie = db.relationship('Movie', backref=db.backref('showtimes', lazy=True))


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    seats = db.Column(db.String(200), nullable=False)
    total_amount = db.Column(db.Integer, nullable=False, default=0)
    booked_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('bookings', lazy=True))
    showtime = db.relationship('Showtime', backref=db.backref('bookings', lazy=True))


class BookedSeat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    seat_id = db.Column(db.String(10), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('showtime_id', 'seat_id', name='uq_showtime_seat'),
    )


class Wallet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    balance = db.Column(db.Integer, default=0)

    user = db.relationship('User', backref=db.backref('wallet', uselist=False))


class WalletTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey('wallet.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(20), nullable=False)  # 'RECHARGE' or 'PAYMENT'
    description = db.Column(db.String(200), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class RechargeRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='PENDING')  # PENDING, APPROVED, REJECTED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('recharge_requests', lazy=True))


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ====================== SEAT LAYOUT & PRICING ======================

SEAT_CLASSES = [
    {"name": "Recliner", "price": 320, "rows": ["A", "B"]},
    {"name": "Executive", "price": 220, "rows": ["C", "D", "E"]},
    {"name": "Normal", "price": 150, "rows": ["F", "G", "H"]}
]


def get_seat_price(seat_id):
    row = seat_id[0].upper()
    for cls in SEAT_CLASSES:
        if row in cls["rows"]:
            return cls["price"]
    return 150  # Fallback default price


def is_valid_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


# ====================== ROUTES ======================

@app.route('/')
def home():
    movies = Movie.query.all()
    return render_template('index.html', movies=movies)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form.get('email', '').strip()
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

        user = User(username=username, email=email if email else None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # Create wallet for new user
        wallet = Wallet(user_id=user.id, balance=0)
        db.session.add(wallet)
        db.session.commit()

        flash('Registered successfully! Please login.')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


@app.route('/movie/<int:movie_id>')
def movie_detail(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    showtimes = Showtime.query.filter_by(movie_id=movie_id).all()
    return render_template('movie.html', movie=movie, showtimes=showtimes)


@app.route('/book/<int:showtime_id>', methods=['GET', 'POST'])
@login_required
def book(showtime_id):
    showtime = Showtime.query.get_or_404(showtime_id)
    movie = Movie.query.get(showtime.movie_id)

    # Fetch currently booked seats for this showtime
    booked_records = BookedSeat.query.filter_by(showtime_id=showtime_id).all()
    booked_seats = [b.seat_id for b in booked_records]

    if request.method == 'POST':
        selected_seats_str = request.form.get('selected_seats', '')
        if not selected_seats_str:
            flash('Please select at least one seat.')
            return redirect(url_for('book', showtime_id=showtime_id))

        seats_list = [s.strip() for s in selected_seats_str.split(',') if s.strip()]

        # Calculate total price dynamically based on row pricing
        total_amount = sum(get_seat_price(s) for s in seats_list)

        try:
            # Atomic booking process
            for seat in seats_list:
                booked_seat = BookedSeat(showtime_id=showtime_id, seat_id=seat)
                db.session.add(booked_seat)

            booking = Booking(
                user_id=current_user.id,
                showtime_id=showtime_id,
                seats=",".join(seats_list),
                total_amount=total_amount
            )
            db.session.add(booking)
            db.session.commit()

            flash('Booking confirmed successfully!')
            return redirect(url_for('dashboard'))

        except IntegrityError:
            db.session.rollback()
            flash('One or more of your selected seats were just booked by someone else. Please select different seats.')
            return redirect(url_for('book', showtime_id=showtime_id))

    return render_template(
        'book.html',
        movie=movie,
        showtime=showtime,
        booked_seats=booked_seats,
        seat_classes=SEAT_CLASSES
    )


@app.route('/dashboard')
@login_required
def dashboard():
    user_bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booked_at.desc()).all()
    
    booking_details = []
    for b in user_bookings:
        showtime = Showtime.query.get(b.showtime_id)
        movie = Movie.query.get(showtime.movie_id) if showtime else None
        booking_details.append({
            'movie': movie.title if movie else 'Unknown Movie',
            'theater': showtime.theater if showtime else 'Unknown Theater',
            'date': showtime.show_date if showtime else '',
            'time': showtime.show_time if showtime else '',
            'seats': b.seats,
            'amount': b.total_amount,
            'booked_at': b.booked_at
        })

    return render_template('dashboard.html', bookings=booking_details)


# ====================== ADMIN ROUTES ======================

@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        flash("Access denied")
        return redirect(url_for('home'))

    movies = Movie.query.all()
    showtimes = Showtime.query.all()
    theaters = Theater.query.all()
    return render_template('admin.html', movies=movies, showtimes=showtimes, theaters=theaters)


@app.route('/admin/add_movie', methods=['GET', 'POST'])
@login_required
def add_movie():
    if not current_user.is_admin:
        flash("Access denied")
        return redirect(url_for('home'))

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        duration = int(request.form['duration'])
        poster = request.form.get('poster', '').strip() or None

        movie = Movie(title=title, description=description, duration=duration, poster=poster)
        db.session.add(movie)
        db.session.commit()

        flash("Movie added successfully!")
        return redirect(url_for('admin'))

    return render_template('add_movie.html')


@app.route('/admin/import_movie', methods=['GET', 'POST'])
@login_required
def import_movie():
    if not current_user.is_admin:
        flash("Access denied")
        return redirect(url_for('home'))

    results = []
    query = ""

    if request.method == 'POST':
        query = request.form.get('query', '').strip()
        if query:
            url = f"{TMDB_BASE_URL}/search/movie"
            params = {'api_key': TMDB_API_KEY, 'query': query}
            try:
                res = requests.get(url, params=params).json()
                for item in res.get('results', [])[:8]:
                    poster_path = item.get('poster_path')
                    poster_url = f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else None
                    release_date = item.get('release_date', '')
                    year = release_date[:4] if release_date else ''

                    results.append({
                        'tmdb_id': item['id'],
                        'title': item['title'],
                        'overview': item.get('overview', ''),
                        'poster_url': poster_url,
                        'year': year
                    })
            except Exception as e:
                flash(f"Error fetching from TMDb: {e}")

    return render_template('import_movie.html', results=results, query=query)


@app.route('/admin/import_movie/add/<int:tmdb_id>', methods=['POST'])
@login_required
def import_movie_add(tmdb_id):
    if not current_user.is_admin:
        flash("Access denied")
        return redirect(url_for('home'))

    url = f"{TMDB_BASE_URL}/movie/{tmdb_id}"
    params = {'api_key': TMDB_API_KEY}
    try:
        res = requests.get(url, params=params).json()
        title = res.get('title', 'Untitled')
        description = res.get('overview', 'No overview available.')
        duration = res.get('runtime') or 120
        poster_path = res.get('poster_path')
        poster = f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else None

        movie = Movie(title=title, description=description, duration=duration, poster=poster)
        db.session.add(movie)
        db.session.commit()

        flash(f'Imported "{title}" successfully!')
    except Exception as e:
        flash(f"Failed to import movie: {e}")

    return redirect(url_for('admin'))


@app.route('/admin/add_showtime', methods=['GET', 'POST'])
@login_required
def add_showtime():
    if not current_user.is_admin:
        flash("Access denied")
        return redirect(url_for('home'))

    movies = Movie.query.all()
    theaters = Theater.query.all()

    if request.method == 'POST':
        show = Showtime(
            movie_id=int(request.form['movie_id']),
            theater=request.form['theater'],
            show_date=datetime.strptime(request.form['show_date'], '%Y-%m-%d').date(),
            show_time=request.form['show_time']
        )
        db.session.add(show)
        db.session.commit()
        flash("Showtime added successfully!")
        return redirect(url_for('admin'))

    return render_template('add_showtime.html', movies=movies, theaters=theaters)


@app.route('/admin/add_theater', methods=['GET', 'POST'])
@login_required
def add_theater():
    if not current_user.is_admin:
        flash("Access denied")
        return redirect(url_for('home'))

    if request.method == 'POST':
        name = request.form['name'].strip()
        location = request.form.get('location', '').strip()

        if not name:
            flash("Theater name is required")
            return redirect(url_for('add_theater'))

        if Theater.query.filter_by(name=name).first():
            flash(f'A theater named "{name}" already exists')
            return redirect(url_for('add_theater'))

        theater = Theater(name=name, location=location)
        db.session.add(theater)
        db.session.commit()

        flash(f'Theater "{name}" added successfully!')
        return redirect(url_for('admin'))

    return render_template('add_theater.html')


# ====================== INITIALIZATION ======================

def init_db():
    with app.app_context():
        db.create_all()

        # Create default admin account if not existing
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            admin_user = User(username='admin', email='admin@cinewave.com', is_admin=True)
            admin_user.set_password('admin123')
            db.session.add(admin_user)
            db.session.commit()

            admin_wallet = Wallet(user_id=admin_user.id, balance=10000)
            db.session.add(admin_wallet)
            db.session.commit()
            print("Default admin created (Username: admin, Password: admin123)")


if __name__ == '__main__':
    init_db()
    app.run(debug=True)