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
  refund_task_fee(conn, task_id, creator_id)    → int   (fee given back on cancel)
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
• Sprint 9 (S9-7a): minting and slashing are FOUNDER-only at the router. A
  mint is always written to the ledger as type='mint' (the caller's reason
  is logged, never used as the ledger label). A slash locks the stake row,
  so a stake is forfeited once, and is refused if there is no treasury to
  receive it. The task fee is taken from the escrow that is really there.
• Sprint 9 (S9-7b): the task fee is collected in the transaction that
  creates and funds the task, and given back (treasury → creator) in the
  transaction that cancels a task nobody took.
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
from .token_service import (
    StakeConflictError,
    _get_treasury_wallet_id,
    _record_transaction,
    _row_to_wallet,
)

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

    The ledger entry is always type='mint'. *reason* is free text from the
    caller; it is logged, not stored as the type, so a mint can never be
    passed off in the ledger as an escrow release, a fee or a transfer.

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
            tx_type="mint",
        )

    logger.info("economy_service: minted %d tokens (reason: %r)", amount, reason)
    return _row_to_supply(supply_row)


# ── Fee collection ────────────────────────────────────────────────────────────

async def collect_task_fee(task_id: UUID, escrow_amount: int, conn=None) -> int:
    """
    Calculate and collect the platform fee for a task.

    Looks up the active fee policy, calculates fee = escrow_amount * rate_bps // 10_000,
    credits the treasury wallet, reduces tasks.escrowed_reward by the fee,
    and updates tasks.task_fee.

    Pass *conn* to run inside the caller's transaction (task_service.create_task
    does: the task, its escrow and its fee are one transaction).

    Returns the fee actually collected (0 if no treasury / no policy / zero rate).
    """
    if escrow_amount <= 0:
        return 0

    if conn is not None:
        fee = await _collect_task_fee(conn, task_id, escrow_amount)
    else:
        async with transaction() as own_conn:
            fee = await _collect_task_fee(own_conn, task_id, escrow_amount)

    if fee:
        logger.debug(
            "economy_service: collected fee %d for task %s", fee, task_id
        )
    return fee


async def _collect_task_fee(conn, task_id: UUID, escrow_amount: int) -> int:
    policy = await conn.fetchrow(
        "SELECT rate_bps FROM fee_policies WHERE active = TRUE LIMIT 1"
    )
    if policy is None or policy["rate_bps"] == 0:
        return 0

    # The fee comes out of the task's escrow, so charge it on what is in
    # escrow now, with the row locked — not on the amount the caller
    # remembers. If the escrow has already been paid out, there is nothing
    # to take, and crediting the treasury anyway would create tokens.
    in_escrow = await conn.fetchval(
        "SELECT escrowed_reward FROM tasks WHERE task_id = $1 FOR UPDATE",
        task_id,
    )
    fee = min(escrow_amount, in_escrow or 0) * policy["rate_bps"] // 10_000
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
           SET escrowed_reward = escrowed_reward - $1,
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
    return fee


async def refund_task_fee(conn, task_id: UUID, creator_agent_id: UUID) -> int:
    """
    Give a cancelled task's platform fee back to its creator, inside the
    caller's transaction. Returns the amount refunded.

    The caller must already hold the task's row lock (task_service.cancel_task
    does), so ``task_fee`` is read and zeroed once however many cancels race.
    The fee moves treasury → creator wallet (ledger type='fee_refund'); the
    treasury debit is guarded (``balance >= fee``), so a refund can never take
    the treasury below zero or create tokens. If the treasury cannot cover it,
    nothing is refunded and ``task_fee`` is left as it is — the cancel itself
    still goes through.
    """
    fee = await conn.fetchval(
        "SELECT task_fee FROM tasks WHERE task_id = $1", task_id
    )
    if not fee or fee <= 0:
        return 0

    treasury_id = await conn.fetchval(
        """
        UPDATE wallets
           SET balance    = balance - $1,
               updated_at = CURRENT_TIMESTAMP
         WHERE wallet_type = 'treasury'
           AND balance    >= $1
        RETURNING wallet_id
        """,
        fee,
    )
    if treasury_id is None:
        logger.warning(
            "economy_service: treasury cannot refund fee %d for task %s; fee kept",
            fee, task_id,
        )
        return 0

    creator_wallet_id = await conn.fetchval(
        """
        INSERT INTO wallets (agent_id, balance)
        VALUES ($2, $1)
        ON CONFLICT (agent_id) DO UPDATE
            SET balance    = wallets.balance + EXCLUDED.balance,
                updated_at = CURRENT_TIMESTAMP
        RETURNING wallet_id
        """,
        fee,
        creator_agent_id,
    )

    await conn.execute(
        "UPDATE tasks SET task_fee = 0 WHERE task_id = $1", task_id
    )

    await _record_transaction(
        conn,
        from_wallet=treasury_id,
        to_wallet=creator_wallet_id,
        amount=fee,
        tx_type="fee_refund",
        related_id=task_id,
    )
    return fee


# ── Stake slashing ────────────────────────────────────────────────────────────

async def slash_stake(stake_id: UUID, reason: str = "") -> StakeSlashResponse:
    """
    Slash a stake: forfeit the full amount to the treasury and mark as released.

    The stake row is locked (``FOR UPDATE``) before ``released_at`` is read, so
    two concurrent slashes (or a slash racing the owner's release) cannot both
    see it unreleased — the treasury is credited once.

    Raises:
        ValueError:         stake not found, or no treasury to receive it (the
                            tokens would otherwise vanish without a record).
        StakeConflictError: stake already released or slashed.
    """
    async with transaction() as conn:
        stake = await conn.fetchrow(
            """
            SELECT stake_id, agent_id, amount, released_at
            FROM   stakes
            WHERE  stake_id = $1
            FOR UPDATE
            """,
            stake_id,
        )
        if stake is None:
            raise ValueError(f"Stake not found: {stake_id}")
        if stake["released_at"] is not None:
            raise StakeConflictError(f"Stake already released or slashed: {stake_id}")

        treasury_id = await _get_treasury_wallet_id(conn)
        if treasury_id is None:
            raise ValueError(
                "Treasury not initialised. Call initialize_treasury() first."
            )

        # Mark stake as released (slash = forced release)
        await conn.execute(
            "UPDATE stakes SET released_at = CURRENT_TIMESTAMP WHERE stake_id = $1",
            stake_id,
        )

        # Credit treasury
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
