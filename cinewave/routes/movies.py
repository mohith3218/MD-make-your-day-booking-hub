from flask import Blueprint
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from ._support import *
from ..services.screen_reviews import eligible_screen
from ..services.seat import screening_availability

bp = Blueprint("movies", __name__)


@bp.route('/cine-match', methods=['GET', 'POST'])
def cine_match():
    movies = Movie.query.filter_by(is_archived=False).order_by(Movie.id.desc()).all()
    genres_by_movie = {movie.id: cinematch_genres(movie) for movie in movies}
    available_genres = sorted({genre for movie_genres in genres_by_movie.values() for genre in movie_genres})
    languages = sorted({movie.language.strip() for movie in movies if movie.language and movie.language.strip()}, key=str.casefold)

    mood = request.values.get('mood', '').strip().casefold()
    if mood not in CINEMATCH_MOODS:
        mood = ''
    language = request.values.get('language', '').strip()
    if language and language.casefold() not in {value.casefold() for value in languages}:
        language = ''
    genre = request.values.get('genre', '').strip()
    if genre.casefold() not in {value.casefold() for value in available_genres}:
        genre = ''
    runtime = request.values.get('time', 'any').strip().casefold()
    if runtime not in {'any', 'short', 'medium', 'long'}:
        runtime = 'any'

    preferences = negative_preferences = None
    saved_ids = set()
    personalization_count = 0
    if current_user.is_authenticated:
        preferences, negative_preferences, saved_ids, personalization_count = cinematch_preferences(current_user.id)

    results = []
    if request.method in {'GET', 'POST'}:
        candidates = []
        for movie in movies:
            movie_moods = {str(value).upper() for value in movie.moods}
            movie_genres = genres_by_movie[movie.id]
            duration = movie.duration or 0
            mood_codes = CINEMATCH_MOODS.get(mood, ())
            if mood_codes and not movie_moods.intersection(mood_codes):
                continue
            if genre and genre.casefold() not in {value.casefold() for value in movie_genres}:
                continue
            if language and language.casefold() != (movie.language or '').casefold():
                continue
            if runtime == 'short' and not (0 < duration < 100):
                continue
            if runtime == 'medium' and not (100 <= duration <= 150):
                continue
            if runtime == 'long' and not (duration > 150):
                continue

            score = 0
            why = []
            if mood_codes:
                score += 4
                why.append(f'Fits your {mood} mood')
            if genre:
                score += 3
                why.append(f'Matches {genre}')
            if language:
                score += 2
                why.append(f'Available in {movie.language}')
            if runtime != 'any':
                why.append({'short': 'Under 100 minutes', 'medium': '100–150 minutes', 'long': 'Over 150 minutes'}[runtime])

            if preferences:
                liked_moods, liked_genres, liked_languages = preferences
                disliked_moods, disliked_genres = negative_preferences
                mood_affinity = sum(liked_moods.get(value, 0) for value in movie_moods)
                genre_affinity = sum(liked_genres.get(value, 0) for value in movie_genres)
                language_affinity = liked_languages.get((movie.language or '').casefold(), 0)
                score += min(3, mood_affinity) + min(3, genre_affinity) + min(2, language_affinity)
                score -= min(3, sum(disliked_moods.get(value, 0) for value in movie_moods))
                score -= min(3, sum(disliked_genres.get(value, 0) for value in movie_genres))
                if mood_affinity or genre_affinity or language_affinity:
                    why.append('Similar to films you saved or rated highly')
            if movie.id in saved_ids:
                why.append('Already in your watchlist')
            candidates.append((score, movie, why))

        candidates.sort(key=lambda item: (-item[0], -(item[1].tmdb_rating or item[1].rating or 0),
                                          item[1].title.casefold()))
        results = [{'movie': movie, 'why': why or ['From the CineWave catalogue']}
                   for _, movie, why in candidates[:3]]

    return render_template('cine_match.html', results=results, mood=mood, language=language,
                           genre=genre, runtime=runtime, genres=available_genres,
                           languages=languages, personalization_count=personalization_count)


