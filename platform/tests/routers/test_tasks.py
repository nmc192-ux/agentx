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
  POST   /tasks/create       — direct assignment
  POST   /tasks/{id}/update  — status update
  GET    /tasks/{agent_did}  — list by agent DID (unchanged, public read)

Sprint 9 (S9-6a) — every POST requires a JWT and acts as the JWT caller:
  no token → 401 and the service is never called; a body DID naming another
  agent → 403; accept = creator only; result = executor only, 409 on repeat;
  update = executor (or FOUNDER) only, forward status changes only.
The same rules are proven end to end against real Postgres in
tests/integration/test_task_escrow_db.py (run with --db).
"""
from __future__ import annotations

from contextlib import contextmanager
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


# ── Mock auth ─────────────────────────────────────────────────────────────────

CALLER_DID = "did:agentx:atlas-001"
OTHER_DID = "did:agentx:victim-001"


def _make_agent(did=CALLER_DID, role="MEMBER"):
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    mock_claims = MagicMock(spec=TokenClaims)
    mock_claims.agent_did = did
    row = {
        "agent_did":       did,
        "display_name":    "Atlas",
        "governance_role": role,
        "tier":            "STANDARD",
        "status":          "ACTIVE",
        "trust_score":     0.9,
    }
    return AgentRecord(row=row, claims=mock_claims)


@contextmanager
def _as(caller):
    """Authenticate the request as *caller*."""
    from src.auth.middleware import get_current_agent
    app.dependency_overrides[get_current_agent] = lambda: caller
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_agent, None)


@pytest.fixture
def authed():
    """Most tests act as CALLER_DID."""
    with _as(_make_agent()):
        yield


def _conn_ctx(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _legacy_row(task_id=None, status="PENDING", requester=CALLER_DID, executor="did:agentx:exec-001"):
    return {
        "task_id": task_id or uuid4(),
        "requester_agent_did": requester,
        "executor_agent_did":  executor,
        "task_type": "security.audit",
        "payload": "{}",
        "status": status,
        "result": None,
        "created_at": _now(),
        "updated_at": _now(),
    }


# ── No token → 401, nothing happens ───────────────────────────────────────────

class TestEveryWriteRequiresLogin:
    """S9-6a: before this, no /tasks endpoint authenticated at all."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,body,service_fn", [
        ("/tasks",
         {"creator_agent_did": OTHER_DID, "task_type": "x", "reward": 500},
         "src.routers.tasks.task_service.create_task"),
        (f"/tasks/{uuid4()}/bid",
         {"agent_did": OTHER_DID, "confidence": 0.9, "bid_price": 1},
         "src.routers.tasks.task_service.submit_bid"),
        (f"/tasks/{uuid4()}/accept?bid_id={uuid4()}",
         None,
         "src.routers.tasks.task_service.assign_task"),
        (f"/tasks/{uuid4()}/result",
         {"agent_did": OTHER_DID, "result_payload": {}},
         "src.routers.tasks.task_service.submit_result"),
        (f"/tasks/{uuid4()}/cancel",
         None,
         "src.routers.tasks.task_service.cancel_task"),
        ("/tasks/route",
         {"requester_agent_did": OTHER_DID, "task_type": "x"},
         "src.routers.tasks.create_routed_task"),
    ])
    async def test_unauthenticated_returns_401_and_service_not_called(
        self, client, path, body, service_fn,
    ):
        service = AsyncMock()
        with patch(service_fn, new=service):
            resp = await client.post(path, json=body)
        assert resp.status_code == 401
        service.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,body", [
        ("/tasks/create",
         {"requester_agent_did": OTHER_DID, "executor_agent_did": "did:agentx:exec-001",
          "task_type": "x"}),
        (f"/tasks/{uuid4()}/update", {"status": "COMPLETED"}),
    ])
    async def test_unauthenticated_direct_task_writes_return_401_without_touching_db(
        self, client, path, body,
    ):
        tx = MagicMock()
        with patch("src.routers.tasks.transaction", new=tx):
            resp = await client.post(path, json=body)
        assert resp.status_code == 401
        tx.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, client):
        create = AsyncMock()
        with patch("src.routers.tasks.task_service.create_task", new=create):
            resp = await client.post(
                "/tasks",
                json={"task_type": "x", "reward": 500},
                headers={"Authorization": "Bearer not-a-real-token"},
            )
        assert resp.status_code == 401
        create.assert_not_awaited()


