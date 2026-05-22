"""Regression tests for two issue-log bugs:

  * Store 12001 — deactivate-to-active did not update Remarks when the
    inactive state was stored as anything other than the literal "NO".
  * Store 67890 — a migration whose source carried the previous code
    (PF "Old SAP" column) was misclassified as a brand-new store.
"""
from __future__ import annotations

import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.reconciler import reconcile, _is_active, apply_isactive_daily_sweep
from engine.reference_reader import get_mapping_for_brand
from engine.brands import MASTER_FIELDS


def _master(**kw):
    r = {f: None for f in MASTER_FIELDS}
    r.update(kw)
    return r


class IsActiveTokenTests(unittest.TestCase):
    def test_inactive_spellings(self):
        for v in ["NO", "No", "no", "N", "false", "False", "Inactive",
                  "inactive", 0, "0", False]:
            self.assertFalse(_is_active(v), f"{v!r} should be inactive")

    def test_active_values(self):
        for v in ["YES", "Yes", "y", 1, True, "Active"]:
            self.assertTrue(_is_active(v), f"{v!r} should be active")

    def test_blank_defaults_active(self):
        # Legacy contract: blank/None Isactive is treated as active.
        self.assertTrue(_is_active(None))
        self.assertTrue(_is_active(""))


class IsactiveNormalizationSweepTests(unittest.TestCase):
    def test_legacy_inactive_normalized_to_NO(self):
        rows = [_master(brand="PF", **{"Store Id": 555,
                "Isactive": "Inactive", "Dailychecklist access": "Inactive"})]
        warns = []
        fixes = apply_isactive_daily_sweep(rows, "brand", "PF", warns)
        self.assertEqual(rows[0]["Isactive"], "NO")
        self.assertEqual(rows[0]["Dailychecklist access"], "NO")
        self.assertTrue(any(f.field_changed == "Isactive" for f in fixes))


class ReactivationRemarkTests(unittest.TestCase):
    def _run(self, stored_inactive):
        rules = get_mapping_for_brand("PF")
        master = [_master(brand="PF", **{
            "Store Id": 12001, "Isactive": stored_inactive,
            "Dailychecklist access": stored_inactive,
            "Remarks": "Store ID not present...Marked as Inactive.",
            "Store Email Id": "x@abfrl.adityabirla.com", "Region": "South"})]
        mapped = [{"brand": "PF", "Store Id": 12001, "Isactive": "YES",
                   "Dailychecklist access": "YES",
                   "Store Email Id": "x@abfrl.adityabirla.com", "Region": "South"}]
        return reconcile(rules=rules, mapped_rows=mapped, master_rows=master,
                         master_field_order=MASTER_FIELDS, scope_column="brand",
                         scope_value="PF", month_label="May-2026")

    def test_reactivation_updates_remark_for_NO(self):
        res = self._run("NO")
        self.assertEqual(res.summary["REACTIVATED"], 1)
        self.assertEqual(res.updated_master[0]["Remarks"], "Reactivated on May 2026")

    def test_reactivation_updates_remark_for_Inactive(self):
        # The bug: previously classified as UPDATED, remark left stale.
        res = self._run("Inactive")
        self.assertEqual(res.summary["REACTIVATED"], 1)
        row = res.updated_master[0]
        self.assertEqual(row["Remarks"], "Reactivated on May 2026")
        self.assertEqual(row["Isactive"], "YES")
        self.assertEqual(row["Dailychecklist access"], "YES")


class MigrationFromSourceOldCodeTests(unittest.TestCase):
    def test_migration_not_created_as_new(self):
        rules = get_mapping_for_brand("PF")
        master = [_master(brand="PF", **{
            "Store Id": 11002, "Isactive": "NO", "Dailychecklist access": "NO",
            "Remarks": "inactive", "Store Email Id": "y@abfrl.adityabirla.com",
            "Region": "West", "Old Sapcode": None})]
        mapped = [{"brand": "PF", "Store Id": 67890, "Old Sapcode": 11002,
                   "Isactive": "YES", "Dailychecklist access": "YES",
                   "Store Email Id": "y@abfrl.adityabirla.com", "Region": "West"}]
        res = reconcile(rules=rules, mapped_rows=mapped, master_rows=master,
                        master_field_order=MASTER_FIELDS, scope_column="brand",
                        scope_value="PF", month_label="May-2026")
        self.assertEqual(res.summary["NEW"], 0, "must not create a new store")
        self.assertEqual(res.summary["CODE_CHANGED"], 1)
        self.assertEqual(len(res.updated_master), 1, "no duplicate row")
        row = res.updated_master[0]
        self.assertEqual(row["Store Id"], 67890)
        self.assertEqual(row["Isactive"], "YES")
        self.assertEqual(row["Dailychecklist access"], "YES")
        self.assertIn("11002", str(row["Old Sapcode"]))
        self.assertEqual(row["Remarks"], "Migrated from old SAP code 11002 on May 2026")


if __name__ == "__main__":
    unittest.main()
