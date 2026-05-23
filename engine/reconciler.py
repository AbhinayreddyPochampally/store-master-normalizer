"""Merge mapper output with the existing master and categorise each row.

v0.4.1 implements the four-step matching cascade from design doc Section 5
(plus the Section 6 inactivation rules, which run in :func:`apply_inactivation_pass`).

Matching cascade (per source row, brand-partitioned)
----------------------------------------------------
    Step 1 -- REFRESH.   source.StoreId hits any of master.[StoreId,
                         Retek Code, Legacy Code] for the same brand,
                         and that row is active.  Source-mapped fields
                         are overwritten unconditionally.  Existing
                         Remark is preserved.

    Step 2 -- MIGRATED.  source.StoreId hits a comma-split token in
                         master.[Old Sapcode] for the same brand.  Same
                         refresh; the Remark is overwritten with the
                         migration template.

    Step 3 -- REACTIVATED. source.StoreId hits master.[StoreId, Retek
                         Code, Legacy Code] for the same brand, AND
                         that row is inactive (Isactive=NO).  Flip
                         Isactive=YES, refresh source-mapped fields,
                         overwrite Remark with the reactivation
                         template.  Do NOT create a new row.

    Step 4 -- NEW.       Else create a new row with the brand's
                         CONSTANT block applied and Isactive=YES.

Step 5 -- ORPHAN.        Source row whose Store Id collides with a
                         master row in a DIFFERENT brand is flagged as
                         ORPHAN; the master row is left untouched.

Brand partitioning: Steps 1-4 only consider in-scope rows
(``master[scope_column] == scope_value``).  A ``WC36`` row showing up in
a Pantaloons source therefore cannot match a ``WC36`` row in TCNS scope.

Refresh contract (unchanged from v0.4.0 A1):
    Source-mapped fields overwrite the master value *unconditionally*.
    PRESERVE_FROM_MASTER, EMPTY, and rules whose mapped value is None
    are skipped, so curated master values survive in those cases only.

Inactivation rules (Section 6) live in :func:`apply_inactivation_pass`
which the caller invokes after :func:`reconcile` returns.  Splitting it
out lets the inactivation pass also touch rows the cascade refreshed
this run (the email-domain check applies to every active in-scope row,
not just untouched ones).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from .reference_reader import COLUMN, EMPTY, PRESERVE_FROM_MASTER, Rule
from .remarks import build_remark, REMARK_NEW, REMARK_MIGRATED, REMARK_REACTIVATED, REMARK_INACTIVE_MISS, REMARK_INACTIVE_BAD_EMAIL


# Approved email domains (design doc Section 6).  A store's Store Email
# Id domain MUST be in this set or the store is inactivated with the
# bad-email remark.
APPROVED_EMAIL_DOMAINS = frozenset({
    "abfrl.adityabirla.com",
    "ablbl.adityabirla.com",
    "sabyasachi.com",
    "shantanunikhil.com",
    "houseofmasaba.com",
})


@dataclass
class ChangeRecord:
    status: str
    store_id: Any
    field_changed: str
    old_value: Any
    new_value: Any
    notes: str = ""


@dataclass
class ReconcileResult:
    updated_master: List[Dict[str, Any]]
    changes: List[ChangeRecord]
    summary: Dict[str, int]
    warnings: List[str]
    matched_source_count: int = 0
    unmatched_source_count: int = 0
    orphan_source_count: int = 0
    matched_master_rows: set = field(default_factory=set)
    in_scope_indices: List[int] = field(default_factory=list)
    # index -> {'new','changed','reactivated','deactivated': bool} describing
    # what happened to that output row THIS run.  Consumed by
    # apply_status_columns to fill the 3 engine-derived status columns.
    row_run_status: Dict[int, Dict[str, bool]] = field(default_factory=dict)


# -- canonicaliser -------------------------------------------------------

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%m/%d/%y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%b-%y",
    "%b-%Y",
)


def _canonical(v: Any):
    if v is None:
        return None
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, bool):
        return ("bool", bool(v))
    if isinstance(v, (datetime, date)):
        d = v.date() if isinstance(v, datetime) else v
        return ("date", d.isoformat())
    if isinstance(v, (int, float)):
        f = float(v)
        if f.is_integer():
            return ("num", int(f))
        return ("num", f)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            f = float(s.replace(",", ""))
            if f.is_integer():
                return ("num", int(f))
            return ("num", f)
        except ValueError:
            pass
        for fmt in _DATE_FORMATS:
            try:
                d = datetime.strptime(s, fmt).date()
                return ("date", d.isoformat())
            except ValueError:
                continue
        return ("str", s.replace("_", " ").casefold())
    return ("str", str(v).strip().replace("_", " ").casefold())


def _values_equal(a: Any, b: Any) -> bool:
    return _canonical(a) == _canonical(b)


def _is_empty(v: Any) -> bool:
    return _canonical(v) is None


def _match_key(v: Any):
    c = _canonical(v)
    return None if c is None else c


# Tokens that mean "not active".  The design doc (Section 6 / Data
# Quality table) says Isactive is stored as canonical upper-case YES / NO,
# but legacy and source data arrive as several spellings of "no".  We
# recognise all of them so a deactivate-to-active store is correctly seen
# as inactive regardless of how the master happened to store the flag.
_INACTIVE_STR_TOKENS = frozenset({"no", "n", "false", "inactive", "deactivated"})


def _is_active(v: Any) -> bool:
    c = _canonical(v)
    if c is None:
        return True   # untyped/blank -> treat as active (legacy data)
    kind, val = c
    if kind == "str":
        return val not in _INACTIVE_STR_TOKENS
    if kind == "num":
        return val != 0          # 0 -> inactive
    if kind == "bool":
        return val               # False -> inactive
    return True


# -- v0.5.1 (F1): Isactive / Dailychecklist access pre-run sweep --------

def apply_isactive_daily_sweep(master_rows: List[Dict[str, Any]],
                                scope_column: str,
                                scope_value: Any,
                                warnings: List[str]) -> List[ChangeRecord]:
    """One-time sweep at the start of every reconcile.

    For every in-scope master row where ``Isactive`` and
    ``Dailychecklist access`` disagree, set ``Dailychecklist access`` to
    match ``Isactive``.  This is how the legacy 12026-style rows (where
    `Isactive=NO, Dailychecklist access=YES`) get cleaned up.

    Returns a list of ChangeRecord rows for inclusion in the Change
    Report.  Also appends an aggregate warning so the operator sees
    *something* happened, even when the per-row diff is collapsed.
    """
    scope_key = _match_key(scope_value)
    fixes: List[ChangeRecord] = []
    for row in master_rows:
        if _match_key(row.get(scope_column)) != scope_key:
            continue
        ia_raw = row.get("Isactive")
        dc_raw = row.get("Dailychecklist access")
        # Empty rows are ignored -- they have their own remarks rule.
        if _is_empty(ia_raw) and _is_empty(dc_raw):
            continue
        # Canonical YES/NO for the row.  Isactive is the authority; when it
        # is blank we fall back to Dailychecklist access so a half-populated
        # legacy row still resolves to one consistent value.
        if not _is_empty(ia_raw):
            canon = "YES" if _is_active(ia_raw) else "NO"
        else:
            canon = "YES" if _is_active(dc_raw) else "NO"

        # Data Quality table: Isactive is stored as canonical upper-case
        # YES / NO.  Normalise any legacy spelling ("Inactive", "no", ...)
        # in place so downstream cascade + reports see the canonical value.
        if not _is_empty(ia_raw) and str(ia_raw).strip().upper() != canon:
            row["Isactive"] = canon
            fixes.append(ChangeRecord(
                status="FLAG_SWEEP",
                store_id=row.get("Store Id"),
                field_changed="Isactive",
                old_value=ia_raw,
                new_value=canon,
                notes="F1 pre-run sweep: normalized Isactive to canonical YES/NO",
            ))

        # Dailychecklist access must equal Isactive.
        if not _values_equal(dc_raw, canon):
            row["Dailychecklist access"] = canon
            fixes.append(ChangeRecord(
                status="FLAG_SWEEP",
                store_id=row.get("Store Id"),
                field_changed="Dailychecklist access",
                old_value=dc_raw,
                new_value=canon,
                notes="F1 pre-run sweep: forced Daily = Isactive",
            ))
    if fixes:
        warnings.append(
            f"F1 sweep: aligned Dailychecklist access to Isactive on "
            f"{len(fixes)} legacy in-scope row(s)."
        )
    return fixes


# -- v0.5.1 (F5): Title = Store Id on every engine-touched row ----------

def _mirror_title(row: Dict[str, Any]) -> None:
    """Force ``Title`` to mirror ``Store Id`` on the given row."""
    sid = row.get("Store Id")
    if sid is not None:
        row["Title"] = sid


def apply_title_mirror_sweep(master_rows: List[Dict[str, Any]],
                              scope_column: str,
                              scope_value: Any) -> List[ChangeRecord]:
    """One-time sweep: replace every legacy ``Title`` value (often the
    literal string 'title') with the row's ``Store Id``.  Only touches
    in-scope rows."""
    scope_key = _match_key(scope_value)
    fixes: List[ChangeRecord] = []
    for row in master_rows:
        if _match_key(row.get(scope_column)) != scope_key:
            continue
        old = row.get("Title")
        sid = row.get("Store Id")
        if sid is None:
            continue
        if not _values_equal(old, sid):
            row["Title"] = sid
            fixes.append(ChangeRecord(
                status="TITLE_SWEEP",
                store_id=sid,
                field_changed="Title",
                old_value=old,
                new_value=sid,
                notes="F5 pre-run sweep: Title := Store Id",
            ))
    return fixes


# -- helpers -------------------------------------------------------------

def _build_rule_index(rules: List[Rule]) -> Dict[str, Rule]:
    return {r.target_field: r for r in rules}


def _make_empty_master_row(field_order: List[str]) -> Dict[str, Any]:
    return {f: None for f in field_order}


def _split_old_sapcode(v: Any) -> List[str]:
    """Split a master row's Old Sapcode field on commas.  Returns
    stripped, non-empty tokens."""
    if v is None:
        return []
    if isinstance(v, (int, float)):
        # A numeric Old Sapcode is a single token.
        return [str(v).rstrip(".0") if isinstance(v, float) and v.is_integer() else str(v)]
    s = str(v).strip()
    if not s:
        return []
    return [t.strip() for t in s.split(",") if t.strip()]


def _merge_old_sapcode(existing: Any, *new_codes: Any) -> Optional[str]:
    """v4 rule (e): Old Sapcode is an accumulating, comma-separated list.

    New codes are ADDED to the list, never replacing what is already
    there, and duplicates are dropped while preserving order.  Returns a
    comma-separated string, or None when there is nothing to store.
    """
    seen: List[str] = []

    def _add(token: Any) -> None:
        for tok in _split_old_sapcode(token):
            if tok not in seen:
                seen.append(tok)

    _add(existing)
    for code in new_codes:
        _add(code)
    return ", ".join(seen) if seen else None


def _fill_area_fallback(row: Dict[str, Any]) -> None:
    """v4 rule (c): Square feet and Carpet are interchangeable.  If only
    one of the two is present on the row, copy it into the other."""
    sf = row.get("Square feet")
    cp = row.get("Carpet")
    if _is_empty(sf) and not _is_empty(cp):
        row["Square feet"] = cp
    elif _is_empty(cp) and not _is_empty(sf):
        row["Carpet"] = sf


def _index_master(master_rows, scope_column, scope_value):
    """Build all four lookup indices the cascade uses, plus the
    in-scope row list.  All indices are brand-partitioned -- entries
    only come from rows where master[scope_column] == scope_value."""
    scope_key = _match_key(scope_value)
    by_id: Dict[Any, int] = {}
    by_retek: Dict[Any, int] = {}
    by_legacy: Dict[Any, int] = {}
    by_old_sapcode: Dict[Any, int] = {}
    in_scope: List[int] = []
    for i, row in enumerate(master_rows):
        if _match_key(row.get(scope_column)) != scope_key:
            continue
        in_scope.append(i)
        sid = _match_key(row.get("Store Id"))
        if sid is not None and sid not in by_id:
            by_id[sid] = i
        rtk = _match_key(row.get("Retek Code"))
        if rtk is not None and rtk not in by_retek:
            by_retek[rtk] = i
        lcd = _match_key(row.get("Legacy Code"))
        if lcd is not None and lcd not in by_legacy:
            by_legacy[lcd] = i
        for tok in _split_old_sapcode(row.get("Old Sapcode")):
            k = _match_key(tok)
            if k is not None and k not in by_old_sapcode:
                by_old_sapcode[k] = i
    return by_id, by_retek, by_legacy, by_old_sapcode, in_scope


def _full_indices(master_rows):
    """Cross-brand indices used only for ORPHAN detection."""
    full_by_id: Dict[Any, int] = {}
    full_by_legacy: Dict[Any, int] = {}
    for i, row in enumerate(master_rows):
        sid = _match_key(row.get("Store Id"))
        if sid is not None and sid not in full_by_id:
            full_by_id[sid] = i
        lcd = _match_key(row.get("Legacy Code"))
        if lcd is not None and lcd not in full_by_legacy:
            full_by_legacy[lcd] = i
    return full_by_id, full_by_legacy


def _apply_refresh(master_row: Dict[str, Any],
                   mapped: Dict[str, Any],
                   master_field_order: List[str],
                   rule_by_field: Dict[str, Rule],
                   status: str,
                   display_sid: Any,
                   match_key_name: str) -> List[ChangeRecord]:
    """Overwrite source-mapped fields on ``master_row`` from ``mapped``.

    Skips PRESERVE_FROM_MASTER, EMPTY, and rules whose mapped value is
    None.  Returns one ChangeRecord per cell that actually changed.
    """
    out: List[ChangeRecord] = []
    for f in master_field_order:
        rule = rule_by_field.get(f)
        new_val = mapped.get(f)
        old_val = master_row.get(f)

        if rule is None or rule.source_type == PRESERVE_FROM_MASTER:
            continue
        if rule.source_type == EMPTY:
            continue
        if new_val is None:
            continue
        # v4 rule (e): Old Sapcode is an accumulating comma-separated
        # list.  On a refresh/migrate/reactivate, any source-provided code
        # is APPENDED to the existing list (never replacing it).  Brands
        # without a source old-code (mapped value None) leave it untouched.
        if f == "Old Sapcode":
            if new_val in (None, ""):
                continue
            merged = _merge_old_sapcode(old_val, new_val)
            if not _values_equal(old_val, merged):
                master_row[f] = merged
                out.append(ChangeRecord(
                    status=status, store_id=display_sid, field_changed=f,
                    old_value=old_val, new_value=merged,
                    notes=f"matched on {match_key_name}; Old Sapcode appended",
                ))
            continue
        if not _values_equal(old_val, new_val):
            master_row[f] = new_val
            out.append(ChangeRecord(
                status=status,
                store_id=display_sid,
                field_changed=f,
                old_value=old_val,
                new_value=new_val,
                notes=f"matched on {match_key_name}",
            ))
    return out


# -- main entry point ----------------------------------------------------

def reconcile(*, rules, mapped_rows, master_rows, master_field_order,
              scope_column, scope_value, month_label: Optional[str] = None):
    rule_by_field = _build_rule_index(rules)

    # v0.5.1 (F1 + F5): pre-run sweeps over the in-scope rows BEFORE the
    # cascade runs.  These repair legacy data (Isactive/Daily mismatches,
    # placeholder Title values) so downstream diffs are clean.
    _sweep_warnings: List[str] = []
    _pre_changes = apply_isactive_daily_sweep(
        master_rows, scope_column, scope_value, _sweep_warnings)
    _pre_changes.extend(apply_title_mirror_sweep(
        master_rows, scope_column, scope_value))

    by_id, by_retek, by_legacy, by_old_sapcode, in_scope_indices = (
        _index_master(master_rows, scope_column, scope_value)
    )
    in_scope_set = set(in_scope_indices)
    full_by_id, full_by_legacy = _full_indices(master_rows)

    changes: List[ChangeRecord] = list(_pre_changes)
    warnings: List[str] = list(_sweep_warnings)
    # Per-row record of what happened this run (index -> flags).  Filled by
    # the cascade below and by apply_inactivation_pass; read by
    # apply_status_columns to derive the 3 status columns.
    row_run_status: Dict[int, Dict[str, bool]] = {}
    summary = {"NEW": 0, "UPDATED": 0, "CLOSED": 0,
               "ORPHAN": 0, "CODE_CHANGED": 0,
               "REACTIVATED": 0, "INACTIVATED_BAD_EMAIL": 0,
               # v0.5.1 (F1/F5) sweep counters.
               "FLAG_SWEEP": sum(1 for c in _pre_changes if c.status == "FLAG_SWEEP"),
               "TITLE_SWEEP": sum(1 for c in _pre_changes if c.status == "TITLE_SWEEP")}

    # Warn about in-scope master rows missing a Store Id.
    for idx in in_scope_indices:
        mrow = master_rows[idx]
        if _is_empty(mrow.get('Store Id')):
            warnings.append(
                f"In-scope master row {idx} has null/blank Store Id: "
                f"Legacy Code={mrow.get('Legacy Code')!r}, "
                f"brand={mrow.get('brand')!r}, "
                f"Region={mrow.get('Region')!r}"
            )

    matched_master_rows: set = set()
    matched_source = 0
    unmatched_source = 0
    orphan_source = 0

    output_rows = [dict(r) for r in master_rows]

    for mapped in mapped_rows:
        sid = _match_key(mapped.get("Store Id"))

        # -- Step 1 / Step 3: StoreId, Retek Code, Legacy Code --
        master_idx: Optional[int] = None
        match_key_name: Optional[str] = None
        if sid is not None:
            if sid in by_id:
                master_idx = by_id[sid]; match_key_name = "Store Id"
            elif sid in by_retek:
                master_idx = by_retek[sid]; match_key_name = "Retek Code"
            elif sid in by_legacy:
                master_idx = by_legacy[sid]; match_key_name = "Legacy Code"

        if master_idx is not None:
            # Determine Refresh (active) vs Reactivated (inactive).
            master_row = output_rows[master_idx]
            is_active = _is_active(master_row.get("Isactive"))
            display_sid = master_row.get("Store Id") or mapped.get("Store Id")
            status = "UPDATED" if is_active else "REACTIVATED"

            matched_master_rows.add(master_idx)
            matched_source += 1

            row_changes = _apply_refresh(
                master_row, mapped, master_field_order, rule_by_field,
                status, display_sid, match_key_name,
            )

            # v0.5.1 (F5): Title is a derived mirror of Store Id on every
            # engine-written row (Refresh and Reactivate alike).
            _mirror_title(master_row)
            # v4 rule (c): keep Square feet / Carpet in sync.
            _fill_area_fallback(master_row)

            if status == "REACTIVATED":
                # Flip Isactive=YES and Dailychecklist access=YES
                old_act = master_row.get("Isactive")
                master_row["Isactive"] = "YES"
                row_changes.append(ChangeRecord(
                    status="REACTIVATED", store_id=display_sid,
                    field_changed="Isactive",
                    old_value=old_act, new_value="YES",
                    notes=f"matched on {match_key_name} (was inactive)",
                ))
                old_daily = master_row.get("Dailychecklist access")
                if not _values_equal(old_daily, "YES"):
                    master_row["Dailychecklist access"] = "YES"
                    row_changes.append(ChangeRecord(
                        status="REACTIVATED", store_id=display_sid,
                        field_changed="Dailychecklist access",
                        old_value=old_daily, new_value="YES",
                        notes="reactivation",
                    ))
                # Overwrite Remark with the reactivation template.
                new_remark = build_remark(REMARK_REACTIVATED, month_label=month_label)
                old_remark = master_row.get("Remarks")
                master_row["Remarks"] = new_remark
                if not _values_equal(old_remark, new_remark):
                    row_changes.append(ChangeRecord(
                        status="REACTIVATED", store_id=display_sid,
                        field_changed="Remarks",
                        old_value=old_remark, new_value=new_remark,
                        notes="reactivation remark",
                    ))
                summary["REACTIVATED"] += 1
                changes.extend(row_changes)
                row_run_status[master_idx] = {"changed": True, "reactivated": True}
            elif row_changes:
                summary["UPDATED"] += 1
                changes.extend(row_changes)
                row_run_status[master_idx] = {"changed": True}
            else:
                # Active refresh that touched no fields -> no data change.
                row_run_status[master_idx] = {"changed": False}
            continue

        # -- Step 2: Migrated --
        # Two ways a migration is detected for the same brand:
        #   (a) the source's (new) Store Id already appears in some master
        #       row's accumulated Old Sapcode list, or
        #   (b) the source row carries the previous code in its own
        #       Old Sapcode field (e.g. PF's "Old SAP" column) and that
        #       code matches an existing master Store Id / Legacy / Retek.
        # Case (b) is the "11002 -> 67890" rename: the new code is unknown
        # to the master, so without it the row would wrongly fall through
        # to Step 4 (New) and the old row would be left to be inactivated.
        migrated_idx: Optional[int] = None
        if sid is not None and sid in by_old_sapcode:
            migrated_idx = by_old_sapcode[sid]
        else:
            for tok in _split_old_sapcode(mapped.get("Old Sapcode")):
                k = _match_key(tok)
                if k is None:
                    continue
                if k in by_id:
                    migrated_idx = by_id[k]; break
                if k in by_legacy:
                    migrated_idx = by_legacy[k]; break
                if k in by_retek:
                    migrated_idx = by_retek[k]; break

        if migrated_idx is not None:
            master_idx = migrated_idx
            master_row = output_rows[master_idx]
            old_store_id = master_row.get("Store Id")
            was_inactive = not _is_active(master_row.get("Isactive"))
            display_sid = f"{old_store_id} -> {mapped.get('Store Id')}"

            matched_master_rows.add(master_idx)
            matched_source += 1

            row_changes = _apply_refresh(
                master_row, mapped, master_field_order, rule_by_field,
                "CODE_CHANGED", display_sid, "Old Sapcode token",
            )
            # v4 rule (e): preserve the migration chain -- append the
            # previous Store Id to the Old Sapcode list (add, never
            # replace), so future runs keep matching this row.
            old_codes = master_row.get("Old Sapcode")
            merged_codes = _merge_old_sapcode(old_codes, old_store_id)
            if not _values_equal(old_codes, merged_codes):
                master_row["Old Sapcode"] = merged_codes
                row_changes.append(ChangeRecord(
                    status="CODE_CHANGED", store_id=display_sid,
                    field_changed="Old Sapcode",
                    old_value=old_codes, new_value=merged_codes,
                    notes="migrated: previous Store Id appended to list",
                ))
            # A store migrated from an inactive row is brought back to
            # active (Isactive / Dailychecklist access are also set to YES
            # via the brand CONSTANT block; recorded here for the report).
            if was_inactive:
                master_row["Isactive"] = "YES"
                master_row["Dailychecklist access"] = "YES"
                row_changes.append(ChangeRecord(
                    status="CODE_CHANGED", store_id=display_sid,
                    field_changed="Isactive", old_value="NO", new_value="YES",
                    notes="migrated from inactive -> active",
                ))
            # v0.5.1 (F5): Title := Store Id on every migrated row.
            _mirror_title(master_row)
            # v4 rule (c): keep Square feet / Carpet in sync.
            _fill_area_fallback(master_row)
            # Overwrite Remark with the migration template.
            new_remark = build_remark(
                REMARK_MIGRATED, month_label=month_label,
                old_code=old_store_id,
            )
            old_remark = master_row.get("Remarks")
            master_row["Remarks"] = new_remark
            if not _values_equal(old_remark, new_remark):
                row_changes.append(ChangeRecord(
                    status="CODE_CHANGED", store_id=display_sid,
                    field_changed="Remarks",
                    old_value=old_remark, new_value=new_remark,
                    notes="migration remark",
                ))
            summary["CODE_CHANGED"] += 1
            changes.extend(row_changes)
            # A migration from an inactive row counts as a reactivation for
            # the standing Reactivated flag (the store has reopened).
            row_run_status[master_idx] = {"changed": True,
                                          "reactivated": bool(was_inactive)}
            continue

        # -- ORPHAN: cross-brand collision --
        orphan_idx = None
        orphan_key_name = None
        if sid is not None and sid in full_by_id and full_by_id[sid] not in in_scope_set:
            orphan_idx = full_by_id[sid]
            orphan_key_name = "Store Id"
        elif sid is not None and sid in full_by_legacy and full_by_legacy[sid] not in in_scope_set:
            orphan_idx = full_by_legacy[sid]
            orphan_key_name = "Legacy Code"

        if orphan_idx is not None:
            orphan_source += 1
            existing_scope = output_rows[orphan_idx].get(scope_column)
            msg = (f"Source row {mapped.get('Store Id')!r} matches master row "
                   f"in scope {existing_scope!r} (expected {scope_value!r}); "
                   f"not applying update.")
            warnings.append(msg)
            summary["ORPHAN"] += 1
            changes.append(ChangeRecord(
                status="ORPHAN",
                store_id=mapped.get("Store Id"),
                field_changed="(scope mismatch)",
                old_value=existing_scope,
                new_value=scope_value,
                notes=f"matched on {orphan_key_name}; master left untouched",
            ))
            continue

        # -- Step 4: NEW --
        unmatched_source += 1
        summary["NEW"] += 1
        new_row = _make_empty_master_row(master_field_order)
        new_sid = mapped.get("Store Id")
        for f in master_field_order:
            rule = rule_by_field.get(f)
            v = mapped.get(f)
            if rule is not None and rule.source_type == PRESERVE_FROM_MASTER:
                continue
            new_row[f] = v
            if not _is_empty(v):
                changes.append(ChangeRecord(
                    status="NEW",
                    store_id=new_sid,
                    field_changed=f,
                    old_value=None,
                    new_value=v,
                    notes="new store",
                ))
        # Brand constants like Isactive / Dailychecklist access are applied
        # via the brand's CONSTANT rules in mapped[]; ensure both are YES
        # even if the brand config didn't include them.
        if _is_empty(new_row.get("Isactive")):
            new_row["Isactive"] = "YES"
        if _is_empty(new_row.get("Dailychecklist access")):
            new_row["Dailychecklist access"] = "YES"
        # v0.5.1 (F6): ID is SharePoint-assigned after upload. Always
        # blank on NEW rows -- Nivethitha's team fills it in once SharePoint
        # provides the value.
        new_row["ID"] = None
        # v0.5.1 (F5): Title mirrors Store Id from day one.
        _mirror_title(new_row)
        # v4 rule (c): keep Square feet / Carpet in sync.
        _fill_area_fallback(new_row)
        # Overwrite Remark with the new-store template.
        new_remark = build_remark(REMARK_NEW, month_label=month_label)
        new_row["Remarks"] = new_remark
        changes.append(ChangeRecord(
            status="NEW", store_id=new_sid,
            field_changed="Remarks",
            old_value=None, new_value=new_remark,
            notes="new-store remark",
        ))
        output_rows.append(new_row)
        row_run_status[len(output_rows) - 1] = {"new": True, "changed": True}

    return ReconcileResult(
        updated_master=output_rows,
        changes=changes,
        summary=summary,
        warnings=warnings,
        row_run_status=row_run_status,
        matched_source_count=matched_source,
        unmatched_source_count=unmatched_source,
        orphan_source_count=orphan_source,
        matched_master_rows=matched_master_rows,
        in_scope_indices=in_scope_indices,
    )


# -- Section 6: inactivation pass ---------------------------------------


# -- Section 6: inactivation pass ---------------------------------------

_EMAIL_RE = re.compile(r"@([^\s>;,]+?)(?:[\s>;,]|$)")


def _extract_domain(email):
    """Pull the lowercase domain out of an email-like value.

    Handles plain ``foo@bar.com``, the angle-bracket form
    ``A205 <A205.tcns@Abfrl.AdityAbirlA.com>`` seen in TCNS source, and
    misc punctuation.  Returns ``None`` if no @-suffix is found.
    """
    if email is None:
        return None
    s = str(email).strip()
    if not s:
        return None
    m = _EMAIL_RE.search(s)
    if not m:
        return None
    return m.group(1).strip(".").lower()


def apply_inactivation_pass(*, result, brand_label,
                            month_label=None,
                            brand_label_short=None):
    """Section 6 in-place inactivation pass.

    1. In-scope master rows that the cascade did NOT touch and are
       currently active are flipped to Isactive=NO + Daily=NO with the
       inactive-missing remark.
    2. ALL in-scope rows where Isactive=YES and the Store Email Id
       domain is not in :data:`APPROVED_EMAIL_DOMAINS` are inactivated
       with the bad-email remark.

    Both checks emit ChangeRecord entries that get appended to
    ``result.changes`` and the corresponding summary counter.

    Mutates ``result.updated_master``, ``result.changes``, ``result.summary``.
    """
    brand_short = brand_label_short or brand_label

    # Step 1: rows not touched this run.
    for idx in result.in_scope_indices:
        if idx in result.matched_master_rows:
            continue
        master_row = result.updated_master[idx]
        if not _is_active(master_row.get("Isactive")):
            continue
        sid = master_row.get("Store Id")
        old_active = master_row.get("Isactive")
        old_daily = master_row.get("Dailychecklist access")
        master_row["Isactive"] = "NO"
        master_row["Dailychecklist access"] = "NO"
        new_remark = build_remark(
            REMARK_INACTIVE_MISS,
            brand=brand_short, month_label=month_label,
        )
        old_remark = master_row.get("Remarks")
        master_row["Remarks"] = new_remark
        # v0.5.1 (F5): keep Title aligned with Store Id even on
        # inactivation (defensive -- Store Id doesn't change here).
        _mirror_title(master_row)

        result.summary["CLOSED"] += 1
        result.row_run_status[idx] = {"changed": True, "deactivated": True}
        result.changes.append(ChangeRecord(
            status="CLOSED", store_id=sid,
            field_changed="Isactive",
            old_value=old_active, new_value="NO",
            notes="in-scope master row not present in source",
        ))
        if not _values_equal(old_daily, "NO"):
            result.changes.append(ChangeRecord(
                status="CLOSED", store_id=sid,
                field_changed="Dailychecklist access",
                old_value=old_daily, new_value="NO",
                notes="inactivation cascade",
            ))
        if not _values_equal(old_remark, new_remark):
            result.changes.append(ChangeRecord(
                status="CLOSED", store_id=sid,
                field_changed="Remarks",
                old_value=old_remark, new_value=new_remark,
                notes="inactive-missing remark",
            ))

    # Step 2: bad email domain on active rows.
    for idx in result.in_scope_indices:
        master_row = result.updated_master[idx]
        if not _is_active(master_row.get("Isactive")):
            continue
        email = master_row.get("Store Email Id")
        domain = _extract_domain(email)
        if domain is None or domain in APPROVED_EMAIL_DOMAINS:
            continue
        sid = master_row.get("Store Id")
        old_active = master_row.get("Isactive")
        old_daily = master_row.get("Dailychecklist access")
        master_row["Isactive"] = "NO"
        master_row["Dailychecklist access"] = "NO"
        new_remark = build_remark(REMARK_INACTIVE_BAD_EMAIL)
        old_remark = master_row.get("Remarks")
        master_row["Remarks"] = new_remark
        _mirror_title(master_row)

        result.summary["INACTIVATED_BAD_EMAIL"] += 1
        # Merge with any prior status this run (e.g. a row refreshed then
        # inactivated for a bad email): deactivation is the final outcome.
        _st = result.row_run_status.setdefault(idx, {})
        _st["changed"] = True
        _st["deactivated"] = True
        _st["reactivated"] = False
        result.changes.append(ChangeRecord(
            status="INACTIVATED_BAD_EMAIL", store_id=sid,
            field_changed="Isactive",
            old_value=old_active, new_value="NO",
            notes=f"email domain {domain!r} not in approved list",
        ))
        if not _values_equal(old_daily, "NO"):
            result.changes.append(ChangeRecord(
                status="INACTIVATED_BAD_EMAIL", store_id=sid,
                field_changed="Dailychecklist access",
                old_value=old_daily, new_value="NO",
                notes="inactivation cascade",
            ))
        if not _values_equal(old_remark, new_remark):
            result.changes.append(ChangeRecord(
                status="INACTIVATED_BAD_EMAIL", store_id=sid,
                field_changed="Remarks",
                old_value=old_remark, new_value=new_remark,
                notes="bad-email remark",
            ))


# -- Section 7: engine-derived status columns --------------------------

def apply_status_columns(result, master_field_order, scope_column=None,
                         scope_value=None):
    """Fill the three engine-derived status columns on this run's rows.

    Must run AFTER :func:`reconcile` and :func:`apply_inactivation_pass`,
    when each row's final ``Isactive`` and this run's event flags are known.
    Appends the column names to ``master_field_order`` (in place) if missing
    so the writer emits them.

    Column semantics (operator decision -- standing state for the two
    YES/NO flags, per-run for Data Modified):

      * ``Data Modified``      -- ``"New"`` for stores created this run,
        ``"Yes"`` when any field changed this run, ``"No"`` otherwise.
      * ``Deactivated Stores`` -- ``"YES"`` while the row is currently
        inactive, ``"NO"`` while active.
      * ``Reactivated Stores`` -- ``"YES"`` once a store reopens; the value
        persists across runs until the store is deactivated again (``"NO"``).
        New stores and inactive stores are ``"NO"``.
    """
    from .brands import STATUS_COLUMNS
    data_mod_col, deact_col, react_col = STATUS_COLUMNS
    for col in STATUS_COLUMNS:
        if col not in master_field_order:
            master_field_order.append(col)

    # Rows belonging to this run's brand: in-scope originals plus any new
    # rows appended this run (tracked in row_run_status).
    indices = set(result.in_scope_indices) | set(result.row_run_status.keys())
    for i in indices:
        if i < 0 or i >= len(result.updated_master):
            continue
        row = result.updated_master[i]
        flags = result.row_run_status.get(i, {})
        active = _is_active(row.get("Isactive"))

        if flags.get("new"):
            row[data_mod_col] = "New"
        elif flags.get("changed"):
            row[data_mod_col] = "Yes"
        else:
            row[data_mod_col] = "No"

        row[deact_col] = "NO" if active else "YES"

        if not active:
            row[react_col] = "NO"
        elif flags.get("reactivated"):
            row[react_col] = "YES"
        elif flags.get("new") or flags.get("deactivated"):
            row[react_col] = "NO"
        else:
            cur = row.get(react_col)
            row[react_col] = "YES" if (
                cur is not None and str(cur).strip().upper() == "YES") else "NO"
