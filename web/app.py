"""FastAPI front end for the store-master normalizer.

Run locally with::

    python -m uvicorn web.app:app --host 127.0.0.1 --port 8000

Routes
------
GET  /                    -- form
POST /convert             -- accepts uploaded source + master, runs engine,
                             returns HTML partial with results
GET  /download/{filename} -- serves files from temp/
"""
from __future__ import annotations

import os
import shutil
import sys
import traceback
import uuid
from collections import Counter
from datetime import date as _date
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Make the engine importable when running from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engine.reference_reader import get_mapping_for_brand, Rule  # noqa: E402
from engine.source_loader import (                        # noqa: E402
    load_source, list_sheets, sheet_has_data,
)
from engine.mapper import map_all                         # noqa: E402
from engine.brand_overrides import get as get_overrides   # noqa: E402
from engine.reconciler import reconcile                   # noqa: E402
from engine.cli import (                                  # noqa: E402
    _load_master,
    _check_divergences,
    _write_updated_master,
    _write_change_report,
    make_output_paths,
    _format_month_label,
)
from engine.reconciler import apply_inactivation_pass     # noqa: E402
from engine.verifier import verify_conversion             # noqa: E402

from engine.brands import load_brands, load_backend_config  # noqa: E402
import engine as _engine                                  # noqa: E402


# Path resolution: works both in development (paths relative to this
# file) and in PyInstaller --onefile builds (sys._MEIPASS holds the
# unpacked bundle).
import tempfile as _tempfile

if getattr(sys, "frozen", False):
    # PyInstaller --onefile -> bundle dir is sys._MEIPASS, e.g.
    # C:\Users\<user>\AppData\Local\Temp\_MEI12345\.
    _BUNDLE = Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    HERE = _BUNDLE / "web"
    # _MEIPASS is wiped on exit, so temp/ MUST live elsewhere.  Prefer
    # a folder next to the EXE so the operator can find downloaded
    # outputs; fall back to the OS temp dir if the EXE folder is
    # read-only (e.g. on a network share).
    _EXE_DIR = Path(sys.executable).resolve().parent
    _CANDIDATE = _EXE_DIR / "StoreMasterNormalizer-temp"
    try:
        _CANDIDATE.mkdir(parents=True, exist_ok=True)
        _t = _CANDIDATE / ".write-test"
        _t.touch()
        _t.unlink()
        TEMP_DIR = _CANDIDATE
    except OSError:
        TEMP_DIR = Path(_tempfile.gettempdir()) / "StoreMasterNormalizer-temp"
else:
    HERE = Path(__file__).resolve().parent
    TEMP_DIR = _REPO_ROOT / "temp"

TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))
STATIC_DIR = HERE / "static"

# In-memory registry of completed runs.  Keyed by run_id, holds the inputs
# and outputs needed for a subsequent /verify call.  Cleared on app start
# (the temp/ wipe drops the files; we just hold a dict alongside).
RUNS: Dict[str, Dict[str, Any]] = {}

# Recent-runs registry surfaced on the home page so closing the tab
# doesn't lose access to the consolidated master / change reports.
# Lives in-process (terminal-scoped); the temp/ wipe on EXE restart
# drops the files, so we don't need to persist this to disk.
RECENT_RUNS: List[Dict[str, Any]] = []
_RECENT_LIMIT = 8



def _clear_temp() -> None:
    """Wipe temp/ on app start so stale files don't accumulate."""
    if TEMP_DIR.exists():
        for p in TEMP_DIR.iterdir():
            try:
                if p.is_file() or p.is_symlink():
                    p.unlink()
                elif p.is_dir():
                    shutil.rmtree(p)
            except OSError:
                pass
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


_clear_temp()

app = FastAPI(title="Store Master Normalizer")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# -- Helpers --------------------------------------------------------------

