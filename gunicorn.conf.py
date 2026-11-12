"""Read-only production preflight for the existing app:app WSGI entry point.

Gunicorn loads this file automatically from the repository working directory.
No schema migrations, seeders or database writes run on production startup.
"""


def on_starting(server):
    from app import app, db, init_db, validate_production_config
    with app.app_context():
        validate_production_config()
    if app.config['APP_ENV'] == 'production':
        init_db()  # existing production branch only checks schema/connectivity
        with app.app_context():
            db.engine.dispose()  # workers open fresh connections after fork
