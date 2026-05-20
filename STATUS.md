# STATUS — v0.5.1 Pre-fix Audit (2026-05-19)

Engine version on disk: **0.6.0** (`engine/__init__.py:3`).

The user-supplied spec describes a Next.js + Electron app; the actual codebase is
**Python + FastAPI + PyInstaller** (entry `web/run.py`, spec
`packaging/StoreMasterNormalizer.spec`, EXE at `dist/StoreMasterNormalizer.exe`).
The v0.5.1 fixes below are implemented in Python; the .exe is rebuilt via
PyInstaller, not electron-builder.

## Phase 1 checklist — current state

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Output has 44 columns with `ID` at pos 1 and `Title` at pos 44 | ❌ FAIL | `engine/brands.py:39-51` `MASTER_FIELDS` lists 42 columns. No `ID`, no `Title`. |
| 2 | Every Tasva row has `Business = "Ethnic Business"` | ❌ FAIL | `brands.json:626-631` TASVA `Business` rule is `EMPTY` / `source_value: null`. The string "Ethnic Business" is wired to `Organization` instead. |
| 3 | Every Tasva row has `Region` in ALL CAPS | ❌ FAIL | `brands.json:632-637` TASVA `Region` has `"transform": ""` (no `upper`). |
| 4 | `Store Zone ∈ {SOUT, NRTH, WEST, EAST}` (4-letter, all caps) | ✅ PASS | `engine/mapper.py:122-127` `_ZONE_PREFIX = {"SOUTH":"SOUT","NORTH":"NRTH","EAST":"EAST","WEST":"WEST"}`. Already 4-letter caps. |
| 5 | `Isactive == Dailychecklist access` on every row | ⚠️ PARTIAL | Paired in REACTIVATED (`reconciler.py:343-360`), NEW (`:462-465`), and inactivation passes (`:542-544, 586-588`). **Missing one-time sweep** to repair legacy rows like 12026 that already disagree. |
| 6 | `Title = Store Id` on every row | ❌ FAIL | No `Title` target field, no `mirror` transform in `engine/mapper.py:182-209`. |
| 7 | `ID` preserved from backend (no engine writes) | ❌ FAIL | `ID` not in `MASTER_FIELDS`, not in `brands.json`. Currently it'd be dropped on output. |
| 8 | Store 12026 not in contradiction state `NO/YES` | ⚠️ DATA | Current fixture has 12026 = `YES/YES`, but missing from client active list (should become `NO/NO`). No engine sweep would fix it. |
| 9 | New stores have `Business` populated | ❌ FAIL | Tied to check 2 above; constants block doesn't set `Business` for TASVA. |
| 10 | Cascade Step 2 MIGRATED fires | ✅ implemented | `reconciler.py:379-409`, status `CODE_CHANGED`, uses `by_old_sapcode` lookup. Untested — added in F7. |
| 11 | Cascade Step 3 REACTIVATED fires | ✅ implemented | `reconciler.py:327-372`, status `REACTIVATED`, flips both flags to YES. Untested — added in F7. |

## Transforms inventory (`engine/mapper.py:182-209`)

Present: `upper`, `lower`, `title`, `strip`, `int`, `isoDate` (alias `iso_date`),
`phoneClean` (alias `phone_clean`).
Missing: `mirror`. Added in F5.

## Other findings

- **No `tests/` directory.** Glob for `tests/**/*.py` and `**/test_*.py` returns nothing. All F1-F8 work needs new tests created from scratch.
- **PyInstaller spec** (`packaging/StoreMasterNormalizer.spec`) already lists every `engine.*` submodule under `HIDDEN`. New module `engine.tasva_check` will need to be added.
- **Existing EXE** `dist/StoreMasterNormalizer.exe` — 17.7 MB, built 2026-05-14. Will be replaced by a fresh PyInstaller build (needs Windows host; build instructions in `BUILD.md` already cover this).

## What's already good, skipped in Phase 3

- F4 (Store Zone 4-letter mapping) — `_ZONE_PREFIX` already correct.
- Cascade structure — Steps 1-4 + post-cascade inactivation pass all implemented.
- Most transforms used by F1/F2/F3 already exist; only `mirror` needs adding.
