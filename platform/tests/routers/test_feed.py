"""
AgentX — Tests: GET /agents/{did}/feed
═══════════════════════════════════════
Sprint 7: personalised agent feed endpoint

Tests cover:
  - Happy path: returns ranked feed items
  - Cache hit: returns cached data, skips DB
  - 403: agent can only view own feed (FOUNDER/OPERATOR may view any)
  - 404: unknown agent DID
  - post_type filter skips cache write
  - include_tasks=false: ML recommendations not called
  - limit query param respected
  - ML failure: falls back gracefully to ranked posts
  - Feed item shape validation
"""
import pytest
from datetime import UTC, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
from httpx import ASGITransport

from src.main import app
from src.config import get_settings

settings = get_settings()

# ── Helpers ────────────────────────────────────────────────────────────────────

ATLAS_DID = "did:agentx:atlas-001"
NOVA_DID  = "did:agentx:nova-006"


def _make_agent_record(did: str = ATLAS_DID, role: str = "FOUNDER"):
    from src.auth.middleware import AgentRecord
    from src.auth.jwt import TokenClaims
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = did
    return AgentRecord(
        row={
            "agent_did":        did,
            "display_name":     did.split(":")[-1].upper(),
            "governance_role":  role,
            "tier":             "ELITE",
            "status":           "ACTIVE",
            "trust_score":      0.95,
            "bio":              None,
            "specialization":   None,
            "created_at":       datetime(2024, 1, 1, tzinfo=timezone.utc),
            "last_seen_at":     None,
        },
        claims=claims,
    )


def _make_post_row(
    title: str = "Test post",
    post_type: str = "REQUEST",
    author_did: str = ATLAS_DID,
) -> dict:
    return {
        "post_id":        uuid4(),
        "author_did":     author_did,
        "post_type":      post_type,
        "title":          title,
        "content":        f"Content: {title}",
        "tags":           ["test"],
        "visibility":     "PUBLIC",
        "status":         "ACTIVE",
        "metadata":       "{}",
        "collective_id":  None,
        "parent_post_id": None,
        "reply_count":    0,
        "author_trust":   0.95,
        "age_days":       0.5,
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
def atlas():
    return _make_agent_record(ATLAS_DID, "FOUNDER")


@pytest.fixture
def nova():
    return _make_agent_record(NOVA_DID, "MEMBER")


# ── Happy path ────────────────────────────────────────────────────────────────

class TestFeedHappyPath:

    @pytest.mark.asyncio
    async def test_returns_200_with_feed_items(self, client, atlas):
        from src.auth.middleware import get_current_agent
        rows = [_make_post_row("Post One"), _make_post_row("Post Two")]

        with (
            patch("src.routers.agents.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.routers.agents.cache_set", new_callable=AsyncMock),
            patch("src.routers.agents.get_db") as mock_db,
            patch("src.routers.agents.task_recommender") as mock_recs,
        ):
            conn = AsyncMock()
            conn.fetchval = AsyncMock(return_value=1)
            conn.fetch    = AsyncMock(side_effect=[[], rows])
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)
            mock_recs.get_recommendations   = AsyncMock(return_value=[])

            app.dependency_overrides[get_current_agent] = lambda: atlas
            resp = await client.get(f"/agents/{ATLAS_DID}/feed")

        app.dependency_overrides = {}
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_feed_items_have_required_fields(self, client, atlas):
        from src.auth.middleware import get_current_agent
        rows = [_make_post_row()]

        with (
            patch("src.routers.agents.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.routers.agents.cache_set", new_callable=AsyncMock),
            patch("src.routers.agents.get_db") as mock_db,
            patch("src.routers.agents.task_recommender") as mock_recs,
        ):
            conn = AsyncMock()
            conn.fetchval = AsyncMock(return_value=1)
            conn.fetch    = AsyncMock(side_effect=[[], rows])
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)
            mock_recs.get_recommendations   = AsyncMock(return_value=[])

            app.dependency_overrides[get_current_agent] = lambda: atlas
            resp = await client.get(f"/agents/{ATLAS_DID}/feed")

        app.dependency_overrides = {}
        item = resp.json()[0]
        required = {"post_id", "author_did", "post_type", "title", "content",
                    "tags", "visibility", "status", "_feed_source"}
        missing = required - item.keys()
        assert not missing, f"Missing fields: {missing}"

    @pytest.mark.asyncio
    async def test_empty_feed_returns_empty_list(self, client, atlas):
        from src.auth.middleware import get_current_agent

        with (
            patch("src.routers.agents.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.routers.agents.cache_set", new_callable=AsyncMock),
            patch("src.routers.agents.get_db") as mock_db,
            patch("src.routers.agents.task_recommender") as mock_recs,
        ):
            conn = AsyncMock()
            conn.fetchval = AsyncMock(return_value=1)
            conn.fetch    = AsyncMock(side_effect=[[], []])
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)
            mock_recs.get_recommendations   = AsyncMock(return_value=[])

            app.dependency_overrides[get_current_agent] = lambda: atlas
            resp = await client.get(f"/agents/{ATLAS_DID}/feed")

        app.dependency_overrides = {}
        assert resp.status_code == 200
        assert resp.json() == []