def _save_upload(upload: UploadFile, slug: str) -> Path:
    """Write an UploadFile into temp/ under a unique-ish filename."""
    safe_name = Path(upload.filename or "upload").name
    out = TEMP_DIR / f"{slug}__{safe_name}"
    with out.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return out


def _run_engine(*, source_path: Path, master_path: Path, brand_key: str,
                sheet_override: Optional[str], run_id: str,
                month_label: Optional[str] = None) -> Dict[str, Any]:
    """Execute the engine end-to-end and return everything the UI needs."""
    cfg = load_brands()[brand_key]
    # v0.4.1 B6: TCNS-style brands accept a sheet override.  When the
    # user leaves the input blank we fall back to cfg.sheet (the
    # configured default), but surface that choice via the warnings
    # block so it's never silent.
    if cfg["sheet_overridable"]:
        if sheet_override:
            sheet = sheet_override
            sheet_source = "user-supplied"
        else:
            sheet = cfg["sheet"]
            sheet_source = "default"
    else:
        sheet = cfg["sheet"]
        sheet_source = "fixed"

    rules: List[Rule] = get_mapping_for_brand(brand_key)
    overrides = get_overrides(brand_key)

    source_sheet = load_source(str(source_path), sheet, int(cfg["header_row"]))

    warnings: List[str] = []
    if sheet_source == "default" and cfg["sheet_overridable"]:
        # v0.4.1 B6: explicit surfacing of the default-sheet choice.
        warnings.append(
            f"No sheet override supplied for {cfg.get('label', brand_key)!r}; "
            f"using default sheet {sheet!r}.  If your workbook's most "
            f"recent month sheet is named differently, set the sheet "
            f"override on the Setup form."
        )
    mapped, map_warnings = map_all(rules, source_sheet)
    warnings.extend(map_warnings)
    _check_divergences(source_sheet, mapped, overrides, warnings,
                       brand_label=cfg.get("label", brand_key))

    master_rows, master_field_order = _load_master(str(master_path))
    result = reconcile(
        rules=rules,
        mapped_rows=mapped,
        master_rows=master_rows,
        master_field_order=master_field_order,
        scope_column=cfg["scope_column"],
        scope_value=cfg["scope_value"],
        month_label=month_label,
    )

    # v0.4.1 B2: Section 6 inactivation pass.
    apply_inactivation_pass(
        result=result,
        brand_label=cfg.get("label", brand_key),
        brand_label_short=brand_key,
        month_label=month_label,
    )
    warnings.extend(result.warnings)

    # v0.4.1 A5: filename = "<Brand>_Updated_Master_<Month-YYYY>.xlsx",
    # no random hash.  The web layer may serve concurrent runs, so to
    # avoid collisions we stage each run under a per-run subdirectory
    # named with run_id; the user-facing filename inside it is clean.
    brand_slug = brand_key.replace(" ", "_")
    run_dir = TEMP_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    updated_path_str, report_path_str = make_output_paths(
        str(run_dir), brand_slug, month_label,
    )
    updated_path = Path(updated_path_str)
    report_path = Path(report_path_str)
    updated_name = updated_path.name
    report_name = report_path.name

    _write_updated_master(str(updated_path), result.updated_master, master_field_order)
    _write_change_report(
        str(report_path),
        summary=result.summary,
        changes=result.changes,
        source_total=len(mapped),
        matched=result.matched_source_count,
        unmatched=result.unmatched_source_count,
        orphan=result.orphan_source_count,
        warnings=warnings,
    )

    # v0.4.1 C3: per-field stats for the brand-analytics table.  We
    # surface count + a representative sample change ("Store Id:
    # before -> after") so the operator can grok what the field's
    # diffs look like without opening the change report.
    fc: Counter = Counter()
    samples: Dict[str, str] = {}
    for c in result.changes:
        if c.status != "UPDATED":
            continue
        fc[c.field_changed] += 1
        if c.field_changed not in samples:
            samples[c.field_changed] = (
                f"{c.store_id}: {c.old_value!r} → {c.new_value!r}"
            )
    top_fields = [
        (f, n, samples.get(f, "")) for f, n in fc.most_common(10)
    ]

    RUNS[run_id] = {
        "source_path": str(source_path),
        "master_path": str(master_path),
        "updated_path": str(updated_path),
        "report_path": str(report_path),
        "brand_key": brand_key,
        "sheet": sheet,
    }
    return {
        "run_id": run_id,
        "summary": result.summary,
        "matched_source_count": result.matched_source_count,
        "unmatched_source_count": result.unmatched_source_count,
        "orphan_source_count": result.orphan_source_count,
        "source_total": len(mapped),
        "warnings": warnings,
        "top_fields": top_fields,
        "updated_file": updated_name,
        "report_file": report_name,
        "brand_label": cfg["label"],
        "sheet_used": sheet,
        "sheet_source": sheet_source,
    }


