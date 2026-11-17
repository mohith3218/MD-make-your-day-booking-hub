"""Record idempotent CinePass to demo-wallet conversions."""
from alembic import op
import sqlalchemy as sa

revision = '20261117_03'
down_revision = '20261117_02'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('wallet_point_conversion',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('idempotency_key', sa.String(length=64), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('credit', sa.Float(), nullable=False),
        sa.Column('balance_after', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', 'idempotency_key',
                            name='uq_wallet_points_conversion_request'))


def downgrade():
    op.drop_table('wallet_point_conversion')
