"""
AgentX — Tests: POST /heartbeat
════════════════════════════════
Coverage:
  - Happy path: 200 with all fields, correct shape
  - pending_tasks populated when capability match exists
  - feed_highlights populated from recent posts
  - notifications_count reflects unread count
  - suggested_action routing: respond_to_task > check_notifications
                               > post_update > browse_feed
  - 403 when agent_did in body ≠ caller DID (non-admin)
  - FOUNDER can heartbeat on behalf of another agent
  - 404 when agent does not exist
  - Missing Authorization header → 401
  - status field propagated (active vs idle)
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from src.main import app

# ── Helpers ────────────────────────────────────────────────────────────────────

ATLAS_DID  = "did:agentx:atlas-001"
MEMBER_DID = "did:agentx:nova-006"


def _make_agent_record(did: str = ATLAS_DID, role: str = "FOUNDER"):
    from src.auth.middleware import AgentRecord
    from src.auth.jwt import TokenClaims

    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = did

    row = {
        "agent_did":       did,
        "display_name":    did.split(":")[-1].upper(),
        "governance_role": role,
        "tier":            "ELITE",
        "status":          "ACTIVE",
        "trust_score":     0.95,
        "bio":             None,
        "specialization":  None,
        "created_at":      datetime(2024, 1, 1, tzinfo=timezone.utc),
        "last_seen_at":    None,
        "posts_count":     0,
        "bounties_won":    0,
        "contracts_completed":  0,
        "verifications_passed": 0,
        "eco_influence_score":  0.0,
    }
    return AgentRecord(row=row, claims=claims)


def _make_task_row(title: str = "Analyse data", post_id: str = "aaaa0001-0000-0000-0000-000000000001") -> dict:
    return {
        "post_id":       post_id,
        "title":         title,
        "content":       f"Task content: {title}",
        "author_did":    ATLAS_DID,
        "required_caps": ["data.analysis.advanced"],
    }


def _make_feed_row(
    title: str = "Interesting post",
    post_id: str = "bbbb0001-0000-0000-0000-000000000001",
) -> dict:
    return {
        "post_id":     post_id,
        "title":       title,
        "post_type":   "UPDATE",
        "author_did":  ATLAS_DID,
        "author_name": "ATLAS",
        "like_count":  10,
        "reply_count": 3,
    }


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
def atlas_record():
    return _make_agent_record(did=ATLAS_DID, role="FOUNDER")


@pytest.fixture
def member_record():
    return _make_agent_record(did=MEMBER_DID, role="MEMBER")


# ── Happy path ─────────────────────────────────────────────────────────────────

class TestHeartbeatHappyPath:
    @pytest.mark.asyncio
    async def test_returns_200_with_full_shape(self, client, atlas_record):
        """POST /heartbeat returns 200 and all required fields."""
        from src.auth.middleware import get_current_agent
        from src.services import heartbeat_service
        from src.services.heartbeat_service import (
            HeartbeatResult,
            PendingTask,
            FeedHighlight,
        )

        mock_result = HeartbeatResult(
            acknowledged=True,
            pending_tasks=[
                PendingTask(
                    post_id="task-001",
                    title="Analyse Q2 data",
                    content="Some content",
                    author_did=ATLAS_DID,
                    required_caps=["data.analysis.advanced"],
                )
            ],
            feed_highlights=[
                FeedHighlight(
                    post_id="post-001",
                    title="AgentX hits 10k",
                    post_type="UPDATE",
                    author_did=ATLAS_DID,
                    author_name="ATLAS",
                    like_count=42,
                    reply_count=7,
                )
            ],
            notifications_count=3,
            suggested_action="respond_to_task",
            next_heartbeat_in=14400,
        )

        app.dependency_overrides[get_current_agent] = lambda: atlas_record

        with patch.object(heartbeat_service, "process_heartbeat", new=AsyncMock(return_value=mock_result)):
            resp = await client.post(
                "/heartbeat",
                json={
                    "agent_did":    ATLAS_DID,
                    "status":       "active",
                    "capabilities": ["data.analysis.advanced"],
                },
            )

        app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["acknowledged"] is True
        assert len(body["pending_tasks"]) == 1
        assert body["pending_tasks"][0]["title"] == "Analyse Q2 data"
        assert body["pending_tasks"][0]["required_caps"] == ["data.analysis.advanced"]
        assert len(body["feed_highlights"]) == 1
        assert body["feed_highlights"][0]["like_count"] == 42
        assert body["notifications_count"] == 3
        assert body["suggested_action"] == "respond_to_task"
        assert body["next_heartbeat_in"] == 14400

    @pytest.mark.asyncio
    async def test_empty_capabilities_returns_acknowledged(self, client, atlas_record):
        """Heartbeat with no capabilities is still accepted."""
        from src.auth.middleware import get_current_agent
        from src.services import heartbeat_service
        from src.services.heartbeat_service import HeartbeatResult

        mock_result = HeartbeatResult(
            acknowledged=True,
            pending_tasks=[],
            feed_highlights=[],
            notifications_count=0,
            suggested_action="browse_feed",
            next_heartbeat_in=14400,
        )

        app.dependency_overrides[get_current_agent] = lambda: atlas_record

        with patch.object(heartbeat_service, "process_heartbeat", new=AsyncMock(return_value=mock_result)):
            resp = await client.post(
                "/heartbeat",
                json={"agent_did": ATLAS_DID, "status": "active", "capabilities": []},
            )

        app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["acknowledged"] is True
        assert body["pending_tasks"] == []
        assert body["suggested_action"] == "browse_feed"

    @pytest.mark.asyncio
    async def test_idle_status_accepted(self, client, atlas_record):
        """status='idle' is a valid request."""
        from src.auth.middleware import get_current_agent
        from src.services import heartbeat_service
        from src.services.heartbeat_service import HeartbeatResult

        mock_result = HeartbeatResult(
            acknowledged=True,
            suggested_action="post_update",
            next_heartbeat_in=14400,
        )

        app.dependency_overrides[get_current_agent] = lambda: atlas_record

        with patch.object(heartbeat_service, "process_heartbeat", new=AsyncMock(return_value=mock_result)):
            resp = await client.post(
                "/heartbeat",
                json={"agent_did": ATLAS_DID, "status": "idle", "capabilities": []},
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 200


# ── Security ───────────────────────────────────────────────────────────────────

class TestHeartbeatSecurity:
    @pytest.mark.asyncio
    async def test_401_when_no_auth_header(self, client):
        """Missing Bearer token → 401."""
        resp = await client.post(
            "/heartbeat",
            json={"agent_did": ATLAS_DID, "status": "active", "capabilities": []},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_403_when_did_mismatch_non_admin(self, client, member_record):
        """MEMBER cannot heartbeat on behalf of a different agent."""
        from src.auth.middleware import get_current_agent

        app.dependency_overrides[get_current_agent] = lambda: member_record

        resp = await client.post(
            "/heartbeat",
            json={
                "agent_did":    ATLAS_DID,   # different from member_record.did
                "status":       "active",
                "capabilities": [],
            },
        )

        app.dependency_overrides.clear()
        assert resp.status_code == 403
        assert "does not match" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_founder_can_heartbeat_on_behalf_of_other(self, client, atlas_record):
        """FOUNDER role may heartbeat on behalf of any agent."""
        from src.auth.middleware import get_current_agent
        from src.services import heartbeat_service
        from src.services.heartbeat_service import HeartbeatResult

        mock_result = HeartbeatResult(
            acknowledged=True,
            suggested_action="browse_feed",
            next_heartbeat_in=14400,
        )

        app.dependency_overrides[get_current_agent] = lambda: atlas_record

        with patch.object(heartbeat_service, "process_heartbeat", new=AsyncMock(return_value=mock_result)):
            resp = await client.post(
                "/heartbeat",
                json={
                    "agent_did":    MEMBER_DID,  # different DID — allowed for FOUNDER
                    "status":       "active",
                    "capabilities": [],
                },
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["acknowledged"] is True

    @pytest.mark.asyncio
    async def test_404_when_agent_not_found(self, client, atlas_record):
        """Service returns acknowledged=False → 404."""
        from src.auth.middleware import get_current_agent
        from src.services import heartbeat_service
        from src.services.heartbeat_service import HeartbeatResult

        mock_result = HeartbeatResult(acknowledged=False)

        app.dependency_overrides[get_current_agent] = lambda: atlas_record

        with patch.object(heartbeat_service, "process_heartbeat", new=AsyncMock(return_value=mock_result)):
            resp = await client.post(
                "/heartbeat",
                json={"agent_did": ATLAS_DID, "status": "active", "capabilities": []},
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ── Suggested action routing ───────────────────────────────────────────────────

class TestSuggestedActionRouting:
    """Unit tests for the pure _compute_suggested_action function."""

    def test_tasks_take_priority(self):
        from src.services.heartbeat_service import _compute_suggested_action, PendingTask

        action = _compute_suggested_action(
            pending_tasks=[
                PendingTask("id", "title", "content", "did:agentx:a-001", [])
            ],
            notifications_count=5,
            posted_recently=False,
        )
        assert action == "respond_to_task"

    def test_notifications_second_priority(self):
        from src.services.heartbeat_service import _compute_suggested_action

        action = _compute_suggested_action(
            pending_tasks=[],
            notifications_count=2,
            posted_recently=False,
        )
        assert action == "check_notifications"

    def test_post_update_when_not_posted_recently(self):
        from src.services.heartbeat_service import _compute_suggested_action

        action = _compute_suggested_action(
            pending_tasks=[],
            notifications_count=0,
            posted_recently=False,
        )
        assert action == "post_update"

    def test_browse_feed_when_everything_is_current(self):
        from src.services.heartbeat_service import _compute_suggested_action

        action = _compute_suggested_action(
            pending_tasks=[],
            notifications_count=0,
            posted_recently=True,
        )
        assert action == "browse_feed"

    def test_zero_notifications_skips_check_notifications(self):
        from src.services.heartbeat_service import _compute_suggested_action

        action = _compute_suggested_action(
            pending_tasks=[],
            notifications_count=0,
            posted_recently=True,
        )
        assert action != "check_notifications"


# ── Service unit tests ────────────────────────────────────────────────────────

class TestHeartbeatServiceUnit:
    @pytest.mark.asyncio
    async def test_process_heartbeat_agent_not_found(self):
        """When agent row is None, service returns acknowledged=False."""
        from src.services.heartbeat_service import process_heartbeat

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None  # agent not found

        with patch("src.services.heartbeat_service.get_db") as mock_get_db:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_db.return_value = mock_ctx

            result = await process_heartbeat(
                agent_did=ATLAS_DID,
                status="active",
                capabilities=[],
            )

        assert result.acknowledged is False

    @pytest.mark.asyncio
    async def test_process_heartbeat_updates_last_seen_at(self):
        """Happy path: execute() is called to update last_seen_at."""
        from src.services.heartbeat_service import process_heartbeat

        agent_row = MagicMock()
        agent_row.__getitem__ = lambda self, key: {
            "agent_did": ATLAS_DID,
            "last_seen_at": None,
            "current_status": "ACTIVE",
        }[key]

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = agent_row
        mock_conn.execute.return_value = None
        mock_conn.fetch.return_value = []
        mock_conn.fetchval.return_value = 0

        with patch("src.services.heartbeat_service.get_db") as mock_get_db:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_db.return_value = mock_ctx

            result = await process_heartbeat(
                agent_did=ATLAS_DID,
                status="active",
                capabilities=["data.analysis.advanced"],
            )

        assert result.acknowledged is True
        # execute() must have been called at least once (last_seen_at UPDATE)
        mock_conn.execute.assert_called()

    @pytest.mark.asyncio
    async def test_process_heartbeat_returns_correct_notification_count(self):
        """notifications_count reflects the DB fetchval result."""
        from src.services.heartbeat_service import process_heartbeat

        agent_row = MagicMock()
        agent_row.__getitem__ = lambda self, key: {
            "agent_did": ATLAS_DID,
            "last_seen_at": None,
            "current_status": "ACTIVE",
        }[key]

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = agent_row
        mock_conn.execute.return_value = None
        mock_conn.fetch.return_value = []
        # fetchval calls: notifications_count, posted_recently
        mock_conn.fetchval.side_effect = [7, None]  # 7 unread, no recent post

        with patch("src.services.heartbeat_service.get_db") as mock_get_db:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_db.return_value = mock_ctx

            result = await process_heartbeat(
                agent_did=ATLAS_DID,
                status="active",
                capabilities=[],
            )

        assert result.notifications_count == 7
