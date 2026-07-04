"""
Tests: Phase 19 — Agent-Created (Auto) Bounties
══════════════════════════════════════════════════
Covers:
  auto_bounty_service.create_agent_bounty()
  POST /markets/bounties/auto  (router)

All DB and HTTP calls are fully mocked.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth.middleware import get_current_agent
from src.main import app
from src.models.markets import BountyResponse


# ── Auth override helpers ─────────────────────────────────────────────────────
# The handler only reads `agent.did`, so a SimpleNamespace stand-in is enough.
def _auth(did: str = "did:agentx:agent1") -> None:
    """Install a JWT-auth override so the authenticated caller is `did`."""
    app.dependency_overrides[get_current_agent] = lambda: SimpleNamespace(did=did)


def _clear_auth() -> None:
    app.dependency_overrides.pop(get_current_agent, None)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bounty(capability="forecast", reward_pool=50) -> BountyResponse:
    return BountyResponse(
        bounty_id=uuid4(),
        creator_did="did:agentx:agent1",
        creator_id=uuid4(),
        title=f"Auto-generated {capability} task",
        description="Autonomously created work request.",
        capability_required=capability,
        reward_pool=reward_pool,
        status="open",
        deadline=None,
        winner_submission_id=None,
        created_at=datetime.now(UTC),
        closed_at=None,
    )


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


# ── auto_bounty_service unit tests ────────────────────────────────────────────

class TestAutoeBountyService:

    @pytest.mark.asyncio
    async def test_create_agent_bounty_delegates_to_bounty_service(self):
        """create_agent_bounty() calls bounty_service.create_bounty()."""
        expected = _bounty()
        with patch(
            "src.services.markets.auto_bounty_service.create_bounty",
            new=AsyncMock(return_value=expected),
        ) as mock_create:
            from src.services.markets.auto_bounty_service import create_agent_bounty
            from src.models.markets import BountyCreate

            result = await create_agent_bounty(
                agent_did="did:agentx:agent1",
                capability="forecast",
                reward_pool=50,
            )

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs[1]["caller_did"] == "did:agentx:agent1"
        assert result.capability_required == "forecast"

    @pytest.mark.asyncio
    async def test_reward_pool_clamped_to_minimum_one(self):
        """reward_pool=0 is clamped to 1."""
        expected = _bounty(reward_pool=1)
        with patch(
            "src.services.markets.auto_bounty_service.create_bounty",
            new=AsyncMock(return_value=expected),
        ) as mock_create:
            from src.services.markets.auto_bounty_service import create_agent_bounty
            from src.models.markets import BountyCreate

            await create_agent_bounty(
                agent_did="did:agentx:agent1",
                capability="forecast",
                reward_pool=0,
            )

        _, kwargs = mock_create.call_args
        assert kwargs["data"].reward_pool >= 1

    @pytest.mark.asyncio
    async def test_auto_title_generated_when_none(self):
        expected = _bounty()
        with patch(
            "src.services.markets.auto_bounty_service.create_bounty",
            new=AsyncMock(return_value=expected),
        ) as mock_create:
            from src.services.markets.auto_bounty_service import create_agent_bounty

            await create_agent_bounty(
                agent_did="did:agentx:agent1",
                capability="research",
                reward_pool=30,
            )

        _, kwargs = mock_create.call_args
        assert "research" in kwargs["data"].title.lower()

    @pytest.mark.asyncio
    async def test_custom_title_is_used(self):
        expected = _bounty()
        with patch(
            "src.services.markets.auto_bounty_service.create_bounty",
            new=AsyncMock(return_value=expected),
        ) as mock_create:
            from src.services.markets.auto_bounty_service import create_agent_bounty

            await create_agent_bounty(
                agent_did="did:agentx:agent1",
                capability="research",
                reward_pool=30,
                title="My Custom Title",
            )

        _, kwargs = mock_create.call_args
        assert kwargs["data"].title == "My Custom Title"

    @pytest.mark.asyncio
    async def test_custom_description_is_used(self):
        expected = _bounty()
        with patch(
            "src.services.markets.auto_bounty_service.create_bounty",
            new=AsyncMock(return_value=expected),
        ) as mock_create:
            from src.services.markets.auto_bounty_service import create_agent_bounty

            await create_agent_bounty(
                agent_did="did:agentx:agent1",
                capability="research",
                reward_pool=30,
                description="Custom description here",
            )

        _, kwargs = mock_create.call_args
        assert kwargs["data"].description == "Custom description here"

    @pytest.mark.asyncio
    async def test_value_error_propagated(self):
        with patch(
            "src.services.markets.auto_bounty_service.create_bounty",
            new=AsyncMock(side_effect=ValueError("Insufficient funds")),
        ):
            from src.services.markets.auto_bounty_service import create_agent_bounty

            with pytest.raises(ValueError, match="Insufficient funds"):
                await create_agent_bounty(
                    agent_did="did:agentx:poor",
                    capability="forecast",
                    reward_pool=10,
                )


# ── Router: POST /markets/bounties/auto ───────────────────────────────────────

class TestAutoBountyRouter:

    # ── SECURITY: the wallet-drain hole is closed ─────────────────────────────

    @pytest.mark.asyncio
    async def test_auto_bounty_requires_auth(self, client):
        """No JWT -> 401/403, never a 201 that would escrow funds."""
        resp = await client.post(
            "/markets/bounties/auto",
            json={"capability": "forecast", "reward_pool": 50},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_regression_unauth_drain_stays_closed(self, client):
        """SECURITY REGRESSION GUARD: an unauthenticated caller supplying a
        victim DID must NOT be able to escrow from that victim's wallet.
        This is the exact pre-fix attack; it must always fail closed."""
        resp = await client.post(
            "/markets/bounties/auto",
            json={"agent_did": "did:agentx:victim", "capability": "x", "reward_pool": 999},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_creator_did_comes_from_token_not_body(self, client):
        """Even if a (stale) client still sends agent_did for a victim, the
        service is called with the AUTHENTICATED caller's did — so a caller can
        only ever escrow from their own wallet."""
        captured = AsyncMock(return_value=_bounty())
        _auth("did:agentx:caller-A")
        try:
            with patch(
                "src.routers.agent_economy.auto_bounty_service.create_agent_bounty",
                new=captured,
            ):
                resp = await client.post(
                    "/markets/bounties/auto",
                    json={
                        "agent_did": "did:agentx:victim-B",  # must be ignored
                        "capability": "forecast",
                        "reward_pool": 50,
                    },
                )
        finally:
            _clear_auth()
        assert resp.status_code == 201
        assert captured.call_args.kwargs["agent_did"] == "did:agentx:caller-A"

    # ── Functional (now authenticated) ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_authenticated_owner_creates_bounty(self, client):
        _auth("did:agentx:agent1")
        try:
            with patch(
                "src.routers.agent_economy.auto_bounty_service.create_agent_bounty",
                new=AsyncMock(return_value=_bounty()),
            ):
                resp = await client.post(
                    "/markets/bounties/auto",
                    json={"capability": "forecast", "reward_pool": 50},
                )
        finally:
            _clear_auth()
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_response_body_has_bounty_id(self, client):
        _auth()
        try:
            with patch(
                "src.routers.agent_economy.auto_bounty_service.create_agent_bounty",
                new=AsyncMock(return_value=_bounty()),
            ):
                resp = await client.post(
                    "/markets/bounties/auto",
                    json={"capability": "forecast", "reward_pool": 50},
                )
        finally:
            _clear_auth()
        assert "bounty_id" in resp.json()

    @pytest.mark.asyncio
    async def test_missing_capability_returns_422(self, client):
        _auth()
        try:
            resp = await client.post(
                "/markets/bounties/auto",
                json={"reward_pool": 50},
            )
        finally:
            _clear_auth()
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_reward_pool_zero_returns_422(self, client):
        _auth()
        try:
            resp = await client.post(
                "/markets/bounties/auto",
                json={"capability": "forecast", "reward_pool": 0},
            )
        finally:
            _clear_auth()
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_service_value_error_returns_400(self, client):
        _auth()
        try:
            with patch(
                "src.routers.agent_economy.auto_bounty_service.create_agent_bounty",
                new=AsyncMock(side_effect=ValueError("Insufficient funds")),
            ):
                resp = await client.post(
                    "/markets/bounties/auto",
                    json={"capability": "forecast", "reward_pool": 50},
                )
        finally:
            _clear_auth()
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_optional_title_accepted(self, client):
        _auth()
        try:
            with patch(
                "src.routers.agent_economy.auto_bounty_service.create_agent_bounty",
                new=AsyncMock(return_value=_bounty()),
            ):
                resp = await client.post(
                    "/markets/bounties/auto",
                    json={"capability": "forecast", "reward_pool": 50, "title": "Custom Title"},
                )
        finally:
            _clear_auth()
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_optional_description_accepted(self, client):
        _auth()
        try:
            with patch(
                "src.routers.agent_economy.auto_bounty_service.create_agent_bounty",
                new=AsyncMock(return_value=_bounty()),
            ):
                resp = await client.post(
                    "/markets/bounties/auto",
                    json={"capability": "forecast", "reward_pool": 50, "description": "Custom description"},
                )
        finally:
            _clear_auth()
        assert resp.status_code == 201


# ── Router: GET /economy/strategies ──────────────────────────────────────────

class TestStrategyEndpoints:

    @pytest.mark.asyncio
    async def test_list_strategies_returns_200(self, client):
        resp = await client.get("/economy/strategies")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_strategies_returns_list(self, client):
        resp = await client.get("/economy/strategies")
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 4

    @pytest.mark.asyncio
    async def test_strategy_has_name(self, client):
        resp = await client.get("/economy/strategies")
        for item in resp.json():
            assert "name" in item

    @pytest.mark.asyncio
    async def test_select_strategy_returns_200(self, client):
        resp = await client.post(
            "/economy/strategies/select",
            json={"agent_id": "agent1", "capabilities": ["forecast"]},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_select_strategy_returns_specialist_for_one_cap(self, client):
        resp = await client.post(
            "/economy/strategies/select",
            json={"agent_id": "agent1", "capabilities": ["forecast"]},
        )
        data = resp.json()
        assert data["strategy"] == "specialist"

    @pytest.mark.asyncio
    async def test_select_strategy_returns_coordinator_for_four_caps(self, client):
        resp = await client.post(
            "/economy/strategies/select",
            json={
                "agent_id": "agent1",
                "capabilities": ["a", "b", "c", "d"],
            },
        )
        data = resp.json()
        assert data["strategy"] == "coordinator"

    @pytest.mark.asyncio
    async def test_market_analysis_returns_200(self, client):
        resp = await client.post(
            "/economy/market-analysis",
            json={"bounties": [], "agents": []},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_market_analysis_returns_health(self, client):
        resp = await client.post(
            "/economy/market-analysis",
            json={"bounties": [], "agents": []},
        )
        data = resp.json()
        assert "market_health" in data
        assert data["market_health"] == "empty"
