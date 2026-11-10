"""Read-only health diagnostics; never return driver errors or credentials."""
import json

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

SCHEMA_HEAD = '20261110_01'


def check_database(engine, metadata):
    result = {'ok': False, 'backend': engine.dialect.name}
    try:
        with engine.connect() as conn:
            result['query_ok'] = conn.scalar(text('SELECT 1')) == 1
            result['version'] = conn.scalar(text(
                'SELECT version()' if engine.dialect.name == 'postgresql' else 'SELECT sqlite_version()'))
            inspector = inspect(conn)
            tables = set(inspector.get_table_names())
            result['missing_tables'] = sorted(set(metadata.tables) - tables)
            result['missing_columns'] = {
                name: sorted(set(table.columns.keys()) - {c['name'] for c in inspector.get_columns(name)})
                for name, table in metadata.tables.items() if name in tables}
            result['missing_columns'] = {k: v for k, v in result['missing_columns'].items() if v}
            result['schema_version'] = (conn.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
                                        if 'alembic_version' in tables else [])
            result['ok'] = (result['query_ok'] and not result['missing_tables']
                            and not result['missing_columns'] and result['schema_version'] == [SCHEMA_HEAD])
            if not result['ok']:
                result['error'] = 'Schema is incomplete or not at head. Apply reviewed Alembic migrations.'
    except SQLAlchemyError:
        result['error'] = ('Database unavailable. Check DATABASE_URL, password encoding, TLS, network access '
                           'and Supabase project status. No connection details are logged.')
    return result


if __name__ == '__main__':
    from app import app, db
    with app.app_context():
        result = check_database(db.engine, db.metadata)
        # Dispose and reconnect to verify a fresh connection can be established.
        db.engine.dispose()
        result['reconnect_ok'] = check_database(db.engine, db.metadata)['ok']
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result['ok'] and result['reconnect_ok'] else 1)
