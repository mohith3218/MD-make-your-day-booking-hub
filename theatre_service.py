"""
theatre_service.py – Read-only Supabase query layer for Theatre and Screen data.

Architecture
------------
The Flask application uses SQLite (instance/vizag_movies.db) as its primary
Flask-SQLAlchemy database. All ORM models (User, Showtime, Booking, etc.),
including Theater and Screen, live on SQLite so that ORM relationships and
cross-table joins (Booking → Showtime → Screen → Theater) work without
modification.

This module holds a *separate*, lightweight SQLAlchemy engine that connects
directly to Supabase PostgreSQL.  It is used by selected read-only theatre-
listing endpoints to surface Supabase as the authoritative source for
theatre and screen data.  It never writes to Supabase and never participates
in SQLite transactions.

Usage
-----
    from theatre_service import TheatreService
    service = TheatreService.get()          # returns None when unavailable
    if service:
        theatres = service.all_theatres()   # list[dict]
    else:
        theatres = None                     # caller falls back to ORM

Thread safety
-------------
The module keeps a single engine per process (lazy-initialised).  SQLAlchemy
connection pools are thread-safe.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level engine singleton (created once, reused)
# ---------------------------------------------------------------------------
_engine: Optional[Engine] = None
_engine_attempted: bool = False   # avoid repeated failed init logs


def _build_engine() -> Optional[Engine]:
    """Create and return a Supabase engine, or None on any configuration error."""
    global _engine, _engine_attempted
    if _engine_attempted:
        return _engine
    _engine_attempted = True
    try:
        from database_config import database_settings
        url, opts = database_settings()
        if url.get_backend_name() != 'postgresql':
            logger.info("theatre_service: DATABASE_URL is not PostgreSQL; Supabase reads disabled.")
            return None
        engine = create_engine(url, **opts)
        # Quick connectivity probe – fail fast so the app still starts cleanly.
        with engine.connect() as probe:
            cnt = probe.execute(text('SELECT count(*) FROM "theater"')).scalar()
        logger.info("theatre_service: Supabase engine ready. theater rows=%s", cnt)
        _engine = engine
    except Exception as exc:
        logger.warning("theatre_service: could not connect to Supabase (%s). "
                       "Theatre routes will fall back to SQLite.", exc)
        _engine = None
    return _engine


# ---------------------------------------------------------------------------
# Public service class
# ---------------------------------------------------------------------------

class TheatreService:
    """
    Provides read-only access to theatre and screen data from Supabase.

    Every public method returns plain Python dicts (never SQLAlchemy model
    instances) so the caller is never accidentally inside a cross-database ORM
    session.

    Call ``TheatreService.get()`` to obtain the shared instance; it returns
    ``None`` when Supabase is unavailable so callers can fall back gracefully.
    """

    _instance: Optional["TheatreService"] = None

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def get(cls) -> Optional["TheatreService"]:
        """Return the shared TheatreService, or None if Supabase is not reachable."""
        if cls._instance is None:
            engine = _build_engine()
            if engine is not None:
                cls._instance = cls(engine)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Force re-initialisation (useful in tests)."""
        global _engine, _engine_attempted
        if _engine:
            _engine.dispose()
        _engine = None
        _engine_attempted = False
        cls._instance = None

    # ------------------------------------------------------------------
    # Public read methods – all return list[dict] or dict | None
    # ------------------------------------------------------------------

    def all_theatres(self) -> list[dict[str, Any]]:
        """Return all theatres ordered by name, each as a plain dict."""
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                'SELECT id, name, location, city, address '
                'FROM "theater" ORDER BY name'
            )).mappings().all()
        return [dict(r) for r in rows]

    def theatre_by_id(self, theatre_id: int) -> Optional[dict[str, Any]]:
        """Return one theatre dict, or None if not found."""
        with self._engine.connect() as conn:
            row = conn.execute(text(
                'SELECT id, name, location, city, address '
                'FROM "theater" WHERE id = :id'
            ), {"id": theatre_id}).mappings().first()
        return dict(row) if row else None

    def screens_for_theatre(self, theatre_id: int) -> list[dict[str, Any]]:
        """Return all screens for a theatre, each as a plain dict."""
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                'SELECT id, theater_id, name, screen_type, layout_json '
                'FROM "screen" WHERE theater_id = :tid ORDER BY id'
            ), {"tid": theatre_id}).mappings().all()
        return [dict(r) for r in rows]

    def screen_by_id(self, screen_id: int) -> Optional[dict[str, Any]]:
        """Return one screen dict (including layout_json), or None."""
        with self._engine.connect() as conn:
            row = conn.execute(text(
                'SELECT s.id, s.theater_id, s.name, s.screen_type, s.layout_json, '
                '       t.name AS theater_name, t.location AS theater_location '
                'FROM "screen" s '
                'JOIN "theater" t ON t.id = s.theater_id '
                'WHERE s.id = :id'
            ), {"id": screen_id}).mappings().first()
        return dict(row) if row else None

    def all_theatres_with_screens(self) -> list[dict[str, Any]]:
        """
        Return all theatres, each with an embedded ``screens`` list.
        Suitable for the full theatre listing page.
        """
        with self._engine.connect() as conn:
            t_rows = conn.execute(text(
                'SELECT id, name, location, city, address FROM "theater" ORDER BY name'
            )).mappings().all()
            s_rows = conn.execute(text(
                'SELECT id, theater_id, name, screen_type FROM "screen" ORDER BY theater_id, id'
            )).mappings().all()

        screens_by_theatre: dict[int, list[dict]] = {}
        for s in s_rows:
            screens_by_theatre.setdefault(s["theater_id"], []).append(dict(s))

        result = []
        for t in t_rows:
            td = dict(t)
            td["screens"] = screens_by_theatre.get(t["id"], [])
            result.append(td)
        return result

    def counts(self) -> dict[str, int]:
        """Return {'theatres': N, 'screens': M} from Supabase."""
        with self._engine.connect() as conn:
            tc = conn.execute(text('SELECT count(*) FROM "theater"')).scalar()
            sc = conn.execute(text('SELECT count(*) FROM "screen"')).scalar()
        return {"theatres": int(tc or 0), "screens": int(sc or 0)}
