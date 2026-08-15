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


def build_layout(layout: dict,
                 booked: set | None = None,
                 held: set | None = None,
                 price_overrides: dict | None = None) -> list:
    """
    Expand the layout JSON into rows of cells for the template.

    Returns [
      {
        "code": "RECLINER", "name": "Recliner", "price": 320, "seats": 40,
        "rows": [
           {"label": "A",
            "cells": [{"kind": "seat", "id": "A1", "num": 1, "price": 320,
                       "cls": "Recliner", "status": "available", "span": 1},
                      {"kind": "aisle"}, ...]}
        ]
      }, ...
    ]
    status is one of: available | booked | held | blocked
    """
    booked = booked or set()
    held = held or set()
    price_overrides = price_overrides or {}
    out = []

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

            for n in range(start, start + count):
                seat_id = f"{label}{n}"
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
                                  "code": code, "status": status, "span": span})
                    block["seats"] += 1
                if n in aisles:
                    cells.append({"kind": "aisle"})

            block["rows"].append({"label": label, "cells": cells})

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
