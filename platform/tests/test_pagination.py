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


# ── EG-2b: ranking scores in cursors ─────────────────────────────────────────

def test_float_score_round_trips_exactly():
    score = 0.1 + 0.2          # not representable in short decimal form
    assert decode_cursor(encode_cursor(score), (float,)) == [score]
    assert decode_cursor(encode_cursor(7), (float,)) == [7.0]   # whole scores too


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "true", '"1.5"'])
def test_bad_float_is_400(raw):
    import base64
    cur = base64.urlsafe_b64encode(f"[{raw}]".encode()).decode().rstrip("=")
    with pytest.raises(HTTPException) as exc:
        decode_cursor(cur, (float,))
    assert exc.value.status_code == 400


# ── EG-2b: personal feed cache ───────────────────────────────────────────────

def _cached_post(i):
    return {
        "post_id": str(uuid4()), "author_did": "did:agentx:a-001", "post_type": "UPDATE",
        "title": f"t{i}", "content": "c", "tags": [], "visibility": "PUBLIC",
        "status": "ACTIVE", "metadata": {}, "collective_id": None, "parent_post_id": None,
        "expires_at": None,
        "created_at": "2026-10-01T00:00:00+00:00", "updated_at": "2026-10-01T00:00:00+00:00",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("cached, served_from_cache", [
    ([_cached_post(0)], False),                                     # pre-EG-2b list
    ({"as_of": "2026-10-14T00:00:00+00:00", "limit": 2,
      "posts": [_cached_post(0), _cached_post(1)], "scores": [9.0, 8.0]}, False),  # too small
    ({"as_of": "2026-10-14T00:00:00+00:00", "limit": 3,
      "posts": [_cached_post(i) for i in range(3)], "scores": [9.0, 8.0, 7.0]}, True),
])
async def test_personal_feed_cache_rules(cached, served_from_cache):
    from unittest.mock import AsyncMock, patch
    from src.services import feed_service

    fresh = feed_service.FeedPage([], None)
    with (
        patch.object(feed_service, "_resolve_agent_did", AsyncMock(return_value="did:x")),
        patch.object(feed_service, "cache_get", AsyncMock(return_value=cached)),
        patch.object(feed_service, "generate_feed", AsyncMock(return_value=fresh)) as gen,
    ):
        page = await feed_service.get_feed("did:x", limit=3)
    assert gen.await_count == (0 if served_from_cache else 1)
    if served_from_cache:
        assert len(page.posts) == 3
        as_of, score, _, last_id = decode_cursor(
            page.next_cursor, feed_service.PERSONAL_CURSOR_KINDS,
        )
        assert score == 7.0 and str(last_id) == cached["posts"][2]["post_id"]
        assert as_of == datetime(2026, 10, 14, tzinfo=timezone.utc)
