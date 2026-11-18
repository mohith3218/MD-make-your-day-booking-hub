from flask import Blueprint
from urllib.parse import urlsplit
from ._support import *

bp = Blueprint("admin", __name__)


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
    movie_query = Movie.query
    if visibility == 'active':
        movie_query = movie_query.filter_by(is_archived=False)
    elif visibility == 'archived':
        movie_query = movie_query.filter_by(is_archived=True)
    if movie_search:
        movie_query = movie_query.filter(Movie.title.contains(movie_search, autoescape=True))
    movies = movie_query.order_by(Movie.is_archived, Movie.title).all()
    showtimes = Showtime.query.order_by(Showtime.show_date.desc()).all()
    theaters = Theater.query.all()
    screens = Screen.query.all()
    pending_recharges = RechargeRequest.query.filter_by(status='PENDING').count()
    revenue = db.session.query(db.func.sum(Booking.total_amount)) \
                        .filter(Booking.status == 'PAID').scalar() or 0
    return render_template('admin.html', movies=movies, showtimes=showtimes,
                           theaters=theaters, screens=screens,
                           movie_search=movie_search, movie_visibility=visibility,
                           pending_recharges=pending_recharges, revenue=revenue,
                           paid_count=Booking.query.filter_by(status='PAID').count())


@bp.route('/admin/add_movie', methods=['GET', 'POST'])
@login_required
def add_movie():
    guard = admin_required()
    if guard:
        return guard
    if request.method == 'POST':
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
                      language=request.form.get('language', 'Telugu'),
                      certificate=request.form.get('certificate', 'U/A'),
                      is_upcoming=is_upcoming,
                      is_rerelease=is_rerelease,
                      release_date=rel_date,
                      youtube_trailer_key=trailer_key or None,
                      trailer_video_path=trailer_path)
        db.session.add(movie)
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
    movie = Movie.query.get_or_404(movie_id)
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
        db.session.commit()
        flash(f"Uploaded trailer saved for '{movie.title}'.")
    elif trailer_input and trailer_key is None:
        flash('Trailer not changed: enter a valid YouTube video link or 11-character video ID.')
    elif trailer_input:
        movie.youtube_trailer_key = trailer_key or None
        movie.trailer_video_path = None
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
        if not TMDB_API_KEY:
            flash('TMDb search is unavailable because TMDB_API_KEY is not configured.')
        else:
            try:
                response = requests.get(f"{TMDB_BASE_URL}/search/movie",
                    params={'api_key': TMDB_API_KEY, 'query': query}, timeout=(3.05, 8))
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
                    raise ValueError('TMDb returned an invalid search response.')
                for item in payload['results'][:8]:
                    if not isinstance(item, dict) or not item.get('id') or not item.get('title'):
                        continue
                    poster_path = item.get('poster_path')
                    release_date = item.get('release_date', '') or ''
                    try:
                        release = date.fromisoformat(release_date[:10]) if release_date else None
                    except ValueError:
                        release = None
                    results.append({'tmdb_id': item['id'], 'title': item['title'],
                        'overview': item.get('overview', ''),
                        'poster_url': f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else None,
                        'release_date': release_date, 'year': release_date[:4] if release_date else '',
                        'suggested_category': 'upcoming' if release and release > date.today() else 'showing'})
            except (requests.RequestException, ValueError, TypeError):
                flash('TMDb could not complete the search. Check the credentials or try again shortly.')
    return render_template('import_movie.html', results=results, query=query)


