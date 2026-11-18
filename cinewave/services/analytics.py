from datetime import date, datetime, timedelta
from sqlalchemy import func as sa_func
import seat_layout as sl
from ..models import BookedSeat, Booking, Movie, Payment, Screen, Showtime, Theater



def _analytics_window(days):
    """(start_of_window, end) datetimes for a `days` lookback; None start = all time."""
    end = datetime.utcnow()
    start = (end - timedelta(days=days)).replace(hour=0, minute=0, second=0,
                                                 microsecond=0) if days else None
    return start, end


def _analytics_bookings(days):
    """All bookings in the window as plain Booking objects, freshest first."""
    q = (Booking.query.join(Showtime, Booking.showtime_id == Showtime.id)
         .join(Movie, Showtime.movie_id == Movie.id))
    start, _ = _analytics_window(days)
    if start:
        q = q.filter(Booking.booked_at >= start)
    return q.order_by(Booking.booked_at.desc()).all()


def _collect_analytics(days):
    """
    All aggregates for the analytics dashboard, in one pass over the window's
    bookings plus grouped queries. Kept independent of templates so tests can
    assert on the numbers directly.
    """
    start, end = _analytics_window(days)

    def in_window(q):
        return q.filter(Booking.booked_at >= start) if start else q

    # ---- headline KPIs -----------------------------------------------------
    rows = (in_window(Booking.query)
            .with_entities(Booking.status,
                           sa_func.count(Booking.id),
                           sa_func.coalesce(sa_func.sum(Booking.total_amount), 0.0))
            .group_by(Booking.status).all())
    status_counts = {status: {'count': cnt, 'amount': float(amount or 0.0)}
                     for status, cnt, amount in rows}
    paid = status_counts.get('PAID', {'count': 0, 'amount': 0.0})
    lost = (status_counts.get('CANCELLED', {'count': 0, 'amount': 0})['count']
            + status_counts.get('FAILED', {'count': 0, 'amount': 0})['count']
            + status_counts.get('EXPIRED', {'count': 0, 'amount': 0})['count'])
    all_count = sum(v['count'] for v in status_counts.values())

    active_buyers = in_window(Booking.query.filter(Booking.status == 'PAID')) \
        .with_entities(sa_func.count(sa_func.distinct(Booking.user_id))).scalar() or 0

    # ---- daily revenue trend (last `days` days, zero-filled) ---------------
    trend = []
    if days:
        daily = (in_window(Booking.query.filter(Booking.status == 'PAID'))
                 .with_entities(sa_func.date(Booking.paid_at).label('d'),
                                sa_func.coalesce(sa_func.sum(Booking.total_amount), 0.0),
                                sa_func.count(Booking.id))
                 .group_by('d').all())
        by_day = {str(d): {'amount': float(a or 0.0), 'tickets': int(n)} for d, a, n in daily}
        today = date.today()
        for i in range(days - 1, -1, -1):
            day = today - timedelta(days=i)
            info = by_day.get(day.isoformat(), {'amount': 0.0, 'tickets': 0})
            trend.append({'date': day, 'label': day.strftime('%d %b'),
                          'amount': info['amount'], 'tickets': info['tickets']})

    # ---- top movies / theatres (PAID only) ---------------------------------
    movie_stats = (in_window(Booking.query.filter(Booking.status == 'PAID'))
                   .join(Showtime, Booking.showtime_id == Showtime.id)
                   .with_entities(Showtime.movie_id,
                                  sa_func.count(Booking.id),
                                  sa_func.coalesce(sa_func.sum(Booking.total_amount), 0.0))
                   .group_by(Showtime.movie_id).all())
    movie_stats = {mid: {'count': int(cnt), 'revenue': float(rev or 0.0)}
                   for mid, cnt, rev in movie_stats}

    theatre_stats = (in_window(Booking.query.filter(Booking.status == 'PAID'))
                     .join(Showtime, Booking.showtime_id == Showtime.id)
                     .join(Screen, Showtime.screen_id == Screen.id)
                     .join(Theater, Screen.theater_id == Theater.id)
                     .with_entities(Theater.id,
                                    sa_func.count(Booking.id),
                                    sa_func.coalesce(sa_func.sum(Booking.total_amount), 0.0))
                     .group_by(Theater.id).all())
    theatre_stats = {tid: {'count': int(cnt), 'revenue': float(rev or 0.0)}
                     for tid, cnt, rev in theatre_stats}

    # ---- occupancy: booked seats per showtime ------------------------------
    q = (Booking.query.filter(Booking.status == 'PAID')
         .join(Showtime, Booking.showtime_id == Showtime.id)
         .with_entities(Showtime.id,
                        sa_func.sum(Booking.total_amount),
                        sa_func.count(Booking.id)))
    if start:
        q = q.filter(Booking.booked_at >= start)
    per_show_paid = {sid: {'revenue': float(rev or 0.0), 'bookings': int(n)}
                     for sid, rev, n in q.group_by(Showtime.id).all()}
    seats_paid_rows = (in_window(Booking.query.filter(Booking.status == 'PAID'))
                       .join(BookedSeat, BookedSeat.booking_id == Booking.id)
                       .with_entities(BookedSeat.showtime_id, sa_func.count(BookedSeat.id))
                       .group_by(BookedSeat.showtime_id).all())
    seats_paid = {sid: int(n) for sid, n in seats_paid_rows}

    # ---- payment method split (PAID) ---------------------------------------
    method_rows = (in_window(Payment.query.filter(Payment.status == 'CAPTURED'))
                   .join(Booking, Payment.booking_id == Booking.id)
                   .with_entities(Payment.method,
                                  sa_func.count(Payment.id),
                                  sa_func.coalesce(sa_func.sum(Payment.amount), 0.0))
                   .group_by(Payment.method).all())
    pay_split = [{'method': (m or 'unknown'), 'count': int(n), 'amount': float(a or 0.0)}
                 for m, n, a in method_rows]
    pay_split.sort(key=lambda x: x['amount'], reverse=True)
    pay_total = sum(m['amount'] for m in pay_split)

    # ---- top movies & theatres joined with names + occupancy ---------------
    movies = Movie.query.all()
    movie_names = {m.id: m.title for m in movies}
    top_movies = sorted(
        ({'id': mid, 'title': movie_names.get(mid, f'Movie #{mid}'), **st}
         for mid, st in movie_stats.items()),
        key=lambda x: x['revenue'], reverse=True)

    theatres = Theater.query.all()
    theatre_names = {t.id: t for t in theatres}
    showtimes = Showtime.query.all()
    layout_cache = {}
    for s in showtimes:
        layout_cache[s.id] = s.layout

    top_theatres = []
    for tid, st in sorted(theatre_stats.items(), key=lambda kv: kv[1]['revenue'], reverse=True):
        th = theatre_names.get(tid)
        if not th:
            continue
        top_theatres.append({'id': tid, 'name': th.name, 'location': th.location or '', **st})

    # ---- upcoming showtimes heat strip (today + next 7 days) ---------------
    upcoming = [s for s in showtimes
                if s.show_date >= date.today() and s.show_date <= date.today() + timedelta(days=7)
                and s.layout]
    upcoming.sort(key=lambda s: (s.show_date, s.show_time))
    heat = []
    for s in upcoming[:24]:
        total = sl.count_seats(layout_cache[s.id]) or 1
        sold = seats_paid.get(s.id, 0)
        pct = min(100, round(100.0 * sold / total))
        heat.append({'showtime': s, 'sold': sold, 'total': total, 'pct': pct,
                     'revenue': per_show_paid.get(s.id, {}).get('revenue', 0.0)})

    overall_total_seats = sum(sl.count_seats(layout_cache[s.id]) or 0
                              for s in showtimes if s.show_date >= date.today())
    overall_sold = sum(seats_paid.values())
    occupancy_overall = round(100.0 * overall_sold / overall_total_seats, 1) \
        if overall_total_seats else 0.0

    return {
        'days': days,
        'paid': paid,
        'all_count': all_count,
        'lost_count': lost,
        'cancel_rate': round(100.0 * lost / all_count, 1) if all_count else 0.0,
        'avg_ticket': round(paid['amount'] / paid['count'], 0) if paid['count'] else 0,
        'active_buyers': active_buyers,
        'trend': trend,
        'trend_max': max((t['amount'] for t in trend), default=0.0),
        'trend_total': round(sum(t['amount'] for t in trend), 2),
        'top_movies': top_movies[:8],
        'top_theatres': top_theatres[:8],
        'pay_split': pay_split,
        'pay_total': pay_total,
        'heat': heat,
        'occupancy_overall': occupancy_overall,
    }
