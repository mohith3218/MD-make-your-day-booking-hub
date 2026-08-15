"""
CineWave - Visakhapatnam (Vizag) theatre + screen seeding
=========================================================
Real Vizag theatres with per-screen seating arrangements that mirror how the
actual audis are laid out (recliner rows up front at INOX/Mukta, classic
Balcony / First Class / Lower divisions at the single-screen halls like
Jagadamba and Melody, aisle positions, staggered row widths).

Sources used for theatre names, screen counts and seat classes:
  * INOX Varun Beach, Beach Road - 6 screens, 1166 seats incl. 37 recliners
    https://businessofcinema.com/bollywood-news/inox-leisure-launches-multiplex-in-vizag/
  * INOX Vizag cinema list (Varun Beach, CMR Central, Chitralaya)
    https://in.bookmyshow.com/vizag/cinemas
  * Cinepolis Sreekanya Cineglitz, Madhurawada / Mukta A2 (recliners & sofas only)
    https://in.bookmyshow.com/vizag/cinemas
  * Jagadamba 70MM capacity split (Premium upper 274 + lower 276, Non-premium 336)
    https://vizagsmartcityin.blogspot.com/

Seat counts are close to the real halls but the point of the layout JSON is that
you (or an admin) can tune any row from the Edit Layout screen until it matches
the audi seat-for-seat.
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


def classic_single_screen(name, balcony_price=140, first_price=110, lower_price=80):
    """Melody / Sangam / Kameswari style hall: Balcony, First Class, Lower."""
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


# ---------------------------------------------------------------------------
# the seed table:  theatre -> screens
# ---------------------------------------------------------------------------

VIZAG_THEATERS = [
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
        "name": "INOX CMR Central",
        "location": "Maddilapalem",
        "address": "3rd Floor, CMR Central Mall, Survey No. 67, Maddilapalem, Vizag 530013",
        "screens": [
            ("Screen 1", "2D", inox_standard(1)),
            ("Screen 2", "2D", inox_standard(2)),
            ("Screen 3", "3D", inox_standard(3, 240, 170)),
            ("Screen 4", "2D", inox_standard(4)),
        ],
    },
    {
        "name": "INOX Chitralaya",
        "location": "Jagadamba Centre",
        "address": "Chitralaya Road, Jagadamba Centre, Vizag 530020",
        "screens": [
            ("Screen 1", "2D", inox_standard(1, 190, 140)),
            ("Screen 2", "2D", inox_standard(2, 190, 140)),
            ("Screen 3", "2D", inox_standard(3, 190, 140)),
        ],
    },
    {
        "name": "Cinepolis Sreekanya Cineglitz",
        "location": "Madhurawada",
        "address": "Sreekanya Cineglitz, NH-16, Madhurawada, Vizag 530048",
        "screens": [
            ("Audi 1", "4K Laser", cinepolis_screen(1)),
            ("Audi 2", "4K Laser", cinepolis_screen(2)),
            ("Audi 3", "3D", cinepolis_screen(3)),
        ],
    },
    {
        "name": "Mukta A2 Cinemas",
        "location": "Town Main Road, Poorna Market",
        "address": "4th Floor, Town Main Road, Next to Super Bazaar, Vizag 530002",
        "screens": [
            ("Screen 1", "Recliner", mukta_recliner_screen(1)),
            ("Screen 2", "Recliner", mukta_recliner_screen(2)),
        ],
    },
    {
        "name": "Jagadamba Theatre",
        "location": "Jagadamba Centre",
        "address": "Jagadamba Junction, Vizag 530020",
        "screens": [
            ("70MM Main", "70MM", jagadamba_70mm()),
        ],
    },
    {
        "name": "Melody Cinema Hall",
        "location": "Dwaraka Nagar",
        "address": "Dwaraka Nagar Main Road, Vizag 530016",
        "screens": [
            ("Main Screen", "2D", classic_single_screen("Melody")),
        ],
    },
    {
        "name": "Sangam Sarat Theatre",
        "location": "Dondaparthy",
        "address": "Sangam Complex, Dondaparthy, Vizag 530016",
        "screens": [
            ("Sarat", "2D", classic_single_screen("Sarat", 150, 120, 90)),
            ("Sangam", "2D", classic_single_screen("Sangam", 150, 120, 90)),
        ],
    },
]


def seed_vizag_theaters(db, Theater, Screen, verbose=True):
    """Idempotent: adds any missing Vizag theatre / screen, never duplicates."""
    created_t = created_s = 0
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
