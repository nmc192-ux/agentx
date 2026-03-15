"""
Tests: discovery router (Phase 16)
════════════════════════════════════════════════════════════════════════════════
Covers:
  GET  /agents/discover                 — by capability (public)
  GET  /agents/top                      — global ranking (public)
  POST /agents/search                   — semantic search (public)
  GET  /agents/{agent_id}/metrics       — per-agent metrics (public)
  POST /agents/{agent_id}/capabilities  — register capability (auth)

All service calls and auth are mocked; no live DB/Redis required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.models.discovery import (
    AgentCapability,
    AgentDiscoveryResponse,
    AgentMetricsResponse,
)

client = TestClient(app, raise_server_exceptions=False)

# ── Fixtures ──────────────────────────────────────────────────────────────────

MOCK_AGENT = MagicMock()
MOCK_AGENT.did = "did:agentx:tester"


def _discovery_response(**kwargs):
    return AgentDiscoveryResponse(
        agent_id=uuid4(),
        agent_did="did:agentx:agent",
        name="Test Agent",
        trust_score=0.7,
        capabilities=["collect_data"],
        score=0.55,
        contracts_completed=10,
        **kwargs,
    )


def _metrics_response(agent_id=None):
    return AgentMetricsResponse(
        agent_id=agent_id or uuid4(),
        contracts_completed=5,
        contracts_failed=0,
        verification_success=0.9,
        bounties_won=1,
    )


def _capability_response(agent_id=None):
    return AgentCapability(
        registry_id=uuid4(),
        agent_id=agent_id or uuid4(),
        capability="collect_data",
        confidence=0.9,
        created_at="2026-01-01T00:00:00Z",
    )


def _auth():
    from src.auth.middleware import get_current_agent
    app.dependency_overrides[get_current_agent] = lambda: MOCK_AGENT


def _clear_auth():
    app.dependency_overrides.clear()


# ═════════════════════════════════════════════════════════════════════════════
# GET /agents/discover
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscoverEndpoint:

    def test_discover_returns_200(self):
        with patch(
            "src.routers.discovery.discovery_service.list_agents_by_capability",
            new_callable=AsyncMock,
            return_value=[_discovery_response()],
        ):
            resp = client.get("/agents/discover?capability=collect_data")
        assert resp.status_code == 200

    def test_discover_returns_list(self):
        agents = [_discovery_response(), _discovery_response()]
        with patch(
            "src.routers.discovery.discovery_service.list_agents_by_capability",
            new_callable=AsyncMock,
            return_value=agents,
        ):
            resp = client.get("/agents/discover?capability=collect_data")
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_discover_calls_list_agents_when_capability_given(self):
        mock_list = AsyncMock(return_value=[])
        with patch("src.routers.discovery.discovery_service.list_agents_by_capability", mock_list):
            client.get("/agents/discover?capability=analyse_data&limit=5")
        mock_list.assert_called_once_with(capability="analyse_data", limit=5)

    def test_discover_falls_back_to_top_when_no_capability(self):
        mock_top = AsyncMock(return_value=[])
        with patch("src.routers.discovery.discovery_service.get_top_agents", mock_top):
            client.get("/agents/discover?limit=3")
        mock_top.assert_called_once_with(limit=3)

    def test_discover_is_public(self):
        with patch(
            "src.routers.discovery.discovery_service.get_top_agents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/agents/discover")
        assert resp.status_code == 200

    def test_discover_response_has_score_field(self):
        with patch(
            "src.routers.discovery.discovery_service.list_agents_by_capability",
            new_callable=AsyncMock,
            return_value=[_discovery_response()],
        ):
            resp = client.get("/agents/discover?capability=collect_data")
        assert "score" in resp.json()[0]

    def test_discover_default_limit_is_ten(self):
        mock_list = AsyncMock(return_value=[])
        with patch("src.routers.discovery.discovery_service.list_agents_by_capability", mock_list):
            client.get("/agents/discover?capability=x")
        _, kwargs = mock_list.call_args
        assert kwargs.get("limit") == 10 or mock_list.call_args[0][1] == 10

    def test_discover_invalid_limit_returns_422(self):
        resp = client.get("/agents/discover?limit=0")
        assert resp.status_code == 422


# ═════════════════════════════════════════════════════════════════════════════
# GET /agents/top
# ═════════════════════════════════════════════════════════════════════════════

class TestTopAgentsEndpoint:

    def test_top_returns_200(self):
        with patch(
            "src.routers.discovery.discovery_service.get_top_agents",
            new_callable=AsyncMock,
            return_value=[_discovery_response()],
        ):
            resp = client.get("/agents/top")
        assert resp.status_code == 200

    def test_top_returns_list(self):
        agents = [_discovery_response() for _ in range(5)]
        with patch(
            "src.routers.discovery.discovery_service.get_top_agents",
            new_callable=AsyncMock,
            return_value=agents,
        ):
            resp = client.get("/agents/top")
        assert len(resp.json()) == 5

    def test_top_passes_limit(self):
        mock_top = AsyncMock(return_value=[])
        with patch("src.routers.discovery.discovery_service.get_top_agents", mock_top):
            client.get("/agents/top?limit=3")
        mock_top.assert_called_once_with(limit=3)

    def test_top_is_public(self):
        with patch(
            "src.routers.discovery.discovery_service.get_top_agents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/agents/top")
        assert resp.status_code == 200

    def test_top_response_contains_trust_score(self):
        with patch(
            "src.routers.discovery.discovery_service.get_top_agents",
            new_callable=AsyncMock,
            return_value=[_discovery_response()],
        ):
            resp = client.get("/agents/top")
        assert "trust_score" in resp.json()[0]


# ═════════════════════════════════════════════════════════════════════════════
# POST /agents/search
# ═════════════════════════════════════════════════════════════════════════════

class TestSearchEndpoint:

    def test_search_returns_200(self):
        with patch(
            "src.routers.discovery.discovery_service.search_agents_semantic",
            new_callable=AsyncMock,
            return_value=[_discovery_response()],
        ):
            resp = client.post("/agents/search", json={"query": "data collector"})
        assert resp.status_code == 200

    def test_search_returns_list(self):
        agents = [_discovery_response(), _discovery_response()]
        with patch(
            "src.routers.discovery.discovery_service.search_agents_semantic",
            new_callable=AsyncMock,
            return_value=agents,
        ):
            resp = client.post("/agents/search", json={"query": "collect"})
        assert len(resp.json()) == 2

    def test_search_passes_query(self):
        mock_search = AsyncMock(return_value=[])
        with patch("src.routers.discovery.discovery_service.search_agents_semantic", mock_search):
            client.post("/agents/search", json={"query": "financial analysis", "limit": 5})
        mock_search.assert_called_once_with(query="financial analysis", limit=5)

    def test_search_missing_query_returns_422(self):
        resp = client.post("/agents/search", json={})
        assert resp.status_code == 422

    def test_search_is_public(self):
        with patch(
            "src.routers.discovery.discovery_service.search_agents_semantic",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.post("/agents/search", json={"query": "test"})
        assert resp.status_code == 200

    def test_search_empty_query_returns_422(self):
        resp = client.post("/agents/search", json={"query": ""})
        assert resp.status_code == 422

    def test_search_response_has_required_fields(self):
        with patch(
            "src.routers.discovery.discovery_service.search_agents_semantic",
            new_callable=AsyncMock,
            return_value=[_discovery_response()],
        ):
            resp = client.post("/agents/search", json={"query": "data"})
        item = resp.json()[0]
        assert "agent_id" in item
        assert "agent_did" in item
        assert "score" in item


# ═════════════════════════════════════════════════════════════════════════════
# GET /agents/{agent_id}/metrics
# ═════════════════════════════════════════════════════════════════════════════

class TestAgentMetricsEndpoint:

    def test_metrics_returns_200(self):
        aid = uuid4()
        with patch(
            "src.routers.discovery.discovery_service.get_agent_metrics",
            new_callable=AsyncMock,
            return_value=_metrics_response(agent_id=aid),
        ):
            resp = client.get(f"/agents/{aid}/metrics")
        assert resp.status_code == 200

    def test_metrics_returns_correct_fields(self):
        aid = uuid4()
        with patch(
            "src.routers.discovery.discovery_service.get_agent_metrics",
            new_callable=AsyncMock,
            return_value=_metrics_response(agent_id=aid),
        ):
            resp = client.get(f"/agents/{aid}/metrics")
        data = resp.json()
        assert "contracts_completed" in data
        assert "verification_success" in data
        assert "bounties_won" in data

    def test_metrics_not_found_returns_404(self):
        with patch(
            "src.routers.discovery.discovery_service.get_agent_metrics",
            new_callable=AsyncMock,
            side_effect=ValueError("Agent not found"),
        ):
            resp = client.get(f"/agents/{uuid4()}/metrics")
        assert resp.status_code == 404

    def test_metrics_is_public(self):
        aid = uuid4()
        with patch(
            "src.routers.discovery.discovery_service.get_agent_metrics",
            new_callable=AsyncMock,
            return_value=_metrics_response(agent_id=aid),
        ):
            resp = client.get(f"/agents/{aid}/metrics")
        assert resp.status_code == 200

    def test_metrics_zero_values_valid(self):
        aid = uuid4()
        with patch(
            "src.routers.discovery.discovery_service.get_agent_metrics",
            new_callable=AsyncMock,
            return_value=AgentMetricsResponse(agent_id=aid),
        ):
            resp = client.get(f"/agents/{aid}/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["contracts_completed"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# POST /agents/{agent_id}/discovery/capabilities
# (path uses /discovery/capabilities to avoid conflicting with the existing
#  capabilities router which uses DID-string agents on the same path)
# ═════════════════════════════════════════════════════════════════════════════

class TestRegisterCapabilityEndpoint:

    def setup_method(self):
        _auth()

    def teardown_method(self):
        _clear_auth()

    def test_register_returns_201(self):
        aid = uuid4()
        cap = _capability_response(agent_id=aid)
        with patch(
            "src.routers.discovery.discovery_service.register_capability",
            new_callable=AsyncMock,
            return_value=cap,
        ):
            resp = client.post(
                f"/agents/{aid}/discovery/capabilities",
                json={"capability": "collect_data", "confidence": 0.9},
            )
        assert resp.status_code == 201

    def test_register_returns_capability_data(self):
        aid = uuid4()
        cap = _capability_response(agent_id=aid)
        with patch(
            "src.routers.discovery.discovery_service.register_capability",
            new_callable=AsyncMock,
            return_value=cap,
        ):
            resp = client.post(
                f"/agents/{aid}/discovery/capabilities",
                json={"capability": "analyse_data"},
            )
        data = resp.json()
        assert "registry_id" in data
        assert data["capability"] == "collect_data"

    def test_register_agent_not_found_returns_404(self):
        aid = uuid4()
        with patch(
            "src.routers.discovery.discovery_service.register_capability",
            new_callable=AsyncMock,
            side_effect=ValueError(f"Agent not found: {aid}"),
        ):
            resp = client.post(
                f"/agents/{aid}/discovery/capabilities",
                json={"capability": "skill_x"},
            )
        assert resp.status_code == 404

    def test_register_requires_auth(self):
        _clear_auth()
        resp = client.post(
            f"/agents/{uuid4()}/discovery/capabilities",
            json={"capability": "skill_x"},
        )
        assert resp.status_code in (401, 403, 422)

    def test_register_missing_capability_returns_422(self):
        resp = client.post(f"/agents/{uuid4()}/discovery/capabilities", json={})
        assert resp.status_code == 422

    def test_register_invalid_confidence_returns_422(self):
        resp = client.post(
            f"/agents/{uuid4()}/discovery/capabilities",
            json={"capability": "x", "confidence": 2.0},  # > 1.0
        )
        assert resp.status_code == 422
