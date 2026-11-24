from flask import Blueprint
from pathlib import Path
from urllib.parse import urlsplit
from sqlalchemy.orm import joinedload
from ._support import *
from ..services.movie_sync import (
    STATE_ID, apply_metadata, create_movie, credentials_configured, matching_local_movie,
    request_movie_sync, sync_status, utc_now,
)
from ..services.movies import (
    TMDBClient, TMDBError, image_url, minimum_metadata, movie_metadata, parse_release_date,
)

bp = Blueprint("admin", __name__)
MAX_FEATURED_MOVIES = 5


def save_trailer_upload(upload):
    """Store an optional MP4/WebM with a random name under the static media path."""
    if not upload or not upload.filename:
        return None
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in {'.mp4', '.webm'}:
        raise ValueError('Trailer uploads must be MP4 or WebM files.')
    filename = secrets.token_hex(16) + suffix
    relative_path = Path('uploads') / 'trailers' / filename
    target = Path(app.static_folder) / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    upload.save(target)
    return relative_path.as_posix()


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
    return render_template('admin.html', movies=movie_page.items, showtimes=showtimes,
                           theaters=theaters, screens=screens,
                           movie_search=movie_search, movie_visibility=visibility,
                           movie_page=movie_page, movie_filters=filters, movie_languages=languages,
                           scheduled_ids=scheduled_ids, sync_state=state, sync_status=sync_status(state),
                           sync_configured=credentials_configured(),
                           pending_recharges=pending_recharges, revenue=revenue,
                           paid_count=Booking.query.filter_by(status='PAID').count())


@bp.post('/admin/movies/sync')
@login_required
def queue_movie_sync():
    guard = admin_required()
    if guard:
        return guard
    if not credentials_configured():
        abort(400, description='Configure TMDB credentials first.')
    request_movie_sync()
    flash('TMDB synchronization queued for the next worker check-in.')
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
            return render_template('edit_movie.html', movie=movie), 400
        fields['duration'] = int(runtime) if runtime else 0
        changed = [name for name, value in fields.items() if value != getattr(movie, name)]
        for name in changed:
            setattr(movie, name, fields[name])
        if changed:
            movie.lock_tmdb_fields(*changed)
            db.session.commit()
        flash('Movie details saved.')
        return redirect(url_for('admin.admin', _anchor='movies'), code=303)
    return render_template('edit_movie.html', movie=movie)


@bp.route('/admin/add_movie', methods=['GET', 'POST'])
@login_required
def add_movie():
    guard = admin_required()
    if guard:
        return guard
    if request.method == 'POST':
        featured_position = _parse_featured_position(request.form.get('featured_order'))
        try:
            trailer_path = save_trailer_upload(request.files.get('trailer_video'))
        except ValueError as exc:
            flash(str(exc))
            return render_template('add_movie.html'), 400
        trailer_key = ('' if trailer_path else
                       parse_youtube_video_key(request.form.get('youtube_trailer')))
        if trailer_key is None:
            flash('Enter a valid YouTube video link or 11-character video ID.')
            return render_template('add_movie.html'), 400
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
                      youtube_trailer_key=trailer_key or None,
                      trailer_video_path=trailer_path)
        db.session.add(movie)
        db.session.flush()
        if featured_position is not None:
            _apply_featured_order(movie, featured_position)
        db.session.commit()
        cat_label = 'Coming Soon' if is_upcoming else 'Now Showing'
        rel_label = ' (Re-Release)' if is_rerelease else ''
        flash(f"Movie '{movie.title}' added to {cat_label}{rel_label}!")
        return redirect(url_for('admin.admin'))
    return render_template('add_movie.html')


