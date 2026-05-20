"""Unit + light-integration tests for the v0.5.2 per-row sheet picker.

What this file covers:
  - brands.json: every brand entry has sheet_overridable=true and a
    default_sheet matching the v0.5.2 defaults table.
  - _backend block is loaded by load_backend_config() and exposes
    default_sheet "Backend Updated Data".
  - engine.brands.load_brands() filters out underscore-prefixed keys
    (so _backend never shows up as a brand).
  - engine.source_loader.list_sheets() + sheet_has_data() do what they
    say on a synthesized xlsx workbook with two sheets, one empty.
  - engine.cli._load_master() accepts a sheet override and raises with
    a clear "Available: ..." message when the sheet is missing.
  - End-to-end byte-for-byte sanity (acceptance criterion #5): a master
    workbook with the data on a non-default sheet, loaded via the
    override, produces the same row dicts as the same data on Sheet1
    loaded via the default.

Real-fixture run (acceptance criterion #4) is gated behind the presence
of the TASVA + Backend Master xlsx/xlsb files under ``fixtures/``, since
those aren't committed.  When absent, the byte-identical comparison
falls back to the synthesized data above; the override code path is
still exercised either way.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _write_two_sheet_xlsx(path: str,
                          data_sheet: str = "Backend Updated Data",
                          extra_sheet: str = "Reference") -> None:
    """Write a tiny two-sheet xlsx: data sheet has 1 header row + 2
    data rows; the extra sheet is intentionally empty (just headers).
    Used for both the source-loader probes and _load_master tests."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = data_sheet
    ws.append(["ID", "Store Id", "Title", "brand"])
    ws.append([1, "S001", "S001", "Pantaloons"])
    ws.append([2, "S002", "S002", "Pantaloons"])
    ws2 = wb.create_sheet(extra_sheet)
    ws2.append(["note"])   # header only, no data row
    wb.save(path)


class BrandsJsonSchemaTests(unittest.TestCase):
    """v0.5.2 acceptance: every brand has sheet_overridable=true with
    the documented defaults."""

    DEFAULTS = {
        "Pantaloons": "Sheet1",
        "PF": "PF Active Stores",
        "Tasva": "Contact Master",
        "TCNS": "Mar",          # whatever cfg.default_sheet was; not the picker default
    }

    def setUp(self):
        from engine.brands import load_brands
        self.brands = load_brands()

    def test_all_brands_sheet_overridable_true(self):
        for key, cfg in self.brands.items():
            self.assertTrue(cfg["sheet_overridable"],
                            f"{key} should be sheet_overridable=true in v0.5.2")

    def test_defaults_table_present(self):
        for key, default in self.DEFAULTS.items():
            if key not in self.brands:
                # TCNS default may be edited month-to-month; skip its exact match
                if key == "TCNS":
                    continue
                self.fail(f"{key} missing from brands.json")
            self.assertEqual(self.brands[key]["default_sheet"], default,
                             f"{key} default_sheet mismatch")

    def test_underscore_keys_filtered_from_load_brands(self):
        """_backend (and any other future _-prefixed keys) must not
        leak into load_brands()."""
        for key in self.brands.keys():
            self.assertFalse(key.startswith("_"),
                             f"{key!r} leaked through load_brands()")


class BackendConfigTests(unittest.TestCase):
    """v0.5.2 acceptance: the _backend block loads with a sensible
    default sheet name."""

    def test_default_sheet_is_backend_updated_data(self):
        from engine.brands import load_backend_config
        cfg = load_backend_config()
        self.assertEqual(cfg["default_sheet"], "Backend Updated Data")

    def test_returns_dict_even_when_key_absent(self):
        """load_backend_config() never raises and always provides a
        default, even if someone hand-edits _backend out of brands.json."""
        from engine.brands import load_backend_config
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "brands.json"
            p.write_text(json.dumps({"Pantaloons": {}}), encoding="utf-8")
            cfg = load_backend_config(p)
            self.assertEqual(cfg["default_sheet"], "Backend Updated Data")


