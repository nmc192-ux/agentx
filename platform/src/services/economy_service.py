"""
AgentX Platform — Economic Engine Service
═════════════════════════════════════════
Phase 8.5: Treasury, supply management, fee collection, stake slashing,
and economic metrics.

Public API
──────────
  initialize_treasury()                         → WalletResponse
  mint_tokens(amount, reason)                   → TokenSupplyResponse
  collect_task_fee(task_id, escrow_amount)      → int   (fee deducted)
  slash_stake(stake_id, reason)                 → StakeSlashResponse
  record_metrics()                              → EconomicMetricsResponse
  get_latest_metrics()                          → EconomicMetricsResponse | None
  get_treasury_balance()                        → WalletResponse

Design notes
────────────
• Treasury wallet has agent_id = NULL and wallet_type = 'treasury'.
• token_supply is a singleton row; initialize_treasury() creates it.
• Fees are taken from the task escrow (escrowed_reward reduced) and
  credited directly to the treasury wallet.
• All DB calls use asyncpg via get_db() / transaction().
"""
from __future__ import annotations

import logging
from uuid import UUID

from ..database import get_db, transaction
from ..models.economy import (
    EconomicMetricsResponse,
    StakeSlashResponse,
    TokenSupplyResponse,
)
from ..models.token import WalletResponse
from .token_service import _get_treasury_wallet_id, _record_transaction, _row_to_wallet

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _row_to_supply(row) -> TokenSupplyResponse:
    return TokenSupplyResponse(
        supply_id=row["supply_id"],
        total_minted=row["total_minted"],
        total_burned=row["total_burned"],
        circulating=row["total_minted"] - row["total_burned"],
        updated_at=row["updated_at"],
    )


def _row_to_slash(row) -> StakeSlashResponse:
    return StakeSlashResponse(
        slash_id=row["slash_id"],
        stake_id=row["stake_id"],
        agent_id=row["agent_id"],
        amount=row["amount"],
        reason=row.get("reason"),
        created_at=row["created_at"],
    )


def _row_to_metrics(row) -> EconomicMetricsResponse:
    return EconomicMetricsResponse(
        metric_id=row["metric_id"],
        total_supply=row["total_supply"],
        treasury_balance=row["treasury_balance"],
        total_staked=row["total_staked"],
        active_tasks=row["active_tasks"],
        fees_collected=row["fees_collected"],
        recorded_at=row["recorded_at"],
    )


# ── Treasury initialisation ───────────────────────────────────────────────────

async def initialize_treasury() -> WalletResponse:
    """
    Idempotently create the treasury wallet and token-supply singleton.

    Also seeds a default fee policy (250 bps = 2.5 %) if none exists.

    Safe to call multiple times; subsequent calls return the existing wallet.
    """
    async with transaction() as conn:
        # ── Treasury wallet ───────────────────────────────────────────────────
        existing = await conn.fetchrow(
            """
            SELECT wallet_id, agent_id, balance, updated_at, wallet_type
            FROM   wallets
            WHERE  wallet_type = 'treasury'
            """
        )
        if existing:
            wallet_row = existing
        else:
            wallet_row = await conn.fetchrow(
                """
                INSERT INTO wallets (wallet_type, balance)
                VALUES ('treasury', 0)
                RETURNING wallet_id, agent_id, balance, updated_at, wallet_type
                """
            )

        # ── Token supply singleton ─────────────────────────────────────────────
        supply_exists = await conn.fetchval("SELECT 1 FROM token_supply LIMIT 1")
        if not supply_exists:
            await conn.execute(
                "INSERT INTO token_supply (total_minted, total_burned) VALUES (0, 0)"
            )

        # ── Default fee policy (2.5 %) ─────────────────────────────────────────
        await conn.execute(
            """
            INSERT INTO fee_policies (name, rate_bps, active)
            VALUES ('default', 250, TRUE)
            ON CONFLICT (name) DO NOTHING
            """
        )

    return _row_to_wallet(dict(wallet_row))


# ── Supply management ─────────────────────────────────────────────────────────

