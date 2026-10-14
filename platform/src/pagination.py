"""
Keyset ("cursor") paging helpers — EG-2 (Neon egress).

A cursor is the sort key of the last row a client has seen, packed into an
opaque URL-safe string.  The next page is "rows that sort after that key", so
the database never re-reads skipped rows (OFFSET does) and rows inserted
while a client is paging do not shift later pages (no repeats, no gaps).

Cursors are not secrets and grant nothing: every query that takes one keeps
its own WHERE clause (owner, visibility), and the cursor only narrows it.
A cursor that does not decode to the expected shape is a 400, never a 500.
"""
from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Any, Sequence
from uuid import UUID

from fastapi import HTTPException, status

# Header carrying the next cursor on routes whose body is a bare JSON list
# (adding a body field there would break existing clients).
NEXT_CURSOR_HEADER = "X-Next-Cursor"

# Longest cursor we bother decoding (three short keys fit in ~150 chars).
_MAX_CURSOR_LEN = 512


def _to_json(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def encode_cursor(*parts: Any) -> str:
    """Pack sort-key values (datetime, UUID, str, bool, int) into a cursor."""
    raw = json.dumps([_to_json(p) for p in parts], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _bad_cursor() -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor")


def _from_json(value: Any, kind: type) -> Any:
    if kind is datetime:
        if not isinstance(value, str):
            raise ValueError
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed
    if kind is UUID:
        if not isinstance(value, str):
            raise ValueError
        return UUID(value)
    if kind is bool:
        if not isinstance(value, bool):
            raise ValueError
        return value
    if kind is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError
        return value
    if kind is str:
        if not isinstance(value, str):
            raise ValueError
        return value
    raise TypeError(f"unsupported cursor part type: {kind!r}")


def decode_cursor(cursor: str, kinds: Sequence[type]) -> list[Any]:
    """Unpack a cursor made by :func:`encode_cursor`.

    ``kinds`` gives the expected type of each part, in order.  Anything else
    (bad base64, bad JSON, wrong length, wrong type, naive timestamp) → 400.
    """
    if not cursor or len(cursor) > _MAX_CURSOR_LEN:
        raise _bad_cursor()
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        parts = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if not isinstance(parts, list) or len(parts) != len(kinds):
            raise ValueError
        return [_from_json(v, k) for v, k in zip(parts, kinds)]
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise _bad_cursor() from None


def next_cursor(rows: Sequence[Any], limit: int, *keys: str) -> str | None:
    """Cursor for the page after ``rows``, or None when this is the last page.

    ``rows`` are DB records / dicts (read by key) or response models (read by
    attribute); ``keys`` name the sort-key fields in cursor order.

    A short page means nothing follows.  A full page may be followed by an
    empty one; that costs one cheap extra request and saves a LIMIT+1 read.
    """
    if not rows or len(rows) < limit:
        return None
    last = rows[-1]
    if hasattr(last, "keys"):   # DB record / dict
        return encode_cursor(*(last[k] for k in keys))
    return encode_cursor(*(getattr(last, k) for k in keys))   # response model
