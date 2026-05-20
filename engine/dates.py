"""Date parsing and ISO serialization for ``Store Opening Date``.

Background
----------
v0.4.0 wrote ``Store Opening Date`` in 100+ different surface formats
(``MM/DD/YYYY``, ``DD-MM-YYYY``, ``11-Aug-17``, ``Aug-25``, ``Oct-17``,
``31.03.2023``, ``Wednesday, 30 November, 2022``, etc.) because every code
path passed the source value through untouched.  v0.4.1 (bug A2) requires
that *every* write to ``Store Opening Date`` -- and a one-pass sweep over
every output row, including untouched-rows -- be parsed and serialized as
``YYYY-MM-DD``.

Design
------
* :func:`parse_iso_date` accepts whatever the master / source happens to
  hold (``datetime``, ``date``, Excel serial number, free-form string) and
  returns ``YYYY-MM-DD`` (str) or ``None`` if the value is empty, a
  non-date sentinel (``Closed``, ``Store Dropped``, ``-``), or cannot be
  parsed.

* For ambiguous numeric formats (``31/03/2026`` -- is the 31 a day or the
  03?) we prefer the Indian day-first interpretation, because the
  operator's data is Indian retail.  US-style month-first is only tried
  as a last resort.

* No external dependencies: stdlib ``datetime.strptime`` plus a few
  regexes for the messier shapes.  We considered ``python-dateutil``;
  ``parser.parse(..., dayfirst=True)`` would handle most cases, but
  pulling in another dependency for one column wasn't worth it -- and
  dateutil's heuristics produce surprises around ``Aug11-2025``-style
  inputs anyway.

Edge cases covered (all observed in the actual backend master):
    1-Oct-25                      D-MMM-YY
    11-Aug-17 / 01-Mar-19         D[D]-MMM-YY
    Oct-17 / Jun-20               MMM-YY  (defaults to day 1)
    Oct-2017                      MMM-YYYY
    23-07-2025                    DD-MM-YYYY
    31/03/2026                    DD/MM/YYYY (NOT MM/DD)
    2025-02-26                    YYYY-MM-DD
    31.03.2023                    DD.MM.YYYY
    08 04 2024                    DD MM YYYY (space-separated)
    Wednesday, 30 November, 2022  weekday + DD MMMM YYYY
    21st May 2024                 D[D]<ord> MMM YYYY
    Aug11-2025                    MMM DD-YYYY no space
    Nov 14-2022                   MMM DD-YYYY
    March 10-2025                 MMMM DD-YYYY
    Jan- 23-2024                  MMM- DD-YYYY (stray space)
    25/Aug/23                     DD/MMM/YY
    20-02.2024                    mixed - and . separators
    01 -FAB-2026                  typo FAB -> FEB
    OCT 15-2025                   uppercase abbrev
    45594                         Excel serial as int / str
    Closed / Store Dropped / -    sentinel -> None
    1 March / 21-Jul              year-less -> None (refuse to guess)
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Optional


# -- Excel serial constants ---------------------------------------------

_EXCEL_EPOCH = datetime(1899, 12, 30)
_EXCEL_SERIAL_MIN = 25569   # 1970-01-01
_EXCEL_SERIAL_MAX = 73050   # 2100-01-01


def _excel_serial_to_date(n: float) -> date:
    whole = int(n)
    return (_EXCEL_EPOCH + timedelta(days=whole)).date()


# -- Pre-clean helpers --------------------------------------------------

_WEEKDAY_RE = re.compile(
    r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*',
    re.IGNORECASE,
)
_ORDINAL_RE = re.compile(r'(\d+)(?:st|nd|rd|th)\b', re.IGNORECASE)
_FAB_TYPO_RE = re.compile(r'\bFAB\b', re.IGNORECASE)
# "Sept" and "Sept." -> "Sep" so strptime's %b accepts it.
_SEPT_RE = re.compile(r'\bSept\.?\b', re.IGNORECASE)
# Stray spaces around hyphens: "Nov- 29- 2024" -> "Nov-29-2024".
_HYPHEN_PADDING_RE = re.compile(r'\s*-\s*')
# Spaces inside numbers + month: "Aug11-2025" stays as is; let format try.
_MULTISPACE_RE = re.compile(r'\s+')

# Sentinel strings that mean "no date" rather than a date.
_SENTINELS = {'', '-', 'na', 'n/a', 'closed', 'store dropped', 'tbd', 'tba'}


# -- Format lists -------------------------------------------------------

# Strict order matters: DD-first first (Indian retail context), then ISO,
# then MM-first as last resort, then month-name variants.
_STRICT_FORMATS = (
    # ISO
    '%Y-%m-%d',
    '%Y-%m-%d %H:%M:%S',
    '%Y/%m/%d',
    '%Y.%m.%d',
    # Indian numeric, DD first
    '%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y',
    '%d-%m-%y', '%d/%m/%y', '%d.%m.%y',
    '%d %m %Y', '%d %m %y',
    # US numeric, MM first (last-resort for ambiguous cases)
    '%m/%d/%Y', '%m-%d-%Y', '%m/%d/%y', '%m-%d-%y',
    # Short month
    '%d-%b-%Y', '%d-%b-%y',
    '%d %b %Y', '%d %b %y',
    '%d %b-%Y', '%d %b-%y',         # "28 may-2025", "8 Mar-26"
    '%d-%b %Y', '%d-%b %y',         # "28-may 2025"
    '%d/%b/%Y', '%d/%b/%y',
    '%b-%d-%Y', '%b-%d-%y',
    '%b %d %Y', '%b %d, %Y',
    '%b %d-%Y', '%b-%d, %Y',
    # MMM only (day defaults to 1 below)
    '%b-%Y', '%b-%y', '%b %Y', '%b %y',
    # Full month
    '%d %B %Y', '%d %B, %Y',
    '%B %d %Y', '%B %d, %Y',
    '%B-%d-%Y', '%B %d-%Y',
    '%d-%B-%Y',
)


# -- Public API ---------------------------------------------------------

def parse_iso_date(value: Any) -> Optional[str]:
    """Return ``value`` as a ``YYYY-MM-DD`` string, or ``None``.

    See module docstring for the format coverage and ambiguity policy.
    """
    if value is None:
        return None
    # NaN check before anything else (float('nan') != float('nan')).
    if isinstance(value, float) and value != value:
        return None
    if isinstance(value, bool):
        # bool is an int subclass; refuse to treat as a date.
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)):
        # Excel serial.  We only treat values inside a plausible range as a
        # date so genuine non-date numbers (zone IDs, etc.) don't sneak in.
        if _EXCEL_SERIAL_MIN <= float(value) <= _EXCEL_SERIAL_MAX:
            return _excel_serial_to_date(float(value)).isoformat()
        return None

    s = str(value).strip()
    if not s or s.lower() in _SENTINELS:
        return None

    # Pre-clean
    s = _WEEKDAY_RE.sub('', s)               # drop "Wednesday, "
    s = _ORDINAL_RE.sub(r'\1', s)            # 21st -> 21
    s = _FAB_TYPO_RE.sub('FEB', s)           # FAB -> FEB
    s = _SEPT_RE.sub('Sep', s)               # Sept / Sept. -> Sep
    s = _HYPHEN_PADDING_RE.sub('-', s)       # "Nov- 29- 2024" -> "Nov-29-2024"
    s = _MULTISPACE_RE.sub(' ', s).strip()

    # Excel serial as string ("45594")
    if s.isdigit():
        n = int(s)
        if _EXCEL_SERIAL_MIN <= n <= _EXCEL_SERIAL_MAX:
            return _excel_serial_to_date(float(n)).isoformat()
        # Bare year, "2025" -> no date
        return None

    # Try strict formats first
    for fmt in _STRICT_FORMATS:
        try:
            d = datetime.strptime(s, fmt).date()
            return d.isoformat()
        except ValueError:
            continue

    # "Aug11-2025"-style: month abbrev or name glued to day.
    m = re.match(r'^([A-Za-z]+)\s*-?\s*(\d{1,2})\s*-?\s*(\d{2,4})$', s)
    if m:
        month_str, day_str, year_str = m.group(1), m.group(2), m.group(3)
        cleaned = f"{month_str} {day_str} {year_str}"
        for fmt in ('%b %d %Y', '%B %d %Y', '%b %d %y', '%B %d %y'):
            try:
                return datetime.strptime(cleaned, fmt).date().isoformat()
            except ValueError:
                continue

    # Mixed separators ("20-02.2024", "20.02-2024")
    if re.match(r'^\d{1,2}[-./ ]\d{1,2}[-./ ]\d{2,4}$', s):
        parts = re.split(r'[-./ ]', s)
        if len(parts) == 3:
            joined = '-'.join(parts)
            for fmt in ('%d-%m-%Y', '%d-%m-%y', '%m-%d-%Y', '%m-%d-%y'):
                try:
                    return datetime.strptime(joined, fmt).date().isoformat()
                except ValueError:
                    continue

    return None


# -- Convenience wrappers -----------------------------------------------

def normalize_field_in_row(row: dict, field: str = "Store Opening Date") -> None:
    """In-place: parse and serialize a row's date field to YYYY-MM-DD.

    Leaves the field as None if parsing fails (we never invent a date).
    """
    parsed = parse_iso_date(row.get(field))
    row[field] = parsed
