from cinewave.data import SAMPLE_LAYOUT
from cinewave.integrations.tmdb import parse_release_date
from cinewave.models import Movie
from cinewave.models import Screen
from cinewave.models import Showtime
from cinewave.models import Theater
from flask import abort
from cinewave.time import cinema_now
from flask_login import current_user
from datetime import datetime
from cinewave.extensions import db
from flask import flash
from flask_login import login_required
from flask import redirect
from flask import render_template
from flask import request
from werkzeug.utils import secure_filename
from vizag_theaters import seed_vizag_theaters
from flask import send_from_directory
from flask import url_for
from cinewave.services import admin_required
from urllib.parse import urlsplit
import json
import os
import re
import seat_layout as sl
import secrets

from . import bp


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
    return render_template('admin/add_theater.html')


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
    return render_template('admin/screens.html', theaters=Theater.query.order_by(Theater.name).all())


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
    return render_template('admin/add_screen.html', theaters=theaters,
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
    return render_template('admin/edit_layout.html', screen=screen, grid=grid,
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
    return render_template('admin/admin_auditorium_reference.html', screen=screen,
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

    return render_template('admin/add_showtime.html', movies=movies, theaters=theaters,
                           screens=screens_list, selected_movie=request.args.get('movie_id', type=int))
