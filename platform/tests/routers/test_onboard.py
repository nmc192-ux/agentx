"""
AgentX — Tests: POST /onboard
══════════════════════════════
Coverage:
  - Happy path: 201 with all required fields, new agent
  - Idempotent return: same name → existing agent credentials, is_new_agent=False
  - No first_post: post_id is null, still 201
  - Minimal body (name only): bio/capabilities default gracefully
  - 503 when DID generation exhausts retries (RuntimeError from service)
  - Response shape validation: all fields present and correctly typed
  - next_steps: populated from capabilities
  - next_steps: fallback when no capabilities provided
  - profile_url / heartbeat_url / agent_card_url are correct
  - Service unit: _name_to_slug normalises correctly
  - Service unit: _build_next_steps includes capability in task URL
"""
import pytest
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from src.main import app

# ── Helpers ────────────────────────────────────────────────────────────────────

AGENT_DID = "did:agentx:myagent-042"


def _make_onboard_result(is_new: bool = True, post_id: str = "post-001") -> object:
    from src.services.onboard_service import OnboardResult
    return OnboardResult(
        agent_did=AGENT_DID,
        access_token="access-jwt-token",
        refresh_token="refresh-jwt-token",
        wallet_balance=100,
        is_new_agent=is_new,
        post_id=post_id if is_new else None,
    )


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """
    /onboard is rate-limited at 5/hour and 20/day per-IP via slowapi's
    memory:// backend.  The in-process counter persists across tests in the
    same pytest session, so the 6th test in the module would otherwise trip
    the limiter regardless of intent.  Clear the storage before each test.
    """
    from src.middleware.rate_limits import limiter
    try:
        limiter.reset()
    except Exception:
        pass
    yield


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


# ── Happy path ─────────────────────────────────────────────────────────────────

class TestOnboardHappyPath:
    @pytest.mark.asyncio
    async def test_returns_201_with_full_shape(self, client):
        """POST /onboard returns 201 with all required fields for a new agent."""
        from src.services import onboard_service

        mock_result = _make_onboard_result(is_new=True, post_id="post-001")

        with patch.object(onboard_service, "onboard_agent", new=AsyncMock(return_value=mock_result)):
            resp = await client.post(
                "/onboard",
                json={
                    "name": "MyAgent",
                    "capabilities": ["coding", "writing"],
                    "bio": "A helpful coding assistant",
                    "first_post": {
                        "title": "Hello AgentX!",
                        "content": "I'm a new agent specializing in Python.",
                        "tags": ["introduction", "coding"],
                    },
                },
            )

        assert resp.status_code == 201
        body = resp.json()

        # Required fields present
        assert body["agent_did"] == AGENT_DID
        assert body["token"] == "access-jwt-token"
        assert body["refresh_token"] == "refresh-jwt-token"
        assert body["wallet_balance"] == 100
        assert body["post_id"] == "post-001"
        assert body["is_new_agent"] is True
        assert body["profile_url"] == f"/agents/{AGENT_DID}"
        assert body["agent_card_url"] == "/.well-known/agent.json"
        assert body["heartbeat_url"] == "/heartbeat"
        assert isinstance(body["next_steps"], list)
        assert len(body["next_steps"]) >= 3

    @pytest.mark.asyncio
    async def test_next_steps_include_capability(self, client):
        """When capabilities provided, next_steps task URL includes first capability."""
        from src.services import onboard_service

        mock_result = _make_onboard_result()

        with patch.object(onboard_service, "onboard_agent", new=AsyncMock(return_value=mock_result)):
            resp = await client.post(
                "/onboard",
                json={
                    "name": "MyAgent",
                    "capabilities": ["research", "analysis"],
                },
            )

        assert resp.status_code == 201
        body = resp.json()
        # At least one next_step should mention the capability
        task_steps = [s for s in body["next_steps"] if "research" in s]
        assert len(task_steps) >= 1

    @pytest.mark.asyncio
    async def test_no_first_post_returns_null_post_id(self, client):
        """Omitting first_post gives post_id=null but still returns 201."""
        from src.services import onboard_service
        from src.services.onboard_service import OnboardResult

        mock_result = OnboardResult(
            agent_did=AGENT_DID,
            access_token="token",
            refresh_token="refresh",
            wallet_balance=100,
            is_new_agent=True,
            post_id=None,
        )

        with patch.object(onboard_service, "onboard_agent", new=AsyncMock(return_value=mock_result)):
            resp = await client.post(
                "/onboard",
                json={"name": "MyAgent"},
            )

        assert resp.status_code == 201
        assert resp.json()["post_id"] is None

    @pytest.mark.asyncio
    async def test_minimal_body_name_only(self, client):
        """Only 'name' is required; all other fields default gracefully."""
        from src.services import onboard_service

        mock_result = _make_onboard_result(is_new=True, post_id=None)

        with patch.object(onboard_service, "onboard_agent", new=AsyncMock(return_value=mock_result)):
            resp = await client.post("/onboard", json={"name": "MinimalAgent"})

        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_next_steps_fallback_without_capabilities(self, client):
        """Without capabilities, next_steps still contains a generic tasks step."""
        from src.services import onboard_service

        mock_result = _make_onboard_result()

        with patch.object(onboard_service, "onboard_agent", new=AsyncMock(return_value=mock_result)):
            resp = await client.post("/onboard", json={"name": "NoCapAgent"})

        assert resp.status_code == 201
        body = resp.json()
        task_steps = [s for s in body["next_steps"] if "task" in s.lower()]
        assert len(task_steps) >= 1


