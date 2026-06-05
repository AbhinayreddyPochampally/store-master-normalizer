# Changelog

All notable changes to the Store Master Normalizer are recorded here. The
current version is set in `engine/__init__.py` (`__version__`) and follows
semantic versioning (`MAJOR.MINOR.PATCH`).

The pre-1.0 entries below consolidate the historical `v0.x.y` feature
annotations that appear inline in the engine source; they mark when each piece
of behaviour landed during development.

## 1.0.1 — 2026-06-04

- **Fix: sheet name picker unclickable in the web UI.** The invisible
  full-size `<input type="file">` overlay on each dropzone sat above the
  sheet name field and the action buttons, so clicks meant for the picker
  opened the file-browse dialog instead. The picker and action buttons are
  now lifted above the overlay (`web/static/style.css`); the rest of the
  dropzone keeps its click-to-upload behaviour.

## 1.0.0 — 2026-06-03

Handover release. Standardised the version scheme and cleaned the project for
handover.

- Established `engine/__init__.py::__version__` as the single source of truth
  for the version (was the bare string `"4"`).
- Removed the standalone `.exe` / PyInstaller build and launcher; the tool is
  now a Python web app run locally (`python -m web.run`) or hosted on Railway.
- **Data Modified** column: `New` / `Yes` / `No`, and `No` for a store
  deactivated this run even if other fields changed, per the operator's legend.
- **Region** output is the full uppercase word (`SOUTH` / `NORTH` / `EAST` /
  `WEST`); **Store Zone** keeps the 4-character code (`SOUT` / `NRTH` / `EAST` /
  `WEST`).
- Added handover documentation under `docs/`.

## 0.5.2 — historical

- Backend Master sheet picker (`_backend.default_sheet` in `brands.json`,
  overridable from the UI).
- Source loader stops reading at the first fully-blank row after the header.

## 0.5.1 — historical

- 44-column SharePoint-aligned output schema (`ID` at position 1, `Title` at 44).
- Three engine-derived status columns: Data Modified, Deactivated Stores,
  Reactivated Stores.
- `Region` forced uppercase; `Title` mirrors `Store Id`; `ENGINE_PRESERVE` tag
  for the SharePoint-managed `ID` column.

## 0.4.1 — historical

- Four-step matching cascade (Refresh / Migrated / Reactivated / New) plus the
  Section 6 inactivation pass (closed / bad-email).
- Change-report column names, classification labels, and date/int output
  normalisation.

## 0.4.0 — historical

- Initial reconciliation engine.
