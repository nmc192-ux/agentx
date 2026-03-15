"""
Tests: src/routers/verifications.py
Phase 12 -- Result Verification Engine

Covers:
  POST /verifications                  -- create verification (requires auth)
  POST /verifications/{id}/vote        -- submit vote (requires auth)
  GET  /verifications/pending          -- list pending/active (public)
  GET  /verifications/{id}             -- get single verification (public)
"""
from __future__ import annotations

from datetime import UTC, datetime
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


# -- Model builders -----------------------------------------------------------

def _verification(status="active"):
    from src.models.verification import VerificationResponse
    return VerificationResponse(
        verification_id=uuid4(),
        contract_id=uuid4(),
        result_id=uuid4(),
        requester_did="did:agentx:creator",
        requester_id=uuid4(),
        status=status,
        required_votes=3,
        consensus_threshold=0.6,
        yes_power=0.0,
        no_power=0.0,
        vote_count=0,
        reward_pool=0,
        created_at=_now(),
        finalized_at=None,
    )


def _vote_resp():
    from src.models.verification import VerificationVoteResponse
    return VerificationVoteResponse(
        vote_id=uuid4(),
        verification_id=uuid4(),
        verifier_did="did:agentx:verifier",
        vote="approve",
        vote_power=2.0,
        comment=None,
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


# -- POST /verifications -------------------------------------------------------

class TestCreateVerification:

    @pytest.mark.asyncio
    async def test_returns_201_on_success(self, client):
        from src.auth.middleware import get_current_agent
        v = _verification(status="active")

        with patch(
            "src.routers.verifications.verification_service.create_verification",
            new=AsyncMock(return_value=v),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/verifications",
                    json={
                        "contract_id": str(uuid4()),
                        "result_id":   str(uuid4()),
                    },
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "active"
        assert data["required_votes"] == 3

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        resp = await client.post(
            "/verifications",
            json={"contract_id": str(uuid4()), "result_id": str(uuid4())},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_returns_404_for_missing_contract(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.verifications.verification_service.create_verification",
            new=AsyncMock(side_effect=ValueError("Contract not found")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/verifications",
                    json={"contract_id": str(uuid4()), "result_id": str(uuid4())},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_400_when_not_creator(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.verifications.verification_service.create_verification",
            new=AsyncMock(side_effect=ValueError("Only the contract creator")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/verifications",
                    json={"contract_id": str(uuid4()), "result_id": str(uuid4())},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_caller_did_comes_from_auth(self, client):
        from src.auth.middleware import get_current_agent
        v = _verification()

        with patch(
            "src.routers.verifications.verification_service.create_verification",
            new=AsyncMock(return_value=v),
        ) as mock_svc:
            app.dependency_overrides[get_current_agent] = lambda: _make_agent("did:agentx:creator")
            try:
                await client.post(
                    "/verifications",
                    json={"contract_id": str(uuid4()), "result_id": str(uuid4())},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        call_kwargs = mock_svc.call_args[1]
        assert call_kwargs["caller_did"] == "did:agentx:creator"


# -- POST /verifications/{id}/vote --------------------------------------------

class TestSubmitVote:

    @pytest.mark.asyncio
    async def test_returns_201_on_success(self, client):
        from src.auth.middleware import get_current_agent
        vid  = uuid4()
        vote = _vote_resp()

        with patch(
            "src.routers.verifications.verification_service.submit_vote",
            new=AsyncMock(return_value=vote),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    f"/verifications/{vid}/vote",
                    json={"vote": "approve"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        data = resp.json()
        assert data["vote"] == "approve"
        assert data["vote_power"] == 2.0

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        resp = await client.post(
            f"/verifications/{uuid4()}/vote",
            json={"vote": "approve"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_verification(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.verifications.verification_service.submit_vote",
            new=AsyncMock(side_effect=ValueError("Verification not found")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    f"/verifications/{uuid4()}/vote",
                    json={"vote": "approve"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_400_if_not_active(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.verifications.verification_service.submit_vote",
            new=AsyncMock(side_effect=ValueError("not active")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    f"/verifications/{uuid4()}/vote",
                    json={"vote": "reject"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_returns_400_for_duplicate_vote(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.verifications.verification_service.submit_vote",
            new=AsyncMock(side_effect=ValueError("already voted")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    f"/verifications/{uuid4()}/vote",
                    json={"vote": "approve"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_vote_with_comment(self, client):
        from src.auth.middleware import get_current_agent
        vote = _vote_resp()

        with patch(
            "src.routers.verifications.verification_service.submit_vote",
            new=AsyncMock(return_value=vote),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    f"/verifications/{uuid4()}/vote",
                    json={"vote": "reject", "comment": "Does not meet spec"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201


# -- GET /verifications/pending -----------------------------------------------

class TestGetPendingVerifications:

    @pytest.mark.asyncio
    async def test_returns_200_with_list(self, client):
        verifications = [_verification("pending"), _verification("active")]

        with patch(
            "src.routers.verifications.verification_service.list_pending_verifications",
            new=AsyncMock(return_value=verifications),
        ):
            resp = await client.get("/verifications/pending")

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_no_auth_required(self, client):
        with patch(
            "src.routers.verifications.verification_service.list_pending_verifications",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/verifications/pending")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_empty_list(self, client):
        with patch(
            "src.routers.verifications.verification_service.list_pending_verifications",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/verifications/pending")

        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_response_fields_correct(self, client):
        v = _verification("active")
        with patch(
            "src.routers.verifications.verification_service.list_pending_verifications",
            new=AsyncMock(return_value=[v]),
        ):
            resp = await client.get("/verifications/pending")

        item = resp.json()[0]
        assert "verification_id" in item
        assert "status" in item
        assert "required_votes" in item
        assert item["status"] == "active"


# -- GET /verifications/{id} --------------------------------------------------

class TestGetVerification:

    @pytest.mark.asyncio
    async def test_returns_200_on_success(self, client):
        vid = uuid4()
        v   = _verification("active")

        with patch(
            "src.routers.verifications.verification_service.get_verification",
            new=AsyncMock(return_value=v),
        ):
            resp = await client.get(f"/verifications/{vid}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_id(self, client):
        with patch(
            "src.routers.verifications.verification_service.get_verification",
            new=AsyncMock(side_effect=ValueError("Verification not found")),
        ):
            resp = await client.get(f"/verifications/{uuid4()}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_no_auth_required(self, client):
        v = _verification("verified")

        with patch(
            "src.routers.verifications.verification_service.get_verification",
            new=AsyncMock(return_value=v),
        ):
            resp = await client.get(f"/verifications/{uuid4()}")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_finalized_verification(self, client):
        from src.models.verification import VerificationResponse
        v = VerificationResponse(
            verification_id=uuid4(),
            contract_id=uuid4(),
            result_id=uuid4(),
            requester_did="did:agentx:creator",
            status="verified",
            required_votes=3,
            consensus_threshold=0.6,
            yes_power=7.5,
            no_power=2.5,
            vote_count=3,
            reward_pool=0,
            created_at=_now(),
            finalized_at=_now(),
        )

        with patch(
            "src.routers.verifications.verification_service.get_verification",
            new=AsyncMock(return_value=v),
        ):
            resp = await client.get(f"/verifications/{v.verification_id}")

        data = resp.json()
        assert data["status"] == "verified"
        assert data["yes_power"] == 7.5
        assert data["finalized_at"] is not None

    @pytest.mark.asyncio
    async def test_pending_literal_path_does_not_conflict(self, client):
        """Ensure GET /verifications/pending isn't captured by /{id} route."""
        with patch(
            "src.routers.verifications.verification_service.list_pending_verifications",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/verifications/pending")

        # Must be 200 (list endpoint), not 422 (UUID parse failure)
        assert resp.status_code == 200