# ── Body identity naming someone else → 403 ───────────────────────────────────

class TestBodyIdentityMustBeTheCaller:
    """S9-6a: the regression guard for 'spend / act as another agent'."""

    @pytest.mark.asyncio
    async def test_create_marketplace_task_as_another_agent_403(self, client, authed):
        create = AsyncMock()
        with patch("src.routers.tasks.task_service.create_task", new=create):
            resp = await client.post(
                "/tasks",
                json={"creator_agent_did": OTHER_DID, "task_type": "x", "reward": 500},
            )
        assert resp.status_code == 403
        create.assert_not_awaited()  # the victim's wallet is never escrowed

    @pytest.mark.asyncio
    async def test_bid_as_another_agent_403(self, client, authed):
        bid = AsyncMock()
        with patch("src.routers.tasks.task_service.submit_bid", new=bid):
            resp = await client.post(
                f"/tasks/{uuid4()}/bid",
                json={"agent_did": OTHER_DID, "confidence": 0.9, "bid_price": 1},
            )
        assert resp.status_code == 403
        bid.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_submit_result_as_another_agent_403(self, client, authed):
        submit = AsyncMock()
        with patch("src.routers.tasks.task_service.submit_result", new=submit):
            resp = await client.post(
                f"/tasks/{uuid4()}/result",
                json={"agent_did": OTHER_DID, "result_payload": {}},
            )
        assert resp.status_code == 403
        submit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_direct_task_as_another_requester_403(self, client, authed):
        tx = MagicMock()
        with patch("src.routers.tasks.transaction", new=tx):
            resp = await client.post(
                "/tasks/create",
                json={"requester_agent_did": OTHER_DID,
                      "executor_agent_did": "did:agentx:exec-001", "task_type": "x"},
            )
        assert resp.status_code == 403
        tx.assert_not_called()

    @pytest.mark.asyncio
    async def test_route_task_as_another_requester_403(self, client, authed):
        route = AsyncMock()
        with patch("src.routers.tasks.create_routed_task", new=route):
            resp = await client.post(
                "/tasks/route",
                json={"requester_agent_did": OTHER_DID, "task_type": "x"},
            )
        assert resp.status_code == 403
        route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_founder_gets_no_exemption_for_body_identity(self, client):
        """Even a FOUNDER cannot spend another agent's wallet through /tasks."""
        create = AsyncMock()
        with (
            _as(_make_agent(role="FOUNDER")),
            patch("src.routers.tasks.task_service.create_task", new=create),
        ):
            resp = await client.post(
                "/tasks",
                json={"creator_agent_did": OTHER_DID, "task_type": "x", "reward": 500},
            )
        assert resp.status_code == 403
        create.assert_not_awaited()


# ── POST /tasks ────────────────────────────────────────────────────────────────