async def mint_tokens(amount: int, reason: str = "mint") -> TokenSupplyResponse:
    """
    Mint *amount* new tokens: credit treasury wallet + update token_supply.

    Raises:
        ValueError: treasury or token_supply not initialised.
    """
    async with transaction() as conn:
        treasury_id = await _get_treasury_wallet_id(conn)
        if treasury_id is None:
            raise ValueError(
                "Treasury not initialised. Call initialize_treasury() first."
            )

        # Credit treasury wallet
        await conn.execute(
            """
            UPDATE wallets
               SET balance    = balance + $1,
                   updated_at = CURRENT_TIMESTAMP
             WHERE wallet_id = $2
            """,
            amount,
            treasury_id,
        )

        # Update supply singleton
        supply_row = await conn.fetchrow(
            """
            UPDATE token_supply
               SET total_minted = total_minted + $1,
                   updated_at   = CURRENT_TIMESTAMP
            RETURNING supply_id, total_minted, total_burned, updated_at
            """,
            amount,
        )
        if supply_row is None:
            raise ValueError(
                "Token supply not initialised. Call initialize_treasury() first."
            )

        # Ledger entry: NULL (mint) → treasury
        await _record_transaction(
            conn,
            from_wallet=None,
            to_wallet=treasury_id,
            amount=amount,
            tx_type=reason,
        )

    logger.info("economy_service: minted %d tokens (%s)", amount, reason)
    return _row_to_supply(supply_row)


# ── Fee collection ────────────────────────────────────────────────────────────

async def collect_task_fee(task_id: UUID, escrow_amount: int) -> int:
    """
    Calculate and collect the platform fee for a task.

    Looks up the active fee policy, calculates fee = escrow_amount * rate_bps // 10_000,
    credits the treasury wallet, reduces tasks.escrowed_reward by the fee,
    and updates tasks.task_fee.

    Returns the fee actually collected (0 if no treasury / no policy / zero rate).
    """
    if escrow_amount <= 0:
        return 0

    async with transaction() as conn:
        policy = await conn.fetchrow(
            "SELECT rate_bps FROM fee_policies WHERE active = TRUE LIMIT 1"
        )
        if policy is None or policy["rate_bps"] == 0:
            return 0

        fee = escrow_amount * policy["rate_bps"] // 10_000
        if fee <= 0:
            return 0

        treasury_id = await _get_treasury_wallet_id(conn)
        if treasury_id is None:
            return 0

        # Credit treasury
        await conn.execute(
            """
            UPDATE wallets
               SET balance    = balance + $1,
                   updated_at = CURRENT_TIMESTAMP
             WHERE wallet_id = $2
            """,
            fee,
            treasury_id,
        )

        # Reduce task escrow and track fee
        await conn.execute(
            """
            UPDATE tasks
               SET escrowed_reward = GREATEST(escrowed_reward - $1, 0),
                   task_fee        = task_fee + $1
             WHERE task_id = $2
            """,
            fee,
            task_id,
        )

        # Ledger entry: NULL (escrow) → treasury
        await _record_transaction(
            conn,
            from_wallet=None,
            to_wallet=treasury_id,
            amount=fee,
            tx_type="fee",
            related_id=task_id,
        )

    logger.debug(
        "economy_service: collected fee %d for task %s", fee, task_id
    )
    return fee


# ── Stake slashing ────────────────────────────────────────────────────────────

