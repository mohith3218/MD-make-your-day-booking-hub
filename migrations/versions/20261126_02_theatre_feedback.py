"""Add venue feedback to existing booking-linked review records."""
from alembic import op
import sqlalchemy as sa

revision = '20261126_02'
down_revision = '20261126_01'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('showtime', sa.Column('actual_ended_at', sa.DateTime()))
    op.add_column('screen_review', sa.Column('has_screen_feedback', sa.Boolean(),
                                            nullable=False, server_default=sa.true()))
    op.add_column('screen_review', sa.Column('theatre_rating', sa.Integer()))
    op.add_column('screen_review', sa.Column('theatre_review_text', sa.String(1000)))
    op.add_column('screen_review', sa.Column('theatre_updated_at', sa.DateTime()))
    op.add_column('screen_review', sa.Column('theatre_withdrawn_at', sa.DateTime()))
    where = sa.text('theatre_rating IS NOT NULL')
    op.create_index('uq_theatre_review_user_venue', 'screen_review', ['user_id', 'theater_id'],
                    unique=True, sqlite_where=where, postgresql_where=where)
    with op.batch_alter_table('movie_rating') as batch:
        batch.drop_constraint('ck_movie_rating_booked_review', type_='check')
        batch.create_check_constraint('ck_movie_rating_booked_review',
                                      'booking_id IS NULL OR (rating BETWEEN 1 AND 5 AND rating = CAST(rating AS INTEGER))')


def downgrade():
    raise RuntimeError('Downgrading could lose theatre feedback and rating-only reviews. Restore a verified backup.')
