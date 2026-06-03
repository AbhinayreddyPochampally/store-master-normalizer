# Store Master Normalizer — developer notes

## Layout

```
engine/                  Pure-Python engine, no UI dependency
  reference_reader.py    Parse <Brand> Reference -> list of typed Rules
  source_loader.py       Open .xlsx (openpyxl) and .xlsb (pyxlsb)
  mapper.py              Apply rules to source rows; anchor adjacency,
                         ZONE_FROM_REGION, PINCODE_FROM_ADDRESS, etc.
  reconciler.py          Match by Store Id, classify NEW / UPDATED /
                         CLOSED / ORPHAN, write changes
  brand_overrides.py     Per-brand engine-side adjustments
  brands.py              BRANDS dict (canonical brand config)
  cli.py                 Command-line entry point
  verifier.py            Independent post-conversion verifier
web/                            FastAPI front end
  app.py                        Serves the UI
  run.py                        Entry point: boots uvicorn,
                                opens browser to 127.0.0.1:8000
  brand_config.py               Re-exports engine.brands.BRANDS
  templates/                    Jinja2 partials
  static/style.css              Visual tokens, layout, components
analysis/findings.md     Original reference-sheet audit
screenshots/             UI state captures
inputs/                  Sample workbooks (gitignored in real use)
outputs/                 CLI sample outputs (gitignored)
temp/                    Wiped on app start; holds in-flight uploads
requirements.txt         Pinned runtime deps
```

## Run from source

```sh
python -m pip install -r requirements.txt
python -m web.run
```

This boots uvicorn on 127.0.0.1:8000 and opens your default browser.
For headless dev (no browser), drop in
`python -m uvicorn web.app:app --port 8000` instead.

Command-line conversion (no UI):

```sh
python -m engine.cli \
  --source inputs/Pantaloons_Apr_2026.xlsx \
  --master inputs/Backend_Data_-_Store_Master.xlsx \
  --brand-name Pantaloons \
  --scope-column brand \
  --scope-value Pantaloons \
  --sheet Sheet1 \
  --header-row 1 \
  --out-dir outputs
```

Independent verification:

```sh
python -m engine.verifier \
  --source inputs/Pantaloons_Apr_2026.xlsx \
  --master inputs/Backend_Data_-_Store_Master.xlsx \
  --output outputs/Pantaloons_Updated_Master_<date>.xlsx \
  --brand Pantaloons
```

## Adding a new brand

1. Add the brand to `engine/brands.py` (`BRANDS` dict) with its
   `scope_column`, `scope_value`, default `sheet`, `header_row`, and
   `sheet_overridable` flag.
2. If the brand's reference sheet maps multiple targets to one source
   column or has a known correction, add it to `engine/brand_overrides.py`
   under a `BrandOverride(field_overrides=[...])` entry.
3. If two source columns should be flagged when their values diverge
   (PF's two `ASP Code` columns, e.g.) add a `divergence_warnings`
   entry. Column references can be 1-indexed integers or names.
4. Run `python -m engine.cli --brand-name <NewBrand> ...` and check
   the change report. Use the verifier to make sure no rule type was
   misclassified.

## Engine design choices worth knowing

- **Coerce-and-compare canonicaliser** (`engine/reconciler.py::_canonical`)
  collapses cosmetic differences before comparing two values:
  - numeric strings → numbers (`'27000'` == `27000`)
  - dates / date-shaped strings → ISO date (`'Jul-17'` == `2017-07-01`)
  - strings → stripped, underscore→space, casefolded
    (`'Uttar_Pradesh'` == `'Uttar Pradesh'`)
  Output writes the source value verbatim — the canonicaliser is only
  used to decide whether a write is necessary.

- **Anchor adjacency** (`engine/mapper.py::_resolve_column`) resolves
  duplicate source columns by picking the smallest column index strictly
  greater than the *anchor*. The anchor is the index of the most
  recently resolved *unique-name* COLUMN rule. Ambiguous resolutions
  don't advance the anchor, so the reference can jump backwards in
  column order without chasing past the next unique anchor (TASVA's
  ARM-before-RM ordering).

- **EMPTY vs PRESERVE_FROM_MASTER**: EMPTY only blanks the master when
  the master is itself already empty; otherwise the curated master
  value is preserved. PRESERVE always keeps the master value. The
  reference's "Keep empty" remark drives EMPTY; "Don't have the column"
  and "keep the existing data" drive PRESERVE.

- **Excel serial dates**: pyxlsb hands back numeric serials. The mapper
  post-pass converts numeric values in the 25569–73050 range (1970-01-01
  to 2100-01-01) to native datetimes, but only for target fields in
  `_DATE_FIELDS = {"Store Opening Date"}`.

- **Isactive / Dailychecklist access**: forced to UPPER on the mapper's
  output, regardless of the reference's literal (`YES` / `NO`).

## Cross-filesystem note (sandbox dev only)

The harness used during development sometimes truncates files on the
Windows-mounted volume mid-write.  If a file looks shorter than
expected or fails to import:

```sh
python - <<'PY'
import os
for fn in os.listdir('engine'):
    fp = f'engine/{fn}'
    if not fn.endswith('.py'): continue
    with open(fp, 'rb') as f: data = f.read()
    if b'\x00' in data:
        data = data.rstrip(b'\x00').rstrip() + b'\n'
        with open(fp, 'wb') as f: f.write(data)
        print('cleaned', fn)
PY
```

This isn't an engine bug — strictly an artifact of the dev environment.