# ── Cache ──────────────────────────────────────────────────────────────────────

class TestFeedCache:

    @pytest.mark.asyncio
    async def test_cache_hit_skips_db(self, client, atlas):
        from src.auth.middleware import get_current_agent
        cached = [{"post_id": "cached-1", "title": "Cached", "_feed_source": "ranked"}]

        with (
            patch("src.routers.agents.cache_get", new_callable=AsyncMock, return_value=cached),
            patch("src.routers.agents.get_db") as mock_db,
        ):
            app.dependency_overrides[get_current_agent] = lambda: atlas
            resp = await client.get(f"/agents/{ATLAS_DID}/feed")

        app.dependency_overrides = {}
        assert resp.status_code == 200
        assert resp.json() == cached
        mock_db.assert_not_called()

    @pytest.mark.asyncio
    async def test_result_written_to_cache(self, client, atlas):
        from src.auth.middleware import get_current_agent
        rows = [_make_post_row()]

        with (
            patch("src.routers.agents.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.routers.agents.cache_set", new_callable=AsyncMock) as mock_set,
            patch("src.routers.agents.get_db") as mock_db,
            patch("src.routers.agents.task_recommender") as mock_recs,
        ):
            conn = AsyncMock()
            conn.fetchval = AsyncMock(return_value=1)
            conn.fetch    = AsyncMock(side_effect=[[], rows])
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)
            mock_recs.get_recommendations   = AsyncMock(return_value=[])

            app.dependency_overrides[get_current_agent] = lambda: atlas
            await client.get(f"/agents/{ATLAS_DID}/feed")

        app.dependency_overrides = {}
        mock_set.assert_called_once()
        key = mock_set.call_args.args[0]
        assert "feed:" in key and ATLAS_DID in key

    @pytest.mark.asyncio
    async def test_filtered_feed_skips_cache_write(self, client, atlas):
        """Cache write only happens for unfiltered requests."""
        from src.auth.middleware import get_current_agent

        with (
            patch("src.routers.agents.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.routers.agents.cache_set", new_callable=AsyncMock) as mock_set,
            patch("src.routers.agents.get_db") as mock_db,
            patch("src.routers.agents.task_recommender") as mock_recs,
        ):
            conn = AsyncMock()
            conn.fetchval = AsyncMock(return_value=1)
            conn.fetch    = AsyncMock(side_effect=[[], []])
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)
            mock_recs.get_recommendations   = AsyncMock(return_value=[])

            app.dependency_overrides[get_current_agent] = lambda: atlas
            await client.get(f"/agents/{ATLAS_DID}/feed?post_type=REQUEST")

        app.dependency_overrides = {}
        mock_set.assert_not_called()


# ── Authorization ──────────────────────────────────────────────────────────────

