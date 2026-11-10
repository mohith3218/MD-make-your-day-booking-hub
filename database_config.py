"""Backend-only connection configuration shared by Flask and migration tools."""
import os
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def database_settings(environ=None):
    env = os.environ if environ is None else environ
    raw = env.get('DATABASE_URL') or 'sqlite:///vizag_movies.db'
    try:
        url = make_url(raw)
        if url.drivername in {'postgres', 'postgresql', 'postgresql+psycopg2'}:
            url = url.set(drivername='postgresql+psycopg')
        backend = url.get_backend_name()
        if backend not in {'sqlite', 'postgresql'}:
            raise ValueError()
        if env.get('APP_ENV', 'development').strip().lower() == 'testing':
            # A test must explicitly choose its own file; .env cannot choose it.
            expected = env.get('TEST_DATABASE_URL')
            if not expected or raw != expected or backend != 'sqlite':
                raise ValueError()
            if not url.database or url.database == ':memory:':
                raise ValueError()
            path = Path(url.database).resolve()
            if not Path(url.database).is_absolute() or path.name == 'vizag_movies.db':
                raise ValueError()
        options = {'pool_pre_ping': True, 'hide_parameters': True}
        if backend == 'postgresql':
            query = dict(url.query)
            query.setdefault('sslmode', env.get('DATABASE_SSLMODE', 'require'))
            if query['sslmode'] not in {'require', 'verify-ca', 'verify-full'}:
                raise ValueError()
            url = url.set(query=query)
            options.update(pool_size=3, max_overflow=2, pool_timeout=15,
                           pool_recycle=300,
                           connect_args={'connect_timeout': 10,
                                         'prepare_threshold': None})
        return url, options
    except (ValueError, TypeError, ArgumentError):
        raise RuntimeError('Invalid database configuration. Use a percent-encoded PostgreSQL URL with TLS, '
                           'or an isolated absolute SQLite TEST_DATABASE_URL in testing.') from None
