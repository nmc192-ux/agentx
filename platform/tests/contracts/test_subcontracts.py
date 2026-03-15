"""
Tests: Phase 19 — Subcontracting
══════════════════════════════════
Covers:
  subcontract_service.spawn_subcontract()
  POST /contracts/{id}/subcontract  (router)

All DB and service calls are fully mocked.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.models.agent_economy import SubcontractCreate, SubcontractResponse


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(UTC)


def _parent_row(
    contract_id=None,
    contractor_did="did:agentx:contractor",
    status="assigned",
):
    data = {
        "contract_id":    contract_id or uuid4(),
        "contractor_did": contractor_did,
        "status":         status,
    }
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=data.__getitem__)
    row.get = MagicMock(side_effect=data.get)
    return row


def _child_contract(parent_id=None):
    from src.models.contract import ContractResponse
    return ContractResponse(
        contract_id=uuid4(),
        creator_did="did:agentx:contractor",
        creator_id=uuid4(),
        contractor_did=None,
        contractor_id=None,
        title="Subcontract task",
        description="Delegated work",
        contract_type="subcontract",
        status="open",
        budget=100,
        escrowed_budget=100,
        deadline=None,
        payload={"parent_contract_id": str(parent_id or uuid4())},
        created_at=_now(),
    )


def _mock_get_db(row):
    @asynccontextmanager
    async def _ctx():
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        yield conn
    return _ctx


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


def _make_agent_record(did="did:agentx:contractor"):
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    mock_claims = MagicMock(spec=TokenClaims)
    mock_claims.agent_did = did
    row = {
        "agent_did": did,
        "display_name": "Test Contractor",
        "governance_role": "MEMBER",
        "tier": "STANDARD",
        "status": "ACTIVE",
        "trust_score": 0.8,
    }
    return AgentRecord(row=row, claims=mock_claims)


# ── subcontract_service unit tests ────────────────────────────────────────────

class TestSpawnSubcontract:

    @pytest.mark.asyncio
    async def test_happy_path_returns_subcontract_response(self):
        parent_id = uuid4()
        parent_row = _parent_row(contract_id=parent_id, status="assigned")
        child = _child_contract(parent_id)

        with patch("src.services.subcontract_service.get_db", new=_mock_get_db(parent_row)):
            with patch(
                "src.services.subcontract_service.contract_service.create_contract",
                new=AsyncMock(return_value=child),
            ):
                from src.services.subcontract_service import spawn_subcontract

                result = await spawn_subcontract(
                    parent_contract_id=parent_id,
                    caller_did="did:agentx:contractor",
                    data=SubcontractCreate(
                        title="Sub task",
                        description="Delegated work",
                        budget=100,
                    ),
                )

        assert result.parent_contract_id == parent_id

    @pytest.mark.asyncio
    async def test_parent_not_found_raises_value_error(self):
        with patch("src.services.subcontract_service.get_db", new=_mock_get_db(None)):
            from src.services.subcontract_service import spawn_subcontract

            with pytest.raises(ValueError, match="not found"):
                await spawn_subcontract(
                    parent_contract_id=uuid4(),
                    caller_did="did:agentx:contractor",
                    data=SubcontractCreate(
                        title="T", description="D", budget=10,
                    ),
                )

    @pytest.mark.asyncio
    async def test_non_contractor_raises_value_error(self):
        parent_id = uuid4()
        parent_row = _parent_row(
            contract_id=parent_id,
            contractor_did="did:agentx:real_contractor",
            status="assigned",
        )
        with patch("src.services.subcontract_service.get_db", new=_mock_get_db(parent_row)):
            from src.services.subcontract_service import spawn_subcontract

            with pytest.raises(ValueError, match="contractor"):
                await spawn_subcontract(
                    parent_contract_id=parent_id,
                    caller_did="did:agentx:impostor",
                    data=SubcontractCreate(title="T", description="D", budget=10),
                )

    @pytest.mark.asyncio
    async def test_open_parent_raises_value_error(self):
        parent_id = uuid4()
        parent_row = _parent_row(
            contract_id=parent_id,
            contractor_did="did:agentx:contractor",
            status="open",  # not yet assigned
        )
        with patch("src.services.subcontract_service.get_db", new=_mock_get_db(parent_row)):
            from src.services.subcontract_service import spawn_subcontract

            with pytest.raises(ValueError, match="open"):
                await spawn_subcontract(
                    parent_contract_id=parent_id,
                    caller_did="did:agentx:contractor",
                    data=SubcontractCreate(title="T", description="D", budget=10),
                )

    @pytest.mark.asyncio
    async def test_submitted_parent_allowed(self):
        parent_id = uuid4()
        parent_row = _parent_row(
            contract_id=parent_id,
            contractor_did="did:agentx:contractor",
            status="submitted",
        )
        child = _child_contract(parent_id)
        with patch("src.services.subcontract_service.get_db", new=_mock_get_db(parent_row)):
            with patch(
                "src.services.subcontract_service.contract_service.create_contract",
                new=AsyncMock(return_value=child),
            ):
                from src.services.subcontract_service import spawn_subcontract

                result = await spawn_subcontract(
                    parent_contract_id=parent_id,
                    caller_did="did:agentx:contractor",
                    data=SubcontractCreate(title="T", description="D", budget=10),
                )

        assert result.contract_type == "subcontract"

    @pytest.mark.asyncio
    async def test_parent_id_in_child_payload(self):
        parent_id = uuid4()
        parent_row = _parent_row(contract_id=parent_id, status="assigned")
        child = _child_contract(parent_id)

        with patch("src.services.subcontract_service.get_db", new=_mock_get_db(parent_row)):
            with patch(
                "src.services.subcontract_service.contract_service.create_contract",
                new=AsyncMock(return_value=child),
            ) as mock_create:
                from src.services.subcontract_service import spawn_subcontract

                await spawn_subcontract(
                    parent_contract_id=parent_id,
                    caller_did="did:agentx:contractor",
                    data=SubcontractCreate(title="T", description="D", budget=50),
                )

        _, kwargs = mock_create.call_args
        assert str(parent_id) in kwargs["data"].payload["parent_contract_id"]

    @pytest.mark.asyncio
    async def test_extra_payload_merged(self):
        parent_id = uuid4()
        parent_row = _parent_row(contract_id=parent_id, status="assigned")
        child = _child_contract(parent_id)

        with patch("src.services.subcontract_service.get_db", new=_mock_get_db(parent_row)):
            with patch(
                "src.services.subcontract_service.contract_service.create_contract",
                new=AsyncMock(return_value=child),
            ) as mock_create:
                from src.services.subcontract_service import spawn_subcontract

                await spawn_subcontract(
                    parent_contract_id=parent_id,
                    caller_did="did:agentx:contractor",
                    data=SubcontractCreate(
                        title="T", description="D", budget=50,
                        payload={"custom": "val"},
                    ),
                )

        _, kwargs = mock_create.call_args
        assert kwargs["data"].payload.get("custom") == "val"

    @pytest.mark.asyncio
    async def test_child_contract_type_is_subcontract(self):
        parent_id = uuid4()
        parent_row = _parent_row(contract_id=parent_id, status="assigned")
        child = _child_contract(parent_id)

        with patch("src.services.subcontract_service.get_db", new=_mock_get_db(parent_row)):
            with patch(
                "src.services.subcontract_service.contract_service.create_contract",
                new=AsyncMock(return_value=child),
            ) as mock_create:
                from src.services.subcontract_service import spawn_subcontract

                await spawn_subcontract(
                    parent_contract_id=parent_id,
                    caller_did="did:agentx:contractor",
                    data=SubcontractCreate(title="T", description="D", budget=50),
                )

        _, kwargs = mock_create.call_args
        assert kwargs["data"].contract_type == "subcontract"

    @pytest.mark.asyncio
    async def test_completed_parent_raises_value_error(self):
        parent_id = uuid4()
        parent_row = _parent_row(
            contract_id=parent_id,
            contractor_did="did:agentx:contractor",
            status="completed",
        )
        with patch("src.services.subcontract_service.get_db", new=_mock_get_db(parent_row)):
            from src.services.subcontract_service import spawn_subcontract

            with pytest.raises(ValueError):
                await spawn_subcontract(
                    parent_contract_id=parent_id,
                    caller_did="did:agentx:contractor",
                    data=SubcontractCreate(title="T", description="D", budget=10),
                )


# ── Router: POST /contracts/{id}/subcontract ──────────────────────────────────

class TestSubcontractRouter:
    """Uses app.dependency_overrides for auth — same pattern as test_contracts.py."""

    @pytest.fixture(autouse=True)
    def _override_auth(self):
        from src.auth.middleware import get_current_agent
        app.dependency_overrides[get_current_agent] = lambda: _make_agent_record()
        yield
        app.dependency_overrides.clear()

    def _sub_response(self, parent_id):
        return SubcontractResponse(
            contract_id=uuid4(),
            creator_did="did:agentx:contractor",
            creator_id=uuid4(),
            contractor_did=None,
            contractor_id=None,
            title="Sub task",
            description="Delegated work",
            contract_type="subcontract",
            status="open",
            budget=100,
            escrowed_budget=100,
            deadline=None,
            payload={"parent_contract_id": str(parent_id)},
            created_at=_now(),
            parent_contract_id=parent_id,
        )

    @pytest.mark.asyncio
    async def test_post_subcontract_returns_201(self, client):
        parent_id = uuid4()
        with patch(
            "src.routers.agent_economy.subcontract_service.spawn_subcontract",
            new=AsyncMock(return_value=self._sub_response(parent_id)),
        ):
            resp = await client.post(
                f"/contracts/{parent_id}/subcontract",
                json={"title": "Sub task", "description": "Delegated work", "budget": 100},
            )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_subcontract_response_has_parent_id(self, client):
        parent_id = uuid4()
        with patch(
            "src.routers.agent_economy.subcontract_service.spawn_subcontract",
            new=AsyncMock(return_value=self._sub_response(parent_id)),
        ):
            resp = await client.post(
                f"/contracts/{parent_id}/subcontract",
                json={"title": "Sub task", "description": "Delegated work", "budget": 100},
            )
        data = resp.json()
        assert str(parent_id) in data.get("parent_contract_id", "")

    @pytest.mark.asyncio
    async def test_value_error_returns_400(self, client):
        parent_id = uuid4()
        with patch(
            "src.routers.agent_economy.subcontract_service.spawn_subcontract",
            new=AsyncMock(side_effect=ValueError("Only the contractor")),
        ):
            resp = await client.post(
                f"/contracts/{parent_id}/subcontract",
                json={"title": "Sub task", "description": "D", "budget": 100},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_not_found_error_returns_404(self, client):
        parent_id = uuid4()
        with patch(
            "src.routers.agent_economy.subcontract_service.spawn_subcontract",
            new=AsyncMock(side_effect=ValueError("not found")),
        ):
            resp = await client.post(
                f"/contracts/{parent_id}/subcontract",
                json={"title": "Sub task", "description": "D", "budget": 100},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_budget_returns_422(self, client):
        parent_id = uuid4()
        resp = await client.post(
            f"/contracts/{parent_id}/subcontract",
            json={"title": "T", "description": "D"},  # missing budget
        )
        assert resp.status_code == 422
