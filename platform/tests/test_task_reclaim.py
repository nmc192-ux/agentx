"""
Unit tests: POST /tasks/{task_id}/reclaim — the task work deadline
Sprint 21, BT-1 (decision D10, default b).

The route and the service's own switch are tested here without a database;
the money path (refund once, the races) is proven against real Postgres in
tests/integration/test_task_reclaim_db.py (run with --db).

What is proven here:
  • an anonymous caller gets 401 and the service is never called
  • the caller comes from the token only: the route takes no body, and a body
    naming someone else changes nothing
  • PermissionError → 403, TaskConflictError → 409, ValueError → 404
  • with TASK_WORK_DAYS at its default (0) the service refuses before it
    touches the database, so a misconfigured platform moves no token
  • the setting is read per call, so switching it on needs no restart of
    the test (and no code change in production)
  • the skill document prints the rule only while reclaim is on
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app

CALLER_DID = "did:agentx:atlas-001"
OTHER_DID = "did:agentx:someone-else-001"


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
    ) as c:
        yield c


def _make_agent(did=CALLER_DID, role="MEMBER"):
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = did
    row = {
        "agent_did": did, "display_name": "Atlas", "governance_role": role,
        "tier": "STANDARD", "status": "ACTIVE", "trust_score": 0.9,
    }
    return AgentRecord(row=row, claims=claims)


@contextmanager
def _as(caller):
    from src.auth.middleware import get_current_agent
    app.dependency_overrides[get_current_agent] = lambda: caller
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_agent, None)


@pytest.fixture
def authed():
    with _as(_make_agent()):
        yield


def _cancelled(task_id):
    from src.models.task import TaskResponse
    return TaskResponse(
        task_id=task_id, creator_agent_id=uuid4(), task_type="marketplace.test",
        payload={}, reward=100, status="cancelled",
        created_at=datetime.now(timezone.utc), executor_agent_id=uuid4(),
    )


SERVICE = "src.routers.tasks.task_service.reclaim_task"


# ── The route ──────────────────────────────────────────────────────────────────

class TestReclaimRoute:

    @pytest.mark.asyncio
    async def test_anonymous_is_401_and_the_service_is_not_called(self, client):
        service = AsyncMock()
        with patch(SERVICE, new=service):
            resp = await client.post(f"/tasks/{uuid4()}/reclaim")
        assert resp.status_code == 401
        service.assert_not_called()

    @pytest.mark.asyncio
    async def test_reclaim_returns_200_and_passes_the_token_caller(self, client, authed):
        task_id = uuid4()
        service = AsyncMock(return_value=_cancelled(task_id))
        with patch(SERVICE, new=service):
            resp = await client.post(f"/tasks/{task_id}/reclaim")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
        service.assert_awaited_once_with(task_id=task_id, caller_did=CALLER_DID)

    @pytest.mark.asyncio
    async def test_a_body_naming_someone_else_is_ignored(self, client, authed):
        """The route takes no body; identity never comes from it."""
        task_id = uuid4()
        service = AsyncMock(return_value=_cancelled(task_id))
        with patch(SERVICE, new=service):
            resp = await client.post(
                f"/tasks/{task_id}/reclaim",
                json={"creator_agent_did": OTHER_DID, "agent_did": OTHER_DID},
                params={"agent_did": OTHER_DID},
                headers={"X-Agent-DID": OTHER_DID},
            )
        assert resp.status_code == 200
        service.assert_awaited_once_with(task_id=task_id, caller_did=CALLER_DID)

    @pytest.mark.asyncio
    async def test_not_the_creator_is_403(self, client, authed):
        with patch(SERVICE, new=AsyncMock(
            side_effect=PermissionError("Only the task creator can reclaim it"),
        )):
            resp = await client.post(f"/tasks/{uuid4()}/reclaim")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    @pytest.mark.parametrize("message", [
        "Task reclaim is switched off on this platform",
        "Only an assigned task with nothing under review can be reclaimed (status=open)",
        "Only an assigned task with nothing under review can be reclaimed (status=in_review)",
        "Only an assigned task with nothing under review can be reclaimed (status=cancelled)",
        "The worker still has time (7 days from taking the task or from the last rejection)",
    ])
    async def test_conflicts_are_409(self, client, authed, message):
        from src.services.task_service import TaskConflictError
        with patch(SERVICE, new=AsyncMock(side_effect=TaskConflictError(message))):
            resp = await client.post(f"/tasks/{uuid4()}/reclaim")
        assert resp.status_code == 409
        assert resp.json()["detail"] == message

    @pytest.mark.asyncio
    async def test_unknown_task_is_404(self, client, authed):
        with patch(SERVICE, new=AsyncMock(side_effect=ValueError("Task not found"))):
            resp = await client.post(f"/tasks/{uuid4()}/reclaim")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_a_bad_task_id_is_422_before_the_service(self, client, authed):
        service = AsyncMock()
        with patch(SERVICE, new=service):
            resp = await client.post("/tasks/not-a-uuid/reclaim")
        assert resp.status_code == 422
        service.assert_not_called()


# ── The service's switch ───────────────────────────────────────────────────────

class TestReclaimSwitch:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [0, -1, None])
    async def test_off_by_default_refuses_before_any_database_work(self, monkeypatch, value):
        from src.config import get_settings
        from src.services import task_service

        monkeypatch.setattr(get_settings(), "task_work_days", value)
        tx = MagicMock()
        monkeypatch.setattr(task_service, "transaction", tx)
        with pytest.raises(task_service.TaskConflictError, match="switched off"):
            await task_service.reclaim_task(uuid4(), CALLER_DID)
        tx.assert_not_called()

    def test_the_shipped_default_is_off(self):
        from src.config import Settings
        assert Settings.model_fields["task_work_days"].default == 0

    @pytest.mark.asyncio
    async def test_switched_on_reaches_the_locked_transaction(self, monkeypatch):
        """With the setting above 0 the service opens its transaction and
        locks the task row before deciding anything (the DB tests prove the
        rest)."""
        from src.config import get_settings
        from src.services import task_service

        monkeypatch.setattr(get_settings(), "task_work_days", 7)
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=None)       # task not found
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(task_service, "transaction", MagicMock(return_value=ctx))

        with pytest.raises(ValueError, match="Task not found"):
            await task_service.reclaim_task(uuid4(), CALLER_DID)
        sql = conn.fetchrow.await_args.args[0]
        assert "FOR UPDATE" in sql and "FROM tasks" in sql


# ── The skill document ─────────────────────────────────────────────────────────

class TestSkillText:

    def _render(self, **kw):
        from src.a2a.skill import render_skill_md
        return render_skill_md(
            "http://testserver", lambda r: True,
            access_token_ttl=900, refresh_token_ttl=86400, **kw,
        )

    def test_rule_is_printed_only_while_reclaim_is_on(self):
        off = self._render()
        assert "/reclaim" not in off
        on = self._render(task_work_days=7)
        assert "Deliver within 7 days" in on
        assert "POST /tasks/<task_id>/reclaim" in on

    @pytest.mark.asyncio
    async def test_served_document_follows_the_setting(self, client, monkeypatch):
        from src.config import get_settings
        monkeypatch.setattr(get_settings(), "task_work_days", 0)
        assert "/reclaim" not in (await client.get("/.well-known/skill.md")).text
        monkeypatch.setattr(get_settings(), "task_work_days", 5)
        assert "Deliver within 5 days" in (await client.get("/.well-known/skill.md")).text
