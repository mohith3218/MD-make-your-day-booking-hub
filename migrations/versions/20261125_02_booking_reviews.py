"""Distinguish demo reviews and extend movie ratings with booking evidence."""
from alembic import op
import sqlalchemy as sa

revision = '20261125_02'
down_revision = '20261125_01'
branch_labels = None
depends_on = None


def flag(name):
    return sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())


def upgrade():
    op.add_column('booking', sa.Column('screen_review_dismissed_at', sa.DateTime()))
    op.add_column('screen_review', flag('is_demo'))

    # Previous versions also marked reviews with no payment evidence as verified.
    op.execute("""
        UPDATE screen_review
        SET verified = CASE WHEN verified IS TRUE AND EXISTS (
                SELECT 1 FROM payment p JOIN booking b ON b.id = p.booking_id
                WHERE p.booking_id = screen_review.booking_id AND b.user_id = screen_review.user_id
                  AND b.status = 'PAID' AND p.status = 'CAPTURED' AND trim(p.gateway) <> ''
                  AND p.gateway NOT IN ('mock', 'mock-split', 'wallet')
                  AND (SELECT count(*) FROM payment WHERE booking_id = b.id) = 1
            ) THEN TRUE ELSE FALSE END,
            is_demo = CASE WHEN EXISTS (
                SELECT 1 FROM payment p JOIN booking b ON b.id = p.booking_id
                WHERE p.booking_id = screen_review.booking_id AND b.user_id = screen_review.user_id
                  AND b.status = 'PAID' AND b.paid_at IS NOT NULL AND p.status = 'CAPTURED'
                  AND p.gateway IN ('mock', 'mock-split', 'wallet')
                  AND (SELECT count(*) FROM payment WHERE booking_id = b.id) = 1
            ) THEN TRUE ELSE FALSE END
    """)
    with op.batch_alter_table('movie_rating') as batch:
        batch.add_column(sa.Column('booking_id', sa.Integer()))
        batch.add_column(sa.Column('title', sa.String(120)))
        for name in ('verified', 'is_demo', 'hidden'):
            batch.add_column(flag(name))
        batch.add_column(sa.Column('withdrawn_at', sa.DateTime()))
        batch.add_column(sa.Column('updated_at', sa.DateTime()))
        batch.create_foreign_key('fk_movie_rating_booking', 'booking', ['booking_id'], ['id'])
        batch.create_check_constraint('ck_movie_rating_booked_review',
                                      'booking_id IS NULL OR (rating BETWEEN 1 AND 5 AND rating = CAST(rating AS INTEGER)'
                                      ' AND review IS NOT NULL AND length(trim(review)) > 0)')
    op.create_index('ix_movie_rating_visibility', 'movie_rating', ['movie_id', 'hidden', 'withdrawn_at'])
    op.create_table(
        'movie_review_report',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('review_id', sa.Integer(), sa.ForeignKey('movie_rating.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('reason', sa.String(300), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime()),
        sa.UniqueConstraint('review_id', 'user_id', name='uq_movie_review_report_user'),
    )
    op.create_index('ix_movie_review_report_pending', 'movie_review_report', ['resolved_at', 'review_id'])
    op.create_table(
        'movie_review_moderation',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('review_id', sa.Integer(), sa.ForeignKey('movie_rating.id'), nullable=False),
        sa.Column('admin_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_movie_review_moderation_review_id', 'movie_review_moderation', ['review_id'])


def downgrade():
    raise RuntimeError('Review provenance and moderation history would be lost. Restore a verified backup instead.')
