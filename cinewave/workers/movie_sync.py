"""Scheduled movie catalogue sync with a recoverable, database-backed lease."""
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from uuid import uuid4

import click
from flask import current_app
from sqlalchemy import case, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError

from ..extensions import db
from ..models import Movie, MovieSyncCandidate, MovieSyncState
from ..time import cinema_now
from ..integrations.tmdb import (
    TMDBClient, TMDBError, minimum_metadata, movie_metadata, normalized, poster_identity,
)

LEASE = timedelta(minutes=10)
RETRY = timedelta(minutes=15)
REFRESH = timedelta(days=1)
TRAILER_RECHECK = timedelta(days=7)
TRAILER_BACKFILL_LIMIT = 5
DISCOVERY_CHUNK = 16
BATCH_SIZE = 40
RUN_BUDGET_SECONDS = 720
COUNTS = ('discovered', 'imported', 'updated', 'skipped', 'failed')
STATE_ID = 1


class LeaseLost(Exception):
    pass


class BatchDeadline(Exception):
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
    if not state:
        return 'Worker has not checked in' if credentials_configured() else 'TMDB is not configured on this web service'
    now = utc_now()
    if state.lease_until and state.lease_until > now:
        return 'Running'
    if state.lease_until:
        return 'Interrupted · awaiting retry'
    if state.throttle_until and state.throttle_until > now:
        return 'Rate limited · awaiting cooldown'
    if state.requested_at:
        return 'Manual sync queued'
    if not state.worker_seen_at or now - state.worker_seen_at > timedelta(minutes=90):
        return 'Worker has not checked in recently'
    if state.error:
        return 'Failed · awaiting retry'
    if (state.counts or {}).get('outcome') == 'partial':
        return 'Completed with candidate failures'
    if (state.counts or {}).get('more_work'):
        return 'Batch completed · more work queued'
    return 'Completed' if state.last_success_at else 'Worker checked in'


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
        run_token=token, requested_at=None,
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


def discovery_queries(lower, today, upper):
    return [
        {'source': 'now_playing', 'path': '/movie/now_playing', 'page': 1},
        {'source': 'upcoming', 'path': '/movie/upcoming', 'page': 1},
        {'source': 'recent', 'path': '/discover/movie', 'page': 1,
         'lower': lower.isoformat(), 'upper': today.isoformat()},
        {'source': 'upcoming', 'path': '/discover/movie', 'page': 1,
         'lower': (today + timedelta(days=1)).isoformat(), 'upper': upper.isoformat()},
    ]


def discover(client, lower, today, upper, page_limit, pending=None, limit=None):
    """Read a bounded number of pages and retain the next page or date range."""
    if pending is None:
        pending = discovery_queries(lower, today, upper)
    sources = {}
    pages = 0
    while pending and (limit is None or pages < limit):
        query = pending[0]
        params = {'region': client.region, 'page': query['page']}
        first = date.fromisoformat(query['lower']) if 'lower' in query else None
        last = date.fromisoformat(query['upper']) if 'upper' in query else None
        if first:
            params.update({'release_date.gte': first, 'release_date.lte': last,
                           'with_release_type': '3|2', 'include_adult': 'false', 'sort_by': 'popularity.desc'})
        payload = client.get(query['path'], **params)
        pages += 1
        results, total_pages = payload.get('results'), payload.get('total_pages')
        if not isinstance(results, list) or type(total_pages) is not int:
            raise TMDBError('TMDB returned an invalid discovery page.')
        if query['page'] == 1 and first and first < last and total_pages > page_limit:
            middle = first + (last - first) // 2
            pending[:1] = [{**query, 'upper': middle.isoformat()},
                           {**query, 'lower': (middle + timedelta(days=1)).isoformat()}]
            continue
        for row in results:
            if not isinstance(row, dict) or row.get('adult'):
                continue
            movie_id = row.get('id')
            if type(movie_id) is int and 0 < movie_id <= 2_147_483_647:
                sources.setdefault(movie_id, query['source'])
        if query['page'] >= min(total_pages, 500):
            pending.pop(0)
        else:
            pending[0] = {**query, 'page': query['page'] + 1}
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
        if key == 'is_upcoming' and not movie.tmdb_managed:
            continue
        if key in snapshot:
            if snapshot_value(current) != snapshot[key]:
                continue
        elif current not in (None, '', 0) and not movie.tmdb_managed:
            continue
        if key == 'cast_json' and current and movie.tmdb_managed:
            try:
                previous, incoming = json.loads(current), json.loads(value)
            except ValueError:
                continue
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
        return 'skipped', 'outside_release_window' if out_of_window else 'invalid_metadata'
    if movie is None and not minimum_metadata(fields):
        defer_candidate(movie_id, source, now)
        reason = ('invalid_metadata' if not fields['title'] else
                  'missing_description' if not fields['description'] else 'missing_poster')
        return 'skipped', reason
    remove_candidate(movie_id)
    if movie is None:
        movie = matching_local_movie(fields)
        if movie is None:
            movie = create_movie(movie_id, fields)
            movie.tmdb_last_checked_at = now
            if not detail.get('trailer_lookup_error'):
                movie.tmdb_trailer_checked_at = now
            db.session.add(movie)
            return 'imported', None
        movie.tmdb_id = movie_id
        apply_metadata(movie, fields)
        movie.tmdb_last_checked_at = now
        if not detail.get('trailer_lookup_error'):
            movie.tmdb_trailer_checked_at = now
        return 'updated', None
    changed = apply_metadata(movie, fields)
    movie.tmdb_last_checked_at = now
    if not detail.get('trailer_lookup_error'):
        movie.tmdb_trailer_checked_at = now
    return ('updated', None) if changed else ('skipped', 'already_imported')