@bp.route('/admin/movie/<int:movie_id>/trailer', methods=['POST'])
@login_required
def update_movie_trailer(movie_id):
    guard = admin_required()
    if guard:
        return guard
    movie = Movie.query.filter_by(id=movie_id).with_for_update().first_or_404()
    try:
        trailer_path = save_trailer_upload(request.files.get('trailer_video'))
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for('admin.admin'))
    trailer_input = request.form.get('youtube_trailer', '').strip()
    trailer_key = parse_youtube_video_key(trailer_input) if trailer_input else None
    if trailer_path:
        movie.trailer_video_path = trailer_path
        movie.youtube_trailer_key = None
        movie.lock_tmdb_fields('youtube_trailer_key')
        db.session.commit()
        flash(f"Uploaded trailer saved for '{movie.title}'.")
    elif trailer_input and trailer_key is None:
        flash('Trailer not changed: enter a valid YouTube video link or 11-character video ID.')
    elif trailer_input:
        movie.youtube_trailer_key = trailer_key or None
        movie.trailer_video_path = None
        movie.lock_tmdb_fields('youtube_trailer_key')
        db.session.commit()
        flash(f"YouTube trailer saved for '{movie.title}'.")
    return redirect(url_for('admin.admin'))


@bp.route('/admin/import_movie', methods=['GET'])
@login_required
def import_movie():
    guard = admin_required()
    if guard:
        return guard
    results, query = [], request.args.get('query', '').strip()[:120]
    if query:
        try:
            with TMDBClient(attempts=1) as client:
                items = client.search(query).get('results')
            if not isinstance(items, list):
                raise TMDBError('TMDB returned invalid search results.')
            for item in items[:8]:
                if (not isinstance(item, dict) or type(item.get('id')) is not int
                        or item['id'] <= 0 or not item.get('title') or item.get('adult')):
                    continue
                release = parse_release_date(item.get('release_date'))
                results.append({
                    'tmdb_id': item['id'], 'title': item['title'], 'overview': item.get('overview'),
                    'poster_url': image_url(item.get('poster_path')),
                    'release_date': release.isoformat() if release else '',
                    'year': release.year if release else '',
                    'suggested_category': 'upcoming' if release and release > cinema_now().date() else 'showing',
                })
        except TMDBError as failure:
            flash(str(failure))
    return render_template('import_movie.html', results=results, query=query)


@bp.route('/admin/import_movie/add/<int:tmdb_id>', methods=['POST'])
@login_required
def import_movie_add(tmdb_id):
    guard = admin_required()
    if guard:
        return guard
    search_url = url_for('admin.import_movie', query=request.form.get('query', ''))
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
        if detail.get('adult') or not minimum_metadata(fields):
            flash('TMDB records need a title, description, and poster before import.')
            return redirect(search_url, code=303)
        trailer_input = request.form.get('youtube_trailer', '').strip()
        trailer_upload = request.files.get('trailer_video')
        trailer_key = parse_youtube_video_key(trailer_input)
        if trailer_input and trailer_key is None and not (trailer_upload and trailer_upload.filename):
            flash('Enter a valid YouTube video link or 11-character video ID.')
            return redirect(search_url, code=303)
        movie = matching_local_movie(fields)
        if movie is None:
            movie = create_movie(tmdb_id, fields)
            db.session.add(movie)
        else:
            movie.tmdb_id = tmdb_id
            apply_metadata(movie, fields)
        movie.tmdb_last_checked_at = utc_now()
        category = request.form.get('category')
        if category in {'showing', 'upcoming'}:
            movie.is_upcoming = category == 'upcoming'
            movie.lock_tmdb_fields('is_upcoming')
        movie.is_rerelease = request.form.get('release_type') == 'rerelease'
        release = parse_release_date(request.form.get('release_date'))
        if release and release != fields['tmdb_original_release_date']:
            movie.release_date = release
            movie.lock_tmdb_fields('release_date')
        trailer_path = save_trailer_upload(trailer_upload)
        if trailer_path or trailer_key:
            movie.youtube_trailer_key = None if trailer_path else trailer_key
            movie.trailer_video_path = trailer_path
            movie.lock_tmdb_fields('youtube_trailer_key')
        db.session.flush()
        if featured_position is not None and not movie.is_archived:
            _apply_featured_order(movie, featured_position)
        db.session.commit()
        flash(f'Saved “{movie.title}” in the CineWave catalogue.')
        return redirect(url_for('movies.movie_detail', movie_id=movie.id), code=303)
    except (TMDBError, ValueError) as failure:
        db.session.rollback()
        flash(str(failure) if isinstance(failure, TMDBError) else 'Check the trailer file and try again.')
    except IntegrityError:
        db.session.rollback()
        existing = Movie.query.filter_by(tmdb_id=tmdb_id).first()
        if existing:
            flash(f'“{existing.title}” is already stored in CineWave.')
            return redirect(url_for('movies.movie_detail', movie_id=existing.id), code=303)
        flash('The import conflicted with another update. Search again and retry.')
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


