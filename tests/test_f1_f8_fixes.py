"""Unit tests for v0.5.1 fixes F1..F8.

These tests don't require the TASVA fixture - they exercise pure
functions in the engine.  For an end-to-end test against the fixture
see ``tests/test_tasva_fixture.py`` (skipped when fixture missing).
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class F1IsactiveDailySweepTests(unittest.TestCase):
    """F1: Isactive and Dailychecklist access must always match."""

    def setUp(self):
        from engine.reconciler import apply_isactive_daily_sweep
        self.sweep = apply_isactive_daily_sweep

    def test_12026_legacy_case_NO_YES(self):
        rows = [{"brand": "Tasva", "Store Id": 12026,
                 "Isactive": "NO", "Dailychecklist access": "YES"}]
        warns = []
        fixes = self.sweep(rows, "brand", "Tasva", warns)
        self.assertEqual(len(fixes), 1)
        self.assertEqual(rows[0]["Dailychecklist access"], "NO")
        self.assertTrue(warns)

    def test_already_matching_no_change(self):
        rows = [{"brand": "Tasva", "Store Id": 1,
                 "Isactive": "YES", "Dailychecklist access": "YES"}]
        warns = []
        fixes = self.sweep(rows, "brand", "Tasva", warns)
        self.assertEqual(fixes, [])

    def test_out_of_scope_untouched(self):
        rows = [{"brand": "Pantaloons", "Store Id": 9,
                 "Isactive": "YES", "Dailychecklist access": "NO"}]
        warns = []
        self.sweep(rows, "brand", "Tasva", warns)
        self.assertEqual(rows[0]["Dailychecklist access"], "NO")


class F3RegionUpperTests(unittest.TestCase):
    """F3: Region must be ALL CAPS regardless of input casing."""

    def test_force_upper_targets_includes_region(self):
        from engine.mapper import _FORCE_UPPER_TARGETS
        self.assertIn("Region", _FORCE_UPPER_TARGETS)
        self.assertIn("Isactive", _FORCE_UPPER_TARGETS)
        self.assertIn("Dailychecklist access", _FORCE_UPPER_TARGETS)


class F4StoreZoneTests(unittest.TestCase):
    """F4: Store Zone must be 4 capital letters per Region."""

    def test_zone_from_region(self):
        from engine.mapper import zone_from_region
        self.assertEqual(zone_from_region("South"), "SOUT")
        self.assertEqual(zone_from_region("SOUTH"), "SOUT")
        self.assertEqual(zone_from_region("south"), "SOUT")
        self.assertEqual(zone_from_region("North"), "NRTH")
        self.assertEqual(zone_from_region("NORTH"), "NRTH")
        self.assertEqual(zone_from_region("East"), "EAST")
        self.assertEqual(zone_from_region("West"), "WEST")
        self.assertEqual(zone_from_region("WEST"), "WEST")

    def test_all_zones_are_4_caps(self):
        from engine.mapper import _ZONE_PREFIX
        for v in _ZONE_PREFIX.values():
            self.assertEqual(len(v), 4, f"{v} not 4 chars")
            self.assertTrue(v.isupper(), f"{v} not upper")
            self.assertTrue(v.isalpha(), f"{v} not alpha")


class F5TitleMirrorTests(unittest.TestCase):
    """F5: Title mirrors Store Id on every engine-written row."""

    def test_title_sweep_replaces_placeholder(self):
        from engine.reconciler import apply_title_mirror_sweep
        rows = [
            {"brand": "Tasva", "Store Id": 11001, "Title": "title"},
            {"brand": "Tasva", "Store Id": 11002, "Title": None},
            {"brand": "Pantaloons", "Store Id": 9, "Title": "title"},
        ]
        fixes = apply_title_mirror_sweep(rows, "brand", "Tasva")
        self.assertEqual(len(fixes), 2)
        self.assertEqual(rows[0]["Title"], 11001)
        self.assertEqual(rows[1]["Title"], 11002)
        self.assertEqual(rows[2]["Title"], "title")  # out of scope


class F6IdPreserveTests(unittest.TestCase):
    """F6: ID column is preserved across all paths."""

    def test_master_fields_has_id_at_pos_1(self):
        from engine.brands import MASTER_FIELDS
        # 44 core columns + 3 engine-derived status columns (45-47).
        self.assertEqual(len(MASTER_FIELDS), 47)
        self.assertEqual(MASTER_FIELDS[0], "ID")
        self.assertEqual(MASTER_FIELDS[43], "Title")
        self.assertEqual(MASTER_FIELDS[-3:],
                         ["Data Modified", "Deactivated Stores", "Reactivated Stores"])

    def test_engine_preserve_in_valid_source_types(self):
        from engine.brands import VALID_SOURCE_TYPES
        self.assertIn("ENGINE_PRESERVE", VALID_SOURCE_TYPES)


class F2TasvaBusinessTests(unittest.TestCase):
    """F2: TASVA Business must be 'Ethnic Business'."""

    def test_brands_json_tasva_business_ethnic_business(self):
        from engine.brands import load_brands
        brands = load_brands()
        self.assertIn("Tasva", brands)
        tasva = brands["Tasva"]
        biz_rule = next((r for r in tasva["mapping"]
                         if r.get("target") == "Business"), None)
        self.assertIsNotNone(biz_rule)
        self.assertEqual(biz_rule["source_type"], "CONSTANT")
        self.assertEqual(biz_rule["source_value"], "Ethnic Business")


class SchemaTests(unittest.TestCase):
    """Phase 2 schema checks."""

    def test_all_brands_have_id_and_title(self):
        from engine.brands import load_brands
        brands = load_brands()
        for key, b in brands.items():
            targets = [r.get("target") for r in b["mapping"]]
            self.assertIn("ID", targets, f"{key} missing ID rule")
            self.assertIn("Title", targets, f"{key} missing Title rule")
            self.assertEqual(targets[0], "ID", f"{key} ID not first")
            self.assertEqual(targets[-1], "Title", f"{key} Title not last")

    def test_all_brands_region_upper_transform(self):
        from engine.brands import load_brands
        brands = load_brands()
        for key, b in brands.items():
            reg = next((r for r in b["mapping"]
                        if r.get("target") == "Region"), None)
            if reg and reg.get("source_type") == "COLUMN":
                self.assertEqual(reg.get("transform"), "upper",
                                 f"{key} Region missing upper transform")


if __name__ == "__main__":
    unittest.main()
