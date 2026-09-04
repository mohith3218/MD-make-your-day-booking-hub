"""
CineWave - seat layout engine
=============================
Turns a screen's layout JSON into a render-ready grid, so every audi can look
exactly like the real theater (different row widths, aisles in the right place,
missing corner seats, couple/sofa seats, staggered rows).

Layout JSON stored on Screen.layout_json
----------------------------------------
{
  "screen_label": "Screen 1 - INSIGNIA",
  "seats_per_group": 0,              # optional, purely cosmetic
  "classes": [
    {
      "code": "RECLINER",
      "name": "Recliner",
      "price": 320,
      "rows": [
        {"label": "A", "count": 10, "aisles_after": [5], "offset": 0},
        {"label": "B", "count": 12, "aisles_after": [4, 8], "blocked": ["B7"], "seat_span": 2}
      ]
    }
  ]
}

Row keys
--------
label         : row letter shown on the left ("A", "AA", "G")
count         : number of seats in that row (rows can differ - that is the point)
start         : first seat number, default 1
aisles_after  : insert a walking aisle *after* these seat numbers
blocked       : seat ids that physically do not exist / are damaged
offset        : blank half-cells at the row start, used to centre short rows
seat_span     : 2 = couple / sofa seat (rendered double width)
"""

from __future__ import annotations

# how many seats one user may book in a single transaction (BookMyShow uses 10)
MAX_SEATS_PER_BOOKING = 10


def _rows_of(cls: dict) -> list:
    return cls.get("rows") or []


def count_seats(layout: dict) -> int:
    """Total real, bookable seats in a layout."""
    total = 0
    for cls in layout.get("classes", []):
        for row in _rows_of(cls):
            blocked = set(row.get("blocked") or [])
            start = int(row.get("start", 1))
            for n in range(start, start + int(row.get("count", 0))):
                if f"{row['label']}{n}" not in blocked:
                    total += 1
    return total


def seat_price_map(layout: dict, price_overrides: dict | None = None) -> dict:
    """seat_id -> price, honouring per-show price overrides by class code."""
    price_overrides = price_overrides or {}
    prices = {}
    for cls in layout.get("classes", []):
        price = float(price_overrides.get(cls.get("code"), cls.get("price", 0)))
        for row in _rows_of(cls):
            start = int(row.get("start", 1))
            for n in range(start, start + int(row.get("count", 0))):
                prices[f"{row['label']}{n}"] = price
    return prices


def seat_class_map(layout: dict) -> dict:
    """seat_id -> class display name."""
    out = {}
    for cls in layout.get("classes", []):
        for row in _rows_of(cls):
            start = int(row.get("start", 1))
            for n in range(start, start + int(row.get("count", 0))):
                out[f"{row['label']}{n}"] = cls.get("name", "Standard")
    return out


def compute_seat_pov(cell_id: str, row_label: str, seat_num: int, row_index: int, total_rows: int, cell_index: int, total_cells_in_row: int) -> dict:
    """
    Calculates viewing zone, viewing angle, and neck tilt recommendation for a seat.
    The screen is drawn at the BOTTOM of the layout (row_index = total_rows - 1).
    - FRONT_ZONE: Rows closest to the screen (bottom rows, high neck tilt angle).
    - GOLD_ZONE: Middle rows, centered columns (Optimal 35° Field of View & Dolby Atmos Sweetspot).
    - SIDE_ZONE: Outer columns left/right.
    - PRIME_ZONE: Elevated back rows / recliners.
    """
    # front_pct = 1.0 means right in front of the screen at the bottom
    front_pct = row_index / max(1, total_rows - 1)
    col_pct = cell_index / max(1, total_cells_in_row - 1)

    # Front row (bottom): ~52° neck tilt, 15% screen distance
    # Back row (top): ~26° eye-level angle, 90% screen distance
    view_angle = int(26 + (front_pct * 26))
    screen_dist_pct = int(90 - (front_pct * 75))
    off_center_deg = int(abs(col_pct - 0.5) * 50)

    # Sound Experience Calculations:
    # Cinema acoustic sweetspot is typically middle-center of the auditorium (front_pct ~0.40 to 0.60, col_pct ~0.40 to 0.60)
    dist_from_sweetspot = ((front_pct - 0.48) ** 2 + (col_pct - 0.5) ** 2) ** 0.5
    sound_score_raw = max(65, int(100 - (dist_from_sweetspot * 50)))

    if dist_from_sweetspot < 0.18:
        sound_exp = "Dolby Atmos Master Sweetspot"
        sound_badge = f"🔊 {sound_score_raw}% · 360° Object Audio"
        sound_profile = "Perfect Surround & Overhead Calibration"
        sound_tier = "Atmos Elite"
    elif front_pct > 0.75:
        sound_exp = "Front Stage & Direct Dialogue"
        sound_badge = f"📢 {sound_score_raw}% · High Center Channel"
        sound_profile = "Direct Front L-C-R Speakers Impact"
        sound_tier = "Front Stage"
    elif col_pct < 0.18 or col_pct > 0.82:
        sound_exp = "Side Surround Array Proximity"
        sound_badge = f"🎧 {sound_score_raw}% · Near Wall Surrounds"
        sound_profile = "Strong Lateral Sound Effects"
        sound_tier = "Side Surround"
    elif front_pct < 0.25:
        sound_exp = "Rear Surround & Deep Bass Depth"
        sound_badge = f"🎶 {sound_score_raw}% · Subwoofer Envelopment"
        sound_profile = "Rich Reverb & Rear Soundfield"
        sound_tier = "Rear Immersion"
    else:
        sound_exp = "Balanced Multi-Channel Surround"
        sound_badge = f"🔊 {sound_score_raw}% · Balanced Acoustic Field"
        sound_profile = "Even 7.1/Atmos Channel Spread"
        sound_tier = "Balanced Surround"

    if front_pct > 0.80:
        zone = "FRONT"
        zone_name = "Front Row Immersive Screen Zone"
        comfort_badge = f"⚠️ {view_angle}° High Upward Neck Tilt"
        zone_color = "amber"
    elif 0.25 <= front_pct <= 0.65 and 0.25 <= col_pct <= 0.75:
        zone = "GOLD"
        zone_name = "VIP Gold Center Zone"
        comfort_badge = f"🌟 Optimal {view_angle}° FOV · Atmos Sweetspot"
        zone_color = "emerald"
    elif col_pct < 0.15 or col_pct > 0.85:
        zone = "SIDE"
        zone_name = "Wide Angle Side View"
        comfort_badge = f"↔️ {off_center_deg}° Off-Center Angle"
        zone_color = "sky"
    else:
        zone = "PRIME"
        zone_name = "Prime Eye-Level View"
        comfort_badge = f"✨ Elevated Recliner / Back Row View"
        zone_color = "purple"

    return {
        "zone": zone,
        "zone_name": zone_name,
        "comfort_badge": comfort_badge,
        "zone_color": zone_color,
        "view_angle": view_angle,
        "screen_dist_pct": screen_dist_pct,
        "off_center_deg": off_center_deg,
        "sound_score": sound_score_raw,
        "sound_exp": sound_exp,
        "sound_badge": sound_badge,
        "sound_profile": sound_profile,
        "sound_tier": sound_tier
    }


