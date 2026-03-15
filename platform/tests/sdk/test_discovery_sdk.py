"""
Tests: agentx_sdk — DiscoveryClient (Phase 16)
════════════════════════════════════════════════════════════════════════════════
Covers:
  DiscoveryClient.discover_agents     — GET /agents/discover
  DiscoveryClient.get_top_agents      — GET /agents/top
  DiscoveryClient.search_agents       — POST /agents/search
  DiscoveryClient.get_agent_metrics   — GET /agents/{id}/metrics
  DiscoveryClient.register_capability — POST /agents/{id}/capabilities

All HTTP calls are mocked via httpx.  No live server required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agentx_sdk.discovery import DiscoveryClient

_BASE  = "http://localhost:8000"
_TOKEN = "test-jwt"


def _client() -> DiscoveryClient:
    return DiscoveryClient(base_url=_BASE, token=_TOKEN)


def _mock_resp(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


def _fake_agent():
    return {
        "agent_id":           str(uuid4()),
        "agent_did":          "did:agentx:agent",
        "name":               "Test Agent",
        "trust_score":        0.7,
        "capabilities":       ["collect_data"],
        "score":              0.55,
        "contracts_completed": 10,
    }


# ═════════════════════════════════════════════════════════════════════════════
# discover_agents
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscoveryClientDiscoverAgents:

    @pytest.mark.asyncio
    async def test_returns_list(self):
        agents = [_fake_agent(), _fake_agent()]
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_resp(agents))
            mock_cls.return_value = mock_http

            result = await _client().discover_agents(capability="collect_data")

        assert result == agents

    @pytest.mark.asyncio
    async def test_passes_capability_param(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_resp([]))
            mock_cls.return_value = mock_http

            await _client().discover_agents(capability="analyse_data", limit=5)

        params = mock_http.get.call_args.kwargs["params"]
        assert params["capability"] == "analyse_data"
        assert params["limit"] == 5

    @pytest.mark.asyncio
    async def test_no_capability_omits_param(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_resp([]))
            mock_cls.return_value = mock_http

            await _client().discover_agents()

        params = mock_http.get.call_args.kwargs["params"]
        assert "capability" not in params

    @pytest.mark.asyncio
    async def test_uses_correct_url(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_resp([]))
            mock_cls.return_value = mock_http

            await _client().discover_agents()

        url = mock_http.get.call_args[0][0]
        assert url == f"{_BASE}/agents/discover"

    @pytest.mark.asyncio
    async def test_sends_bearer_token(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_resp([]))
            mock_cls.return_value = mock_http

            await _client().discover_agents()

        headers = mock_http.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == f"Bearer {_TOKEN}"


# ═════════════════════════════════════════════════════════════════════════════
# get_top_agents
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscoveryClientGetTopAgents:

    @pytest.mark.asyncio
    async def test_returns_list(self):
        agents = [_fake_agent() for _ in range(3)]
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_resp(agents))
            mock_cls.return_value = mock_http

            result = await _client().get_top_agents(limit=3)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_uses_correct_url(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_resp([]))
            mock_cls.return_value = mock_http

            await _client().get_top_agents()

        url = mock_http.get.call_args[0][0]
        assert url == f"{_BASE}/agents/top"

    @pytest.mark.asyncio
    async def test_passes_limit_param(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_resp([]))
            mock_cls.return_value = mock_http

            await _client().get_top_agents(limit=7)

        params = mock_http.get.call_args.kwargs["params"]
        assert params["limit"] == 7


# ═════════════════════════════════════════════════════════════════════════════
# search_agents
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscoveryClientSearchAgents:

    @pytest.mark.asyncio
    async def test_returns_list(self):
        agents = [_fake_agent()]
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_resp(agents))
            mock_cls.return_value = mock_http

            result = await _client().search_agents("data collection")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_uses_correct_url(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_resp([]))
            mock_cls.return_value = mock_http

            await _client().search_agents("test")

        url = mock_http.post.call_args[0][0]
        assert url == f"{_BASE}/agents/search"

    @pytest.mark.asyncio
    async def test_sends_query_in_body(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_resp([]))
            mock_cls.return_value = mock_http

            await _client().search_agents("financial analysis", limit=5)

        body = mock_http.post.call_args.kwargs["json"]
        assert body["query"] == "financial analysis"
        assert body["limit"] == 5

    @pytest.mark.asyncio
    async def test_default_limit_is_10(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_resp([]))
            mock_cls.return_value = mock_http

            await _client().search_agents("query")

        body = mock_http.post.call_args.kwargs["json"]
        assert body["limit"] == 10


# ═════════════════════════════════════════════════════════════════════════════
# get_agent_metrics
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscoveryClientGetAgentMetrics:

    @pytest.mark.asyncio
    async def test_returns_metrics_dict(self):
        aid = str(uuid4())
        metrics = {
            "agent_id": aid,
            "contracts_completed": 10,
            "contracts_failed": 1,
            "verification_success": 0.9,
            "bounties_won": 2,
        }
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_resp(metrics))
            mock_cls.return_value = mock_http

            result = await _client().get_agent_metrics(aid)

        assert result["contracts_completed"] == 10

    @pytest.mark.asyncio
    async def test_uses_correct_url(self):
        aid = str(uuid4())
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_resp({"agent_id": aid}))
            mock_cls.return_value = mock_http

            await _client().get_agent_metrics(aid)

        url = mock_http.get.call_args[0][0]
        assert f"/agents/{aid}/metrics" in url

    @pytest.mark.asyncio
    async def test_is_public_no_token_needed(self):
        """get_agent_metrics should work without a bearer token."""
        public_client = DiscoveryClient(base_url=_BASE)  # no token
        aid = str(uuid4())
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_resp({"agent_id": aid}))
            mock_cls.return_value = mock_http

            result = await public_client.get_agent_metrics(aid)

        headers = mock_http.get.call_args.kwargs["headers"]
        assert "Authorization" not in headers


# ═════════════════════════════════════════════════════════════════════════════
# register_capability
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscoveryClientRegisterCapability:

    @pytest.mark.asyncio
    async def test_returns_capability_dict(self):
        aid = str(uuid4())
        cap = {
            "registry_id": str(uuid4()),
            "agent_id": aid,
            "capability": "collect_data",
            "confidence": 0.9,
            "created_at": "2026-01-01T00:00:00Z",
        }
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_resp(cap))
            mock_cls.return_value = mock_http

            result = await _client().register_capability(aid, "collect_data", 0.9)

        assert result["capability"] == "collect_data"

    @pytest.mark.asyncio
    async def test_uses_correct_url(self):
        aid = str(uuid4())
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_resp({}))
            mock_cls.return_value = mock_http

            await _client().register_capability(aid, "skill_x")

        url = mock_http.post.call_args[0][0]
        assert f"/agents/{aid}/capabilities" in url

    @pytest.mark.asyncio
    async def test_sends_capability_in_body(self):
        aid = str(uuid4())
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_resp({}))
            mock_cls.return_value = mock_http

            await _client().register_capability(aid, "analyse_data", confidence=0.75)

        body = mock_http.post.call_args.kwargs["json"]
        assert body["capability"] == "analyse_data"
        assert body["confidence"] == 0.75

    @pytest.mark.asyncio
    async def test_default_confidence_is_one(self):
        aid = str(uuid4())
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_resp({}))
            mock_cls.return_value = mock_http

            await _client().register_capability(aid, "x")

        body = mock_http.post.call_args.kwargs["json"]
        assert body["confidence"] == 1.0


# ═════════════════════════════════════════════════════════════════════════════
# DiscoveryClient construction
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscoveryClientConstruction:

    def test_strips_trailing_slash(self):
        c = DiscoveryClient(base_url="http://localhost:8000/")
        assert c._base_url == "http://localhost:8000"

    def test_default_timeout(self):
        c = DiscoveryClient(base_url=_BASE)
        assert c._timeout == 30.0

    def test_custom_timeout(self):
        c = DiscoveryClient(base_url=_BASE, timeout=60.0)
        assert c._timeout == 60.0

    def test_no_auth_header_without_token(self):
        c = DiscoveryClient(base_url=_BASE)
        assert "Authorization" not in c._headers()

    def test_auth_header_with_token(self):
        c = DiscoveryClient(base_url=_BASE, token="my-token")
        assert c._headers()["Authorization"] == "Bearer my-token"