def remove_candidate(movie_id):
    candidate = db.session.get(MovieSyncCandidate, movie_id)
    if candidate is not None:
        db.session.delete(candidate)


def pending_count(now):
    return db.session.scalar(select(db.func.count()).select_from(MovieSyncCandidate)
                             .where(MovieSyncCandidate.next_attempt_at <= now))


def queue_discovery(sources, counts, reasons, now):
    counts['discovered'] += len(sources)
    if not sources:
        return
    recent = set(db.session.scalars(select(Movie.tmdb_id).where(
        Movie.tmdb_id.in_(sources), Movie.tmdb_last_checked_at > now - REFRESH)))
    waiting = dict(db.session.execute(select(MovieSyncCandidate.tmdb_id, MovieSyncCandidate.next_attempt_at)
                   .where(MovieSyncCandidate.tmdb_id.in_(sources))).all())
    rows = []
    for movie_id, source in sources.items():
        reason = ('already_imported' if movie_id in recent else
                  'deferred_for_retry' if movie_id in waiting and waiting[movie_id] > now else None)
        if reason:
            counts['skipped'] += 1
            reasons[reason] = reasons.get(reason, 0) + 1
        elif movie_id not in waiting:
            rows.append({'tmdb_id': movie_id, 'source': source, 'attempts': 0, 'next_attempt_at': now})
    if rows:
        insert = pg_insert if db.engine.dialect.name == 'postgresql' else sqlite_insert
        db.session.execute(insert(MovieSyncCandidate).on_conflict_do_nothing(index_elements=['tmdb_id']), rows)


