"""Scheduled movie catalogue sync with a recoverable, database-backed lease."""
import json
import logging
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import click
from flask import current_app
from sqlalchemy import case, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..extensions import db
from ..models import Movie, MovieSyncCandidate, MovieSyncState
from ..time import cinema_now
from .movies import (
    TMDBClient, TMDBError, minimum_metadata, movie_metadata, normalized, poster_identity,
)

LEASE = timedelta(minutes=10)
RETRY = timedelta(minutes=15)
REFRESH = timedelta(days=1)
COUNTS = ('imported', 'updated', 'skipped', 'failed')
STATE_ID = 1


class LeaseLost(Exception):
    pass


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def credentials_configured():
    return bool(current_app.config['TMDB_READ_TOKEN'] or current_app.config['TMDB_API_KEY'])


def ensure_state():
    insert = pg_insert if db.engine.dialect.name == 'postgresql' else sqlite_insert
    db.session.execute(insert(MovieSyncState).values(id=STATE_ID).on_conflict_do_nothing())


def request_movie_sync():
    ensure_state()
    db.session.execute(update(MovieSyncState).where(MovieSyncState.id == STATE_ID)
                       .values(requested_at=utc_now()))
    db.session.commit()


def sync_status(state):
    if not credentials_configured():
        return 'TMDB credentials missing'
    if not state:
        return 'Awaiting first worker check-in'
    now = utc_now()
    if state.lease_until and state.lease_until > now:
        return 'Running'
    if state.lease_until:
        return 'Interrupted · awaiting retry'
    if not state.worker_seen_at or now - state.worker_seen_at > timedelta(minutes=90):
        return 'Awaiting worker check-in'
    if state.throttle_until and state.throttle_until > now:
        return 'TMDB rate limit · retry scheduled'
    if state.requested_at:
        return 'Manual sync queued'
    return 'Retry scheduled' if state.error else 'Waiting for next run'


def claim(force):
    now = utc_now()
    ensure_state()
    query = update(MovieSyncState).where(
        MovieSyncState.id == STATE_ID,
        or_(MovieSyncState.lease_until.is_(None), MovieSyncState.lease_until <= now),
        or_(MovieSyncState.throttle_until.is_(None), MovieSyncState.throttle_until <= now),
    )
    if not force:
        query = query.where(or_(MovieSyncState.lease_until.is_not(None),
                                MovieSyncState.requested_at.is_not(None),
                                MovieSyncState.next_run_at.is_(None), MovieSyncState.next_run_at <= now))
    token = uuid4().hex
    claimed = db.session.execute(query.values(
        worker_seen_at=now, last_attempt_at=now, lease_until=now + LEASE,
        run_token=token, requested_at=None, counts=dict.fromkeys(COUNTS, 0), error=None,
    )).rowcount
    if not claimed:
        db.session.execute(update(MovieSyncState).where(MovieSyncState.id == STATE_ID)
                           .values(worker_seen_at=now))
    db.session.commit()
    return token if claimed else None


def update_lease(token, **values):
    now = utc_now()
    result = db.session.execute(update(MovieSyncState).where(
        MovieSyncState.id == STATE_ID, MovieSyncState.run_token == token, MovieSyncState.lease_until > now,
    ).values(**{'worker_seen_at': now, 'lease_until': now + LEASE, **values}))
    if result.rowcount != 1:
        db.session.rollback()
        raise LeaseLost


def heartbeat(token):
    update_lease(token)
    db.session.commit()


def discovery_pages(client, source, path, page_limit, bounds=None):
    params = {'region': client.region}
    if bounds:
        lower, upper = bounds
        params.update({'release_date.gte': lower, 'release_date.lte': upper,
                       'with_release_type': '3|2', 'include_adult': 'false', 'sort_by': 'popularity.desc'})
    for page in range(1, page_limit + 1):
        payload = client.get(path, page=page, **params)
        results = payload.get('results')
        total_pages = payload.get('total_pages')
        if not isinstance(results, list) or type(total_pages) is not int:
            raise TMDBError('TMDB returned an invalid discovery page.')
        if page == 1 and bounds and total_pages > page_limit and lower < upper:
            middle = lower + (upper - lower) // 2
            for smaller in ((lower, middle), (middle + timedelta(days=1), upper)):
                yield from discovery_pages(client, source, path, page_limit, smaller)
            return
        yield from results
        if page >= total_pages:
            return
    current_app.logger.warning('tmdb_discovery_page_limit source=%s pages=%s', source, page_limit)


