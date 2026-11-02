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

import math


def auditorium_geometry(layout: dict, row_defs: list[dict], fallback_aspect: float = 1.85) -> dict:
    """Normalize optional physical layout metadata and estimate missing dimensions in metres.

    `classes` are pricing groups. Rows share a physical level unless a row explicitly
    names a level_id; price classes never create floors implicitly.
    """
    screen = layout.get("screen") if isinstance(layout.get("screen"), dict) else {}
    room = layout.get("room") if isinstance(layout.get("room"), dict) else {}
    explicit_levels = layout.get("levels") if isinstance(layout.get("levels"), list) else []
    levels = {}
    for item in explicit_levels:
        if isinstance(item, dict) and item.get("id"):
            levels[str(item["id"])] = item
    row_levels = [str(r.get("level_id") or "main") for r in row_defs]
    for level_id in row_levels:
        levels.setdefault(level_id, {"id": level_id, "name": "Main floor", "type": "floor"})
    warnings = []
    if not screen.get("width_m") or not screen.get("height_m"):
        warnings.append("Screen dimensions are estimated; enter measured width_m and height_m to replace them.")
    if not room.get("width_m") or not room.get("depth_m") or not room.get("height_m"):
        warnings.append("Room dimensions are estimated from the seating layout.")
    widest = max((max(1, int(row.get("count", 0))) * max(1, int(row.get("seatSpan", 1))) * .62 for row in row_defs), default=8)
    width = float(screen.get("width_m") or max(6.0, min(30.0, widest)))
    aspect = float(screen.get("aspect_ratio") or fallback_aspect)
    height = float(screen.get("height_m") or width / max(.1, aspect))
    max_row_units = max((int(r.get("count", 0)) * int(r.get("seatSpan", 1)) * .62 + len(r.get("aislesAfter", [])) * .85 + int(r.get("offset", 0)) * .62 for r in row_defs), default=8)
    needed_width = max(max_row_units + 5.0, width + 2.0)
    room_width = float(room.get("width_m") or needed_width)
    if room_width < needed_width:
        warnings.append(f"Configured room width ({room_width:g} m) is narrower than seating plus side clearance ({needed_width:g} m); preview expands to fit.")
        room_width = needed_width
    default_spacing = float(screen.get("row_spacing_m") or 1.15)
    row_positions = []
    per_level_index = {}
    level_row_counts = {}
    for level_id in row_levels:
        level_row_counts[level_id] = level_row_counts.get(level_id, 0) + 1
    main_row_count = row_levels.count("main")
    balcony_front = 7.0 + main_row_count * default_spacing + 3.0
    for i, row in enumerate(row_defs):
        level_id = row_levels[i]
        level = levels[level_id]
        idx = per_level_index.get(level_id, 0)
        per_level_index[level_id] = idx + 1
        spacing = float(level.get("row_spacing_m") or default_spacing)
        riser = float(level.get("riser_height_m") or screen.get("riser_height_m") or .18)
        is_balcony = str(level.get("type") or "").lower() in {"balcony", "mezzanine"}
        base = float(level.get("base_elevation_m", 4.0 if is_balcony else 0) or 0)
        front = float(level.get("front_distance_m") or (balcony_front if is_balcony else 7.0))
        level_row_index = level_row_counts[level_id] - idx - 1
        row_positions.append({"levelId": level_id, "levelIndex": idx, "x": 0,
                              "z": front + level_row_index * spacing,
                              "y": base + level_row_index * riser,
                              "rowSpacing": spacing, "riserHeight": riser,
                              "levelType": str(level.get("type") or "floor")})
    furthest = max((abs(p["z"]) for p in row_positions), default=12)
    needed_depth = furthest + 8.0
    deepest = float(room.get("depth_m") or needed_depth)
    if deepest < needed_depth:
        warnings.append(f"Configured room depth ({deepest:g} m) does not include row and rear clearance ({needed_depth:g} m); preview expands to fit.")
        deepest = needed_depth
    tallest_level = max((float(level.get("base_elevation_m") or 0) +
                         max(0, per_level_index.get(level_id, 1)-1) * float(level.get("riser_height_m") or .18)
                         for level_id, level in levels.items()), default=0)
    needed_height = max(float(screen.get("bottom_m") or 1) + height + 2, tallest_level + 4)
    room_height = float(room.get("height_m") or needed_height)
    if room_height < needed_height:
        warnings.append(f"Configured room height ({room_height:g} m) is below screen/seating clearance ({needed_height:g} m); preview expands to fit.")
        room_height = needed_height
    surface = str(screen.get("surface") or "curved").lower()
    curve = float(screen.get("curve", 0 if surface in {"flat", "led"} else .3))
    return {"screen": {"width": width, "height": height,
                       "bottom": float(screen.get("bottom_m", 1.0)),
                       "surface": surface,
                       "curve": curve, "aspect": aspect},
            "room": {"width": room_width, "depth": deepest, "height": room_height},
            "levels": list(levels.values()), "rows": row_positions,
            "estimated": bool(warnings), "warnings": warnings}


