"""Read-only checks for the existing TMDB integration and sync database."""
import click
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from database_health import SCHEMA_HEAD, check_database
from ..extensions import db
from ..integrations.tmdb import TMDBClient, TMDBError
from ..models import Movie, MovieSyncState
from .movie_sync import STATE_ID, sync_status, utc_now


def register_tmdb_doctor(app):
    @app.cli.command('tmdb-doctor')
    def tmdb_doctor():
        """Check TMDB connectivity, database migrations, and worker state without writes."""
        click.echo(f'Application environment: {current_app.config["APP_ENV"]}')
        click.echo(f'Discovery region: {current_app.config["TMDB_REGION"]}')
        usable = []
        cooldown = False
        for method, setting in (('read_token', 'TMDB_READ_TOKEN'), ('api_key', 'TMDB_API_KEY')):
            if not current_app.config[setting]:
                click.echo(f'{setting}: missing')
                continue
            if cooldown:
                click.echo(f'{setting}: configured, verification deferred during TMDB cooldown')
                continue
            try:
                with TMDBClient(auth=method, attempts=1) as client:
                    detail = client.get('/movie/550')
                    results = client.search('Baahubali')
                if detail.get('id') != 550 or not isinstance(results.get('results'), list) or not results['results']:
                    raise TMDBError('TMDB returned an unexpected diagnostic response.')
            except TMDBError as failure:
                cooldown = failure.status == 429
                click.echo(f'{setting}: {failure.category}. {failure}')
            else:
                usable.append(method)
                click.echo(f'{setting}: verified movie details and search ({len(results["results"])} results)')
        click.echo(f'Working authentication: {", ".join(usable) or "none verified"}')

        health = check_database(db.engine, db.metadata)
        click.echo(f'Database: {health["backend"]}, {"reachable" if health.get("query_ok") else "unavailable"}')
        click.echo(f'Alembic: {", ".join(health.get("schema_version", [])) or "unversioned"}; expected {SCHEMA_HEAD}')
        for table in health.get('missing_tables', []):
            click.echo(f'Missing table: {table}')
        for table, columns in health.get('missing_columns', {}).items():
            click.echo(f'Missing columns in {table}: {", ".join(columns)}')
        try:
            if 'missing_tables' in health and 'missing_columns' in health:
                if 'movie' not in health['missing_tables'] and 'tmdb_id' not in health['missing_columns'].get('movie', []):
                    count = Movie.query.filter(Movie.tmdb_id.is_not(None)).count()
                    click.echo(f'TMDB-linked movies: {count}')
                if 'movie_sync_state' not in health['missing_tables'] and 'movie_sync_state' not in health['missing_columns']:
                    state = db.session.get(MovieSyncState, STATE_ID)
                    click.echo(f'Worker status: {sync_status(state)}')
                    expired = bool(state and state.lease_until and state.lease_until <= utc_now())
                    click.echo(f'Expired worker lease: {"yes" if expired else "no"}')
        except SQLAlchemyError:
            raise click.ClickException('The database became unavailable during diagnostics.') from None
        if not usable or not health['ok']:
            raise click.ClickException('Resolve the authentication or database problems reported above.')
