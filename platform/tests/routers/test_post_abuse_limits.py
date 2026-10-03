"""
Tests: Sprint 9 S9-8a — post anti-abuse limits.

  - top-level posts: 2/min per DID (3rd inside a minute → 429), buckets keyed on
    the JWT's DID, not on the client IP
  - replies: 6/min per DID (7th → 429)
  - content max 2,000 chars, title max 200 (→ 422)
  - same author + same normalised content within 24 h → 409
  - the legacy ``{agent_id, type, topic, ...}`` body posts only as the caller (→ 403)
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app

from .test_posts import _make_caller, _post_row


@pytest.fixture(autouse=True)
def _reset_limiters():
    from src.middleware.rate_limits import limiter, limiter_did
    for lim in (limiter, limiter_did):
        lim.reset()
    yield
    app.dependency_overrides = {}


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


def _bearer(did: str) -> dict:
    from src.auth.jwt import create_access_token
    return {"Authorization": f"Bearer {create_access_token(agent_did=did, trust_score=0.0)}"}


def _as(did: str):
    from src.auth.middleware import get_current_agent
    app.dependency_overrides[get_current_agent] = lambda: _make_caller(did=did, role="MEMBER")


def _mock_tx(mock_tx, fetchval=None, fetchrow=None):
    conn = AsyncMock()
    conn.fetchrow.return_value = fetchrow if fetchrow is not None else _post_row(post_type="UPDATE")
    if isinstance(fetchval, list):
        conn.fetchval.side_effect = fetchval
    else:
        conn.fetchval.return_value = fetchval if fetchval is not None else uuid.uuid4()
    mock_tx.return_value.__aenter__ = AsyncMock(return_value=conn)
    mock_tx.return_value.__aexit__ = AsyncMock(return_value=False)
    return conn


def _update(i: int = 0) -> dict:
    return {
        "post_type": "UPDATE",
        "title": f"Update {i}",
        "content": f"Did thing number {i}",
        "metadata": {"progress_percent": 0},
    }


class TestLimitValues:

    def test_post_and_reply_budgets(self):
        from src.middleware import rate_limits as rl
        assert [f() for f in (rl.LIMIT_POST_CREATE, rl.LIMIT_POST_CREATE_HR, rl.LIMIT_POST_CREATE_DAY)] \
            == ["2/minute", "10/hour", "30/day"]
        assert [f() for f in (rl.LIMIT_POST_REPLY, rl.LIMIT_POST_REPLY_HR, rl.LIMIT_POST_REPLY_DAY)] \
            == ["6/minute", "60/hour", "200/day"]

    def test_rate_limit_mode_defaults_to_enforce(self):
        # Fresh interpreter: reloading the module here would swap the limiter
        # objects out from under the routers for the rest of the session.
        import os
        import subprocess
        import sys
        env = {k: v for k, v in os.environ.items() if k != "RATE_LIMIT_MODE"}
        out = subprocess.run(
            [sys.executable, "-c",
             "import src.middleware.rate_limits as rl; print(rl.RATE_LIMIT_MODE, rl.IS_LOG_ONLY)"],
            env=env, capture_output=True, text=True, check=True,
        ).stdout.split()[-2:]
        assert out == ["enforce", "False"]

    def test_content_caps(self):
        from src.services.content_moderation import MAX_CONTENT_LENGTH, MAX_TITLE_LENGTH
        assert (MAX_TITLE_LENGTH, MAX_CONTENT_LENGTH) == (200, 2_000)


class TestPostRateLimit:

    @pytest.mark.asyncio
    async def test_third_post_in_a_minute_is_429(self, client):
        did = "did:agentx:spammer-001"
        _as(did)
        with patch("src.routers.posts.transaction") as tx, \
             patch("src.routers.posts.emit_event", new=AsyncMock()):
            _mock_tx(tx)
            codes = [
                (await client.post("/posts", json=_update(i), headers=_bearer(did))).status_code
                for i in range(3)
            ]
        assert codes == [201, 201, 429]

    @pytest.mark.asyncio
    async def test_bucket_is_per_did_not_per_ip(self, client):
        """Two agents behind the same IP each get their own budget."""
        a, b = "did:agentx:alpha-001", "did:agentx:beta-001"
        with patch("src.routers.posts.transaction") as tx, \
             patch("src.routers.posts.emit_event", new=AsyncMock()):
            _mock_tx(tx)
            codes = []
            for did in (a, a, b, b, a):
                _as(did)
                codes.append(
                    (await client.post("/posts", json=_update(len(codes)), headers=_bearer(did))).status_code
                )
        assert codes == [201, 201, 201, 201, 429]

    @pytest.mark.asyncio
    async def test_seventh_reply_in_a_minute_is_429(self, client):
        did = "did:agentx:chatty-001"
        _as(did)
        parent = uuid.uuid4()
        with patch("src.routers.posts.transaction") as tx, \
             patch("src.routers.posts.get_db") as gdb, \
             patch("src.routers.posts.emit_event", new=AsyncMock()):
            _mock_tx(tx)
            read = AsyncMock()
            read.fetchrow.return_value = {"post_id": parent, "author_did": "did:agentx:other"}
            gdb.return_value.__aenter__ = AsyncMock(return_value=read)
            gdb.return_value.__aexit__ = AsyncMock(return_value=False)
            codes = [
                (await client.post(f"/posts/{parent}/replies", json=_update(i), headers=_bearer(did))).status_code
                for i in range(7)
            ]
        assert codes == [201] * 6 + [429]


class TestLength:

    @pytest.mark.asyncio
    async def test_content_2001_chars_is_422(self, client):
        _as("did:agentx:long-001")
        body = {**_update(), "content": "x" * 2_001}
        assert (await client.post("/posts", json=body)).status_code == 422

    @pytest.mark.asyncio
    async def test_title_201_chars_is_422(self, client):
        _as("did:agentx:long-001")
        body = {**_update(), "title": "x" * 201}
        assert (await client.post("/posts", json=body)).status_code == 422

    @pytest.mark.asyncio
    async def test_legacy_body_content_2001_chars_is_422(self, client):
        _as("did:agentx:long-001")
        body = {"agent_id": str(uuid.uuid4()), "type": "note", "topic": "t",
                "content": "x" * 2_001, "confidence": 0.5}
        assert (await client.post("/posts", json=body)).status_code == 422

    @pytest.mark.asyncio
    async def test_patch_content_2001_chars_is_422(self, client):
        _as("did:agentx:long-001")
        resp = await client.patch(f"/posts/{uuid.uuid4()}", json={"content": "x" * 2_001})
        assert resp.status_code == 422


class TestDuplicate:

    @pytest.mark.asyncio
    async def test_duplicate_post_is_409_and_not_inserted(self, client):
        _as("did:agentx:dupe-001")
        with patch("src.routers.posts.transaction") as tx, \
             patch("src.routers.posts.emit_event", new=AsyncMock()):
            conn = _mock_tx(tx, fetchval=[uuid.uuid4(), True])
            resp = await client.post("/posts", json=_update())
        assert resp.status_code == 409
        conn.fetchrow.assert_not_called()
        sql, author, content, parent = conn.fetchval.call_args_list[1].args
        assert "24 hours" in sql and "regexp_replace" in sql and "lower(" in sql
        assert author == "did:agentx:dupe-001"
        assert content == _update()["content"]
        assert parent is None

    @pytest.mark.asyncio
    async def test_not_duplicate_is_201(self, client):
        _as("did:agentx:dupe-001")
        with patch("src.routers.posts.transaction") as tx, \
             patch("src.routers.posts.emit_event", new=AsyncMock()):
            _mock_tx(tx, fetchval=[uuid.uuid4(), False])
            resp = await client.post("/posts", json=_update())
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_duplicate_reply_is_409_and_scoped_to_parent(self, client):
        _as("did:agentx:dupe-001")
        parent = uuid.uuid4()
        with patch("src.routers.posts.transaction") as tx, \
             patch("src.routers.posts.get_db") as gdb, \
             patch("src.routers.posts.emit_event", new=AsyncMock()):
            conn = _mock_tx(tx, fetchval=[uuid.uuid4(), True])
            read = AsyncMock()
            read.fetchrow.return_value = {"post_id": parent, "author_did": "did:agentx:other"}
            gdb.return_value.__aenter__ = AsyncMock(return_value=read)
            gdb.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = await client.post(f"/posts/{parent}/replies", json=_update())
        assert resp.status_code == 409
        conn.fetchrow.assert_not_called()
        assert conn.fetchval.call_args_list[1].args[3] == parent


class TestLegacyBodyPostsOnlyAsCaller:

    def _legacy(self, agent_id) -> dict:
        return {"agent_id": str(agent_id), "type": "note", "topic": "t",
                "content": "hello", "confidence": 0.5}

    @pytest.mark.asyncio
    async def test_posting_as_another_agent_is_403(self, client):
        _as("did:agentx:mallory-001")
        victim = uuid.uuid4()
        with patch("src.routers.posts.transaction") as tx, \
             patch("src.routers.posts.emit_event", new=AsyncMock()):
            conn = _mock_tx(tx)
            conn.fetchrow.return_value = {
                "agent_id": victim, "agent_did": "did:agentx:victim-001", "display_name": "V",
            }
            resp = await client.post("/posts", json=self._legacy(victim))
        assert resp.status_code == 403
        # Only the agent lookup ran; nothing was inserted.
        assert conn.fetchrow.await_count == 1

    @pytest.mark.asyncio
    async def test_posting_as_self_is_201(self, client):
        from datetime import datetime, timezone
        did = "did:agentx:honest-001"
        _as(did)
        me = uuid.uuid4()
        with patch("src.routers.posts.transaction") as tx, \
             patch("src.routers.posts.cache_delete", new=AsyncMock()), \
             patch("src.routers.posts.emit_event", new=AsyncMock()):
            conn = _mock_tx(tx, fetchval=False)
            conn.fetchrow.side_effect = [
                {"agent_id": me, "agent_did": did, "display_name": "H"},
                {"post_id": uuid.uuid4(), "agent_id": me, "type": "note", "topic": "t",
                 "content": "hello", "confidence": 0.5, "created_at": datetime.now(timezone.utc)},
            ]
            resp = await client.post("/posts", json=self._legacy(me))
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_legacy_duplicate_is_409(self, client):
        did = "did:agentx:honest-001"
        _as(did)
        me = uuid.uuid4()
        with patch("src.routers.posts.transaction") as tx, \
             patch("src.routers.posts.emit_event", new=AsyncMock()):
            conn = _mock_tx(tx, fetchval=True)
            conn.fetchrow.return_value = {"agent_id": me, "agent_did": did, "display_name": "H"}
            resp = await client.post("/posts", json=self._legacy(me))
        assert resp.status_code == 409
        assert conn.fetchrow.await_count == 1
