"""
Tests: POST /blocks, DELETE /blocks/{target_did}
Phase 3.4 — Agent Blocks

Covers:
  - POST /blocks → 204 when target exists and has not blocked caller
  - POST /blocks → 404 when target agent does not exist
  - POST /blocks → 422 when trying to block self
  - POST /blocks → 401 when unauthenticated
  - DELETE /blocks/{target_did} → 204 (idempotent)
  - DELETE /blocks/{target_did} → 401 when unauthenticated
  - POST /agents/{did}/follow → 403 when target has blocked requester
  - POST /agents/{did}/follow → 204 when no block
  - POST /messages/send → 403 when receiver has blocked sender
  - POST /messages/send → 201 when no block
  - blocks_service unit: block / unblock / has_blocked / get_blocked_dids
"""
from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from httpx import AsyncClient, ASGITransport

from src.main import app
from src.auth.middleware import AgentRecord, get_current_agent
from src.auth.jwt import TokenClaims


# ── Fixtures & helpers ────────────────────────────────────────────────────────

ATLAS = "did:agentx:atlas-001"
NOVA  = "did:agentx:nova-006"
ROGUE = "did:agentx:rogue-013"


def _make_caller(did: str = ATLAS, role: str = "MEMBER") -> AgentRecord:
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = did
    return AgentRecord(
        row={
            "agent_did":       did,
            "display_name":    did.split(":")[-1],
            "governance_role": role,
            "tier":            "BASIC",
            "status":          "ACTIVE",
            "trust_score":     0.5,
            "bio":             None,
            "specialization":  None,
            "created_at":      datetime(2024, 1, 1, tzinfo=timezone.utc),
            "last_seen_at":    None,
        },
        claims=claims,
    )


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


def _override_auth(caller: AgentRecord):
    """Set app.dependency_overrides so every get_current_agent call returns caller."""
    app.dependency_overrides[get_current_agent] = lambda: caller


def _clear_overrides():
    app.dependency_overrides = {}


# ── POST /blocks ──────────────────────────────────────────────────────────────

class TestBlockAgent:

    @pytest.mark.asyncio
    async def test_block_returns_204(self, client):
        caller = _make_caller(ATLAS)
        _override_auth(caller)
        try:
            with (
                patch("src.routers.blocks.get_db") as mock_db,
                patch("src.routers.blocks.transaction") as mock_tx,
                patch("src.routers.blocks.blocks_service.block", new_callable=AsyncMock) as mock_block,
            ):
                conn = AsyncMock()
                conn.fetchval = AsyncMock(return_value=1)   # target agent exists
                mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
                mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_tx.return_value.__aenter__ = AsyncMock(return_value=conn)
                mock_tx.return_value.__aexit__ = AsyncMock(return_value=False)

                resp = await client.post(
                    "/blocks",
                    json={"target_did": NOVA},
                    headers={"Authorization": "Bearer ignored"},
                )
        finally:
            _clear_overrides()

        assert resp.status_code == 204
        mock_block.assert_awaited_once_with(conn, ATLAS, NOVA)

    @pytest.mark.asyncio
    async def test_block_self_returns_422(self, client):
        caller = _make_caller(ATLAS)
        _override_auth(caller)
        try:
            resp = await client.post(
                "/blocks",
                json={"target_did": ATLAS},
                headers={"Authorization": "Bearer ignored"},
            )
        finally:
            _clear_overrides()
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_block_unknown_agent_returns_404(self, client):
        caller = _make_caller(ATLAS)
        _override_auth(caller)
        try:
            with patch("src.routers.blocks.get_db") as mock_db:
                conn = AsyncMock()
                conn.fetchval = AsyncMock(return_value=None)   # agent not found
                mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
                mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

                resp = await client.post(
                    "/blocks",
                    json={"target_did": "did:agentx:ghost-999"},
                    headers={"Authorization": "Bearer ignored"},
                )
        finally:
            _clear_overrides()
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_block_unauthenticated_returns_401(self, client):
        # No override → real auth runs → invalid token → 401
        resp = await client.post("/blocks", json={"target_did": NOVA})
        assert resp.status_code == 401


# ── DELETE /blocks/{target_did} ───────────────────────────────────────────────

class TestUnblockAgent:

    @pytest.mark.asyncio
    async def test_unblock_returns_204(self, client):
        caller = _make_caller(ATLAS)
        _override_auth(caller)
        try:
            with (
                patch("src.routers.blocks.transaction") as mock_tx,
                patch("src.routers.blocks.blocks_service.unblock", new_callable=AsyncMock) as mock_unblock,
            ):
                conn = AsyncMock()
                mock_tx.return_value.__aenter__ = AsyncMock(return_value=conn)
                mock_tx.return_value.__aexit__ = AsyncMock(return_value=False)

                resp = await client.delete(
                    f"/blocks/{NOVA}",
                    headers={"Authorization": "Bearer ignored"},
                )
        finally:
            _clear_overrides()

        assert resp.status_code == 204
        mock_unblock.assert_awaited_once_with(conn, ATLAS, NOVA)

    @pytest.mark.asyncio
    async def test_unblock_unauthenticated_returns_401(self, client):
        resp = await client.delete(f"/blocks/{NOVA}")
        assert resp.status_code == 401


# ── Follow blocked 403 ─────────────────────────────────────────────────────────

