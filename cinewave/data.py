"""Curated in-app data defaults; no database operations are performed here."""

SNACK_ITEMS = [
    {"id": "popcorn_lg", "name": "Large Butter Popcorn", "price": 180, "icon": "fa-bowl-food", "desc": "Fresh tub with extra butter"},
    {"id": "pepsi_m", "name": "Chilled Pepsi 500ml", "price": 110, "icon": "fa-glass-water", "desc": "Ice-cold cinema beverage"},
    {"id": "combo_sav", "name": "Saver Combo (Popcorn + 2 Pepsi)", "price": 260, "icon": "fa-box-open", "desc": "Best value for 2 viewers"},
    {"id": "nachos_c", "name": "Cheese Nachos Extra Dip", "price": 160, "icon": "fa-stroopwafel", "desc": "Crispy corn chips with warm cheese"}
]


SAMPLE_LAYOUT = {
    "screen_label": "Screen 1",
    "screen": {"width_m": 18, "height_m": 9.7},
    "classes": [
        {"code": "RECLINER", "name": "Recliner", "price": 320,
         "rows": [{"label": "A", "count": 10, "aisles_after": [5], "blocked": []},
                  {"label": "B", "count": 10, "aisles_after": [5], "blocked": []}]},
        {"code": "EXECUTIVE", "name": "Executive", "price": 220,
         "rows": [{"label": "C", "count": 16, "aisles_after": [4, 12], "blocked": []},
                  {"label": "D", "count": 16, "aisles_after": [4, 12], "blocked": []}]},
        {"code": "NORMAL", "name": "Normal", "price": 150,
         "rows": [{"label": "E", "count": 18, "aisles_after": [4, 14], "blocked": []},
                  {"label": "F", "count": 18, "aisles_after": [4, 14], "blocked": []}]},
    ],
}
