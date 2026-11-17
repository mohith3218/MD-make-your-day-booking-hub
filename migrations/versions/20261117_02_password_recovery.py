"""Add expiring password recovery links and database throttles."""
from alembic import op
import sqlalchemy as sa

revision = '20261117_02'
down_revision = '20261117_01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('password_reset',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_digest', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('token_digest', name='uq_password_reset_token_digest'))
    op.create_index('ix_password_reset_user_id', 'password_reset', ['user_id'])
    op.create_table('password_reset_throttle',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('throttle_key', sa.String(length=64), nullable=False),
        sa.Column('window_started', sa.DateTime(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.UniqueConstraint('throttle_key', name='uq_password_reset_throttle_key'))


def downgrade():
    op.drop_table('password_reset_throttle')
    op.drop_index('ix_password_reset_user_id', table_name='password_reset')
    op.drop_table('password_reset')