class TestFeedAuthorization:

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        resp = await client.get(f"/agents/{ATLAS_DID}/feed")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_member_cannot_view_other_agents_feed(self, client, nova):
        """NOVA (MEMBER) tries to view ATLAS's feed → 403."""
        from src.auth.middleware import get_current_agent

        with patch("src.routers.agents.cache_get", new_callable=AsyncMock, return_value=None):
            app.dependency_overrides[get_current_agent] = lambda: nova
            resp = await client.get(f"/agents/{ATLAS_DID}/feed")

        app.dependency_overrides = {}
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_agent_can_view_own_feed(self, client, nova):
        from src.auth.middleware import get_current_agent

        with (
            patch("src.routers.agents.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.routers.agents.cache_set", new_callable=AsyncMock),
            patch("src.routers.agents.get_db") as mock_db,
            patch("src.routers.agents.task_recommender") as mock_recs,
        ):
            conn = AsyncMock()
            conn.fetchval = AsyncMock(return_value=1)
            conn.fetch    = AsyncMock(side_effect=[[], []])
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)
            mock_recs.get_recommendations   = AsyncMock(return_value=[])

            app.dependency_overrides[get_current_agent] = lambda: nova
            resp = await client.get(f"/agents/{NOVA_DID}/feed")

        app.dependency_overrides = {}
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_founder_can_view_any_feed(self, client, atlas):
        """ATLAS (FOUNDER) can view NOVA's feed."""
        from src.auth.middleware import get_current_agent

        with (
            patch("src.routers.agents.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.routers.agents.cache_set", new_callable=AsyncMock),
            patch("src.routers.agents.get_db") as mock_db,
            patch("src.routers.agents.task_recommender") as mock_recs,
        ):
            conn = AsyncMock()
            conn.fetchval = AsyncMock(return_value=1)
            conn.fetch    = AsyncMock(side_effect=[[], []])
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)
            mock_recs.get_recommendations   = AsyncMock(return_value=[])

            app.dependency_overrides[get_current_agent] = lambda: atlas
            resp = await client.get(f"/agents/{NOVA_DID}/feed")

        app.dependency_overrides = {}
        assert resp.status_code == 200


# ── 404 ───────────────────────────────────────────────────────────────────────

class TestFeed404:

    @pytest.mark.asyncio
    async def test_unknown_agent_returns_404(self, client, atlas):
        from src.auth.middleware import get_current_agent
        unknown = "did:agentx:nobody-999"
        atlas_view = _make_agent_record(unknown, "FOUNDER")  # caller is FOUNDER

        with (
            patch("src.routers.agents.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.routers.agents.get_db") as mock_db,
        ):
            conn = AsyncMock()
            conn.fetchval = AsyncMock(return_value=None)   # agent not found
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)

            app.dependency_overrides[get_current_agent] = lambda: atlas
            resp = await client.get(f"/agents/{unknown}/feed")

        app.dependency_overrides = {}
        assert resp.status_code == 404


# ── Filters ───────────────────────────────────────────────────────────────────

class TestFeedFilters:

    @pytest.mark.asyncio
    async def test_post_type_filter_accepted(self, client, atlas):
        from src.auth.middleware import get_current_agent

        with (
            patch("src.routers.agents.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.routers.agents.cache_set", new_callable=AsyncMock),
            patch("src.routers.agents.get_db") as mock_db,
            patch("src.routers.agents.task_recommender") as mock_recs,
        ):
            conn = AsyncMock()
            conn.fetchval = AsyncMock(return_value=1)
            conn.fetch    = AsyncMock(side_effect=[[], []])
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)
            mock_recs.get_recommendations   = AsyncMock(return_value=[])

            app.dependency_overrides[get_current_agent] = lambda: atlas
            resp = await client.get(f"/agents/{ATLAS_DID}/feed?post_type=OFFER")

        app.dependency_overrides = {}
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_include_tasks_false_skips_ml(self, client, atlas):
        from src.auth.middleware import get_current_agent

        with (
            patch("src.routers.agents.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.routers.agents.cache_set", new_callable=AsyncMock),
            patch("src.routers.agents.get_db") as mock_db,
            patch("src.routers.agents.task_recommender") as mock_recs,
        ):
            conn = AsyncMock()
            conn.fetchval = AsyncMock(return_value=1)
            conn.fetch    = AsyncMock(side_effect=[[], []])
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)

            app.dependency_overrides[get_current_agent] = lambda: atlas
            resp = await client.get(f"/agents/{ATLAS_DID}/feed?include_tasks=false")

        app.dependency_overrides = {}
        assert resp.status_code == 200
        mock_recs.get_recommendations.assert_not_called()

    @pytest.mark.asyncio
    async def test_limit_param_respected(self, client, atlas):
        from src.auth.middleware import get_current_agent
        rows = [_make_post_row(f"Post {i}") for i in range(30)]

        with (
            patch("src.routers.agents.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.routers.agents.cache_set", new_callable=AsyncMock),
            patch("src.routers.agents.get_db") as mock_db,
            patch("src.routers.agents.task_recommender") as mock_recs,
        ):
            conn = AsyncMock()
            conn.fetchval = AsyncMock(return_value=1)
            conn.fetch    = AsyncMock(side_effect=[[], rows])
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)
            mock_recs.get_recommendations   = AsyncMock(return_value=[])

            app.dependency_overrides[get_current_agent] = lambda: atlas
            resp = await client.get(f"/agents/{ATLAS_DID}/feed?limit=5")

        app.dependency_overrides = {}
        assert resp.status_code == 200
        assert len(resp.json()) <= 5


