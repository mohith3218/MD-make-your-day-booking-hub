"""Admin routes for the catalogue, venues, and operations."""
from flask import Blueprint

bp = Blueprint("admin", __name__)

from .movies import (
    queue_movie_sync,
    edit_movie,
    add_movie,
    update_movie_trailer,
    import_movie,
    import_movie_add,
    toggle_movie_status,
    set_movie_featured_order,
    archive_movie,
    fetch_cast,
    toggle_rerelease,
    delete_movie,
)
from .dashboard import (
    admin,
)
from .venues import (
    verify_theater,
    verify_screen,
    add_theater,
    seed_vizag,
    screens,
    add_screen,
    edit_layout,
    edit_auditorium_reference,
    admin_auditorium_reference_file,
    add_showtime,
)
from .operations import (
    admin_recharges,
    handle_recharge,
    admin_bookings,
    admin_analytics,
    admin_analytics_export,
)
