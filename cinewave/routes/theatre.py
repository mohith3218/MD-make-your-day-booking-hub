from flask import Blueprint
from ._support import *
from ..services.seat import screening_availability

bp = Blueprint("theatre", __name__)


@bp.route('/api/screen/<int:screen_id>/classes')
@login_required
def screen_classes(screen_id):
    """Used by add_showtime.html to show per-class price boxes for a screen."""
    screen = Screen.query.get_or_404(screen_id)
    return jsonify({'screen': screen.name, 'seats': screen.total_seats,
                    'classes': [{'code': c.get('code'), 'name': c.get('name'),
                                 'price': c.get('price')}
                                for c in screen.layout.get('classes', [])]})


@bp.route('/api/theatres')
def api_theatres():
    """
    Return all theatres from Supabase as JSON.
    Falls back to SQLite if Supabase is unavailable.
    Response: { source: "supabase"|"sqlite", theatres: [...] }
    """
    service = TheatreService.get()
    if service:
        try:
            data = service.all_theatres_with_screens()
            return jsonify({'source': 'supabase', 'count': len(data), 'theatres': data})
        except Exception as exc:
            app.logger.warning("TheatreService.all_theatres_with_screens failed: %s", exc)
    # Fallback: SQLite ORM
    theaters = Theater.query.order_by(Theater.name).all()
    data = [{'id': t.id, 'name': t.name, 'location': t.location,
             'city': t.city, 'address': t.address,
             'screens': [{'id': s.id, 'name': s.name, 'screen_type': s.screen_type}
                         for s in t.screens]}
            for t in theaters]
    return jsonify({'source': 'sqlite', 'count': len(data), 'theatres': data})


@bp.route('/api/theatres/<int:theatre_id>')
def api_theatre_detail(theatre_id):
    """
    Return one theatre with its screens from Supabase.
    Falls back to SQLite ORM.
    """
    service = TheatreService.get()
    if service:
        try:
            theatre = service.theatre_by_id(theatre_id)
            if theatre:
                theatre['screens'] = service.screens_for_theatre(theatre_id)
                return jsonify({'source': 'supabase', 'theatre': theatre})
        except Exception as exc:
            app.logger.warning("TheatreService.theatre_by_id failed: %s", exc)
    # Fallback: SQLite ORM
    t = Theater.query.get_or_404(theatre_id)
    return jsonify({'source': 'sqlite', 'theatre': {
        'id': t.id, 'name': t.name, 'location': t.location,
        'city': t.city, 'address': t.address,
        'screens': [{'id': s.id, 'name': s.name, 'screen_type': s.screen_type,
                     'layout_json': s.layout_json}
                    for s in t.screens]
    }})


@bp.route('/api/theatres/<int:theatre_id>/screens/<int:screen_id>/layout')
def api_screen_layout(theatre_id, screen_id):
    """
    Return one screen's layout_json from Supabase.
    Used by the 3D preview and seat-selection clients to fetch the authoritative layout.
    Falls back to SQLite ORM.
    """
    service = TheatreService.get()
    if service:
        try:
            screen = service.screen_by_id(screen_id)
            if screen and screen.get('theater_id') == theatre_id:
                return jsonify({'source': 'supabase', 'screen': screen})
        except Exception as exc:
            app.logger.warning("TheatreService.screen_by_id failed: %s", exc)
    # Fallback: SQLite ORM
    screen = Screen.query.filter_by(id=screen_id, theater_id=theatre_id).first_or_404()
    return jsonify({'source': 'sqlite', 'screen': {
        'id': screen.id, 'theater_id': screen.theater_id,
        'name': screen.name, 'screen_type': screen.screen_type,
        'layout_json': screen.layout_json,
        'theater_name': screen.theater.name,
        'theater_location': screen.theater.location,
    }})



@bp.route('/api/showtime/<int:showtime_id>/availability')
@login_required
def seat_availability(showtime_id):
    """Polled by the seat page so seats grey out live while you are choosing."""
    purge_expired_holds()
    showtime = Showtime.query.get_or_404(showtime_id)
    return jsonify({'booked': sorted(showtime.booked_seat_ids()),
                    'held': sorted(showtime.held_seat_ids())})


@bp.route('/api/showtime/<int:showtime_id>/live-info')
def showtime_live_info(showtime_id):
    """Public endpoint: returns real-time seats left, show status, and countdown seconds."""
    purge_expired_holds()
    showtime = Showtime.query.get_or_404(showtime_id)
    if showtime.movie.is_archived:
        abort(404)
    dt = showtime.show_datetime
    availability = screening_availability([showtime])[showtime_id] if showtime.accepts_bookings else None
    seconds_to_start = int((dt - cinema_now()).total_seconds()) if availability else 0
    return jsonify({
        'seats_left': availability['remaining'] if availability else 0,
        'total_seats': sl.count_seats(showtime.layout),
        'status': showtime.status,
        'seconds_to_start': max(0, seconds_to_start),
    })
