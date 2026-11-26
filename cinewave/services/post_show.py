from ..models import ScreenReview
from .movie_reviews import movie_review_states
from .screen_reviews import eligible_screen


def experience_states(bookings, user_id):
    movie_states = movie_review_states(bookings, user_id)
    screens = {booking.id: screen for booking in bookings if booking.id in movie_states
               if (screen := eligible_screen(booking, user_id))}
    venues = {item.theater_id: item for item in ScreenReview.query.filter(
        ScreenReview.user_id == user_id,
        ScreenReview.theater_id.in_({screen.theater_id for screen in screens.values()}),
        ScreenReview.theatre_rating.is_not(None))} if screens else {}
    result = {}
    for booking in bookings:
        if booking.id not in movie_states:
            continue
        screen = screens.get(booking.id)
        venue = venues.get(screen.theater_id) if screen else None
        theatre = None
        if screen:
            theatre = ('withdrawn' if venue.theatre_withdrawn_at else 'edit') if venue else 'invite'
        result[booking.id] = {'movie': movie_states[booking.id], 'theatre': theatre}
    return result


def pending_experiences(bookings, states):
    movies, theatres, entries = set(), set(), []
    for booking in bookings:
        state = states.get(booking.id, {})
        movie_id = booking.showtime.movie_id
        theatre_id = booking.showtime.screen.theater_id if booking.showtime.screen else None
        movie = state.get('movie') == 'invite' and movie_id not in movies
        theatre = state.get('theatre') == 'invite' and theatre_id not in theatres
        if movie or theatre:
            entries.append({'booking': booking, 'movie': movie, 'theatre': theatre})
        if movie:
            movies.add(movie_id)
        if theatre:
            theatres.add(theatre_id)
    return entries