@bp.route('/admin/import_movie/add/<int:tmdb_id>', methods=['POST'])
@login_required
def import_movie_add(tmdb_id):
    guard = admin_required()
    if guard:
        return guard
    try:
        existing = Movie.query.filter_by(tmdb_id=tmdb_id).first()
        if existing:
            flash(f'"{existing.title}" is already stored in CineWave.')
            return redirect(url_for('movies.movie_detail', movie_id=existing.id), code=303)
        try:
            trailer_path = save_trailer_upload(request.files.get('trailer_video'))
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for('admin.admin'))
        trailer_key = ('' if trailer_path else
                       parse_youtube_video_key(request.form.get('youtube_trailer')))
        raw_trailer = request.form.get('youtube_trailer', '').strip()
        if raw_trailer and trailer_key is None and not trailer_path:
            flash('Enter a valid YouTube video link or 11-character video ID.')
            return redirect(url_for('admin.import_movie', query=request.form.get('query', '')), code=303)
        if not TMDB_API_KEY:
            flash('TMDb import is unavailable because TMDB_API_KEY is not configured.')
            return redirect(url_for('admin.import_movie'), code=303)
        detail_response = requests.get(f"{TMDB_BASE_URL}/movie/{tmdb_id}",
                           params={'api_key': TMDB_API_KEY}, timeout=(3.05, 8))
        detail_response.raise_for_status()
        res = detail_response.json()
        if not isinstance(res, dict) or res.get('id') != tmdb_id or not res.get('title'):
            raise ValueError('TMDb returned invalid movie details.')
        poster_path = res.get('poster_path')
        category = request.form.get('category', 'showing')
        is_upcoming = (category == 'upcoming')
        is_rerelease = (request.form.get('release_type', 'fresh') == 'rerelease')

        rel_date_str = request.form.get('release_date', '').strip() or res.get('release_date', '')
        rel_date = None
        if rel_date_str:
            try:
                rel_date = datetime.strptime(rel_date_str[:10], '%Y-%m-%d').date()
            except ValueError:
                rel_date = None

        movie = Movie(title=res.get('title', 'Untitled'),
                      description=res.get('overview', 'No overview available.'),
                      duration=res.get('runtime') or 120,
                      poster=f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else None,
                      language=(res.get('original_language') or 'te').upper(),
                      is_upcoming=is_upcoming,
                      is_rerelease=is_rerelease,
                      release_date=rel_date,
                      tmdb_id=tmdb_id,
                      youtube_trailer_key=trailer_key or None,
                      trailer_video_path=trailer_path)
        db.session.add(movie)
        db.session.commit()

        # Credits are fetched for the exact selected TMDb ID.
        cast_saved = _store_movie_cast(movie, tmdb_id)

        cat_label = 'Coming Soon' if is_upcoming else 'Now Showing'
        rel_label = ' (Re-Release)' if is_rerelease else ''
        cast_note = ' with cast' if cast_saved else ''
        flash(f'Imported "{movie.title}" as {cat_label}{rel_label}{cast_note}.')
        return redirect(url_for('movies.movie_detail', movie_id=movie.id), code=303)
    except (requests.RequestException, ValueError, TypeError):
        db.session.rollback()
        flash('TMDb did not return usable details. The film was not imported; try again shortly.')
        return redirect(url_for('admin.import_movie'), code=303)
    except IntegrityError:
        db.session.rollback()
        existing = Movie.query.filter_by(tmdb_id=tmdb_id).first()
        if existing:
            flash(f'"{existing.title}" is already stored in CineWave.')
            return redirect(url_for('movies.movie_detail', movie_id=existing.id), code=303)
        flash('The import conflicted with another update. Search again and retry.')
        return redirect(url_for('admin.import_movie'), code=303)


@bp.route('/admin/toggle_movie_status/<int:movie_id>', methods=['POST'])
@login_required
def toggle_movie_status(movie_id):
    guard = admin_required()
    if guard:
        return guard
    movie = Movie.query.get_or_404(movie_id)
    movie.is_upcoming = not movie.is_upcoming
    db.session.commit()
    status_str = "Coming Soon" if movie.is_upcoming else "Now Showing"
    flash(f"Movie '{movie.title}' status changed to {status_str}!")
    return redirect(url_for('admin.admin'))


@bp.route('/admin/movie/<int:movie_id>/archive', methods=['POST'])
@login_required
def archive_movie(movie_id):
    guard = admin_required()
    if guard:
        return guard
    movie = Movie.query.get_or_404(movie_id)
    movie.is_archived = not movie.is_archived
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

    tmdb_id = movie.tmdb_id or _tmdb_find_id(movie.title)
    if not tmdb_id:
        flash(f"Could not find '{movie.title}' on TMDb. Try adding the TMDb id manually.")
        return redirect(url_for('admin.admin'))

    if _store_movie_cast(movie, tmdb_id):
        flash(f"Cast updated for '{movie.title}'!")
    else:
        flash(f"TMDb reachable but no cast found for '{movie.title}'.")
    return redirect(url_for('admin.admin'))


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
    movies = Movie.query.all()
    theaters = Theater.query.all()
    screens_list = Screen.query.all()

    if request.method == 'POST':
        screen = Screen.query.get_or_404(int(request.form['screen_id']))
        overrides = {}
        for cls in screen.layout.get('classes', []):
            val = request.form.get(f"price_{cls['code']}", '').strip()
            if val:
                try:
                    overrides[cls['code']] = float(val)
                except ValueError:
                    pass

        show = Showtime(movie_id=int(request.form['movie_id']),
                        screen_id=screen.id,
                        theater=screen.theater.name,
                        show_date=datetime.strptime(request.form['show_date'], '%Y-%m-%d').date(),
                        show_time=request.form['show_time'],
                        price_overrides_json=json.dumps(overrides))
        db.session.add(show)
        db.session.commit()
        flash("Showtime added successfully!")
        return redirect(url_for('admin.admin'))

    return render_template('add_showtime.html', movies=movies, theaters=theaters,
                           screens=screens_list)


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
