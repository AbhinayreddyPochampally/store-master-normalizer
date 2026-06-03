"""Brand configuration backed by ``brands.json``.

The JSON file lives next to the EXE in packaged builds and at the repo
root in development.  Each brand entry now carries its full 42-row
mapping inline -- the engine no longer reads a Reference sheet from the
brand workbook.

Schema (per brand)::

    {
      "label": "...",
      "scope_column": "brand" | "Organization",
      "scope_value": "...",
      "default_sheet": "...",
      "header_row": 1 | 2,
      "sheet_overridable": false,
      "mapping": [
        {"target": "Store Id", "source_type": "COLUMN",
         "source_value": "Site Code", "transform": ""},
        ...
      ],
      "divergence_warnings": [[col_a, col_b], ...]
    }

There is no UI for editing brands; this file is the operator's hand-edited
config.  ``load_brands()`` reads it on every request, so a JSON edit takes
effect on the next conversion with no restart.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


MASTER_FIELDS: List[str] = [
    # v0.5.1: 44-column SharePoint-aligned schema.
    # Position 1: ID -- SharePoint list ID, engine-preserve on every path
    # except NEW (blank for NEW; Nivethitha's team fills it after upload).
    "ID",
    "Store Id", "Store Name", "Retek Code", "Legacy Code",
    "Organization", "MainOrganization", "SubOrganization",
    "Facility Name", "NewFacilityName", "NewSubBrand",
    "brand", "Sub-brand", "Facility Type", "Brand2", "Business",
    "Region", "Store Type", "Store Main type", "Store Subtype",
    "Store Zone", "Store City", "State", "Address", "Pincode",
    "Location", "Located", "Square feet", "Carpet",
    "Store Opening Date", "Showroom Manager Name", "Showroom Manager No",
    "Store Email Id", "Area Manager Name", "ARM Contact No", "ARM E mail",
    "Regional Manager Name", "RM Contact No", "Regional Manager E-mail Id",
    "Isactive", "Dailychecklist access", "Old Sapcode", "Remarks",
    # Position 44: Title -- mirror of Store Id on every engine-written row.
    "Title",
    # Positions 45-47: engine-derived run-status columns (added per the
    # operator's "3 new columns" request).  Not source-mapped; computed by
    # engine.reconciler.apply_status_columns after the cascade + inactivation
    # pass run.
    #   Data Modified       -- "New" / "Yes" / "No" for this run's outcome.
    #   Deactivated Stores  -- standing: "YES" while the store is inactive.
    #   Reactivated Stores  -- standing: "YES" after a reopen, until changed.
    "Data Modified", "Deactivated Stores", "Reactivated Stores",
]

# Engine-derived run-status columns (not present in source files; the engine
# computes and appends these to the output).  Kept as a named tuple so the
# reconciler and writers agree on names and order.
STATUS_COLUMNS = ("Data Modified", "Deactivated Stores", "Reactivated Stores")

VALID_SOURCE_TYPES = {
    "COLUMN", "CONSTANT", "EMPTY", "DERIVED", "PRESERVE_FROM_MASTER",
    # v0.5.1: ENGINE_PRESERVE is a synonym for PRESERVE_FROM_MASTER used
    # for SharePoint-managed columns (ID).  Treated the same way at runtime
    # but kept distinct in brands.json for operator clarity.
    "ENGINE_PRESERVE",
}

VALID_SCOPE_COLUMNS = {"brand", "Organization"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_brands_path() -> Path:
    """Resolve where ``brands.json`` lives (repo root)."""
    return _repo_root() / "brands.json"


def _seed_external_file(p: Path) -> None:
    """Create ``p`` on first run -- write an empty dict so the operator's
    edits land somewhere reasonable."""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}\n", encoding="utf-8")


def _normalize_brand(b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(b)
    out.setdefault("label", out.get("scope_value", ""))
    out.setdefault("scope_column", "brand")
    out.setdefault("scope_value", "")
    out.setdefault("default_sheet", "")
    out.setdefault("header_row", 1)
    out.setdefault("sheet_overridable", False)
    out["header_row"] = int(out.get("header_row", 1))
    out["sheet_overridable"] = bool(out.get("sheet_overridable", False))
    out.setdefault("mapping", [])
    out.setdefault("divergence_warnings", [])
    out["sheet"] = out["default_sheet"]   # legacy alias
    return out


def load_brands(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Fresh read of ``brands.json``.  Seeds on first run if the file is
    missing.  No caching -- callers get the current disk state.

    Top-level keys whose name starts with ``_`` are reserved for non-brand
    config blocks (e.g. ``_backend`` for the Backend Master sheet default)
    and are filtered out here so brand iteration stays clean."""
    raw = _load_raw(path)
    return {k: _normalize_brand(v) for k, v in raw.items()
            if not k.startswith("_")}


