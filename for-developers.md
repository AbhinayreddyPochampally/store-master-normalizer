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
  app.py                        Sys-frozen-aware paths; serves the UI
  run.py                        Single-file entry: boots uvicorn,
                                opens browser to 127.0.0.1:8000
  brand_config.py               Re-exports engine.brands.BRANDS
  templates/                    Jinja2 partials
  static/style.css              Visual tokens, layout, components
packaging/                      Windows build assets
  StoreMasterNormalizer.spec    PyInstaller --onefile spec  <-- canonical
  icon.ico
  StoreMasterTool.spec / launcher.py / setup.iss / build.cmd
                                Deprecated --onedir + Inno Setup
                                pipeline; kept for reference only.
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

This is the same entry point the packaged EXE uses. It boots uvicorn
on 127.0.0.1:8000 and opens your default browser. For headless
dev (no browser), drop in `python -m uvicorn web.app:app --port 8000`
instead.

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

## Build the Windows EXE (PyInstaller --onefile)

The packaged build is a single ``StoreMasterNormalizer.exe`` — no
installer, no admin prompt.  Build on a Windows host:

```cmd
:: From the repo root, in cmd.exe / PowerShell
python -m pip install -r requirements.txt pyinstaller
pyinstaller --clean --noconfirm packaging\StoreMasterNormalizer.spec
```

Output: ``dist\StoreMasterNormalizer.exe`` (~80–120 MB).

If you'd rather not use the spec, the equivalent one-liner is:

```cmd
pyinstaller --onefile --console --name StoreMasterNormalizer ^
  --icon packaging\icon.ico ^
  --add-data "web\templates;web/templates" ^
  --add-data "web\static;web/static" ^
  --hidden-import openpyxl --hidden-import pyxlsb ^
  --hidden-import et_xmlfile ^
  --hidden-import python_multipart --hidden-import multipart ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.http.h11_impl ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.protocols.websockets.wsproto_impl ^
  --hidden-import uvicorn.lifespan.on ^
  --hidden-import anyio._backends._asyncio ^
  web
  web\run.py
```

Either approach produces the same single-file EXE.

### Smoke test the EXE

1. Copy ``dist\StoreMasterNormalizer.exe`` to a fresh location
   (Desktop is fine).
2. Double-click it.  A console window opens with
   *"Starting Store Master Normalizer…"*; after ~5–15 seconds the
   browser opens to ``http://127.0.0.1:8000/``.
3. Drop ``inputs\Pantaloons_Apr_2026.xlsx`` and
   ``inputs\Backend_Data_-_Store_Master.xlsx`` into the form, leave
   the brand on Pantaloons, click **Convert**.
4. Confirm **UPDATED: 137**, **NEW 0**, **CLOSED 0**, **WARNINGS 0**.
5. Click **Verify output** → verdict **PASS**.
6. Quit by closing the console window.

### Common pitfalls

- **pyxlsb / openpyxl `ModuleNotFoundError`**.  Both are dynamic
  imports the static analyser misses on some PyInstaller versions.
  The spec lists them as ``hiddenimports``; if you build via the
  one-liner make sure ``--hidden-import openpyxl`` and
  ``--hidden-import pyxlsb`` are present.
- **Template / static path resolution.**  ``web/app.py`` checks
  ``sys.frozen`` and uses ``sys._MEIPASS`` to find ``templates/`` and
  ``static/`` inside the bundle.  If you copy the spec or rewrite the
  entry script, preserve that branch — assuming the cwd works in
  development but fails after packaging.
- **First-run unpack (5–15 seconds).**  ``--onefile`` extracts the
  bundle into ``%TEMP%\_MEIxxxx`` on each run.  This is expected;
  subsequent runs feel faster because Windows caches the file.
- **Windows Defender SmartScreen warning.**  Unsigned EXEs trigger a
  one-time "Windows protected your PC" dialog.  Click *More info →
  Run anyway*.  Code-signing the EXE removes this; out of scope for
  now.
- **Stale ``StoreMasterNormalizer-temp``.**  Outputs accumulate in
  the folder next to the EXE; the app clears it on startup, but if
  the user kills the process between writes the folder may grow.
  Documented in README; users can delete it freely.

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
