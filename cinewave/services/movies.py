import json
import requests
from ..extensions import db
from ..models import Movie
from ..config import TMDB_API_KEY, TMDB_BASE_URL, TMDB_IMAGE_BASE



def _tmdb_find_id(title):
    """Best-effort TMDb lookup by title; returns the first result's id or None."""
    try:
        res = requests.get(f"{TMDB_BASE_URL}/search/movie",
                           params={'api_key': TMDB_API_KEY, 'query': title},
                           timeout=10).json()
        for item in res.get('results', []):
            if item.get('id'):
                return item['id']
    except Exception:
        pass
    return None


def _tmdb_fetch_credits(tmdb_id):
    """
    Returns (cast_entries, director_name) for a TMDb movie id; ([], None) on any
    failure so callers never hard-fail when TMDb is unreachable.
    """
    try:
        res = requests.get(f"{TMDB_BASE_URL}/movie/{tmdb_id}/credits",
                           params={'api_key': TMDB_API_KEY}, timeout=10).json()
        cast_entries = []
        for c in (res.get('cast') or [])[:12]:
            cast_entries.append({
                'name': c.get('name') or '',
                'character': c.get('character') or '',
                'profile': f"{TMDB_IMAGE_BASE}{c['profile_path']}" if c.get('profile_path') else None,
            })
        director = next((c.get('name') for c in (res.get('crew') or [])
                         if c.get('job') == 'Director'), None)
        return cast_entries, director
    except Exception:
        return [], None


def _store_movie_cast(movie, tmdb_id):
    """Fetch credits for tmdb_id and store them on the movie. Returns True if anything was saved."""
    cast_entries, director = _tmdb_fetch_credits(tmdb_id)
    if not cast_entries and not director:
        return False
    movie.tmdb_id = tmdb_id
    movie.cast_json = json.dumps({'director': director, 'cast': cast_entries})
    db.session.commit()
    return True
