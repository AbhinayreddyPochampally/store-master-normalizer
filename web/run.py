"""Single-file entry point for the PyInstaller ``--onefile`` build.

When PyInstaller bundles the app with ``--onefile``, ``sys._MEIPASS`` is
the temporary directory it unpacks into.  We add it to ``sys.path`` so
the embedded ``engine`` and ``web`` packages resolve, then start uvicorn
on 127.0.0.1:8000 and pop the browser open after a one-second beat.

Run directly during development::

    python -m web.run

Or via the packaged EXE::

    StoreMasterNormalizer.exe
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser

# When frozen by PyInstaller, sys._MEIPASS holds the unpacked bundle.
# Add it (and any nested 'src'-style folders) to the import path BEFORE
# we import the FastAPI app.
if getattr(sys, "frozen", False):
    bundle_root = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    if bundle_root not in sys.path:
        sys.path.insert(0, bundle_root)


def _open_browser(url: str, delay: float = 1.0) -> None:
    time.sleep(delay)
    try:
        webbrowser.open(url, new=2)
    except Exception:
        pass


def main() -> int:
    # Import after sys.path is fixed up, so frozen builds find web.app.
    import uvicorn
    from web.app import app

    host = "127.0.0.1"
    port = 8000
    url = f"http://{host}:{port}/"

    print("=" * 60)
    print("Store Master Normalizer")
    print("=" * 60)
    print(f"Starting local server on {url}")
    print("Your browser should open automatically in a second.")
    print("Close this window to stop the tool.")
    print("=" * 60)

    threading.Thread(target=_open_browser, args=(url,), daemon=True).start()

    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
