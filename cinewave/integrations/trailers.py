"""Validate trailer references and construct player URLs."""
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from flask import current_app, has_request_context, url_for

YOUTUBE_ID = re.compile(r'[A-Za-z0-9_-]{11}')
UPLOADED_TRAILER_PATH = re.compile(r'uploads/trailers/([a-f0-9]{32}\.(?:mp4|webm))')
NATIVE_TRAILER_PROVIDERS = {'upload', 'cloudinary'}
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


def optimized_projection_url(url):
    """Size plain Cloudinary uploads for projection, preserving authored transformations."""
    url = cloudinary_video_url(url)
    if not url:
        return None
    base, separator, asset = url.partition('/video/upload/')
    if separator and ('/' not in asset or re.match(r'v[0-9]+/', asset)):
        return f'{base}/video/upload/c_limit,h_480,w_960/q_auto/{asset}'
    return None


def uploaded_trailer_name(path):
    match = UPLOADED_TRAILER_PATH.fullmatch(path or '')
    return match[1] if match else None


def trailer_upload_directory():
    configured = current_app.config.get('TRAILER_UPLOAD_DIR')
    return Path(configured) if configured else Path(current_app.static_folder) / 'uploads' / 'trailers'


def save_trailer_upload(upload):
    """Keep the original filesystem layout and only publish native video files."""
    suffix = Path(upload.filename).suffix.lower()
    try:
        header = upload.stream.read(4096)
        upload.stream.seek(0)
        valid_mp4 = suffix == '.mp4' and header[4:8] == b'ftyp'
        valid_webm = suffix == '.webm' and header.startswith(b'\x1a\x45\xdf\xa3') and b'webm' in header
        if not (valid_mp4 or valid_webm):
            raise ValueError('Choose an MP4 or WebM video file.')
        filename = secrets.token_hex(16) + suffix
        directory = trailer_upload_directory()
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / filename).open('xb') as output:
            upload.save(output)
    except OSError as error:
        current_app.logger.warning('Could not write trailer upload: %s', type(error).__name__)
        raise ValueError('The trailer could not be saved. Check the upload storage and try again.') from error
    return f'uploads/trailers/{filename}'


def player(source, *, youtube=None, cloudinary=None, uploaded=None, movie_id=None):
    if source == 'upload' or (source is None and uploaded):
        filename = uploaded_trailer_name(uploaded)
        if not filename or movie_id is None:
            return None
        url = (url_for('movies.trailer_file', movie_id=movie_id, filename=filename)
               if has_request_context() else f'/movies/{movie_id}/trailer-file/{filename}')
        return {'provider': 'upload', 'url': url, 'external': url}
    if source == 'cloudinary':
        url = cloudinary_video_url(cloudinary)
        return {'provider': source, 'url': url, 'external': url} if url else None
    if youtube and YOUTUBE_ID.fullmatch(youtube):
        return {'provider': 'youtube', 'url': f'https://www.youtube-nocookie.com/embed/{youtube}',
                'external': f'https://www.youtube.com/watch?v={youtube}'}
    return None


def trailer_selection(form, *, upload=None, existing_path=None):
    action = form.get('trailer_action')
    if not action and upload and upload.filename:
        return 'upload', None, None, save_trailer_upload(upload)
    source = (action or form.get('trailer_source')
              or ('youtube' if form.get('youtube_trailer', '').strip() else 'auto'))
    if source == 'upload':
        if not uploaded_trailer_name(existing_path):
            raise ValueError('Choose a trailer file to upload.')
        return source, None, None, existing_path
    if source == 'youtube':
        key = parse_youtube_video_key(form.get('youtube_trailer'))
        if not key:
            raise ValueError('Enter a valid HTTPS YouTube link or video ID.')
        return source, key, None, None
    if source == 'cloudinary':
        url = cloudinary_video_url(form.get('cloudinary_trailer'))
        if not url:
            raise ValueError('Enter a direct Cloudinary HTTPS MP4 or WebM URL.')
        return source, None, url, None
    if source in {'auto', 'none'}:
        return source, None, None, None
    raise ValueError('Choose a trailer source.')