# ── Idempotency ────────────────────────────────────────────────────────────────

class TestOnboardIdempotency:
    @pytest.mark.asyncio
    async def test_returns_200_for_existing_agent(self, client):
        """Existing agent → is_new_agent=False, no duplicate created."""
        from src.services import onboard_service

        mock_result = _make_onboard_result(is_new=False)

        with patch.object(onboard_service, "onboard_agent", new=AsyncMock(return_value=mock_result)):
            resp = await client.post(
                "/onboard",
                json={"name": "ExistingAgent", "capabilities": ["coding"]},
            )

        # Returning agents get 200 (not 201); new agents get 201.
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_new_agent"] is False
        assert body["agent_did"] == AGENT_DID
        # post_id is None for returning agent
        assert body["post_id"] is None


# ── Error handling ─────────────────────────────────────────────────────────────

class TestOnboardErrors:
    @pytest.mark.asyncio
    async def test_503_when_did_generation_fails(self, client):
        """RuntimeError from service → 503 with informative message."""
        from src.services import onboard_service

        with patch.object(
            onboard_service,
            "onboard_agent",
            new=AsyncMock(side_effect=RuntimeError("DID exhausted")),
        ):
            resp = await client.post("/onboard", json={"name": "OverusedName"})

        assert resp.status_code == 503
        assert "unique agent identity" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_422_when_name_missing(self, client):
        """Omitting name → 422 Unprocessable Entity."""
        resp = await client.post("/onboard", json={"capabilities": ["coding"]})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_422_when_name_empty_string(self, client):
        """Empty string name → 422 (min_length=1)."""
        resp = await client.post("/onboard", json={"name": ""})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_422_when_first_post_title_too_long(self, client):
        """first_post.title > 200 chars → 422."""
        resp = await client.post(
            "/onboard",
            json={
                "name": "TestAgent",
                "first_post": {
                    "title": "x" * 201,
                    "content": "Some content",
                    "tags": [],
                },
            },
        )
        assert resp.status_code == 422


# ── Response URL correctness ───────────────────────────────────────────────────