class TestFollowBlocked:

    @pytest.mark.asyncio
    async def test_follow_blocked_by_target_returns_403(self, client):
        """If target (NOVA) has blocked caller (ATLAS), follow → 403."""
        caller = _make_caller(ATLAS)
        _override_auth(caller)
        try:
            with (
                patch("src.routers.follows.get_db") as mock_db,
                patch("src.routers.follows.blocks_service.has_blocked",
                      new_callable=AsyncMock, return_value=True),
            ):
                conn = AsyncMock()
                conn.fetchval = AsyncMock(return_value=1)   # target agent exists
                mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
                mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

                resp = await client.post(
                    f"/agents/{NOVA}/follow",
                    headers={"Authorization": "Bearer ignored"},
                )
        finally:
            _clear_overrides()
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_follow_not_blocked_succeeds(self, client):
        """Normal follow (no block) proceeds to 204."""
        caller = _make_caller(ATLAS)
        _override_auth(caller)
        try:
            with (
                patch("src.routers.follows.get_db") as mock_db,
                patch("src.routers.follows.transaction") as mock_tx,
                patch("src.routers.follows.blocks_service.has_blocked",
                      new_callable=AsyncMock, return_value=False),
            ):
                conn = AsyncMock()
                conn.fetchval = AsyncMock(return_value=1)
                conn.execute = AsyncMock()
                mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
                mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_tx.return_value.__aenter__ = AsyncMock(return_value=conn)
                mock_tx.return_value.__aexit__ = AsyncMock(return_value=False)

                resp = await client.post(
                    f"/agents/{NOVA}/follow",
                    headers={"Authorization": "Bearer ignored"},
                )
        finally:
            _clear_overrides()
        assert resp.status_code == 204


# ── Messages blocked 403 ───────────────────────────────────────────────────────

class TestMessageBlocked:

    def _body(self, sender: str = ATLAS, receiver: str = NOVA) -> dict:
        return {
            "sender_agent_did":   sender,
            "receiver_agent_did": receiver,
            "message":            "Hello there!",
        }

    @pytest.mark.asyncio
    async def test_send_message_blocked_by_receiver_returns_403(self, client):
        """If NOVA has blocked ATLAS, ATLAS cannot message NOVA."""
        with (
            patch("src.routers.messages.transaction") as mock_tx,
            patch("src.routers.messages.blocks_service.has_blocked",
                  new_callable=AsyncMock, return_value=True),
        ):
            conn = AsyncMock()
            conn.fetchrow = AsyncMock(side_effect=[
                {"agent_id": uuid4()},   # sender exists
                {"agent_id": uuid4()},   # receiver exists
            ])
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_tx.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.post("/messages/send", json=self._body())

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_send_message_not_blocked_succeeds(self, client):
        """Normal message (no block) returns 201."""
        msg_id = uuid4()
        now = datetime.now(timezone.utc)
        with (
            patch("src.routers.messages.transaction") as mock_tx,
            patch("src.routers.messages.blocks_service.has_blocked",
                  new_callable=AsyncMock, return_value=False),
            patch("src.routers.messages.emit_event", new_callable=AsyncMock),
            patch("src.routers.messages.record_event", new_callable=AsyncMock),
            patch("src.routers.messages.cache_delete", new_callable=AsyncMock),
        ):
            conn = AsyncMock()
            conn.fetchrow = AsyncMock(side_effect=[
                {"agent_id": uuid4()},
                {"agent_id": uuid4()},
                {
                    "message_id":         msg_id,
                    "sender_agent_did":   ATLAS,
                    "receiver_agent_did": NOVA,
                    "message":            "Hello there!",
                    "metadata":           json.dumps({}),
                    "created_at":         now,
                },
            ])
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_tx.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.post("/messages/send", json=self._body())

        assert resp.status_code == 201


# ── blocks_service unit tests (pure, no HTTP) ─────────────────────────────────

class TestBlocksServiceUnit:

    @pytest.mark.asyncio
    async def test_block_executes_insert(self):
        from src.services.blocks_service import block
        conn = AsyncMock()
        await block(conn, ATLAS, NOVA)
        conn.execute.assert_awaited_once()
        assert "INSERT INTO agent_blocks" in conn.execute.call_args[0][0]

    @pytest.mark.asyncio
    async def test_unblock_executes_delete(self):
        from src.services.blocks_service import unblock
        conn = AsyncMock()
        await unblock(conn, ATLAS, NOVA)
        conn.execute.assert_awaited_once()
        assert "DELETE FROM agent_blocks" in conn.execute.call_args[0][0]

    @pytest.mark.asyncio
    async def test_has_blocked_true_when_row_exists(self):
        from src.services.blocks_service import has_blocked
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        assert await has_blocked(conn, ATLAS, NOVA) is True

    @pytest.mark.asyncio
    async def test_has_blocked_false_when_no_row(self):
        from src.services.blocks_service import has_blocked
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        assert await has_blocked(conn, ATLAS, NOVA) is False

    @pytest.mark.asyncio
    async def test_get_blocked_dids_returns_list(self):
        from src.services.blocks_service import get_blocked_dids
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[
            {"blocked_did": NOVA},
            {"blocked_did": ROGUE},
        ])
        result = await get_blocked_dids(conn, ATLAS)
        assert set(result) == {NOVA, ROGUE}

    @pytest.mark.asyncio
    async def test_get_blocked_dids_empty(self):
        from src.services.blocks_service import get_blocked_dids
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        assert await get_blocked_dids(conn, ATLAS) == []
