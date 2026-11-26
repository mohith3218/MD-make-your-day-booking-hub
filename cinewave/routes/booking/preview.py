import seat_layout as sl
from cinewave.integrations.trailers import optimized_projection_url
from cinewave.models import Screen, Showtime
from cinewave.services import admin_required, purge_expired_holds
from datetime import date
from flask import abort, render_template, request
from flask_login import login_required
from types import SimpleNamespace

from . import bp


@bp.route('/book/<int:showtime_id>/vr-preview')
@login_required
def vr_seat_preview(showtime_id):
    """Render the immersive seat preview from this show's real screen layout."""
    admin_screen_id = request.args.get('admin_screen', type=int)
    if admin_screen_id is not None:
        guard = admin_required()
        if guard:
            return guard
        screen_for_preview = Screen.query.get_or_404(admin_screen_id)
        showtime = SimpleNamespace(
            screen=screen_for_preview, layout=screen_for_preview.layout or {},
            theater=screen_for_preview.theater.name,
            movie=SimpleNamespace(title='Auditorium profile comparison', trailer=None),
            show_date=date.today(), show_time='Admin preview',
            price_overrides={}, dynamic_pricing_info={'factor': 1},
            booked_seat_ids=lambda: set(), held_seat_ids=lambda: set(),
        )
    else:
        purge_expired_holds()
        showtime = Showtime.query.get_or_404(showtime_id)
    if not showtime.screen:
        abort(404)

    layout = showtime.layout or {}
    geometry_errors = sl.validate_auditorium_geometry(layout)
    if geometry_errors:
        abort(422, description="This screen layout needs correction before the 3D preview can safely render it: " + geometry_errors[0])
    booked = showtime.booked_seat_ids()
    held = showtime.held_seat_ids()
    dynamic = showtime.dynamic_pricing_info
    row_defs = []
    prices = []
    for cls in layout.get('classes', []):
        code = cls.get('code', 'STD')
        base_price = float(showtime.price_overrides.get(code, cls.get('price', 0)))
        price = round(base_price * dynamic['factor'], 2)
        prices.append(price)
        for row in cls.get('rows', []):
            start = int(row.get('start', 1))
            count = max(0, int(row.get('count', 0)))
            blocked = set(row.get('blocked') or [])
            seats = {}
            for number in range(start, start + count):
                seat_id = f"{row['label']}{number}"
                if seat_id in blocked:
                    continue
                seats[seat_id] = 'booked' if seat_id in booked else ('held' if seat_id in held else 'available')
            row_defs.append({
                'label': row['label'], 'start': start, 'count': count,
                'aislesAfter': [int(a) for a in row.get('aisles_after', [])],
                'blocked': list(blocked), 'offset': int(row.get('offset', 0)),
                'seatSpan': max(1, int(row.get('seat_span', 1))),
                'classCode': code, 'className': cls.get('name', 'Standard'),
                'price': price, 'seats': seats,
                'level_id': row.get('level_id'),
            })

    if not row_defs:
        abort(404)
    max_seat = max((row['start'] + row['count'] - 1 for row in row_defs), default=1)
    screen = layout.get('screen') or {}
    screen_type = (showtime.screen.screen_type or '').upper()
    fallback_aspect = 1.43 if 'IMAX' in screen_type else (2.2 if '70MM' in screen_type else 1.85)
    # Seed layouts contain seat-by-seat arrangements, but most do not include
    # surveyed auditorium dimensions. Keep supplied measurements and estimate
    # screen width proportionally when a layout has no measurement.
    widest_row_seats = max((row['count'] * row['seatSpan'] for row in row_defs), default=0)
    try:
        width = float(screen.get('width_m') or max(8.0, min(24.0, widest_row_seats * 0.62)))
    except (TypeError, ValueError):
        width = max(8.0, min(24.0, widest_row_seats * 0.62))
    try:
        aspect = float(screen.get('aspect_ratio') or fallback_aspect)
        if aspect <= 0:
            aspect = fallback_aspect
    except (TypeError, ValueError):
        aspect = fallback_aspect
    try:
        height = float(screen.get('height_m') or (width / aspect))
    except (TypeError, ValueError):
        height = width / aspect
    geometry = sl.auditorium_geometry(layout, row_defs, fallback_aspect)
    reference_profile = layout.get('reference_profile') or {}
    reference_status = reference_profile.get('reference_status', 'estimated_model')
    reference_status_label = {
        'verified_reference': 'screen-identified photo reference · currentness/permission review pending',
        'venue_reference': 'venue reference · screen match unverified',
        'estimated_model': 'estimated auditorium appearance',
    }.get(reference_status, 'administrator-defined appearance profile')
    surface = str(geometry.get('screen', {}).get('surface', '')).lower()
    screen_label = 'Flat LED screen' if surface == 'led' else ('Flat screen' if surface == 'flat' else 'Curved cinema screen')
    all_seat_ids = [seat_id for row in row_defs for seat_id in row['seats']]
    available_ids = [seat_id for row in row_defs for seat_id, state in row['seats'].items() if state == 'available']
    middle_row = row_defs[len(row_defs) // 2]
    middle_seat = middle_row['start'] + max(0, middle_row['count'] - 1) // 2
    preferred_id = f"{middle_row['label']}{middle_seat}"
    default_seat = preferred_id if preferred_id in available_ids else (available_ids[0] if available_ids else (all_seat_ids[0] if all_seat_ids else ''))

    preview = {
        'name': f'{showtime.theater} · {showtime.screen.name}',
        'movieTitle': showtime.movie.title,
        'sub': f'{showtime.screen.screen_type} · {len(row_defs)} rows · {sum(len(r["seats"]) for r in row_defs)} seats' + (' · dimensions estimated' if geometry.get('estimated') else ''),
        'rows': [row['label'] for row in row_defs], 'rowDefs': row_defs,
        'cols': max_seat, 'aislesAfter': [], 'vipRows': [], 'reclinerRows': [],
        'screenWidth': width, 'screenHeight': height,
        'geometry': geometry,
        # Only visual parameters and confidence are sent to customer pages.
        # Photo URLs remain in the administrator reference workflow and are
        # never requested by the ordinary preview renderer.
        'referenceProfile': {
            'architecture': reference_profile.get('architecture') or {},
            'confidence': reference_profile.get('confidence') or {},
        },
        'reference_status_label': reference_status_label,
        'screen_label': screen_label,
        'visual': layout.get('visual') or {
            'seat_color': '#51252d', 'wall_color': '#11151d',
            'trim_color': '#c9a84c', 'seat_style': 'standard',
            'verified_at_theater_level': False,
        },
        'rowSpacing': max(1.6, min(3.8, float(screen.get('row_spacing_m', 2.45)))),
        'screenCurve': max(0, min(0.6, float(screen.get('curve', 0.3)))),
        'stadiumSlope': max(0.25, min(1.2, float(screen.get('stadium_slope', 0.55)))),
        'prices': {'standard': min(prices or [0]), 'vip': max(prices or [0]), 'recliner': max(prices or [0])},
        'defaultSeat': default_seat,
    }
    trailer = showtime.movie.trailer
    optimized_url = (optimized_projection_url(trailer['url'])
                     if trailer and trailer['provider'] == 'cloudinary' else None)
    return render_template('booking/vr_seat_preview.html', showtime=showtime,
                           screen_type=showtime.screen.screen_type or 'Cinema screen',
                           movie=showtime.movie, preview=preview, trailer=trailer,
                           optimized_trailer_url=optimized_url,
                           embedded=request.args.get('embed') == '1')
