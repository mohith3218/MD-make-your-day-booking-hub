from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
from datetime import date, datetime
 
app = Flask(__name__)
app.config['SECRET_KEY'] = 'vizag-movie-booking-secret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vizag_movies.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
 
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
 
# ====================== MODELS ======================
 
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
 
class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    duration = db.Column(db.Integer)
    poster = db.Column(db.String(300))
 
class Theater(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    location = db.Column(db.String(200))
 
class Showtime(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    theater = db.Column(db.String(100), nullable=False)
    show_date = db.Column(db.Date, nullable=False)
    show_time = db.Column(db.String(20), nullable=False)
 
class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    seats = db.Column(db.String(200), nullable=False)  # Example: "A5,A6,B7"
    amount = db.Column(db.Integer, default=0)
    booked_at = db.Column(db.DateTime, default=datetime.utcnow)
 
class BookedSeat(db.Model):
    """
    One row per seat per showtime. The unique constraint below is what
    actually stops a race condition: if two people submit the same seat
    at the same instant, the database itself rejects the second insert
    (raises IntegrityError) instead of both requests succeeding.
    """
    id = db.Column(db.Integer, primary_key=True)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    seat = db.Column(db.String(10), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
 
    __table_args__ = (
        db.UniqueConstraint('showtime_id', 'seat', name='uq_showtime_seat'),
    )
 
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
 
# ====================== CREATE TABLES + DEFAULT ADMIN ======================
 
# Real Visakhapatnam theaters, seeded once on first run. Admins can add
# more any time from /admin/add_theater -- this list is just a starting point.
SEED_THEATERS = [
    ("INOX CMR Central", "Maddilapalem"),
    ("INOX Varun Beach", "RK Beach Road"),
    ("Cinepolis CMR Mall", "Seethammadhara"),
    ("Mukta A2 Cinemas", "Vizag Central, Asilmetta"),
    ("Leela Mahal 70MM", "Jagadamba Junction"),
    ("Jagadamba Theater", "Jagadamba Junction"),
    ("Sangam 70MM", "Jagadamba Junction"),
    ("Sri Kanya Theater", "Gajuwaka"),
    ("Melody Theater", "Gopalapatnam"),
    ("Mohini Cinemas", "Gajuwaka"),
    ("Mourya Theatre", "Gopalapatnam"),
    ("Alankar Theatre", "Gandhi Nagar"),
    ("Aditya Cinema Hall", "Visakhapatnam"),
    ("Urvasi Theatre", "Kancharapalem"),
]
 
# Seat classes: each row letter maps to a class with its own price + color.
# Used both for showing the legend and for pricing bookings server-side.
SEAT_CLASSES = [
    {"name": "Premium", "rows": ["A", "B"],      "price": 320, "color": "#c084fc"},
    {"name": "Gold",    "rows": ["C", "D", "E"], "price": 220, "color": "#f1c40f"},
    {"name": "Silver",  "rows": ["F", "G", "H"], "price": 150, "color": "#5dd39e"},
]
 
def price_for_row(row_letter):
    for cls in SEAT_CLASSES:
        if row_letter in cls["rows"]:
            return cls["price"]
    return 0
 
with app.app_context():
    db.create_all()
 
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            password=generate_password_hash('admin123'),
            is_admin=True
        )
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin created → username: admin | password: admin123")
 
    if Theater.query.count() == 0:
        for name, location in SEED_THEATERS:
            db.session.add(Theater(name=name, location=location))
        db.session.commit()
        print(f"✅ Seeded {len(SEED_THEATERS)} Visakhapatnam theaters")
 
# ====================== ROUTES ======================
 
@app.route('/')
def home():
    movies = Movie.query.all()
    return render_template('index.html', movies=movies)
 
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
 
        if User.query.filter_by(username=username).first():
            flash('Username already exists!')
            return redirect(url_for('register'))
 
        user = User(username=username, password=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    return render_template('register.html')
 
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
 
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('home'))
        flash('Invalid username or password')
    return render_template('login.html')
 
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))
 
