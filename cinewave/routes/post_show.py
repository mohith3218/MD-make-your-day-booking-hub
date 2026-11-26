from datetime import datetime, timezone

from flask import Blueprint, abort, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from ..extensions import db
from ..models import Booking, Screen, Showtime
from ..services.post_show import experience_states, pending_experiences
from ..services.reviews import plain_text
from ..services.screen_reviews import eligible_screen
from ..services.theatre_reviews import own_venue_review, store_venue_feedback
from ..time import cinema_now
from .movie_reviews import own_rating, owned_completed_booking, review_values, save_review

bp = Blueprint('post_show', __name__)


@bp.get('/reviews/pending')
@login_required
def prompt():
    bookings = (Booking.query.join(Booking.showtime).filter(
        Booking.user_id == current_user.id, Booking.status == 'PAID', Showtime.is_cancelled.is_(False),
        Showtime.show_date <= cinema_now().date()).options(
            selectinload(Booking.captured_payments), joinedload(Booking.showtime).joinedload(Showtime.movie),
            joinedload(Booking.showtime).joinedload(Showtime.screen).joinedload(Screen.theater),
        ).order_by(Showtime.show_date.desc(), Booking.booked_at.desc()).all())
    pending = pending_experiences(bookings, experience_states(bookings, current_user.id))
    response = make_response(
        render_template('components/post_show_prompt.html', item=pending[0]) if pending else '', 200 if pending else 204)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def theatre_values(form):
    marks = form.getlist('theatre_rating')
    if len(marks) != 1 or marks[0] not in {'1', '2', '3', '4', '5'}:
        raise ValueError('Choose a theatre rating from 1 to 5 stars.')
    return int(marks[0]), plain_text(form.get('theatre_review', ''), 1000) or None


@bp.route('/booking/<reference>/experience-review', methods=['GET', 'POST'])
@bp.route('/booking/<reference>/theatre-review', defaults={'venue_only': True},
          methods=['GET', 'POST'], endpoint='edit_theatre')
@login_required
def edit(reference, venue_only=False):
    booking, source = owned_completed_booking(reference)
    screen = eligible_screen(booking, current_user.id)
    if venue_only and not screen:
        abort(403)
    venue = own_venue_review(screen.theater_id, current_user.id) if screen else None
    movie = own_rating(booking.showtime.movie_id)
    movie_allowed = not venue_only and not (movie and movie.booking_id)
    venue_allowed = bool(screen and (venue_only or not venue))
    values, errors = {}, {}
    if venue:
        values = {'theatre_rating': venue.theatre_rating, 'theatre_review': venue.theatre_review_text or ''}
    if request.method == 'POST':
        if request.form.get('action') == 'withdraw' and venue_only and venue:
            venue.theatre_withdrawn_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.session.commit()
            flash('Your theatre review was withdrawn.')
            return redirect(url_for('profile.dashboard', _anchor='pending-reviews'), code=303)
        movie_requested = bool(request.form.get('rating') or request.form.get('review', '').strip())
        venue_requested = bool(request.form.get('theatre_rating') or request.form.get('theatre_review', '').strip())
        if (movie_requested and not movie_allowed) or (venue_requested and not venue_allowed):
            abort(409, description='A review already exists. Reopen its edit form to make changes.')
        if not movie_requested and not venue_requested:
            errors['general'] = 'Choose a star rating for at least one review.'
        if movie_requested:
            movie_fields, movie_errors = review_values(request.form)
            errors.update(movie_errors)
            values.update(movie_fields)
        if venue_requested:
            try:
                rating, comment = theatre_values(request.form)
                values.update(theatre_rating=rating, theatre_review=comment)
            except ValueError as error:
                errors['theatre_rating'] = str(error)
                values['theatre_review'] = request.form.get('theatre_review', '')[:1000]
        if not errors:
            try:
                if movie_requested:
                    save_review(booking, source, movie, movie_fields, commit=False)
                if venue_requested:
                    store_venue_feedback(booking, source, screen, rating, comment)
                db.session.commit()
                flash('Your reviews were saved.' if movie_requested and venue_requested else 'Your review was saved.')
            except IntegrityError:
                db.session.rollback()
                flash('The review changed in another request. Open the form again to check it.')
            return redirect(url_for('profile.dashboard', _anchor='pending-reviews'), code=303)
    return render_template('reviews/experience_review.html', booking=booking, movie_allowed=movie_allowed,
                           venue_allowed=venue_allowed, venue=venue, venue_only=venue_only, values=values,
                           errors=errors), 422 if errors else 200
