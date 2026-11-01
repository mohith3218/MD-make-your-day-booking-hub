import urllib.request

req = urllib.request.Request('http://127.0.0.1:5000/book/40/vr-preview')
with urllib.request.urlopen(req, timeout=30) as r:
    body = r.read()

open('vr_preview_fetched.html', 'wb').write(body)
print('status', r.status)
print('bytes', len(body))

lower = body.lower()
for needle in [b'<html', b'<head', b'<body', b'currentAudi', b'three.min', b'threedot', b'canvas-container', b'"type":"module"', b'preview-embedded', b'#[68]', b'#f5e47b'.lower(), b'selectSeats', b'postMessage']:
    print(needle, needle in lower)
