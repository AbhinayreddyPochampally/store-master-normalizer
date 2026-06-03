"""Remark templates emitted by the cascade and inactivation passes.

v0.4.1 B3: design doc Section 7 specifies the strings the engine writes
to the Remarks column on each row classification.  Keeping them in one
module makes them editable in one place and ensures every engine path
uses the same wording.

Placeholders:
    {monthLong}   "May 13, 2026"   - free-form, used by new / migrated / reactivated
    {monthShort}  "May-2026"       - used by inactive-missing (also drives filenames)
    {brand}       brand short label (Pantaloons / TCNS / TASVA / PF)
    {oldCode}     pre-migration Store Id (Migrated only)
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional


# Template identifiers (used internally as keys, not user-visible).
REMARK_NEW              = "new"
REMARK_MIGRATED         = "migrated"
REMARK_REACTIVATED      = "reactivated"
REMARK_INACTIVE_MISS    = "inactiveMiss"
REMARK_INACTIVE_BAD_EMAIL = "inactiveBadEmail"


# Design doc Section 7 templates.  Edit here only.
REMARK_TEMPLATES = {
    REMARK_NEW:               "Store newly created on {monthLong}",
    REMARK_MIGRATED:          "Migrated from old SAP code {oldCode} on {monthLong}",
    REMARK_REACTIVATED:       "Reactivated on {monthLong}",
    REMARK_INACTIVE_MISS:     "Store ID not present in {brand} sheet for {monthShort}. "
                              "Marked as Inactive.",
    REMARK_INACTIVE_BAD_EMAIL: "Store email domain not in approved list. Marked as Inactive.",
}


_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

_MONTH_ABBR = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def _today_long() -> str:
    """e.g. 'May 13, 2026'."""
    today = _dt.date.today()
    return f"{_MONTH_NAMES[today.month - 1]} {today.day}, {today.year}"


def _short_from_label(month_label: Optional[str]) -> str:
    """Normalise an operator-supplied label into 'MMM-YYYY'.

    Accepts 'May-2026', 'May 2026', 'may-2026', or None (uses today).
    """
    if month_label:
        s = month_label.strip().replace(" ", "-")
        if s:
            return s
    today = _dt.date.today()
    return f"{_MONTH_ABBR[today.month - 1]}-{today.year}"


def _long_from_label(month_label: Optional[str]) -> str:
    """Long form 'May 2026' derived from the operator's month label.

    Falls back to today's full date when no label is supplied.  This
    keeps the new/migrated/reactivated remarks readable for both ad-hoc
    runs and the regular monthly batch.
    """
    if not month_label:
        return _today_long()
    # Parse 'May-2026' / 'May 2026' / 'May-26' / 'May 2026'
    s = month_label.strip().replace("-", " ")
    parts = s.split()
    if len(parts) == 2:
        month_part, year_part = parts
        for i, abbr in enumerate(_MONTH_ABBR):
            if month_part.lower().startswith(abbr.lower()):
                year = year_part
                if len(year) == 2:
                    year = "20" + year
                return f"{_MONTH_NAMES[i]} {year}"
    return s


def build_remark(template_key: str, *,
                 month_label: Optional[str] = None,
                 brand: Optional[str] = None,
                 old_code: Optional[str] = None) -> str:
    """Render a remark template.

    Unknown ``template_key`` returns ``""`` rather than raising; the
    engine should never produce that, but a missing template should
    never crash a run.
    """
    template = REMARK_TEMPLATES.get(template_key)
    if not template:
        return ""
    return template.format(
        monthLong=_long_from_label(month_label),
        monthShort=_short_from_label(month_label),
        brand=(brand or ""),
        oldCode=(old_code if old_code is not None else ""),
    )
