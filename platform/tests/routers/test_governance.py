"""
Tests: src/routers/governance.py
Phase 9 -- Governance Layer

Covers:
  POST /governance/proposals  -- create a proposal (requires auth)
  GET  /governance/proposals  -- list active proposals
  POST /governance/vote       -- cast a vote (requires auth)
  GET  /governance/results    -- list finalized proposals
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


# -- Fixtures -----------------------------------------------------------------

@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


def _now():
    return datetime.now(UTC)


def _future(days: int = 7):
    return datetime.now(UTC) + timedelta(days=days)


# -- Model builders -----------------------------------------------------------

def _proposal(status="active", yes_power=0.0, no_power=0.0):
    from src.models.governance import ProposalResponse
    return ProposalResponse(
        proposal_id=uuid4(),
        proposer_did="did:agentx:proposer",
        proposer_id=uuid4(),
        title="Test Proposal",
        description="A proposal for testing",
        proposal_type="general",
        status=status,
        payload=None,
        yes_power=yes_power,
        no_power=no_power,
        voting_ends_at=_future(),
        created_at=_now(),
    )


def _vote_response():
    from src.models.governance import VoteResponse
    return VoteResponse(
        vote_id=uuid4(),
        proposal_id=uuid4(),
        voter_did="did:agentx:voter",
        vote="yes",
        vote_power=400.0,
        created_at=_now(),
    )


# -- Mock auth helper ---------------------------------------------------------

def _make_agent(did="did:agentx:caller-001"):
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    mock_claims = MagicMock(spec=TokenClaims)
    mock_claims.agent_did = did
    row = {
        "agent_did":       did,
        "display_name":    "Test Agent",
        "governance_role": "MEMBER",
        "tier":            "STANDARD",
        "status":          "ACTIVE",
        "trust_score":     0.8,
    }
    return AgentRecord(row=row, claims=mock_claims)


# -- POST /governance/proposals -----------------------------------------------

class TestCreateProposal:

    @pytest.mark.asyncio
    async def test_returns_201_on_success(self, client):
        from src.auth.middleware import get_current_agent
        prop = _proposal()

        with patch(
            "src.routers.governance.governance_service.create_proposal",
            new=AsyncMock(return_value=prop),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/governance/proposals",
                    json={
                        "title": "Test Proposal",
                        "description": "Details",
                        "voting_days": 7,
                    },
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Test Proposal"
        assert data["status"] == "active"

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        """Without auth, endpoint returns 401."""
        resp = await client.post(
            "/governance/proposals",
            json={"title": "T", "description": "D"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_returns_400_on_service_error(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.governance.governance_service.create_proposal",
            new=AsyncMock(side_effect=ValueError("validation failed")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/governance/proposals",
                    json={"title": "T", "description": "D"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400


# -- GET /governance/proposals ------------------------------------------------

class TestListProposals:

    @pytest.mark.asyncio
    async def test_returns_active_proposals(self, client):
        proposals = [_proposal(), _proposal()]

        with patch(
            "src.routers.governance.governance_service.list_proposals",
            new=AsyncMock(return_value=proposals),
        ):
            resp = await client.get("/governance/proposals")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert all(p["status"] == "active" for p in data)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_none(self, client):
        with patch(
            "src.routers.governance.governance_service.list_proposals",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/governance/proposals")

        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_no_auth_required(self, client):
        """GET /governance/proposals is public."""
        with patch(
            "src.routers.governance.governance_service.list_proposals",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/governance/proposals")

        assert resp.status_code == 200


# -- POST /governance/vote ----------------------------------------------------

class TestVoteOnProposal:

    @pytest.mark.asyncio
    async def test_returns_201_on_success(self, client):
        from src.auth.middleware import get_current_agent
        vote = _vote_response()

        with patch(
            "src.routers.governance.governance_service.vote_on_proposal",
            new=AsyncMock(return_value=vote),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/governance/vote",
                    json={"proposal_id": str(uuid4()), "vote": "yes"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        assert resp.json()["vote"] == "yes"
        assert resp.json()["vote_power"] == 400.0

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        resp = await client.post(
            "/governance/vote",
            json={"proposal_id": str(uuid4()), "vote": "yes"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_proposal(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.governance.governance_service.vote_on_proposal",
            new=AsyncMock(side_effect=ValueError("Proposal not found")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/governance/vote",
                    json={"proposal_id": str(uuid4()), "vote": "yes"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_400_for_already_voted(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.governance.governance_service.vote_on_proposal",
            new=AsyncMock(side_effect=ValueError("already voted on proposal")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/governance/vote",
                    json={"proposal_id": str(uuid4()), "vote": "yes"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400


# -- GET /governance/results --------------------------------------------------

class TestGetResults:

    @pytest.mark.asyncio
    async def test_returns_finalized_proposals(self, client):
        passed   = [_proposal(status="passed", yes_power=300.0)]
        failed   = [_proposal(status="failed", no_power=200.0)]
        executed = [_proposal(status="executed")]

        with patch(
            "src.routers.governance.governance_service.list_proposals",
            new=AsyncMock(side_effect=[passed, failed, executed]),
        ):
            resp = await client.get("/governance/results")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        statuses = {p["status"] for p in data}
        assert statuses == {"passed", "failed", "executed"}

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_results(self, client):
        with patch(
            "src.routers.governance.governance_service.list_proposals",
            new=AsyncMock(side_effect=[[], [], []]),
        ):
            resp = await client.get("/governance/results")

        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_no_auth_required(self, client):
        """GET /governance/results is public."""
        with patch(
            "src.routers.governance.governance_service.list_proposals",
            new=AsyncMock(side_effect=[[], [], []]),
        ):
            resp = await client.get("/governance/results")

        assert resp.status_code == 200
