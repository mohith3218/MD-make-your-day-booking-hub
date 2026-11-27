from cinewave.integrations.tmdb import parse_release_date
from cinewave.models import Booking
from cinewave.models import Movie
from cinewave.models import MovieSyncState
from cinewave.models import RechargeRequest
from cinewave.models import Screen
from cinewave.models import Showtime
from cinewave.models import Theater
from cinewave.extensions import db
from flask_login import login_required
from flask import render_template
from flask import request
from cinewave.services import admin_required
from cinewave.workers.movie_sync import STATE_ID, pending_count, utc_now
from cinewave.workers.movie_sync import credentials_configured
from cinewave.workers.movie_sync import sync_status
from sqlalchemy.orm import joinedload

from . import bp


@bp.route('/admin')
@login_required
def admin():
    guard = admin_required()
    if guard:
        return guard
    visibility = request.args.get('visibility', 'active').strip().lower()
    if visibility not in {'active', 'archived', 'all'}:
        visibility = 'active'
    movie_search = request.args.get('q', '').strip()[:100]
    language = request.args.get('language', '').strip()[:50]
    released_from = parse_release_date(request.args.get('released_from'))
    released_to = parse_release_date(request.args.get('released_to'))
    schedule = request.args.get('schedule', '')
    source = request.args.get('source', '')
    movie_query = Movie.query
    if visibility == 'active':
        movie_query = movie_query.filter_by(is_archived=False)
    elif visibility == 'archived':
        movie_query = movie_query.filter_by(is_archived=True)
    if movie_search:
        movie_query = movie_query.filter(Movie.title.icontains(movie_search, autoescape=True))
    if language:
        movie_query = movie_query.filter(Movie.language == language)
    if released_from:
        movie_query = movie_query.filter(Movie.release_date >= released_from)
    if released_to:
        movie_query = movie_query.filter(Movie.release_date <= released_to)
    if source == 'tmdb':
        movie_query = movie_query.filter(Movie.tmdb_id.is_not(None))
    if source == 'manual':
        movie_query = movie_query.filter(Movie.tmdb_id.is_(None))
    showtimes = Showtime.query.options(joinedload(Showtime.screen)).order_by(Showtime.show_date.desc()).all()
    scheduled_ids = {show.movie_id for show in showtimes if show.screen and show.status == 'upcoming'}
    if schedule == 'scheduled':
        movie_query = movie_query.filter(Movie.id.in_(scheduled_ids))
    if schedule == 'unscheduled':
        movie_query = movie_query.filter(Movie.id.not_in(scheduled_ids))
    movie_page = movie_query.order_by(Movie.is_archived, Movie.title, Movie.id).paginate(
        page=request.args.get('page', 1, type=int), per_page=25, error_out=False)
    languages = [row[0] for row in db.session.query(Movie.language).filter(Movie.language.is_not(None))
                 .distinct().order_by(Movie.language)]
    filters = {'q': movie_search, 'visibility': visibility, 'language': language,
               'released_from': released_from, 'released_to': released_to,
               'schedule': schedule, 'source': source}
    state = db.session.get(MovieSyncState, STATE_ID)
    theaters = Theater.query.all()
    screens = Screen.query.all()
    pending_recharges = RechargeRequest.query.filter_by(status='PENDING').count()
    revenue = db.session.query(db.func.sum(Booking.total_amount)) \
                        .filter(Booking.status == 'PAID').scalar() or 0
    return render_template('admin/admin.html', movies=movie_page.items, showtimes=showtimes,
                           theaters=theaters, screens=screens,
                           movie_search=movie_search, movie_visibility=visibility,
                           movie_page=movie_page, movie_filters=filters, movie_languages=languages,
                           scheduled_ids=scheduled_ids, sync_state=state, sync_status=sync_status(state),
                           sync_configured=credentials_configured(),
                           sync_pending_candidates=pending_count(utc_now()),
                           sync_total_movies=Movie.query.filter(Movie.tmdb_id.is_not(None)).count(),
                           pending_recharges=pending_recharges, revenue=revenue,
                           paid_count=Booking.query.filter_by(status='PAID').count())
