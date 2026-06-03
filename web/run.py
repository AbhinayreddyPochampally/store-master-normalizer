"""Entry point for the local web app.

Starts uvicorn on 127.0.0.1:8000 and opens the browser after a
one-second beat.

Run with::

    python -m web.run
"""
from __future__ import annotations

import sys
import threading
import time
import webbrowser

from engine import __version__


def _open_browser(url: str, delay: float = 1.0) -> None:
    time.sleep(delay)
    try:
        webbrowser.open(url, new=2)
    except Exception:
        pass


def main() -> int:
    # Imported lazily so uvicorn / web.app load only when the server starts.
    import uvicorn
    from web.app import app

    host = "127.0.0.1"
    port = 8000
    url = f"http://{host}:{port}/"

    print("=" * 60)
    print(f"Store Master Normalizer  v{__version__}")
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
