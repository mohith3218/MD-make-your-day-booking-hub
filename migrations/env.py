"""Use the backend configuration, never a credential stored in alembic.ini."""
from alembic import context
from app import app, db

with app.app_context():
    connection = context.config.attributes.get('connection')
    def migrate(conn):
        context.configure(connection=conn, target_metadata=db.metadata,
                          compare_type=True, render_as_batch=conn.dialect.name == 'sqlite')
        with context.begin_transaction():
            context.run_migrations()

    if connection is not None:
        migrate(connection)
    else:
        with db.engine.connect() as conn:
            migrate(conn)
