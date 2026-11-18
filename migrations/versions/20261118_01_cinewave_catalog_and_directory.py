"""Add reversible movie archiving and evidence-backed theatre verification."""
from alembic import op
import sqlalchemy as sa

revision = '20261118_01'
down_revision = '20261117_04'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('movie', sa.Column('is_archived', sa.Boolean(), nullable=False,
                                     server_default=sa.false()))
    for table in ('theater', 'screen'):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('verification_status', sa.String(length=20),
                                       nullable=False, server_default='unverified'))
            batch.add_column(sa.Column('verification_source_url', sa.String(length=500), nullable=True))
            batch.add_column(sa.Column('verification_notes', sa.Text(), nullable=True))
            batch.add_column(sa.Column('verification_reviewed_at', sa.DateTime(), nullable=True))
            batch.add_column(sa.Column('verification_reviewed_by_id', sa.Integer(),
                                       sa.ForeignKey('user.id', name='fk_directory_verification_reviewed_by_user'),
                                       nullable=True))


def downgrade():
    for table in ('screen', 'theater'):
        with op.batch_alter_table(table) as batch:
            batch.drop_column('verification_reviewed_by_id')
            batch.drop_column('verification_reviewed_at')
            batch.drop_column('verification_notes')
            batch.drop_column('verification_source_url')
            batch.drop_column('verification_status')
    op.drop_column('movie', 'is_archived')
