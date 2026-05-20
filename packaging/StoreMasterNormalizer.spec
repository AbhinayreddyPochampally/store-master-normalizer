# PyInstaller spec for the Store Master Normalizer (--onefile build).
#
# Build (from the repo root, on Windows)::
#
#     pyinstaller --clean --noconfirm packaging\StoreMasterNormalizer.spec
#
# Output: dist\StoreMasterNormalizer.exe

# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

HERE = Path(SPECPATH).resolve()
ROOT = HERE.parent

block_cipher = None

HIDDEN = [
    # Spreadsheet I/O.
    "openpyxl", "openpyxl.cell._writer",
    "et_xmlfile",
    "pyxlsb", "pyxlsb.workbook", "pyxlsb.worksheet", "pyxlsb.records",
    # Web framework.
    "fastapi",
    "starlette", "starlette.templating",
    "jinja2", "markupsafe",
    "python_multipart", "multipart",
    # ASGI server.
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    # Async transport.
    "anyio", "anyio._backends._asyncio",
    "sniffio", "h11", "idna", "click", "certifi",
    # Our own packages.  v0.4.1 added engine.dates and engine.remarks.
    "engine", "engine.reference_reader", "engine.source_loader",
    "engine.mapper", "engine.reconciler", "engine.brand_overrides",
    "engine.cli", "engine.verifier", "engine.brands",
    "engine.dates", "engine.remarks",
    "web", "web.app", "web.brand_config", "web.run",
]


a = Analysis(
    [str(ROOT / "web" / "run.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "web" / "templates"), "web/templates"),
        (str(ROOT / "web" / "static"),    "web/static"),
        # brands.json seed.  At runtime, load_brands() copies this to
        # the folder next to the EXE on first launch and then leaves it
        # alone -- the external copy is the source of truth.
        (str(ROOT / "brands.json"),       "."),
    ],
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib", "PIL",
        "numpy", "pandas", "scipy",
        "playwright",
        "test", "tests",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# --onefile mode: everything goes into the single EXE.  No COLLECT step.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="StoreMasterNormalizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(HERE / "icon.ico"),
)
