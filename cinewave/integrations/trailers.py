"""Validate trailer references and construct player URLs."""
import re
from urllib.parse import urlsplit, parse_qs

YOUTUBE_ID = re.compile(r'[A-Za-z0-9_-]{11}')
CLOUDINARY_PATH = re.compile(
    r'/[A-Za-z0-9_-]+/video/upload/(?:[A-Za-z0-9_.,%-]+/)*[A-Za-z0-9_.,%-]+\.(?:mp4|webm)',
    re.IGNORECASE,
)


def parse_youtube_video_key(value):
    value = (value or '').strip()
    if not value:
        return ''
    if YOUTUBE_ID.fullmatch(value):
        return value
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    if url.scheme != 'https' or url.netloc != url.hostname:
        return None
    parts = url.path.strip('/').split('/')
    key = None
    if url.hostname in {'youtu.be', 'www.youtu.be'}:
        key = parts[0] if len(parts) == 1 else None
    elif url.hostname in {'youtube.com', 'www.youtube.com', 'm.youtube.com',
                          'youtube-nocookie.com', 'www.youtube-nocookie.com'}:
        if url.path == '/watch':
            key = parse_qs(url.query).get('v', [''])[0]
        elif len(parts) == 2 and parts[0] in {'embed', 'shorts', 'live'}:
            key = parts[1]
    return key if key and YOUTUBE_ID.fullmatch(key) else None


def cloudinary_video_url(value):
    value = (value or '').strip()
    if not value or len(value) > 500 or any(char.isspace() for char in value):
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    if (url.scheme == 'https' and url.netloc == 'res.cloudinary.com'
            and not url.query and not url.fragment and CLOUDINARY_PATH.fullmatch(url.path)
            and not any(segment in {'.', '..'} or '%2e' in segment.lower() or '%2f' in segment.lower()
                        or '%5c' in segment.lower() for segment in url.path.split('/'))):
        return value
    return None


def player(source, *, youtube=None, cloudinary=None):
    if source == 'cloudinary':
        url = cloudinary_video_url(cloudinary)
        return {'provider': source, 'url': url, 'external': url} if url else None
    if youtube and YOUTUBE_ID.fullmatch(youtube):
        return {'provider': 'youtube', 'url': f'https://www.youtube-nocookie.com/embed/{youtube}',
                'external': f'https://www.youtube.com/watch?v={youtube}'}
    return None


def trailer_selection(form):
    source = (form.get('trailer_action') or form.get('trailer_source')
              or ('youtube' if form.get('youtube_trailer', '').strip() else 'auto'))
    if source == 'youtube':
        key = parse_youtube_video_key(form.get('youtube_trailer'))
        if not key:
            raise ValueError('Enter a valid HTTPS YouTube link or video ID.')
        return source, key, None
    if source == 'cloudinary':
        url = cloudinary_video_url(form.get('cloudinary_trailer'))
        if not url:
            raise ValueError('Enter a direct Cloudinary HTTPS MP4 or WebM URL.')
        return source, None, url
    if source in {'auto', 'none'}:
        return source, None, None
    raise ValueError('Choose a trailer source.')
