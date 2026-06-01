"""Tests for the 3 engine-derived status columns (operator's request):

    Data Modified       -- "New" / "Yes" / "No" for this run.
    Deactivated Stores  -- standing: "YES" while inactive.
    Reactivated Stores  -- standing: "YES" after a reopen, persisted.
"""
from __future__ import annotations

import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.reconciler import (
    reconcile, apply_inactivation_pass, apply_status_columns,
)
from engine.reference_reader import get_mapping_for_brand
from engine.brands import MASTER_FIELDS, STATUS_COLUMNS

DATA_MOD, DEACT, REACT = STATUS_COLUMNS


def _master(**kw):
    r = {f: None for f in MASTER_FIELDS if f not in STATUS_COLUMNS}
    r.update(kw)
    return r


def _run(master, mapped):
    rules = get_mapping_for_brand("PF")
    # Simulate a legacy 44-column master (no status columns yet).
    mfo = [f for f in MASTER_FIELDS if f not in STATUS_COLUMNS]
    res = reconcile(rules=rules, mapped_rows=mapped, master_rows=master,
                    master_field_order=mfo, scope_column="brand",
                    scope_value="PF", month_label="May-2026")
    apply_inactivation_pass(result=res, brand_label="Planet Fashion",
                            brand_label_short="PF", month_label="May-2026")
    apply_status_columns(res, mfo, scope_column="brand", scope_value="PF")
    return res, mfo


class ColumnAppendTests(unittest.TestCase):
    def test_columns_appended_to_field_order(self):
        _, mfo = _run([], [])
        self.assertEqual(mfo[-3:], list(STATUS_COLUMNS))


class NewStoreTests(unittest.TestCase):
    def test_new_store_flags(self):
        mapped = [{"brand": "PF", "Store Id": 900, "Region": "South",
                   "Store Email Id": "a@abfrl.adityabirla.com"}]
        res, _ = _run([], mapped)
        row = res.updated_master[-1]
        self.assertEqual(row["Store Id"], 900)
        self.assertEqual(row[DATA_MOD], "New")
        self.assertEqual(row[DEACT], "NO")
        self.assertEqual(row[REACT], "NO")


class ReactivationTests(unittest.TestCase):
    def test_reactivated_store_flags(self):
        master = [_master(brand="PF", **{"Store Id": 500, "Isactive": "NO",
                  "Dailychecklist access": "NO", "Region": "South",
                  "Store Email Id": "b@abfrl.adityabirla.com"})]
        mapped = [{"brand": "PF", "Store Id": 500, "Isactive": "YES",
                   "Dailychecklist access": "YES", "Region": "South",
                   "Store Email Id": "b@abfrl.adityabirla.com"}]
        res, _ = _run(master, mapped)
        row = res.updated_master[0]
        self.assertEqual(row[REACT], "YES")
        self.assertEqual(row[DEACT], "NO")
        self.assertEqual(row[DATA_MOD], "Yes")


class DeactivationTests(unittest.TestCase):
    def test_store_missing_from_source_is_deactivated(self):
        master = [_master(brand="PF", **{"Store Id": 600, "Isactive": "YES",
                  "Dailychecklist access": "YES", "Region": "West",
                  "Store Email Id": "c@abfrl.adityabirla.com"})]
        res, _ = _run(master, [])   # store not present in source -> closed
        row = res.updated_master[0]
        self.assertEqual(row[DEACT], "YES")
        self.assertEqual(row[REACT], "NO")
        self.assertEqual(row[DATA_MOD], "Yes")


class StandingInactiveTests(unittest.TestCase):
    def test_long_inactive_untouched_is_yes_deactivated(self):
        # Already inactive, present in source as still-inactive (no change).
        master = [_master(brand="PF", **{"Store Id": 700, "Isactive": "NO",
                  "Dailychecklist access": "NO", "Region": "East",
                  "Store Email Id": "d@abfrl.adityabirla.com"})]
        # Not in this month's source at all -> stays inactive, untouched.
        res, _ = _run(master, [])
        row = res.updated_master[0]
        # Standing state: currently inactive -> Deactivated = YES.
        self.assertEqual(row[DEACT], "YES")
        self.assertEqual(row[REACT], "NO")
        # No field changed this run.
        self.assertEqual(row[DATA_MOD], "No")


class ReactivatedPersistTests(unittest.TestCase):
    def test_reactivated_persists_when_untouched(self):
        # Active store, previously reactivated (Reactivated=YES carried in
        # the master), matched this run with no changes -> stays YES.
        master = [_master(brand="PF", **{"Store Id": 800, "Isactive": "YES",
                  "Dailychecklist access": "YES", "Region": "South",
                  "Store Email Id": "e@abfrl.adityabirla.com"})]
        master[0]["Reactivated Stores"] = "YES"
        mapped = [{"brand": "PF", "Store Id": 800, "Isactive": "YES",
                   "Dailychecklist access": "YES", "Region": "South",
                   "Store Email Id": "e@abfrl.adityabirla.com"}]
        res, _ = _run(master, mapped)
        row = res.updated_master[0]
        self.assertEqual(row[REACT], "YES")   # persisted
        self.assertEqual(row[DEACT], "NO")
        self.assertEqual(row[DATA_MOD], "No")  # nothing changed this run


if __name__ == "__main__":
    unittest.main()
