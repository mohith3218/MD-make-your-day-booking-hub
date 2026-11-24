"""Migration safety tests. Only temporary SQLite files are ever written."""
import copy
from datetime import date, datetime
from importlib import import_module
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest

_temp = tempfile.TemporaryDirectory(prefix='migration-tests-')
os.environ['APP_ENV'] = 'testing'
os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(_temp.name) / 'app-test.db').as_posix()
os.environ['TEST_DATABASE_URL'] = os.environ['DATABASE_URL']

from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateTable
from werkzeug.security import generate_password_hash, check_password_hash

from app import db
from database_config import database_settings
from database_health import check_database
from migrate_sqlite_to_postgres import backup_source, read_snapshot, transfer, MigrationError, digest


class MigrationTests(unittest.TestCase):
    def test_screen_review_upgrade_preserves_existing_booking_and_catalog_rows(self):
        legacy = create_engine('sqlite:///' + (self.folder / 'before-screen-reviews.db').as_posix(),
                               poolclass=NullPool)
        self.addCleanup(legacy.dispose)
        cfg = Config(str(Path(__file__).with_name('alembic.ini')))
        rows = {
            'user': dict(id=10, username='review_migration', password_hash='recorded'),
            'theater': dict(id=11, name='Existing theatre'),
            'screen': dict(id=12, theater_id=11, name='Existing screen', layout_json='{}'),
            'movie': dict(id=13, title='Existing film', description='Fixture', duration=110),
            'showtime': dict(id=14, movie_id=13, screen_id=12, theater='Existing theatre',
                             show_date=date(2025, 1, 1), show_time='19:30'),
            'booking': dict(id=15, user_id=10, showtime_id=14, seats='A1', status='PAID', total_amount=120),
            'payment': dict(id=16, booking_id=15, gateway='historical', status='CAPTURED'),
            'movie_rating': dict(id=17, user_id=10, movie_id=13, rating=4),
            'movie_hype_vote': dict(id=18, user_id=10, movie_id=13, level='SUPER_HYPED',
                                    updated_at=datetime(2025, 1, 1)),
        }
        with legacy.begin() as conn:
            cfg.attributes['connection'] = conn
            command.upgrade(cfg, '20261119_01')
            legacy_tables = {name: Table(name, MetaData(), autoload_with=conn) for name in rows}
            for name, values in rows.items():
                if name == 'user':
                    values.update(email_verified=False, email_otp_attempts=0, alternative_id='legacy-10')
                if name == 'booking':
                    values.update(reference='CW-LEGACY')
                conn.execute(legacy_tables[name].insert(), values)
            before = {name: conn.execute(select(table)).mappings().all()
                      for name, table in legacy_tables.items()}
        with legacy.begin() as conn:
            cfg.attributes['connection'] = conn
            command.upgrade(cfg, 'head')
            after = {name: conn.execute(select(table)).mappings().all()
                     for name, table in legacy_tables.items()}
            self.assertEqual(before, after)
            for name in ('screen_review', 'screen_review_report', 'screen_review_moderation'):
                self.assertEqual(conn.execute(select(db.metadata.tables[name])).all(), [])
        self.assertTrue(check_database(legacy, db.metadata)['ok'])

    def test_screen_review_migration_emits_additive_postgres_ddl(self):
        output = StringIO()
        context = MigrationContext.configure(dialect_name='postgresql',
                                             opts={'as_sql': True, 'output_buffer': output})
        with Operations.context(context):
            import_module('migrations.versions.20261123_01_screen_reviews').upgrade()
        ddl = output.getvalue()
        for suffix in ('', '_report', '_moderation'):
            self.assertIn(f'CREATE TABLE screen_review{suffix} (', ddl)
        self.assertIn('REFERENCES booking (id)', ddl)
        self.assertIn('UNIQUE (booking_id)', ddl)
        self.assertIn('TIMESTAMP WITHOUT TIME ZONE', ddl)
        for operation in ('DROP ', 'DELETE ', 'UPDATE ', 'ALTER TABLE '):
            self.assertNotIn(operation, ddl)

    def test_tmdb_upgrade_preserves_duplicate_legacy_records(self):
        cfg = Config(str(Path(__file__).with_name('alembic.ini')))
        engine = create_engine('sqlite:///' + (self.folder / 'before-tmdb.db').as_posix(),
                               poolclass=NullPool)
        with engine.begin() as conn:
            cfg.attributes['connection'] = conn
            command.upgrade(cfg, '20261123_01')
            conn.execute(text("INSERT INTO movie (id, title, description, duration, tmdb_id) VALUES "
                              "(1, 'One', 'Synopsis one', 97, 42), (2, 'Two', 'Synopsis two', 89, 42)"))
            conn.execute(text("INSERT INTO showtime (id, movie_id, theater, show_date, show_time) "
                              "VALUES (3, 2, 'Existing theatre', '2025-01-01', '10:00')"))
        with engine.begin() as conn:
            cfg.attributes['connection'] = conn
            command.upgrade(cfg, 'head')
            self.assertEqual(conn.execute(text(
                'SELECT id, tmdb_id, tmdb_legacy_id FROM movie ORDER BY id')).all(),
                [(1, 42, None), (2, None, 42)])
            self.assertEqual(conn.execute(text(
                'SELECT movie_id, is_cancelled FROM showtime WHERE id = 3')).one(), (2, 0))
        self.assertTrue(check_database(engine, db.metadata)['ok'])

    def test_tmdb_migration_emits_postgres_ddl(self):
        output = StringIO()
        context = MigrationContext.configure(dialect_name='postgresql',
                                             opts={'as_sql': True, 'output_buffer': output})
        with Operations.context(context):
            import_module('migrations.versions.20261125_01_tmdb_sync').upgrade()
        ddl = output.getvalue()
        self.assertIn('CREATE UNIQUE INDEX ix_movie_tmdb_id ON movie (tmdb_id)', ddl)
        self.assertIn('ALTER TABLE showtime ADD COLUMN is_cancelled BOOLEAN', ddl)
        self.assertIn('CREATE TABLE movie_sync_state', ddl)
        self.assertNotIn('DROP TABLE', ddl)
        self.assertNotIn('DELETE FROM', ddl)

    def test_legacy_party_and_jagadamba_upgrade(self):
        import vizag_theaters as theaters
        import seat_layout as sl
        legacy = create_engine('sqlite:///' + (self.folder / 'legacy.db').as_posix())
        cfg = Config(str(Path(__file__).with_name('alembic.ini')))
        layout = theaters.jagadamba_70mm()
        layout['levels'] = [dict(id='upper-balcony', type='balcony'),
                            dict(id='lower-balcony', type='balcony'), dict(id='stalls', type='floor')]
        for cls in layout['classes']:
            for row in cls['rows']:
                row['level_id'] = {'PREM_UPPER':'upper-balcony', 'PREM_LOWER':'lower-balcony',
                                   'NONPREM':'stalls'}[cls['code']]
        before = (sl.seat_price_map(layout), sl.seat_class_map(layout), sl.count_seats(layout))
        try:
            with legacy.begin() as conn:
                cfg.attributes['connection'] = conn
                command.upgrade(cfg, '20261110_01')
                conn.execute(__import__('sqlalchemy').text(
                    'INSERT INTO "user" (id, username, password_hash, email_verified, email_otp_attempts) '
                    'VALUES (1, :name, :password, 1, 0)'),
                    {'name': 'Host', 'password': 'unchanged'})
                conn.execute(text('INSERT INTO theater (id, name) VALUES (1, :name)'),
                             {'name': 'Jagadamba Theatre'})
                conn.execute(text('INSERT INTO movie (id, title, description, duration) '
                                  'VALUES (1, :title, :description, :duration)'),
                             {'title': 'Fixture', 'description': 'Fixture', 'duration': 120})
                conn.execute(text('INSERT INTO screen (id, theater_id, name, layout_json) '
                                  'VALUES (:id, 1, :name, :layout)'), [
                    {'id': 1, 'name': '70MM Main', 'layout': json.dumps(layout)},
                    {'id': 2, 'name': 'Other screen', 'layout': '{"classes":[]}'}])
                from datetime import date, datetime
                legacy_showtime = Table('showtime', MetaData(), autoload_with=conn)
                conn.execute(legacy_showtime.insert(), dict(id=1, movie_id=1, screen_id=1,
                             theater='Jagadamba Theatre', show_date=date.today(), show_time='18:30'))
                conn.execute(db.metadata.tables['party_session'].insert(), dict(id=1, code='ABC123', showtime_id=1, host_id=1))
                conn.execute(db.metadata.tables['party_member'].insert(), [
                    dict(id=1, party_id=1, user_id=1, user_name='Old', selected_seats='A1'),
                    dict(id=2, party_id=1, user_id=1, user_name='New', selected_seats='A2')])
            with legacy.begin() as conn:
                cfg.attributes['connection'] = conn
                command.upgrade(cfg, 'head')
                self.assertFalse(conn.execute(select(db.metadata.tables['movie'].c.is_archived)
                                              .where(db.metadata.tables['movie'].c.id == 1)).scalar_one())
                self.assertEqual(conn.execute(select(db.metadata.tables['theater'].c.verification_status)
                                               .where(db.metadata.tables['theater'].c.id == 1)).scalar_one(),
                                 'unverified')
                self.assertEqual(conn.execute(select(db.metadata.tables['screen'].c.verification_status)
                                               .where(db.metadata.tables['screen'].c.id == 1)).scalar_one(),
                                 'unverified')
                raw = conn.execute(select(db.metadata.tables['screen'].c.layout_json).where(
                    db.metadata.tables['screen'].c.id == 1)).scalar_one()
                corrected = json.loads(raw)
                self.assertEqual(len(corrected['levels']), 2)
                self.assertEqual(before, (sl.seat_price_map(corrected), sl.seat_class_map(corrected), sl.count_seats(corrected)))
                members = conn.execute(select(db.metadata.tables['party_member'])).mappings().all()
                self.assertEqual([(m['id'], m['selected_seats']) for m in members], [(2, 'A2')])
                self.assertEqual(conn.execute(select(db.metadata.tables['screen'].c.layout_json).where(
                    db.metadata.tables['screen'].c.id == 2)).scalar_one(), '{"classes":[]}')
        finally:
            legacy.dispose()

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
            conn.execute(db.metadata.tables['movie'].insert(), dict(id=17, title='Fixture movie',
                         description='Migration test fixture', duration=120))
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
            self.assertEqual(len(report), len(db.metadata.tables))
            self.assertTrue(all(r['source'] == r['target'] and r['content_verified'] for r in report.values()))
        with self.engine.connect() as conn:
            user = conn.execute(select(db.metadata.tables['user'])).mappings().one()
            self.assertTrue(user['is_admin'])
            self.assertEqual(user['password_hash'], self.password_hash)
            self.assertTrue(check_password_hash(user['password_hash'], 'fixture-password'))

    def test_preserves_matching_existing_tables_and_inserts_empty_tables(self):
        theater = db.metadata.tables['theater']
        screen = db.metadata.tables['screen']

        # Pre-populate the target with exact copies of source theater and screen.
        with self.engine.begin() as conn:
            conn.execute(theater.insert(), [dict(row) for row in self.data['theater']])
            conn.execute(screen.insert(), [dict(row) for row in self.data['screen']])

        report = transfer(self.engine, db.metadata, self.data)

        self.assertEqual(report['theater']['action'], 'preserved_existing')
        self.assertEqual(report['screen']['action'], 'preserved_existing')

        self.assertEqual(report['movie']['action'], 'inserted')
        self.assertEqual(report['user']['action'], 'inserted')

        self.assertTrue(
            all(item['content_verified'] for item in report.values())
        )

        # Exact rerun must remain safe.
        second_report = transfer(self.engine, db.metadata, self.data)

        self.assertEqual(
            second_report['theater']['action'],
            'preserved_existing'
        )
        self.assertEqual(
            second_report['screen']['action'],
            'preserved_existing'
        )

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
