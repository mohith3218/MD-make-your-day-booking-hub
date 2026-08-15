"""
CineWave - Visakhapatnam (Vizag) theatre + screen seeding
=========================================================
Real Vizag cinemas with per-screen seating arrangements that mirror how the
actual audis are laid out - recliner rows up front at the multiplexes, classic
Balcony / First Class / Lower divisions at the single-screen halls, aisle
positions, staggered row widths, couple sofas.

Sources for theatre names, localities, screen counts and seat data:
  * Vizag cinema list with full addresses (INOX x4, Cinepolis, STBL x2, Mukta A2,
    Sarat, Sangam, Sree Kanya, Sree Rama, Mohini, Annapurna, Natraj, ...)
    https://in.bookmyshow.com/vizag-visakhapatnam/cinemas
  * AAA Cinemas, Inorbit Mall - 8 screens, ~1,556 seats, opened 9 Aug 2026
    https://www.m9.news/movienews/aaa-cinemas-vizag-allu-arjun-raaka-update/
  * AAA per-screen seat counts (491 LED, 58, 76, 130, 130, 436, 197, 34)
    https://www.gulte.com/shorts/424741/70x30-led-screen-biggest-in-aaa-vizag
  * AAA screen roles (1 VIP, 5 largest 57ft, 7 Qluxon LED, 8 Lounge) + tech
    https://www.ntvenglish.com/movie-news/allu-arjun-aaa-cinemas-visakhapatnam-barcosp4k-dolby-atmos-quluxon.html
  * AAA ticket prices - Platinum Rs 177, Recliner Rs 295
    https://www.yovizag.com/allu-arjun-inaugurates-aaa-cinemas-at-inorbit-mall-in-vizag/amp/
  * INOX Varun Beach - 6 screens, 1166 seats incl. 37 recliners
    https://businessofcinema.com/bollywood-news/inox-leisure-launches-multiplex-in-vizag/
  * Jagadamba 70MM 886 seats (Premium upper 274 + lower 276, Non-premium 336),
    Melody 774 seats, Cinepolis Madhurawada 4 screens, Mukta A2 3 screens
    https://vizagsmartcityin.blogspot.com/2026/06/best-movie-theatres-in-visakhapatnam.html
  * Kameswari & Kinnera, SVC Likitha, Miraj Bhupathi Surya Central
    https://ticketnew.com/movies/vizag/cinema-halls-and-movie-theatre

Seat counts for the multiplexes are matched to the published figures where they
exist; row-by-row detail is our best reconstruction. Everything is editable from
Admin > Theatres & Screens > Edit layout, so any audi can be tuned seat-for-seat.
"""


def rows(labels, count, aisles_after=None, blocked=None, seat_span=1, offset=0, start=1):
    """Build identical rows for a list of row labels."""
    return [{"label": lb, "count": count, "start": start,
             "aisles_after": aisles_after or [], "blocked": blocked or [],
             "seat_span": seat_span, "offset": offset}
            for lb in labels]


def varied(spec, aisles_after=None):
    """Build rows of differing widths: spec = [("A", 14), ("B", 16), ...]"""
    return [{"label": lb, "count": n, "start": 1,
             "aisles_after": aisles_after or [], "blocked": [],
             "seat_span": 1, "offset": 0}
            for lb, n in spec]


ROW_LABELS = [c for c in "ABCDEFGHJKLMNPQRSTUVWXYZ"]  # cinemas skip I and O