# -- Routes ---------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return TEMPLATES.TemplateResponse(
        request=request, name="index.html",
        context={
            "brands": load_brands(),
            "backend_cfg": load_backend_config(),
            "engine_version": getattr(_engine, "__version__", "?"),
            "recent_runs": RECENT_RUNS,
        },
    )


# -- v0.5.2: per-row sheet validation (onBlur) ---------------------------

@app.post("/validate-sheet")
async def validate_sheet(
    file: UploadFile = File(...),
    sheet: str = Form(...),
    header_row: int = Form(1),
):
    """Cheap pre-flight: confirm ``sheet`` exists in the uploaded workbook
    and has at least one data row beyond the header.  Returns JSON the UI
    renders inline under the upload row.

    Response::

        { "ok": true,
          "available_sheets": ["...", "..."],
          "has_data": true,
          "first_sheet": "Sheet1" }

    On error, ``ok`` is false and an ``error`` field carries the message.
    The endpoint never raises -- it always returns 200 with the diagnosis,
    so the UI can render the message directly.
    """
    tmp_path = TEMP_DIR / f"validate_{uuid.uuid4().hex[:8]}__{Path(file.filename or 'upload').name}"
    try:
        with tmp_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            sheets = list_sheets(str(tmp_path))
        except Exception as exc:
            return JSONResponse({
                "ok": False,
                "error": f"Could not open workbook: {exc}",
                "available_sheets": [],
                "has_data": False,
                "first_sheet": None,
            })
        first = sheets[0] if sheets else None
        wanted = (sheet or "").strip()
        if not wanted:
            return JSONResponse({
                "ok": False,
                "error": "Sheet name is required.",
                "available_sheets": sheets,
                "has_data": False,
                "first_sheet": first,
            })
        if wanted not in sheets:
            return JSONResponse({
                "ok": False,
                "error": (
                    f"Sheet {wanted!r} not found in {Path(file.filename or '').name!r}. "
                    f"Available: {', '.join(repr(s) for s in sheets)}."
                ),
                "available_sheets": sheets,
                "has_data": False,
                "first_sheet": first,
            })
        try:
            has_data = sheet_has_data(str(tmp_path), wanted, int(header_row))
        except Exception:
            has_data = False
        if not has_data:
            return JSONResponse({
                "ok": False,
                "error": (
                    f"Sheet {wanted!r} in {Path(file.filename or '').name!r} "
                    f"has no data rows."
                ),
                "available_sheets": sheets,
                "has_data": False,
                "first_sheet": first,
            })
        return JSONResponse({
            "ok": True,
            "available_sheets": sheets,
            "has_data": True,
            "first_sheet": first,
        })
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