def worklist(lower, upper):
    now = utc_now()
    missing = db.session.execute(select(MovieSyncCandidate.tmdb_id, MovieSyncCandidate.source)
                                 .where(MovieSyncCandidate.next_attempt_at <= now)
                                 .order_by(MovieSyncCandidate.next_attempt_at, MovieSyncCandidate.tmdb_id)
                                 .limit(BATCH_SIZE)).all()
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
               Movie.tmdb_last_checked_at, Movie.id).limit(10)).all()
    backfill = db.session.scalars(select(Movie.tmdb_id).where(
        Movie.tmdb_id.is_not(None), Movie.automatic_youtube_key.is_(None),
        or_(Movie.tmdb_trailer_checked_at.is_(None), Movie.tmdb_trailer_checked_at <= now - TRAILER_RECHECK),
    ).order_by(Movie.tmdb_trailer_checked_at.asc().nulls_first(), Movie.id).limit(TRAILER_BACKFILL_LIMIT)).all()
    sources = {movie_id: 'upcoming' if upcoming else 'refresh' for movie_id, upcoming in refresh}
    sources.update({movie_id: 'trailer' for movie_id in backfill if movie_id not in sources})
    sources.update(dict(missing))
    deferred = set(db.session.scalars(select(MovieSyncCandidate.tmdb_id).where(
        MovieSyncCandidate.tmdb_id.in_(sources), MovieSyncCandidate.next_attempt_at > now)))
    db.session.rollback()
    return [(movie_id, source) for movie_id, source in sources.items() if movie_id not in deferred][:BATCH_SIZE]


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
    previous = db.session.get(MovieSyncState, STATE_ID)
    was_requested = bool(previous and previous.requested_at)
    token = claim(force)
    if token is None:
        return None
    state = db.session.get(MovieSyncState, STATE_ID)
    signature = [config['TMDB_REGION'], lookback, lookahead, page_limit]
    progress = dict((state.counts or {}).get('_discovery') or {})
    if progress.get('configuration') != signature:
        progress = {'configuration': signature, 'pending': [], 'due_at': None}
    db.session.rollback()
    current_app.logger.info('tmdb_sync_started region=%s', config['TMDB_REGION'])
    counts = dict.fromkeys(COUNTS, 0)
    reasons = {}
    today = cinema_now().date()
    lower, upper = today - timedelta(days=lookback), today + timedelta(days=lookahead)
    error = failure_kind = None
    retry_after = 0
    limited = False
    deadline = monotonic() + RUN_BUDGET_SECONDS

    def checkpoint():
        return {**counts, 'reasons': dict(reasons), '_discovery': progress}

    def record(outcome, reason=None):
        counts[outcome] += 1
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1

    def guard_request():
        if monotonic() >= deadline:
            raise BatchDeadline
        heartbeat(token)

    try:
        update_lease(token, counts=checkpoint(), error=None)
        db.session.commit()
        with TMDBClient(heartbeat=guard_request) as client:
            now = utc_now()
            pending = list(progress.get('pending') or [])
            due_at = progress.get('due_at')
            if not pending and (force or was_requested or not due_at or due_at <= now.isoformat()):
                pending = discovery_queries(lower, today, upper)
                progress = {**progress, 'pending': pending.copy()}
            queued = pending_count(now)
            db.session.rollback()
            if pending and queued < 2 * BATCH_SIZE:
                found = discover(client, lower, today, upper, page_limit, pending, DISCOVERY_CHUNK)
                update_lease(token)
                queue_discovery(found, counts, reasons, now)
                progress = {**progress, 'pending': pending,
                            'due_at': (now + timedelta(minutes=interval)).isoformat() if not pending else due_at}
                update_lease(token, counts=checkpoint())
                db.session.commit()

            consecutive_unavailable = 0
            for movie_id, source in worklist(lower, upper):
                if monotonic() >= deadline:
                    raise BatchDeadline
                try:
                    detail = client.details(movie_id)
                except TMDBError as failure:
                    record('failed', 'upstream_api_failure')
                    if failure.status is None or (failure.status not in {400, 404, 422} and failure.status < 500):
                        raise
                    consecutive_unavailable = consecutive_unavailable + 1 if failure.status >= 500 else 0
                    if consecutive_unavailable >= 3:
                        raise
                    update_lease(token)
                    if failure.status == 404 and Movie.query.filter_by(tmdb_id=movie_id).first() is not None:
                        save_movie(movie_id, source, None, client.region, lower, upper)
                    else:
                        defer_candidate(movie_id, source, utc_now())
                    update_lease(token, counts=checkpoint())
                    db.session.commit()
                    current_app.logger.warning('tmdb_movie_unavailable tmdb_id=%s status=%s', movie_id, failure.status)
                    continue
                consecutive_unavailable = 0
                update_lease(token)
                try:
                    outcome, reason = save_movie(movie_id, source, detail, client.region, lower, upper)
                    db.session.flush()
                except (DataError, IntegrityError):
                    db.session.rollback()
                    update_lease(token)
                    if Movie.query.filter_by(tmdb_id=movie_id).first():
                        remove_candidate(movie_id)
                        outcome, reason = 'skipped', 'already_imported'
                    else:
                        defer_candidate(movie_id, source, utc_now())
                        outcome, reason = 'failed', 'database_failure'
                record(outcome, reason)
                update_lease(token, counts=checkpoint())
                db.session.commit()
                if reason:
                    current_app.logger.info('tmdb_movie_result tmdb_id=%s reason=%s', movie_id, reason)
                rate_limit = detail.get('lookup_rate_limit') or detail.get('trailer_lookup_error')
                if rate_limit and rate_limit.status == 429:
                    raise rate_limit
    except BatchDeadline:
        limited = True
    except LeaseLost:
        raise
    except TMDBError as failure:
        error, retry_after = str(failure), failure.retry_after
        failure_kind = 'rate_limited' if failure.status == 429 else 'api_failure'
    except SQLAlchemyError:
        record('failed', 'database_failure')
        failure_kind = 'database_failure'
        error = 'A database operation failed. Check database health before retrying.'
    except Exception as failure:
        record('failed', 'unexpected_failure')
        failure_kind = 'internal_failure'
        error = 'The worker encountered an unexpected error.'
        current_app.logger.error('tmdb_sync_unexpected error_type=%s', type(failure).__name__)
    finally:
        db.session.rollback()
    now = utc_now()
    more_work = limited or bool(progress.get('pending'))
    if not error:
        more_work = more_work or bool(pending_count(now))
        db.session.rollback()
    if error:
        delay = max(RETRY, timedelta(seconds=min(retry_after, 86400)))
    else:
        delay = timedelta(minutes=1 if more_work else interval)
    outcome = (failure_kind or ('partial' if counts['failed'] else 'batch_complete' if more_work else
                               'completed' if counts['imported'] or counts['updated'] else 'no_changes'))
    update_values = {'lease_until': None, 'run_token': None,
                     'counts': {**checkpoint(), 'outcome': outcome, 'more_work': more_work},
                     'error': error, 'next_run_at': now + delay,
                     'throttle_until': now + delay if failure_kind == 'rate_limited' else None}
    if not error:
        update_values['last_success_at'] = now
    update_lease(token, **update_values)
    db.session.commit()
    current_app.logger.info('tmdb_sync_finished outcome=%s %s', outcome,
                            ' '.join(f'{key}={counts[key]}' for key in COUNTS))
    return counts, error


