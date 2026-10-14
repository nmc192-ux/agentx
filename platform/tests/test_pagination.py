"""EG-2: cursor encode/decode helpers (src/pagination.py)."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.pagination import decode_cursor, encode_cursor, next_cursor

KINDS = (bool, datetime, str)


def test_round_trip_keeps_types_and_microseconds():
    ts = datetime(2026, 10, 14, 12, 30, 1, 123456, tzinfo=timezone.utc)
    uid = uuid4()
    cur = encode_cursor(True, ts, uid)
    assert "=" not in cur
    assert decode_cursor(cur, (bool, datetime, type(uid))) == [True, ts, uid]


@pytest.mark.parametrize("bad", [
    "",
    "%%%",                                      # not base64
    encode_cursor(True)[:-1] + "!",
    "e30",                                      # {} — not a list
    encode_cursor(True, "2026-01-01T00:00:00+00:00"),            # too short
    encode_cursor(True, "2026-01-01T00:00:00+00:00", "x", "y"),  # too long
    encode_cursor("yes", "2026-01-01T00:00:00+00:00", "x"),      # bool expected
    encode_cursor(1, "2026-01-01T00:00:00+00:00", "x"),          # int is not bool
    encode_cursor(True, "2026-01-01T00:00:00", "x"),             # naive time
    encode_cursor(True, "not a time", "x"),
    encode_cursor(True, "2026-01-01T00:00:00+00:00", 5),         # str expected
    "A" * 600,                                   # oversized
])
def test_bad_cursor_is_400(bad):
    with pytest.raises(HTTPException) as exc:
        decode_cursor(bad, KINDS)
    assert exc.value.status_code == 400


def test_bad_uuid_is_400():
    from uuid import UUID
    with pytest.raises(HTTPException):
        decode_cursor(encode_cursor("not-a-uuid"), (UUID,))


def test_next_cursor_only_on_full_page():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [{"t": ts, "id": "a"}, {"t": ts, "id": "b"}]
    assert next_cursor([], 2, "t", "id") is None
    assert next_cursor(rows[:1], 2, "t", "id") is None
    assert decode_cursor(next_cursor(rows, 2, "t", "id"), (datetime, str)) == [ts, "b"]


def test_next_cursor_reads_model_attributes():
    from types import SimpleNamespace
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [SimpleNamespace(created_at=ts, stream_id="s1")]
    cur = next_cursor(rows, 1, "created_at", "stream_id")
    assert decode_cursor(cur, (datetime, str)) == [ts, "s1"]
