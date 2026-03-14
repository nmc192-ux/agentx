"""
Tests: src/services/token_service.py
Phase 8 — Agent Token Economy

Covers:
  create_wallet()        — creates or funds wallet
  get_wallet()           — returns wallet, raises if missing
  get_balance()          — delegates to get_wallet
  transfer_tokens()      — atomic debit+credit, insufficient funds, missing wallet
  stake_tokens()         — debits wallet, creates stake
  release_stake()        — credits wallet, marks released, raises if already released
  get_transactions()     — returns list for agent
  get_stakes()           — returns unreleased stakes only
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services import token_service


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tx_context(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _now():
    return datetime.now(UTC)


def _wallet_row(wallet_id=None, agent_id=None, balance=1000):
    return {
        "wallet_id":  wallet_id or uuid4(),
        "agent_id":   agent_id or uuid4(),
        "balance":    balance,
        "updated_at": _now(),
    }


def _tx_row(tx_id=None, from_w=None, to_w=None, amount=100, tx_type="transfer"):
    return {
        "transaction_id": tx_id or uuid4(),
        "from_wallet":    from_w,
        "to_wallet":      to_w,
        "amount":         amount,
        "type":           tx_type,
        "related_id":     None,
        "timestamp":      _now(),
    }


def _stake_row(stake_id=None, agent_id=None, amount=200):
    return {
        "stake_id":     stake_id or uuid4(),
        "agent_id":     agent_id or uuid4(),
        "amount":       amount,
        "locked_until": None,
        "released_at":  None,
        "created_at":   _now(),
    }


# ── create_wallet ─────────────────────────────────────────────────────────────

class TestCreateWallet:

    @pytest.mark.asyncio
    async def test_create_wallet_returns_wallet_response(self):
        agent_id = uuid4()
        row = _wallet_row(agent_id=agent_id, balance=500)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.token_service.transaction", return_value=_tx_context(conn)):
            result = await token_service.create_wallet(agent_id, initial_balance=500)

        assert result.agent_id == agent_id
        assert result.balance == 500
        conn.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_wallet_funds_existing_wallet(self):
        """ON CONFLICT path: second call merges balance."""
        agent_id = uuid4()
        # Simulate DB returning updated balance
        row = _wallet_row(agent_id=agent_id, balance=1500)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.token_service.transaction", return_value=_tx_context(conn)):
            result = await token_service.create_wallet(agent_id, initial_balance=500)

        assert result.balance == 1500


# ── get_wallet / get_balance ──────────────────────────────────────────────────

class TestGetWallet:

    @pytest.mark.asyncio
    async def test_get_wallet_returns_wallet_response(self):
        agent_id = uuid4()
        row = _wallet_row(agent_id=agent_id, balance=750)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.token_service.get_db", return_value=_tx_context(conn)):
            result = await token_service.get_wallet(agent_id)

        assert result.balance == 750
        assert result.agent_id == agent_id

    @pytest.mark.asyncio
    async def test_get_wallet_raises_if_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.token_service.get_db", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Wallet not found"),
        ):
            await token_service.get_wallet(uuid4())

    @pytest.mark.asyncio
    async def test_get_balance_returns_correct_balance(self):
        agent_id = uuid4()
        row = _wallet_row(agent_id=agent_id, balance=300)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.token_service.get_db", return_value=_tx_context(conn)):
            balance = await token_service.get_balance(agent_id)

        assert balance == 300


# ── transfer_tokens ───────────────────────────────────────────────────────────

class TestTransferTokens:

    @pytest.mark.asyncio
    async def test_transfer_tokens_debits_and_credits_correctly(self):
        from_agent = uuid4()
        to_agent   = uuid4()
        from_wid   = uuid4()
        to_wid     = uuid4()

        tx_row = _tx_row(from_w=from_wid, to_w=to_wid, amount=100)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"wallet_id": from_wid},   # debit RETURNING
            {"wallet_id": to_wid},     # credit RETURNING
            tx_row,                    # insert transaction RETURNING
        ])

        with patch("src.services.token_service.transaction", return_value=_tx_context(conn)):
            result = await token_service.transfer_tokens(from_agent, to_agent, 100)

        assert result.amount == 100
        assert result.from_wallet == from_wid
        assert result.to_wallet == to_wid
        assert conn.fetchrow.await_count == 3

    @pytest.mark.asyncio
    async def test_transfer_tokens_raises_on_insufficient_funds(self):
        from_agent = uuid4()
        to_agent   = uuid4()

        conn = AsyncMock()
        # Debit returns None (balance check failed), fetchval confirms wallet exists
        conn.fetchrow = AsyncMock(return_value=None)
        conn.fetchval = AsyncMock(return_value=1)  # wallet exists

        with (
            patch("src.services.token_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Insufficient funds"),
        ):
            await token_service.transfer_tokens(from_agent, to_agent, 9999)

    @pytest.mark.asyncio
    async def test_transfer_tokens_raises_if_sender_wallet_missing(self):
        from_agent = uuid4()
        to_agent   = uuid4()

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.fetchval = AsyncMock(return_value=None)  # wallet does not exist

        with (
            patch("src.services.token_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Sender wallet not found"),
        ):
            await token_service.transfer_tokens(from_agent, to_agent, 50)

    @pytest.mark.asyncio
    async def test_transfer_tokens_raises_if_receiver_wallet_missing(self):
        from_agent = uuid4()
        to_agent   = uuid4()
        from_wid   = uuid4()

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"wallet_id": from_wid},  # debit succeeds
            None,                      # credit returns None (receiver missing)
        ])

        with (
            patch("src.services.token_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Receiver wallet not found"),
        ):
            await token_service.transfer_tokens(from_agent, to_agent, 50)


# ── stake_tokens ──────────────────────────────────────────────────────────────

class TestStakeTokens:

    @pytest.mark.asyncio
    async def test_stake_tokens_creates_stake(self):
        agent_id = uuid4()
        wid      = uuid4()
        stake    = _stake_row(agent_id=agent_id, amount=200)
        tx_row   = _tx_row(from_w=wid, amount=200, tx_type="stake")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"wallet_id": wid},  # debit RETURNING
            stake,               # INSERT INTO stakes RETURNING
            tx_row,              # INSERT INTO transactions RETURNING
        ])

        with patch("src.services.token_service.transaction", return_value=_tx_context(conn)):
            result = await token_service.stake_tokens(agent_id, amount=200)

        assert result.amount == 200
        assert result.released_at is None

    @pytest.mark.asyncio
    async def test_stake_tokens_raises_on_insufficient_funds(self):
        agent_id = uuid4()

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.fetchval = AsyncMock(return_value=1)  # wallet exists

        with (
            patch("src.services.token_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Insufficient funds"),
        ):
            await token_service.stake_tokens(agent_id, amount=99999)


# ── release_stake ─────────────────────────────────────────────────────────────

class TestReleaseStake:

    @pytest.mark.asyncio
    async def test_release_stake_credits_wallet(self):
        stake_id = uuid4()
        agent_id = uuid4()
        wid      = uuid4()

        stake_row = {
            "stake_id":     stake_id,
            "agent_id":     agent_id,
            "amount":       300,
            "locked_until": None,
            "released_at":  None,
        }
        wallet_row = _wallet_row(wallet_id=wid, agent_id=agent_id, balance=1300)
        tx_row     = _tx_row(to_w=wid, amount=300, tx_type="unstake")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            stake_row,   # SELECT stake
            wallet_row,  # UPDATE wallets RETURNING
            tx_row,      # INSERT transactions RETURNING
        ])
        conn.execute = AsyncMock()

        with patch("src.services.token_service.transaction", return_value=_tx_context(conn)):
            result = await token_service.release_stake(stake_id)

        assert result.balance == 1300
        conn.execute.assert_awaited_once()  # UPDATE stakes SET released_at

    @pytest.mark.asyncio
    async def test_release_stake_raises_if_already_released(self):
        stake_id  = uuid4()
        stake_row = {
            "stake_id":     stake_id,
            "agent_id":     uuid4(),
            "amount":       100,
            "locked_until": None,
            "released_at":  _now(),   # already released
        }

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=stake_row)

        with (
            patch("src.services.token_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="already released"),
        ):
            await token_service.release_stake(stake_id)


# ── get_transactions ──────────────────────────────────────────────────────────

class TestGetTransactions:

    @pytest.mark.asyncio
    async def test_get_transactions_returns_list(self):
        agent_id = uuid4()
        wid      = uuid4()
        rows     = [_tx_row(from_w=wid), _tx_row(to_w=wid)]

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=wid)
        conn.fetch    = AsyncMock(return_value=rows)

        with patch("src.services.token_service.get_db", return_value=_tx_context(conn)):
            result = await token_service.get_transactions(agent_id)

        assert len(result) == 2
        assert result[0].amount == 100

    @pytest.mark.asyncio
    async def test_get_transactions_returns_empty_if_no_wallet(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)

        with patch("src.services.token_service.get_db", return_value=_tx_context(conn)):
            result = await token_service.get_transactions(uuid4())

        assert result == []


# ── get_stakes ────────────────────────────────────────────────────────────────

class TestGetStakes:

    @pytest.mark.asyncio
    async def test_get_stakes_returns_unreleased_only(self):
        agent_id = uuid4()
        rows     = [_stake_row(agent_id=agent_id), _stake_row(agent_id=agent_id)]

        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.token_service.get_db", return_value=_tx_context(conn)):
            result = await token_service.get_stakes(agent_id)

        assert len(result) == 2
        for stake in result:
            assert stake.released_at is None

    @pytest.mark.asyncio
    async def test_get_stakes_returns_empty_list(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.token_service.get_db", return_value=_tx_context(conn)):
            result = await token_service.get_stakes(uuid4())

        assert result == []
