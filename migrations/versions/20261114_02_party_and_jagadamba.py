"""Prevent duplicate party membership and correct only Jagadamba's physical levels."""
import json

from alembic import op
import sqlalchemy as sa

revision = '20261114_02'
down_revision = '20261110_01'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # Legacy anonymous memberships cannot be reused by authenticated clients.
    # Keep the newest row per authenticated identity before adding uniqueness.
    conn.execute(sa.text('''DELETE FROM party_member WHERE user_id IS NOT NULL
        AND id NOT IN (SELECT MAX(id) FROM party_member WHERE user_id IS NOT NULL
                       GROUP BY party_id, user_id)'''))
    op.create_index('uq_party_member_user', 'party_member', ['party_id', 'user_id'], unique=True)
    from vizag_theaters import correct_jagadamba_levels
    rows = conn.execute(sa.text('''SELECT s.id, s.layout_json FROM screen s
        JOIN theater t ON t.id = s.theater_id
        WHERE t.name = 'Jagadamba Theatre' AND s.name = '70MM Main' '''))
    for row in rows.mappings().all():
        layout = correct_jagadamba_levels(json.loads(row['layout_json']), 'Jagadamba Theatre', '70MM Main')
        conn.execute(sa.text('UPDATE screen SET layout_json=:layout WHERE id=:id'),
                     {'layout': json.dumps(layout), 'id': row['id']})


def downgrade():
    raise RuntimeError('Destructive downgrade disabled; restore a verified backup instead.')
