"""Apply a list of Rules to source rows and produce target-field dicts.

Two responsibilities live here:

1. Resolve duplicate source column names by *adjacency to an anchor*.
   The anchor is the column index of the most recently resolved
   *unique-name* COLUMN rule.  When a rule's source name is ambiguous
   (appears multiple times in the source sheet), pick the occurrence
   whose column index is closest to and greater than the current anchor.
   Ambiguous resolutions do NOT advance the anchor -- only a unique-name
   COLUMN resolution does.

2. Apply the built-in DERIVED rules:
       ZONE_FROM_REGION   -- SOUTH -> SOUT, NORTH -> NRTH, EAST -> EAST,
                             WEST  -> WEST.
       PINCODE_FROM_ADDRESS -- last 6-digit run in the address text.

After applying all rules:
* Isactive and Dailychecklist access are forced upper-case so the master
  always stores YES / NO regardless of source casing.
* Target fields in ``_DATE_FIELDS`` are coerced from numeric Excel serial
  dates to native ``datetime`` values.  xlsb loaders hand back the raw
  serial number (e.g. 45235.0); without coercion the output master would
  hold integers in a date column.  We only coerce values in the plausible
  Excel-serial range (1970-01-01 .. 2100-01-01) so genuine non-date
  numbers stay untouched.

PRESERVE_FROM_MASTER and EMPTY rules emit None; the reconciler distinguishes
the two when merging with the existing master row.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .dates import parse_iso_date
from .reference_reader import (
    CONSTANT,
    COLUMN,
    DERIVED,
    EMPTY,
    ENGINE_PRESERVE,
    PINCODE_FROM_ADDRESS,
    PRESERVE_FROM_MASTER,
    Rule,
    TITLE_FROM_STORE_ID,
    ZONE_FROM_REGION,
)
from .source_loader import SourceSheet


# Target fields forced to upper-case on output regardless of reference.
# v0.5.1 (F3): Region is included so all four values become uppercase
# NORTH / SOUTH / EAST / WEST, even when the brand mapping omits the
# explicit "upper" transform.
_FORCE_UPPER_TARGETS = {
    "Isactive",
    "Dailychecklist access",
    "Region",
}

# Target fields where a numeric value in the plausible Excel-serial range
# should be coerced to a real ``datetime``.  xlsb cells don't carry format
# metadata in pyxlsb's open-source build, so we lean on the target field
# instead.
_DATE_FIELDS = {
    "Store Opening Date",
}

# Target fields cast to int on write (bug A3: pincodes were emitted as
# float64 like 411005.0).  Empty / non-numeric values become None, never
# 'nan' or 'NaN'.
_INT_FIELDS = {
    "Pincode",
}


def _coerce_int(v):
    """Return ``v`` as an int, or None if it can't be one.

    Handles floats with .0 ("411005.0" -> 411005), bare ints, numeric
    strings, NaN, and surrounding whitespace.  Refuses to truncate a real
    fraction (so "411005.7" -> None, surfacing the data problem instead
    of silently rounding).
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, float):
        if v != v:           # NaN
            return None
        if not v.is_integer():
            return None
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if not s or s.lower() in {"nan", "none", "null", "-"}:
            return None
        try:
            f = float(s)
        except ValueError:
            return None
        if f != f or not f.is_integer():
            return None
        return int(f)
    return None

# Excel serial date epoch.  Day 25569 = 1970-01-01; day 73050 = 2100-01-01.
# We treat any numeric value strictly inside that window as a serial.
_EXCEL_EPOCH = datetime(1899, 12, 30)
_EXCEL_SERIAL_MIN = 25569   # 1970-01-01
_EXCEL_SERIAL_MAX = 73050   # 2100-01-01


def _excel_serial_to_datetime(n: float) -> datetime:
    """Convert an Excel serial date number to a Python ``datetime``."""
    whole = int(n)
    frac = n - whole
    return _EXCEL_EPOCH + timedelta(days=whole, seconds=round(frac * 86400))


# -- Derived helpers -----------------------------------------------------