def discover(client, lower, today, upper, page_limit):
    sources = {}
    for source, path, bounds in (
        ('now_playing', '/movie/now_playing', None),
        ('upcoming', '/movie/upcoming', None),
        ('recent', '/discover/movie', (lower, today)),
        ('upcoming', '/discover/movie', (today + timedelta(days=1), upper)),
    ):
        for row in discovery_pages(client, source, path, page_limit, bounds):
            if not isinstance(row, dict) or row.get('adult'):
                continue
            movie_id = row.get('id')
            if type(movie_id) is int and 0 < movie_id <= 2_147_483_647:
                sources.setdefault(movie_id, source)
    return sources


def matching_local_movie(fields):
    metadata = fields['tmdb_metadata']
    titles = {normalized(fields['title']), normalized(metadata.get('original_title'))} - {''}
    dates = {fields['tmdb_original_release_date'], fields['tmdb_regional_release_date']} - {None}
    poster = poster_identity(fields['poster'])
    evidence = [Movie.release_date.in_(dates)] if dates else []
    if poster:
        evidence.append(Movie.poster.endswith(poster, autoescape=True))
    if not evidence:
        return None
    languages = {normalized(fields['language']), normalized(metadata.get('original_language'))} - {''}
    candidates = Movie.query.filter(
        Movie.tmdb_id.is_(None), Movie.tmdb_legacy_id.is_(None), or_(*evidence),
    ).with_for_update().all()
    matches = [movie for movie in candidates if normalized(movie.title) in titles and (
        (poster is not None and poster_identity(movie.poster) == poster)
        or (movie.release_date in dates and normalized(movie.language) in languages)
    )]
    return matches[0] if len(matches) == 1 else None


def snapshot_value(value):
    return value.isoformat() if isinstance(value, date) else value


def apply_metadata(movie, fields):
    snapshot = dict(movie.tmdb_snapshot or {})
    overrides = set(movie.tmdb_overrides or ())
    changed = False
    extras = dict(movie.tmdb_metadata or {})
    for key, value in fields['tmdb_metadata'].items():
        if value:
            extras[key] = value
    if extras and extras != movie.tmdb_metadata:
        movie.tmdb_metadata = extras
        changed = True
    for key, value in fields.items():
        if key == 'tmdb_metadata' or value is None or key in overrides:
            continue
        current = getattr(movie, key)
        if key == 'youtube_trailer_key' and movie.trailer_video_path:
            continue
        if key == 'is_upcoming' and not movie.tmdb_managed:
            continue
        if key in snapshot:
            if snapshot_value(current) != snapshot[key]:
                continue
        elif current not in (None, '', 0) and not movie.tmdb_managed:
            continue
        if key == 'cast_json' and current and movie.tmdb_managed:
            previous, incoming = json.loads(current), json.loads(value)
            if isinstance(previous, dict):
                value = json.dumps({part: incoming.get(part) or previous.get(part)
                                    for part in ('director', 'cast')}, ensure_ascii=False)
        if current != value:
            setattr(movie, key, value)
            changed = True
        snapshot[key] = snapshot_value(value)
    if snapshot != movie.tmdb_snapshot:
        movie.tmdb_snapshot = snapshot
    return changed


def create_movie(movie_id, fields):
    movie = Movie(tmdb_id=movie_id, tmdb_managed=True, duration=0, rating=db.null())
    apply_metadata(movie, fields)
    for field in ('language', 'certificate'):
        if getattr(movie, field) is None:
            setattr(movie, field, db.null())
    return movie