def write_sync_result(outcome, *, counts=None, reasons=None, message=None):
    rows = [f'Outcome: {outcome.replace("_", " ")}']
    if message:
        rows.append(message)
    if counts is not None:
        rows.extend(f'- {name.replace("_", " ").capitalize()}: {counts.get(name, 0)}' for name in COUNTS)
    if reasons:
        rows.extend(f'- {name.replace("_", " ").capitalize()}: {count}' for name, count in sorted(reasons.items()))
    click.echo('\n'.join(rows))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as handle:
            handle.write('## TMDB sync\n\n' + '\n\n'.join(rows) + '\n')


def register_sync_command(app):
    @app.cli.command('sync-movies')
    @click.option('--force', is_flag=True, help='Run now if another worker is not active.')
    def sync_movies(force):
        """Run the TMDB catalogue sync if due or requested."""
        current_app.logger.setLevel(logging.INFO)
        try:
            result = run_sync(force=force)
            state = db.session.get(MovieSyncState, STATE_ID)
        except ValueError as failure:
            write_sync_result('configuration_failure', message=str(failure))
            raise click.ClickException(str(failure)) from None
        except LeaseLost:
            write_sync_result('interrupted', message='The sync lease expired. Another worker can resume.')
            raise click.ClickException('The sync lease expired. Another worker can resume.') from None
        except SQLAlchemyError:
            write_sync_result('database_failure', message='Check database connectivity and the Alembic revision.')
            raise click.ClickException(
                'Could not access the sync database. Check the connection and migration revision.'
            ) from None
        if result is None:
            now = utc_now()
            if state.throttle_until and state.throttle_until > now:
                write_sync_result('rate_limited', message='The worker did not call TMDB during the cooldown.')
            elif state.lease_until and state.lease_until > now:
                write_sync_result('running', message='Another worker holds the active lease.')
            else:
                write_sync_result('not_due', message='The worker checked in. The catalogue sync is not due.')
            return
        counts, error = result
        persisted = state.counts or {}
        write_sync_result(persisted.get('outcome', 'completed'), counts=counts,
                          reasons=persisted.get('reasons'), message=error)
        if error:
            raise click.ClickException(error)