_ZONE_PREFIX = {
    "SOUTH": "SOUT",
    "NORTH": "NRTH",
    "EAST": "EAST",
    "WEST": "WEST",
}


def zone_from_region(region: Any) -> Optional[str]:
    if region is None:
        return None
    s = str(region).strip().upper()
    if not s:
        return None
    if s in _ZONE_PREFIX:
        return _ZONE_PREFIX[s]
    head = re.match(r"[A-Z]+", s)
    if head:
        token = head.group(0)
        if token in _ZONE_PREFIX:
            return _ZONE_PREFIX[token]
        return token[:4]
    return s[:4]


_PINCODE_RE = re.compile(r"(\d{6})(?!\d)")


def pincode_from_address(addr: Any) -> Optional[str]:
    if addr is None:
        return None
    s = str(addr)
    matches = _PINCODE_RE.findall(s)
    if not matches:
        return None
    return matches[-1]


# -- Transforms ----------------------------------------------------------

_PHONE_KEEP_RE = re.compile(r"[^\d+]")


def _phone_clean(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        s = str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
    else:
        s = str(v)
    cleaned = _PHONE_KEEP_RE.sub("", s).strip()
    if cleaned.startswith("+91") and len(cleaned) == 13:
        cleaned = cleaned[3:]
    if cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = cleaned[1:]
    return cleaned or None


def _apply_transform(value: Any, transform: str) -> Any:
    """Apply a per-rule transform from brands.json.

    Supported (case-insensitive):
        upper / lower / title / strip   string case helpers
        lowercase / titlecase           v0.4.1 B4 schema aliases
        int                             _coerce_int
        isodate / iso_date / isoDate    parse_iso_date
        phoneclean                      tidy phone digits
    """
    if value is None or transform == "":
        return value
    t = transform.strip().lower()
    if t == "upper":
        return value.upper() if isinstance(value, str) else value
    if t in ("lower", "lowercase"):
        return value.lower() if isinstance(value, str) else value
    if t in ("title", "titlecase"):
        return value.title() if isinstance(value, str) else value
    if t == "strip":
        return value.strip() if isinstance(value, str) else value
    if t == "int":
        return _coerce_int(value)
    if t in ("isodate", "iso_date"):
        return parse_iso_date(value)
    if t in ("phoneclean", "phone_clean"):
        return _phone_clean(value)
    return value


# -- Duplicate resolution -----------------------------------------------

def _resolve_column(name: str, sheet: SourceSheet, anchor: int,
                    warnings: List[str]) -> Tuple[Optional[int], bool]:
    """Resolve a source-column name; return (col_index, is_unique)."""
    idxs = sheet.indices_for(name)
    if not idxs:
        return None, False
    if len(idxs) == 1:
        return idxs[0], True
    forward = [i for i in idxs if i > anchor]
    if forward:
        return min(forward), False
    warnings.append(
        f"Column {name!r} is duplicated at {idxs} but none lies after the "
        f"current anchor ({anchor}); falling back to leftmost."
    )
    return idxs[0], False


# -- Main API ------------------------------------------------------------

def map_row(rules: List[Rule], row: Dict[int, Any], sheet: SourceSheet,
            warnings: List[str]) -> Dict[str, Any]:
    """Apply `rules` to one source `row`, returning {target_field: value}."""
    out: Dict[str, Any] = {}
    anchor = -1
    for rule in rules:
        tf = rule.target_field
        st = rule.source_type
        sv = rule.source_value

        if st == CONSTANT:
            out[tf] = _apply_transform(sv, rule.transform)
            continue

        if st == EMPTY:
            out[tf] = None
            continue

        if st == PRESERVE_FROM_MASTER:
            out[tf] = None
            continue

        # v0.5.1 (F6): ENGINE_PRESERVE is identical at runtime to
        # PRESERVE_FROM_MASTER -- emit None so the reconciler keeps
        # whatever is already on the master row (typically the SharePoint
        # ID).  NEW-store path leaves the field blank.
        if st == ENGINE_PRESERVE:
            out[tf] = None
            continue

        if st == DERIVED:
            if sv == ZONE_FROM_REGION:
                region_val = out.get("Region")
                if region_val is None:
                    idxs = (sheet.indices_for("Region")
                            or sheet.indices_for("REGION")
                            or sheet.indices_for("Zone"))
                    if idxs:
                        region_val = row.get(idxs[0])
                out[tf] = zone_from_region(region_val)
            elif sv == TITLE_FROM_STORE_ID:
                # v0.5.1 (F5): Title is a mirror of Store Id. Falls back
                # to looking up the source column if Store Id rule hasn't
                # been applied yet (unusual ordering).
                store_id_val = out.get("Store Id")
                if store_id_val is None:
                    idxs = sheet.indices_for("Store Id") or sheet.indices_for("Site Code")
                    if idxs:
                        store_id_val = row.get(idxs[0])
                out[tf] = store_id_val
            elif sv == PINCODE_FROM_ADDRESS:
                addr = out.get("Address")
                if addr is None:
                    idxs = (sheet.indices_for("Store -Address")
                            or sheet.indices_for("Store Address")
                            or sheet.indices_for("ADDRESS")
                            or sheet.indices_for("Address"))
                    if idxs:
                        addr = row.get(idxs[0])
                out[tf] = pincode_from_address(addr)
            else:
                warnings.append(f"Unknown DERIVED rule {sv!r} for {tf!r}")
                out[tf] = None
            continue

        if st == COLUMN:
            col_idx, is_unique = _resolve_column(sv, sheet, anchor, warnings)
            if col_idx is None:
                warnings.append(
                    f"Reference column {sv!r} for target {tf!r} not found in source sheet."
                )
                out[tf] = None
                continue
            val = row.get(col_idx)
            out[tf] = _apply_transform(val, rule.transform)
            if is_unique:
                anchor = col_idx
            continue

        warnings.append(f"Unknown source_type {st!r} for {tf!r}")
        out[tf] = None

        warnings.append(f"Unknown source_type {st!r} for {tf!r}")
        out[tf] = None

    # Normalize date fields to YYYY-MM-DD string regardless of which
    # rule type produced the value.
    for tf in _DATE_FIELDS:
        if tf in out:
            out[tf] = parse_iso_date(out.get(tf))

    # Cast int fields (pincodes etc.).
    for tf in _INT_FIELDS:
        if tf in out:
            out[tf] = _coerce_int(out.get(tf))

    # Force upper-case on Isactive / Dailychecklist access / Region (v0.5.1 F3).
    for tf in _FORCE_UPPER_TARGETS:
        val = out.get(tf)
        if isinstance(val, str):
            out[tf] = val.upper()

    # -- v4 corrected rules (confirmed with Nivethitha) ------------------
    # (d) Region and Store Zone are the SAME value: a 4-character, all-caps
    #     code, one of SOUT / NRTH / WEST / EAST.  Derive the code from
    #     whichever of the two the source provided and write it to both.
    region_src = out.get("Region")
    if region_src in (None, ""):
        region_src = out.get("Store Zone")
    zone_code = zone_from_region(region_src)
    if zone_code is not None:
        if "Region" in out:
            out["Region"] = zone_code
        if "Store Zone" in out:
            out["Store Zone"] = zone_code

    # (b) Store Type / Store Main type / Store Subtype: when the brand
    #     sheet does not provide Main type or Subtype, they default to
    #     Store Type.
    store_type = out.get("Store Type")
    if store_type not in (None, ""):
        for tf in ("Store Main type", "Store Subtype"):
            if out.get(tf) in (None, ""):
                out[tf] = store_type

    # (c) Square feet <-> Carpet are interchangeable.  When the source
    #     gives only one of the two areas, set the other equal to it.
    sqft = out.get("Square feet")
    carpet = out.get("Carpet")
    if sqft in (None, "") and carpet not in (None, ""):
        out["Square feet"] = carpet
    elif carpet in (None, "") and sqft not in (None, ""):
        out["Carpet"] = sqft

    return out


def map_all(rules: List[Rule], sheet: SourceSheet) -> Tuple[List[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    mapped = [map_row(rules, row, sheet, warnings) for row in sheet.rows]
    return mapped, warnings