@app.route('/movie/<int:movie_id>')
def movie_detail(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    showtimes = Showtime.query.filter_by(movie_id=movie_id).order_by(Showtime.show_date, Showtime.show_time).all()
    return render_template('movie.html', movie=movie, showtimes=showtimes)
 
@app.route('/book/<int:showtime_id>', methods=['GET', 'POST'])
@login_required
def book(showtime_id):
    showtime = Showtime.query.get_or_404(showtime_id)
    movie = Movie.query.get(showtime.movie_id)
 
    # Get already booked seats from the BookedSeat table (source of truth)
    booked_seats = [
        bs.seat for bs in BookedSeat.query.filter_by(showtime_id=showtime_id).all()
    ]
 
    if request.method == 'POST':
        selected = request.form.get('selected_seats')
        if not selected:
            flash("Please select at least one seat")
            return redirect(url_for('book', showtime_id=showtime_id))
 
        selected_list = selected.split(',')
 
        # Quick pre-check for a friendlier error message (not the real
        # safety net -- the DB constraint below is what actually prevents
        # a race condition between two simultaneous bookings)
        for seat in selected_list:
            if seat in booked_seats:
                flash(f"Seat {seat} is already booked. Please choose different seats.")
                return redirect(url_for('book', showtime_id=showtime_id))
 
        total_amount = sum(price_for_row(seat[0]) for seat in selected_list)
 
        try:
            new_booking = Booking(
                user_id=current_user.id,
                showtime_id=showtime_id,
                seats=selected,
                amount=total_amount
            )
            db.session.add(new_booking)
            db.session.flush()  # assigns new_booking.id without committing yet
 
            for seat in selected_list:
                db.session.add(BookedSeat(
                    showtime_id=showtime_id,
                    seat=seat,
                    booking_id=new_booking.id
                ))
 
            db.session.commit()
            flash(f"Booking confirmed! {len(selected_list)} seat(s) for ₹{total_amount}.")
            return redirect(url_for('dashboard'))
 
        except IntegrityError:
            # Someone else grabbed one of these seats between our check
            # above and this commit. Roll back the whole booking so we
            # don't end up with a partial/inconsistent booking.
            db.session.rollback()
            flash("Sorry, one or more of those seats were just booked by someone else. Please choose different seats.")
            return redirect(url_for('book', showtime_id=showtime_id))
 
    return render_template('book.html', 
                           showtime=showtime, 
                           movie=movie, 
                           booked_seats=booked_seats,
                           seat_classes=SEAT_CLASSES)
 
@app.route('/dashboard')
@login_required
def dashboard():
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booked_at.desc()).all()
    booking_list = []
    for b in bookings:
        show = Showtime.query.get(b.showtime_id)
        movie = Movie.query.get(show.movie_id)
        booking_list.append({
            'movie': movie.title,
            'theater': show.theater,
            'date': show.show_date,
            'time': show.show_time,
            'seats': b.seats,
            'amount': b.amount,
            'booked_at': b.booked_at
        })
    return render_template('dashboard.html', bookings=booking_list)
 
# ====================== ADMIN ROUTES ======================
 
@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        flash("Access denied")
        return redirect(url_for('home'))
    movies = Movie.query.all()
    showtimes = Showtime.query.order_by(Showtime.show_date.desc()).all()
    theaters = Theater.query.order_by(Theater.name).all()
    return render_template('admin.html', movies=movies, showtimes=showtimes, theaters=theaters)
 
@app.route('/admin/add_movie', methods=['GET', 'POST'])
@login_required
def add_movie():
    if not current_user.is_admin:
        flash("Access denied")
        return redirect(url_for('home'))
 
    if request.method == 'POST':
        movie = Movie(
            title=request.form['title'],
            description=request.form['description'],
            duration=int(request.form['duration']),
            poster=request.form['poster']
        )
        db.session.add(movie)
        db.session.commit()
        flash("Movie added successfully!")
        return redirect(url_for('admin'))
    return render_template('add_movie.html')
 
@app.route('/admin/add_showtime', methods=['GET', 'POST'])
@login_required
def add_showtime():
    if not current_user.is_admin:
        flash("Access denied")
        return redirect(url_for('home'))
 
    movies = Movie.query.all()
    theaters = Theater.query.order_by(Theater.name).all()
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
 
# ====================== RUN ======================
 
if __name__ == '__main__':
    app.run(debug=True)