from flask import Blueprint
from sqlalchemy.orm import joinedload, selectinload
from ._support import *
from ..services.screen_reviews import review_invitation
from ..services.movie_reviews import movie_review_states
from ..services.post_show import experience_states, pending_experiences

bp = Blueprint("profile", __name__)


@bp.route('/dashboard')
@login_required
def dashboard():
    purge_expired_holds()
    bookings = (Booking.query.filter_by(user_id=current_user.id)
                .options(joinedload(Booking.screen_review), joinedload(Booking.payment),
                         selectinload(Booking.captured_payments),
                         joinedload(Booking.showtime).joinedload(Showtime.movie),
                         joinedload(Booking.showtime).joinedload(Showtime.screen).joinedload(Screen.theater))
                .order_by(Booking.booked_at.desc()).all())
    review_states = {booking.id: review_invitation(booking, current_user.id) for booking in bookings}
    states = experience_states(bookings, current_user.id)
    return render_template('account/dashboard.html', bookings=bookings, review_states=review_states,
                           movie_review_states={booking_id: state['movie'] for booking_id, state in states.items()},
                           experience_states=states, pending_reviews=pending_experiences(bookings, states))


@bp.route('/profile')
@login_required
def profile():
    purge_expired_holds()
    user_stats = current_user.stats
    film_dna = current_user.film_dna
    watchlist_movies = [movie for movie in current_user.watchlist_movies if not movie.is_archived]
    recent_bookings = (Booking.query.filter_by(user_id=current_user.id, status='PAID')
                      .order_by(Booking.booked_at.desc()).limit(6).all())
    hype_stickers = (MovieHypeVote.query.filter_by(user_id=current_user.id)
                     .join(Movie).filter(Movie.is_archived.is_(False))
                     .order_by(MovieHypeVote.updated_at.desc()).all())
    return render_template(
        'account/profile.html',
        stats=user_stats,
        film_dna=film_dna,
        watchlist_movies=watchlist_movies,
        recent_bookings=recent_bookings,
        hype_stickers=hype_stickers,
        review_states={booking.id: review_invitation(booking, current_user.id) for booking in recent_bookings},
        movie_review_states=movie_review_states(recent_bookings, current_user.id),
    )


@bp.route('/profile/edit', methods=['POST'])
@login_required
def edit_profile():
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    bio = request.form.get('bio', '').strip()

    if email and not is_valid_email(email):
        flash('Please enter a valid email address.')
        return redirect(url_for('profile.profile'))

    # Check email uniqueness if changed
    if email and email != current_user.email:
        password_check = request.form.get('current_password', '')
        if not password_check or not current_user.check_password(password_check):
            flash('Enter your current password to change the recovery address.')
            return redirect(url_for('profile.profile'), code=303)
        existing = User.query.filter_by(email=email).first()
        if existing and existing.id != current_user.id:
            flash('This email address is already in use by another account.')
            return redirect(url_for('profile.profile'), code=303)
        current_user.email = email
        current_user.email_verified = False
        db.session.query(PasswordReset).filter_by(user_id=current_user.id, used_at=None).update(
            {'used_at': datetime.utcnow()}, synchronize_session=False)

    if phone:
        current_user.phone = phone
    if bio:
        current_user.bio = bio[:250]

    db.session.commit()
    flash('Your profile has been updated!')
    return redirect(url_for('profile.profile'), code=303)
