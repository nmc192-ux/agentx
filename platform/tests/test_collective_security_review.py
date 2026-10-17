"""
Tests: Sprint 22 security review (CL-8a) — the holes it closed, fail closed.

  GET  /collectives/{id}            a private collective was returned to anyone
  GET  /collectives/{id}/members    … and so was its member list
  DELETE /collectives/{id}/members/{did}
                                    an ADMIN could remove another ADMIN; a BANNED
                                    agent could delete its own row (un-banning
                                    itself) and ask again
  POST /collectives/{id}/join       a BANNED agent was told "pending"
  assign_task_to_collective         one task could be shown as "work done" by
                                    several collectives
  GET  /collectives?q=              the search string had no length cap

Every refusal is checked for *nothing written*: the DELETE or INSERT is not
sent at all, and the refusal does not depend on the row being there.
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app

ME = "did:agentx:me-001"
OTHER = "did:agentx:other-001"


def _caller(did=ME):
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = did
    return AgentRecord(
        row={"agent_did": did, "display_name": "me", "governance_role": "MEMBER",
             "tier": "BOOTSTRAP", "status": "ACTIVE", "trust_score": 0.5},
        claims=claims,
    )


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c
    app.dependency_overrides = {}


def _login(auth: bool):
    from src.auth.middleware import get_current_agent, get_current_agent_optional
    if auth:
        app.dependency_overrides[get_current_agent] = lambda: _caller()
        app.dependency_overrides[get_current_agent_optional] = lambda: _caller()
    else:
        app.dependency_overrides[get_current_agent_optional] = lambda: None


def _db(fetchrow=None, fetchval=None, fetch=()):
    conn = AsyncMock()
    if isinstance(fetchrow, list):
        conn.fetchrow.side_effect = fetchrow
    else:
        conn.fetchrow.return_value = fetchrow
    conn.fetchval.return_value = fetchval
    conn.fetch.return_value = list(fetch)
    ctx = patch("src.routers.collectives.get_db")
    mock_db = ctx.start()
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
    return ctx, conn


def _tx(result="DELETE 1"):
    tx = AsyncMock()
    tx.execute.return_value = result
    ctx = patch("src.routers.collectives.transaction")
    mock_tx = ctx.start()
    mock_tx.return_value.__aenter__ = AsyncMock(return_value=tx)
    mock_tx.return_value.__aexit__ = AsyncMock(return_value=False)
    return ctx, tx


COLLECTIVE = {
    "collective_id": uuid4(), "name": "G", "description": "d", "charter": None,
    "is_public": False, "owner_did": OTHER, "member_count": 2,
    "trust_score_avg": 0.6, "created_at": "2026-10-15T00:00:00+00:00",
}


# ── Private collective reads ─────────────────────────────────────────────────

class TestPrivateCollectiveProfile:

    async def _get(self, client, vis, auth):
        _login(auth)
        ctx, conn = _db(fetchrow=[vis, COLLECTIVE], fetch=[])
        try:
            resp = await client.get(f"/collectives/{uuid4()}")
        finally:
            ctx.stop()
        return resp, conn

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth", [False, True])
    async def test_private_hidden_unless_active_member(self, client, auth):
        resp, conn = await self._get(client, {"is_public": False, "active": False}, auth)
        assert resp.status_code == 404
        assert conn.fetchrow.call_count == 1          # the profile is never read
        conn.fetch.assert_not_called()               # nor the member list

    @pytest.mark.asyncio
    async def test_private_shown_to_active_member(self, client):
        resp, _ = await self._get(client, {"is_public": False, "active": True}, True)
        assert resp.status_code == 200
        assert resp.json()["is_public"] is False

    @pytest.mark.asyncio
    async def test_public_shown_to_anonymous(self, client):
        resp, _ = await self._get(client, {"is_public": True, "active": False}, False)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_missing_404(self, client):
        resp, conn = await self._get(client, None, False)
        assert resp.status_code == 404
        assert conn.fetchrow.call_count == 1

    @pytest.mark.asyncio
    async def test_visibility_is_asked_for_the_caller_only(self, client):
        """The membership check is keyed on the caller's own DID (not a body
        or query value), and anonymous callers are checked with no DID."""
        _login(True)
        ctx, conn = _db(fetchrow=[{"is_public": False, "active": True}, COLLECTIVE])
        try:
            await client.get(f"/collectives/{uuid4()}?did={OTHER}")
        finally:
            ctx.stop()
        assert conn.fetchrow.call_args_list[0].args[2] == ME
        _login(False)
        ctx, conn = _db(fetchrow=[{"is_public": True, "active": False}, COLLECTIVE])
        try:
            await client.get(f"/collectives/{uuid4()}")
        finally:
            ctx.stop()
        assert conn.fetchrow.call_args_list[0].args[2] is None


class TestPrivateCollectiveMembers:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth", [False, True])
    async def test_private_hidden_and_service_not_called(self, client, auth):
        _login(auth)
        ctx, _ = _db(fetchrow={"is_public": False, "active": False})
        service = AsyncMock(return_value=[])
        try:
            with patch("src.routers.collectives.collective_service.get_members", new=service):
                resp = await client.get(f"/collectives/{uuid4()}/members")
        finally:
            ctx.stop()
        assert resp.status_code == 404
        service.assert_not_called()

    @pytest.mark.asyncio
    async def test_private_shown_to_active_member(self, client):
        _login(True)
        ctx, _ = _db(fetchrow={"is_public": False, "active": True})
        try:
            with patch("src.routers.collectives.collective_service.get_members",
                       new=AsyncMock(return_value=[])):
                resp = await client.get(f"/collectives/{uuid4()}/members")
        finally:
            ctx.stop()
        assert resp.status_code == 200


# ── DELETE /members/{did} ────────────────────────────────────────────────────

class TestRemoveMember:

    async def _delete(self, client, target_did, caller_role, target, deleted="DELETE 1"):
        """caller_role: the caller's ACTIVE role (None = not an active member);
        target: the row being removed, or None."""
        _login(True)
        ctx, conn = _db(fetchrow=target, fetchval=caller_role)
        tctx, tx = _tx(deleted)
        try:
            resp = await client.delete(f"/collectives/{uuid4()}/members/{target_did}")
        finally:
            ctx.stop()
            tctx.stop()
        return resp, tx

    @pytest.mark.asyncio
    async def test_admin_cannot_remove_admin(self, client):
        resp, tx = await self._delete(client, OTHER, "ADMIN",
                                      {"role": "ADMIN", "status": "ACTIVE"})
        assert resp.status_code == 403
        assert "OWNER" in resp.json()["detail"]
        tx.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_owner_can_remove_admin(self, client):
        resp, tx = await self._delete(client, OTHER, "OWNER",
                                      {"role": "ADMIN", "status": "ACTIVE"})
        assert resp.status_code == 204
        sql = tx.execute.call_args.args[0]
        assert "role <> 'OWNER'" in sql

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_", ["ACTIVE", "PENDING"])
    async def test_admin_can_remove_member(self, client, status_):
        resp, tx = await self._delete(client, OTHER, "ADMIN",
                                      {"role": "MEMBER", "status": status_})
        assert resp.status_code == 204
        sql = tx.execute.call_args.args[0]
        assert "role = 'MEMBER'" in sql        # the DELETE itself re-checks the role

    @pytest.mark.asyncio
    async def test_admin_delete_races_a_promotion(self, client):
        """The target became an ADMIN between the read and the write: the
        guarded DELETE touches nothing and the call is a 404, not a removal."""
        resp, tx = await self._delete(client, OTHER, "ADMIN",
                                      {"role": "MEMBER", "status": "ACTIVE"}, deleted="DELETE 0")
        assert resp.status_code == 404
        tx.execute.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caller_role", [None, "MEMBER"])
    async def test_member_or_outsider_cannot_remove_anyone(self, client, caller_role):
        resp, tx = await self._delete(client, OTHER, caller_role,
                                      {"role": "MEMBER", "status": "ACTIVE"})
        assert resp.status_code == 403
        tx.execute.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caller_role", ["OWNER", "ADMIN"])
    async def test_nobody_removes_the_owner(self, client, caller_role):
        resp, tx = await self._delete(client, OTHER, caller_role,
                                      {"role": "OWNER", "status": "ACTIVE"})
        assert resp.status_code == 422
        tx.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_owner_cannot_leave(self, client):
        resp, tx = await self._delete(client, ME, None, {"role": "OWNER", "status": "ACTIVE"})
        assert resp.status_code == 422
        tx.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_banned_agent_cannot_delete_its_own_row(self, client):
        resp, tx = await self._delete(client, ME, None, {"role": "MEMBER", "status": "BANNED"})
        assert resp.status_code == 403
        assert "banned" in resp.json()["detail"].lower()
        tx.execute.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_", ["ACTIVE", "PENDING"])
    async def test_member_can_leave_or_withdraw(self, client, status_):
        resp, tx = await self._delete(client, ME, None, {"role": "MEMBER", "status": status_})
        assert resp.status_code == 204
        sql = tx.execute.call_args.args[0]
        assert "status <> 'BANNED'" in sql and "role <> 'OWNER'" in sql

    @pytest.mark.asyncio
    async def test_admin_can_leave(self, client):
        resp, _ = await self._delete(client, ME, None, {"role": "ADMIN", "status": "ACTIVE"})
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_no_row_404(self, client):
        resp, tx = await self._delete(client, ME, None, None)
        assert resp.status_code == 404
        tx.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_outsider_gets_403_before_the_target_is_looked_at(self, client):
        """No 404-vs-403 difference tells a non-member whether a DID is in the group."""
        for target in (None, {"role": "MEMBER", "status": "ACTIVE"}):
            resp, tx = await self._delete(client, OTHER, None, target)
            assert resp.status_code == 403
            tx.execute.assert_not_called()


# ── POST /join ───────────────────────────────────────────────────────────────

class TestJoinWhenBanned:

    async def _join(self, client, status_):
        _login(True)
        ctx, conn = _db(fetchrow=None if status_ == "missing"
                        else {"collective_id": "x", "status": status_})
        tctx, tx = _tx("INSERT 0 1")
        try:
            resp = await client.post(f"/collectives/{uuid4()}/join", json={"message": "hi"})
        finally:
            ctx.stop()
            tctx.stop()
        return resp, conn, tx

    @pytest.mark.asyncio
    async def test_banned_403_and_nothing_written(self, client):
        resp, conn, tx = await self._join(client, "BANNED")
        assert resp.status_code == 403
        tx.execute.assert_not_called()
        # the standing read is the caller's own, by DID
        assert conn.fetchrow.call_args.args[2] == ME

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_", [None, "PENDING", "ACTIVE"])
    async def test_others_accepted_without_overwriting(self, client, status_):
        resp, _, tx = await self._join(client, status_)
        assert resp.status_code == 202
        assert "DO NOTHING" in tx.execute.call_args.args[0]

    @pytest.mark.asyncio
    async def test_missing_404(self, client):
        resp, _, tx = await self._join(client, "missing")
        assert resp.status_code == 404
        tx.execute.assert_not_called()


# ── One collective per task ──────────────────────────────────────────────────

class TestAssignOnce:

    def _conn(self, task_row, col_id):
        conn = AsyncMock()
        conn.fetchval.side_effect = [1, "OWNER"]       # collective exists; assigner role
        conn.fetchrow.side_effect = [task_row, {
            "collective_task_id": uuid4(), "collective_id": col_id, "task_id": task_row["task_id"],
            "assigned_by_did": ME, "status": "assigned", "assigned_at": "2026-10-15T00:00:00+00:00",
        }]
        return conn

    async def _assign(self, task_row, col_id):
        from src.services import collective_service
        conn = self._conn(task_row, col_id)
        with patch("src.services.collective_service.transaction") as tx:
            tx.return_value.__aenter__ = AsyncMock(return_value=conn)
            tx.return_value.__aexit__ = AsyncMock(return_value=False)
            return await collective_service.assign_task_to_collective(
                collective_id=col_id, task_id=task_row["task_id"], assigned_by_did=ME,
            ), conn

    @pytest.mark.asyncio
    async def test_task_in_another_collective_is_refused(self):
        col_id, elsewhere = uuid4(), uuid4()
        row = {"task_id": uuid4(), "status": "assigned", "requester_agent_did": OTHER,
               "executor_agent_did": ME, "executor_collective_id": elsewhere}
        with pytest.raises(ValueError, match="another collective"):
            await self._assign(row, col_id)

    @pytest.mark.asyncio
    async def test_same_collective_again_is_fine(self):
        col_id = uuid4()
        row = {"task_id": uuid4(), "status": "assigned", "requester_agent_did": OTHER,
               "executor_agent_did": ME, "executor_collective_id": col_id}
        result, conn = await self._assign(row, col_id)
        assert result.status == "assigned"
        assert "UPDATE tasks SET executor_collective_id" in conn.execute.call_args.args[0]

    @pytest.mark.asyncio
    async def test_unassigned_task_is_fine(self):
        col_id = uuid4()
        row = {"task_id": uuid4(), "status": "assigned", "requester_agent_did": OTHER,
               "executor_agent_did": ME, "executor_collective_id": None}
        result, _ = await self._assign(row, col_id)
        assert result.collective_id == col_id


# ── Search string cap ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_string_capped(client):
    ctx, conn = _db(fetchval=0, fetch=[])
    try:
        resp = await client.get("/collectives", params={"q": "x" * 129})
        assert resp.status_code == 422
        conn.fetch.assert_not_called()
        resp = await client.get("/collectives", params={"q": "x" * 128})
        assert resp.status_code == 200
    finally:
        ctx.stop()
