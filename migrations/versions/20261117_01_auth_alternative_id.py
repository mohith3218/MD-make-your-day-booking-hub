"""Add revocable identifiers for remembered browser sessions."""
import secrets

from alembic import op
import sqlalchemy as sa

revision = '20261117_01'
down_revision = '20261114_02'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('alternative_id', sa.String(length=64), nullable=True))
    connection = op.get_bind()
    for row in connection.execute(sa.text('SELECT id FROM "user"')).fetchall():
        connection.execute(sa.text('UPDATE "user" SET alternative_id=:token WHERE id=:id'),
                           {'token': secrets.token_urlsafe(32), 'id': row.id})
    with op.batch_alter_table('user') as batch:
        batch.alter_column('alternative_id', existing_type=sa.String(length=64), nullable=False)
        batch.create_unique_constraint('uq_user_alternative_id', ['alternative_id'])


def downgrade():
    with op.batch_alter_table('user') as batch:
        batch.drop_constraint('uq_user_alternative_id', type_='unique')
        batch.drop_column('alternative_id')
