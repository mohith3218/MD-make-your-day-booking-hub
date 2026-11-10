"""Migration safety tests. Only temporary SQLite files are ever written."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

_instance = Path(__file__).resolve().parent / 'instance'
_instance.mkdir(exist_ok=True)
_temp = tempfile.TemporaryDirectory(prefix='migration-tests-', dir=_instance)
os.environ['APP_ENV'] = 'testing'
os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(_temp.name) / 'app-test.db').as_posix()
os.environ['TEST_DATABASE_URL'] = os.environ['DATABASE_URL']

from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from werkzeug.security import generate_password_hash, check_password_hash

from app import db
from database_config import database_settings
from database_health import check_database
from migrate_sqlite_to_postgres import backup_source, read_snapshot, transfer, MigrationError, digest


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=_temp.name)
        self.folder = Path(self.temp.name)
        self.source = self.folder / 'source.db'
        self.source_engine = create_engine('sqlite:///' + self.source.as_posix())
        db.metadata.create_all(self.source_engine)
        self.password_hash = generate_password_hash('fixture-password')
        with self.source_engine.begin() as conn:
            conn.execute(db.metadata.tables['user'].insert(), dict(id=42, username='admin',
                         password_hash=self.password_hash, is_admin=True))
            conn.execute(db.metadata.tables['theater'].insert(), dict(id=91, name='Fixture venue'))
            conn.execute(db.metadata.tables['screen'].insert(), dict(id=128, theater_id=91,
                         name='Fixture screen', layout_json='{"wall":{"left":"custom"},"confidence":"estimated"}'))
        before = self.source.read_bytes()
        self.backup = backup_source(self.source, self.folder / 'backups')
        self.assertEqual(before, self.source.read_bytes())
        self.data = read_snapshot(self.backup, db.metadata)
        self.engine = create_engine('sqlite:///' + (self.folder / 'target.db').as_posix())
        cfg = Config(str(Path(__file__).with_name('alembic.ini')))
        with self.engine.begin() as conn:
            cfg.attributes['connection'] = conn
            command.upgrade(cfg, 'head')

    def tearDown(self):
        self.engine.dispose()
        self.source_engine.dispose()
        self.temp.cleanup()

    def test_copy_and_exact_rerun_preserve_every_column(self):
        for _ in range(2):
            report = transfer(self.engine, db.metadata, self.data)
            self.assertEqual(len(report), 18)
            self.assertTrue(all(r['source'] == r['target'] and r['content_verified'] for r in report.values()))
        with self.engine.connect() as conn:
            user = conn.execute(select(db.metadata.tables['user'])).mappings().one()
            self.assertTrue(user['is_admin'])
            self.assertEqual(user['password_hash'], self.password_hash)
            self.assertTrue(check_password_hash(user['password_hash'], 'fixture-password'))

    def test_conflicting_target_is_never_overwritten(self):
        transfer(self.engine, db.metadata, self.data)
        changed = copy.deepcopy(self.data)
        changed['theater'] = [dict(changed['theater'][0], name='Different')]
        with self.assertRaises(MigrationError):
            transfer(self.engine, db.metadata, changed)
        self.assertEqual(transfer(self.engine, db.metadata, self.data)['theater']['target'], 1)

    def test_failed_insert_rolls_back_all_tables(self):
        broken = copy.deepcopy(self.data)
        broken['user'] = [dict(broken['user'][0], username=None)]
        with self.assertRaises(Exception):
            transfer(self.engine, db.metadata, broken)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(db.metadata.tables['theater'])).all(), [])

    def test_health_and_reconnect(self):
        self.assertTrue(check_database(self.engine, db.metadata)['ok'])
        self.engine.dispose()
        self.assertTrue(check_database(self.engine, db.metadata)['ok'])
        empty = create_engine('sqlite:///:memory:')
        self.assertFalse(check_database(empty, db.metadata)['ok'])
        empty.dispose()

    def test_all_model_ddl_compiles_for_postgres(self):
        for table in db.metadata.sorted_tables:
            ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
            self.assertNotIn('DATETIME', ddl)
            self.assertIn('PRIMARY KEY', ddl)

    def test_frozen_baseline_matches_models(self):
        with self.engine.connect() as conn:
            changes = compare_metadata(MigrationContext.configure(conn), db.metadata)
            self.assertEqual(changes, [])


class ConfigurationTests(unittest.TestCase):
    def test_postgres_driver_tls_and_pooling(self):
        for scheme in ('postgres', 'postgresql', 'postgresql+psycopg'):
            url, options = database_settings({'DATABASE_URL': scheme + '://user:p%40ss@host/db'})
            self.assertEqual(url.drivername, 'postgresql+psycopg')
            self.assertEqual(url.password, 'p@ss')
            self.assertEqual(url.query['sslmode'], 'require')
            self.assertTrue(options['pool_pre_ping'])
            self.assertIsNone(options['connect_args']['prepare_threshold'])

    def test_testing_rejects_remote_and_development_database(self):
        for url in ('postgresql://user:secret@host/db', 'sqlite:///vizag_movies.db',
                    'sqlite:///relative-test.db', 'sqlite:///:memory:'):
            with self.assertRaises(RuntimeError) as error:
                database_settings({'APP_ENV': 'testing', 'DATABASE_URL': url, 'TEST_DATABASE_URL': url})
            self.assertNotIn('secret', str(error.exception))

    def test_tls_cannot_be_disabled(self):
        with self.assertRaises(RuntimeError):
            database_settings({'DATABASE_URL': 'postgresql://user:secret@host/db?sslmode=disable'})


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        _temp.cleanup()
