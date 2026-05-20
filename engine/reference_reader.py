"""Per-brand mapping rules.

Mappings used to be read from a ``<Brand> Reference`` sheet inside each
brand's workbook.  That worked for the four pilot workbooks we hand-edited
during development, but real monthly exports arrive without that reference
sheet.  Mappings now live in ``brands.json`` alongside the EXE, with the
full 42-row translation table per brand inline.

The classifier in earlier versions of this file (which parsed the
reference sheet's free-form "Remarks" column) is gone.  ``brands.json``
carries the already-classified rules directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .brands import load_brands


# -- Rule type tags ------------------------------------------------------

CONSTANT = "CONSTANT"
COLUMN = "COLUMN"
EMPTY = "EMPTY"
DERIVED = "DERIVED"
PRESERVE_FROM_MASTER = "PRESERVE_FROM_MASTER"

# -- Derived rule identifiers --------------------------------------------

ZONE_FROM_REGION = "ZONE_FROM_REGION"
PINCODE_FROM_ADDRESS = "PINCODE_FROM_ADDRESS"
# v0.5.1 (F5): Title mirrors Store Id on every engine-written row.
TITLE_FROM_STORE_ID = "TITLE_FROM_STORE_ID"

# v0.5.1 (F6): ENGINE_PRESERVE — same runtime semantics as
# PRESERVE_FROM_MASTER, kept as a distinct tag for the SharePoint ID column.
ENGINE_PRESERVE = "ENGINE_PRESERVE"


@dataclass
class Rule:
    target_field: str
    source_type: str
    source_value: Optional[str]
    transform: str = ""
    notes: str = ""

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"Rule({self.target_field!r}, {self.source_type}, "
            f"{self.source_value!r}, transform={self.transform!r})"
        )


# -- Public API ----------------------------------------------------------

def get_mapping_for_brand(brand_key: str) -> List[Rule]:
    """Return the per-target mapping rules for ``brand_key`` from
    brands.json.  Raises ``KeyError`` if the brand is unknown."""
    brands = load_brands()
    if brand_key not in brands:
        raise KeyError(
            f"Brand {brand_key!r} not in brands.json.  Known: {sorted(brands)}"
        )
    mapping = brands[brand_key].get("mapping") or []
    rules: List[Rule] = []
    for entry in mapping:
        rules.append(Rule(
            target_field=entry.get("target") or "",
            source_type=entry.get("source_type") or "",
            source_value=entry.get("source_value"),
            transform=entry.get("transform") or "",
            notes=entry.get("notes") or "",
        ))
    return rules
