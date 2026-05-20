"""Per-brand divergence-warning rules.

Field-level mapping overrides used to live here, separate from the
reference sheet's rules.  Mappings have since moved inline into each
brand's ``brands.json`` entry (with the overrides merged), so this
module only carries divergence-warning configuration now.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple, Union

from .brands import load_brands


ColumnRef = Union[str, int]


@dataclass
class BrandOverride:
    divergence_warnings: List[Tuple[ColumnRef, ColumnRef]] = field(default_factory=list)


def get(brand_name: str) -> BrandOverride:
    """Return the divergence-warning block for ``brand_name``."""
    cfg = load_brands().get(brand_name)
    if cfg is None:
        return BrandOverride()
    out: List[Tuple[ColumnRef, ColumnRef]] = []
    for pair in cfg.get("divergence_warnings") or []:
        try:
            a, b = pair
        except (TypeError, ValueError):
            continue
        out.append((a, b))
    return BrandOverride(divergence_warnings=out)
