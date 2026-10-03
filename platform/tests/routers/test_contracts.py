"""
Tests: src/routers/contracts.py
Phase 10 -- Agent Contract Engine

Covers:
  POST /contracts                       -- create contract (requires auth)
  GET  /contracts                       -- list contracts (public)
  POST /contracts/{id}/bid              -- submit bid (requires auth)
  POST /contracts/{id}/assign           -- assign contract (requires auth)
  POST /contracts/{id}/result           -- submit result (requires auth)
  POST /contracts/{id}/complete         -- accept result, pay contractor (requires auth)
  POST /contracts/{id}/cancel           -- cancel open contract, refund (requires auth)
  POST /contracts/{id}/dispute          -- open dispute (requires auth)

Sprint 9, S9-6b: every write needs a JWT and acts as the JWT caller; the
service's PermissionError → 403 and ContractConflictError → 409.
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

def _contract(status="open", budget=1000):
    from src.models.contract import ContractResponse
    return ContractResponse(
        contract_id=uuid4(),
        creator_did="did:agentx:creator",
        creator_id=uuid4(),
        contractor_did=None,
        contractor_id=None,
        title="Test Contract",
        description="Description",
        contract_type="general",
        status=status,
        budget=budget,
        escrowed_budget=budget,
        deadline=None,
        payload=None,
        created_at=_now(),
    )


def _bid():
    from src.models.contract import ContractBidResponse
    return ContractBidResponse(
        bid_id=uuid4(),
        contract_id=uuid4(),
        bidder_did="did:agentx:bidder",
        bid_amount=500,
        proposal="I can do this",
        status="pending",
        created_at=_now(),
    )


def _result():
    from src.models.contract import ContractResultResponse
    return ContractResultResponse(
        result_id=uuid4(),
        contract_id=uuid4(),
        contractor_did="did:agentx:contractor",
        result_payload={"output": "done"},
        submitted_at=_now(),
    )


def _dispute():
    from src.models.contract import ContractDisputeResponse
    return ContractDisputeResponse(
        dispute_id=uuid4(),
        contract_id=uuid4(),
        initiator_did="did:agentx:initiator",
        reason="Work not delivered",
        status="open",
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


# -- POST /contracts ----------------------------------------------------------

class TestCreateContract:

    @pytest.mark.asyncio
    async def test_returns_201_on_success(self, client):
        from src.auth.middleware import get_current_agent
        c = _contract()

        with patch(
            "src.routers.contracts.contract_service.create_contract",
            new=AsyncMock(return_value=c),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/contracts",
                    json={"title": "Test", "description": "Desc", "budget": 1000},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Test Contract"
        assert data["status"] == "open"

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        resp = await client.post(
            "/contracts",
            json={"title": "T", "description": "D", "budget": 100},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_returns_400_on_service_error(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.contracts.contract_service.create_contract",
            new=AsyncMock(side_effect=ValueError("insufficient funds")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/contracts",
                    json={"title": "T", "description": "D", "budget": 100},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400


# -- GET /contracts -----------------------------------------------------------

class TestListContracts:

    @pytest.mark.asyncio
    async def test_returns_open_contracts(self, client):
        contracts = [_contract(), _contract()]

        with patch(
            "src.routers.contracts.contract_service.list_contracts",
            new=AsyncMock(return_value=contracts),
        ):
            resp = await client.get("/contracts")

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_no_auth_required(self, client):
        with patch(
            "src.routers.contracts.contract_service.list_contracts",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/contracts")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_status_all_passes_none(self, client):
        """?status=all should call list_contracts(status=None)."""
        with patch(
            "src.routers.contracts.contract_service.list_contracts",
            new=AsyncMock(return_value=[]),
        ) as mock_svc:
            resp = await client.get("/contracts?status=all")

        assert resp.status_code == 200
        mock_svc.assert_awaited_once_with(status=None, limit=50, offset=0)

    @pytest.mark.asyncio
    async def test_page_size_is_capped(self, client):
        with patch(
            "src.routers.contracts.contract_service.list_contracts",
            new=AsyncMock(return_value=[]),
        ) as mock_svc:
            too_big = await client.get("/contracts?limit=100000")
            ok = await client.get("/contracts?limit=200&offset=40")

        assert too_big.status_code == 422
        assert ok.status_code == 200
        mock_svc.assert_awaited_once_with(status="open", limit=200, offset=40)


# -- POST /contracts/{id}/bid -------------------------------------------------

class TestSubmitBid:

    @pytest.mark.asyncio
    async def test_returns_201_on_success(self, client):
        from src.auth.middleware import get_current_agent
        contract_id = uuid4()
        b = _bid()

        with patch(
            "src.routers.contracts.contract_service.submit_bid",
            new=AsyncMock(return_value=b),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    f"/contracts/{contract_id}/bid",
                    json={"bid_amount": 500, "proposal": "I can do it"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        assert resp.json()["bid_amount"] == 500

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        resp = await client.post(
            f"/contracts/{uuid4()}/bid",
            json={"bid_amount": 100},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_contract(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.contracts.contract_service.submit_bid",
            new=AsyncMock(side_effect=ValueError("Contract not found")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    f"/contracts/{uuid4()}/bid",
                    json={"bid_amount": 100},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 404


# -- POST /contracts/{id}/assign ----------------------------------------------

class TestAssignContract:

    @pytest.mark.asyncio
    async def test_returns_200_on_success(self, client):
        from src.auth.middleware import get_current_agent
        contract_id = uuid4()
        bid_id      = uuid4()
        c = _contract(status="assigned")

        with patch(
            "src.routers.contracts.contract_service.assign_contract",
            new=AsyncMock(return_value=c),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    f"/contracts/{contract_id}/assign",
                    json={"bid_id": str(bid_id)},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 200
        assert resp.json()["status"] == "assigned"

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        resp = await client.post(
            f"/contracts/{uuid4()}/assign",
            json={"bid_id": str(uuid4())},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_returns_403_if_not_creator(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.contracts.contract_service.assign_contract",
            new=AsyncMock(side_effect=PermissionError("Only the contract creator")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    f"/contracts/{uuid4()}/assign",
                    json={"bid_id": str(uuid4())},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 403


# -- POST /contracts/{id}/result ----------------------------------------------

class TestSubmitResult:

    @pytest.mark.asyncio
    async def test_returns_201_on_success(self, client):
        from src.auth.middleware import get_current_agent
        contract_id = uuid4()
        r = _result()

        with patch(
            "src.routers.contracts.contract_service.submit_result",
            new=AsyncMock(return_value=r),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    f"/contracts/{contract_id}/result",
                    json={"result_payload": {"output": "done"}},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        assert resp.json()["contractor_did"] == "did:agentx:contractor"

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        resp = await client.post(
            f"/contracts/{uuid4()}/result",
            json={"result_payload": {}},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_returns_403_if_not_contractor(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.contracts.contract_service.submit_result",
            new=AsyncMock(side_effect=PermissionError("Only the assigned contractor")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    f"/contracts/{uuid4()}/result",
                    json={},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 403


# -- POST /contracts/{id}/dispute ---------------------------------------------

class TestOpenDispute:

    @pytest.mark.asyncio
    async def test_returns_201_on_success(self, client):
        from src.auth.middleware import get_current_agent
        contract_id = uuid4()
        d = _dispute()

        with patch(
            "src.routers.contracts.contract_service.open_dispute",
            new=AsyncMock(return_value=d),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    f"/contracts/{contract_id}/dispute",
                    json={"reason": "Work not delivered"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        assert resp.json()["status"] == "open"
        assert resp.json()["reason"] == "Work not delivered"

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        resp = await client.post(
            f"/contracts/{uuid4()}/dispute",
            json={"reason": "reason"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_contract(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.contracts.contract_service.open_dispute",
            new=AsyncMock(side_effect=ValueError("Contract not found")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    f"/contracts/{uuid4()}/dispute",
                    json={"reason": "reason"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 404


# -- POST /contracts/{id}/complete and /cancel --------------------------------

class TestCompleteAndCancel:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action,final", [("complete", "completed"), ("cancel", "cancelled")])
    async def test_returns_200_and_acts_as_the_jwt_caller(self, client, action, final):
        from src.auth.middleware import get_current_agent
        contract_id = uuid4()

        with patch(
            f"src.routers.contracts.contract_service.{action}_contract",
            new=AsyncMock(return_value=_contract(status=final)),
        ) as mock_svc:
            app.dependency_overrides[get_current_agent] = lambda: _make_agent("did:agentx:me-001")
            try:
                # A body naming someone else changes nothing: there is no body.
                resp = await client.post(
                    f"/contracts/{contract_id}/{action}",
                    json={"caller_did": "did:agentx:victim-001"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 200
        assert resp.json()["status"] == final
        mock_svc.assert_awaited_once_with(contract_id=contract_id, caller_did="did:agentx:me-001")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["complete", "cancel"])
    async def test_requires_auth(self, client, action):
        with patch(
            f"src.routers.contracts.contract_service.{action}_contract", new=AsyncMock(),
        ) as mock_svc:
            resp = await client.post(f"/contracts/{uuid4()}/{action}")

        assert resp.status_code == 401
        mock_svc.assert_not_awaited()


# -- Error mapping, every write endpoint ---------------------------------------

_WRITES = [
    # (path suffix, service function, request body)
    ("bid",      "submit_bid",        {"bid_amount": 10}),
    ("assign",   "assign_contract",   {"bid_id": str(uuid4())}),
    ("result",   "submit_result",     {"result_payload": {}}),
    ("complete", "complete_contract", None),
    ("cancel",   "cancel_contract",   None),
    ("dispute",  "open_dispute",      {"reason": "late"}),
]


def _errors():
    from src.services.contract_service import ContractConflictError
    return [
        (PermissionError("Only the contract creator can do that"), 403),
        (ContractConflictError("Contract is not in submitted state (status=completed)"), 409),
        (ValueError("Contract not found: x"), 404),
        (ValueError("Something else is wrong"), 400),
    ]


class TestErrorMapping:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("suffix,func,body", _WRITES)
    async def test_service_errors_map_to_http(self, client, suffix, func, body):
        from src.auth.middleware import get_current_agent

        app.dependency_overrides[get_current_agent] = lambda: _make_agent()
        try:
            for error, expected in _errors():
                with patch(
                    f"src.routers.contracts.contract_service.{func}",
                    new=AsyncMock(side_effect=error),
                ):
                    resp = await client.post(f"/contracts/{uuid4()}/{suffix}", json=body)
                assert resp.status_code == expected, (suffix, error, resp.text)
        finally:
            app.dependency_overrides.pop(get_current_agent, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("suffix,func,body", _WRITES)
    async def test_every_write_needs_a_login(self, client, suffix, func, body):
        with patch(
            f"src.routers.contracts.contract_service.{func}", new=AsyncMock(),
        ) as mock_svc:
            resp = await client.post(f"/contracts/{uuid4()}/{suffix}", json=body)

        assert resp.status_code == 401
        mock_svc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unfunded_contract_is_a_400_not_a_404(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.contracts.contract_service.create_contract",
            new=AsyncMock(side_effect=ValueError(
                "Insufficient funds: the creator's wallet cannot cover a budget of 500 tokens"
            )),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/contracts", json={"title": "T", "description": "D", "budget": 500},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400
        assert "Insufficient funds" in resp.json()["detail"]
