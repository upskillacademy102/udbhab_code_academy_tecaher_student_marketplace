"""
Resolves the SPA's built asset filenames.

Vite fingerprints its output (main-B2xK9.js), so the template cannot hard-code
a path. It writes static/app/manifest.json mapping the source entry to the
built files; this reads that and hands the shell template real URLs.

Cached in memory in production and read per-request in DEBUG, so a rebuild
from `npm run dev` shows up on the next refresh without restarting Django.

If the manifest is missing — nobody has run the build yet — this returns empty
lists and the shell renders a plain "not built" notice instead of a blank
page pointing at a 404 script.
"""

import json
from pathlib import Path

from django.conf import settings

_MANIFEST_REL = Path("app") / "manifest.json"
_ENTRY = "src/main.tsx"

_cache: dict | None = None


def _manifest_path() -> Path:
    return Path(settings.BASE_DIR) / "static" / _MANIFEST_REL


def _load() -> dict:
    path = _manifest_path()
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _manifest() -> dict:
    global _cache
    if settings.DEBUG:
        return _load()
    if _cache is None:
        _cache = _load()
    return _cache


def spa_assets() -> dict:
    """``{"js": [url, ...], "css": [url, ...], "built": bool}``."""
    manifest = _manifest()
    entry = manifest.get(_ENTRY)
    if not entry:
        return {"js": [], "css": [], "built": False}

    static_url = settings.STATIC_URL.rstrip("/")
    js, css = [], []

    def url(rel: str) -> str:
        return f"{static_url}/app/{rel}"

    # Imported chunks must load before the entry that needs them.
    for chunk_key in entry.get("imports", []):
        chunk = manifest.get(chunk_key, {})
        if chunk.get("file"):
            js.append(url(chunk["file"]))
        css.extend(url(c) for c in chunk.get("css", []))

    if entry.get("file"):
        js.append(url(entry["file"]))
    css.extend(url(c) for c in entry.get("css", []))

    return {"js": js, "css": css, "built": True}
