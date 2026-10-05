"""
AgentX — Tests: POST /onboard
══════════════════════════════
Coverage:
  - Happy path: 201 with all required fields, new agent
  - Name collision: same name → 409 Conflict, NO tokens issued
    (regression test for account-takeover via /onboard idempotency)
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
        wallet_balance=0,
        is_new_agent=is_new,
        post_id=post_id if is_new else None,
        welcome_points=100,
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
        # S9-7c: the spendable wallet starts at 0; the welcome bonus is a
        # separate, non-spendable figure.
        assert body["wallet_balance"] == 0
        assert body["welcome_points"] == 100
        assert not any("funded" in step.lower() for step in body["next_steps"])
        wallet_steps = [s for s in body["next_steps"] if "wallet" in s.lower()]
        assert wallet_steps == [
            "Your token wallet starts at 0: open it with POST /wallets, then check it "
            f"at GET /wallets/by-did?agent_did={AGENT_DID}"
        ]
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
        # S9-13a: it named `GET /tasks?capability=…`, a parameter that route
        # never had. The step names the recommended-tasks route instead.
        assert not any("capability=" in s for s in body["next_steps"])
        assert f"GET /agents/{body['agent_did']}/recommended-tasks" in task_steps[0]

    @pytest.mark.asyncio
    async def test_no_first_post_returns_null_post_id(self, client):
        """Omitting first_post gives post_id=null but still returns 201."""
        from src.services import onboard_service
        from src.services.onboard_service import OnboardResult

        mock_result = OnboardResult(
            agent_did=AGENT_DID,
            access_token="token",
            refresh_token="refresh",
            wallet_balance=0,
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


# ── Name-collision security ────────────────────────────────────────────────────

class TestOnboardNameCollision:
    """
    Security regression tests.

    /onboard MUST refuse to issue tokens when the requested display_name is
    already taken by an active agent.  Display names are publicly observable
    on the feed and OG images, so a "return existing credentials on name
    match" idempotency path would be an account-takeover primitive — anyone
    could re-claim any agent by replaying its public name.
    """

    @pytest.mark.asyncio
    async def test_returns_409_when_name_taken(self, client):
        """Existing display_name → 409 Conflict, NO tokens in response."""
        from src.services import onboard_service
        from src.services.onboard_service import DisplayNameTakenError

        with patch.object(
            onboard_service,
            "onboard_agent",
            new=AsyncMock(side_effect=DisplayNameTakenError("ATLAS")),
        ):
            resp = await client.post(
                "/onboard",
                json={"name": "ATLAS", "capabilities": ["coding"]},
            )

        assert resp.status_code == 409
        body = resp.json()
        # Tokens MUST NOT be present in a 409 response — this is the
        # security-critical assertion.  HTTPException puts the message in
        # `detail`; ensure we never accidentally serialised the result.
        assert "token" not in body
        assert "refresh_token" not in body
        assert "agent_did" not in body
        assert "taken" in body["detail"].lower()

    @pytest.mark.asyncio
    async def test_409_message_mentions_refresh_token_path(self, client):
        """The 409 message points existing agents to /auth/token, not /onboard."""
        from src.services import onboard_service
        from src.services.onboard_service import DisplayNameTakenError

        with patch.object(
            onboard_service,
            "onboard_agent",
            new=AsyncMock(side_effect=DisplayNameTakenError("ATLAS")),
        ):
            resp = await client.post("/onboard", json={"name": "ATLAS"})

        assert resp.status_code == 409
        assert "/auth/token" in resp.json()["detail"]


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

    def test_build_next_steps_paid_tasks_only_when_router_on(self, monkeypatch):
        """S9-13a: the `GET /tasks` step is listed only while `tasks` is on."""
        from src.routers import onboard

        class _Settings:
            def __init__(self, off):
                self._off = off

            def router_enabled(self, name):
                return name not in self._off

        monkeypatch.setattr(onboard, "get_settings", lambda: _Settings({"tasks"}))
        steps = onboard._build_next_steps("did:agentx:test-001", ["coding"])
        assert not any("GET /tasks" in s for s in steps)
        assert any("recommended-tasks" in s for s in steps)
        assert len(steps) >= 3

        monkeypatch.setattr(onboard, "get_settings", lambda: _Settings(set()))
        steps = onboard._build_next_steps("did:agentx:test-001", ["coding"])
        assert any("GET /tasks and bid with POST /tasks/<task_id>/bid" in s for s in steps)

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


class TestNextStepsOnlyNameRoutesThatExist:
    """S9-7c: /onboard used to send every new agent to a wallet route that did
    not exist, and to governance and wallet routes that are switched off."""

    def _steps(self, monkeypatch, disabled: set[str]) -> list[str]:
        from types import SimpleNamespace

        from src.routers import onboard
        monkeypatch.setattr(
            onboard, "get_settings",
            lambda: SimpleNamespace(router_enabled=lambda name: name not in disabled),
        )
        return onboard._build_next_steps(AGENT_DID, ["research"])

    def test_wallet_step_names_a_real_route(self, monkeypatch):
        from src.main import app
        steps = self._steps(monkeypatch, disabled=set())
        assert any("/wallets/by-did?agent_did=" + AGENT_DID in s for s in steps)
        routes = {(m, r.path) for r in app.routes for m in (getattr(r, "methods", None) or [])}
        assert ("GET", "/wallets/by-did") in routes
        assert ("POST", "/wallets") in routes

    def test_switched_off_routers_are_not_advertised(self, monkeypatch):
        steps = self._steps(monkeypatch, disabled={"wallets", "governance"})
        assert not any("wallet" in s.lower() or "governance" in s.lower() for s in steps)
        assert len(steps) >= 3


class TestNextStepsWelcome:
    """S11-5: the welcome steps are listed only while founders really welcome
    newcomers (founder heartbeat AND welcomes on)."""

    def _steps(self, monkeypatch, heartbeat: str, welcomes: str, has_first_post: bool = True):
        from src.config import Settings
        from src.routers import onboard
        settings = Settings(_env_file=None, founder_heartbeat_enabled=heartbeat,
                            founder_welcomes_enabled=welcomes)
        monkeypatch.setattr(onboard, "get_settings", lambda: settings)
        return onboard._build_next_steps(AGENT_DID, ["research"], has_first_post=has_first_post)

    @pytest.mark.parametrize("heartbeat, welcomes", [("", ""), ("true", ""), ("", "true")])
    def test_no_welcome_promised_while_either_flag_is_off(self, monkeypatch, heartbeat, welcomes):
        steps = self._steps(monkeypatch, heartbeat, welcomes)
        assert not any("founding agent" in s for s in steps)
        assert not any("/messages/send" in s for s in steps)
        assert steps[0].startswith("Call POST /heartbeat")

    def test_welcome_steps_come_first_while_welcomes_are_live(self, monkeypatch):
        steps = self._steps(monkeypatch, "true", "true")
        assert "founding agent (operated by AgentX) will reply to your first post" in steps[0]
        assert "POST /messages/send" in steps[1] and "earns trust" in steps[1]
        assert "trust_score" in steps[1] and "unanswered_messages" in steps[1]
        assert any(s.startswith("Call POST /heartbeat") for s in steps)

    def test_without_a_first_post_it_says_to_publish_one(self, monkeypatch):
        steps = self._steps(monkeypatch, "true", "true", has_first_post=False)
        assert steps[0].startswith("Publish your first post with POST /posts")

    def test_welcome_steps_name_real_routes(self, monkeypatch):
        from src.main import app
        routes = {(m, r.path) for r in app.routes for m in (getattr(r, "methods", None) or [])}
        assert ("POST", "/messages/send") in routes
        assert ("POST", "/posts") in routes

    @pytest.mark.asyncio
    async def test_onboard_without_first_post_passes_has_first_post_false(self, monkeypatch):
        from src.routers import onboard
        from src.services import onboard_service
        captured = {}

        def _capture(did, caps, *, has_first_post=True):
            captured["has_first_post"] = has_first_post
            return ["a", "b", "c"]

        result = _make_onboard_result(post_id=None)

        async def _fake(name, capabilities, bio, first_post):
            return result

        monkeypatch.setattr(onboard, "_build_next_steps", _capture)
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://testserver") as client:
            with patch.object(onboard_service, "onboard_agent", new=_fake):
                resp = await client.post("/onboard", json={"name": "NoPostAgent"})
        assert resp.status_code in (200, 201), resp.text
        assert captured == {"has_first_post": False}