def defer_candidate(movie_id, source, now):
    candidate = db.session.get(MovieSyncCandidate, movie_id)
    if candidate is None:
        candidate = MovieSyncCandidate(tmdb_id=movie_id, source=source, attempts=0)
        db.session.add(candidate)
    candidate.attempts += 1
    candidate.next_attempt_at = now + timedelta(hours=min(6 * 2 ** min(candidate.attempts - 1, 5), 168))


def save_movie(movie_id, source, detail, region, lower, upper):
    now = utc_now()
    movie = Movie.query.filter_by(tmdb_id=movie_id).with_for_update().first()
    fields = movie_metadata(detail, region, source=source) if detail else None
    release_date = fields['release_date'] if fields else None
    out_of_window = release_date is not None and not lower <= release_date <= upper
    if fields is None or detail.get('adult') or (movie is None and out_of_window):
        remove_candidate(movie_id)
        if movie is not None:
            movie.tmdb_last_checked_at = now
        return 'skipped'
    if movie is None and not minimum_metadata(fields):
        defer_candidate(movie_id, source, now)
        return 'skipped'
    remove_candidate(movie_id)
    if movie is None:
        movie = matching_local_movie(fields)
        if movie is None:
            movie = create_movie(movie_id, fields)
            movie.tmdb_last_checked_at = now
            db.session.add(movie)
            return 'imported'
        movie.tmdb_id = movie_id
        apply_metadata(movie, fields)
        movie.tmdb_last_checked_at = now
        return 'updated'
    changed = apply_metadata(movie, fields)
    movie.tmdb_last_checked_at = now
    return 'updated' if changed else 'skipped'


def remove_candidate(movie_id):
    candidate = db.session.get(MovieSyncCandidate, movie_id)
    if candidate is not None:
        db.session.delete(candidate)


def worklist(client, lower, today, upper, page_limit):
    now = utc_now()
    missing = db.session.execute(select(MovieSyncCandidate.tmdb_id, MovieSyncCandidate.source)
                                 .where(MovieSyncCandidate.next_attempt_at <= now)
                                 .order_by(MovieSyncCandidate.next_attempt_at).limit(100)).all()
    refresh = db.session.execute(select(Movie.tmdb_id, Movie.is_upcoming).where(
        Movie.tmdb_id.is_not(None),
        or_(Movie.tmdb_last_checked_at.is_(None), (
            (Movie.tmdb_last_checked_at <= now - REFRESH)
            & or_(Movie.release_date.between(lower, upper),
                  Movie.tmdb_regional_release_date.between(lower, upper),
                  Movie.tmdb_original_release_date.between(lower, upper),
                  Movie.release_date.is_(None) & Movie.is_upcoming.is_(True))
        )),
    ).order_by(case((Movie.tmdb_last_checked_at.is_(None), 0), else_=1),
               Movie.tmdb_last_checked_at, Movie.id).limit(100)).all()
    db.session.rollback()
    sources = dict(missing)
    for movie_id, upcoming in refresh:
        sources.setdefault(movie_id, 'upcoming' if upcoming else 'refresh')
    for movie_id, source in discover(client, lower, today, upper, page_limit).items():
        sources.setdefault(movie_id, source)
    recent = set(db.session.scalars(select(Movie.tmdb_id).where(
        Movie.tmdb_last_checked_at > now - REFRESH, Movie.tmdb_id.is_not(None))))
    deferred = set(db.session.scalars(select(MovieSyncCandidate.tmdb_id).where(
        MovieSyncCandidate.next_attempt_at > now)))
    db.session.rollback()
    return {movie_id: source for movie_id, source in sources.items()
            if movie_id not in recent and movie_id not in deferred}