@app.post("/convert", response_class=HTMLResponse)
async def convert(
    request: Request,
    brand: str = Form(...),
    sheet: Optional[str] = Form(None),
    month: Optional[str] = Form(None),
    source: UploadFile = File(...),
    master: UploadFile = File(...),
):
    if brand not in load_brands():
        return TEMPLATES.TemplateResponse(
            request=request, name="_error.html",
            context={"message": f"Unknown brand {brand!r}."},
            status_code=400,
        )

    run_slug = uuid.uuid4().hex[:8]
    try:
        source_path = _save_upload(source, slug=f"src_{run_slug}")
        master_path = _save_upload(master, slug=f"master_{run_slug}")
    except Exception as exc:
        return TEMPLATES.TemplateResponse(
            request=request, name="_error.html",
            context={"message": f"Could not save uploaded files: {exc}"},
            status_code=500,
        )

    try:
        result = _run_engine(
            source_path=source_path,
            master_path=master_path,
            brand_key=brand,
            sheet_override=sheet.strip() if sheet else None,
            run_id=run_slug,
            month_label=(month or None),
        )
    except Exception as exc:
        tb = traceback.format_exc(limit=4)
        return TEMPLATES.TemplateResponse(
            request=request, name="_error.html",
            context={"message": f"{type(exc).__name__}: {exc}", "trace": tb},
            status_code=500,
        )

    return TEMPLATES.TemplateResponse(
        request=request, name="_results.html",
        context={"r": result},
    )


