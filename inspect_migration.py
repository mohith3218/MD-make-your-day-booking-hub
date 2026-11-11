import os, sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from database_config import database_settings

# Locate the populated SQLite database
BASE_DIR = Path(__file__).resolve().parent

sqlite_path = BASE_DIR / 'instance' / 'vizag_movies.db'

if not sqlite_path.is_file():
    raise RuntimeError(f'SQLite DB not found at {sqlite_path}')

sqlite_url = f'sqlite:///{sqlite_path.as_posix()}'

# Engines (read‑only)
sqlite_engine = create_engine(sqlite_url, pool_pre_ping=True, hide_parameters=True)
pg_url, pg_opts = database_settings()
pg_engine = create_engine(pg_url, **pg_opts)

sqlite_inspector = inspect(sqlite_engine)
pg_inspector = inspect(pg_engine)

# Helper to get schema details
def get_schema(inspector):
    schema = {}
    for table in inspector.get_table_names():
        cols = []
        for col in inspector.get_columns(table):
            cols.append({
                'name': col['name'],
                'type': str(col['type']),
                'nullable': col.get('nullable'),
                'default': col.get('default'),
            })
        pk_info = inspector.get_pk_constraint(table)
        pk = pk_info.get('constrained_columns', [])
        uniques = [uq['name'] for uq in inspector.get_unique_constraints(table)]
        indexes = [idx['name'] for idx in inspector.get_indexes(table)]
        fks = []
        for fk in inspector.get_foreign_keys(table):
            fks.append({
                'columns': fk['constrained_columns'],
                'referred_table': fk['referred_table'],
                'referred_columns': fk['referred_columns'],
            })
        schema[table] = {
            'columns': cols,
            'primary_key': pk,
            'uniques': uniques,
            'indexes': indexes,
            'foreign_keys': fks,
        }
    return schema

sqlite_schema = get_schema(sqlite_inspector)
pg_schema = get_schema(pg_inspector)

# Record counts (read‑only)
def get_counts(engine, inspector):
    counts = {}
    with engine.connect() as conn:
        for table in inspector.get_table_names():
            result = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
            counts[table] = result.scalar()
    return counts

sqlite_counts = get_counts(sqlite_engine, sqlite_inspector)
pg_counts = get_counts(pg_engine, pg_inspector)

# Comparison helpers
missing_in_pg = set(sqlite_schema.keys()) - set(pg_schema.keys())
extra_in_pg = set(pg_schema.keys()) - set(sqlite_schema.keys())

# Build report
lines = []
lines.append('# Supabase Migration Readiness – Read‑Only Inspection')
lines.append('\n---\n')
lines.append('## SQLite Database')
lines.append(f'* File: `{sqlite_path}`')
lines.append('### Tables and record counts')
for tbl in sorted(sqlite_schema.keys()):
    lines.append(f'- `{tbl}`: {sqlite_counts.get(tbl, 0)} rows')
lines.append('\n### Schema details')
for tbl, info in sorted(sqlite_schema.items()):
    lines.append(f'#### {tbl}')
    lines.append('**Columns**')
    for col in info['columns']:
        lines.append(f"- `{col['name']}`: {col['type']}, nullable={col['nullable']}, default={col['default']}")
    lines.append(f"**Primary key**: {info['primary_key']}")
    lines.append(f"**Unique constraints**: {info['uniques']}")
    lines.append(f"**Indexes**: {info['indexes']}")
    lines.append('**Foreign keys**')
    for fk in info['foreign_keys']:
        lines.append(f"- {fk['columns']} → {fk['referred_table']}({fk['referred_columns']})")
    lines.append('')

lines.append('---')
lines.append('## Supabase PostgreSQL Database')
lines.append('### Tables and record counts')
for tbl in sorted(pg_schema.keys()):
    lines.append(f'- `{tbl}`: {pg_counts.get(tbl, 0)} rows')
lines.append('\n### Schema details')
for tbl, info in sorted(pg_schema.items()):
    lines.append(f'#### {tbl}')
    lines.append('**Columns**')
    for col in info['columns']:
        lines.append(f"- `{col['name']}`: {col['type']}, nullable={col['nullable']}, default={col['default']}")
    lines.append(f"**Primary key**: {info['primary_key']}")
    lines.append(f"**Unique constraints**: {info['uniques']}")
    lines.append(f"**Indexes**: {info['indexes']}")
    lines.append('**Foreign keys**')
    for fk in info['foreign_keys']:
        lines.append(f"- {fk['columns']} → {fk['referred_table']}({fk['referred_columns']})")
    lines.append('')

lines.append('---')
lines.append('## Comparison Summary')
lines.append(f'* Tables only in SQLite (would need creation in Supabase): {sorted(missing_in_pg)}')
lines.append(f'* Tables only in PostgreSQL (pre‑existing data): {sorted(extra_in_pg)}')
lines.append('\n### Potential schema gaps')
for tbl in missing_in_pg:
    lines.append(f'- Table `{tbl}` missing in PostgreSQL.')
for tbl in set(sqlite_schema.keys()) & set(pg_schema.keys()):
    sqlite_cols = {c['name']: c for c in sqlite_schema[tbl]['columns']}
    pg_cols = {c['name']: c for c in pg_schema[tbl]['columns']}
    missing_cols = set(sqlite_cols) - set(pg_cols)
    extra_cols = set(pg_cols) - set(sqlite_cols)
    if missing_cols:
        lines.append(f'  - In table `{tbl}`, columns missing in PostgreSQL: {sorted(missing_cols)}')
    if extra_cols:
        lines.append(f'  - In table `{tbl}`, extra columns in PostgreSQL: {sorted(extra_cols)}')
    # Compare PKs, uniques, indexes, FKs
    if sqlite_schema[tbl]['primary_key'] != pg_schema[tbl]['primary_key']:
        lines.append(f'  - Primary key mismatch in `{tbl}`: SQLite {sqlite_schema[tbl]["primary_key"]} vs PG {pg_schema[tbl]["primary_key"]}')
    # Unique and indexes not exhaustive here but noted
lines.append('\n### Duplicate / conflicting records')
lines.append('No data modifications were performed. Duplicate checks would require row‑by‑row comparison, which is beyond this read‑only audit.')
lines.append('\n### Foreign‑key dependencies & migration order')
for tbl, info in sorted(sqlite_schema.items()):
    if info['foreign_keys']:
        deps = [fk['referred_table'] for fk in info['foreign_keys']]
        lines.append(f'- Table `{tbl}` depends on {deps}')
lines.append('\n### Overwrite risk')
lines.append('Supabase already contains data in tables listed under "extra in PostgreSQL". Importing SQLite rows into those tables could cause primary‑key or unique‑constraint conflicts. A merge strategy or fresh schema creation is recommended.')
lines.append('\n---\n')
lines.append('**Next steps** (manual, no automated actions taken):')
lines.append('1. Verify that missing tables/columns are acceptable to create in Supabase.')
lines.append('2. Generate Alembic migration scripts (`alembic revision --autogenerate`) in `--sql` mode and review.')
lines.append('3. Backup both databases (SQLite copy, `pg_dump` for PostgreSQL).')
lines.append('4. Plan data import order based on foreign‑key dependencies (leaf tables first, then parents).')
lines.append('5. Decide on conflict resolution (skip existing rows, upsert, or truncate target tables if safe).')

# Write the report
out_path = BASE_DIR / 'docs' / 'SUPABASE_MIGRATION_READINESS.md'
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text('\n'.join(lines), encoding='utf-8')
print('Report written to', out_path)
