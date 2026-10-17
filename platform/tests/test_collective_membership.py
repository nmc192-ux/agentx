"""
Tests: collective membership reads (Phase C, Sprint 22, CL-2).

  GET /collectives/{id}/requests    — pending requests, ACTIVE OWNER/ADMIN only
  GET /collectives/{id}/membership  — the caller's own role/status, or "none"
  POST /collectives/{id}/join       — the request's message is now kept

Fails closed: anonymous 401; non-member, MEMBER, PENDING or BANNED caller 403
for requests; a private collective is 404 to anyone who is not an ACTIVE
member (its existence is not confirmed); a missing collective 404.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app

ME = "did:agentx:me-001"
NOW = datetime.now(timezone.utc)


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


def _me(is_public=True, role=None, status=None, joined_at=None):
    return {"is_public": is_public, "role": role, "status": status, "joined_at": joined_at}


PENDING_ROWS = [
    {"agent_did": "did:agentx:c-001", "display_name": "C", "trust_score": 0.5,
     "joined_at": NOW, "request_message": "I review Python code"},
    {"agent_did": "did:agentx:d-001", "display_name": "D", "trust_score": 0.61,
     "joined_at": NOW, "request_message": None},
]


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c
    app.dependency_overrides = {}


def _db(me_row, rows=()):
    conn = AsyncMock()
    conn.fetchrow.return_value = me_row
    conn.fetch.return_value = list(rows)
    ctx = patch("src.routers.collectives.get_db")
    mock_db = ctx.start()
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
    return ctx, conn


async def _get(client, path, me_row, rows=(), auth=True):
    from src.auth.middleware import get_current_agent
    if auth:
        app.dependency_overrides[get_current_agent] = lambda: _caller()
    ctx, conn = _db(me_row, rows)
    try:
        resp = await client.get(path)
    finally:
        ctx.stop()
    return resp, conn


# ── GET /requests ─────────────────────────────────────────────────────────────

class TestRequests:

    @pytest.mark.asyncio
    async def test_anonymous_401(self, client):
        resp = await client.get(f"/collectives/{uuid.uuid4()}/requests")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["OWNER", "ADMIN"])
    async def test_owner_or_admin_sees_pending(self, client, role):
        resp, conn = await _get(
            client, f"/collectives/{uuid.uuid4()}/requests",
            _me(role=role, status="ACTIVE"), PENDING_ROWS)
        assert resp.status_code == 200
        body = resp.json()
        assert [r["agent_did"] for r in body] == ["did:agentx:c-001", "did:agentx:d-001"]
        assert body[0]["message"] == "I review Python code"
        assert body[1]["message"] is None
        assert body[1]["trust_score"] == 0.61
        assert body[0]["requested_at"]
        # only PENDING rows of this collective are read
        sql, col_id = conn.fetch.call_args.args
        assert "cm.status = 'PENDING'" in sql and "cm.collective_id = $1" in sql

    @pytest.mark.asyncio
    async def test_private_collective_admin_sees_pending(self, client):
        resp, _ = await _get(
            client, f"/collectives/{uuid.uuid4()}/requests",
            _me(is_public=False, role="ADMIN", status="ACTIVE"), PENDING_ROWS)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role,status_", [
        (None, None),            # not a member
        ("MEMBER", "ACTIVE"),
        ("MEMBER", "PENDING"),
        ("ADMIN", "PENDING"),    # an ADMIN row that is not ACTIVE
        ("ADMIN", "BANNED"),
        ("OWNER", "BANNED"),
    ])
    async def test_others_403_and_nothing_read(self, client, role, status_):
        resp, conn = await _get(
            client, f"/collectives/{uuid.uuid4()}/requests",
            _me(role=role, status=status_), PENDING_ROWS)
        assert resp.status_code == 403
        assert "OWNER or ADMIN" in resp.json()["detail"]
        conn.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_collective_404(self, client):
        resp, conn = await _get(client, f"/collectives/{uuid.uuid4()}/requests", None)
        assert resp.status_code == 404
        conn.fetch.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role,status_", [(None, None), ("MEMBER", "PENDING"),
                                              ("ADMIN", "BANNED")])
    async def test_private_collective_404_to_non_active(self, client, role, status_):
        resp, conn = await _get(
            client, f"/collectives/{uuid.uuid4()}/requests",
            _me(is_public=False, role=role, status=status_), PENDING_ROWS)
        assert resp.status_code == 404
        conn.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_bad_id_422(self, client):
        from src.auth.middleware import get_current_agent
        app.dependency_overrides[get_current_agent] = lambda: _caller()
        resp = await client.get("/collectives/not-a-uuid/requests")
        assert resp.status_code == 422


# ── GET /membership ───────────────────────────────────────────────────────────

class TestMembership:

    @pytest.mark.asyncio
    async def test_anonymous_401(self, client):
        resp = await client.get(f"/collectives/{uuid.uuid4()}/membership")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_none(self, client):
        col = uuid.uuid4()
        resp, conn = await _get(client, f"/collectives/{col}/membership", _me())
        assert resp.status_code == 200
        assert resp.json() == {"collective_id": str(col), "agent_did": ME,
                               "role": None, "status": "none", "since": None}
        # the lookup is keyed on the caller's own DID, never a parameter
        assert conn.fetchrow.call_args.args[1:] == (col, ME)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role,status_", [("MEMBER", "PENDING"), ("MEMBER", "ACTIVE"),
                                              ("ADMIN", "ACTIVE"), ("OWNER", "ACTIVE"),
                                              ("MEMBER", "BANNED")])
    async def test_own_row(self, client, role, status_):
        resp, _ = await _get(client, f"/collectives/{uuid.uuid4()}/membership",
                             _me(role=role, status=status_, joined_at=NOW))
        assert resp.status_code == 200
        body = resp.json()
        assert (body["role"], body["status"]) == (role, status_)
        assert body["since"]

    @pytest.mark.asyncio
    async def test_missing_404(self, client):
        resp, _ = await _get(client, f"/collectives/{uuid.uuid4()}/membership", None)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_private_404_unless_active(self, client):
        resp, _ = await _get(client, f"/collectives/{uuid.uuid4()}/membership",
                             _me(is_public=False))
        assert resp.status_code == 404
        resp, _ = await _get(client, f"/collectives/{uuid.uuid4()}/membership",
                             _me(is_public=False, role="MEMBER", status="PENDING"))
        assert resp.status_code == 404
        resp, _ = await _get(client, f"/collectives/{uuid.uuid4()}/membership",
                             _me(is_public=False, role="MEMBER", status="ACTIVE",
                                 joined_at=NOW))
        assert resp.status_code == 200 and resp.json()["status"] == "ACTIVE"


# ── POST /join keeps the message ──────────────────────────────────────────────

class TestJoinMessage:

    async def _join(self, client, body):
        from src.auth.middleware import get_current_agent
        app.dependency_overrides[get_current_agent] = lambda: _caller()
        with (
            patch("src.routers.collectives.get_db") as mock_db,
            patch("src.routers.collectives.transaction") as mock_tx,
        ):
            conn = AsyncMock()
            conn.fetchrow.return_value = {"collective_id": "x", "status": None}  # exists, no row
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
            tx = AsyncMock()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=tx)
            mock_tx.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = await client.post(f"/collectives/{uuid.uuid4()}/join", json=body)
        return resp, tx

    @pytest.mark.asyncio
    async def test_message_stored(self, client):
        resp, tx = await self._join(client, {"message": "  I review Python code \n"})
        assert resp.status_code == 202
        sql, _col, did, message = tx.execute.call_args.args
        assert "request_message" in sql and "ON CONFLICT" in sql and "DO NOTHING" in sql
        assert did == ME and message == "I review Python code"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", [{}, {"message": None}, {"message": "   "}])
    async def test_blank_message_is_null(self, client, body):
        resp, tx = await self._join(client, body)
        assert resp.status_code == 202
        assert tx.execute.call_args.args[3] is None

    @pytest.mark.asyncio
    async def test_overlong_message_422(self, client):
        resp, tx = await self._join(client, {"message": "x" * 501})
        assert resp.status_code == 422
        tx.execute.assert_not_called()
