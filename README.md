# Store Master Normalizer

A web tool that turns a brand's monthly store-master export into an up-to-date
copy of the company's backend master store list, plus a change report that
records exactly what changed.

It replaces a manual reconciliation task (roughly 25 days of effort per cycle)
with a few minutes of supervised, auditable work. Eight brands are configured:
Pantaloons, PF (Planet Fashion), Tasva, TCNS, Shantanu and Nikhil, Ownd,
House of Masaba, and Jaypore.

## Run locally

You need **Python 3.12**. From the repo root:

```sh
# (optional) create and activate a virtual environment
python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate

python -m pip install -r requirements.txt
python -m web.run
```

The console prints `Store Master Normalizer  v1.0.0` / "Starting…" and your
default browser opens to `http://127.0.0.1:8000/`. Everything runs on your
machine — nothing is uploaded. Press Ctrl-C (or close the console) to stop.

Headless (no auto-browser), useful for development:

```sh
python -m uvicorn web.app:app --port 8000
```

## Use (web UI)

1. **Brand** — pick the brand the source file belongs to. For brands whose data
   tab name changes monthly, type the current tab name in the **Sheet name**
   field.
2. **Source workbook** — drop the brand's monthly export (`.xlsx` or `.xlsb`).
3. **Backend master** — drop the most recent backend master `.xlsx`.
4. **Convert** — produces, in the `temp/` folder (and as browser downloads):
   - `<brand>_Updated_Master_<month>.xlsx`
   - `<brand>_Change_Report_<month>.xlsx`
5. **Verify output** — runs an independent check that re-derives the output cell
   by cell and returns **PASS** or **FAIL**.

## Command line

```sh
python -m engine.cli \
  --source "inputs/Pantaloons_Apr_2026.xlsx" \
  --master "inputs/Backend_Data_-_Store_Master.xlsx" \
  --brand-name Pantaloons \
  --scope-column brand --scope-value Pantaloons \
  --sheet Sheet1 --header-row 1 \
  --month May-2026 --out-dir outputs
```

## What the counts mean

- **New** — a store in the source but not yet in the master. Added.
- **Updated** — a store in both, with at least one field changed.
- **Reactivated** — a previously inactive store that reappeared in the source.
- **Migrated** — matched via the master's `Old Sapcode` (a code change).
- **Closed** — a master store no longer in the source; `Isactive` set to `NO`.
- **Warnings** — non-blocking issues (e.g. a master row with no Store Id, or two
  duplicated source columns carrying different values).

Cosmetic differences are ignored (`'WEST BENGAL'` vs `'West Bengal'`, `'27000'`
vs `27000`, `'Jul-17'` vs a real date, underscores vs spaces). Only real changes
appear in the change report.

## Project layout

```
engine/        Reconciliation engine (pure Python, no UI dependency)
web/           FastAPI app + entry point (web/run.py) + templates
tests/         Regression tests (pytest / unittest)
brands.json    Per-brand configuration and mapping rules
docs/          Handover documentation (Explanation, HLD, LLD, SLD, Code, Guide)
Dockerfile     Railway container build
Procfile       Process command for buildpack deploys
requirements.txt
```

## Configuration

All per-brand behaviour lives in `brands.json` at the repo root, read fresh on
every run (no restart needed locally). See **docs/06_Guide_Document.docx** for
how to add a brand or add/remove a master column.

## Tests

```sh
python -m pip install -r requirements.txt pytest
python -m pytest -q
```

## Deployment (Railway)

The hosted instance builds from the `Dockerfile` and serves
`uvicorn web.app:app` on the platform-provided `$PORT`. To ship a change, commit
and push to `main`; Railway rebuilds and redeploys automatically.

## Versioning

The single source of truth for the version is `__version__` in
`engine/__init__.py` — currently **1.0.0** — following semantic versioning
(`MAJOR.MINOR.PATCH`):

- **MAJOR** — incompatible changes to the output schema or the `brands.json`
  format.
- **MINOR** — backward-compatible additions (a new brand, a new column).
- **PATCH** — backward-compatible fixes.

To update the version:

1. Edit `__version__` in `engine/__init__.py`.
2. Add an entry to `CHANGELOG.md`.
3. Commit (e.g. `git commit -m "Release vX.Y.Z"`), optionally tag
   (`git tag vX.Y.Z`), and push. Railway redeploys on push.

The startup banner and the handover docs reference this constant. The inline
`v0.x.y` notes in the source code are **historical change annotations** marking
when a fix landed (see `CHANGELOG.md`) — not the current version.

## Documentation

Full handover documentation is in `docs/`:

| File | Contents |
|------|----------|
| `01_Explanation_Document.docx` | What the tool does and why (plain language) |
| `02_HLD_High_Level_Design.docx` | Components, responsibilities, data flow |
| `03_LLD_Low_Level_Design.docx` | Module internals, rules, the reconciliation cascade |
| `04_SLD_System_Level_Design.docx` | Runtime, deployment, system data flow |
| `05_Code_Document.docx` | Module-by-module code reference |
| `06_Guide_Document.docx` | Run locally, add brands/columns, edit remarks, deploy, versioning |