def run_sync(*, force=False):
    config = current_app.config
    interval = config['TMDB_SYNC_INTERVAL_MINUTES']
    lookback, lookahead = config['TMDB_SYNC_LOOKBACK_DAYS'], config['TMDB_SYNC_LOOKAHEAD_DAYS']
    page_limit = config['TMDB_SYNC_MAX_PAGES']
    if not credentials_configured():
        raise ValueError('Configure TMDB_READ_TOKEN or TMDB_API_KEY before starting the worker.')
    if (not 1 <= interval <= 10080 or not 0 <= lookback <= 365 or not 1 <= lookahead <= 730
            or not 1 <= page_limit <= 500 or len(config['TMDB_REGION']) != 2
            or not config['TMDB_REGION'].isascii() or not config['TMDB_REGION'].isalpha()):
        raise ValueError('Check TMDB discovery region, date window, page limit and interval settings.')
    token = claim(force)
    if token is None:
        return None
    current_app.logger.info('tmdb_sync_started region=%s', config['TMDB_REGION'])
    counts = dict.fromkeys(COUNTS, 0)
    today = cinema_now().date()
    lower, upper = today - timedelta(days=lookback), today + timedelta(days=lookahead)
    error = None
    retry_after = 0
    rate_limited = False
    try:
        with TMDBClient(heartbeat=lambda: heartbeat(token)) as client:
            for movie_id, source in worklist(client, lower, today, upper, page_limit).items():
                try:
                    detail = client.details(movie_id)
                except TMDBError as failure:
                    if failure.status not in {400, 404, 422}:
                        counts['failed'] += 1
                        raise
                    update_lease(token)
                    if failure.status == 404 and Movie.query.filter_by(tmdb_id=movie_id).first() is not None:
                        save_movie(movie_id, source, None, client.region, lower, upper)
                    else:
                        defer_candidate(movie_id, source, utc_now())
                    counts['failed'] += 1
                    update_lease(token, counts=dict(counts))
                    db.session.commit()
                    current_app.logger.warning('tmdb_movie_unavailable tmdb_id=%s status=%s',
                                               movie_id, failure.status)
                    continue
                update_lease(token)
                try:
                    outcome = save_movie(movie_id, source, detail, client.region, lower, upper)
                    db.session.flush()
                except IntegrityError:
                    # A simultaneous manual import may have won the unique ID.
                    db.session.rollback()
                    update_lease(token)
                    if not Movie.query.filter_by(tmdb_id=movie_id).first():
                        raise
                    outcome = 'skipped'
                counts[outcome] += 1
                update_lease(token, counts=dict(counts))
                db.session.commit()
    except LeaseLost:
        raise
    except TMDBError as failure:
        error, retry_after = str(failure), failure.retry_after
        rate_limited = failure.status == 429
    except SQLAlchemyError:
        counts['failed'] += 1
        error = 'A database write failed. Check database health before retrying.'
    except Exception as failure:
        counts['failed'] += 1
        error = 'The worker encountered an unexpected error.'
        current_app.logger.error('tmdb_sync_unexpected error_type=%s', type(failure).__name__)
    finally:
        db.session.rollback()
    now = utc_now()
    delay = max(RETRY, timedelta(seconds=min(retry_after, 86400))) if error else timedelta(minutes=interval)
    update_values = {'lease_until': None, 'run_token': None, 'counts': counts,
                     'error': error, 'next_run_at': now + delay,
                     'throttle_until': now + delay if rate_limited else None}
    if not error:
        update_values['last_success_at'] = now
    update_lease(token, **update_values)
    db.session.commit()
    current_app.logger.info('tmdb_sync_finished imported=%d updated=%d skipped=%d failed=%d error=%s',
                            *(counts[key] for key in COUNTS), error or 'none')
    return counts, error


def register_sync_command(app):
    @app.cli.command('sync-movies')
    @click.option('--force', is_flag=True, help='Run now if another worker is not active.')
    def sync_movies(force):
        """Run the TMDB catalogue sync if due or requested."""
        current_app.logger.setLevel(logging.INFO)
        try:
            result = run_sync(force=force)
        except ValueError as failure:
            raise click.ClickException(str(failure)) from None
        except LeaseLost:
            raise click.ClickException('The sync lease expired. Another worker can resume.') from None
        except SQLAlchemyError:
            raise click.ClickException(
                'Could not access the sync database. Check the connection and migration revision.'
            ) from None
        if result is None:
            click.echo('Movie sync is not due, or another worker is active.')
            return
        counts, error = result
        click.echo(' '.join(f'{name}={count}' for name, count in counts.items()))
        if error:
            raise click.ClickException(error)
