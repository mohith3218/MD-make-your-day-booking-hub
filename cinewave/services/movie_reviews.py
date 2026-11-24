from sqlalchemy.orm import joinedload

from ..models import Booking, MovieRating, Showtime
from ..time import cinema_now
from .reviews import completed_booking_source, published_reviews

ACCESS_MESSAGE = 'Movie reviews become available after you complete your booked screening.'


def eligible_booking(movie_id, user_id):
    if user_id is None:
        return None
    bookings = (Booking.query.join(Booking.showtime)
                .filter(Booking.user_id == user_id, Booking.status == 'PAID',
                        Showtime.movie_id == movie_id, Showtime.show_date <= cinema_now().date(),
                        Showtime.is_cancelled.is_(False))
                .options(joinedload(Booking.showtime).joinedload(Showtime.movie), joinedload(Booking.payment))
                .order_by(Booking.id.desc()))
    return next((booking for booking in bookings if completed_booking_source(booking, user_id)), None)


def movie_review_states(bookings, user_id):
    eligible = {booking.id: booking.showtime.movie_id for booking in bookings
                if completed_booking_source(booking, user_id)}
    if not eligible:
        return {}
    ratings = {review.movie_id: review for review in MovieRating.query.filter(
        MovieRating.user_id == user_id, MovieRating.movie_id.in_(set(eligible.values())),
        MovieRating.booking_id.is_not(None))}
    return {booking_id: ('withdrawn' if ratings[movie_id].withdrawn_at else 'edit')
            if movie_id in ratings else 'invite' for booking_id, movie_id in eligible.items()}


def booked_movie_reviews():
    return MovieRating.query.filter(MovieRating.booking_id.is_not(None))


def published_movie_reviews():
    return published_reviews(MovieRating).filter(MovieRating.booking_id.is_not(None))
