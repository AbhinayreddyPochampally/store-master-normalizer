"""Bootstrap entry point bundled into the Windows installer.

Responsibilities
----------------
1. Start the FastAPI app on a free local port (try 8000 first, then walk
   upward until one is free).
2. Wait until the server responds, then open the default web browser to
   http://127.0.0.1:<port>/.
3. Park a console window (hidden in the packaged build) so the server
   keeps running while the user works.  Closing the browser does NOT
   kill the server -- they can re-open the URL via the desktop shortcut
   or the system tray icon (if extended later).
4. Exit cleanly on Ctrl+C / shutdown.

This file is the PyInstaller entry script -- the icon, hidden console, and
windowed mode are set on the PyInstaller spec, not here.
"""
from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser
from contextlib import closing
from pathlib import Path

# When frozen by PyInstaller, the embedded files live next to the EXE.
# Make sure imports resolve from that bundle.
HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import uvicorn  # noqa: E402
from web.app import app  # noqa: E402


def _pick_free_port(preferred: int = 8000, ceiling: int = 8050) -> int:
    """Return the first free local port at or above `preferred`."""
    for port in range(preferred, ceiling + 1):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free port between {preferred} and {ceiling}.")


def _open_browser_when_ready(port: int) -> None:
    """Poll until the server answers, then launch the default browser."""
    import urllib.request
    url = f"http://127.0.0.1:{port}/"
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    webbrowser.open(url, new=2)


def main() -> int:
    port = _pick_free_port()
    threading.Thread(target=_open_browser_when_ready,
                     args=(port,), daemon=True).start()
    config = uvicorn.Config(app, host="127.0.0.1", port=port,
                            log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
