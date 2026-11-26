"""Store automatic and administrator-selected trailers independently."""
import re

from alembic import op
import sqlalchemy as sa

revision = '20261126_01'
down_revision = '20261125_02'
branch_labels = None
depends_on = None


def upgrade():
    for name, column_type in (
        ('trailer_source', sa.String(12)), ('automatic_youtube_key', sa.String(11)),
        ('cloudinary_trailer_url', sa.String(500)), ('tmdb_trailer_checked_at', sa.DateTime()),
    ):
        op.add_column('movie', sa.Column(name, column_type))
    movie = sa.table('movie', sa.column('id', sa.Integer), sa.column('tmdb_id', sa.Integer),
                     sa.column('youtube_trailer_key', sa.String), sa.column('trailer_source', sa.String),
                     sa.column('automatic_youtube_key', sa.String), sa.column('trailer_video_path', sa.String),
                     sa.column('tmdb_snapshot', sa.JSON), sa.column('tmdb_overrides', sa.JSON))
    conn = op.get_bind()
    rows = conn.execute(sa.select(movie).where(
        sa.or_(movie.c.youtube_trailer_key.is_not(None), movie.c.trailer_video_path.is_not(None)))).mappings()
    for row in rows.all():
        key = row['youtube_trailer_key']
        if row['trailer_video_path']:
            values = {'trailer_source': 'none'}
        elif not key or not re.fullmatch(r'[A-Za-z0-9_-]{11}', key):
            continue
        elif (row['tmdb_id'] and (row['tmdb_snapshot'] or {}).get('youtube_trailer_key') == key
              and 'youtube_trailer_key' not in (row['tmdb_overrides'] or ())):
            values = {'trailer_source': 'auto', 'automatic_youtube_key': key}
        else:
            values = {'trailer_source': 'youtube'}
        conn.execute(movie.update().where(movie.c.id == row['id']).values(**values))


def downgrade():
    for field in ('tmdb_trailer_checked_at', 'cloudinary_trailer_url', 'automatic_youtube_key', 'trailer_source'):
        op.drop_column('movie', field)
