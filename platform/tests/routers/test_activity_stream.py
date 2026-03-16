"""
Tests: src/routers/activity_stream.py
        src/routers/agents.py  (achievements endpoint)
Phase 21 — Social-Economic Integration Layer

Covers:
  GET  /activity                               — global public activity stream
  GET  /agents/{agent_did}/activity-stream     — per-agent stream
  POST /activity                               — manually record (auth required)
  GET  /feed/activity                          — combined feed (Phase 21)
  GET  /agents/{did}/achievements              — achievement + milestone posts

All service calls are mocked; no real DB connections are made.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.models.activity_stream import ActivityEvent


# ── Fixtures and helpers ───────────────────────────────────────────────────────

@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


def _make_caller(did: str = "did:agentx:atlas-001", role: str = "FOUNDER"):
    from src.auth.middleware import AgentRecord
    from src.auth.jwt import TokenClaims

    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = did
    return AgentRecord(
        row={
            "agent_did":       did,
            "display_name":    "ATLAS",
            "governance_role": role,
            "tier":            "ELITE",
            "status":          "ACTIVE",
            "trust_score":     0.98,
        },
        claims=claims,
    )


def _make_activity_event(
    agent_did: str = "did:agentx:test-001",
    stream_type: str = "contract_completed",
) -> ActivityEvent:
    return ActivityEvent(
        stream_id=uuid4(),
        agent_did=agent_did,
        stream_type=stream_type,
        ref_entity_id=None,
        ref_entity_type=None,
        ref_post_id=None,
        ref_contract_id=None,
        ref_bounty_id=None,
        content="Test activity event",
        visibility="PUBLIC",
        metadata={},
        created_at=datetime.now(UTC),
    )


def _make_feed_item(agent_did: str = "did:agentx:test-001") -> dict:
    return {
        "item_type":  "activity",
        "id":         str(uuid4()),
        "agent_did":  agent_did,
        "type_label": "bounty_won",
        "content":    "Won a bounty!",
        "created_at": datetime.now(UTC).isoformat(),
    }


def _make_achievement_row(agent_did: str = "did:agentx:test-001") -> dict:
    return {
        "post_id":          str(uuid4()),
        "author_did":       agent_did,
        "post_type":        "ACHIEVEMENT",
        "title":            "Won a Bounty",
        "content":          "Achievement unlocked",
        "tags":             ["achievement", "bounty"],
        "visibility":       "PUBLIC",
        "status":           "ACTIVE",
        "metadata":         {},
        "created_at":       datetime.now(UTC).isoformat(),
        "is_auto_generated": True,
    }


# ── GET /activity ──────────────────────────────────────────────────────────────

class TestGetGlobalActivity:

    @pytest.mark.asyncio
    async def test_returns_200(self, client):
        with patch(
            "src.routers.activity_stream.activity_stream_svc.get_global_activity_stream",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/activity")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_no_auth_required(self, client):
        """Endpoint must be publicly accessible — no Authorization header needed."""
        with patch(
            "src.routers.activity_stream.activity_stream_svc.get_global_activity_stream",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/activity")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_default_limit_50(self, client):
        with patch(
            "src.routers.activity_stream.activity_stream_svc.get_global_activity_stream",
            new=AsyncMock(return_value=[]),
        ) as mock_fn:
            await client.get("/activity")
        mock_fn.assert_awaited_once_with(limit=50)

    @pytest.mark.asyncio
    async def test_custom_limit_accepted(self, client):
        with patch(
            "src.routers.activity_stream.activity_stream_svc.get_global_activity_stream",
            new=AsyncMock(return_value=[]),
        ) as mock_fn:
            await client.get("/activity?limit=10")
        mock_fn.assert_awaited_once_with(limit=10)

    @pytest.mark.asyncio
    async def test_returns_list(self, client):
        events = [_make_activity_event(), _make_activity_event()]
        with patch(
            "src.routers.activity_stream.activity_stream_svc.get_global_activity_stream",
            new=AsyncMock(return_value=events),
        ):
            resp = await client.get("/activity")
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_limit_above_100_returns_422(self, client):
        resp = await client.get("/activity?limit=999")
        assert resp.status_code == 422


# ── GET /agents/{agent_did}/activity-stream ────────────────────────────────────

class TestGetAgentActivityStream:

    @pytest.mark.asyncio
    async def test_returns_200(self, client):
        agent_did = "did:agentx:test-agent-001"
        with patch(
            "src.routers.activity_stream.activity_stream_svc.get_agent_activity_stream",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/agents/{agent_did}/activity-stream")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_no_auth_required(self, client):
        """Agent activity stream is public — no Authorization header needed."""
        agent_did = "did:agentx:public-agent-001"
        with patch(
            "src.routers.activity_stream.activity_stream_svc.get_agent_activity_stream",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/agents/{agent_did}/activity-stream")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_list(self, client):
        agent_did = "did:agentx:test-agent-001"
        events = [_make_activity_event(agent_did=agent_did)]
        with patch(
            "src.routers.activity_stream.activity_stream_svc.get_agent_activity_stream",
            new=AsyncMock(return_value=events),
        ):
            resp = await client.get(f"/agents/{agent_did}/activity-stream")
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1

    @pytest.mark.asyncio
    async def test_agent_did_passed_to_service(self, client):
        agent_did = "did:agentx:specific-agent-007"
        with patch(
            "src.routers.activity_stream.activity_stream_svc.get_agent_activity_stream",
            new=AsyncMock(return_value=[]),
        ) as mock_fn:
            await client.get(f"/agents/{agent_did}/activity-stream")
        mock_fn.assert_awaited_once_with(agent_did=agent_did, limit=50)

    @pytest.mark.asyncio
    async def test_limit_query_param_respected(self, client):
        agent_did = "did:agentx:test-agent-001"
        with patch(
            "src.routers.activity_stream.activity_stream_svc.get_agent_activity_stream",
            new=AsyncMock(return_value=[]),
        ) as mock_fn:
            await client.get(f"/agents/{agent_did}/activity-stream?limit=15")
        mock_fn.assert_awaited_once_with(agent_did=agent_did, limit=15)


# ── POST /activity ─────────────────────────────────────────────────────────────

class TestPostActivity:

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        """POST /activity must return 401 without a valid token."""
        resp = await client.post(
            "/activity",
            json={"stream_type": "contract_completed"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_201(self, client):
        from src.auth.middleware import get_current_agent

        caller = _make_caller("did:agentx:poster-001")
        event = _make_activity_event(agent_did=caller.did)

        with patch(
            "src.routers.activity_stream.activity_stream_svc.record_activity",
            new=AsyncMock(return_value=event),
        ):
            app.dependency_overrides[get_current_agent] = lambda: caller
            resp = await client.post(
                "/activity",
                json={"stream_type": "contract_completed", "content": "Done!"},
            )

        app.dependency_overrides = {}
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_uses_caller_did_not_body(self, client):
        """agent_did must come from the JWT caller, not from the request body."""
        from src.auth.middleware import get_current_agent

        caller = _make_caller("did:agentx:real-caller-001")
        event = _make_activity_event(agent_did=caller.did)

        with patch(
            "src.routers.activity_stream.activity_stream_svc.record_activity",
            new=AsyncMock(return_value=event),
        ) as mock_record:
            app.dependency_overrides[get_current_agent] = lambda: caller
            await client.post(
                "/activity",
                json={"stream_type": "bounty_won"},
            )

        app.dependency_overrides = {}
        # The service must have been called with the caller's DID
        call_kwargs = mock_record.await_args.kwargs
        assert call_kwargs.get("agent_did") == caller.did

    @pytest.mark.asyncio
    async def test_response_has_stream_id(self, client):
        from src.auth.middleware import get_current_agent

        caller = _make_caller("did:agentx:poster-001")
        event = _make_activity_event(agent_did=caller.did)

        with patch(
            "src.routers.activity_stream.activity_stream_svc.record_activity",
            new=AsyncMock(return_value=event),
        ):
            app.dependency_overrides[get_current_agent] = lambda: caller
            resp = await client.post(
                "/activity",
                json={"stream_type": "task_completed"},
            )

        app.dependency_overrides = {}
        assert "stream_id" in resp.json()

    @pytest.mark.asyncio
    async def test_response_has_agent_did(self, client):
        from src.auth.middleware import get_current_agent

        caller = _make_caller("did:agentx:poster-002")
        event = _make_activity_event(agent_did=caller.did)

        with patch(
            "src.routers.activity_stream.activity_stream_svc.record_activity",
            new=AsyncMock(return_value=event),
        ):
            app.dependency_overrides[get_current_agent] = lambda: caller
            resp = await client.post(
                "/activity",
                json={"stream_type": "verification_passed"},
            )

        app.dependency_overrides = {}
        data = resp.json()
        assert "agent_did" in data
        assert data["agent_did"] == caller.did

    @pytest.mark.asyncio
    async def test_response_has_stream_type(self, client):
        from src.auth.middleware import get_current_agent

        caller = _make_caller("did:agentx:poster-003")
        event = _make_activity_event(agent_did=caller.did, stream_type="bounty_won")

        with patch(
            "src.routers.activity_stream.activity_stream_svc.record_activity",
            new=AsyncMock(return_value=event),
        ):
            app.dependency_overrides[get_current_agent] = lambda: caller
            resp = await client.post(
                "/activity",
                json={"stream_type": "bounty_won"},
            )

        app.dependency_overrides = {}
        assert resp.json()["stream_type"] == "bounty_won"


# ── GET /feed/activity ─────────────────────────────────────────────────────────

class TestFeedActivity:

    @pytest.mark.asyncio
    async def test_returns_200(self, client):
        # The feed router imports get_activity_feed_items directly from feed_service
        # at module load time, so patch at the router's namespace.
        with patch(
            "src.routers.feed.get_activity_feed_items",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/feed/activity")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_no_auth_required(self, client):
        """The combined activity feed must be publicly accessible."""
        with patch(
            "src.routers.feed.get_activity_feed_items",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/feed/activity")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_list(self, client):
        items = [_make_feed_item(), _make_feed_item()]
        with patch(
            "src.routers.feed.get_activity_feed_items",
            new=AsyncMock(return_value=items),
        ):
            resp = await client.get("/feed/activity")
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_limit_query_param_respected(self, client):
        with patch(
            "src.routers.feed.get_activity_feed_items",
            new=AsyncMock(return_value=[]),
        ) as mock_fn:
            await client.get("/feed/activity?limit=5")
        mock_fn.assert_awaited_once_with(limit=5)


# ── GET /agents/{did}/achievements ────────────────────────────────────────────

class TestAgentAchievements:

    @pytest.mark.asyncio
    async def test_returns_200(self, client):
        agent_did = "did:agentx:achiever-001"

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)  # agent exists
        conn.fetch = AsyncMock(return_value=[])

        db_ctx = MagicMock()
        db_ctx.__aenter__ = AsyncMock(return_value=conn)
        db_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("src.routers.agents.get_db", return_value=db_ctx):
            resp = await client.get(f"/agents/{agent_did}/achievements")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_no_auth_required(self, client):
        """Achievements endpoint is public — no Authorization header needed."""
        agent_did = "did:agentx:achiever-001"

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        conn.fetch = AsyncMock(return_value=[])

        db_ctx = MagicMock()
        db_ctx.__aenter__ = AsyncMock(return_value=conn)
        db_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("src.routers.agents.get_db", return_value=db_ctx):
            resp = await client.get(f"/agents/{agent_did}/achievements")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_list(self, client):
        agent_did = "did:agentx:achiever-001"

        achievement_rows = [
            {
                "post_id":           uuid4(),
                "author_did":        agent_did,
                "post_type":         "ACHIEVEMENT",
                "title":             "Won a Bounty",
                "content":           "Achievement unlocked",
                "tags":              [],
                "visibility":        "PUBLIC",
                "status":            "ACTIVE",
                "metadata":          {},
                "created_at":        datetime.now(UTC),
                "is_auto_generated": True,
            }
        ]

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        conn.fetch = AsyncMock(return_value=achievement_rows)

        db_ctx = MagicMock()
        db_ctx.__aenter__ = AsyncMock(return_value=conn)
        db_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("src.routers.agents.get_db", return_value=db_ctx):
            resp = await client.get(f"/agents/{agent_did}/achievements")

        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1

    @pytest.mark.asyncio
    async def test_limit_query_param_respected(self, client):
        agent_did = "did:agentx:achiever-001"

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        conn.fetch = AsyncMock(return_value=[])

        db_ctx = MagicMock()
        db_ctx.__aenter__ = AsyncMock(return_value=conn)
        db_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("src.routers.agents.get_db", return_value=db_ctx):
            resp = await client.get(f"/agents/{agent_did}/achievements?limit=5")

        assert resp.status_code == 200
        # limit=5 was passed; verify fetch was called with limit 5 in args
        fetch_args = conn.fetch.await_args.args
        assert 5 in fetch_args
