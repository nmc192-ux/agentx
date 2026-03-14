"""
Tests: Marketplace endpoints in routers/tasks.py
Phase 4 — Agent Task Economy

Covers new endpoints:
  POST   /tasks              — publish marketplace task
  GET    /tasks              — discover open tasks
  POST   /tasks/{id}/bid     — submit bid
  POST   /tasks/{id}/accept  — accept bid / assign task
  POST   /tasks/{id}/result  — submit result

Existing endpoints (regression):
  POST   /tasks/create       — direct assignment (unchanged)
  POST   /tasks/{id}/update  — status update (unchanged)
  GET    /tasks/{agent_did}  — list by agent DID (unchanged)
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


def _now():
    return datetime.now(timezone.utc)


def _uuid_str():
    return str(uuid4())


# ── Helper data builders ───────────────────────────────────────────────────────

def _marketplace_task_response(task_id=None, status="open"):
    from src.models.task import TaskResponse
    tid = task_id or uuid4()
    return TaskResponse(
        task_id=tid,
        creator_agent_id=uuid4(),
        task_type="marketplace.test",
        payload={"key": "value"},
        reward=100,
        status=status,
        created_at=_now(),
    )


def _bid_response(bid_id=None, task_id=None):
    from src.models.task import TaskBidResponse
    return TaskBidResponse(
        bid_id=bid_id or uuid4(),
        task_id=task_id or uuid4(),
        agent_id=uuid4(),
        confidence=0.9,
        bid_price=50,
        created_at=_now(),
    )


def _assignment_response(assignment_id=None, task_id=None):
    from src.models.task import TaskAssignmentResponse
    return TaskAssignmentResponse(
        assignment_id=assignment_id or uuid4(),
        task_id=task_id or uuid4(),
        agent_id=uuid4(),
        status="assigned",
        started_at=_now(),
        completed_at=None,
    )


def _result_response(result_id=None, task_id=None):
    from src.models.task import TaskResultResponse
    return TaskResultResponse(
        result_id=result_id or uuid4(),
        task_id=task_id or uuid4(),
        agent_id=uuid4(),
        result_payload={"score": 99},
        verification_status="pending",
        created_at=_now(),
    )


# ── POST /tasks ────────────────────────────────────────────────────────────────

class TestMarketplaceCreateTask:

    @pytest.mark.asyncio
    async def test_post_tasks_returns_201(self, client):
        task = _marketplace_task_response()
        with patch(
            "src.routers.tasks.task_service.create_task",
            new=AsyncMock(return_value=task),
        ):
            resp = await client.post(
                "/tasks",
                json={
                    "creator_agent_did": "did:agentx:atlas-001",
                    "task_type": "marketplace.test",
                    "payload": {"key": "value"},
                    "reward": 100,
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["task_type"] == "marketplace.test"
        assert data["reward"] == 100
        assert data["status"] == "open"

    @pytest.mark.asyncio
    async def test_post_tasks_404_unknown_agent(self, client):
        with patch(
            "src.routers.tasks.task_service.create_task",
            new=AsyncMock(side_effect=ValueError("Creator agent not found: did:agentx:ghost-001")),
        ):
            resp = await client.post(
                "/tasks",
                json={
                    "creator_agent_did": "did:agentx:ghost-001",
                    "task_type": "marketplace.test",
                    "payload": None,
                    "reward": 0,
                },
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_post_tasks_422_missing_required_field(self, client):
        resp = await client.post("/tasks", json={"reward": 50})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_post_tasks_default_reward_zero(self, client):
        task = _marketplace_task_response()
        with patch(
            "src.routers.tasks.task_service.create_task",
            new=AsyncMock(return_value=task),
        ) as mock_create:
            await client.post(
                "/tasks",
                json={
                    "creator_agent_did": "did:agentx:atlas-001",
                    "task_type": "marketplace.test",
                },
            )
        call_kwargs = mock_create.await_args.kwargs
        assert call_kwargs.get("reward", 0) == 0


# ── GET /tasks ─────────────────────────────────────────────────────────────────

class TestMarketplaceListTasks:

    @pytest.mark.asyncio
    async def test_get_tasks_returns_200_list(self, client):
        tasks = [_marketplace_task_response(), _marketplace_task_response()]
        with patch(
            "src.routers.tasks.task_service.list_tasks",
            new=AsyncMock(return_value=tasks),
        ):
            resp = await client.get("/tasks")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_get_tasks_passes_status_filter(self, client):
        with patch(
            "src.routers.tasks.task_service.list_tasks",
            new=AsyncMock(return_value=[]),
        ) as mock_list:
            await client.get("/tasks?status=assigned")
        mock_list.assert_awaited_once_with(status="assigned", limit=50)

    @pytest.mark.asyncio
    async def test_get_tasks_passes_limit(self, client):
        with patch(
            "src.routers.tasks.task_service.list_tasks",
            new=AsyncMock(return_value=[]),
        ) as mock_list:
            await client.get("/tasks?limit=10")
        mock_list.assert_awaited_once_with(status="open", limit=10)

    @pytest.mark.asyncio
    async def test_get_tasks_empty_returns_empty_list(self, client):
        with patch(
            "src.routers.tasks.task_service.list_tasks",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/tasks")
        assert resp.status_code == 200
        assert resp.json() == []


# ── POST /tasks/{task_id}/bid ──────────────────────────────────────────────────

class TestMarketplaceBidTask:

    @pytest.mark.asyncio
    async def test_bid_returns_201(self, client):
        task_id = uuid4()
        bid = _bid_response(task_id=task_id)
        with patch(
            "src.routers.tasks.task_service.submit_bid",
            new=AsyncMock(return_value=bid),
        ):
            resp = await client.post(
                f"/tasks/{task_id}/bid",
                json={
                    "agent_did": "did:agentx:bidder-001",
                    "confidence": 0.9,
                    "bid_price": 50,
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["confidence"] == 0.9
        assert data["bid_price"] == 50

    @pytest.mark.asyncio
    async def test_bid_422_task_not_open(self, client):
        task_id = uuid4()
        with patch(
            "src.routers.tasks.task_service.submit_bid",
            new=AsyncMock(side_effect=ValueError("Task is not open for bidding")),
        ):
            resp = await client.post(
                f"/tasks/{task_id}/bid",
                json={
                    "agent_did": "did:agentx:bidder-001",
                    "confidence": 0.5,
                    "bid_price": 10,
                },
            )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_bid_422_missing_agent_did(self, client):
        task_id = uuid4()
        resp = await client.post(
            f"/tasks/{task_id}/bid",
            json={"confidence": 0.9},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_bid_confidence_bounds_enforced(self, client):
        task_id = uuid4()
        resp = await client.post(
            f"/tasks/{task_id}/bid",
            json={"agent_did": "did:agentx:bidder-001", "confidence": 1.5, "bid_price": 10},
        )
        assert resp.status_code == 422


# ── POST /tasks/{task_id}/accept ───────────────────────────────────────────────

class TestMarketplaceAcceptTask:

    @pytest.mark.asyncio
    async def test_accept_returns_200(self, client):
        task_id = uuid4()
        bid_id = uuid4()
        assignment = _assignment_response(task_id=task_id)
        with patch(
            "src.routers.tasks.task_service.assign_task",
            new=AsyncMock(return_value=assignment),
        ):
            resp = await client.post(
                f"/tasks/{task_id}/accept",
                params={"bid_id": str(bid_id)},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "assigned"

    @pytest.mark.asyncio
    async def test_accept_422_task_already_assigned(self, client):
        task_id = uuid4()
        bid_id = uuid4()
        with patch(
            "src.routers.tasks.task_service.assign_task",
            new=AsyncMock(side_effect=ValueError("Task cannot be assigned")),
        ):
            resp = await client.post(
                f"/tasks/{task_id}/accept",
                params={"bid_id": str(bid_id)},
            )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_accept_422_missing_bid_id(self, client):
        task_id = uuid4()
        resp = await client.post(f"/tasks/{task_id}/accept")
        assert resp.status_code == 422


# ── POST /tasks/{task_id}/result ───────────────────────────────────────────────

class TestMarketplaceSubmitResult:

    @pytest.mark.asyncio
    async def test_submit_result_returns_201(self, client):
        task_id = uuid4()
        result = _result_response(task_id=task_id)
        with patch(
            "src.routers.tasks.task_service.submit_result",
            new=AsyncMock(return_value=result),
        ):
            resp = await client.post(
                f"/tasks/{task_id}/result",
                json={
                    "agent_did": "did:agentx:exec-001",
                    "result_payload": {"score": 99},
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["verification_status"] == "pending"
        assert data["result_payload"] == {"score": 99}

    @pytest.mark.asyncio
    async def test_submit_result_404_unknown_task(self, client):
        task_id = uuid4()
        with patch(
            "src.routers.tasks.task_service.submit_result",
            new=AsyncMock(side_effect=ValueError("Task not found")),
        ):
            resp = await client.post(
                f"/tasks/{task_id}/result",
                json={"agent_did": "did:agentx:exec-001", "result_payload": {}},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_submit_result_422_missing_agent_did(self, client):
        task_id = uuid4()
        resp = await client.post(
            f"/tasks/{task_id}/result",
            json={"result_payload": {"score": 1}},
        )
        assert resp.status_code == 422


# ── Regression: existing endpoints still work ─────────────────────────────────

class TestExistingEndpointsRegression:

    @pytest.mark.asyncio
    async def test_get_tasks_by_uuid_still_works(self, client):
        """GET /tasks/{uuid} still routes to get_tasks_for_agent handler."""
        task_id = uuid4()
        from src.models.agent_task import TaskResponse as LegacyTaskResponse
        legacy_row = {
            "task_id": task_id,
            "requester_agent_did": "did:agentx:atlas-001",
            "executor_agent_did":  "did:agentx:exec-001",
            "task_type": "security.audit",
            "payload": "{}",
            "status": "COMPLETED",
            "result": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=legacy_row)

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("src.routers.tasks.get_db", return_value=ctx):
            resp = await client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["task_type"] == "security.audit"

    @pytest.mark.asyncio
    async def test_post_tasks_create_still_works(self, client):
        """POST /tasks/create (direct assignment) is unchanged."""
        task_id = uuid4()
        legacy_row = {
            "task_id": task_id,
            "requester_agent_did": "did:agentx:atlas-001",
            "executor_agent_did":  "did:agentx:exec-001",
            "task_type": "security.audit",
            "payload": "{}",
            "status": "PENDING",
            "result": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(side_effect=[
            {"agent_id": uuid4()},  # requester lookup
            {"agent_id": uuid4()},  # executor lookup
            legacy_row,             # insert
        ])

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("src.routers.tasks.transaction", return_value=ctx),
            patch("src.routers.tasks.cache_delete", new=AsyncMock()),
            patch("src.routers.tasks.enqueue_task", new=AsyncMock()),
            patch("src.routers.tasks.emit_event", new=AsyncMock()),
        ):
            resp = await client.post(
                "/tasks/create",
                json={
                    "requester_agent_did": "did:agentx:atlas-001",
                    "executor_agent_did":  "did:agentx:exec-001",
                    "task_type": "security.audit",
                    "payload": {},
                },
            )
        assert resp.status_code == 201
        assert resp.json()["task_type"] == "security.audit"
