"""
Tests: src/routers/reputation_graph.py
Phase 20 — Agent Reputation Graph

Covers:
  GET  /agents/{agent_id}/trust-network
  GET  /agents/{agent_id}/top-collaborators
  POST /agents/{agent_id}/trust-network/interactions
  GET  /agents/{agent_id}/graph-score

All service calls are mocked; no real DB connections are made.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.models.reputation_graph import (
    CollaboratorSummary,
    GraphEdge,
    GraphEnhancedScore,
)


# ── Fixtures and helpers ──────────────────────────────────────────────────────

@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


def _graph_edge(agent_id=None, peer_agent_id=None, trust_weight=0.5, count=1):
    return GraphEdge(
        graph_id=uuid4(),
        agent_id=agent_id or uuid4(),
        peer_agent_id=peer_agent_id or uuid4(),
        trust_weight=trust_weight,
        interaction_count=count,
        last_interaction=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )


def _collaborator(trust_weight=0.6, count=3):
    return CollaboratorSummary(
        peer_agent_id=uuid4(),
        trust_weight=trust_weight,
        interaction_count=count,
        last_interaction=datetime.now(UTC),
    )


# ── GET /agents/{agent_id}/trust-network ──────────────────────────────────────

class TestGetTrustNetwork:

    @pytest.mark.asyncio
    async def test_returns_200(self, client):
        agent_id = uuid4()
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_agent_trust_network",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/agents/{agent_id}/trust-network")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_response_has_agent_id(self, client):
        agent_id = uuid4()
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_agent_trust_network",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/agents/{agent_id}/trust-network")
        data = resp.json()
        assert data["agent_id"] == str(agent_id)

    @pytest.mark.asyncio
    async def test_response_has_peer_count(self, client):
        agent_id = uuid4()
        edges = [_graph_edge(agent_id=agent_id) for _ in range(3)]
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_agent_trust_network",
            new=AsyncMock(return_value=edges),
        ):
            resp = await client.get(f"/agents/{agent_id}/trust-network")
        data = resp.json()
        assert data["peer_count"] == 3

    @pytest.mark.asyncio
    async def test_response_has_peers_list(self, client):
        agent_id = uuid4()
        edges = [_graph_edge(agent_id=agent_id)]
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_agent_trust_network",
            new=AsyncMock(return_value=edges),
        ):
            resp = await client.get(f"/agents/{agent_id}/trust-network")
        data = resp.json()
        assert isinstance(data["peers"], list)
        assert len(data["peers"]) == 1

    @pytest.mark.asyncio
    async def test_empty_network_returns_zero_peers(self, client):
        agent_id = uuid4()
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_agent_trust_network",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/agents/{agent_id}/trust-network")
        data = resp.json()
        assert data["peer_count"] == 0
        assert data["peers"] == []

    @pytest.mark.asyncio
    async def test_limit_query_param_passed(self, client):
        agent_id = uuid4()
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_agent_trust_network",
            new=AsyncMock(return_value=[]),
        ) as mock_fn:
            await client.get(f"/agents/{agent_id}/trust-network?limit=5")
        mock_fn.assert_awaited_once_with(agent_id, limit=5)

    @pytest.mark.asyncio
    async def test_invalid_agent_id_returns_422(self, client):
        resp = await client.get("/agents/not-a-uuid/trust-network")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_limit_above_max_returns_422(self, client):
        agent_id = uuid4()
        resp = await client.get(f"/agents/{agent_id}/trust-network?limit=9999")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_limit_zero_returns_422(self, client):
        agent_id = uuid4()
        resp = await client.get(f"/agents/{agent_id}/trust-network?limit=0")
        assert resp.status_code == 422


# ── GET /agents/{agent_id}/top-collaborators ──────────────────────────────────

class TestGetTopCollaborators:

    @pytest.mark.asyncio
    async def test_returns_200(self, client):
        agent_id = uuid4()
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_top_collaborators",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/agents/{agent_id}/top-collaborators")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_list(self, client):
        agent_id = uuid4()
        collaborators = [_collaborator(), _collaborator()]
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_top_collaborators",
            new=AsyncMock(return_value=collaborators),
        ):
            resp = await client.get(f"/agents/{agent_id}/top-collaborators")
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, client):
        agent_id = uuid4()
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_top_collaborators",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/agents/{agent_id}/top-collaborators")
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_each_has_trust_weight(self, client):
        agent_id = uuid4()
        collaborators = [_collaborator(trust_weight=0.88)]
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_top_collaborators",
            new=AsyncMock(return_value=collaborators),
        ):
            resp = await client.get(f"/agents/{agent_id}/top-collaborators")
        item = resp.json()[0]
        assert "trust_weight" in item
        assert item["trust_weight"] == pytest.approx(0.88)

    @pytest.mark.asyncio
    async def test_limit_query_param_respected(self, client):
        agent_id = uuid4()
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_top_collaborators",
            new=AsyncMock(return_value=[]),
        ) as mock_fn:
            await client.get(f"/agents/{agent_id}/top-collaborators?limit=3")
        mock_fn.assert_awaited_once_with(agent_id, limit=3)

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_422(self, client):
        resp = await client.get("/agents/bad-uuid/top-collaborators")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_limit_above_50_returns_422(self, client):
        agent_id = uuid4()
        resp = await client.get(f"/agents/{agent_id}/top-collaborators?limit=100")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_each_has_peer_agent_id(self, client):
        agent_id = uuid4()
        collaborators = [_collaborator()]
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_top_collaborators",
            new=AsyncMock(return_value=collaborators),
        ):
            resp = await client.get(f"/agents/{agent_id}/top-collaborators")
        assert "peer_agent_id" in resp.json()[0]


# ── POST /agents/{agent_id}/trust-network/interactions ────────────────────────

class TestRecordInteraction:

    @pytest.mark.asyncio
    async def test_returns_201(self, client):
        agent_id = uuid4()
        peer_id = uuid4()
        edge = _graph_edge(agent_id=agent_id, peer_agent_id=peer_id)
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.record_interaction",
            new=AsyncMock(return_value=edge),
        ):
            resp = await client.post(
                f"/agents/{agent_id}/trust-network/interactions",
                json={"peer_agent_id": str(peer_id)},
            )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_response_has_graph_id(self, client):
        agent_id = uuid4()
        peer_id = uuid4()
        edge = _graph_edge(agent_id=agent_id, peer_agent_id=peer_id)
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.record_interaction",
            new=AsyncMock(return_value=edge),
        ):
            resp = await client.post(
                f"/agents/{agent_id}/trust-network/interactions",
                json={"peer_agent_id": str(peer_id)},
            )
        assert "graph_id" in resp.json()

    @pytest.mark.asyncio
    async def test_same_agent_returns_400(self, client):
        agent_id = uuid4()
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.record_interaction",
            new=AsyncMock(side_effect=ValueError("must be different")),
        ):
            resp = await client.post(
                f"/agents/{agent_id}/trust-network/interactions",
                json={"peer_agent_id": str(agent_id)},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_peer_agent_id_returns_422(self, client):
        agent_id = uuid4()
        resp = await client.post(
            f"/agents/{agent_id}/trust-network/interactions",
            json={},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_custom_weight_delta_accepted(self, client):
        agent_id = uuid4()
        peer_id = uuid4()
        edge = _graph_edge(agent_id=agent_id, peer_agent_id=peer_id)
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.record_interaction",
            new=AsyncMock(return_value=edge),
        ) as mock_fn:
            await client.post(
                f"/agents/{agent_id}/trust-network/interactions",
                json={
                    "peer_agent_id": str(peer_id),
                    "weight_delta": 0.12,
                    "interaction_type": "contract_completed",
                },
            )
        call_kwargs = mock_fn.await_args.kwargs
        assert call_kwargs["weight_delta"] == pytest.approx(0.12)
        assert call_kwargs["interaction_type"] == "contract_completed"

    @pytest.mark.asyncio
    async def test_default_weight_delta_is_01(self, client):
        agent_id = uuid4()
        peer_id = uuid4()
        edge = _graph_edge(agent_id=agent_id, peer_agent_id=peer_id)
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.record_interaction",
            new=AsyncMock(return_value=edge),
        ) as mock_fn:
            await client.post(
                f"/agents/{agent_id}/trust-network/interactions",
                json={"peer_agent_id": str(peer_id)},
            )
        call_kwargs = mock_fn.await_args.kwargs
        assert call_kwargs["weight_delta"] == pytest.approx(0.1)

    @pytest.mark.asyncio
    async def test_weight_above_1_returns_422(self, client):
        agent_id = uuid4()
        peer_id = uuid4()
        resp = await client.post(
            f"/agents/{agent_id}/trust-network/interactions",
            json={"peer_agent_id": str(peer_id), "weight_delta": 2.0},
        )
        assert resp.status_code == 422


# ── GET /agents/{agent_id}/graph-score ────────────────────────────────────────

class TestGetGraphScore:

    @pytest.mark.asyncio
    async def test_returns_200(self, client):
        agent_id = uuid4()
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_graph_weight_for_agent",
            new=AsyncMock(return_value=0.5),
        ), patch(
            "src.routers.reputation_graph.rep_graph_svc.calculate_graph_enhanced_score",
            return_value=0.55,
        ):
            resp = await client.get(f"/agents/{agent_id}/graph-score")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_response_has_agent_id(self, client):
        agent_id = uuid4()
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_graph_weight_for_agent",
            new=AsyncMock(return_value=0.4),
        ), patch(
            "src.routers.reputation_graph.rep_graph_svc.calculate_graph_enhanced_score",
            return_value=0.54,
        ):
            resp = await client.get(f"/agents/{agent_id}/graph-score")
        data = resp.json()
        assert data["agent_id"] == str(agent_id)

    @pytest.mark.asyncio
    async def test_response_has_base_score(self, client):
        agent_id = uuid4()
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_graph_weight_for_agent",
            new=AsyncMock(return_value=0.3),
        ), patch(
            "src.routers.reputation_graph.rep_graph_svc.calculate_graph_enhanced_score",
            return_value=0.53,
        ):
            resp = await client.get(f"/agents/{agent_id}/graph-score")
        data = resp.json()
        assert "base_score" in data

    @pytest.mark.asyncio
    async def test_response_has_graph_weight(self, client):
        agent_id = uuid4()
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_graph_weight_for_agent",
            new=AsyncMock(return_value=0.3),
        ), patch(
            "src.routers.reputation_graph.rep_graph_svc.calculate_graph_enhanced_score",
            return_value=0.53,
        ):
            resp = await client.get(f"/agents/{agent_id}/graph-score")
        data = resp.json()
        assert "graph_weight" in data

    @pytest.mark.asyncio
    async def test_response_has_enhanced_score(self, client):
        agent_id = uuid4()
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_graph_weight_for_agent",
            new=AsyncMock(return_value=0.4),
        ), patch(
            "src.routers.reputation_graph.rep_graph_svc.calculate_graph_enhanced_score",
            return_value=0.54,
        ):
            resp = await client.get(f"/agents/{agent_id}/graph-score")
        data = resp.json()
        assert "enhanced_score" in data

    @pytest.mark.asyncio
    async def test_custom_base_score_passed(self, client):
        agent_id = uuid4()
        with patch(
            "src.routers.reputation_graph.rep_graph_svc.get_graph_weight_for_agent",
            new=AsyncMock(return_value=0.3),
        ), patch(
            "src.routers.reputation_graph.rep_graph_svc.calculate_graph_enhanced_score",
            return_value=0.63,
        ) as mock_calc:
            await client.get(f"/agents/{agent_id}/graph-score?base_score=0.6")
        mock_calc.assert_called_once_with(pytest.approx(0.6), pytest.approx(0.3))

    @pytest.mark.asyncio
    async def test_base_score_above_1_returns_422(self, client):
        agent_id = uuid4()
        resp = await client.get(f"/agents/{agent_id}/graph-score?base_score=1.5")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_base_score_below_0_returns_422(self, client):
        agent_id = uuid4()
        resp = await client.get(f"/agents/{agent_id}/graph-score?base_score=-0.1")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_agent_id_returns_422(self, client):
        resp = await client.get("/agents/not-a-uuid/graph-score")
        assert resp.status_code == 422
