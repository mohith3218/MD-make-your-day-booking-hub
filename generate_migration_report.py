import os, sys
from pathlib import Path
sys.path.append('C:/Code/MD-booking-hub')
from sqlalchemy import create_engine, inspect
from database_config import database_settings

# SQLite DB (main file)
sqlite_path = Path('C:/Code/MD-booking-hub/vizag_movies.db')
if not sqlite_path.exists():
    raise RuntimeError('SQLite DB not found at {}'.format(sqlite_path))
sqlite_url = f'sqlite:///{sqlite_path}'
sqlite_engine = create_engine(sqlite_url, pool_pre_ping=True, hide_parameters=True)
sqlite_inspector = inspect(sqlite_engine)

# PostgreSQL (Supabase) connection
pg_url, pg_opts = database_settings()
pg_engine = create_engine(pg_url, **pg_opts)
pg_inspector = inspect(pg_engine)

def get_schema(inspector):
    schema = {}
    for table in inspector.get_table_names():
        cols = []
        for col in inspector.get_columns(table):
            cols.append((col['name'], str(col['type']), col.get('nullable'), col.get('default')))
        pk_info = inspector.get_pk_constraint(table)
        pk = pk_info.get('constrained_columns', [])
        uniques = [uq['name'] for uq in inspector.get_unique_constraints(table)]
        indexes = [idx['name'] for idx in inspector.get_indexes(table)]
        fks = []
        for fk in inspector.get_foreign_keys(table):
            fks.append((fk['constrained_columns'], fk['referred_table'], fk['referred_columns']))
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

missing_in_pg = set(sqlite_schema.keys()) - set(pg_schema.keys())
extra_in_pg = set(pg_schema.keys()) - set(sqlite_schema.keys())

def format_schema(s):
    lines = []
    for table, info in sorted(s.items()):
        lines.append(f"### {table}")
        lines.append("- Columns:")
        for name, typ, null, default in info['columns']:
            lines.append(f"  - `{name}`: {typ}, nullable={null}, default={default}")
        lines.append(f"- Primary key: {info['primary_key']}")
        lines.append(f"- Unique constraints: {info['uniques']}")
        lines.append(f"- Indexes: {info['indexes']}")
        lines.append(f"- Foreign keys: {info['foreign_keys']}")
        lines.append("")
    return "\n".join(lines)

report_lines = []
report_lines.append("# Supabase Migration Readiness – Assessment Report")
report_lines.append("\n---\n")
report_lines.append("## Schema Overview – SQLite (local)")
report_lines.append(format_schema(sqlite_schema))
report_lines.append("## Schema Overview – Supabase PostgreSQL (remote)")
report_lines.append(format_schema(pg_schema))
report_lines.append("## Table Presence Comparison")
report_lines.append(f"- Tables only in SQLite: {sorted(missing_in_pg)}")
report_lines.append(f"- Tables only in PostgreSQL: {sorted(extra_in_pg)}")
report_lines.append("\n---\n")
report_lines.append("## Migration Risks & Recommendations")
report_lines.append("- Verify data types match (e.g., INTEGER vs BIGINT, TEXT vs VARCHAR).")
report_lines.append("- Ensure all foreign‑key references exist in target DB before copying data.")
report_lines.append("- Preserve existing PostgreSQL data – do **not** drop or truncate tables.")
report_lines.append("- Use Alembic’s `--sql` mode to generate SQL scripts for any missing tables or columns, then review before applying.")
report_lines.append("- Back‑up SQLite: copy `vizag_movies.db` to a safe location (already present in `instance/` backups).")
report_lines.append("- Back‑up PostgreSQL: `pg_dump --format=custom --no-owner --no-acl -f supabase_backup.dump <DATABASE_URL>` (run manually).")
report_lines.append("- If Supabase already contains data, plan a **merge** strategy rather than overwrite.")

out_path = Path('C:/Code/MD-booking-hub/docs/SUPABASE_MIGRATION_READINESS.md')
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text('\n'.join(report_lines))
print('Report written to', out_path)
