# PyInstaller spec for the Store Master Normalizer.
#
# Build with::
#
#     pyinstaller packaging\StoreMasterTool.spec --noconfirm
#
# Output lands under dist\StoreMasterTool\.

# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

HERE = Path(SPECPATH).resolve()
ROOT = HERE.parent

block_cipher = None


a = Analysis(
    [str(HERE / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Bundle templates and static assets alongside the entry script.
        (str(ROOT / "web" / "templates"), "web/templates"),
        (str(ROOT / "web" / "static"),    "web/static"),
        # We also ship the engine package as data so Python finds it after
        # PyInstaller's --onedir rewrite (templates reference engine
        # version via app context).
    ],
    hiddenimports=[
        # FastAPI/Starlette wired imports.
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # Engine modules are imported via strings from cli/verifier.
        "engine.reference_reader",
        "engine.source_loader",
        "engine.mapper",
        "engine.reconciler",
        "engine.brand_overrides",
        "engine.cli",
        "engine.verifier",
        "engine.brands",
        "web.app",
        "web.brand_config",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "PIL",
        "numpy",
        "pandas",
        "scipy",
        "test",
        "tests",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StoreMasterTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # Windowed (no console flash) for non-tech users.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(HERE / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StoreMasterTool",
)
