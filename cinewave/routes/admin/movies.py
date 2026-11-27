from cinewave.config import PARTY_LIFETIME
from cinewave.integrations.tmdb import TMDBClient
from cinewave.integrations.tmdb import TMDBError
from cinewave.integrations.tmdb import LANGUAGES
from cinewave.integrations.tmdb import authorized_poster_url
from cinewave.integrations.tmdb import clean_text
from cinewave.integrations.tmdb import image_url
from cinewave.integrations.tmdb import meaningful_overview
from cinewave.integrations.tmdb import minimum_metadata
from cinewave.integrations.tmdb import movie_metadata
from cinewave.integrations.tmdb import parse_release_date
from cinewave.integrations.trailers import trailer_selection
from cinewave.models import BookedSeat
from cinewave.models import Booking
from cinewave.models import Movie
from cinewave.models import PartyMember
from cinewave.models import PartySession
from cinewave.models import SeatHold
from cinewave.models import SeatLock
from cinewave.models import Showtime
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from flask import abort
from cinewave.time import cinema_now
from flask import current_app as app
from datetime import datetime
from cinewave.extensions import db
from flask import flash
from flask_login import login_required
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from cinewave.services import admin_required
from cinewave.workers.movie_sync import apply_metadata
from cinewave.workers.movie_sync import create_movie
from cinewave.workers.movie_sync import matching_local_movie
from cinewave.workers.movie_sync import request_movie_sync
from cinewave.workers.movie_sync import utc_now
import re

from . import bp


MAX_FEATURED_MOVIES = 5


def _apply_featured_order(movie, position):
    """Insert or remove an active movie, then compact the ordered feature list."""
    movie.featured_order = None
    db.session.flush()
    ordered = (Movie.query.filter(Movie.is_archived.is_(False),
                                  Movie.featured_order.isnot(None))
               .order_by(Movie.featured_order.asc(), Movie.id.asc()).all())
    ordered = [item for item in ordered if item.id != movie.id]
    if position is not None:
        ordered.insert(min(position - 1, len(ordered)), movie)
    for item in ordered[MAX_FEATURED_MOVIES:]:
        item.featured_order = None
    for rank, item in enumerate(ordered[:MAX_FEATURED_MOVIES], start=1):
        item.featured_order = rank


def _parse_featured_position(raw_value):
    value = (raw_value or '').strip()
    if not value:
        return None
    try:
        position = int(value)
    except ValueError:
        abort(400, description='Featured order must be between 1 and 5.')
    if not 1 <= position <= MAX_FEATURED_MOVIES:
        abort(400, description='Featured order must be between 1 and 5.')
    return position


@bp.post('/admin/movies/sync')
@login_required
def queue_movie_sync():
    guard = admin_required()
    if guard:
        return guard
    try:
        request_movie_sync()
    except SQLAlchemyError:
        db.session.rollback()
        flash('CineWave could not queue synchronization. Check the database and Alembic revision.')
    else:
        flash('TMDB synchronization queued for the next external worker check-in.')
    return redirect(url_for('admin.admin', _anchor='movie-sync'), code=303)


