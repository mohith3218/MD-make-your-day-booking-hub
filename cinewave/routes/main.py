from flask import Blueprint
from ._support import *

bp = Blueprint("main", __name__)


@bp.route('/')
def home():
    # Now Showing
    now_showing_releases = Movie.query.filter(
        Movie.is_archived.is_(False),
        (Movie.is_upcoming.is_(False)) | (Movie.is_upcoming.is_(None)),
        (Movie.is_rerelease.is_(False)) | (Movie.is_rerelease.is_(None))
    ).order_by(Movie.id.desc()).all()
    
    now_showing_rereleases = Movie.query.filter(
        Movie.is_archived.is_(False),
        (Movie.is_upcoming.is_(False)) | (Movie.is_upcoming.is_(None)),
        Movie.is_rerelease.is_(True)
    ).order_by(Movie.id.desc()).all()

    # Coming Soon
    coming_soon_releases = Movie.query.filter(
        Movie.is_archived.is_(False),
        Movie.is_upcoming.is_(True),
        (Movie.is_rerelease.is_(False)) | (Movie.is_rerelease.is_(None))
    ).order_by(Movie.release_date.asc(), Movie.id.desc()).all()

    coming_soon_rereleases = Movie.query.filter(
        Movie.is_archived.is_(False),
        Movie.is_upcoming.is_(True),
        Movie.is_rerelease.is_(True)
    ).order_by(Movie.release_date.asc(), Movie.id.desc()).all()

    # The landing-page screening cards use the same live schedule as booking.
    scheduled_shows = (Showtime.query.join(Movie, Showtime.movie_id == Movie.id)
                       .filter(Movie.is_archived.is_(False), Showtime.show_date >= cinema_now().date())
                       .order_by(Showtime.show_date, Showtime.id).all())
    scheduled_shows = [show for show in scheduled_shows if show.status == 'upcoming' and show.seats_left > 0]
    screening_dates = sorted({show.show_date for show in scheduled_shows})[:5]
    screening_groups = {}
    for show in scheduled_shows:
        if show.show_date in screening_dates:
            screening_groups.setdefault(show.show_date, {}).setdefault(show.theater, []).append(show)
    featured_movies = (Movie.query.filter(
        Movie.is_archived.is_(False), Movie.featured_order.isnot(None)
    ).order_by(Movie.featured_order.asc(), Movie.id.asc()).limit(5).all())
    # Keep the hero populated from the live catalogue until an administrator
    # publishes an explicit feature order. Prefer real screenings with seats,
    # then other active releases, and finally upcoming releases.
    if not featured_movies:
        fallback_movies = []
        included_ids = set()
        for show in scheduled_shows:
            if show.movie_id not in included_ids:
                fallback_movies.append(show.movie)
                included_ids.add(show.movie_id)
        for movie in (now_showing_releases + now_showing_rereleases
                      + coming_soon_releases + coming_soon_rereleases):
            if movie.id not in included_ids:
                fallback_movies.append(movie)
                included_ids.add(movie.id)
        featured_movies = fallback_movies[:5]
    featured_shows_by_movie = {}
    featured_ids = {movie.id for movie in featured_movies}
    for show in scheduled_shows:
        if show.movie_id in featured_ids:
            featured_shows_by_movie.setdefault(show.movie_id, show)
    active_category = request.args.get('category', 'showing').strip().lower()
    if active_category not in {'showing', 'upcoming'}:
        active_category = 'showing'
    search_query = request.args.get('q', '').strip()[:100]
    if search_query:
        query_lower = search_query.casefold()
        now_showing_releases = [movie for movie in now_showing_releases if query_lower in movie.title.casefold()]
        now_showing_rereleases = [movie for movie in now_showing_rereleases if query_lower in movie.title.casefold()]
        coming_soon_releases = [movie for movie in coming_soon_releases if query_lower in movie.title.casefold()]
        coming_soon_rereleases = [movie for movie in coming_soon_rereleases if query_lower in movie.title.casefold()]
    upcoming_ids = [movie.id for movie in coming_soon_releases + coming_soon_rereleases]
    hype_ids = list(dict.fromkeys(upcoming_ids + [
        movie.id for movie in featured_movies if movie.is_upcoming
    ]))
    hype_counts = {movie_id: {'HYPED': 0, 'SUPER_HYPED': 0, 'EXTREME_HYPED': 0}
                   for movie_id in hype_ids}
    if hype_ids:
        for movie_id, level, count in db.session.query(
                MovieHypeVote.movie_id, MovieHypeVote.level, sa_func.count(MovieHypeVote.id)
        ).filter(MovieHypeVote.movie_id.in_(hype_ids)).group_by(
                MovieHypeVote.movie_id, MovieHypeVote.level):
            if level in hype_counts[movie_id]:
                hype_counts[movie_id][level] = count
    hype_mine = {vote.movie_id: vote.level for vote in MovieHypeVote.query.filter(
        MovieHypeVote.user_id == current_user.id, MovieHypeVote.movie_id.in_(hype_ids)).all()} if hype_ids else {}

    return render_template(
        'index.html',
        featured_movies=featured_movies,
        screening_dates=screening_dates,
        screening_groups=screening_groups,
        featured_shows_by_movie=featured_shows_by_movie,
        active_category=active_category,
        search_query=search_query,
        hype_counts=hype_counts,
        hype_mine=hype_mine,
        theater_count=Theater.query.count(),
        screen_count=Screen.query.count(),
        now_showing_releases=now_showing_releases,
        now_showing_rereleases=now_showing_rereleases,
        coming_soon_releases=coming_soon_releases,
        coming_soon_rereleases=coming_soon_rereleases,
        # backward compat counts
        total_now_showing=len(now_showing_releases) + len(now_showing_rereleases),
        total_coming_soon=len(coming_soon_releases) + len(coming_soon_rereleases)
    )
