"""Re-export shims for the web app.

The canonical brand config now lives in ``engine.brands`` and is read
fresh from ``brands.json`` on every call (so newly-added brands appear
in the UI without restart).

Older code that still does ``from .brand_config import BRANDS`` gets a
snapshot at import time, which is fine for callers that don't need
live updates.
"""
from engine.brands import load_brands

# Snapshot at import time for legacy callers that index BRANDS as a dict.
# Request-time fresh reads should call ``load_brands()`` directly.
BRANDS = load_brands()

__all__ = ["BRANDS", "load_brands"]
