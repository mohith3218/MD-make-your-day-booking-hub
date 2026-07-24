from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'movie-booking-secret-key-123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///movies.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ==================== MODELS ====================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    duration = db.Column(db.Integer)  # in minutes

class Showtime(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    theater = db.Column(db.String(100))
    show_date = db.Column(db.Date, nullable=False)
    show_time = db.Column(db.String(20), nullable=False)

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    seats = db.Column(db.String(100))
    status = db.Column(db.String(50), default='Confirmed')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==================== CREATE DATABASE + SAMPLE DATA ====================

with app.app_context():
    db.create_all()

    # Add sample movies only if database is empty
    if Movie.query.count() == 0:
        m1 = Movie(title="Dune: Part Two")
if __name__ == '__main__':
    app.run(debug=True)