"""
Tests: src/services/economy_service.py
Phase 8.5 — Economic Engine

Covers:
  initialize_treasury()      — creates wallet + supply singleton (idempotent)
  mint_tokens()              — increases supply + credits treasury
  collect_task_fee()         — deducts fee from escrow, credits treasury
  slash_stake()              — forfeits stake to treasury, records slash
  record_metrics()           — inserts economic snapshot
  get_latest_metrics()       — returns most recent snapshot
  get_treasury_balance()     — returns treasury wallet
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services import economy_service


# ── Helpers ────────────────────────────────────────────────────────────────────

def _tx_context(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _now():
    return datetime.now(UTC)


def _wallet_row(wallet_id=None, balance=0, wallet_type="treasury"):
    return {
        "wallet_id":   wallet_id or uuid4(),
        "agent_id":    None,
        "balance":     balance,
        "updated_at":  _now(),
        "wallet_type": wallet_type,
    }


def _supply_row(supply_id=None, minted=1000, burned=0):
    return {
        "supply_id":    supply_id or uuid4(),
        "total_minted": minted,
        "total_burned": burned,
        "updated_at":   _now(),
    }


def _stake_row(stake_id=None, agent_id=None, amount=200):
    return {
        "stake_id":    stake_id or uuid4(),
        "agent_id":    agent_id or uuid4(),
        "amount":      amount,
        "released_at": None,
    }


def _slash_row(slash_id=None, stake_id=None, agent_id=None, amount=200):
    return {
        "slash_id":   slash_id or uuid4(),
        "stake_id":   stake_id or uuid4(),
        "agent_id":   agent_id or uuid4(),
        "amount":     amount,
        "reason":     "bad actor",
        "created_at": _now(),
    }


def _metrics_row(metric_id=None):
    return {
        "metric_id":        metric_id or uuid4(),
        "total_supply":     5000,
        "treasury_balance": 1200,
        "total_staked":     800,
        "active_tasks":     3,
        "fees_collected":   50,
        "recorded_at":      _now(),
    }


# ── initialize_treasury ───────────────────────────────────────────────────────

class TestInitializeTreasury:

    @pytest.mark.asyncio
    async def test_creates_treasury_wallet_when_none_exists(self):
        """First call inserts a treasury wallet."""
        treasury_row = _wallet_row()
        conn = AsyncMock()
        # No existing treasury, no supply, insert succeeds
        conn.fetchrow = AsyncMock(side_effect=[
            None,         # SELECT existing treasury → none
            treasury_row, # INSERT INTO wallets RETURNING
        ])
        conn.fetchval = AsyncMock(return_value=None)  # SELECT 1 FROM token_supply
        conn.execute  = AsyncMock()

        with patch("src.services.economy_service.transaction", return_value=_tx_context(conn)):
            result = await economy_service.initialize_treasury()

        assert result.wallet_type == "treasury"
        assert result.agent_id is None

    @pytest.mark.asyncio
    async def test_is_idempotent_when_treasury_exists(self):
        """Subsequent calls return existing treasury without re-inserting."""
        existing = _wallet_row(balance=500)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=existing)  # existing found
        conn.fetchval = AsyncMock(return_value=1)          # supply exists
        conn.execute  = AsyncMock()

        with patch("src.services.economy_service.transaction", return_value=_tx_context(conn)):
            result = await economy_service.initialize_treasury()

        assert result.balance == 500
        # fetchrow called once (SELECT existing) — no INSERT
        assert conn.fetchrow.await_count == 1


# ── mint_tokens ───────────────────────────────────────────────────────────────

class TestMintTokens:

    @pytest.mark.asyncio
    async def test_mint_increases_supply(self):
        treasury_id = uuid4()
        supply      = _supply_row(minted=5000)
        tx_row = {
            "transaction_id": uuid4(),
            "from_wallet":    None,
            "to_wallet":      treasury_id,
            "amount":         1000,
            "type":           "genesis",
            "related_id":     None,
            "timestamp":      _now(),
        }

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=treasury_id)  # _get_treasury_wallet_id
        conn.execute  = AsyncMock()
        # First fetchrow: UPDATE token_supply RETURNING; second: INSERT tx RETURNING
        conn.fetchrow = AsyncMock(side_effect=[supply, tx_row])

        with patch("src.services.economy_service.transaction", return_value=_tx_context(conn)):
            result = await economy_service.mint_tokens(1000, "genesis")

        assert result.total_minted == 5000
        assert result.circulating == 5000   # burned = 0

    @pytest.mark.asyncio
    async def test_mint_raises_if_no_treasury(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)   # no treasury

        with (
            patch("src.services.economy_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Treasury not initialised"),
        ):
            await economy_service.mint_tokens(100)

    @pytest.mark.asyncio
    async def test_mint_raises_if_no_supply_row(self):
        """UPDATE token_supply returns None when supply row missing."""
        treasury_id = uuid4()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=treasury_id)
        conn.execute  = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)   # supply UPDATE returns None

        with (
            patch("src.services.economy_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not initialised"),
        ):
            await economy_service.mint_tokens(100)

    @pytest.mark.asyncio
    async def test_mint_records_transaction(self):
        """A transaction ledger entry (NULL → treasury) is recorded."""
        treasury_id = uuid4()
        supply      = _supply_row(minted=200)

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=treasury_id)
        conn.execute  = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            supply,                              # UPDATE token_supply RETURNING
            {                                    # INSERT INTO transactions RETURNING
                "transaction_id": uuid4(),
                "from_wallet":    None,
                "to_wallet":      treasury_id,
                "amount":         100,
                "type":           "mint",
                "related_id":     None,
                "timestamp":      _now(),
            },
        ])

        with patch("src.services.economy_service.transaction", return_value=_tx_context(conn)):
            await economy_service.mint_tokens(100)

        # Ensure execute was called (UPDATE wallets) and fetchrow for INSERT tx
        conn.execute.assert_awaited()


# ── collect_task_fee ──────────────────────────────────────────────────────────

class TestCollectTaskFee:

    @pytest.mark.asyncio
    async def test_returns_fee_when_policy_and_treasury_exist(self):
        """250 bps fee on 1000 escrow = 25 tokens."""
        task_id     = uuid4()
        treasury_id = uuid4()
        tx_row = {
            "transaction_id": uuid4(), "from_wallet": None,
            "to_wallet": treasury_id, "amount": 25,
            "type": "fee", "related_id": task_id, "timestamp": _now(),
        }

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"rate_bps": 250},  # SELECT fee policy
            tx_row,             # INSERT transactions RETURNING
        ])
        conn.fetchval = AsyncMock(return_value=treasury_id)
        conn.execute  = AsyncMock()

        with patch("src.services.economy_service.transaction", return_value=_tx_context(conn)):
            fee = await economy_service.collect_task_fee(task_id, 1000)

        assert fee == 25

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_active_policy(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # no policy

        with patch("src.services.economy_service.transaction", return_value=_tx_context(conn)):
            fee = await economy_service.collect_task_fee(uuid4(), 1000)

        assert fee == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_treasury(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"rate_bps": 250})
        conn.fetchval = AsyncMock(return_value=None)  # no treasury

        with patch("src.services.economy_service.transaction", return_value=_tx_context(conn)):
            fee = await economy_service.collect_task_fee(uuid4(), 1000)

        assert fee == 0

    @pytest.mark.asyncio
    async def test_returns_zero_for_zero_escrow(self):
        """Escrow of 0 should skip all DB work."""
        with patch("src.services.economy_service.transaction") as mock_tx:
            fee = await economy_service.collect_task_fee(uuid4(), 0)
        assert fee == 0
        mock_tx.assert_not_called()


# ── slash_stake ───────────────────────────────────────────────────────────────

class TestSlashStake:

    @pytest.mark.asyncio
    async def test_slash_records_slash_and_releases_stake(self):
        stake_id    = uuid4()
        agent_id    = uuid4()
        treasury_id = uuid4()
        stake       = _stake_row(stake_id=stake_id, agent_id=agent_id, amount=300)
        slash       = _slash_row(stake_id=stake_id, agent_id=agent_id, amount=300)
        tx_row = {
            "transaction_id": uuid4(), "from_wallet": None,
            "to_wallet": treasury_id, "amount": 300,
            "type": "slash", "related_id": stake_id, "timestamp": _now(),
        }

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            stake,   # SELECT stake
            tx_row,  # INSERT transactions RETURNING
            slash,   # INSERT stake_slashes RETURNING
        ])
        conn.fetchval = AsyncMock(return_value=treasury_id)
        conn.execute  = AsyncMock()

        with patch("src.services.economy_service.transaction", return_value=_tx_context(conn)):
            result = await economy_service.slash_stake(stake_id, "bad actor")

        assert result.amount == 300
        assert result.stake_id == stake_id

    @pytest.mark.asyncio
    async def test_slash_transfers_to_treasury(self):
        """UPDATE wallets (treasury credit) must be called."""
        stake_id    = uuid4()
        treasury_id = uuid4()
        stake       = _stake_row(stake_id=stake_id, amount=150)
        slash       = _slash_row(stake_id=stake_id, amount=150)
        tx_row = {
            "transaction_id": uuid4(), "from_wallet": None,
            "to_wallet": treasury_id, "amount": 150,
            "type": "slash", "related_id": stake_id, "timestamp": _now(),
        }

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[stake, tx_row, slash])
        conn.fetchval = AsyncMock(return_value=treasury_id)
        conn.execute  = AsyncMock()

        with patch("src.services.economy_service.transaction", return_value=_tx_context(conn)):
            await economy_service.slash_stake(stake_id, "test")

        # execute called at least for: UPDATE stakes released_at + UPDATE wallets balance
        assert conn.execute.await_count >= 2

    @pytest.mark.asyncio
    async def test_slash_raises_if_stake_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.economy_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await economy_service.slash_stake(uuid4())

    @pytest.mark.asyncio
    async def test_slash_raises_if_already_released(self):
        stake = {
            "stake_id":    uuid4(),
            "agent_id":    uuid4(),
            "amount":      100,
            "released_at": _now(),   # already released
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=stake)

        with (
            patch("src.services.economy_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="already released"),
        ):
            await economy_service.slash_stake(stake["stake_id"])


# ── record_metrics ────────────────────────────────────────────────────────────

class TestRecordMetrics:

    @pytest.mark.asyncio
    async def test_inserts_metrics_snapshot(self):
        row = _metrics_row()

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"total_minted": 5000},  # SELECT token_supply
            {"balance": 1200},       # SELECT wallets (treasury)
            row,                     # INSERT economic_metrics RETURNING
        ])
        conn.fetchval = AsyncMock(side_effect=[800, 3, 50])  # staked, active, fees

        with patch("src.services.economy_service.transaction", return_value=_tx_context(conn)):
            result = await economy_service.record_metrics()

        assert result.total_supply == 5000
        assert result.treasury_balance == 1200
        assert result.total_staked == 800


# ── get_latest_metrics ────────────────────────────────────────────────────────

class TestGetLatestMetrics:

    @pytest.mark.asyncio
    async def test_returns_most_recent_snapshot(self):
        row = _metrics_row()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.economy_service.get_db", return_value=_tx_context(conn)):
            result = await economy_service.get_latest_metrics()

        assert result is not None
        assert result.active_tasks == 3

    @pytest.mark.asyncio
    async def test_returns_none_when_no_snapshots(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("src.services.economy_service.get_db", return_value=_tx_context(conn)):
            result = await economy_service.get_latest_metrics()

        assert result is None


# ── get_treasury_balance ──────────────────────────────────────────────────────

class TestGetTreasuryBalance:

    @pytest.mark.asyncio
    async def test_returns_treasury_wallet(self):
        row = _wallet_row(balance=9999)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.economy_service.get_db", return_value=_tx_context(conn)):
            result = await economy_service.get_treasury_balance()

        assert result.balance == 9999
        assert result.wallet_type == "treasury"

    @pytest.mark.asyncio
    async def test_raises_if_treasury_not_initialised(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.economy_service.get_db", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Treasury not initialised"),
        ):
            await economy_service.get_treasury_balance()