def _save_directory_verification(record):
    status = request.form.get('verification_status', '').strip().lower()
    if status not in {'unverified', 'needs_review', 'verified'}:
        abort(400, description='Choose a valid directory verification status.')
    source = request.form.get('verification_source_url', '').strip()[:500]
    if source:
        parsed = urlsplit(source)
        if parsed.scheme != 'https' or not parsed.netloc:
            abort(400, description='Evidence links must use HTTPS and include a host name.')
    if status == 'verified' and not source:
        abort(400, description='Add an HTTPS source before marking this listing verified.')
    record.verification_status = status
    record.verification_source_url = source or None
    record.verification_notes = request.form.get('verification_notes', '').strip()[:2000] or None
    record.verification_reviewed_at = datetime.utcnow()
    record.verification_reviewed_by_id = current_user.id
    db.session.commit()


@bp.route('/admin/theater/<int:theater_id>/verify', methods=['POST'])
@login_required
def verify_theater(theater_id):
    guard = admin_required()
    if guard:
        return guard
    theater = Theater.query.get_or_404(theater_id)
    _save_directory_verification(theater)
    flash(f'Directory review saved for {theater.name}.')
    return redirect(url_for('admin.screens') + f'#theater-{theater.id}', code=303)


@bp.route('/admin/screen/<int:screen_id>/verify', methods=['POST'])
@login_required
def verify_screen(screen_id):
    guard = admin_required()
    if guard:
        return guard
    screen = Screen.query.get_or_404(screen_id)
    _save_directory_verification(screen)
    flash(f'Directory review saved for {screen.theater.name} · {screen.name}.')
    return redirect(url_for('admin.screens') + f'#screen-{screen.id}', code=303)


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


@bp.route('/admin/add_theater', methods=['GET', 'POST'])
@login_required
def add_theater():
    guard = admin_required()
    if guard:
        return guard
    if request.method == 'POST':
        name = request.form['name'].strip()
        if not name:
            flash("Theater name is required")
            return redirect(url_for('admin.add_theater'))
        if Theater.query.filter_by(name=name).first():
            flash(f'A theater named "{name}" already exists')
            return redirect(url_for('admin.add_theater'))
        db.session.add(Theater(name=name,
                               location=request.form.get('location', '').strip(),
                               city=request.form.get('city', 'Visakhapatnam').strip(),
                               address=request.form.get('address', '').strip()))
        db.session.commit()
        flash(f'Theater "{name}" added. Now add its screens and seat layout.')
        return redirect(url_for('admin.screens'))
    return render_template('add_theater.html')


@bp.route('/admin/seed_vizag', methods=['POST'])
@login_required
def seed_vizag():
    guard = admin_required()
    if guard:
        return guard
    t, s = seed_vizag_theaters(db, Theater, Screen, verbose=False)
    flash(f"Loaded Vizag theatres: +{t} theatres, +{s} screens with real seat layouts.")
    return redirect(url_for('admin.screens'))


