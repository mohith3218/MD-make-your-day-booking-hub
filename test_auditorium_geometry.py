"""Focused geometry assertions; these tests do not touch the app database."""
import unittest
import copy

import seat_layout as sl
import vizag_theaters as theaters


def make_layout(row_count, seats_per_row, *, level_id=None, explicit=False):
    rows = [{"label": f"R{i + 1}", "count": seats_per_row, "start": 1,
             **({"level_id": level_id} if level_id else {})}
            for i in range(row_count)]
    layout = {"classes": [{"code": "STD", "name": "Standard", "price": 200, "rows": rows}]}
    if explicit:
        layout.update({"screen": {"width_m": 18, "height_m": 7.5, "bottom_m": 1.2, "surface": "flat"},
                       "room": {"width_m": 26, "depth_m": 45, "height_m": 11},
                       "levels": [{"id": "main", "name": "Floor", "type": "floor"}]})
    return layout


class AuditoriumGeometryTests(unittest.TestCase):
    def geometry(self, layout, aspect=1.85):
        row_defs = []
        for cls in layout["classes"]:
            for row in cls["rows"]:
                row_defs.append({"label": row["label"], "count": row["count"],
                                 "seatSpan": row.get("seat_span", 1), "aislesAfter": [],
                                 "level_id": row.get("level_id")})
        return sl.auditorium_geometry(layout, row_defs, aspect)

    def test_seven_layout_shapes_have_finite_nonzero_geometry(self):
        cases = [
            make_layout(5, 8), make_layout(10, 18), make_layout(25, 22),
            theaters.jagadamba_70mm(), make_layout(20, 14, explicit=True),
            make_layout(20, 14), make_layout(4, 8),
        ]
        cases[5]["classes"][0]["rows"] = [
            {"label": f"F{i + 1}", "count": 10} for i in range(8)
        ] + [{"label": f"B{i + 1}", "count": 10, "level_id": "balcony"} for i in range(4)]
        cases[5]["levels"] = [{"id": "main", "name": "Floor", "type": "floor"},
                               {"id": "balcony", "name": "Balcony", "type": "balcony"}]
        for layout in cases:
            with self.subTest(rows=len(layout["classes"][0]["rows"])):
                geo = self.geometry(layout)
                self.assertGreater(geo["screen"]["width"], 0)
                self.assertGreater(geo["screen"]["height"], 0)
                self.assertGreater(geo["room"]["depth"], max(p["z"] for p in geo["rows"]))
                expected_rows = sum(len(cls["rows"]) for cls in layout["classes"])
                self.assertEqual(len(geo["rows"]), expected_rows)
                self.assertTrue(all(all(map(lambda n: isinstance(n, (int, float)) and abs(n) < 1000,
                                           (p["x"], p["y"], p["z"]))) for p in geo["rows"]))
        self.assertEqual(self.geometry(cases[4])["screen"]["surface"], "flat")
        balcony = self.geometry(cases[5])
        self.assertTrue(all(p["y"] >= 4 for p in balcony["rows"][8:]))
        self.assertGreater(balcony["rows"][8]["z"], balcony["rows"][7]["z"])
        self.assertEqual(sl.count_seats(cases[0]), 40)
        self.assertEqual(sl.count_seats(cases[1]), 180)
        self.assertEqual(sl.count_seats(cases[2]), 550)
        self.assertEqual(sum(len(c["rows"]) for c in cases[3]["classes"]), 38)
        self.assertEqual(sl.count_seats(cases[3]), 886)
        self.assertEqual(sl.count_seats(theaters.aaa_qluxon_screen()), 491)
        self.assertEqual(sl.count_seats(theaters.melody_hall()), 774)

    def test_variable_rows_offsets_blocked_aisles_and_couples_survive(self):
        layout = {"classes": [{"code": "STD", "rows": [
            {"label": "A", "count": 8, "offset": 2, "blocked": ["A3"],
             "aisles_after": [4], "seat_span": 2},
            {"label": "B", "count": 5, "offset": 0, "aisles_after": [2]},
        ]}]}
        self.assertEqual(sl.count_seats(layout), 12)
        self.assertEqual(len(set(sl.seat_price_map(layout))), 13)

    def test_seeded_jagadamba_uses_distinct_estimated_physical_levels(self):
        layout = theaters.jagadamba_70mm()
        theaters._attach_known_screen_geometry(layout, "Jagadamba Theatre", "70MM Main")
        self.assertEqual({row["level_id"] for cls in layout["classes"] for row in cls["rows"]},
                         {"upper-balcony", "lower-balcony", "stalls"})
        geo = self.geometry(layout)
        heights = {level["id"]: level["base_elevation_m"] for level in geo["levels"]}
        self.assertGreater(heights["upper-balcony"], heights["lower-balcony"])
        self.assertGreater(heights["lower-balcony"], heights["stalls"])
        self.assertTrue(geo["estimated"])

    def test_all_seeded_layouts_have_valid_geometry_and_unique_ids(self):
        for theater in theaters.VIZAG_THEATERS:
            for screen_name, _, layout in theater["screens"]:
                with self.subTest(theater=theater["name"], screen=screen_name):
                    self.assertEqual(sl.validate_auditorium_geometry(layout), [])
                    self.assertGreater(sl.count_seats(layout), 0)

    def test_every_screen_gets_an_individual_truthful_visual_profile(self):
        profile_keys = set()
        status_counts = {}
        for theater in theaters.VIZAG_THEATERS:
            for screen_name, screen_type, source_layout in theater["screens"]:
                layout = copy.deepcopy(source_layout)
                theaters._attach_auditorium_visual(layout, theater["name"], screen_type)
                theaters._attach_auditorium_screen_profile(layout, theater["name"], screen_name)
                profile = layout["reference_profile"]
                profile_keys.add((profile["theater"], profile["screen"]))
                status_counts[profile["reference_status"]] = status_counts.get(profile["reference_status"], 0) + 1
                if (theater["name"], screen_name) not in theaters.AUDITORIUM_SCREEN_PROFILES:
                    self.assertEqual(profile["reference_status"], "estimated_model")
                    self.assertEqual(profile["references"], [])

        self.assertEqual(len(profile_keys), 127)
        self.assertEqual(status_counts.get("verified_reference"), 3)
        self.assertEqual(status_counts.get("venue_reference"), 1)
        self.assertEqual(status_counts.get("estimated_model"), 123)

    def test_screen_photo_profiles_are_interior_only_and_admin_edits_survive(self):
        for key in [("Sarat Theatre", "Main Screen"), ("INOX Varun Beach", "Screen 5")]:
            profile = theaters.AUDITORIUM_SCREEN_PROFILES[key]
            reference = profile["references"][0]
            self.assertTrue(reference["screen_verified"])
            self.assertFalse(reference["approved_for_use"])
            self.assertEqual(reference["license"], "review_required")
            self.assertIn("interior", reference["notes"].lower())

        layout = {"visual": {}, "reference_profile": {
            "theater": "INOX Varun Beach", "screen": "Screen 5",
            "reference_status": "estimated_model", "administrator_edited": True,
            "architecture": {"seat_color": "#123456"},
        }}
        theaters._attach_auditorium_screen_profile(layout, "INOX Varun Beach", "Screen 5")
        self.assertEqual(layout["reference_profile"]["architecture"]["seat_color"], "#123456")
        self.assertTrue(layout["reference_profile"]["administrator_edited"])

    def test_duplicate_seat_ids_across_price_classes_are_rejected(self):
        layout = {"classes": [
            {"code": "A", "rows": [{"label": "A", "count": 5}]},
            {"code": "B", "rows": [{"label": "A", "count": 5}]},
        ]}
        self.assertTrue(any("repeated" in msg for msg in sl.validate_auditorium_geometry(layout)))

    def test_invalid_physical_measurements_are_rejected(self):
        layout = make_layout(1, 5)
        layout["room"] = {"width_m": -3}
        self.assertTrue(any("positive measurement" in msg for msg in sl.validate_auditorium_geometry(layout)))

    def test_conflicting_room_dimensions_expand_with_clear_warning(self):
        layout = make_layout(8, 10)
        layout["room"] = {"width_m": 4, "depth_m": 5, "height_m": 4}
        geometry = self.geometry(layout)
        self.assertGreaterEqual(geometry["room"]["width"], geometry["screen"]["width"] + 2)
        self.assertGreater(geometry["room"]["depth"], max(row["z"] for row in geometry["rows"]))
        self.assertGreater(geometry["room"]["height"], geometry["screen"]["height"])
        self.assertGreaterEqual(len(geometry["warnings"]), 3)


if __name__ == "__main__":
    unittest.main()