def fill_rows(total, width, first_label_index=0, aisles_after=None):
    """
    Lay `total` seats into rows of `width`, last row taking the remainder and
    centred with an offset - the way a real audi's front row is short.
    Returns (rows, next_label_index).
    """
    out, i, left = [], first_label_index, total
    while left > 0:
        n = min(width, left)
        label = ROW_LABELS[i % len(ROW_LABELS)] if i < len(ROW_LABELS) \
            else ROW_LABELS[i % len(ROW_LABELS)] * 2
        out.append({"label": label, "count": n, "start": 1,
                    "aisles_after": [a for a in (aisles_after or []) if a < n],
                    "blocked": [], "seat_span": 1,
                    "offset": (width - n) // 2 if n < width else 0})
        left -= n
        i += 1
    return out, i


def capacity_screen(label, total, split, width=18, aisles_after=(5, 13)):
    """
    Build a screen layout that adds up to exactly `total` seats.

    split = [(code, name, price, share), ...] - shares are relative weights,
    seats are handed out front-class first and the last class absorbs rounding.
    """
    weights = sum(s[3] for s in split)
    counts, used = [], 0
    for idx, (_c, _n, _p, share) in enumerate(split):
        n = total - used if idx == len(split) - 1 else int(round(total * share / weights))
        counts.append(n)
        used += n

    classes, label_i = [], 0
    for (code, name, price, _share), n in zip(split, counts):
        if n <= 0:
            continue
        rws, label_i = fill_rows(n, width, label_i, list(aisles_after))
        classes.append({"code": code, "name": name, "price": price, "rows": rws})
    return {"screen_label": label, "classes": classes}


# ---------------------------------------------------------------------------
# multiplex layouts
# ---------------------------------------------------------------------------

def inox_insignia():
    """Premium recliner-heavy audi. 37 recliners like the real Varun Beach one."""
    return {
        "screen_label": "INSIGNIA · Recliner Lounge",
        "classes": [
            {"code": "RECLINER", "name": "Recliner", "price": 350,
             "rows": varied([("A", 12), ("B", 12), ("C", 13)], aisles_after=[6])},
            {"code": "PRIME", "name": "Prime", "price": 220,
             "rows": rows(list("DEFG"), 16, aisles_after=[4, 12])},
            {"code": "CLASSIC", "name": "Classic", "price": 160,
             "rows": rows(list("HJK"), 18, aisles_after=[4, 14])},
        ],
    }


def inox_standard(screen_no, price_prime=210, price_classic=150):
    """Regular INOX audi: 2 prime blocks + classic, aisles down both sides."""
    return {
        "screen_label": f"Screen {screen_no} · Dolby Atmos",
        "classes": [
            {"code": "PRIME", "name": "Prime", "price": price_prime,
             "rows": varied([("A", 14), ("B", 16), ("C", 16), ("D", 18)],
                            aisles_after=[4, 12])},
            {"code": "CLASSIC", "name": "Classic", "price": price_classic,
             "rows": rows(list("EFGHJ"), 20, aisles_after=[4, 16])},
            {"code": "EXECUTIVE", "name": "Executive", "price": 180,
             "rows": rows(list("KL"), 18, aisles_after=[4, 14])},
        ],
    }


def cinepolis_screen(screen_no):
    return {
        "screen_label": f"Audi {screen_no} · 4K Laser",
        "classes": [
            {"code": "VIP", "name": "VIP Recliner", "price": 330,
             "rows": rows(list("AB"), 10, aisles_after=[5], seat_span=1)},
            {"code": "PLATINUM", "name": "Platinum", "price": 230,
             "rows": rows(list("CDE"), 16, aisles_after=[4, 12])},
            {"code": "GOLD", "name": "Gold", "price": 170,
             "rows": rows(list("FGHJ"), 18, aisles_after=[4, 14])},
        ],
    }


def mukta_recliner_screen(screen_no):
    """Mukta A2 Vizag is recliners + couple sofas only."""
    return {
        "screen_label": f"Screen {screen_no} · Recliners & Sofas",
        "classes": [
            {"code": "SOFA", "name": "Couple Sofa", "price": 640,
             "rows": [{"label": "A", "count": 6, "start": 1, "aisles_after": [3],
                       "blocked": [], "seat_span": 2, "offset": 0}]},
            {"code": "RECLINER", "name": "Recliner", "price": 340,
             "rows": rows(list("BCDE"), 12, aisles_after=[6])},
            {"code": "PREMIUM", "name": "Premium Recliner", "price": 300,
             "rows": rows(list("FG"), 12, aisles_after=[6])},
        ],
    }


def stbl_screen(screen_no):
    return {
        "screen_label": f"Screen {screen_no} · 4K Dolby Atmos",
        "classes": [
            {"code": "RECLINER", "name": "Recliner", "price": 250,
             "rows": rows(list("AB"), 10, aisles_after=[5])},
            {"code": "PLATINUM", "name": "Platinum", "price": 160,
             "rows": rows(list("CDEF"), 16, aisles_after=[4, 12])},
            {"code": "GOLD", "name": "Gold", "price": 120,
             "rows": rows(list("GHJK"), 18, aisles_after=[4, 14])},
        ],
    }


# ---------------------------------------------------------------------------
# AAA Cinemas - Inorbit Mall (opened Aug 2026)
# published seat counts: S1 58, S2 76, S3 130, S4 130, S5 436, S6 197,
# S7 (Qluxon LED) 491, S8 lounge 34  ->  ~1,556 total
# published prices: Platinum Rs 177, Recliner Rs 295
# ---------------------------------------------------------------------------

def aaa_vip_screen():
    """Screen 1 - VIP screen, 58 seats, 40 of them premium recliners."""
    return {
        "screen_label": "Screen 1 · VIP · Barco SP4K + Dolby Atmos",
        "classes": [
            {"code": "RECLINER", "name": "Premium Recliner", "price": 295,
             "rows": varied([("A", 8), ("B", 8), ("C", 8), ("D", 8), ("E", 8)],
                            aisles_after=[4])},
            {"code": "PLATINUM", "name": "Platinum", "price": 177,
             "rows": varied([("F", 9), ("G", 9)], aisles_after=[4])},
        ],
    }


def aaa_screen(screen_no, total, label_extra="", recliner_share=0.25):
    return capacity_screen(
        f"Screen {screen_no} · {label_extra}".strip(" ·"),
        total,
        [("RECLINER", "Recliner", 295, recliner_share),
         ("PLATINUM", "Platinum", 177, 1 - recliner_share)],
        width=18 if total > 150 else 12,
    )


def aaa_lounge_screen():
    """Screen 8 - lounge screen, 34 seats, all recliner-class."""
    return {
        "screen_label": "Screen 8 · Lounge · Dolby 7.1",
        "classes": [
            {"code": "SOFA", "name": "Lounge Sofa", "price": 450,
             "rows": [{"label": "A", "count": 4, "start": 1, "aisles_after": [2],
                       "blocked": [], "seat_span": 2, "offset": 0}]},
            {"code": "RECLINER", "name": "Lounge Recliner", "price": 295,
             "rows": varied([("B", 10), ("C", 10), ("D", 10)], aisles_after=[5])},
        ],
    }


def aaa_qluxon_screen():
    """Screen 7 - 70x30 ft Q-Luxon LED, 491 seats, biggest in the complex."""
    return capacity_screen(
        "Screen 7 · Q-LUXON LED 70x30 · Dolby Atmos", 491,
        [("RECLINER", "Recliner", 295, 0.12),
         ("PLATINUM", "Platinum", 177, 0.58),
         ("GOLD", "Gold", 150, 0.30)],
        width=26, aisles_after=(7, 19),
    )


# ---------------------------------------------------------------------------
# single screen halls
# ---------------------------------------------------------------------------

def jagadamba_70mm():
    """
    Jagadamba 70MM main screen, ~886 seats:
      Premium (Upper) 274 · Premium (Lower) 276 · Non-Premium 336
    """
    return {
        "screen_label": "Jagadamba 70MM Main Screen",
        "classes": [
            {"code": "PREM_UPPER", "name": "Premium (Upper Balcony)", "price": 190,
             "rows": rows(list("ABCDEFGHJKL"), 24, aisles_after=[8, 16])[:11] +
                     [{"label": "M", "count": 10, "start": 1, "aisles_after": [5],
                       "blocked": [], "seat_span": 1, "offset": 7}]},
            {"code": "PREM_LOWER", "name": "Premium (Lower Balcony)", "price": 160,
             "rows": rows(list("NPQRSTUVWXYZ"), 23, aisles_after=[7, 16])},
            {"code": "NONPREM", "name": "First Class (Non-Premium)", "price": 110,
             "rows": rows(["AA", "BB", "CC", "DD", "EE", "FF", "GG",
                           "HH", "JJ", "KK", "LL", "MM", "NN", "PP"], 24,
                          aisles_after=[8, 16])},
        ],
    }


def melody_hall():
    """Sri Melody, Suryabagh - 774 seats, HDR + Dolby Atmos 54-channel."""
    return capacity_screen(
        "Melody · Galalite Mirage 2.7 · Dolby Atmos", 774,
        [("BALCONY", "Balcony", 150, 0.34),
         ("FIRST", "First Class", 120, 0.38),
         ("LOWER", "Lower Class", 90, 0.28)],
        width=26, aisles_after=(8, 18),
    )


def classic_single_screen(name, balcony_price=140, first_price=110, lower_price=80,
                          total=None):
    """Sarat / Sangam / Sree Rama style hall: Balcony, First Class, Lower."""
    if total:
        return capacity_screen(
            f"{name} · Main Screen", total,
            [("BALCONY", "Balcony", balcony_price, 0.32),
             ("FIRST", "First Class", first_price, 0.38),
             ("LOWER", "Lower Class", lower_price, 0.30)],
            width=22, aisles_after=(7, 15),
        )
    return {
        "screen_label": f"{name} · Main Screen",
        "classes": [
            {"code": "BALCONY", "name": "Balcony", "price": balcony_price,
             "rows": rows(list("ABCDEF"), 20, aisles_after=[6, 14])},
            {"code": "FIRST", "name": "First Class", "price": first_price,
             "rows": rows(list("GHJKL"), 22, aisles_after=[7, 15])},
            {"code": "LOWER", "name": "Lower Class", "price": lower_price,
             "rows": rows(list("MNPQ"), 24, aisles_after=[8, 16])},
        ],
    }


def small_town_hall(name, total=420, recliner=False):
    """Suburban single screens - Annapurna, Natraj, Mohini, Aruna and friends."""
    split = [("RECLINER", "Recliner", 150, 0.18)] if recliner else []
    split += [("FIRST", "First Class", 110, 0.45 if recliner else 0.55),
              ("LOWER", "Lower Class", 80, 0.37 if recliner else 0.45)]
    return capacity_screen(f"{name} · Main Screen", total, split,
                           width=20, aisles_after=(6, 14))


# ---------------------------------------------------------------------------
# the seed table:  theatre -> screens
# ---------------------------------------------------------------------------

VIZAG_THEATERS = [
    {
        "name": "AAA Cinemas",
        "location": "Inorbit Mall, Madhurawada",
        "address": "Inorbit Mall, NH-16, Madhurawada, Visakhapatnam 530048",
        "screens": [
            ("Screen 1", "VIP", aaa_vip_screen()),
            ("Screen 2", "Dolby 7.1", aaa_screen(2, 76, "Barco SP4K")),
            ("Screen 3", "Dolby Atmos", aaa_screen(3, 130, "Barco SP4K")),
            ("Screen 4", "Dolby 7.1", aaa_screen(4, 130, "Barco SP4K")),
            ("Screen 5", "Dolby Atmos", aaa_screen(5, 436, "57ft · Barco SP4K-55B", 0.15)),
            ("Screen 6", "Dolby Atmos", aaa_screen(6, 197, "Barco SP4K", 0.2)),
            ("Screen 7", "Q-Luxon LED", aaa_qluxon_screen()),
            ("Screen 8", "Lounge", aaa_lounge_screen()),
        ],
    },
    {
        "name": "INOX Varun Beach",
        "location": "Beach Road, Maharani Peta",
        "address": "3rd Floor, Varun Beach, Survey No. 120 & 121, R K Beach Road, Vizag 530003",
        "screens": [
            ("Screen 1", "INSIGNIA", inox_insignia()),
            ("Screen 2", "2D", inox_standard(2)),
            ("Screen 3", "3D", inox_standard(3, 230, 160)),
            ("Screen 4", "2D", inox_standard(4)),
            ("Screen 5", "2D", inox_standard(5)),
            ("Screen 6", "3D", inox_standard(6, 230, 160)),
        ],
    },
    {
        "name": "INOX CMR Central, Maddilapalem",
        "location": "Maddilapalem, Dwaraka Nagar",
        "address": "3rd Floor, CMR Central Mall, Survey No. 67, Maddilapalem, Vizag 530013",
        "screens": [
            ("Screen 1", "2D", inox_standard(1)),
            ("Screen 2", "2D", inox_standard(2)),
            ("Screen 3", "3D", inox_standard(3, 240, 170)),
            ("Screen 4", "2D", inox_standard(4)),
        ],
    },
    {
        "name": "INOX CMR Central, Gajuwaka",
        "location": "Chaitanya Nagar, Gajuwaka",
        "address": "3rd Floor, CMR Central, Chaitanya Nagar, NH-5, Gajuwaka, Vizag 530026",
        "screens": [
            ("Screen 1", "2D", inox_standard(1, 190, 140)),
            ("Screen 2", "2D", inox_standard(2, 190, 140)),
            ("Screen 3", "3D", inox_standard(3, 210, 150)),
        ],
    },
    {
        "name": "INOX Vizag Chitralaya Mall",
        "location": "Chitralaya Road, Suryabagh",
        "address": "4th Floor, Chitralayaa Mall, Chitralaya Road, Suryabagh, Vizag 530020",
        "screens": [
            ("Screen 1", "2D", inox_standard(1, 190, 140)),
            ("Screen 2", "2D", inox_standard(2, 190, 140)),
            ("Screen 3", "2D", inox_standard(3, 190, 140)),
        ],
    },
    {
        "name": "Cinepolis Sreekanya Cineglitz",
        "location": "Madhurawada",
        "address": "100 Feet Road, Madhurawada, Vizag 530048",
        "screens": [
            ("Audi 1", "4K Laser", cinepolis_screen(1)),
            ("Audi 2", "4K Laser", cinepolis_screen(2)),
            ("Audi 3", "3D", cinepolis_screen(3)),
            ("Audi 4", "4K Laser", cinepolis_screen(4)),
        ],
    },
    {
        "name": "Mukta A2 Cinemas",
        "location": "Town Main Road, Poorna Market",
        "address": "4th Floor, Town Main Road, Next to Super Bazaar, Vizag 530002",
        "screens": [
            ("Screen 1", "Recliner", mukta_recliner_screen(1)),
            ("Screen 2", "Recliner", mukta_recliner_screen(2)),
            ("Screen 3", "Recliner", mukta_recliner_screen(3)),
        ],
    },
    {
        "name": "STBL Cine World, Madhurawada",
        "location": "Srinivasa Nagar, Madhurawada",
        "address": "2, 9-25/2, NH-16, Srinivasa Nagar, Madhurawada, Vizag 530048",
        "screens": [
            ("Screen 1", "4K Atmos", stbl_screen(1)),
            ("Screen 2", "4K Atmos", stbl_screen(2)),
            ("Screen 3", "2D", stbl_screen(3)),
        ],
    },
    {
        "name": "STBL Cinemas Multiplex, Sheela Nagar",
        "location": "Sheela Nagar",
        "address": "6-175/20, Sheela Nagar, Beside Ayyappa Swamy Temple, Vizag 530012",
        "screens": [
            ("Screen 1", "4K Atmos", stbl_screen(1)),
            ("Screen 2", "2D", stbl_screen(2)),
        ],
    },
    {
        "name": "Miraj Cinemas, Bhupathi Surya Central",
        "location": "Dwaraka Nagar",
        "address": "Bhupathi Surya Central Mall, Dwaraka Nagar, Vizag 530016",
        "screens": [
            ("Screen 1", "4K Atmos", stbl_screen(1)),
            ("Screen 2", "2D", stbl_screen(2)),
            ("Screen 3", "2D", stbl_screen(3)),
        ],
    },
    {
        "name": "Jagadamba Theatre",
        "location": "Jagadamba Junction",
        "address": "Chitralaya Road, Jagadamba Junction, Vizag 530020",
        "screens": [
            ("70MM Main", "70MM 4K Atmos", jagadamba_70mm()),
        ],
    },
    {
        "name": "Sri Melody",
        "location": "Suryabagh, Jagadamba Junction",
        "address": "V Max Theatre, Suryabagh, Jagadamba Junction, Vizag 530020",
        "screens": [
            ("Main Screen", "HDR Dolby Atmos", melody_hall()),
        ],
    },
    {
        "name": "Sarat Theatre",
        "location": "Dondaparthy, Dwaraka Nagar",
        "address": "Railway Station Road, Near RTC Complex, Dondaparthy, Vizag 530016",
        "screens": [
            ("Main Screen", "4K Dolby Atmos", classic_single_screen("Sarat", 150, 120, 90, total=720)),
        ],
    },
    {
        "name": "Sangam Theatre",
        "location": "Dondaparthy, Dwaraka Nagar",
        "address": "Station Road, Dondaparthy, Dwaraka Nagar, Vizag 530016",
        "screens": [
            ("Main Screen", "4K Dolby Atmos", classic_single_screen("Sangam", 150, 120, 90, total=680)),
        ],
    },
    {
        "name": "Sree Kanya Cinemas",
        "location": "Old Gajuwaka",
        "address": "Main Road, Old Gajuwaka, Near Mamata Hospital, Vizag 530026",
        "screens": [
            ("Main Screen", "2D", classic_single_screen("Sree Kanya", 130, 100, 80, total=640)),
        ],
    },
    {
        "name": "Sree Rama Theatre",
        "location": "Ram Nagar",
        "address": "Rama Talkies Road, RTC Complex, Ram Nagar, Vizag 530002",
        "screens": [
            ("Main Screen", "4K Dolby Atmos", classic_single_screen("Sree Rama", 140, 110, 85, total=700)),
        ],
    },
    {
        "name": "Leelamahal Theatre",
        "location": "Leelamahal Junction, Seethammadhara",
        "address": "Leelamahal Junction, Seethammadhara, Vizag 530013",
        "screens": [
            ("Main Screen", "2D", classic_single_screen("Leelamahal", 130, 100, 80, total=620)),
        ],
    },
    {
        "name": "Kameswari & Kinnera",
        "location": "Maddilapalem",
        "address": "Maddilapalem Junction, Vizag 530013",
        "screens": [
            ("Kameswari", "4K Laser Atmos", small_town_hall("Kameswari", 520, recliner=True)),
            ("Kinnera", "4K Laser 7.1", small_town_hall("Kinnera", 480, recliner=True)),
        ],
    },
    {
        "name": "Mohini Cinemas",
        "location": "Indira Colony, Gajuwaka",
        "address": "Indira Colony, Gajuwaka, Near Alif Family Restaurant, Vizag 530026",
        "screens": [
            ("Main Screen", "Dolby Atmos", small_town_hall("Mohini", 560)),
        ],
    },
    {
        "name": "Annapurna Theatre",
        "location": "Kurmannapalem",
        "address": "Askapalli - Aganampudi Road, Kurmannapalem, Vizag 530046",
        "screens": [
            ("Main Screen", "2K Dolby Digital", small_town_hall("Annapurna", 460, recliner=True)),
        ],
    },
    {
        "name": "Natraj Theatre",
        "location": "Aditya Nagar, Pendurthi",
        "address": "Aditya Nagar, Pendurthi, Near Tirumala Hospital, Vizag 531173",
        "screens": [
            ("Main Screen", "A/C DTS", small_town_hall("Natraj", 440)),
        ],
    },
    {
        "name": "Sri Lakshmi Narasimha Picture Palace",
        "location": "Kancharapalem, 104 Area",
        "address": "104 Area, Kancharapalem, Vizag 530002",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Lakshmi Narasimha", 500)),
        ],
    },
    {
        "name": "SVC Likitha",
        "location": "Sriharipuram, Malkapuram",
        "address": "Sriharipuram, Malkapuram, Vizag 530011",
        "screens": [
            ("Main Screen", "A/C DTS", small_town_hall("SVC Likitha", 420, recliner=True)),
        ],
    },
]


# theatres seeded under an older name -> current name, so an existing database
# gets renamed instead of ending up with two copies of the same cinema
RENAMES = {
    "INOX CMR Central": "INOX CMR Central, Maddilapalem",
    "INOX Chitralaya": "INOX Vizag Chitralaya Mall",
    "Melody Cinema Hall": "Sri Melody",
    "Sangam Sarat Theatre": "Sangam Theatre",
}


def seed_vizag_theaters(db, Theater, Screen, verbose=True):
    """Idempotent: adds any missing Vizag theatre / screen, never duplicates."""
    created_t = created_s = 0

    for old, new in RENAMES.items():
        legacy = Theater.query.filter_by(name=old).first()
        if legacy and not Theater.query.filter_by(name=new).first():
            legacy.name = new
    db.session.commit()

    for data in VIZAG_THEATERS:
        theater = Theater.query.filter_by(name=data["name"]).first()
        if not theater:
            theater = Theater(name=data["name"], location=data["location"],
                              city="Visakhapatnam", address=data["address"])
            db.session.add(theater)
            db.session.flush()
            created_t += 1

        for screen_name, screen_type, layout in data["screens"]:
            existing = Screen.query.filter_by(theater_id=theater.id,
                                              name=screen_name).first()
            if existing:
                continue
            screen = Screen(theater_id=theater.id, name=screen_name,
                            screen_type=screen_type)
            screen.layout = layout
            db.session.add(screen)
            created_s += 1

    db.session.commit()
    if verbose:
        print(f"Vizag seed: +{created_t} theatres, +{created_s} screens")
    return created_t, created_s
