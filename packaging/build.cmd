@echo off
REM Build the Store Master Normalizer Windows installer.
REM Run from the repo root.  Requires:
REM   * Python 3.10+ on PATH
REM   * PyInstaller installed (pip install pyinstaller)
REM   * Inno Setup 6 on PATH (ISCC.exe) -- get it from
REM     https://jrsoftware.org/isdl.php

setlocal
pushd "%~dp0\.."

echo === Installing/upgrading runtime dependencies ===
python -m pip install --upgrade --quiet -r requirements.txt
python -m pip install --upgrade --quiet pyinstaller

echo.
echo === Building PyInstaller bundle ===
python -m PyInstaller packaging\StoreMasterTool.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo [BUILD FAILED] PyInstaller stopped with errors.
    popd
    exit /b 1
)

echo.
echo === Building Inno Setup installer ===
where ISCC >nul 2>nul
if errorlevel 1 (
    echo.
    echo [SKIP] ISCC.exe is not on PATH.  Install Inno Setup 6 from
    echo        https://jrsoftware.org/isdl.php then re-run this script,
    echo        or run:    ISCC packaging\setup.iss
    popd
    exit /b 2
)
ISCC packaging\setup.iss

echo.
echo Done.  Installer is at dist\StoreMasterTool-Setup.exe.
popd
endlocal