@app.get("/download/{run_id}/{filename}")
def download(run_id: str, filename: str):
    # v0.4.1 A5: outputs are staged under temp/<run_id>/<filename>.
    safe_run = Path(run_id).name
    safe_name = Path(filename).name
    path = TEMP_DIR / safe_run / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(
        str(path),
        filename=safe_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/download/{filename}")
def download_legacy(filename: str):
    """Backwards-compat: pre-v0.4.1 download links omitted run_id."""
    safe_name = Path(filename).name
    # Search every run directory for a matching file.
    if TEMP_DIR.exists():
        for run_dir in TEMP_DIR.iterdir():
            cand = run_dir / safe_name if run_dir.is_dir() else None
            if cand and cand.exists() and cand.is_file():
                return FileResponse(
                    str(cand),
                    filename=safe_name,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
        # Pre-A5 flat layout
        flat = TEMP_DIR / safe_name
        if flat.exists() and flat.is_file():
            return FileResponse(
                str(flat), filename=safe_name,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
    raise HTTPException(status_code=404, detail="file not found")


@app.post("/verify", response_class=HTMLResponse)
def verify(request: Request, run_id: str = Form(...)):
    state = RUNS.get(run_id)
    if state is None:
        return TEMPLATES.TemplateResponse(
            request=request, name="_error.html",
            context={"message": f"Unknown run_id {run_id!r}; try converting again."},
            status_code=404,
        )
    try:
        report = verify_conversion(
            source_path=state["source_path"],
            master_path=state["master_path"],
            output_path=state["updated_path"],
            brand_key=state["brand_key"],
            sheet_name=state["sheet"],
        )
    except Exception as exc:
        tb = traceback.format_exc(limit=4)
        return TEMPLATES.TemplateResponse(
            request=request, name="_error.html",
            context={"message": f"{type(exc).__name__}: {exc}", "trace": tb},
            status_code=500,
        )
    return TEMPLATES.TemplateResponse(
        request=request, name="_verify.html",
        context={"v": report, "by_rule_type": list(report.mismatches_by_rule_type.most_common()),
                 "by_field": list(report.mismatches_by_field.most_common(10)),
                 "by_row_type": list(report.mismatches_by_row_type.most_common())},
    )


# -- Multi-brand reconciliation -----------------------------------------

@app.post("/reconcile", response_class=HTMLResponse)
async def reconcile_route(request: Request):
    """v0.4.1 (post-mockup): every selected brand is folded into a SINGLE
    consolidated master.  The flow:

        1. Load the uploaded backend master into memory once.
        2. For each brand with a file: run the cascade + inactivation pass
           against the current state of master_rows.  The result's
           `updated_master` carries that brand's edits forward; we use it
           as the input for the next brand.  Per-brand changes are written
           to one Change Report each.
        3. After all brands have folded in, write ONE Consolidated_Master
           file at the end -- not one per brand.

    Brand-partitioning in the reconciler guarantees brand B never mutates
    brand A's rows, so threading the master forward is safe.

    Form fields:
        brand_keys              -- list of brand keys (hidden per row)
        source__<brand_key>     -- file upload per brand row
        sheet_override__<brand_key>  -- optional, only for sheet_overridable brands
        master                  -- backend master xlsx
        month                   -- optional label
    """
    form = await request.form()
    brand_keys = form.getlist("brand_keys") or []
    if not brand_keys:
        return TEMPLATES.TemplateResponse(
            request=request, name="_error.html",
            context={"message": "No brand rows submitted."},
            status_code=400,
        )

    brands = load_brands()
    master_field = form.get("master")
    if master_field is None or not getattr(master_field, "filename", None):
        return TEMPLATES.TemplateResponse(
            request=request, name="_error.html",
            context={"message": "Please upload the backend master."},
            status_code=400,
        )

    # Save the master once; load it once.
    run_slug = uuid.uuid4().hex[:8]
    month_label = (form.get("month") or "").strip() or None

    # v0.5.2: Backend Master sheet is now picker-overridable.  Priority:
    #   1. ``sheet_override__backend`` from the form (operator's choice)
    #   2. ``_backend.default_sheet`` from brands.json
    #   3. Hardcoded fallback "Backend Updated Data" (load_backend_config()).
    backend_cfg = load_backend_config()
    backend_sheet_override = (form.get("sheet_override__backend") or "").strip() or None
    backend_sheet = backend_sheet_override or backend_cfg.get("default_sheet")

    try:
        master_path = _save_upload(master_field, slug=f"master_{run_slug}")
    except Exception as exc:
        return TEMPLATES.TemplateResponse(
            request=request, name="_error.html",
            context={"message": f"Could not save master: {exc}"},
            status_code=500,
        )

    # Pre-flight: surface a clean inline error if the chosen backend sheet
    # is not in the workbook, instead of letting the engine raise mid-run.
    try:
        backend_sheets = list_sheets(str(master_path))
    except Exception as exc:
        return TEMPLATES.TemplateResponse(
            request=request, name="_error.html",
            context={"message": f"Could not open backend master: {exc}"},
            status_code=400,
        )
    if backend_sheet not in backend_sheets:
        return TEMPLATES.TemplateResponse(
            request=request, name="_error.html",
            context={"message": (
                f"Backend Master: sheet {backend_sheet!r} not found in "
                f"{Path(master_field.filename or 'workbook').name!r}. "
                f"Available: {', '.join(repr(s) for s in backend_sheets)}."
            )},
            status_code=400,
        )

    master_rows, master_field_order = _load_master(str(master_path), backend_sheet)
    run_dir = TEMP_DIR / run_slug
    run_dir.mkdir(parents=True, exist_ok=True)

    per_brand_results: List[Dict[str, Any]] = []
    aggregate = {
        "source_rows": 0,
        "master_in_scope": 0,
        "new": 0,
        "updated": 0,
        "code_changed": 0,
        "closed": 0,
        "warnings": 0,
        "fields_changed": set(),
        "brands_run": [],
    }

    for key in brand_keys:
        if key not in brands:
            continue
        upload = form.get(f"source__{key}")
        if upload is None or not getattr(upload, "filename", None):
            continue  # skip brands with no file
        cfg = brands[key]
        sheet_override = (form.get(f"sheet_override__{key}") or "").strip() or None
        if cfg["sheet_overridable"]:
            sheet = sheet_override or cfg["sheet"]
            sheet_source = "user-supplied" if sheet_override else "default"
        else:
            sheet = cfg["sheet"]
            sheet_source = "fixed"

        try:
            source_path = _save_upload(upload, slug=f"src_{run_slug}_{key}")
        except Exception as exc:
            return TEMPLATES.TemplateResponse(
                request=request, name="_error.html",
                context={"message": f"Saving {cfg['label']} upload failed: {exc}"},
                status_code=500,
            )

        # v0.5.2: pre-flight sheet check.  Bail out with a clean inline
        # error naming the available sheets, rather than letting the
        # engine raise a KeyError several frames deep.
        try:
            available = list_sheets(str(source_path))
        except Exception as exc:
            return TEMPLATES.TemplateResponse(
                request=request, name="_error.html",
                context={"message": (
                    f"{cfg['label']}: could not open workbook "
                    f"{Path(upload.filename or '').name!r}: {exc}"
                )},
                status_code=400,
            )
        if sheet not in available:
            return TEMPLATES.TemplateResponse(
                request=request, name="_error.html",
                context={"message": (
                    f"{cfg['label']}: sheet {sheet!r} not found in "
                    f"{Path(upload.filename or '').name!r}. "
                    f"Available: {', '.join(repr(s) for s in available)}."
                )},
                status_code=400,
            )

        per_brand_warnings: List[str] = []
        try:
            rules: List[Rule] = get_mapping_for_brand(key)
            overrides = get_overrides(key)
            source_sheet = load_source(str(source_path), sheet, int(cfg["header_row"]))
            if sheet_source == "default" and cfg["sheet_overridable"]:
                per_brand_warnings.append(
                    f"No sheet override supplied for {cfg.get('label', key)!r}; "
                    f"using default sheet {sheet!r}."
                )
            mapped, map_warnings = map_all(rules, source_sheet)
            per_brand_warnings.extend(map_warnings)
            _check_divergences(source_sheet, mapped, overrides, per_brand_warnings,
                               brand_label=cfg.get("label", key))

            # Reconcile against the SHARED in-memory master, then thread
            # the result forward as the new master for the next brand.
            result = reconcile(
                rules=rules,
                mapped_rows=mapped,
                master_rows=master_rows,
                master_field_order=master_field_order,
                scope_column=cfg["scope_column"],
                scope_value=cfg["scope_value"],
                month_label=month_label,
            )
            apply_inactivation_pass(
                result=result,
                brand_label=cfg.get("label", key),
                brand_label_short=key,
                month_label=month_label,
            )
            per_brand_warnings.extend(result.warnings)
            master_rows = result.updated_master   # thread forward
        except Exception as exc:
            tb = traceback.format_exc(limit=4)
            return TEMPLATES.TemplateResponse(
                request=request, name="_error.html",
                context={"message": f"{cfg['label']}: {type(exc).__name__}: {exc}",
                         "trace": tb},
                status_code=500,
            )

        # Write THIS brand's change report (no per-brand master file).
        brand_slug = key.replace(" ", "_")
        _, report_path_str = make_output_paths(str(run_dir), brand_slug, month_label)
        _write_change_report(
            report_path_str,
            summary=result.summary,
            changes=result.changes,
            source_total=len(mapped),
            matched=result.matched_source_count,
            unmatched=result.unmatched_source_count,
            orphan=result.orphan_source_count,
            warnings=per_brand_warnings,
        )

        # Per-field stats for the analytics table (UPDATED only, with sample).
        fc: Counter = Counter()
        samples: Dict[str, str] = {}
        for c in result.changes:
            if c.status != "UPDATED":
                continue
            fc[c.field_changed] += 1
            if c.field_changed not in samples:
                samples[c.field_changed] = (
                    f"{c.store_id}: {c.old_value!r} → {c.new_value!r}"
                )
        top_fields = [(f, n, samples.get(f, "")) for f, n in fc.most_common(10)]

        brand_run_id = f"{run_slug}_{key}"
        RUNS[brand_run_id] = {
            "source_path": str(source_path),
            "master_path": str(master_path),
            "updated_path": "",  # consolidated; per-brand verify not yet wired
            "report_path": report_path_str,
            "brand_key": key,
            "sheet": sheet,
        }

        r = {
            "run_id": brand_run_id,
            "summary": result.summary,
            "matched_source_count": result.matched_source_count,
            "unmatched_source_count": result.unmatched_source_count,
            "orphan_source_count": result.orphan_source_count,
            "source_total": len(mapped),
            "warnings": per_brand_warnings,
            "top_fields": top_fields,
            "report_file": Path(report_path_str).name,
            "brand_label": cfg["label"],
            "brand_key": key,
            "sheet_used": sheet,
            "sheet_source": sheet_source,
        }
        per_brand_results.append(r)
        aggregate["source_rows"]    += r["source_total"]
        aggregate["new"]            += r["summary"].get("NEW", 0)
        aggregate["updated"]        += r["summary"].get("UPDATED", 0)
        aggregate["code_changed"]   += r["summary"].get("CODE_CHANGED", 0) or 0
        aggregate["closed"]         += r["summary"].get("CLOSED", 0)
        aggregate["warnings"]       += len(r["warnings"])
        aggregate["brands_run"].append(cfg["label"])
        for tup in r["top_fields"]:
            aggregate["fields_changed"].add(tup[0])

    if not per_brand_results:
        return TEMPLATES.TemplateResponse(
            request=request, name="_error.html",
            context={"message": "Tick at least one brand and upload its file."},
            status_code=400,
        )

    # ---- Consolidated master write ----
    # All brand passes are done; `master_rows` now holds every brand's
    # edits.  Emit ONE master file, normalised (ISO dates, int pincodes,
    # see _write_updated_master).  Filename uses the month label.
    consolidated_label = _format_month_label(month_label)
    consolidated_name = f"Consolidated_Master_{consolidated_label}.xlsx"
    consolidated_path = run_dir / consolidated_name
    _write_updated_master(str(consolidated_path), master_rows, master_field_order)

    # In-scope master row totals -- counted against the FINAL consolidated
    # master so the post-run figures are accurate.
    in_scope_by_brand: Dict[str, int] = {}
    for key in brand_keys:
        if key not in brands:
            continue
        if brands[key]["label"] not in [r["brand_label"] for r in per_brand_results]:
            continue
        cfg = brands[key]
        col = cfg["scope_column"]; val = cfg["scope_value"]
        n = sum(1 for r in master_rows if r.get(col) == val)
        in_scope_by_brand[brands[key]["label"]] = n
    aggregate["master_in_scope"] = sum(in_scope_by_brand.values())
    aggregate["fields_changed"] = len(aggregate["fields_changed"])
    aggregate["consolidated_file"] = consolidated_name
    aggregate["consolidated_run_id"] = run_slug

    # ---- Record the run for the home-page Recent runs panel ----
    import datetime as _dt2
    RECENT_RUNS.insert(0, {
        "run_id": run_slug,
        "completed_at": _dt2.datetime.now().strftime("%H:%M"),
        "completed_on": _dt2.datetime.now().strftime("%b %d"),
        "month": month_label or consolidated_label,
        "brands": [r["brand_label"] for r in per_brand_results],
        "brand_count": len(per_brand_results),
        "consolidated_file": consolidated_name,
        "change_reports": [
            {"brand": r["brand_label"], "filename": r["report_file"]}
            for r in per_brand_results
        ],
    })
    del RECENT_RUNS[_RECENT_LIMIT:]

    return TEMPLATES.TemplateResponse(
        request=request, name="_multi_results.html",
        context={
            "brand_results": per_brand_results,
            "aggregate": aggregate,
            "month": month_label or "",
            "consolidated_file": consolidated_name,
            "consolidated_run_id": run_slug,
        },
    )