@bp.route('/movies/<int:movie_id>/hype', methods=['POST'])
@login_required
def vote_movie_hype(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    if movie.is_archived or not movie.is_upcoming:
        abort(404)
    level = request.form.get('level', '').strip().upper()
    if level not in {'HYPED', 'SUPER_HYPED', 'EXTREME_HYPED'}:
        abort(400, description='Choose a valid hype level.')
    insert = postgres_insert if db.engine.dialect.name == 'postgresql' else sqlite_insert
    vote = insert(MovieHypeVote).values(user_id=current_user.id, movie_id=movie.id, level=level)
    db.session.execute(vote.on_conflict_do_update(
        index_elements=[MovieHypeVote.user_id, MovieHypeVote.movie_id],
        set_={'level': vote.excluded.level, 'updated_at': datetime.utcnow()},
        where=MovieHypeVote.level != vote.excluded.level,
    ))
    counts = MovieHypeVote.counts_for(movie.id)
    db.session.commit()
    if request.accept_mimetypes.best == 'application/json':
        return jsonify(selected=level, counts=counts)
    flash(f'Your hype for {movie.title} is now {level.replace("_", " ").title()}.')
    if request.form.get('return_to') == 'movie':
        return redirect(url_for('.movie_detail', movie_id=movie.id) + '#movie-hype', code=303)
    return redirect(url_for('main.home', category='upcoming') + '#movies', code=303)


@bp.route('/movie/<int:movie_id>')
def movie_detail(movie_id):
    purge_expired_holds()
    movie = Movie.query.get_or_404(movie_id)
    if movie.is_archived and not current_user.is_admin:
        abort(404)
    all_shows = (Showtime.query.filter_by(movie_id=movie_id)
                 .order_by(Showtime.show_date, Showtime.id).all())

    shows = [s for s in all_shows if s.screen and s.status in {'upcoming', 'live'}]
    remaining_seats = {show_id: card['remaining'] for show_id, card in
                       screening_availability([s for s in shows if s.accepts_bookings]).items()}

    # group by date -> theatre so it reads like a real booking page
    grouped = {}
    for s in shows:
        grouped.setdefault(s.show_date, {}).setdefault(s.theater, []).append(s)

    hype_counts = MovieHypeVote.counts_for(movie.id) if movie.is_upcoming and not movie.is_archived else {}
    vote = MovieHypeVote.query.filter_by(user_id=current_user.id, movie_id=movie.id).first() if hype_counts else None
    return render_template('movie.html', movie=movie, showtimes=shows, grouped=grouped,
                           remaining_seats=remaining_seats, can_review=can_review_movie(movie),
                           movie_hype_counts=hype_counts, movie_hype_mine=vote.level if vote else None)


def can_review_movie(movie):
    if not current_user.is_authenticated or movie.is_archived:
        return False
    if not movie.tmdb_managed:
        return True
    bookings = Booking.query.join(Showtime).filter(
        Booking.user_id == current_user.id, Booking.status == 'PAID', Showtime.movie_id == movie.id,
        Showtime.show_date <= cinema_now().date()).all()
    return any(eligible_screen(booking, current_user.id) for booking in bookings)


@bp.route('/api/movies/by-mood/<mood_code>')
def movies_by_mood(mood_code):
    """Returns list of movies matching a specified mood code."""
    all_movies = Movie.query.filter_by(is_archived=False).all()
    if mood_code.upper() == 'ALL':
        matched = all_movies
    else:
        matched = [m for m in all_movies if mood_code.upper() in m.moods]
    return jsonify({
        'count': len(matched),
        'movies': [{
            'id': m.id,
            'title': m.title,
            'poster': m.poster,
            'duration': m.duration,
            'language': m.language,
            'certificate': m.certificate,
            'is_upcoming': m.is_upcoming,
            'release_date': m.release_date.strftime('%d %b %Y') if m.release_date else None,
            'moods': m.moods
        } for m in matched]
    })


@bp.route('/api/watchlist/toggle/<int:movie_id>', methods=['POST'])
@login_required
def toggle_watchlist(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    if movie.is_archived:
        abort(404)
    item = Watchlist.query.filter_by(user_id=current_user.id, movie_id=movie_id).first()
    if item:
        db.session.delete(item)
        db.session.commit()
        saved = False
        message = f"Removed '{movie.title}' from your watchlist."
    else:
        new_item = Watchlist(user_id=current_user.id, movie_id=movie_id)
        db.session.add(new_item)
        db.session.commit()
        saved = True
        message = f"Added '{movie.title}' to your watchlist!"

    count = Watchlist.query.filter_by(user_id=current_user.id).count()
    return jsonify({
        'success': True,
        'saved': saved,
        'movie_id': movie_id,
        'message': message,
        'watchlist_count': count
    })


@bp.route('/watchlist')
@login_required
def watchlist_page():
    return redirect(url_for('profile.profile') + '#watchlist')


@bp.route('/api/movie/<int:movie_id>/rate', methods=['POST'])
@login_required
def rate_movie(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    if not can_review_movie(movie):
        return jsonify({'success': False, 'message': 'Complete an eligible booked screening to review this film.'}), 403
    data = request.get_json(silent=True) or request.form
    try:
        score = float(data.get('rating', 0))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid rating score'}), 400

    if not 1.0 <= score <= 5.0:
        return jsonify({'success': False, 'message': 'Rating must be between 1 and 5 stars'}), 400

    review_text = (data.get('review') or '').strip()[:500]
    has_spoiler = bool(data.get('has_spoiler', False))
    # Auto-detect plot spoilers if not explicitly flagged
    if not has_spoiler and review_text:
        spoiler_triggers = ['die', 'dies', 'died', 'death', 'kill', 'kills', 'killed', 'murder',
                            'climax', 'twist', 'ending', 'ends with', 'post credit', 'villain is',
                            'culprit', 'betray', 'killer is']
        if any(trig in review_text.lower() for trig in spoiler_triggers):
            has_spoiler = True

    rating_obj = MovieRating.query.filter_by(user_id=current_user.id, movie_id=movie_id).first()
    is_new = False
    if rating_obj:
        rating_obj.rating = score
        rating_obj.review = review_text
        rating_obj.has_spoiler = has_spoiler
        rating_obj.created_at = datetime.utcnow()
    else:
        rating_obj = MovieRating(user_id=current_user.id, movie_id=movie_id, rating=score,
                                 review=review_text, has_spoiler=has_spoiler)
        db.session.add(rating_obj)
        is_new = True

    if is_new:
        current_user.points = (current_user.points or 0) + 5

    db.session.commit()

    return jsonify({
        'success': True,
        'message': f"You rated '{movie.title}' {score:.1f} ★" + (" (+5 CinePass Pts)" if is_new else ""),
        'rating': score,
        'has_spoiler': has_spoiler,
        'movie_avg_rating': movie.display_rating,
        'user_points': current_user.points
    })
