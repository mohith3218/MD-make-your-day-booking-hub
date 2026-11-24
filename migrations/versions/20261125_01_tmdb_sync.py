"""Add TMDB synchronization state, metadata, and showtime cancellation."""
from alembic import op
import sqlalchemy as sa

revision = '20261125_01'
down_revision = '20261123_01'
branch_labels = None
depends_on = None


def upgrade():
    for name, column_type in (
        ('tmdb_legacy_id', sa.Integer()), ('tmdb_metadata', sa.JSON()),
        ('tmdb_snapshot', sa.JSON()), ('tmdb_overrides', sa.JSON()),
        ('tmdb_original_release_date', sa.Date()), ('tmdb_regional_release_date', sa.Date()),
        ('tmdb_rating', sa.Float()), ('tmdb_last_checked_at', sa.DateTime()),
    ):
        op.add_column('movie', sa.Column(name, column_type))
    op.add_column('movie', sa.Column('tmdb_managed', sa.Boolean(),
                                     nullable=False, server_default=sa.false()))
    op.add_column('showtime', sa.Column('is_cancelled', sa.Boolean(),
                                        nullable=False, server_default=sa.false()))

    # Keep every CineWave movie and its references. Only the oldest row owns
    # a duplicate external ID. The original association is retained for audit.
    op.execute("""
        UPDATE movie SET tmdb_legacy_id = tmdb_id, tmdb_id = NULL
        WHERE tmdb_id IS NOT NULL AND EXISTS (
            SELECT 1 FROM movie AS canonical
            WHERE canonical.tmdb_id = movie.tmdb_id AND canonical.id < movie.id
        )
    """)
    op.drop_index('ix_movie_tmdb_id', table_name='movie')
    op.create_index('ix_movie_tmdb_id', 'movie', ['tmdb_id'], unique=True)
    op.create_index('ix_movie_tmdb_refresh', 'movie', ['tmdb_last_checked_at'])

    op.create_table(
        'movie_sync_state',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('requested_at', sa.DateTime()),
        sa.Column('worker_seen_at', sa.DateTime()),
        sa.Column('last_attempt_at', sa.DateTime()),
        sa.Column('last_success_at', sa.DateTime()),
        sa.Column('next_run_at', sa.DateTime()),
        sa.Column('throttle_until', sa.DateTime()),
        sa.Column('lease_until', sa.DateTime()),
        sa.Column('run_token', sa.String(32)),
        sa.Column('counts', sa.JSON()),
        sa.Column('error', sa.String(300)),
    )
    op.create_table(
        'movie_sync_candidate',
        sa.Column('tmdb_id', sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column('next_attempt_at', sa.DateTime(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(16), nullable=False),
    )
    op.create_index('ix_movie_sync_candidate_next_attempt_at',
                    'movie_sync_candidate', ['next_attempt_at'])


def downgrade():
    op.drop_table('movie_sync_candidate')
    op.drop_table('movie_sync_state')
    op.drop_index('ix_movie_tmdb_refresh', table_name='movie')
    op.drop_index('ix_movie_tmdb_id', table_name='movie')
    op.create_index('ix_movie_tmdb_id', 'movie', ['tmdb_id'])
    op.execute('UPDATE movie SET tmdb_id = tmdb_legacy_id WHERE tmdb_id IS NULL')
    with op.batch_alter_table('movie') as batch:
        for name in (
            'tmdb_managed', 'tmdb_legacy_id', 'tmdb_metadata', 'tmdb_snapshot', 'tmdb_overrides',
            'tmdb_original_release_date', 'tmdb_regional_release_date', 'tmdb_rating',
            'tmdb_last_checked_at',
        ):
            batch.drop_column(name)
    with op.batch_alter_table('showtime') as batch:
        batch.drop_column('is_cancelled')
