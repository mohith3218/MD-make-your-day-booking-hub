import sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from database_config import database_settings

# SQLite DB path
sqlite_path = Path('C:/Code/MD-booking-hub/vizag_movies.db')
if not sqlite_path.is_file():
    raise RuntimeError(f'SQLite DB not found at {sqlite_path}')
sqlite_url = f'sqlite:///{sqlite_path}'
sqlite_engine = create_engine(sqlite_url, pool_pre_ping=True, hide_parameters=True)
sqlite_inspector = inspect(sqlite_engine)

# Supabase PostgreSQL connection
pg_url, pg_opts = database_settings()
pg_engine = create_engine(pg_url, **pg_opts)
pg_inspector = inspect(pg_engine)

# Helper to count rows
def count_rows(engine, table):
    with engine.connect() as conn:
        result = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
        return result.scalar()

# Tables of interest
tables = ['theater', 'screen']
report_lines = []
report_lines.append('## Theatre‑related record counts')
for tbl in tables:
    sqlite_cnt = count_rows(sqlite_engine, tbl)
    pg_cnt = count_rows(pg_engine, tbl)
    report_lines.append(f'- Table `{tbl}`: SQLite={sqlite_cnt}, Supabase={pg_cnt}')

# Seats are stored in `screen.layout_json`; we will count total seat entries per screen using the seat_layout helper
from seat_layout import count_seats
with sqlite_engine.connect() as conn:
    screens = conn.execute(text('SELECT id, layout_json FROM screen')).fetchall()
    total_seats_sqlite = sum(count_seats(row['layout_json']) for row in screens)
report_lines.append(f'- Total seats (derived from `screen.layout_json` in SQLite): {total_seats_sqlite}')

# For PostgreSQL, same approach
with pg_engine.connect() as conn:
    screens = conn.execute(text('SELECT id, layout_json FROM screen')).fetchall()
    total_seats_pg = sum(count_seats(row['layout_json']) for row in screens)
report_lines.append(f'- Total seats (derived from `screen.layout_json` in Supabase): {total_seats_pg}')

# Output
out_path = Path('C:/Code/MD-booking-hub/docs/THEATRE_DATA_COUNTS.md')
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text('\n'.join(report_lines), encoding='utf-8')
print('Counts written to', out_path)