@bp.route('/admin/screens')
@login_required
def screens():
    guard = admin_required()
    if guard:
        return guard
    return render_template('screens.html', theaters=Theater.query.order_by(Theater.name).all())


@bp.route('/admin/add_screen', methods=['GET', 'POST'])
@login_required
def add_screen():
    guard = admin_required()
    if guard:
        return guard
    theaters = Theater.query.all()
    if request.method == 'POST':
        theater_id = int(request.form['theater_id'])
        name = request.form['name'].strip()
        raw = request.form.get('layout_json', '').strip() or '{"classes": []}'
        try:
            layout = json.loads(raw)
        except json.JSONDecodeError as e:
            flash(f"Layout JSON is invalid: {e}")
            return redirect(url_for('admin.add_screen'))
        geometry_errors = sl.validate_auditorium_geometry(layout)
        if geometry_errors:
            flash("Screen layout was not added: " + " ".join(geometry_errors[:4]))
            return redirect(url_for('admin.add_screen'))
        screen = Screen(theater_id=theater_id, name=name,
                        screen_type=request.form.get('screen_type', '2D'))
        screen.layout = layout
        db.session.add(screen)
        db.session.commit()
        flash(f"Screen '{name}' added with {screen.total_seats} seats.")
        return redirect(url_for('admin.edit_layout', screen_id=screen.id))
    return render_template('add_screen.html', theaters=theaters,
                           sample=json.dumps(SAMPLE_LAYOUT, indent=2))


@bp.route('/admin/screen/<int:screen_id>/layout', methods=['GET', 'POST'])
@login_required
def edit_layout(screen_id):
    """Edit a screen's seating arrangement and preview it exactly as users see it."""
    guard = admin_required()
    if guard:
        return guard
    screen = Screen.query.get_or_404(screen_id)

    if request.method == 'POST':
        try:
            layout = json.loads(request.form['layout_json'])
        except json.JSONDecodeError as e:
            flash(f"Layout JSON is invalid: {e}")
            return redirect(url_for('admin.edit_layout', screen_id=screen_id))
        geometry_errors = sl.validate_auditorium_geometry(layout)
        if geometry_errors:
            flash("Layout was not saved: " + " ".join(geometry_errors[:4]))
            return redirect(url_for('admin.edit_layout', screen_id=screen_id))
        screen.layout = layout
        db.session.commit()
        flash(f"Layout saved — {screen.total_seats} seats.")
        return redirect(url_for('admin.edit_layout', screen_id=screen_id))

    grid = sl.build_layout(screen.layout)
    return render_template('edit_layout.html', screen=screen, grid=grid,
                           layout_json=json.dumps(screen.layout, indent=2),
                           geometry_json=json.dumps({
                               'screen': (screen.layout or {}).get('screen', {}),
                               'room': (screen.layout or {}).get('room', {}),
                               'levels': (screen.layout or {}).get('levels', []),
                           }, indent=2))


