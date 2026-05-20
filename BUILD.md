# Build `StoreMasterNormalizer.exe` (Windows)

A single console EXE that operators double-click to launch the local web
app.  No installer, no admin, no shortcut.  Drop on Desktop or in
OneDrive — works from anywhere.

## What's in the box

```
engine/                       Pure-Python reconciliation engine
web/                          FastAPI front end (run.py is the entry)
packaging/
  StoreMasterNormalizer.spec  PyInstaller --onefile spec (canonical)
  icon.ico                    Embedded icon
brands.json                   42-row mapping per brand (seeded into EXE)
requirements.txt              Pinned runtime deps
README.md / for-developers.md / demo-script.md   Operator + dev docs
```

## Build, on a Windows host

```cmd
:: From the repo root, in cmd.exe / PowerShell.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
pyinstaller --clean --noconfirm packaging\StoreMasterNormalizer.spec
```

Output: `dist\StoreMasterNormalizer.exe` (~80–120 MB; one self-contained
file).

**Requirements on the build host:** Python 3.10 or newer on PATH.
PyInstaller will be installed by the command above.

### One-liner equivalent (without the spec)

If you'd rather not use the spec:

```cmd
pyinstaller --onefile --console --name StoreMasterNormalizer ^
  --icon packaging\icon.ico ^
  --add-data "web\templates;web/templates" ^
  --add-data "web\static;web/static" ^
  --add-data "brands.json;." ^
  --hidden-import openpyxl --hidden-import pyxlsb --hidden-import et_xmlfile ^
  --hidden-import python_multipart --hidden-import multipart ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.http.h11_impl ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.protocols.websockets.wsproto_impl ^
  --hidden-import uvicorn.lifespan.on ^
  --hidden-import anyio._backends._asyncio ^
  web\run.py
```

## Smoke test the EXE

1. Copy `dist\StoreMasterNormalizer.exe` (and *only* it) to a fresh
   path, e.g. `C:\Users\<you>\Desktop\smoke-test\`.
2. Double-click.  Windows Defender SmartScreen may show *"Windows
   protected your PC"* → click **More info → Run anyway** (one-time).
3. A console window opens with:

   ```
   ============================================================
   Store Master Normalizer
   ============================================================
   Starting local server on http://127.0.0.1:8000/
   Your browser should open automatically in a second.
   Close this window to stop the tool.
   ============================================================
   ```

4. After ~5–15 s (PyInstaller unpacks to `%TEMP%\_MEIxxxx`), your
   default browser opens to <http://127.0.0.1:8000>.
5. A new file `brands.json` appears next to the EXE — this is the
   first-run seed from the bundled defaults.  The dropdowns / brand
   chips read from this file going forward; edit by hand to add or
   tweak brands.
6. Tick the brand chips you want to reconcile, drop the matching
   monthly export(s) into the dropzones, drop the backend master, click
   **Run Reconciliation**.  Expected end-to-end on the bundled inputs:

   | Brand | NEW | UPDATED | CODE_CHANGED | CLOSED | Warnings |
   |---|---:|---:|---:|---:|---:|
   | Pantaloons | 0 | 137 | 0 | 0 | 0 |
   | Planet Fashion | 0 | 48 | 0 | 0 | 8 (ASP Code divergence) |
   | TASVA | 1 | 87 | 0 | 1 | 0 |
   | TCNS | 23 | 370 | 0 | 10 | 1 (Folksong null-Store-Id) |

   Aggregate Validation Summary across all four: 1,071 source rows,
   1,523 master rows in scope, 24 new, 11 missing, 12 fields with
   changes.

7. Quit by closing the console window.

## Distributing the EXE

- **Single file** — email, OneDrive, USB stick.  ~80–120 MB.
- **No install step** — the operator double-clicks; the EXE creates a
  `StoreMasterNormalizer-temp` folder next to itself for in-flight
  uploads + generated outputs.
- **brands.json sits next to the EXE.**  Operators can hand-edit it to
  add brands or tweak mappings.  Changes take effect on the next
  conversion (no restart needed).

## Common build gotchas

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: pyxlsb` at runtime, only on TASVA uploads | Re-run with `--hidden-import pyxlsb.workbook pyxlsb.worksheet pyxlsb.records` — already in the spec. |
| `TypeError: unhashable type: 'dict'` in a template | Jinja2 ≥ 3.1.6 required. `pip install --upgrade "jinja2>=3.1.6,<4.0"` and rebuild. |
| Blank page on first launch | First launch unpack takes 5–15 s.  Wait a beat, then refresh. |
| SmartScreen blocks first launch | One-time *More info → Run anyway*.  Unblockable from the build side without code-signing. |
| `brands.json` keeps reverting to defaults | The EXE only seeds `brands.json` the first time it runs in a new folder.  If the file exists, the EXE leaves it alone. |
| EXE runs but browser doesn't open | The `webbrowser.open()` call is best-effort; manually visit <http://127.0.0.1:8000>. |
| Build is much slower than expected | First PyInstaller analysis takes ~60 s. Subsequent `--noconfirm` rebuilds reuse the cache and finish in ~15 s. |

## Source zip

For transferring the source to a clean Windows machine:
`outputs/StoreMasterNormalizer-src-<date>.zip` (70 KB).  Unzip, `cd`
in, run the build command above.
