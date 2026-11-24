from ..extensions import db


class MovieSyncState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requested_at = db.Column(db.DateTime)
    worker_seen_at = db.Column(db.DateTime)
    last_attempt_at = db.Column(db.DateTime)
    last_success_at = db.Column(db.DateTime)
    next_run_at = db.Column(db.DateTime)
    throttle_until = db.Column(db.DateTime)
    lease_until = db.Column(db.DateTime)
    run_token = db.Column(db.String(32))
    counts = db.Column(db.JSON)
    error = db.Column(db.String(300))


class MovieSyncCandidate(db.Model):
    tmdb_id = db.Column(db.Integer, primary_key=True, autoincrement=False)
    next_attempt_at = db.Column(db.DateTime, nullable=False, index=True)
    attempts = db.Column(db.Integer, nullable=False)
    source = db.Column(db.String(16), nullable=False)
