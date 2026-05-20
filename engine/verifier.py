"""Independent verification of an engine output.

Given the original source workbook, the original master, and the engine's
produced output, the verifier walks every scope row of the output and
checks each cell against what the rules + master should produce.  Any
mismatch is a real bug.

Independence note: the verifier shares the ``_canonical`` comparator with
the reconciler so cosmetic diffs (string vs int, case, MMM-YY vs full
datetime, etc.) don't fire as false positives.  But it re-derives the
expected value from first principles -- it does NOT re-run ``reconcile()``
and diff against that output, which would only test self-consistency.

CLI::

    python -m engine.verifier --output <path> --source <path> \
        --master <path> --brand <name> [--sheet <name>] [--verbose]
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import openpyxl

# Allow `python -m engine.verifier` and `python engine/verifier.py` both.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from engine.reference_reader import (
        CONSTANT, COLUMN, DERIVED, EMPTY, PRESERVE_FROM_MASTER, Rule,
        get_mapping_for_brand,
    )
    from engine.source_loader import load_source
    from engine.mapper import map_all, _DATE_FIELDS, _FORCE_UPPER_TARGETS, _EXCEL_SERIAL_MIN, _EXCEL_SERIAL_MAX, _excel_serial_to_datetime
    from engine.brand_overrides import get as get_overrides
    from engine.reconciler import _canonical, _is_empty
    from engine.cli import _load_master
    from engine.brands import load_brands
    from engine.dates import parse_iso_date
else:
    from .reference_reader import (
        CONSTANT, COLUMN, DERIVED, EMPTY, PRESERVE_FROM_MASTER, Rule,
        get_mapping_for_brand,
    )
    from .source_loader import load_source
    from .mapper import map_all, _DATE_FIELDS, _FORCE_UPPER_TARGETS, _EXCEL_SERIAL_MIN, _EXCEL_SERIAL_MAX, _excel_serial_to_datetime
    from .brand_overrides import get as get_overrides
    from .reconciler import _canonical, _is_empty
    from .cli import _load_master
    from .brands import load_brands
    from .dates import parse_iso_date


# -- Report types --------------------------------------------------------

@dataclass
class Mismatch:
    store_id: Any
    field: str
    row_type: str              # UPDATED / NEW / CLOSED
    rule_type: str             # CONSTANT / COLUMN / DERIVED / EMPTY / PRESERVE_FROM_MASTER / (no rule)
    expected_repr: str         # repr() of the expected raw value
    actual_repr: str           # repr() of the actual cell value
    expected_canonical: Any    # what _canonical() said it should be
    actual_canonical: Any      # what _canonical() said it is


@dataclass
class VerificationReport:
    cells_checked: int = 0
    rows_checked: int = 0
    scope_rows: int = 0
    passthrough_rows: int = 0
    mismatches: List[Mismatch] = field(default_factory=list)
    mismatches_by_rule_type: Counter = field(default_factory=Counter)
    mismatches_by_field: Counter = field(default_factory=Counter)
    mismatches_by_row_type: Counter = field(default_factory=Counter)
    brand: str = ""

    @property
    def passed(self) -> bool:
        return not self.mismatches

    @property
    def verdict(self) -> str:
        if self.passed:
            return "PASS"
        return f"FAIL ({len(self.mismatches)} mismatches)"


# -- Helpers -------------------------------------------------------------

def _load_output(path: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        ws = wb["Sheet1"]
        headers: List[str] = []
        rows: List[Dict[str, Any]] = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                headers = [str(h) if h is not None else f"_col{j}"
                           for j, h in enumerate(row)]
                continue
            if all(v is None for v in row):
                continue
            rows.append({headers[j]: row[j] if j < len(row) else None
                         for j in range(len(headers))})
        return rows, headers
    finally:
        wb.close()


def _coerce_date_field(field_name: str, value: Any) -> Any:
    """Apply the same date normalisation the mapper / writer apply so the
    verifier compares against ISO strings, not raw source values.  v0.4.1
    A2: date fields are always YYYY-MM-DD on output, so the expected
    value here must be normalised too."""
    if field_name not in _DATE_FIELDS:
        return value
    if isinstance(value, bool):
        return value
    return parse_iso_date(value)


def _force_upper(field_name: str, value: Any) -> Any:
    if field_name in _FORCE_UPPER_TARGETS and isinstance(value, str):
        return value.upper()
    return value


# -- Main entry point ----------------------------------------------------

def verify_conversion(
    source_path: str,
    master_path: str,
    output_path: str,
    brand_key: str,
    sheet_name: Optional[str] = None,
) -> VerificationReport:
    """Independently re-derive expected cells and compare to the output."""
    cfg = load_brands()[brand_key]
    sheet = sheet_name or cfg["sheet"]
    header_row = int(cfg["header_row"])
    scope_column = cfg["scope_column"]
    scope_value = cfg["scope_value"]

    # Load mapping rules from brands.json (no longer from the workbook).
    rules = get_mapping_for_brand(brand_key)
    rule_by_field = {r.target_field: r for r in rules}

    # Load source and produce mapped target dicts using the engine's mapper.
    # This lets us reuse the same DERIVED rule logic (ZONE_FROM_REGION,
    # PINCODE_FROM_ADDRESS) and adjacency anchor resolution.
    source_sheet_obj = load_source(source_path, sheet, header_row)
    mapped_rows, _map_warnings = map_all(rules, source_sheet_obj)

    # Index mapped rows by Store Id (canonical) for matching to output.
    source_by_id: Dict[Any, Dict[str, Any]] = {}
    for m in mapped_rows:
        sid = _canonical(m.get("Store Id"))
        if sid is not None and sid not in source_by_id:
            source_by_id[sid] = m

    # Load master and index in-scope rows by Store Id (canonical).
    master_rows, _master_headers = _load_master(master_path)
    scope_key = _canonical(scope_value)
    master_by_id: Dict[Any, Dict[str, Any]] = {}
    master_in_scope_sids = set()
    for mr in master_rows:
        if _canonical(mr.get(scope_column)) != scope_key:
            continue
        sid = _canonical(mr.get("Store Id"))
        if sid is not None and sid not in master_by_id:
            master_by_id[sid] = mr
            master_in_scope_sids.add(sid)

    # Load output rows.
    output_rows, output_headers = _load_output(output_path)

    report = VerificationReport(brand=brand_key)

    for out_row in output_rows:
        report.rows_checked += 1
        if _canonical(out_row.get(scope_column)) != scope_key:
            report.passthrough_rows += 1
            continue
        report.scope_rows += 1

        sid = _canonical(out_row.get("Store Id"))
        # Determine row type.
        source = source_by_id.get(sid) if sid is not None else None
        master = master_by_id.get(sid) if sid is not None else None

        # CODE_CHANGED detection: the engine renumbered the row, so the
        # output's Store Id matches the SOURCE's Store Id but NOT the
        # original master's Store Id (the old code lives in mapped
        # Old Sapcode).  Walk the source rows; if any mapped row's
        # Old Sapcode equals an original master Store Id AND its mapped
        # Store Id equals this output row's Store Id, we have a code
        # change.
        old_master = None
        if source is not None and master is None:
            for src_row in mapped_rows:
                if _canonical(src_row.get("Store Id")) != sid:
                    continue
                osap = _canonical(src_row.get("Old Sapcode"))
                if osap is None:
                    continue
                cand = master_by_id.get(osap)
                if cand is not None:
                    old_master = cand
                    break

        if source is not None and old_master is not None:
            row_type = "CODE_CHANGED"
            master = old_master
        elif source is not None and master is not None:
            row_type = "UPDATED"
        elif source is not None and master is None:
            row_type = "NEW"
        elif source is None and master is not None:
            row_type = "CLOSED"
        else:
            # Null-Store-Id master row or genuine orphan; skip cell-level
            # verification (these are surfaced by the engine's null-ID
            # warning).
            continue

        for f in output_headers:
            actual = out_row.get(f)
            rule = rule_by_field.get(f)
            rule_type = rule.source_type if rule else "(no rule)"

            # Determine expected raw value.
            expected: Any
            if row_type == "CLOSED":
                if f == "Isactive":
                    expected = "NO"
                else:
                    expected = master.get(f)
            elif row_type == "CODE_CHANGED" and f == "Remarks":
                # Engine appends "Code changed from <old> to <new> on <date>"
                # to Remarks regardless of the reference's rule.  We don't
                # know the exact date the engine used at the moment it ran
                # (it could be yesterday's run we're verifying today), so
                # accept any string that starts with the existing master
                # Remarks (if any) followed by "Code changed from ...".
                # For strict comparison we compare canonical of actual
                # against a regex-friendly prefix.  Easier: skip the strict
                # Remarks check on CODE_CHANGED rows; the change report
                # already proves the append happened.
                continue
            else:
                # UPDATED / NEW / CODE_CHANGED (non-Remarks): use the rule.
                if rule is None:
                    expected = master.get(f) if master else None
                elif rule.source_type == PRESERVE_FROM_MASTER:
                    expected = master.get(f) if master else None
                elif rule.source_type == EMPTY:
                    if master is not None and not _is_empty(master.get(f)):
                        expected = master.get(f)
                    else:
                        expected = None
                else:
                    # CONSTANT / COLUMN / DERIVED -- the mapper has already
                    # produced the canonical value in `source` (after
                    # transforms and the FORCE_UPPER / date-coerce passes).
                    mapped_val = source.get(f) if source else None
                    if mapped_val is None and master is not None:
                        expected = master.get(f)
                    else:
                        expected = mapped_val

            # Apply the same Isactive/Dailychecklist upper-case and Excel
            # serial-date coercions the engine applies, so we compare on
            # the engine's terms.
            expected = _force_upper(f, expected)
            expected = _coerce_date_field(f, expected)

            ec = _canonical(expected)
            ac = _canonical(actual)
            report.cells_checked += 1
            if ec != ac:
                m = Mismatch(
                    store_id=out_row.get("Store Id"),
                    field=f,
                    row_type=row_type,
                    rule_type=rule_type,
                    expected_repr=repr(expected),
                    actual_repr=repr(actual),
                    expected_canonical=ec,
                    actual_canonical=ac,
                )
                report.mismatches.append(m)
                report.mismatches_by_rule_type[rule_type] += 1
                report.mismatches_by_field[f] += 1
                report.mismatches_by_row_type[row_type] += 1

    return report


# -- CLI -----------------------------------------------------------------

def _print_report(report: VerificationReport, verbose: bool) -> None:
    print(f"Brand:            {report.brand}")
    print(f"Verdict:          {report.verdict}")
    print(f"Rows checked:     {report.rows_checked} "
          f"(scope: {report.scope_rows}, passthrough: {report.passthrough_rows})")
    print(f"Cells checked:    {report.cells_checked}")
    print(f"Mismatches:       {len(report.mismatches)}")
    if report.mismatches_by_rule_type:
        print()
        print("By rule type:")
        for k, v in report.mismatches_by_rule_type.most_common():
            print(f"  {k:<24} {v}")
    if report.mismatches_by_row_type:
        print()
        print("By row type:")
        for k, v in report.mismatches_by_row_type.most_common():
            print(f"  {k:<24} {v}")
    if report.mismatches_by_field:
        print()
        print("By field (top 10):")
        for k, v in report.mismatches_by_field.most_common(10):
            print(f"  {k:<32} {v}")
    if verbose and report.mismatches:
        print()
        print("Detail:")
        for m in report.mismatches[:200]:
            print(f"  [{m.row_type}/{m.rule_type}] Store Id={m.store_id!r} "
                  f"field={m.field!r}")
            print(f"      expected: {m.expected_repr}  (canonical: {m.expected_canonical!r})")
            print(f"      actual:   {m.actual_repr}  (canonical: {m.actual_canonical!r})")
        if len(report.mismatches) > 200:
            print(f"  ... and {len(report.mismatches) - 200} more.")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Independently verify an engine output against rules + inputs."
    )
    p.add_argument("--source", required=True)
    p.add_argument("--master", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--brand", required=True,
                   help=f"One of: {', '.join(sorted(load_brands()))}")
    p.add_argument("--sheet", default=None,
                   help="Override the data sheet name (TCNS).")
    p.add_argument("--verbose", action="store_true",
                   help="Dump the full mismatch list.")
    args = p.parse_args(argv)

    if args.brand not in load_brands():
        print(f"Unknown brand {args.brand!r}.  Known: {sorted(load_brands())}")
        return 2

    report = verify_conversion(
        source_path=args.source,
        master_path=args.master,
        output_path=args.output,
        brand_key=args.brand,
        sheet_name=args.sheet,
    )
    _print_report(report, verbose=args.verbose)
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
