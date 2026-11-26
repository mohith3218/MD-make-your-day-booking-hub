"""Shared TMDB client and movie metadata mapping for admin and worker use."""
import json
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from time import sleep
from urllib.parse import urlsplit

import requests
from flask import current_app

from ..config import TMDB_BACKDROP_BASE, TMDB_BASE_URL, TMDB_IMAGE_BASE
from ..time import cinema_now
from .trailers import YOUTUBE_ID

LANGUAGES = {
    'bn': 'Bengali', 'en': 'English', 'gu': 'Gujarati', 'hi': 'Hindi',
    'kn': 'Kannada', 'ml': 'Malayalam', 'mr': 'Marathi', 'or': 'Odia',
    'pa': 'Punjabi', 'ta': 'Tamil', 'te': 'Telugu', 'ur': 'Urdu',
}
IMAGE_PATH = re.compile(r'/[A-Za-z0-9_-]+\.(?:jpe?g|png|webp)', re.I)


class TMDBError(Exception):
    def __init__(self, message, *, status=None, retry_after=0):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def retry_delay(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value).astimezone(timezone.utc)
            return max(0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0


class TMDBClient:
    def __init__(self, *, heartbeat=None, attempts=3):
        self.key = current_app.config['TMDB_API_KEY']
        self.token = current_app.config['TMDB_READ_TOKEN']
        self.region = current_app.config['TMDB_REGION']
        self.session = requests.Session()
        self.heartbeat = heartbeat
        self.attempts = attempts

    def __enter__(self):
        return self

    def __exit__(self, *error):
        self.session.close()

    def get(self, path, **params):
        if not self.key and not self.token:
            raise TMDBError('TMDB credentials are missing.')
        headers = {'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        else:
            params['api_key'] = self.key
        for attempt in range(self.attempts):
            if self.heartbeat:
                self.heartbeat()
            try:
                with self.session.get(TMDB_BASE_URL + path, params=params, headers=headers,
                                      timeout=(3.05, 10), allow_redirects=False) as response:
                    status = response.status_code
                    if status == 200:
                        payload = response.json()
                        if isinstance(payload, dict):
                            return payload
                        raise ValueError('Invalid response shape')
                    error = TMDBError(f'TMDB returned HTTP {status}.', status=status,
                                      retry_after=retry_delay(response.headers.get('Retry-After')))
            except (requests.RequestException, ValueError):
                error = TMDBError('TMDB returned an invalid response or could not be reached.')
            if error.status not in (None, 429) and error.status < 500:
                break
            delay = max(2 ** attempt, error.retry_after)
            if attempt + 1 == self.attempts or delay > 30:
                break
            sleep(delay)
        raise error from None

    def search(self, query):
        return self.get('/search/movie', query=query, region=self.region, include_adult='false')

    def details(self, movie_id):
        detail = self.get(f'/movie/{movie_id}',
                          append_to_response='credits,videos,release_dates,images',
                          include_image_language='en,null')
        if type(detail.get('id')) is not int or detail['id'] != movie_id:
            raise TMDBError('TMDB returned details for an unexpected movie.', status=422)
        language = clean_text(detail.get('original_language'))
        if not meaningful_overview(detail.get('overview')) and language and language != 'en':
            original = self.get(f'/movie/{movie_id}', language=language)
            if original.get('id') == movie_id:
                if meaningful_overview(original.get('overview')):
                    detail['overview'] = original['overview']
                for field in ('title', 'poster_path', 'tagline'):
                    if not clean_text(detail.get(field)) and clean_text(original.get(field)):
                        detail[field] = original[field]
        videos = section_entries(detail, 'videos')
        preferred = language if language and re.fullmatch(r'[a-z]{2}', language) else 'en'
        if not any(official_trailer(video) and video.get('iso_639_1') == preferred
                   and playable_video(video) for video in videos):
            try:
                payload = self.get(f'/movie/{movie_id}/videos', language=preferred)
                videos.extend(entries(payload.get('results')))
            except TMDBError as error:
                detail['trailer_lookup_error'] = error
        detail['videos'] = {'results': videos}
        return detail


def clean_text(value, length=None):
    value = value.strip() if isinstance(value, str) else ''
    return (value[:length] if length else value) or None


def meaningful_overview(value):
    value = clean_text(value)
    if value and any(char.isalnum() for char in value):
        if value.casefold().rstrip('.') not in {
            'tba', 'n/a', 'tbd', 'no overview available', 'no description available'
        }:
            return value
    return None


def parse_release_date(value):
    try:
        return date.fromisoformat(value[:10]) if isinstance(value, str) else None
    except ValueError:
        return None


def image_url(path, base=TMDB_IMAGE_BASE):
    if isinstance(path, str) and IMAGE_PATH.fullmatch(path):
        return base + path
    return None


def poster_identity(url):
    try:
        parts = urlsplit(url or '')
    except ValueError:
        return None
    path = '/' + parts.path.rsplit('/', 1)[-1]
    if parts.hostname == 'image.tmdb.org' and IMAGE_PATH.fullmatch(path):
        return path
    return None


def entries(value):
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []


def section_entries(payload, section, field='results'):
    value = payload.get(section)
    return entries(value.get(field)) if isinstance(value, dict) else []


def official_trailer(video):
    return video.get('official') is True and video.get('type') == 'Trailer'


def playable_video(video):
    key = video.get('key')
    return video.get('site') == 'YouTube' and isinstance(key, str) and YOUTUBE_ID.fullmatch(key)


def best_trailer(videos, preferred_language):
    suitable = [video for video in videos if playable_video(video) and (
        video.get('type') == 'Trailer' or (video.get('type') == 'Teaser' and video.get('official') is True))]
    best = max(suitable, key=lambda video: (
        video.get('type') == 'Trailer', video.get('official') is True,
        bool(preferred_language and video.get('iso_639_1') == preferred_language),
    ), default=None)
    return best['key'] if best else None


def normalized(value):
    return ' '.join((value or '').casefold().split())


def movie_metadata(detail, region, *, source=None):
    original_date = parse_release_date(detail.get('release_date'))
    release_rows = next((entries(group.get('release_dates'))
                         for group in section_entries(detail, 'release_dates')
                         if group.get('iso_3166_1') == region), [])
    dates = [(row['type'], released, clean_text(row.get('certification'), 10))
             for row in release_rows if row.get('type') in (2, 3)
             if (released := parse_release_date(row.get('release_date')))]
    dates.sort(key=lambda item: (-item[0], item[1]))
    regional_date = dates[0][1] if dates else None
    certification = next((cert for _, _, cert in dates if cert), None)
    today = cinema_now().date()
    release_date = regional_date or original_date
    upcoming = release_date > today if release_date else (
        source == 'upcoming' or detail.get('status') in {'Planned', 'In Production', 'Post Production'})

    language_code = clean_text(detail.get('original_language'), 12)
    spoken_languages = {item.get('iso_639_1'): item.get('english_name')
                        for item in entries(detail.get('spoken_languages'))}
    language = LANGUAGES.get(language_code) or spoken_languages.get(language_code) or language_code
    runtime = detail.get('runtime')
    rating = detail.get('vote_average')
    votes = detail.get('vote_count')
    cast = [{'name': person['name'], 'character': clean_text(person.get('character')),
             'profile': image_url(person.get('profile_path'))}
            for person in section_entries(detail, 'credits', 'cast')[:12] if clean_text(person.get('name'))]
    director = next((person['name'] for person in section_entries(detail, 'credits', 'crew')
                     if person.get('job') == 'Director' and clean_text(person.get('name'))), None)
    poster = image_url(detail.get('poster_path')) or next((
        url for item in section_entries(detail, 'images', 'posters')
        if (url := image_url(item.get('file_path')))), None)
    return {
        'title': clean_text(detail.get('title'), 200) or clean_text(detail.get('original_title'), 200),
        'description': meaningful_overview(detail.get('overview')),
        'poster': poster,
        'backdrop': image_url(detail.get('backdrop_path'), TMDB_BACKDROP_BASE),
        'duration': runtime if type(runtime) is int and 0 < runtime <= 9999 else None,
        'language': clean_text(language, 50),
        'certificate': certification,
        'is_upcoming': upcoming,
        'release_date': release_date,
        'tmdb_original_release_date': original_date,
        'tmdb_regional_release_date': regional_date,
        'tmdb_rating': (rating if type(rating) in (int, float) and 0 <= rating <= 10
                        and type(votes) is int and votes > 0 else None),
        'automatic_youtube_key': best_trailer(section_entries(detail, 'videos'), language_code),
        'cast_json': json.dumps({'director': director, 'cast': cast}, ensure_ascii=False) if cast or director else None,
        'tmdb_metadata': {
            'genres': [item['name'] for item in entries(detail.get('genres')) if clean_text(item.get('name'))],
            'production_companies': [item['name'] for item in entries(detail.get('production_companies'))
                                     if clean_text(item.get('name'))],
            'original_language': language_code,
            'original_title': clean_text(detail.get('original_title')),
            'tagline': clean_text(detail.get('tagline')),
        },
    }


def minimum_metadata(fields):
    return all(fields[key] for key in ('title', 'description', 'poster'))