async def slash_stake(stake_id: UUID, reason: str = "") -> StakeSlashResponse:
    """
    Slash a stake: forfeit the full amount to the treasury and mark as released.

    Raises:
        ValueError: stake not found or already released/slashed.
    """
    async with transaction() as conn:
        stake = await conn.fetchrow(
            """
            SELECT stake_id, agent_id, amount, released_at
            FROM   stakes
            WHERE  stake_id = $1
            """,
            stake_id,
        )
        if stake is None:
            raise ValueError(f"Stake not found: {stake_id}")
        if stake["released_at"] is not None:
            raise ValueError(f"Stake already released or slashed: {stake_id}")

        # Mark stake as released (slash = forced release)
        await conn.execute(
            "UPDATE stakes SET released_at = CURRENT_TIMESTAMP WHERE stake_id = $1",
            stake_id,
        )

        # Credit treasury (if initialised)
        treasury_id = await _get_treasury_wallet_id(conn)
        if treasury_id:
            await conn.execute(
                """
                UPDATE wallets
                   SET balance    = balance + $1,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE wallet_id = $2
                """,
                stake["amount"],
                treasury_id,
            )
            await _record_transaction(
                conn,
                from_wallet=None,
                to_wallet=treasury_id,
                amount=stake["amount"],
                tx_type="slash",
                related_id=stake_id,
            )

        # Immutable slash record
        slash_row = await conn.fetchrow(
            """
            INSERT INTO stake_slashes (stake_id, agent_id, amount, reason)
            VALUES ($1, $2, $3, $4)
            RETURNING slash_id, stake_id, agent_id, amount, reason, created_at
            """,
            stake_id,
            stake["agent_id"],
            stake["amount"],
            reason or None,
        )

    logger.info(
        "economy_service: slashed stake %s (amount=%d, agent=%s)",
        stake_id, stake["amount"], stake["agent_id"],
    )
    return _row_to_slash(slash_row)


# ── Metrics snapshot ──────────────────────────────────────────────────────────

async def record_metrics() -> EconomicMetricsResponse:
    """
    Take an economic snapshot and persist it to economic_metrics.

    Computes:
      total_supply     — total_minted from token_supply (0 if not initialised)
      treasury_balance — current treasury wallet balance (0 if none)
      total_staked     — SUM of unreleased stakes
      active_tasks     — COUNT of tasks with status IN ('open', 'assigned')
      fees_collected   — SUM of task_fee across all tasks
    """
    async with transaction() as conn:
        # Total supply
        supply_row = await conn.fetchrow(
            "SELECT total_minted FROM token_supply LIMIT 1"
        )
        total_supply = supply_row["total_minted"] if supply_row else 0

        # Treasury balance
        treasury_row = await conn.fetchrow(
            "SELECT balance FROM wallets WHERE wallet_type = 'treasury'"
        )
        treasury_balance = treasury_row["balance"] if treasury_row else 0

        # Total staked
        total_staked = await conn.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM stakes WHERE released_at IS NULL"
        ) or 0

        # Active tasks
        active_tasks = await conn.fetchval(
            "SELECT COUNT(*) FROM tasks WHERE status IN ('open', 'assigned')"
        ) or 0

        # Fees collected
        fees_collected = await conn.fetchval(
            "SELECT COALESCE(SUM(task_fee), 0) FROM tasks"
        ) or 0

        # Insert snapshot
        row = await conn.fetchrow(
            """
            INSERT INTO economic_metrics
                (total_supply, treasury_balance, total_staked, active_tasks, fees_collected)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING
                metric_id, total_supply, treasury_balance,
                total_staked, active_tasks, fees_collected, recorded_at
            """,
            total_supply,
            treasury_balance,
            total_staked,
            active_tasks,
            fees_collected,
        )

    return _row_to_metrics(row)


async def get_latest_metrics() -> EconomicMetricsResponse | None:
    """Return the most recent economic snapshot, or None if none recorded yet."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT metric_id, total_supply, treasury_balance,
                   total_staked, active_tasks, fees_collected, recorded_at
            FROM   economic_metrics
            ORDER BY recorded_at DESC
            LIMIT  1
            """
        )
    if row is None:
        return None
    return _row_to_metrics(row)


async def get_treasury_balance() -> WalletResponse:
    """Return the treasury wallet, or raise ValueError if not initialised."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT wallet_id, agent_id, balance, updated_at, wallet_type
            FROM   wallets
            WHERE  wallet_type = 'treasury'
            """
        )
    if row is None:
        raise ValueError(
            "Treasury not initialised. Call initialize_treasury() first."
        )
    return _row_to_wallet(dict(row))