# v0.5.2: Backend Master sheet picker -- the engine has been hardcoded
# to ``Sheet1`` on the master forever.  We now allow a per-run override
# from the UI, defaulting to ``_backend.default_sheet`` in ``brands.json``,
# defaulting in turn to "Backend Updated Data" (the post-v0.5 reality).
def load_backend_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Return the ``_backend`` block from brands.json, with safe defaults
    if absent.  Always returns a dict with at least ``default_sheet``."""
    raw = _load_raw(path)
    block = raw.get("_backend") or {}
    out = dict(block) if isinstance(block, dict) else {}
    out.setdefault("label", "Backend Master")
    out.setdefault("default_sheet", "Backend Updated Data")
    return out


def _load_raw(path: Optional[Path] = None) -> Dict[str, Any]:
    """Read brands.json off disk and return the parsed mapping verbatim
    (no normalisation, no key filtering).

    Self-heals one specific Windows corruption mode: trailing NUL bytes
    appended after a valid JSON document (seen in the wild as 11k+ ``\\x00``
    bytes after the closing ``}``).  json.load otherwise raises
    JSONDecodeError("Extra data") and the engine silently behaves as if
    there were no brands configured.  We strip the trailing NULs, retry,
    and rewrite the cleaned file on disk so the corruption doesn't keep
    biting on subsequent runs.

    Returns ``{}`` only when the file is truly unrecoverable; the caller
    cannot distinguish "no brands configured" from "file unreadable" via
    the return value alone, so the silent-empty fallback is a last
    resort.
    """
    p = Path(path) if path is not None else get_brands_path()
    if not p.exists():
        try:
            _seed_external_file(p)
        except OSError:
            return {}
    try:
        raw_bytes = p.read_bytes()
    except OSError:
        return {}
    # Fast path: well-formed JSON parses directly.
    try:
        return json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    # Recovery path: strip trailing NULs (and trailing whitespace) and
    # try again.  If that works, rewrite the file so it stays clean.
    trimmed = raw_bytes.rstrip(b"\x00").rstrip()
    if trimmed and trimmed != raw_bytes:
        try:
            obj = json.loads(trimmed.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        try:
            # Rewrite without the trailing NULs.  Best-effort; an OSError
            # here is non-fatal -- the in-memory dict is already good.
            with p.open("w", encoding="utf-8", newline="\n") as f:
                json.dump(obj, f, indent=2)
                f.write("\n")
        except OSError:
            pass
        return obj
    return {}


def save_brands(data: Dict[str, Dict[str, Any]],
                path: Optional[Path] = None) -> None:
    """Atomic write of ``brands.json``.  Kept for developer use; not
    exposed via the web UI."""
    p = Path(path) if path is not None else get_brands_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    out: Dict[str, Dict[str, Any]] = {}
    for k, v in data.items():
        rec = {kk: vv for kk, vv in v.items() if kk != "sheet"}
        out[k] = rec
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    os.replace(tmp, p)


def get_brand(brand_key: str) -> Optional[Dict[str, Any]]:
    return load_brands().get(brand_key)


def __getattr__(name):
    """Lazy ``BRANDS`` accessor for legacy callers."""
    if name == "BRANDS":
        return load_brands()
    raise AttributeError(f"module 'engine.brands' has no attribute {name!r}")
