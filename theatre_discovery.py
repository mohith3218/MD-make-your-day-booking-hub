"""Public theatre discovery using the same ORM database and booking records."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import math
import re

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload

import seat_layout as sl

CINEMA_TIMEZONE = timezone(timedelta(hours=5, minutes=30), name='Asia/Kolkata')


def cinema_now():
    """Stored show dates/times are Visakhapatnam wall time, not host UTC."""
    return datetime.now(CINEMA_TIMEZONE).replace(tzinfo=None)


def text_filter(name, maximum=120):
    values = request.args.getlist(name)
    if len(values) > 1:
        abort(400, description='Provide each filter only once.')
    value = (values[0] if values else '').strip()
    if len(value) > maximum or any(ord(char) < 32 for char in value):
        abort(400, description='A discovery filter is invalid or too long.')
    return value


def positive_id(value):
    if not re.fullmatch(r'[1-9][0-9]{0,9}', value):
        abort(400, description='Identifiers must be positive integers.')
    return int(value)


def validate_booking_context(show):
    """Check every supplied query/form identifier against the persisted show."""
    expected = {'theatre_id': show.screen.theater_id if show.screen else None,
                'screen_id': show.screen_id, 'movie_id': show.movie_id}
    supplied = False
    for name, actual in expected.items():
        for source in (request.args, request.form):
            values = source.getlist(name)
            if len(values) > 1:
                abort(400, description='Provide each booking identifier only once.')
            if values:
                supplied = True
                if positive_id(values[0]) != actual:
                    abort(404, description='The selected show does not belong to this theatre, screen and movie.')
    return expected if supplied else {}


def create_theatre_blueprint(db, models, price_map):
    """Reuse existing models without another engine, schema or booking system."""
    bp = Blueprint('theatre_discovery', __name__)
    Theater, Screen, Showtime = models.Theater, models.Screen, models.Showtime
    Movie, BookedSeat, SeatHold = models.Movie, models.BookedSeat, models.SeatHold

    def scheduled(theatre_id=None):
        query = (Showtime.query.join(Screen, Showtime.screen_id == Screen.id)
                 .join(Theater, Screen.theater_id == Theater.id)
                 .join(Movie, Showtime.movie_id == Movie.id)
                 .options(joinedload(Showtime.movie),
                          joinedload(Showtime.screen).joinedload(Screen.theater))
                 .filter(Showtime.show_date >= cinema_now().date()))
        if theatre_id is not None:
            query = query.filter(Screen.theater_id == theatre_id)
        return sorted((show for show in query.all() if show.status == 'upcoming'
                       and show.show_datetime is not None), key=lambda show: (show.show_datetime, show.id))

    def availability(shows):
        """Two batched seat queries; overlapping held/booked IDs count once."""
        ids = [show.id for show in shows]
        booked, held = defaultdict(set), defaultdict(set)
        if ids:
            for show_id, seat in db.session.query(BookedSeat.showtime_id, BookedSeat.seat_id).filter(
                    BookedSeat.showtime_id.in_(ids)):
                booked[show_id].add(seat)
            utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
            for show_id, seat in db.session.query(SeatHold.showtime_id, SeatHold.seat_id).filter(
                    SeatHold.showtime_id.in_(ids), SeatHold.expires_at > utc_now):
                held[show_id].add(seat)
        cards = []
        for show in shows:
            try:
                pricing = show.pricing_info(booked_count=len(booked[show.id]))
                prices = price_map(show, pricing_info=pricing)
                # Only physical seats in the persisted layout may be offered.
                available = {seat: price for seat, price in prices.items()
                             if seat not in booked[show.id] | held[show.id]
                             and math.isfinite(price) and price > 0}
                total = sl.count_seats(show.layout)
            except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
                available, total = {}, 0
            start = show.show_datetime
            end = start + timedelta(minutes=show.movie.duration) if show.movie.duration and show.movie.duration > 0 else None
            cards.append({'show': show, 'remaining': len(available), 'total': total,
                          'price': min(available.values()) if available else None,
                          'start': start, 'end': end,
                          'format': show.screen.screen_type or 'Unspecified',
                          'bookable': bool(available), 'pricing_label': pricing['badge'] if total else None})
        return cards

    @bp.errorhandler(SQLAlchemyError)
    def unavailable(error):
        db.session.rollback()
        current_app.logger.warning('Theatre discovery database query failed (%s)', type(error).__name__)
        return render_template('theatre_discovery_error.html',
                               message='Cinema schedules are temporarily unavailable. Please try again shortly.'), 503

    @bp.errorhandler(400)
    def invalid_filter(error):
        return render_template('theatre_discovery_error.html', message=error.description), 400

    @bp.route('/theatres')
    def index():
        filters = {'q': text_filter('q')}
        query = Theater.query.options(selectinload(Theater.screens))
        if filters['q']:
            literal = filters['q'].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            pattern = '%' + literal + '%'
            query = query.filter(Theater.name.ilike(pattern, escape='\\'))
        theatres = query.all()
        folded = filters['q'].casefold()
        theatres.sort(key=lambda theatre: (
            0 if folded and theatre.name.casefold() == folded else
            1 if folded and theatre.name.casefold().startswith(folded) else 2,
            theatre.name.casefold(), theatre.id))
        shows = scheduled()
        summary = defaultdict(lambda: {'shows': 0, 'movies': set()})
        for show in shows:
            summary[show.screen.theater_id]['shows'] += 1
            summary[show.screen.theater_id]['movies'].add(show.movie_id)
        return render_template('theatres.html', theatres=theatres, filters=filters,
                               summary=summary)

    @bp.route('/theatres/<int:theatre_id>', defaults={'movie_id': None})
    @bp.route('/theatres/<int:theatre_id>/movies/<int:movie_id>')
    def detail(theatre_id, movie_id):
        theatre = Theater.query.options(selectinload(Theater.screens)).get_or_404(theatre_id)
        filters = {name: text_filter(name, 80) for name in ('date', 'language', 'format', 'screen', 'time')}
        shows = scheduled(theatre.id)
        movie = None
        if movie_id is not None:
            movie = next((show.movie for show in shows if show.movie_id == movie_id), None)
            if movie is None:
                abort(404, description='This movie has no upcoming shows at the selected theatre.')
            shows = [show for show in shows if show.movie_id == movie_id]
        dates = sorted({show.show_date for show in shows})
        if filters['date']:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', filters['date']):
                abort(400, description='Choose a valid date in YYYY-MM-DD format.')
            try:
                selected_date = date.fromisoformat(filters['date'])
            except ValueError:
                abort(400, description='Choose a valid calendar date.')
        else:
            selected_date = dates[0] if dates else cinema_now().date()
        filters['date'] = selected_date.isoformat()
        if filters['screen']:
            selected_screen = positive_id(filters['screen'])
            if selected_screen not in {screen.id for screen in theatre.screens}:
                abort(404, description='This screen does not belong to the selected theatre.')
        if filters['time'] and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', filters['time']):
            abort(400, description='Choose a valid show time in HH:MM format.')
        on_date = [show for show in shows if show.show_date == selected_date]
        languages = sorted({show.movie.language for show in on_date if show.movie.language})
        formats = sorted({show.screen.screen_type for show in on_date if show.screen.screen_type})
        times = sorted({show.show_datetime.strftime('%H:%M') for show in on_date})
        filtered = [show for show in on_date
                    if (not filters['language'] or (show.movie.language or '').casefold() == filters['language'].casefold())
                    and (not filters['format'] or (show.screen.screen_type or '').casefold() == filters['format'].casefold())
                    and (not filters['screen'] or show.screen_id == int(filters['screen']))
                    and (not filters['time'] or show.show_datetime.strftime('%H:%M') == filters['time'])]
        groups = {}
        for card in availability(filtered):
            film = card['show'].movie
            groups.setdefault(film.id, {'movie': film, 'shows': []})['shows'].append(card)
        for group in groups.values():
            prices = [card['price'] for card in group['shows'] if card['price'] is not None]
            group['starting_price'] = min(prices) if prices else None
        return render_template('theatre_detail.html', theatre=theatre, movie=movie,
                               movie_groups=list(groups.values()), dates=dates,
                               filters=filters, selected_date=selected_date,
                               languages=languages, formats=formats, times=times)

    @bp.route('/theatres/<int:theatre_id>/shows/<int:showtime_id>/book')
    def select_show(theatre_id, showtime_id):
        show = (Showtime.query.options(joinedload(Showtime.screen), joinedload(Showtime.movie))
                .filter_by(id=showtime_id).first_or_404())
        if not show.screen or show.screen.theater_id != theatre_id:
            abort(404, description='This show does not belong to the selected theatre.')
        if show.status != 'upcoming' or not show.show_datetime:
            return render_template('theatre_discovery_error.html',
                                   message='This show has started or is no longer available. Choose another screening.'), 409
        if not availability([show])[0]['bookable']:
            return render_template('theatre_discovery_error.html',
                                   message='This screening has no bookable seats. Choose another showtime.'), 409
        return redirect(url_for('book', showtime_id=show.id, theatre_id=theatre_id,
                                screen_id=show.screen_id, movie_id=show.movie_id))

    return bp
