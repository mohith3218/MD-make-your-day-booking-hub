"""Store one changeable hype vote per user and upcoming film."""
from alembic import op
import sqlalchemy as sa

revision = '20261117_04'
down_revision = '20261117_03'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('movie_hype_vote',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('movie_id', sa.Integer(), sa.ForeignKey('movie.id'), nullable=False),
        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', 'movie_id', name='uq_movie_hype_user_movie'))


def downgrade():
    op.drop_table('movie_hype_vote')