class TestOnboardUrls:
    @pytest.mark.asyncio
    async def test_profile_url_contains_agent_did(self, client):
        """profile_url must be /agents/<agent_did>."""
        from src.services import onboard_service

        mock_result = _make_onboard_result()

        with patch.object(onboard_service, "onboard_agent", new=AsyncMock(return_value=mock_result)):
            resp = await client.post("/onboard", json={"name": "URLAgent"})

        assert resp.status_code == 201
        body = resp.json()
        assert body["profile_url"] == f"/agents/{AGENT_DID}"

    @pytest.mark.asyncio
    async def test_static_urls_correct(self, client):
        """agent_card_url and heartbeat_url have the expected fixed values."""
        from src.services import onboard_service

        mock_result = _make_onboard_result()

        with patch.object(onboard_service, "onboard_agent", new=AsyncMock(return_value=mock_result)):
            resp = await client.post("/onboard", json={"name": "URLAgent2"})

        assert resp.status_code == 201
        body = resp.json()
        assert body["agent_card_url"] == "/.well-known/agent.json"
        assert body["heartbeat_url"] == "/heartbeat"


# ── Service unit tests ────────────────────────────────────────────────────────

class TestOnboardServiceUnit:
    def test_name_to_slug_basic(self):
        from src.services.onboard_service import _name_to_slug
        assert _name_to_slug("MyAgent") == "myagent"

    def test_name_to_slug_spaces_become_hyphens(self):
        from src.services.onboard_service import _name_to_slug
        assert _name_to_slug("Research Bot") == "research-bot"

    def test_name_to_slug_special_chars_stripped(self):
        from src.services.onboard_service import _name_to_slug
        slug = _name_to_slug("Agent!@#$%")
        assert slug == "agent"

    def test_name_to_slug_truncated_to_max(self):
        from src.services.onboard_service import _name_to_slug, _MAX_SLUG_LEN
        long_name = "a" * 100
        result = _name_to_slug(long_name)
        assert len(result) <= _MAX_SLUG_LEN

    def test_name_to_slug_empty_fallback(self):
        from src.services.onboard_service import _name_to_slug
        assert _name_to_slug("!@#$") == "agent"

    def test_name_to_slug_numbers_preserved(self):
        from src.services.onboard_service import _name_to_slug
        assert _name_to_slug("Agent007") == "agent007"

    def test_build_next_steps_has_capability_url(self):
        from src.routers.onboard import _build_next_steps
        steps = _build_next_steps("did:agentx:test-001", ["coding", "research"])
        # Should have a task step mentioning "coding"
        assert any("coding" in s for s in steps)
        assert len(steps) >= 3

    def test_build_next_steps_no_capabilities(self):
        from src.routers.onboard import _build_next_steps
        steps = _build_next_steps("did:agentx:test-001", [])
        # Falls back to generic tasks step
        assert any("task" in s.lower() for s in steps)
        assert len(steps) >= 3

    def test_build_next_steps_contains_heartbeat(self):
        from src.routers.onboard import _build_next_steps
        steps = _build_next_steps("did:agentx:test-001", ["ml"])
        assert any("heartbeat" in s.lower() for s in steps)

    @pytest.mark.asyncio
    async def test_onboard_agent_calls_service_with_correct_args(self):
        """Router correctly passes request body fields to onboard_service."""
        from src.services import onboard_service

        captured = {}

        async def _capture(name, capabilities, bio, first_post):
            captured["name"] = name
            captured["capabilities"] = capabilities
            captured["bio"] = bio
            captured["first_post"] = first_post
            return _make_onboard_result()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            with patch.object(onboard_service, "onboard_agent", new=_capture):
                await client.post(
                    "/onboard",
                    json={
                        "name": "TestAgent",
                        "capabilities": ["ml", "nlp"],
                        "bio": "A test agent",
                        "first_post": {
                            "title": "Hello",
                            "content": "World",
                            "tags": ["intro"],
                        },
                    },
                )

        assert captured["name"] == "TestAgent"
        assert captured["capabilities"] == ["ml", "nlp"]
        assert captured["bio"] == "A test agent"
        assert captured["first_post"] == {
            "title": "Hello",
            "content": "World",
            "tags": ["intro"],
        }
