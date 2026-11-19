"""Add admin-ranked featured movie artwork and ordering."""
from alembic import op
import sqlalchemy as sa

revision = '20261119_01'
down_revision = '20261118_01'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('movie', sa.Column('backdrop', sa.String(length=500), nullable=True))
    op.add_column('movie', sa.Column('featured_order', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('movie', 'featured_order')
    op.drop_column('movie', 'backdrop')
