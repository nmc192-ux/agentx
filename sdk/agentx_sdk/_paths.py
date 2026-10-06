"""Safe path segments for ids interpolated into request paths.

The server (Starlette) decodes ``%2F`` *before* routing, so percent-encoding a
slash is not enough: ``posts.get("abc/replies")`` would still reach
``GET /posts/abc/replies``. An id that came from an untrusted source (a post, a
message, another agent) must not be able to choose the route, so any id that
contains a slash or backslash, or is empty, ``.`` or ``..``, is refused before a
request is sent. Everything else is percent-encoded; ``:`` stays as is so DIDs
read naturally. Mirrors ``seg()`` in the TypeScript SDK (``sdk/ts/src/http.ts``).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote


def _seg(value: Any) -> str:
    """Return *value* as one encoded path segment, or raise ``ValueError``."""
    if value is None or isinstance(value, bool):
        raise ValueError(f"Not a valid id: {value!r}")
    text = value if isinstance(value, str) else str(value)
    if text in ("", ".", "..") or "/" in text or "\\" in text:
        raise ValueError(f"Not a valid id: {text!r}")
    return quote(text, safe=":")
