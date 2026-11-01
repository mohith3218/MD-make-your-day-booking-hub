"""
CineWave - Visakhapatnam (Vizag) Comprehensive Theatre + Screen Seeding
======================================================================
Real Vizag cinemas with per-screen seating arrangements that mirror how the
actual audis are laid out - recliner rows up front at the multiplexes, classic
Balcony / First Class / Lower divisions at the single-screen halls, aisle
positions, staggered row widths, couple sofas, Dolby Atmos & 4K laser auditoriums.

Covers 85+ Theatres across all 7 regions of Visakhapatnam Metropolitan & District:
  1. City Core (Jagadamba, Daba Gardens, RTC Complex, Dwaraka Nagar & Beach Road)
  2. North Vizag & Coastal Suburbs (Maddilapalem, MVP, Madhurawada, Bheemili & Tagarapuvalasa)
  3. Central-West & Suburbs (Kancharapalem, 104 Area, NAD, Gopalapatnam, Simhachalam & Pendurthi)
  4. South Industrial Corridor (Gajuwaka, Malkapuram, Sriharipuram & Kurmannapalem)
  5. Anakapalle & Kasimkota Region
  6. Chodavaram & K.Kotapadu Belt
  7. Narsipatnam, Yelamanchili & Outer Hubs
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
    split = [(code, name, price, share), ...]
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
# Multiplex & Specialty Layout Builders
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


def aaa_vip_screen():
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
    return capacity_screen(
        "Screen 7 · Q-LUXON LED 70x30 · Dolby Atmos", 491,
        [("RECLINER", "Recliner", 295, 0.12),
         ("PLATINUM", "Platinum", 177, 0.58),
         ("GOLD", "Gold", 150, 0.30)],
        width=26, aisles_after=(7, 19),
    )


def jagadamba_70mm():
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
    return capacity_screen(
        "Melody · Galalite Mirage 2.7 · Dolby Atmos", 774,
        [("BALCONY", "Balcony", 150, 0.34),
         ("FIRST", "First Class", 120, 0.38),
         ("LOWER", "Lower Class", 90, 0.28)],
        width=26, aisles_after=(8, 18),
    )


def classic_single_screen(name, balcony_price=140, first_price=110, lower_price=80, total=None):
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


def small_town_hall(name, total=420, recliner=False, rec_price=160, first_price=110, lower_price=80):
    split = [("RECLINER", "Recliner", rec_price, 0.18)] if recliner else []
    split += [("FIRST", "First Class", first_price, 0.45 if recliner else 0.55),
              ("LOWER", "Lower Class", lower_price, 0.37 if recliner else 0.45)]
    return capacity_screen(f"{name} · Main Screen", total, split,
                           width=20, aisles_after=(6, 14))


def multiplex_generic(screen_name, screen_label_extra="4K Laser", total=220, rec_p=260, prime_p=180, classic_p=130):
    return capacity_screen(
        f"{screen_name} · {screen_label_extra}", total,
        [("RECLINER", "Recliner", rec_p, 0.15),
         ("PRIME", "Prime", prime_p, 0.50),
         ("CLASSIC", "Classic", classic_p, 0.35)],
        width=18, aisles_after=(5, 13),
    )


# ---------------------------------------------------------------------------
# Comprehensive Seed Table: 85+ Theatres across Visakhapatnam Region
# ---------------------------------------------------------------------------

VIZAG_THEATERS = [
    # =======================================================================
    # REGION 1: CITY CORE (Jagadamba, Daba Gardens, RTC Complex, Beach Road)
    # =======================================================================
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
        "name": "V-Max Multiplex",
        "location": "Jagadamba Junction",
        "address": "Jagadamba Commercial Complex, Jagadamba Junction, Vizag 530020",
        "screens": [
            ("Screen 1", "Dolby Atmos", multiplex_generic("Screen 1", "4K Atmos", 280, 220, 160, 110)),
            ("Screen 2", "4K Laser", multiplex_generic("Screen 2", "Dolby 7.1", 240, 200, 150, 100)),
        ],
    },
    {
        "name": "Sharada Theatre",
        "location": "Jagadamba Junction",
        "address": "Opposite Jagadamba Theatre, Jagadamba Junction, Vizag 530020",
        "screens": [
            ("Main Screen", "2K Dolby Atmos", classic_single_screen("Sharada", 150, 110, 80, total=520)),
        ],
    },
    {
        "name": "Sri Melody",
        "location": "Suryabagh, Jagadamba Junction",
        "address": "V Max Theatre Road, Suryabagh, Jagadamba Junction, Vizag 530020",
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
        "name": "Sree Rama Theatre",
        "location": "Ram Nagar",
        "address": "Rama Talkies Road, RTC Complex, Ram Nagar, Vizag 530002",
        "screens": [
            ("Main Screen", "4K Dolby Atmos", classic_single_screen("Sree Rama", 140, 110, 85, total=700)),
        ],
    },
    {
        "name": "Leelamahal Theatre",
        "location": "Leelamahal Junction, Daba Gardens",
        "address": "Leelamahal Junction, Daba Gardens, Vizag 530020",
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
        "name": "Sri Venkateswara Theatre, Daba Gardens",
        "location": "Daba Gardens",
        "address": "Main Road, Daba Gardens, Vizag 530020",
        "screens": [
            ("Main Screen", "2K Dolby", classic_single_screen("Venkateswara", 140, 110, 80, total=560)),
        ],
    },
    {
        "name": "SVC Gokul 2K",
        "location": "Allipuram, Jagadamba",
        "address": "Main Road, Allipuram, Near Railway Station, Vizag 530004",
        "screens": [
            ("Main Screen", "2K Dolby Atmos", small_town_hall("SVC Gokul", 480, recliner=True, rec_price=160)),
        ],
    },
    {
        "name": "Jyothi Theatre",
        "location": "Jagadamba Centre",
        "address": "Jagadamba Centre, Vizag 530020",
        "screens": [
            ("Main Screen", "2D DTS", classic_single_screen("Jyothi", 130, 100, 75, total=510)),
        ],
    },
    {
        "name": "Alankar Theatre",
        "location": "Gandhi Nagar, Poorna Market",
        "address": "Gandhi Nagar, Main Road, Poorna Market, Vizag 530002",
        "screens": [
            ("Main Screen", "A/C DTS", classic_single_screen("Alankar", 120, 90, 70, total=450)),
        ],
    },
    {
        "name": "Poorna Theatre",
        "location": "Poorna Market",
        "address": "Poorna Market Main Road, Visakhapatnam 530001",
        "screens": [
            ("Main Screen", "2D", classic_single_screen("Poorna", 120, 90, 70, total=460)),
        ],
    },
    {
        "name": "Crown Talkies",
        "location": "Town Area",
        "address": "Town Kotha Road, Old Post Office, Vizag 530001",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Crown Talkies", 380)),
        ],
    },
    {
        "name": "Prabhat Cinema",
        "location": "Jagadamba Junction",
        "address": "Chitralaya Road, Jagadamba Junction, Vizag 530020",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Prabhat", 400)),
        ],
    },

    # =======================================================================
    # REGION 2: NORTH VIZAG & COASTAL (Maddilapalem, Madhurawada, Bheemili)
    # =======================================================================
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
        "name": "STBL Cine Pride",
        "location": "Madhurawada",
        "address": "Near IT SEZ, Madhurawada, Visakhapatnam 530048",
        "screens": [
            ("Screen 1", "4K Atmos", multiplex_generic("Screen 1", "4K Atmos", 210, 240, 160, 110)),
            ("Screen 2", "Dolby 7.1", multiplex_generic("Screen 2", "Dolby 7.1", 190, 220, 150, 100)),
        ],
    },
    {
        "name": "Sri Ramulamma 4K Dolby Atmos",
        "location": "Tagarapuvalasa",
        "address": "NH-16, Near RTC Bus Stand, Tagarapuvalasa, Vizag 531162",
        "screens": [
            ("Main Screen", "4K Dolby Atmos", small_town_hall("Sri Ramulamma", 580, recliner=True, rec_price=170)),
        ],
    },
    {
        "name": "AVR Saptagiri Theatre",
        "location": "Tagarapuvalasa",
        "address": "Chittivalasa Road, Tagarapuvalasa, Vizag 531162",
        "screens": [
            ("Main Screen", "Dolby Digital", small_town_hall("AVR Saptagiri", 460)),
        ],
    },
    {
        "name": "Srinivasa Complex",
        "location": "Tagarapuvalasa",
        "address": "Main Road, Tagarapuvalasa, Vizag 531162",
        "screens": [
            ("Screen 1", "2D DTS", small_town_hall("Srinivasa", 420)),
        ],
    },
    {
        "name": "LSK Movie Theatre",
        "location": "Bheemunipatnam (Bheemili)",
        "address": "Beach Road, Bheemunipatnam, Vizag 531163",
        "screens": [
            ("Main Screen", "4K Dolby", small_town_hall("LSK Theatre", 450, recliner=True)),
        ],
    },
    {
        "name": "Ganesh Cinema Hall",
        "location": "Bheemili",
        "address": "Main Bazaar, Bheemunipatnam, Vizag 531163",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Ganesh Cinema", 360)),
        ],
    },
    {
        "name": "Thatha Theatre",
        "location": "Bheemunipatnam",
        "address": "Dutch Cemetery Road, Bheemili, Vizag 531163",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Thatha Theatre", 380)),
        ],
    },
    {
        "name": "Sri Jaya Theatre",
        "location": "Kothavalasa",
        "address": "Railway Station Road, Kothavalasa, Vizag Outer 535183",
        "screens": [
            ("Main Screen", "AC DTS", small_town_hall("Sri Jaya", 480, recliner=True)),
        ],
    },
    {
        "name": "Padmasri Theatre",
        "location": "Kothavalasa",
        "address": "Main Road, Kothavalasa 535183",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Padmasri", 410)),
        ],
    },

    # =======================================================================
    # REGION 3: CENTRAL-WEST (Kancharapalem, NAD, Gopalapatnam, Pendurthi)
    # =======================================================================
    {
        "name": "Urvasi Laser 15K AC Dolby",
        "location": "Kancharapalem, Bowdra Ring Road",
        "address": "Bowdra Ring Road, Kancharapalem, Vizag 530008",
        "screens": [
            ("Main Screen", "15K Laser Dolby", capacity_screen(
                "Urvasi Laser · Dolby Atmos", 620,
                [("RECLINER", "Recliner", 220, 0.15),
                 ("PREMIUM", "Premium Balcony", 160, 0.45),
                 ("FIRST", "First Class", 110, 0.40)],
                width=24, aisles_after=(7, 17)
            )),
        ],
    },
    {
        "name": "Sri Lakshmi Narasimha Picture Palace",
        "location": "Kancharapalem, 104 Area",
        "address": "104 Area, Kancharapalem, Vizag 530002",
        "screens": [
            ("Main Screen", "2D DTS", small_town_hall("Lakshmi Narasimha", 500)),
        ],
    },
    {
        "name": "Mourya 4K Dolby",
        "location": "Gopalapatnam",
        "address": "Near Railway Station, Gopalapatnam, Vizag 530027",
        "screens": [
            ("Main Screen", "4K Dolby Atmos", small_town_hall("Mourya", 540, recliner=True, rec_price=170)),
        ],
    },
    {
        "name": "Sri Narasimha Picture Palace",
        "location": "Gopalapatnam",
        "address": "Simhachalam Road, Gopalapatnam, Vizag 530027",
        "screens": [
            ("Main Screen", "Dolby Digital", small_town_hall("Sri Narasimha", 480)),
        ],
    },
    {
        "name": "Mini Narasimha Theatre",
        "location": "Gopalapatnam",
        "address": "Gopalapatnam Main Road, Vizag 530027",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Mini Narasimha", 340)),
        ],
    },
    {
        "name": "Sukanya Cinema Hall",
        "location": "Gopalapatnam",
        "address": "NAD Kotha Road, Gopalapatnam, Vizag 530027",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Sukanya", 420)),
        ],
    },
    {
        "name": "Sowjanya Cinema Hall",
        "location": "Gopalapatnam",
        "address": "Main Road, Gopalapatnam, Vizag 530027",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Sowjanya", 400)),
        ],
    },
    {
        "name": "Sri Sankara Talkies",
        "location": "Gopalapatnam",
        "address": "Near Petrol Bunk, Gopalapatnam, Vizag 530027",
        "screens": [
            ("Main Screen", "A/C DTS", small_town_hall("Sri Sankara", 430)),
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
        "name": "Asquare Cinemas",
        "location": "Pendurthi",
        "address": "Pendurthi Junction, Vizag 531173",
        "screens": [
            ("Screen 1", "4K Atmos", multiplex_generic("Screen 1", "4K Atmos", 230, 220, 160, 110)),
            ("Screen 2", "Dolby 7.1", multiplex_generic("Screen 2", "Dolby 7.1", 190, 200, 150, 100)),
        ],
    },
    {
        "name": "Satyam A/C DTS",
        "location": "Pendurthi",
        "address": "Main Road, Pendurthi, Vizag 531173",
        "screens": [
            ("Main Screen", "A/C DTS", small_town_hall("Satyam", 420)),
        ],
    },
    {
        "name": "Arena Cinemas",
        "location": "Saripalli, Pendurthi",
        "address": "Saripalli Road, Pendurthi, Vizag 531173",
        "screens": [
            ("Screen 1", "Dolby Atmos", multiplex_generic("Screen 1", "Dolby Atmos", 220, 220, 150, 100)),
        ],
    },
    {
        "name": "Sree Vijaya Talkies",
        "location": "Simhachalam",
        "address": "Simhachalam Hill Road, Vizag 530028",
        "screens": [
            ("Main Screen", "2D DTS", small_town_hall("Sree Vijaya", 390)),
        ],
    },
    {
        "name": "Sri Venkateswara Talkies, NAD",
        "location": "NAD Junction",
        "address": "Near NAD Flyover, Vizag 530009",
        "screens": [
            ("Main Screen", "Dolby 7.1", small_town_hall("Venkateswara NAD", 450, recliner=True)),
        ],
    },

    # =======================================================================
    # REGION 4: SOUTH INDUSTRIAL (Gajuwaka, Malkapuram, Kurmannapalem)
    # =======================================================================
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
        "name": "Sree Kanya Cinemas",
        "location": "Old Gajuwaka",
        "address": "Main Road, Old Gajuwaka, Near Mamata Hospital, Vizag 530026",
        "screens": [
            ("Main Screen", "2D", classic_single_screen("Sree Kanya", 130, 100, 80, total=640)),
        ],
    },
    {
        "name": "Sree Kanya Mini",
        "location": "Old Gajuwaka",
        "address": "Beside Sree Kanya Main, Old Gajuwaka, Vizag 530026",
        "screens": [
            ("Mini Screen", "4K Dolby", small_town_hall("Sree Kanya Mini", 320, recliner=True)),
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
        "name": "Mohini Mini Complex",
        "location": "Gajuwaka",
        "address": "Mohini Complex, High School Road, Gajuwaka, Vizag 530026",
        "screens": [
            ("Mini Screen", "Dolby 7.1", small_town_hall("Mohini Mini", 310)),
        ],
    },
    {
        "name": "Ramachandra Max",
        "location": "Gajuwaka",
        "address": "Main Road, Gajuwaka, Vizag 530026",
        "screens": [
            ("Screen 1", "4K Atmos", multiplex_generic("Screen 1", "4K Atmos", 260, 200, 150, 100)),
        ],
    },
    {
        "name": "Globex Cinemas",
        "location": "Gajuwaka",
        "address": "Chaitanya Nagar, Gajuwaka, Vizag 530026",
        "screens": [
            ("Screen 1", "Dolby 7.1", multiplex_generic("Screen 1", "2K Dolby", 210, 190, 140, 95)),
        ],
    },
    {
        "name": "Lakshmikanth Theatre",
        "location": "Gajuwaka",
        "address": "Near RTC Bus Depot, Gajuwaka, Vizag 530026",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Lakshmikanth", 420)),
        ],
    },
    {
        "name": "Kanya Cinema Hall",
        "location": "Gajuwaka",
        "address": "Old Gajuwaka Junction, Vizag 530026",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Kanya Cinema", 390)),
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
        "name": "Venkateswara Theatre, Kurmannapalem",
        "location": "Kurmannapalem Steel Plant Gate",
        "address": "Steel Plant Main Gate, Kurmannapalem, Vizag 530046",
        "screens": [
            ("Main Screen", "2D DTS", small_town_hall("Venkateswara Steel Plant", 480)),
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
    {
        "name": "Aruna Picture Palace",
        "location": "Malkapuram",
        "address": "Gullalapalem Road, Malkapuram, Vizag 530011",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Aruna Picture Palace", 450)),
        ],
    },
    {
        "name": "Maha Lakshmi Talkies",
        "location": "Malkapuram",
        "address": "Coromandel Gate, Malkapuram, Vizag 530011",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Maha Lakshmi", 370)),
        ],
    },
    {
        "name": "Sri Venkateswara Talkies, Scindia",
        "location": "Scindia, Malkapuram",
        "address": "Scindia Junction, Malkapuram, Vizag 530011",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Scindia Talkies", 360)),
        ],
    },
    {
        "name": "STBL Balaji Village Cinema",
        "location": "Sabbavaram",
        "address": "Main Road, Sabbavaram, Vizag Suburb 531035",
        "screens": [
            ("Screen 1", "4K Atmos", small_town_hall("Balaji Village Screen 1", 380, recliner=True, rec_price=160)),
            ("Screen 2", "Dolby 7.1", small_town_hall("Balaji Village Screen 2", 300)),
        ],
    },

    # =======================================================================
    # REGION 5: ANAKAPALLE & KASIMKOTA
    # =======================================================================
    {
        "name": "Venkateswara Movie Mart",
        "location": "Woodpeta, Anakapalle",
        "address": "Woodpeta, Main Road, Anakapalle, Vizag Dist 531001",
        "screens": [
            ("Screen 1", "4K Dolby Atmos", multiplex_generic("Screen 1", "4K Atmos", 320, 200, 140, 90)),
            ("Screen 2", "Dolby 7.1", multiplex_generic("Screen 2", "Dolby 7.1", 240, 180, 130, 80)),
        ],
    },
    {
        "name": "Sri Satyanarayana Picture Palace",
        "location": "Niddanam Doddi, Anakapalle",
        "address": "Niddanam Doddi, Main Road, Anakapalle 531001",
        "screens": [
            ("Main Screen", "Dolby Atmos", classic_single_screen("Satyanarayana", 140, 100, 75, total=520)),
        ],
    },
    {
        "name": "Sri Sairam Movie Land",
        "location": "Library Road, Anakapalle",
        "address": "Library Road, Anakapalle 531001",
        "screens": [
            ("Main Screen", "A/C DTS", small_town_hall("Sri Sairam", 440, recliner=True)),
        ],
    },
    {
        "name": "Ramachandra Theatre, Anakapalle",
        "location": "Narasinga Rao Peta, Anakapalle",
        "address": "Narasinga Rao Peta, Anakapalle 531001",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Ramachandra Anakapalle", 480)),
        ],
    },
    {
        "name": "Raja Picture Palace",
        "location": "Main Road, Anakapalle",
        "address": "Main Road, RTC Complex Area, Anakapalle 531001",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Raja Palace", 430)),
        ],
    },
    {
        "name": "Shirdi Sai Complex",
        "location": "Anakapalle",
        "address": "Railway Station Road, Anakapalle 531001",
        "screens": [
            ("Screen 1", "Dolby 7.1", small_town_hall("Shirdi Sai 1", 340)),
            ("Screen 2", "2D", small_town_hall("Shirdi Sai 2", 280)),
        ],
    },
    {
        "name": "Venkateshwara Cinema Hall, Chinna Veedhi",
        "location": "Chinna Veedhi, Anakapalle",
        "address": "Chinna Veedhi, Anakapalle 531001",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Venkateshwara Old", 360)),
        ],
    },
    {
        "name": "Sri Radha Krishna Theatre",
        "location": "Kasimkota",
        "address": "Main Road, Kasimkota, Anakapalle Mandal 531031",
        "screens": [
            ("Main Screen", "2D DTS", small_town_hall("Radha Krishna", 410)),
        ],
    },
    {
        "name": "Sri Laxmi Chitramandir",
        "location": "Kasimkota",
        "address": "Near Market Yard, Kasimkota 531031",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Laxmi Chitramandir", 370)),
        ],
    },

    # =======================================================================
    # REGION 6: CHODAVARAM & K.KOTAPADU
    # =======================================================================
    {
        "name": "Lakshmi Theatre, Chodavaram",
        "location": "Nowdu Veedhi, Chodavaram",
        "address": "Nowdu Veedhi, Chodavaram, Vizag Dist 531036",
        "screens": [
            ("Main Screen", "4K Laser Dolby", small_town_hall("Lakshmi Chodavaram", 460, recliner=True, rec_price=150)),
        ],
    },
    {
        "name": "Poorna Theatre A/C Dolby 7.1",
        "location": "Chodavaram",
        "address": "RTC Bus Stand Road, Chodavaram 531036",
        "screens": [
            ("Main Screen", "Dolby 7.1", small_town_hall("Poorna Chodavaram", 430)),
        ],
    },
    {
        "name": "Sai Siri Max AC DTS",
        "location": "Chodavaram",
        "address": "Main Road, Chodavaram 531036",
        "screens": [
            ("Main Screen", "AC DTS", small_town_hall("Sai Siri Max", 390)),
        ],
    },
    {
        "name": "Sri Sai Lakshmi AC",
        "location": "Chodavaram",
        "address": "Govt Hospital Road, Chodavaram 531036",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Sai Lakshmi", 370)),
        ],
    },
    {
        "name": "Twin Theatre Complex, Chodavaram",
        "location": "Chodavaram Bypass",
        "address": "Bypass Road, Chodavaram 531036",
        "screens": [
            ("Screen 1", "Dolby 7.1", small_town_hall("Twin 1", 310)),
            ("Screen 2", "2D", small_town_hall("Twin 2", 290)),
        ],
    },
    {
        "name": "Sri Rama Chitramandir",
        "location": "K.Kotapadu",
        "address": "Main Road, K.Kotapadu, Vizag Dist 531039",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Rama Kotapadu", 380)),
        ],
    },

    # =======================================================================
    # REGION 7: NARSIPATNAM, YELAMANCHILI & OUTER DISTRICT
    # =======================================================================
    {
        "name": "PVR Sree Kanya Cinemax",
        "location": "Main Road, Narsipatnam",
        "address": "Main Road, RTC Complex Area, Narsipatnam, Vizag Dist 531116",
        "screens": [
            ("Screen 1", "4K Atmos", multiplex_generic("Screen 1", "4K Atmos", 290, 200, 140, 90)),
            ("Screen 2", "Dolby 7.1", multiplex_generic("Screen 2", "Dolby 7.1", 220, 180, 130, 80)),
        ],
    },
    {
        "name": "Bangarraju Picture Palace",
        "location": "Narsipatnam",
        "address": "Near Gandhi Statue, Narsipatnam 531116",
        "screens": [
            ("Main Screen", "Dolby Atmos", small_town_hall("Bangarraju", 490, recliner=True)),
        ],
    },
    {
        "name": "Raju Movie Max",
        "location": "Narsipatnam",
        "address": "Bypass Road, Narsipatnam 531116",
        "screens": [
            ("Main Screen", "2D DTS", small_town_hall("Raju Movie Max", 440)),
        ],
    },
    {
        "name": "Sri Venkatavema Cinema Hall",
        "location": "Narsipatnam",
        "address": "Pedabondapalli Road, Narsipatnam 531116",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Venkatavema", 380)),
        ],
    },
    {
        "name": "SVC Sita Chitramandir",
        "location": "Yelamanchili",
        "address": "NH-16 Junction, Yelamanchili, Vizag Dist 531055",
        "screens": [
            ("Main Screen", "4K Dolby Atmos", small_town_hall("SVC Sita", 470, recliner=True, rec_price=160)),
        ],
    },
    {
        "name": "SVC Tulasi Chitramandir",
        "location": "Yelamanchili",
        "address": "Railway Station Road, Yelamanchili 531055",
        "screens": [
            ("Main Screen", "2K Dolby", small_town_hall("SVC Tulasi", 430)),
        ],
    },
    {
        "name": "Parameswari Theatre",
        "location": "Yelamanchili",
        "address": "Main Bazaar, Yelamanchili 531055",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Parameswari", 390)),
        ],
    },
    {
        "name": "Balaji Cinema Hall",
        "location": "Payakaraopeta",
        "address": "Main Road, Payakaraopeta 531126",
        "screens": [
            ("Main Screen", "2D DTS", small_town_hall("Balaji Payakaraopeta", 420)),
        ],
    },
    {
        "name": "Sri Venkateswara Talkies, Payakaraopeta",
        "location": "Payakaraopeta",
        "address": "Near Tuni Bridge, Payakaraopeta 531126",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Venkateswara Payakaraopeta", 380)),
        ],
    },
    {
        "name": "Sri Vijaya Cinema",
        "location": "Kotauratla",
        "address": "Main Road, Kotauratla, Vizag Dist 531085",
        "screens": [
            ("Main Screen", "2D", small_town_hall("Sri Vijaya Kotauratla", 360)),
        ],
    },
]


RENAMES = {
    "INOX CMR Central": "INOX CMR Central, Maddilapalem",
    "INOX Chitralaya": "INOX Vizag Chitralaya Mall",
    "Melody Cinema Hall": "Sri Melody",
    "Sangam Sarat Theatre": "Sangam Theatre",
}

# Public auditorium photos/reports are useful for surface appearance and seat
# type, but rarely publish a measured plan for each screen. These profiles are
# visual references only; the seat coordinates continue to come from each
# screen's own layout above.
AUDITORIUM_VISUAL_REFERENCES = {
    "Sarat Theatre": {
        "seat_color": "#71345f", "wall_color": "#17121b", "trim_color": "#bd9b6b",
        "seat_style": "standard", "source": "https://in.bookmyshow.com/buytickets/sarat-theater-a-c-4k-dolby-atmos-vizag/cinema-viza-sttr-MT",
    },
    "AVR Saptagiri Theatre": {
        "seat_color": "#31584b", "wall_color": "#111821", "trim_color": "#a94c5c",
        "seat_style": "standard", "source": "https://yappe.in/andhra-pradesh/visakhapatnam/saptagiri-theatre/634399",
    },
    "SVC Gokul 2K": {
        "seat_color": "#623c48", "wall_color": "#13151b", "trim_color": "#c9a84c",
        "seat_style": "standard", "source": "https://yappe.in/andhra-pradesh/visakhapatnam/gokul-theater/634527",
    },
    "Globex Cinemas": {
        "seat_color": "#a64f22", "wall_color": "#17120f", "trim_color": "#d59b52",
        "seat_style": "recliner", "source": "https://yappe.in/andhra-pradesh/visakhapatnam/globex-cinema/634532",
    },
    "Sri Melody": {
        "seat_color": "#254c75", "wall_color": "#0d1724", "trim_color": "#38a9c1",
        "seat_style": "recliner", "source": "https://x.com/rahool360/status/1946268195947724868",
    },
    "Cinepolis Sreekanya Cineglitz": {
        "seat_color": "#3e604b", "wall_color": "#111a17", "trim_color": "#71bf83",
        "seat_style": "standard", "source": "https://yappe.in/andhra-pradesh/visakhapatnam/cinepolis-sree-kanya/287464",
    },
    "Mukta A2 Cinemas": {
        "seat_color": "#572d2d", "wall_color": "#171313", "trim_color": "#c18b68",
        "seat_style": "recliner", "source": "https://www.moneycontrol.com/entertainment/mukta-a2-cinemas-reopens-in-vizag-after-stunning-makeover-deets-inside-article-12982879.html",
    },
}


def _attach_auditorium_visual(layout, theater_name, screen_type):
    """Attach evidence-based room styling while retaining screen seat geometry."""
    profile = AUDITORIUM_VISUAL_REFERENCES.get(theater_name)
    if profile:
        layout["visual"] = {**profile, "verified_at_theater_level": True}
        return

    # For screens without a venue photo, use conservative styling inferred
    # from their listed seating classes. This is explicitly marked as a model.
    classes = layout.get("classes", [])
    has_recliners = any("reclin" in str(c.get("name", "")).lower() or
                        "reclin" in str(c.get("code", "")).lower()
                        for c in classes)
    premium = any(any(word in str(c.get("name", "")).lower()
                      for word in ("vip", "prime", "premium", "lounge"))
                  for c in classes)
    layout["visual"] = {
        "seat_color": "#31594d" if has_recliners else ("#72533a" if premium else "#51252d"),
        "wall_color": "#11151d", "trim_color": "#c9a84c",
        "seat_style": "recliner" if has_recliners else "standard",
        "source": None, "verified_at_theater_level": False,
    }


def _attach_known_screen_geometry(layout, theater_name, screen_name):
    """Add only published screen measurements; all unmeasured room data stays estimated."""
    screen_label = str(layout.get("screen_label", "")).upper()
    if theater_name == "AAA Cinemas" and screen_name == "Screen 7" and "Q-LUXON" in screen_label:
        published = {
            "width_m": 70 * 0.3048, "height_m": 30 * 0.3048,
            "aspect_ratio": 70 / 30, "surface": "flat", "curve": 0,
            "source": "https://thirdeyecinemas.com/aaa-cinemas-vizag-introduces-indias-first-led-projection-q-luxon-screen/",
        }
    elif theater_name == "Sri Melody":
        published = {
            "width_m": 58.8 * 0.3048, "height_m": 32 * 0.3048,
            "aspect_ratio": 58.8 / 32, "surface": "flat", "curve": 0,
            "source": "https://www.hyderabadtheatres.com/screen/sri-melody-hdr-dolby-atmos-vizag-melody/",
        }
    elif theater_name == "Jagadamba Theatre" and screen_name == "70MM Main" and "70MM" in screen_label:
        published = {
            "width_m": 77.0 * 0.3048, "height_m": 32.2 * 0.3048,
            "aspect_ratio": 77.0 / 32.2,
            "surface": "curved", "curve": 0.3,
            "source": "https://theatresdb.com/screen/jagadamba-complex-jagadamba/",
        }
        # The seed names three actual seating sections; source descriptions
        # distinguish upper and lower balcony. Heights/distances are model
        # estimates for an editable preview, not surveyed architectural data.
        layout.setdefault("levels", [
            {"id": "upper-balcony", "name": "Upper Balcony", "type": "balcony",
             "base_elevation_m": 8.0, "front_distance_m": 34.0,
             "row_spacing_m": 1.15, "riser_height_m": 0.16},
            {"id": "lower-balcony", "name": "Lower Balcony", "type": "balcony",
             "base_elevation_m": 4.0, "front_distance_m": 20.0,
             "row_spacing_m": 1.15, "riser_height_m": 0.16},
            {"id": "stalls", "name": "First Class", "type": "floor",
             "base_elevation_m": 0.0, "front_distance_m": 7.0,
             "row_spacing_m": 1.15, "riser_height_m": 0.16},
        ])
        for cls in layout.get("classes", []):
            name = str(cls.get("name", "")).lower()
            level_id = ("upper-balcony" if "upper balcony" in name else
                        "lower-balcony" if "lower balcony" in name else
                        "stalls" if "first class" in name else None)
            if level_id:
                for row in cls.get("rows", []):
                    row.setdefault("level_id", level_id)
    else:
        return False
    # Preserve every administrator value and fill only absent published fields.
    current = layout.setdefault("screen", {})
    if not isinstance(current, dict):
        return False
    changed = False
    for key, value in published.items():
        if key not in current:
            current[key] = value
            changed = True
    return changed


def seed_vizag_theaters(db, Theater, Screen, verbose=True):
    """Idempotent: adds any missing Vizag theatre / screen with real seat layouts, never duplicates."""
    created_t = created_s = updated_l = 0

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
        else:
            if data.get("location") and theater.location != data["location"]:
                theater.location = data["location"]
            if data.get("address") and theater.address != data["address"]:
                theater.address = data["address"]

        for screen_name, screen_type, layout in data["screens"]:
            _attach_auditorium_visual(layout, data["name"], screen_type)
            _attach_known_screen_geometry(layout, data["name"], screen_name)
            existing = Screen.query.filter_by(theater_id=theater.id,
                                              name=screen_name).first()
            if existing:
                if not existing.layout:
                    existing.layout = layout
                    updated_l += 1
                else:
                    current_layout = existing.layout
                    changed = False
                    if current_layout.get("visual") != layout.get("visual"):
                        current_layout["visual"] = layout["visual"]
                        changed = True
                    # Geometry metadata is merged by missing keys only; seat
                    # rows, IDs, prices, and any admin-entered dimensions survive.
                    known_screen = layout.get("screen")
                    if known_screen:
                        target = current_layout.setdefault("screen", {})
                        if isinstance(target, dict):
                            for key, value in known_screen.items():
                                if key not in target:
                                    target[key] = value
                                    changed = True
                    def row_signature(source):
                        return [(cls.get("code"), row.get("label"), int(row.get("start", 1)), int(row.get("count", 0)))
                                for cls in source.get("classes", []) for row in cls.get("rows", [])]
                    same_seed_rows = row_signature(current_layout) == row_signature(layout)
                    known_levels = (layout.get("levels") or []) if same_seed_rows else []
                    if known_levels:
                        current_levels = current_layout.setdefault("levels", [])
                        if isinstance(current_levels, list):
                            existing_level_ids = {str(item.get("id")) for item in current_levels if isinstance(item, dict)}
                            for level in known_levels:
                                if str(level.get("id")) not in existing_level_ids:
                                    current_levels.append(level)
                                    existing_level_ids.add(str(level.get("id")))
                                    changed = True
                    known_rows = {row.get("label"): row.get("level_id")
                                  for cls in layout.get("classes", []) for row in cls.get("rows", [])
                                  if row.get("level_id")} if same_seed_rows else {}
                    if known_rows:
                        for cls in current_layout.get("classes", []):
                            for row in cls.get("rows", []):
                                if row.get("label") in known_rows and not row.get("level_id"):
                                    row["level_id"] = known_rows[row["label"]]
                                    changed = True
                    if changed:
                        existing.layout = current_layout
                        updated_l += 1
                continue
            screen = Screen(theater_id=theater.id, name=screen_name,
                            screen_type=screen_type)
            screen.layout = layout
            db.session.add(screen)
            created_s += 1

    db.session.commit()
    if verbose:
        print(f"Vizag seed: +{created_t} theatres, +{created_s} screens, +{updated_l} layouts updated (Total: {len(VIZAG_THEATERS)} theatres)")
    return created_t, created_s