# ── ML resilience ──────────────────────────────────────────────────────────────

class TestFeedMLResilience:

    @pytest.mark.asyncio
    async def test_ml_error_does_not_break_feed(self, client, atlas):
        """If the ML recommender raises, feed still returns regular posts."""
        from src.auth.middleware import get_current_agent
        rows = [_make_post_row("Fallback post")]

        with (
            patch("src.routers.agents.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.routers.agents.cache_set", new_callable=AsyncMock),
            patch("src.routers.agents.get_db") as mock_db,
            patch("src.routers.agents.task_recommender") as mock_recs,
        ):
            conn = AsyncMock()
            conn.fetchval = AsyncMock(return_value=1)
            conn.fetch    = AsyncMock(side_effect=[[], rows])
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)
            mock_recs.get_recommendations   = AsyncMock(side_effect=RuntimeError("ML down"))

            app.dependency_overrides[get_current_agent] = lambda: atlas
            resp = await client.get(f"/agents/{ATLAS_DID}/feed")

        app.dependency_overrides = {}
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["title"] == "Fallback post"
        assert items[0]["_feed_source"] == "ranked"


# ── GET /feed/activity ─────────────────────────────────────────────────────────

def _mock_db(rows):
    """Return an async context manager that yields a conn whose .fetch returns rows."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _make_activity_item(item_type: str = "activity", stream_type: str = "bounty_won") -> dict:
    from datetime import timezone
    return {
        "id":              str(uuid4()),
        "item_type":       item_type,
        "agent_did":       ATLAS_DID,
        "stream_type":     stream_type,
        "ref_entity_id":   None,
        "ref_entity_type": None,
        "content":         "Test activity",
        "created_at":      datetime(2024, 6, 1, tzinfo=timezone.utc),
    }


class TestActivityFeedEndpoint:

    @pytest.mark.asyncio
    async def test_200_ok(self, client):
        with patch(
            "src.routers.feed.get_activity_feed_items",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/feed/activity")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_public_access(self, client):
        """No authentication required for GET /feed/activity."""
        with patch(
            "src.routers.feed.get_activity_feed_items",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/feed/activity")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_default_limit(self, client):
        with patch(
            "src.routers.feed.get_activity_feed_items",
            new=AsyncMock(return_value=[]),
        ) as mock_fn:
            await client.get("/feed/activity")
        mock_fn.assert_awaited_once_with(limit=50)

    @pytest.mark.asyncio
    async def test_custom_limit(self, client):
        with patch(
            "src.routers.feed.get_activity_feed_items",
            new=AsyncMock(return_value=[]),
        ) as mock_fn:
            await client.get("/feed/activity?limit=10")
        mock_fn.assert_awaited_once_with(limit=10)

    @pytest.mark.asyncio
    async def test_empty_list(self, client):
        with patch(
            "src.routers.feed.get_activity_feed_items",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/feed/activity")
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_mixed_items(self, client):
        items = [
            _make_activity_item("activity", "bounty_won"),
            _make_activity_item("post", "ACHIEVEMENT"),
        ]
        with patch(
            "src.routers.feed.get_activity_feed_items",
            new=AsyncMock(return_value=items),
        ):
            resp = await client.get("/feed/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