class SourceLoaderProbesTests(unittest.TestCase):
    """list_sheets() and sheet_has_data() must be fast, side-effect-free
    probes the validation endpoint can call onBlur."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.td.name, "two_sheet.xlsx")
        _write_two_sheet_xlsx(self.path)

    def tearDown(self):
        self.td.cleanup()

    def test_list_sheets_returns_both(self):
        from engine.source_loader import list_sheets
        sheets = list_sheets(self.path)
        self.assertIn("Backend Updated Data", sheets)
        self.assertIn("Reference", sheets)

    def test_sheet_has_data_true_for_data_sheet(self):
        from engine.source_loader import sheet_has_data
        self.assertTrue(sheet_has_data(self.path, "Backend Updated Data", 1))

    def test_sheet_has_data_false_for_empty_sheet(self):
        from engine.source_loader import sheet_has_data
        self.assertFalse(sheet_has_data(self.path, "Reference", 1))

    def test_sheet_has_data_false_for_missing_sheet(self):
        from engine.source_loader import sheet_has_data
        self.assertFalse(sheet_has_data(self.path, "Nope", 1))


class LoadMasterOverrideTests(unittest.TestCase):
    """_load_master accepts a sheet override and produces the same
    row dicts as if the data had been on the default Sheet1 -- this
    is the engine-side half of acceptance criterion #5."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.master_override = os.path.join(self.td.name, "master_override.xlsx")
        self.master_default = os.path.join(self.td.name, "master_default.xlsx")
        # Same data, two sheet layouts:
        #   override case -> sheet is "Backend Updated Data" + a sibling "Reference"
        #   default case  -> sheet is "Sheet1" (no override needed)
        _write_two_sheet_xlsx(self.master_override,
                              data_sheet="Backend Updated Data",
                              extra_sheet="Reference")
        _write_two_sheet_xlsx(self.master_default,
                              data_sheet="Sheet1",
                              extra_sheet="Notes")

    def tearDown(self):
        self.td.cleanup()

    def test_override_yields_same_rows_as_default(self):
        from engine.cli import _load_master
        rows_a, fields_a = _load_master(self.master_override, "Backend Updated Data")
        rows_b, fields_b = _load_master(self.master_default)   # default Sheet1
        self.assertEqual(fields_a, fields_b)
        self.assertEqual(rows_a, rows_b)

    def test_missing_sheet_raises_with_available_list(self):
        from engine.cli import _load_master
        with self.assertRaises(ValueError) as cm:
            _load_master(self.master_override, "Contact Maste")
        msg = str(cm.exception)
        self.assertIn("Contact Maste", msg)
        self.assertIn("Backend Updated Data", msg)
        self.assertIn("Reference", msg)


class FixtureSmokeTest(unittest.TestCase):
    """Acceptance criterion #4: real end-to-end with the documented
    fixtures, when present.  Skipped otherwise so CI on a clean checkout
    still passes."""

    FIXTURES_DIR = Path(ROOT) / "fixtures"
    TASVA_FIX = FIXTURES_DIR / "TASVA_Stores_-_April_26.xlsb"
    BACKEND_FIX = FIXTURES_DIR / "Backend_Updated_Data_with_ID.xlsx"

    def setUp(self):
        if not (self.TASVA_FIX.exists() and self.BACKEND_FIX.exists()):
            self.skipTest(
                f"v0.5.2 fixtures not present at {self.FIXTURES_DIR}; "
                "skipping end-to-end run. The synthesized tests above "
                "still exercise the override code paths."
            )

    def test_tasva_plus_backend_runs_with_overrides(self):
        from engine.cli import _load_master
        from engine.source_loader import load_source

        master_rows, fields = _load_master(str(self.BACKEND_FIX),
                                           "Backend Updated Data")
        self.assertGreater(len(master_rows), 0)
        self.assertIn("Store Id", fields)

        tasva = load_source(str(self.TASVA_FIX), "Contact Master", 2)
        self.assertGreater(len(tasva.rows), 0)


if __name__ == "__main__":
    unittest.main()