@bp.route('/admin/screen/<int:screen_id>/auditorium-reference', methods=['GET', 'POST'])
@login_required
def edit_auditorium_reference(screen_id):
    """Review per-screen interior-photo evidence and editable visual metadata."""
    guard = admin_required()
    if guard:
        return guard
    screen = Screen.query.get_or_404(screen_id)
    layout = screen.layout or {}
    profile = layout.get('reference_profile') or {
        'theater': screen.theater.name, 'screen': screen.name,
        'reference_status': 'estimated_model', 'references': [],
        'architecture': {}, 'confidence': {'appearance': 'low', 'geometry': 'estimated'},
    }

    if request.method == 'POST':
        try:
            profile = json.loads(request.form.get('profile_json', '{}'))
            if not isinstance(profile, dict) or not isinstance(profile.get('references', []), list):
                raise ValueError('Profile must be an object with a references array.')
            profile['theater'] = screen.theater.name
            profile['screen'] = screen.name
            profile['administrator_edited'] = True
        except (json.JSONDecodeError, ValueError) as error:
            flash(f'Reference profile was not saved: {error}')
            return redirect(url_for('admin.edit_auditorium_reference', screen_id=screen.id))

        image_file = request.files.get('reference_image')
        if image_file and image_file.filename:
            extension = os.path.splitext(secure_filename(image_file.filename))[1].lower()
            if extension not in {'.jpg', '.jpeg', '.png', '.webp'}:
                flash('Upload a JPG, PNG, or WebP auditorium photo.')
                return redirect(url_for('admin.edit_auditorium_reference', screen_id=screen.id))
            image_file.stream.seek(0, os.SEEK_END)
            image_size = image_file.stream.tell()
            image_file.stream.seek(0)
            if image_size > 10 * 1024 * 1024:
                flash('Reference photos must be 10 MB or smaller.')
                return redirect(url_for('admin.edit_auditorium_reference', screen_id=screen.id))
            filename = secrets.token_hex(16) + extension
            private_dir = os.path.join(current_app.instance_path, 'auditorium_references')
            os.makedirs(private_dir, exist_ok=True)
            image_file.save(os.path.join(private_dir, filename))
            profile.setdefault('references', []).append({
                'source_url': '', 'image_url': url_for('admin.admin_auditorium_reference_file', filename=filename),
                'view': 'unknown', 'screen_verified': False, 'captured_at': None,
                'license': 'administrator_uploaded_review_required', 'approved_for_use': False,
                'notes': 'Administrator upload; confirm venue, screen, date, and permissions before approval.'
            })

        layout['reference_profile'] = profile
        screen.layout = layout
        db.session.commit()
        flash('Auditorium reference profile saved.')
        return redirect(url_for('admin.edit_auditorium_reference', screen_id=screen.id))

    preview_url = url_for('booking.vr_seat_preview', showtime_id=0, admin_screen=screen.id, embed=1)
    return render_template('admin_auditorium_reference.html', screen=screen,
                           profile_json=json.dumps(profile, indent=2),
                           preview_url=preview_url)


@bp.route('/admin/auditorium-reference-file/<filename>')
@login_required
def admin_auditorium_reference_file(filename):
    guard = admin_required()
    if guard:
        return guard
    # Only random filenames generated by the upload handler are accepted.
    if not re.fullmatch(r'[a-f0-9]{32}\.(?:jpg|jpeg|png|webp)', filename):
        abort(404)
    return send_from_directory(os.path.join(current_app.instance_path, 'auditorium_references'),
                               filename, max_age=0)


@bp.route('/admin/add_showtime', methods=['GET', 'POST'])
@login_required
def add_showtime():
    guard = admin_required()
    if guard:
        return guard
    movies = Movie.query.filter_by(is_archived=False).order_by(Movie.title).all()
    theaters = Theater.query.all()
    screens_list = Screen.query.all()

    if request.method == 'POST':
        screen = Screen.query.get_or_404(request.form.get('screen_id', type=int))
        movie = Movie.query.filter_by(id=request.form.get('movie_id', type=int),
                                      is_archived=False).first_or_404()
        overrides = {}
        for cls in screen.layout.get('classes', []):
            val = request.form.get(f"price_{cls['code']}", '').strip()
            if val:
                try:
                    price = float(val)
                    if not 0 < price < float('inf'):
                        raise ValueError
                    overrides[cls['code']] = price
                except ValueError:
                    abort(400, description='Enter a positive ticket price.')

        show_date = parse_release_date(request.form.get('show_date'))
        if not show_date:
            abort(400, description='Enter a valid screening date.')
        show = Showtime(movie_id=movie.id,
                        screen_id=screen.id,
                        theater=screen.theater.name,
                        show_date=show_date,
                        show_time=request.form.get('show_time', '')[:20],
                        price_overrides_json=json.dumps(overrides))
        if not show.show_datetime or show.show_datetime <= cinema_now():
            abort(400, description='Enter a future screening date and time.')
        db.session.add(show)
        db.session.commit()
        flash("Showtime added successfully!")
        return redirect(url_for('admin.admin'))

    return render_template('add_showtime.html', movies=movies, theaters=theaters,
                           screens=screens_list, selected_movie=request.args.get('movie_id', type=int))


