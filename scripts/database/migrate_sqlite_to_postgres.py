"""Back up SQLite, then copy and verify application rows atomically.

Target schema must already be at Alembic head.
Each table must either be empty or exactly match its SQLite source.
Existing matching records are preserved; missing records are inserted.
Conflicting or partial records are rejected without overwriting.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from sqlalchemy import create_engine, inspect, select, text

from database_health import check_database


class MigrationError(RuntimeError):
    pass


def backup_source(source, backup_dir):
    source = Path(source).resolve(strict=True)
    backup_dir = Path(backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / ('vizag_movies-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.db')
    # SQLite's backup API produces a consistent snapshot, including WAL data.
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(str(backup))) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise MigrationError('Source snapshot failed integrity check.')
            if dst.execute('PRAGMA foreign_key_check').fetchall():
                raise MigrationError('Source snapshot contains foreign-key violations.')
            dst.commit()
    return backup


def digest(rows):
    encoded = json.dumps([dict(row) for row in rows], sort_keys=True, default=str,
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def read_snapshot(backup, metadata):
    engine = create_engine('sqlite:///' + backup.as_posix(), hide_parameters=True)
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            names = set(inspector.get_table_names()) - {'alembic_version', 'sqlite_sequence'}
            if names != set(metadata.tables):
                raise MigrationError('Source tables differ from model schema; review snapshot before migration.')
            data = {}
            for table in metadata.sorted_tables:
                if {c['name'] for c in inspector.get_columns(table.name)} != set(table.columns.keys()):
                    raise MigrationError('Source columns differ from model schema: ' + table.name)
                rows = conn.execute(select(table).order_by(*table.primary_key.columns)).mappings().all()
                for row in rows:
                    for col in table.columns:
                        value = row[col.name]
                        if value is None and not col.nullable:
                            raise MigrationError('Unexpected NULL: ' + table.name + '.' + col.name)
                        if isinstance(value, str) and getattr(col.type, 'length', None) and len(value) > col.type.length:
                            raise MigrationError('Value exceeds PostgreSQL length: ' + table.name + '.' + col.name)
                data[table.name] = rows
            return data
    finally:
        engine.dispose()


def transfer(engine, metadata, data):
    health = check_database(engine, metadata)
    if not health['ok']:
        raise MigrationError(
            'Target is unavailable or not at schema head. '
            'Run database_health.py.'
        )

    report = {}

    with engine.begin() as conn:
        if engine.dialect.name == 'postgresql':
            conn.execute(text('SELECT pg_advisory_xact_lock(740621110)'))

            quoted = ', '.join(
                conn.dialect.identifier_preparer.format_table(t)
                for t in metadata.sorted_tables
            )
            conn.execute(
                text('LOCK TABLE ' + quoted + ' IN ACCESS EXCLUSIVE MODE')
            )

        # Inspect existing records in every application table.
        target = {
            t.name: conn.execute(
                select(t).order_by(*t.primary_key.columns)
            ).mappings().all()
            for t in metadata.sorted_tables
        }

        # Reject conflicting or partially populated tables.
        # Matching tables are preserved; empty tables can be populated.
        for table in metadata.sorted_tables:
            source_rows = data[table.name]
            target_rows = target[table.name]

            if target_rows and digest(target_rows) != digest(source_rows):
                raise MigrationError(
                    'Target table contains different or partial records: '
                    + table.name
                    + '. No records changed.'
                )

        # Insert only into empty tables.
        for table in metadata.sorted_tables:
            source_rows = data[table.name]
            target_rows = target[table.name]

            if not target_rows and source_rows:
                for offset in range(0, len(source_rows), 500):
                    conn.execute(
                        table.insert(),
                        [
                            dict(row)
                            for row in source_rows[offset:offset + 500]
                        ]
                    )

            # Verify the final contents of every table.
            copied = conn.execute(
                select(table).order_by(*table.primary_key.columns)
            ).mappings().all()

            if (
                len(source_rows) != len(copied)
                or digest(source_rows) != digest(copied)
            ):
                raise MigrationError(
                    'Verification failed; transaction rolled back: '
                    + table.name
                )

            report[table.name] = {
                'source': len(source_rows),
                'target': len(copied),
                'content_verified': True,
                'action': (
                    'preserved_existing'
                    if target_rows
                    else 'inserted'
                    if source_rows
                    else 'empty'
                )
            }

        # Explicit imported IDs do not automatically advance PostgreSQL
        # SERIAL sequences. Synchronize every ID sequence with actual data.
        if engine.dialect.name == 'postgresql':
            for table in metadata.sorted_tables:
                if 'id' not in table.columns:
                    continue

                quoted = conn.dialect.identifier_preparer.format_table(table)

                sequence = conn.scalar(
                    text(
                        "SELECT pg_get_serial_sequence(:table_name, 'id')"
                    ),
                    {'table_name': quoted}
                )

                if sequence:
                    maximum = conn.scalar(
                        select(table.c.id).order_by(table.c.id.desc()).limit(1)
                    )

                    if maximum is None:
                        conn.execute(
                            text(
                                'SELECT setval(CAST(:sequence AS regclass), '
                                ':value, false)'
                            ),
                            {'sequence': sequence, 'value': 1}
                        )
                    else:
                        conn.execute(
                            text(
                                'SELECT setval(CAST(:sequence AS regclass), '
                                ':value, true)'
                            ),
                            {
                                'sequence': sequence,
                                'value': maximum
                            }
                        )

    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='instance/vizag_movies.db')
    parser.add_argument('--backup-dir', default='instance/backups')
    parser.add_argument('--report', default='instance/supabase-migration-result.json')
    parser.add_argument('--apply', action='store_true', help='Commit copy to configured PostgreSQL database')
    args = parser.parse_args()
    if Path(args.report).suffix.lower() != '.json' or Path(args.report).resolve() == Path(args.source).resolve():
        raise MigrationError('Report must be a separate JSON file, never the source database.')
    backup = backup_source(args.source, args.backup_dir)
    from app import app, db
    with app.app_context():
        data = read_snapshot(backup, db.metadata)
        result = {'backup': str(backup), 'status': 'snapshot_verified',
                  'source_counts': {name: len(rows) for name, rows in data.items()}}
        if args.apply:
            if db.engine.dialect.name != 'postgresql':
                raise MigrationError('--apply requires a PostgreSQL DATABASE_URL.')
            result['tables'] = transfer(db.engine, db.metadata, data)
            result['status'] = 'committed_and_verified'
        report = Path(args.report)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Driver exceptions may contain credentials, SQL parameters and user data.
        print(str(exc) if isinstance(exc, MigrationError) else
              'Migration failed (' + type(exc).__name__ + '). No success claimed. Check configuration and schema.')
        raise SystemExit(1)