class TestMarketplaceCreateTask:

    @pytest.mark.asyncio
    async def test_post_tasks_returns_201(self, client, authed):
        task = _marketplace_task_response()
        with patch(
            "src.routers.tasks.task_service.create_task",
            new=AsyncMock(return_value=task),
        ) as mock_create:
            resp = await client.post(
                "/tasks",
                json={
                    "creator_agent_did": CALLER_DID,
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
        assert mock_create.await_args.kwargs["creator_agent_did"] == CALLER_DID

    @pytest.mark.asyncio
    async def test_post_tasks_creator_defaults_to_caller(self, client, authed):
        """The body DID is optional: the creator is the JWT caller."""
        task = _marketplace_task_response()
        with patch(
            "src.routers.tasks.task_service.create_task",
            new=AsyncMock(return_value=task),
        ) as mock_create:
            resp = await client.post(
                "/tasks", json={"task_type": "marketplace.test", "reward": 100},
            )
        assert resp.status_code == 201
        assert mock_create.await_args.kwargs["creator_agent_did"] == CALLER_DID

    @pytest.mark.asyncio
    async def test_post_tasks_404_unknown_agent(self, client, authed):
        with patch(
            "src.routers.tasks.task_service.create_task",
            new=AsyncMock(side_effect=ValueError("Creator agent not found: did:agentx:ghost-001")),
        ):
            resp = await client.post(
                "/tasks",
                json={"task_type": "marketplace.test", "payload": None, "reward": 0},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_post_tasks_400_reward_the_wallet_cannot_cover(self, client, authed):
        """S9-7b: an unfunded reward is refused, not created with nothing behind it."""
        from src.services.task_service import InsufficientFundsError
        with patch(
            "src.routers.tasks.task_service.create_task",
            new=AsyncMock(side_effect=InsufficientFundsError(
                "Insufficient funds: agent x cannot escrow 100 tokens")),
        ):
            resp = await client.post("/tasks", json={"task_type": "x", "reward": 100})
        assert resp.status_code == 400
        assert "Insufficient funds" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_post_tasks_422_reward_beyond_the_column(self, client, authed):
        create = AsyncMock()
        with patch("src.routers.tasks.task_service.create_task", new=create):
            resp = await client.post("/tasks", json={"task_type": "x", "reward": 2**31})
        assert resp.status_code == 422
        create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_post_tasks_422_missing_required_field(self, client, authed):
        resp = await client.post("/tasks", json={"reward": 50})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_post_tasks_422_negative_reward(self, client, authed):
        create = AsyncMock()
        with patch("src.routers.tasks.task_service.create_task", new=create):
            resp = await client.post("/tasks", json={"task_type": "x", "reward": -5})
        assert resp.status_code == 422
        create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_post_tasks_default_reward_zero(self, client, authed):
        task = _marketplace_task_response()
        with patch(
            "src.routers.tasks.task_service.create_task",
            new=AsyncMock(return_value=task),
        ) as mock_create:
            await client.post(
                "/tasks",
                json={"creator_agent_did": CALLER_DID, "task_type": "marketplace.test"},
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
    async def test_bid_returns_201(self, client, authed):
        task_id = uuid4()
        bid = _bid_response(task_id=task_id)
        with patch(
            "src.routers.tasks.task_service.submit_bid",
            new=AsyncMock(return_value=bid),
        ) as mock_bid:
            resp = await client.post(
                f"/tasks/{task_id}/bid",
                json={"agent_did": CALLER_DID, "confidence": 0.9, "bid_price": 50},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["confidence"] == 0.9
        assert data["bid_price"] == 50
        assert mock_bid.await_args.kwargs["agent_did"] == CALLER_DID

    @pytest.mark.asyncio
    async def test_bid_bidder_defaults_to_caller(self, client, authed):
        task_id = uuid4()
        with patch(
            "src.routers.tasks.task_service.submit_bid",
            new=AsyncMock(return_value=_bid_response(task_id=task_id)),
        ) as mock_bid:
            resp = await client.post(f"/tasks/{task_id}/bid", json={"confidence": 0.9})
        assert resp.status_code == 201
        assert mock_bid.await_args.kwargs["agent_did"] == CALLER_DID

    @pytest.mark.asyncio
    async def test_bid_on_own_task_403(self, client, authed):
        with patch(
            "src.routers.tasks.task_service.submit_bid",
            new=AsyncMock(side_effect=PermissionError(
                "The task creator cannot bid on their own task")),
        ):
            resp = await client.post(f"/tasks/{uuid4()}/bid", json={"confidence": 0.9})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_bid_422_task_not_open(self, client, authed):
        task_id = uuid4()
        with patch(
            "src.routers.tasks.task_service.submit_bid",
            new=AsyncMock(side_effect=ValueError("Task is not open for bidding")),
        ):
            resp = await client.post(
                f"/tasks/{task_id}/bid",
                json={"agent_did": CALLER_DID, "confidence": 0.5, "bid_price": 10},
            )
        assert resp.status_code == 422
        # runners/sdk_agent_runner.py matches on this wording
        assert "not open" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_bid_confidence_bounds_enforced(self, client, authed):
        task_id = uuid4()
        resp = await client.post(
            f"/tasks/{task_id}/bid",
            json={"agent_did": CALLER_DID, "confidence": 1.5, "bid_price": 10},
        )
        assert resp.status_code == 422


# ── POST /tasks/{task_id}/accept ───────────────────────────────────────────────

class TestMarketplaceAcceptTask:

    @pytest.mark.asyncio
    async def test_accept_returns_200_and_passes_the_caller(self, client, authed):
        task_id = uuid4()
        bid_id = uuid4()
        assignment = _assignment_response(task_id=task_id)
        with patch(
            "src.routers.tasks.task_service.assign_task",
            new=AsyncMock(return_value=assignment),
        ) as mock_assign:
            resp = await client.post(
                f"/tasks/{task_id}/accept",
                params={"bid_id": str(bid_id)},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "assigned"
        mock_assign.assert_awaited_once_with(
            task_id=task_id, bid_id=bid_id, caller_did=CALLER_DID,
        )

    @pytest.mark.asyncio
    async def test_accept_by_non_creator_403(self, client, authed):
        with patch(
            "src.routers.tasks.task_service.assign_task",
            new=AsyncMock(side_effect=PermissionError("Only the task creator can accept a bid")),
        ):
            resp = await client.post(
                f"/tasks/{uuid4()}/accept", params={"bid_id": str(uuid4())},
            )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_accept_422_task_already_assigned(self, client, authed):
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
    async def test_accept_422_missing_bid_id(self, client, authed):
        task_id = uuid4()
        resp = await client.post(f"/tasks/{task_id}/accept")
        assert resp.status_code == 422


# ── POST /tasks/{task_id}/result ───────────────────────────────────────────────

class TestMarketplaceSubmitResult:

    @pytest.mark.asyncio
    async def test_submit_result_returns_201(self, client, authed):
        task_id = uuid4()
        result = _result_response(task_id=task_id)
        with patch(
            "src.routers.tasks.task_service.submit_result",
            new=AsyncMock(return_value=result),
        ) as mock_submit:
            resp = await client.post(
                f"/tasks/{task_id}/result",
                json={"agent_did": CALLER_DID, "result_payload": {"score": 99}},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["verification_status"] == "pending"
        assert data["result_payload"] == {"score": 99}
        assert mock_submit.await_args.kwargs["agent_did"] == CALLER_DID

    @pytest.mark.asyncio
    async def test_submit_result_executor_defaults_to_caller(self, client, authed):
        task_id = uuid4()
        with patch(
            "src.routers.tasks.task_service.submit_result",
            new=AsyncMock(return_value=_result_response(task_id=task_id)),
        ) as mock_submit:
            resp = await client.post(
                f"/tasks/{task_id}/result", json={"result_payload": {"score": 1}},
            )
        assert resp.status_code == 201
        assert mock_submit.await_args.kwargs["agent_did"] == CALLER_DID

    @pytest.mark.asyncio
    async def test_submit_result_by_non_executor_403(self, client, authed):
        with patch(
            "src.routers.tasks.task_service.submit_result",
            new=AsyncMock(side_effect=PermissionError(
                "Only the assigned executor can submit a result")),
        ):
            resp = await client.post(f"/tasks/{uuid4()}/result", json={"result_payload": {}})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_submit_result_twice_409(self, client, authed):
        from src.services.task_service import TaskConflictError
        with patch(
            "src.routers.tasks.task_service.submit_result",
            new=AsyncMock(side_effect=TaskConflictError(
                "Task is not awaiting a result (status=COMPLETED)")),
        ):
            resp = await client.post(f"/tasks/{uuid4()}/result", json={"result_payload": {}})
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_submit_result_404_unknown_task(self, client, authed):
        task_id = uuid4()
        with patch(
            "src.routers.tasks.task_service.submit_result",
            new=AsyncMock(side_effect=ValueError("Task not found")),
        ):
            resp = await client.post(
                f"/tasks/{task_id}/result",
                json={"agent_did": CALLER_DID, "result_payload": {}},
            )
        assert resp.status_code == 404


# ── POST /tasks/{task_id}/cancel (S9-7b) ───────────────────────────────────────

class TestMarketplaceCancelTask:

    @pytest.mark.asyncio
    async def test_cancel_returns_200_and_passes_the_caller(self, client, authed):
        task_id = uuid4()
        from src.models.task import TaskResponse as MarketplaceTaskResponse
        cancelled = MarketplaceTaskResponse(
            task_id=task_id, creator_agent_id=uuid4(), task_type="marketplace.test",
            payload={}, reward=100, status="cancelled",
            created_at=datetime.now(timezone.utc),
        )
        mock_cancel = AsyncMock(return_value=cancelled)
        with patch("src.routers.tasks.task_service.cancel_task", new=mock_cancel):
            resp = await client.post(f"/tasks/{task_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
        # The caller comes from the token; the route takes no body at all.
        mock_cancel.assert_awaited_once_with(task_id=task_id, caller_did=CALLER_DID)

    @pytest.mark.asyncio
    async def test_cancel_by_non_creator_403(self, client, authed):
        with patch(
            "src.routers.tasks.task_service.cancel_task",
            new=AsyncMock(side_effect=PermissionError("Only the task creator can cancel it")),
        ):
            resp = await client.post(f"/tasks/{uuid4()}/cancel")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_cancel_a_task_that_is_not_open_409(self, client, authed):
        from src.services.task_service import TaskConflictError
        with patch(
            "src.routers.tasks.task_service.cancel_task",
            new=AsyncMock(side_effect=TaskConflictError(
                "Only an open task can be cancelled (status=assigned)")),
        ):
            resp = await client.post(f"/tasks/{uuid4()}/cancel")
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_404_unknown_task(self, client, authed):
        with patch(
            "src.routers.tasks.task_service.cancel_task",
            new=AsyncMock(side_effect=ValueError("Task not found")),
        ):
            resp = await client.post(f"/tasks/{uuid4()}/cancel")
        assert resp.status_code == 404


# ── POST /tasks/{task_id}/update ───────────────────────────────────────────────

class TestUpdateTask:
    """Executor-only, forward-only status changes on direct tasks (S9-6a)."""

    def _patches(self, conn):
        return (
            patch("src.routers.tasks.transaction", return_value=_conn_ctx(conn)),
            patch("src.routers.tasks.cache_delete", new=AsyncMock()),
            patch("src.routers.tasks.emit_event", new=AsyncMock()),
            patch("src.routers.tasks.record_task_completed", new=AsyncMock()),
            patch("src.routers.tasks.record_task_failed", new=AsyncMock()),
            patch("src.routers.tasks.update_workflow_for_task", new=AsyncMock()),
        )

    async def _update(self, client, conn, body, caller):
        """Returns (response, emit mock, record mock). The record mock stands
        for both reputation calls: `.completed` and `.failed` are the two
        functions, and its own await count is the two together."""
        tx, cache, emit, completed, failed, workflow = self._patches(conn)
        with (
            _as(caller), tx, cache, emit as mock_emit,
            completed as mock_completed, failed as mock_failed, workflow,
        ):
            resp = await client.post(f"/tasks/{uuid4()}/update", json=body)
        record = MagicMock(completed=mock_completed, failed=mock_failed)
        record.assert_not_awaited = lambda: (
            mock_completed.assert_not_awaited(), mock_failed.assert_not_awaited(),
        )
        return resp, mock_emit, record

    def _conn(self, existing_status, executor, updated_status=None, requester="did:agentx:req-001"):
        conn = AsyncMock()
        rows = [{"status": existing_status, "executor_agent_did": executor}]
        if updated_status is not None:
            rows.append(_legacy_row(status=updated_status, requester=requester, executor=executor))
        conn.fetchrow = AsyncMock(side_effect=rows)
        return conn

    @pytest.mark.asyncio
    async def test_executor_completes_task(self, client):
        conn = self._conn("IN_PROGRESS", CALLER_DID, updated_status="COMPLETED")
        resp, emit, record = await self._update(
            client, conn, {"status": "COMPLETED", "result": {"ok": True}}, _make_agent(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "COMPLETED"
        assert "FOR UPDATE" in conn.fetchrow.await_args_list[0].args[0]
        # One report; whether it counts is the reputation service's decision.
        record.completed.assert_awaited_once()
        record.failed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_executor_403_and_nothing_written(self, client):
        conn = self._conn("PENDING", "did:agentx:exec-001")
        resp, emit, record = await self._update(
            client, conn, {"status": "COMPLETED"}, _make_agent(),
        )
        assert resp.status_code == 403
        assert conn.fetchrow.await_count == 1  # the lookup only, no UPDATE
        emit.assert_not_awaited()
        record.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_requester_is_not_enough_403(self, client):
        """The requester cannot mark the executor's task FAILED (a trust penalty)."""
        conn = self._conn("PENDING", "did:agentx:exec-001")
        resp, _, record = await self._update(
            client, conn, {"status": "FAILED"}, _make_agent(),
        )
        assert resp.status_code == 403
        record.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_founder_may_update_for_the_system_worker(self, client):
        conn = self._conn("PENDING", "did:agentx:exec-001", updated_status="COMPLETED")
        resp, _, _ = await self._update(
            client, conn, {"status": "COMPLETED"}, _make_agent(role="FOUNDER"),
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.parametrize("existing,requested", [
        ("COMPLETED", "PENDING"),      # re-open → complete again → farm trust events
        ("COMPLETED", "COMPLETED"),
        ("COMPLETED", "FAILED"),
        ("FAILED", "COMPLETED"),
        ("IN_PROGRESS", "PENDING"),
        ("open", "COMPLETED"),         # marketplace: must go through /result
        ("assigned", "COMPLETED"),
        ("assigned", "FAILED"),
    ])
    async def test_illegal_status_change_409(self, client, existing, requested):
        conn = self._conn(existing, CALLER_DID)
        resp, emit, record = await self._update(
            client, conn, {"status": requested}, _make_agent(),
        )
        assert resp.status_code == 409
        assert conn.fetchrow.await_count == 1  # no UPDATE
        emit.assert_not_awaited()
        record.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_result_cannot_be_rewritten_after_completion(self, client):
        conn = self._conn("COMPLETED", CALLER_DID)
        resp, _, _ = await self._update(
            client, conn, {"result": {"rewritten": True}}, _make_agent(),
        )
        assert resp.status_code == 409
        assert conn.fetchrow.await_count == 1

    @pytest.mark.asyncio
    async def test_failure_is_reported_with_who_marked_it(self, client):
        """The reputation service penalises only a failure the executor
        reported, so the route must say who the caller was — here a FOUNDER."""
        founder = _make_agent(role="FOUNDER")
        conn = self._conn("PENDING", "did:agentx:exec-001", updated_status="FAILED")
        resp, _, record = await self._update(client, conn, {"status": "FAILED"}, founder)
        assert resp.status_code == 200
        record.completed.assert_not_awaited()
        record.failed.assert_awaited_once()
        assert record.failed.await_args.kwargs == {"reported_by_did": founder.did}

    @pytest.mark.asyncio
    async def test_unknown_task_404(self, client):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        resp, _, _ = await self._update(client, conn, {"status": "COMPLETED"}, _make_agent())
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_status_422(self, client):
        conn = AsyncMock()
        resp, _, _ = await self._update(client, conn, {"status": "open"}, _make_agent())
        assert resp.status_code == 422


# ── Regression: existing endpoints still work ─────────────────────────────────

class TestExistingEndpointsRegression:

    @pytest.mark.asyncio
    async def test_get_tasks_by_uuid_still_works(self, client):
        """GET /tasks/{uuid} still routes to get_tasks_for_agent handler."""
        task_id = uuid4()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=_legacy_row(task_id, status="COMPLETED"))

        with patch("src.routers.tasks.get_db", return_value=_conn_ctx(mock_conn)):
            resp = await client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["task_type"] == "security.audit"

    @pytest.mark.asyncio
    async def test_get_open_marketplace_task_has_no_executor(self, client):
        """An open marketplace task has executor_agent_did NULL; GET must not 500."""
        task_id = uuid4()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(
            return_value=_legacy_row(task_id, status="open", executor=None)
        )

        with patch("src.routers.tasks.get_db", return_value=_conn_ctx(mock_conn)):
            resp = await client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["executor_agent_did"] is None

    @pytest.mark.asyncio
    async def test_post_tasks_create_uses_the_caller_as_requester(self, client, authed):
        """POST /tasks/create (direct assignment): requester = JWT caller."""
        task_id = uuid4()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(side_effect=[
            {"agent_id": uuid4()},  # requester lookup
            {"agent_id": uuid4()},  # executor lookup
            _legacy_row(task_id),   # insert
        ])

        with (
            patch("src.routers.tasks.transaction", return_value=_conn_ctx(mock_conn)),
            patch("src.routers.tasks.cache_delete", new=AsyncMock()),
            patch("src.routers.tasks.enqueue_task", new=AsyncMock()),
            patch("src.routers.tasks.emit_event", new=AsyncMock()),
        ):
            resp = await client.post(
                "/tasks/create",
                json={
                    "executor_agent_did":  "did:agentx:exec-001",
                    "task_type": "security.audit",
                    "payload": {},
                },
            )
        assert resp.status_code == 201
        assert resp.json()["task_type"] == "security.audit"
        # requester lookup and the INSERT both use the JWT caller's DID
        assert mock_conn.fetchrow.await_args_list[0].args[1] == CALLER_DID
        assert mock_conn.fetchrow.await_args_list[2].args[3] == CALLER_DID

    @pytest.mark.asyncio
    async def test_route_task_uses_the_caller_as_requester(self, client, authed):
        route = AsyncMock(return_value=_legacy_row())
        with patch("src.routers.tasks.create_routed_task", new=route):
            resp = await client.post("/tasks/route", json={"task_type": "security.audit"})
        assert resp.status_code == 201
        assert route.await_args.kwargs["requester_agent_did"] == CALLER_DID
