"""Add booking-backed screen reviews, reports and moderation history."""
from alembic import op
import sqlalchemy as sa

revision = '20261123_01'
down_revision = '20261119_01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'screen_review',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('booking_id', sa.Integer(), sa.ForeignKey('booking.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('theater_id', sa.Integer(), sa.ForeignKey('theater.id'), nullable=False),
        sa.Column('screen_id', sa.Integer(), sa.ForeignKey('screen.id'), nullable=False),
        sa.Column('overall_rating', sa.Integer(), nullable=False),
        sa.Column('sound_rating', sa.Integer()),
        sa.Column('ac_rating', sa.Integer()),
        sa.Column('comfort_rating', sa.Integer()),
        sa.Column('review_text', sa.String(1000)),
        sa.Column('verified', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('hidden', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('withdrawn_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('booking_id', name='uq_screen_review_booking'),
        *(sa.CheckConstraint(f'{field} BETWEEN 1 AND 5 AND {field} = CAST({field} AS INTEGER)',
                             name=f'ck_screen_review_{field}')
          for field in ('overall_rating', 'sound_rating', 'ac_rating', 'comfort_rating')),
        sa.CheckConstraint('length(review_text) <= 1000', name='ck_screen_review_text_length'),
    )
    for group in ('screen', 'theater'):
        op.create_index(f'ix_screen_review_{group}_visibility', 'screen_review',
                        [f'{group}_id', 'hidden', 'withdrawn_at'])
    op.create_table(
        'screen_review_report',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('review_id', sa.Integer(), sa.ForeignKey('screen_review.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('reason', sa.String(300), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime()),
        sa.UniqueConstraint('review_id', 'user_id', name='uq_screen_review_report_user'),
    )
    op.create_index('ix_screen_review_report_pending', 'screen_review_report', ['resolved_at', 'review_id'])
    op.create_table(
        'screen_review_moderation',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('review_id', sa.Integer(), sa.ForeignKey('screen_review.id'), nullable=False),
        sa.Column('admin_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_screen_review_moderation_review_id', 'screen_review_moderation', ['review_id'])


def downgrade():
    op.drop_table('screen_review_moderation')
    op.drop_table('screen_review_report')
    op.drop_table('screen_review')