@bp.route('/admin/movie/<int:movie_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_movie(movie_id):
    guard = admin_required()
    if guard:
        return guard
    query = Movie.query.filter_by(id=movie_id)
    movie = (query.with_for_update() if request.method == 'POST' else query).first_or_404()
    if request.method == 'POST':
        fields = {
            'title': request.form.get('title', '').strip(),
            'description': request.form.get('description', '').strip(),
            **{key: request.form.get(key, '').strip() or None
               for key in ('language', 'certificate', 'poster', 'backdrop')},
        }
        runtime = request.form.get('duration', '').strip()
        release = request.form.get('release_date', '').strip()
        fields['release_date'] = parse_release_date(release)
        if (not fields['title'] or not fields['description']
                or any(len(fields[key] or '') > limit for key, limit in (
                    ('title', 200), ('language', 50), ('certificate', 10), ('poster', 500), ('backdrop', 500)))
                or (runtime and not re.fullmatch(r'[1-9][0-9]{0,3}', runtime))
                or (release and not fields['release_date'])):
            flash('Enter a title, description, and valid movie information.')
            return render_template('admin/edit_movie.html', movie=movie), 400
        fields['duration'] = int(runtime) if runtime else 0
        changed = [name for name, value in fields.items() if value != getattr(movie, name)]
        for name in changed:
            setattr(movie, name, fields[name])
        if changed:
            movie.lock_tmdb_fields(*changed)
            db.session.commit()
        flash('Movie details saved.')
        return redirect(url_for('admin.admin', _anchor='movies'), code=303)
    return render_template('admin/edit_movie.html', movie=movie)


@bp.route('/admin/add_movie', methods=['GET', 'POST'])
@login_required
def add_movie():
    guard = admin_required()
    if guard:
        return guard
    if request.method == 'POST':
        featured_position = _parse_featured_position(request.form.get('featured_order'))
        try:
            source, trailer_key, cloudinary_url = trailer_selection(request.form)
        except ValueError as error:
            flash(str(error))
            return render_template('admin/add_movie.html'), 400
        category = request.form.get('category', 'showing')
        is_upcoming = (category == 'upcoming')
        is_rerelease = (request.form.get('release_type', 'fresh') == 'rerelease')

        rel_date_str = request.form.get('release_date', '').strip()
        rel_date = None
        if rel_date_str:
            try:
                rel_date = datetime.strptime(rel_date_str, '%Y-%m-%d').date()
            except ValueError:
                rel_date = None

        movie = Movie(title=request.form['title'],
                      description=request.form['description'],
                      duration=int(request.form['duration']),
                      poster=request.form.get('poster', '').strip() or None,
                      backdrop=request.form.get('backdrop', '').strip() or None,
                      language=request.form.get('language', 'Telugu'),
                      certificate=request.form.get('certificate', 'U/A'),
                      is_upcoming=is_upcoming,
                      is_rerelease=is_rerelease,
                      release_date=rel_date,
                      trailer_source=source, youtube_trailer_key=trailer_key,
                      cloudinary_trailer_url=cloudinary_url)
        db.session.add(movie)
        db.session.flush()
        if featured_position is not None:
            _apply_featured_order(movie, featured_position)
        db.session.commit()
        cat_label = 'Coming Soon' if is_upcoming else 'Now Showing'
        rel_label = ' (Re-Release)' if is_rerelease else ''
        flash(f"Movie '{movie.title}' added to {cat_label}{rel_label}!")
        return redirect(url_for('admin.admin'))
    return render_template('admin/add_movie.html')


@bp.route('/admin/movie/<int:movie_id>/trailer', methods=['POST'])
@login_required
def update_movie_trailer(movie_id):
    guard = admin_required()
    if guard:
        return guard
    movie = Movie.query.filter_by(id=movie_id).with_for_update().first_or_404()
    try:
        source, key, cloudinary_url = trailer_selection(request.form)
    except ValueError as error:
        flash(str(error))
        return redirect(url_for('admin.edit_movie', movie_id=movie.id, _anchor='trailer'), code=303)
    movie.trailer_source = source
    movie.youtube_trailer_key = key
    movie.cloudinary_trailer_url = cloudinary_url
    db.session.commit()
    flash('Trailer settings saved.')
    return redirect(url_for('admin.edit_movie', movie_id=movie.id, _anchor='trailer'), code=303)


@bp.route('/admin/import_movie', methods=['GET'])
@login_required
def import_movie():
    guard = admin_required()
    if guard:
        return guard
    results, query = [], request.args.get('query', '').strip()[:120]
    page = min(500, max(1, request.args.get('page', 1, type=int)))
    total_pages, search_error = 0, None
    if query:
        try:
            with TMDBClient(attempts=2) as client:
                if re.fullmatch(r'[0-9]{1,10}', query) and 0 < int(query) <= 2_147_483_647:
                    item = client.get(f'/movie/{int(query)}', append_to_response='release_dates')
                    if item.get('id') != int(query):
                        raise TMDBError('TMDB returned details for an unexpected movie.')
                    regional = movie_metadata(item, client.region)['release_date']
                    if regional:
                        item['release_date'] = regional.isoformat()
                    items, total_pages, page = [item], 1, 1
                else:
                    payload = client.search(query, page=page)
                    items, total_pages = payload.get('results'), payload.get('total_pages')
            if not isinstance(items, list) or type(total_pages) is not int:
                raise TMDBError('TMDB returned invalid search results.')
            results = [import_result(item) for item in items if isinstance(item, dict)
                       and type(item.get('id')) is int and 0 < item['id'] <= 2_147_483_647
                       and clean_text(item.get('title') or item.get('original_title')) and not item.get('adult')]
            ids = [item['tmdb_id'] for item in results]
            imported = {movie.tmdb_id: movie for movie in Movie.query.filter(Movie.tmdb_id.in_(ids))} if ids else {}
            for movie in results:
                movie['existing'] = imported.get(movie['tmdb_id'])
        except TMDBError as failure:
            search_error = str(failure)
        except SQLAlchemyError:
            db.session.rollback()
            results = []
            search_error = 'CineWave could not check imported movies. Check database connectivity and Alembic revision.'
    return render_template('admin/import_movie.html', results=results, query=query, page=page,
                           total_pages=min(total_pages or 0, 500) if type(total_pages) is int else 0,
                           search_error=search_error)


def import_result(item, fields=None):
    release = fields['release_date'] if fields else parse_release_date(item.get('release_date'))
    language = clean_text(item.get('original_language'), 12)
    return {
        'tmdb_id': item['id'], 'title': clean_text(item.get('title')) or clean_text(item.get('original_title')),
        'overview': fields['description'] if fields else meaningful_overview(item.get('overview')),
        'poster_url': fields['poster'] if fields else image_url(item.get('poster_path')),
        'release_date': release.isoformat() if release else '', 'year': release.year if release else '',
        'language': LANGUAGES.get(language, language),
    }


@bp.route('/admin/import_movie/add/<int:tmdb_id>', methods=['POST'])
@login_required
def import_movie_add(tmdb_id):
    guard = admin_required()
    if guard:
        return guard
    query = request.form.get('query', '')[:120]
    page = min(500, max(1, request.form.get('page', 1, type=int)))
    search_url = url_for('admin.import_movie', query=query, page=page)
    if not 0 < tmdb_id <= 2_147_483_647:
        abort(400)
    try:
        existing = Movie.query.filter_by(tmdb_id=tmdb_id).first()
        if existing:
            flash(f'“{existing.title}” is already stored in CineWave.')
            return redirect(url_for('movies.movie_detail', movie_id=existing.id), code=303)
        featured_position = _parse_featured_position(request.form.get('featured_order'))
        with TMDBClient(attempts=1) as client:
            detail = client.details(tmdb_id)
            fields = movie_metadata(detail, client.region)
        if detail.get('adult') or not fields['title']:
            flash('This TMDB record cannot be imported. It needs an eligible movie title.')
            return redirect(search_url, code=303)
        supplied = {
            'description': meaningful_overview(request.form.get('description', '')[:4000]),
            'poster': authorized_poster_url(request.form.get('poster_url')),
        }
        overrides = [field for field, value in supplied.items() if value and not fields[field]]
        for field in overrides:
            fields[field] = supplied[field]
        if not minimum_metadata(fields):
            db.session.rollback()
            return render_template('admin/import_movie.html', results=[import_result(detail, fields)],
                                   query=query, page=page, total_pages=0, completion=request.form,
                                   missing_description=not fields['description'], missing_poster=not fields['poster']), 422
        trailer_source, trailer_key, cloudinary_url = trailer_selection(request.form)
        movie = matching_local_movie(fields)
        if movie is None:
            movie = create_movie(tmdb_id, fields)
            db.session.add(movie)
        else:
            movie.tmdb_id = tmdb_id
            apply_metadata(movie, fields)
        movie.lock_tmdb_fields(*overrides)
        movie.tmdb_last_checked_at = utc_now()
        category = request.form.get('category')
        if category in {'showing', 'upcoming'}:
            movie.is_upcoming = category == 'upcoming'
            movie.lock_tmdb_fields('is_upcoming')
        movie.is_rerelease = request.form.get('release_type') == 'rerelease'
        release = parse_release_date(request.form.get('release_date'))
        if release and release != fields['release_date']:
            movie.release_date = release
            if category not in {'showing', 'upcoming'}:
                movie.is_upcoming = release > cinema_now().date()
            movie.lock_tmdb_fields('release_date')
        if trailer_source != 'auto' or not movie.trailer_source:
            movie.trailer_source = trailer_source
            movie.youtube_trailer_key = trailer_key
            movie.cloudinary_trailer_url = cloudinary_url
        db.session.flush()
        if featured_position is not None and not movie.is_archived:
            _apply_featured_order(movie, featured_position)
        db.session.commit()
        flash(f'Saved “{movie.title}” in the CineWave catalogue.')
        return redirect(url_for('movies.movie_detail', movie_id=movie.id), code=303)
    except UnicodeError:
        db.session.rollback()
        flash('CineWave could not store the imported text. Check that the database uses UTF-8.')
    except (TMDBError, ValueError) as failure:
        db.session.rollback()
        flash(str(failure))
    except IntegrityError:
        db.session.rollback()
        try:
            existing = Movie.query.filter_by(tmdb_id=tmdb_id).first()
        except SQLAlchemyError:
            db.session.rollback()
            existing = None
        if existing:
            flash(f'“{existing.title}” is already stored in CineWave.')
            return redirect(url_for('movies.movie_detail', movie_id=existing.id), code=303)
        flash('The import conflicted with another update. Search again and retry.')
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.warning('tmdb_manual_import_database_failure tmdb_id=%d', tmdb_id)
        flash('CineWave could not save this movie. Check database connectivity and the Alembic revision, then retry.')
    return redirect(search_url, code=303)


@bp.route('/admin/toggle_movie_status/<int:movie_id>', methods=['POST'])
@login_required
def toggle_movie_status(movie_id):
    guard = admin_required()
    if guard:
        return guard
    movie = Movie.query.filter_by(id=movie_id).with_for_update().first_or_404()
    movie.is_upcoming = not movie.is_upcoming
    movie.lock_tmdb_fields('is_upcoming')
    db.session.commit()
    status_str = "Coming Soon" if movie.is_upcoming else "Now Showing"
    flash(f"Movie '{movie.title}' status changed to {status_str}!")
    return redirect(url_for('admin.admin'))


@bp.route('/admin/movie/<int:movie_id>/feature', methods=['POST'])
@login_required
def set_movie_featured_order(movie_id):
    guard = admin_required()
    if guard:
        return guard
    movie = Movie.query.get_or_404(movie_id)
    if movie.is_archived:
        abort(400, description='Archived movies cannot be featured.')
    position = _parse_featured_position(request.form.get('featured_order'))
    _apply_featured_order(movie, position)
    db.session.commit()
    action = f'featured at position {position}' if position else 'removed from featured movies'
    flash(f'"{movie.title}" was {action}.')
    visibility = request.args.get('visibility', 'active')
    if visibility not in {'active', 'archived', 'all'}:
        visibility = 'active'
    return redirect(url_for('admin.admin', q=request.args.get('q', ''),
                            visibility=visibility), code=303)


@bp.route('/admin/movie/<int:movie_id>/archive', methods=['POST'])
@login_required
def archive_movie(movie_id):
    guard = admin_required()
    if guard:
        return guard
    movie = Movie.query.get_or_404(movie_id)
    movie.is_archived = not movie.is_archived
    if movie.is_archived:
        _apply_featured_order(movie, None)
    db.session.commit()
    action = 'archived' if movie.is_archived else 'restored to the catalogue'
    flash(f'"{movie.title}" was {action}. Its booking and rating history was preserved.')
    return redirect(url_for('admin.admin', q=request.args.get('q', ''),
                            visibility='archived' if movie.is_archived else 'active'), code=303)


@bp.route('/admin/fetch_cast/<int:movie_id>', methods=['POST'])
@login_required
def fetch_cast(movie_id):
    """Pull cast + director from TMDb for an existing movie (admin action)."""
    guard = admin_required()
    if guard:
        return guard
    movie = Movie.query.get_or_404(movie_id)
    if not movie.tmdb_id:
        flash('Use TMDB import to link a verified match before fetching cast.')
        return redirect(url_for('admin.admin'), code=303)
    try:
        with TMDBClient(attempts=1) as client:
            fields = movie_metadata(client.details(movie.tmdb_id), client.region)
    except TMDBError as failure:
        flash(str(failure))
        return redirect(url_for('admin.admin'), code=303)
    if fields['cast_json']:
        movie = Movie.query.filter_by(id=movie_id).with_for_update().first_or_404()
        movie.cast_json = fields['cast_json']
        movie.tmdb_snapshot = {**(movie.tmdb_snapshot or {}), 'cast_json': movie.cast_json}
        db.session.commit()
        flash(f'Cast updated for “{movie.title}”.')
    else:
        flash('TMDB has no cast information for this movie.')
    return redirect(url_for('admin.admin'), code=303)


@bp.route('/admin/toggle_rerelease/<int:movie_id>', methods=['POST'])
@login_required
def toggle_rerelease(movie_id):
    guard = admin_required()
    if guard:
        return guard
    movie = Movie.query.get_or_404(movie_id)
    movie.is_rerelease = not movie.is_rerelease
    db.session.commit()
    rel_label = "Re-Release" if movie.is_rerelease else "Fresh Release"
    flash(f"'{movie.title}' is now marked as {rel_label}!")
    return redirect(url_for('admin.admin'))


@bp.route('/admin/delete_movie/<int:movie_id>', methods=['POST'])
@login_required
def delete_movie(movie_id):
    guard = admin_required()
    if guard:
        return guard
    # Lock the parent and shows before checking dependencies. PostgreSQL's FK
    # locks prevent a concurrent reservation from slipping past these checks.
    movie = Movie.query.filter_by(id=movie_id).with_for_update().first_or_404()
    title = movie.title
    try:
        shows = Showtime.query.filter_by(movie_id=movie_id).with_for_update().all()
        showtime_ids = [show.id for show in shows]
        if showtime_ids:
            # Ticket, payment and cancellation history must remain accessible.
            if Booking.query.filter(Booking.showtime_id.in_(showtime_ids)).first():
                db.session.rollback()
                flash(f"Movie '{title}' cannot be deleted because it has bookings. Booking and payment history has been kept.")
                return redirect(url_for('admin.admin'))
            if BookedSeat.query.filter(BookedSeat.showtime_id.in_(showtime_ids)).first():
                db.session.rollback()
                flash(f"Movie '{title}' cannot be deleted because it has confirmed seats.")
                return redirect(url_for('admin.admin'))

            now = datetime.utcnow()
            active_hold = SeatHold.query.filter(
                SeatHold.showtime_id.in_(showtime_ids), SeatHold.expires_at > now).first()
            active_lock = SeatLock.query.filter(
                SeatLock.showtime_id.in_(showtime_ids), SeatLock.expires_at > now).first()
            if active_hold or active_lock:
                db.session.rollback()
                flash(f"Movie '{title}' cannot be deleted while active seat holds exist. Please wait for checkout to finish or expire.")
                return redirect(url_for('admin.admin'))

            active_parties = PartySession.query.filter(
                PartySession.showtime_id.in_(showtime_ids), PartySession.status == 'ACTIVE',
                PartySession.created_at > now - PARTY_LIFETIME).all()
            if any(party.showtime.status != 'ended' for party in active_parties):
                db.session.rollback()
                flash(f"Movie '{title}' cannot be deleted while active Watch Together parties exist. Close the parties or wait for them to expire.")
                return redirect(url_for('admin.admin'))

            # Bulk deletes do not invoke ORM cascades. Remove transient child
            # rows first, then the shows, so PostgreSQL FK checks remain valid.
            party_ids = [party.id for party in PartySession.query.filter(
                PartySession.showtime_id.in_(showtime_ids)).all()]
            if party_ids:
                PartyMember.query.filter(PartyMember.party_id.in_(party_ids)).delete(synchronize_session='fetch')
                PartySession.query.filter(PartySession.id.in_(party_ids)).delete(synchronize_session='fetch')
            SeatHold.query.filter(SeatHold.showtime_id.in_(showtime_ids)).delete(synchronize_session='fetch')
            SeatLock.query.filter(SeatLock.showtime_id.in_(showtime_ids)).delete(synchronize_session='fetch')
            Showtime.query.filter(Showtime.id.in_(showtime_ids)).delete(synchronize_session='fetch')
        # Reviews and watchlist entries already have ORM delete cascades.
        db.session.delete(movie)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        app.logger.warning('Movie deletion blocked by related records (movie_id=%s)', movie_id)
        flash(f"Movie '{title}' could not be deleted because related records still exist. No changes were saved.")
        return redirect(url_for('admin.admin'))
    flash(f"Movie '{title}' has been deleted.")
    return redirect(url_for('admin.admin'))