def build_layout(layout: dict,
                 booked: set | None = None,
                 held: set | None = None,
                 price_overrides: dict | None = None) -> list:
    """
    Expand the layout JSON into rows of cells for the template.
    """
    booked = booked or set()
    held = held or set()
    price_overrides = price_overrides or {}
    out = []

    # Calculate total rows across all classes
    all_rows = []
    for cls in layout.get("classes", []):
        all_rows.extend(_rows_of(cls))
    total_rows_count = max(1, len(all_rows))

    global_row_index = 0
    for cls in layout.get("classes", []):
        code = cls.get("code", "STD")
        price = float(price_overrides.get(code, cls.get("price", 0)))
        block = {"code": code,
                 "name": cls.get("name", "Standard"),
                 "price": price,
                 "base_price": float(cls.get("price", 0)),
                 "rows": [],
                 "seats": 0}

        for row in _rows_of(cls):
            label = row["label"]
            start = int(row.get("start", 1))
            count = int(row.get("count", 0))
            aisles = set(int(a) for a in (row.get("aisles_after") or []))
            blocked = set(row.get("blocked") or [])
            span = int(row.get("seat_span", 1))
            cells = []

            for _ in range(int(row.get("offset", 0))):
                cells.append({"kind": "pad"})

            total_cols_in_row = count + len(aisles) + int(row.get("offset", 0))
            col_idx = int(row.get("offset", 0))

            for n in range(start, start + count):
                seat_id = f"{label}{n}"
                pov = compute_seat_pov(seat_id, label, n, global_row_index, total_rows_count, col_idx, total_cols_in_row)

                if seat_id in blocked:
                    cells.append({"kind": "blocked"})
                else:
                    if seat_id in booked:
                        status = "booked"
                    elif seat_id in held:
                        status = "held"
                    else:
                        status = "available"
                    cells.append({"kind": "seat", "id": seat_id, "num": n,
                                  "price": price, "cls": block["name"],
                                  "code": code, "status": status, "span": span,
                                  "pov": pov})
                    block["seats"] += 1
                col_idx += 1
                if n in aisles:
                    cells.append({"kind": "aisle"})
                    col_idx += 1

            block["rows"].append({"label": label, "cells": cells})
            global_row_index += 1

        out.append(block)

    # classes are drawn screen-first (closest to screen at the top)
    return out


def validate_seats(layout: dict, seat_ids: list) -> tuple[bool, str]:
    """Make sure the posted seat ids actually exist in this screen."""
    valid = set(seat_price_map(layout).keys())
    blocked = set()
    for cls in layout.get("classes", []):
        for row in _rows_of(cls):
            blocked.update(row.get("blocked") or [])

    if not seat_ids:
        return False, "Please select at least one seat."
    if len(seat_ids) > MAX_SEATS_PER_BOOKING:
        return False, f"You can book a maximum of {MAX_SEATS_PER_BOOKING} seats at a time."
    if len(set(seat_ids)) != len(seat_ids):
        return False, "Duplicate seats in your selection."
    for s in seat_ids:
        if s not in valid or s in blocked:
            return False, f"Seat {s} does not exist in this screen."
    return True, ""


def availability(layout: dict, unavailable: set) -> dict:
    """Small summary used on the movie page: 12 of 180 seats left."""
    total = count_seats(layout)
    return {"total": total,
            "sold": len(unavailable),
            "left": max(0, total - len(unavailable))}