def validate_auditorium_geometry(layout: dict) -> list[str]:
    """Validate seat identity and explicitly supplied physical geometry."""
    errors = []
    if not isinstance(layout, dict) or not isinstance(layout.get("classes", []), list):
        return ["Layout must be an object with a classes array."]
    seen = set()
    for cls in layout.get("classes", []):
        if not isinstance(cls, dict):
            errors.append("Each class must be an object.")
            continue
        for row in cls.get("rows", []):
            if not isinstance(row, dict) or not row.get("label"):
                errors.append("Each row must be an object with a label.")
                continue
            try:
                start, count = int(row.get("start", 1)), int(row.get("count", 0))
            except (TypeError, ValueError):
                errors.append(f"Row {row['label']} needs integer start and count values.")
                continue
            if start < 1 or count < 0 or count > 500:
                errors.append(f"Row {row['label']} has an invalid seat range.")
                continue
            blocked = set(row.get("blocked") or [])
            for n in range(start, start + count):
                seat_id = f"{row['label']}{n}"
                if seat_id in seen:
                    errors.append(f"Seat ID {seat_id} is repeated across rows or price classes.")
                    break
                seen.add(seat_id)
    for section_name in ("screen", "room"):
        section = layout.get(section_name, {})
        if section and not isinstance(section, dict):
            errors.append(f"{section_name} metadata must be an object.")
            continue
        if isinstance(section, dict):
            for key, value in section.items():
                if key.endswith("_m"):
                    try:
                        number = float(value)
                        if not math.isfinite(number) or number < (0 if key == "bottom_m" else .01) or number > 200:
                            raise ValueError
                    except (TypeError, ValueError):
                        errors.append(f"{section_name}.{key} must be a positive measurement in metres (up to 200 m).")
    level_ids = set()
    for level in layout.get("levels", []):
        if not isinstance(level, dict) or not level.get("id"):
            errors.append("Every physical level must be an object with an id.")
            continue
        if str(level["id"]) in level_ids:
            errors.append(f"Physical level id {level['id']} is repeated.")
        level_ids.add(str(level["id"]))
        for key, value in level.items():
            if key.endswith("_m"):
                try:
                    number = float(value)
                    if not math.isfinite(number) or abs(number) > 200 or (key == "base_elevation_m" and number < 0) or (key != "base_elevation_m" and number <= 0):
                        raise ValueError
                except (TypeError, ValueError):
                    errors.append(f"levels[{level['id']}].{key} must be a valid measurement in metres.")
    for cls in layout.get("classes", []):
        if not isinstance(cls, dict):
            continue
        for row in cls.get("rows", []):
            if isinstance(row, dict) and row.get("level_id") and str(row["level_id"]) not in level_ids:
                errors.append(f"Row {row.get('label', '?')} references missing physical level {row['level_id']}.")
    screen = layout.get("screen", {})
    if isinstance(screen, dict):
        surface = screen.get("surface")
        if surface and str(surface).lower() not in {"flat", "curved", "led", "imax"}:
            errors.append("screen.surface must be flat, curved, led, or imax.")
        if "curve" in screen:
            try:
                curve = float(screen["curve"])
                if not math.isfinite(curve) or curve < 0 or curve > .75:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append("screen.curve must be between 0 and 0.75; use 0 for a flat screen.")
    return errors

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

    # Approximate the upward viewing angle from a 3.4m screen-centre rise and
    # the seat's estimated distance. This keeps the displayed angle physically
    # plausible instead of assigning every row an arbitrary 26°–52° tilt.
    screen_dist_pct = int(90 - (front_pct * 75))
    seat_distance_m = 6.5 + ((screen_dist_pct - 15) / 75) * 11.5
    view_angle = int(round(math.degrees(math.atan2(3.4, seat_distance_m))))
    rows_ahead = max(0, total_rows - row_index - 1)
    off_center_deg = int(abs(col_pct - 0.5) * 50)
    side_angle_deg = int(round((col_pct - 0.5) * 50))

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
        comfort_badge = f"⚠️ {view_angle}° Upward View"
        zone_color = "amber"
    elif 0.25 <= front_pct <= 0.65 and 0.25 <= col_pct <= 0.75:
        zone = "GOLD"
        zone_name = "VIP Gold Center Zone"
        comfort_badge = f"🌟 {view_angle}° Upward View · Atmos Sweetspot"
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

    # Vibe Zone Calculations:
    # 1. Couples Corner (span == 2 or corner recliners/back row pairs)
    # 2. Quiet Zone (back rows, high privacy)
    # 3. Fun & Social Zone (center middle crowd rows)
    # Front seats are the rows closest to the screen (at the bottom of the map).
    # Reserve this front quarter for fans who want an immersive, energetic view.
    # 1. Fans Front Zone  2. Couples Corner  3. Quiet Zone  4. Fun & Social  5. Family & Easy-Exit
    if front_pct >= 0.75:
        vibe_code = "FANS"
        vibe_name = "Fans Front Zone"
        vibe_icon = "📣"
        vibe_badge = "📣 Front Row Fan Zone"
        vibe_desc = "Front rows closest to the screen for fans who want a larger, more immersive view."
        vibe_color = "amber"
    elif front_pct < 0.25 and (col_pct < 0.2 or col_pct > 0.8):
        vibe_code = "COUPLES"
        vibe_name = "Couples Corner"
        vibe_icon = "💑"
        vibe_badge = "💑 Cozy & Private Pair"
        vibe_desc = "Spacious corner seating with extra privacy and great ambiance."
        vibe_color = "rose"
    elif front_pct < 0.35:
        vibe_code = "QUIET"
        vibe_name = "Quiet Zone"
        vibe_icon = "🔇"
        vibe_badge = "🔇 Distraction-Free Quiet"
        vibe_desc = "Top-tier viewing position with minimal foot traffic."
        vibe_color = "purple"
    elif 0.35 <= front_pct <= 0.75 and 0.25 <= col_pct <= 0.75:
        vibe_code = "FUN"
        vibe_name = "Fun & Social Zone"
        vibe_icon = "😂"
        vibe_badge = "😂 High Energy & Laughs"
        vibe_desc = "Heart of the cinema crowd — best for blockbusters and comedy!"
        vibe_color = "amber"
    else:
        vibe_code = "FAMILY"
        vibe_name = "Family & Easy-Exit Zone"
        vibe_icon = "👨‍👩‍👧"
        vibe_badge = "👨‍👩‍👧 Family Friendly & Easy Access"
        vibe_desc = "Convenient exit access for kids, families, and quick snack runs."
        vibe_color = "emerald"

    # Overall seat quality score (0 to 100) combining acoustics, center alignment & view distance
    overall_score = max(50, min(99, int((sound_score_raw * 0.4) + (max(0, 100 - off_center_deg * 3) * 0.35) + (screen_dist_pct * 0.25))))

    return {
        "zone": zone,
        "zone_name": zone_name,
        "comfort_badge": comfort_badge,
        "zone_color": zone_color,
        "view_angle": view_angle,
        "screen_dist_pct": screen_dist_pct,
        "rows_ahead": rows_ahead,
        "row_index": row_index,
        "off_center_deg": off_center_deg,
        "side_angle_deg": side_angle_deg,
        "sound_score": sound_score_raw,
        "sound_exp": sound_exp,
        "sound_badge": sound_badge,
        "sound_profile": sound_profile,
        "sound_tier": sound_tier,
        "vibe_code": vibe_code,
        "vibe_name": vibe_name,
        "vibe_icon": vibe_icon,
        "vibe_badge": vibe_badge,
        "vibe_desc": vibe_desc,
        "vibe_color": vibe_color,
        "score": overall_score
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

    # Preserve layout row order; the booking template places the screen marker after the rows,
    # so the last rows are the front rows nearest the screen at the bottom of the map.
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