@bp.route('/admin/recharges')
@login_required
def admin_recharges():
    guard = admin_required()
    if guard:
        return guard
    reqs = RechargeRequest.query.order_by(RechargeRequest.created_at.desc()).all()
    return render_template('admin_recharges.html', requests=reqs)


@bp.route('/admin/recharges/<int:req_id>/<action>', methods=['POST'])
@login_required
def handle_recharge(req_id, action):
    guard = admin_required()
    if guard:
        return guard
    req = RechargeRequest.query.get_or_404(req_id)
    if req.status != 'PENDING':
        flash("Already processed.")
        return redirect(url_for('admin.admin_recharges'))

    if action == 'approve':
        wallet = get_wallet(req.user)
        wallet.balance = round(wallet.balance + req.amount, 2)
        db.session.add(WalletTransaction(wallet_id=wallet.id, amount=req.amount,
                                         type='RECHARGE',
                                         description='Admin approved recharge'))
        req.status = 'APPROVED'
        flash(f"₹{req.amount:.0f} credited to {req.user.username}.")
    elif action == 'reject':
        req.status = 'REJECTED'
        flash("Recharge request rejected.")
    db.session.commit()
    return redirect(url_for('admin.admin_recharges'))


@bp.route('/admin/bookings')
@login_required
def admin_bookings():
    guard = admin_required()
    if guard:
        return guard
    bookings = Booking.query.order_by(Booking.booked_at.desc()).limit(100).all()
    return render_template('admin_bookings.html', bookings=bookings)


@bp.route('/admin/analytics')
@login_required
def admin_analytics():
    guard = admin_required()
    if guard:
        return guard
    try:
        days = int(request.args.get('days', '') or 0)
    except ValueError:
        days = 0
    if days not in (7, 30, 90):
        days = 0
    data = _collect_analytics(days)
    return render_template('admin_analytics.html', a=data, days=days)


@bp.route('/admin/analytics/export.csv')
@login_required
def admin_analytics_export():
    guard = admin_required()
    if guard:
        return guard
    try:
        days = int(request.args.get('days', '') or 0)
    except ValueError:
        days = 0
    if days not in (7, 30, 90):
        days = 0

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['reference', 'booked_at', 'status', 'movie', 'theatre',
                     'screen', 'show_date', 'show_time', 'seats', 'seat_count',
                     'ticket_amount', 'convenience_fee', 'gst', 'total_amount',
                     'method', 'paid_at', 'payment_mode'])
    for b in _analytics_bookings(days):
        payment = b.payment
        writer.writerow([
            b.reference,
            b.booked_at.strftime('%Y-%m-%d %H:%M') if b.booked_at else '',
            b.status,
            b.showtime.movie.title,
            b.showtime.theater,
            b.showtime.screen_label,
            b.showtime.show_date.isoformat(),
            b.showtime.show_time,
            b.seats,
            len(b.seat_list),
            f"{b.ticket_amount:.2f}",
            f"{b.convenience_fee:.2f}",
            f"{b.gst:.2f}",
            f"{b.total_amount:.2f}",
            payment.method if payment else '',
            b.paid_at.strftime('%Y-%m-%d %H:%M') if b.paid_at else '',
            'DEMO - not settled' if payment and payment.is_demo else 'Historical record',
        ])

    stamp = datetime.utcnow().strftime('%Y%m%d_%H%M')
    resp = app.response_class(out.getvalue(), mimetype='text/csv')
    resp.headers['Content-Disposition'] = f'attachment; filename=cinewave_bookings_{stamp}.csv'
    return resp
