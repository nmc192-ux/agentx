"""
AgentX Platform — Token Economy Service
════════════════════════════════════════
Phase 8: Native token currency.

Public API
──────────
  create_wallet(agent_id, initial_balance)  → WalletResponse
  get_wallet(agent_id)                      → WalletResponse
  get_balance(agent_id)                     → int
  transfer_tokens(from_id, to_id, amount, tx_type, related_id) → TransactionResponse
  stake_tokens(agent_id, amount, locked_until)  → StakeResponse
  release_stake(stake_id, caller_agent_id)  → WalletResponse
  get_transactions(agent_id, limit)         → list[TransactionResponse]
  get_stakes(agent_id)                      → list[StakeResponse]

Internal helpers (used by task_service)
────────────────────────────────────────
  escrow_task_reward(agent_id, task_id, amount)   → None
  release_task_escrow(task_id, executor_agent_id) → int  (amount released)
  refund_task_escrow(task_id, creator_agent_id)   → int  (amount refunded)
  Each takes ``conn=`` to run inside the caller's transaction, which is how
  task_service uses them: a task and its money commit or roll back together.

All DB access uses asyncpg via get_db() / transaction() context managers.
Atomic debit is performed with ``WHERE balance >= $amount RETURNING wallet_id``
so a failed RETURNING means insufficient funds without a separate SELECT.

Sprint 9 (S9-7a) — money rules
──────────────────────────────
• Tokens are created in two places only, both FOUNDER-only at the router and
  both written to the ledger and to token_supply.total_minted: a founder
  grant (``create_wallet`` with initial_balance > 0, type='grant') and a
  treasury mint (``economy_service.mint_tokens``, type='mint').
• A stake leaves in two ways only, each with the stake row locked
  (``FOR UPDATE``) so it happens once: back to its owner (``release_stake``)
  or to the treasury (``economy_service.slash_stake``).
• Errors: PermissionError → 403, StakeConflictError → 409, other ValueError
  → 400 (404 for "not found").
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from ..database import get_db, transaction
from ..models.token import (
    StakeResponse,
    TransactionResponse,
    WalletResponse,
)

logger = logging.getLogger(__name__)


class StakeConflictError(ValueError):
    """The stake is not in a state that allows the action (HTTP 409)."""


class InsufficientFundsError(ValueError):
    """The paying wallet is missing or does not hold the amount (HTTP 400)."""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _row_to_wallet(row: Any) -> WalletResponse:
    return WalletResponse(
        wallet_id=row["wallet_id"],
        agent_id=row.get("agent_id"),           # Optional — None for treasury
        balance=row["balance"],
        updated_at=row["updated_at"],
        wallet_type=row.get("wallet_type", "agent"),  # Phase 8.5
    )


def _row_to_transaction(row: Any) -> TransactionResponse:
    return TransactionResponse(
        transaction_id=row["transaction_id"],
        from_wallet=row["from_wallet"],
        to_wallet=row["to_wallet"],
        amount=row["amount"],
        type=row["type"],
        related_id=row["related_id"],
        timestamp=row["timestamp"],
    )


def _row_to_stake(row: Any) -> StakeResponse:
    return StakeResponse(
        stake_id=row["stake_id"],
        agent_id=row["agent_id"],
        amount=row["amount"],
        locked_until=row["locked_until"],
        released_at=row["released_at"],
        created_at=row["created_at"],
    )


async def _record_transaction(
    conn,
    *,
    from_wallet: UUID | None,
    to_wallet: UUID | None,
    amount: int,
    tx_type: str,
    related_id: UUID | None = None,
) -> TransactionResponse:
    """Insert an immutable ledger entry. NULL from/to = system/escrow."""
    row = await conn.fetchrow(
        """
        INSERT INTO transactions
            (from_wallet, to_wallet, amount, type, related_id)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING
            transaction_id, from_wallet, to_wallet, amount, type, related_id, timestamp
        """,
        from_wallet,
        to_wallet,
        amount,
        tx_type,
        related_id,
    )
    return _row_to_transaction(row)


# ── Wallet operations ─────────────────────────────────────────────────────────

async def create_wallet(
    agent_id: UUID,
    initial_balance: int = 0,
) -> WalletResponse:
    """
    Create a wallet for *agent_id*, or add *initial_balance* to an existing one.

    ON CONFLICT is idempotent: calling twice is safe and just credits the agent.

    A non-zero *initial_balance* creates tokens (a founder grant — the router
    only lets a FOUNDER pass one). It is written to the ledger (NULL → wallet,
    type='grant') and added to token_supply.total_minted in the same
    transaction, so no token exists without a record.
    """
    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO wallets (agent_id, balance)
            VALUES ($1, $2)
            ON CONFLICT (agent_id) DO UPDATE
                SET balance    = wallets.balance + EXCLUDED.balance,
                    updated_at = CURRENT_TIMESTAMP
            RETURNING wallet_id, agent_id, balance, updated_at
            """,
            agent_id,
            initial_balance,
        )
        if initial_balance > 0:
            await conn.execute(
                """
                UPDATE token_supply
                   SET total_minted = total_minted + $1,
                       updated_at   = CURRENT_TIMESTAMP
                """,
                initial_balance,
            )
            await _record_transaction(
                conn,
                from_wallet=None,
                to_wallet=row["wallet_id"],
                amount=initial_balance,
                tx_type="grant",
            )
            logger.info(
                "token_service: granted %d tokens to agent %s", initial_balance, agent_id
            )
    return _row_to_wallet(row)


async def get_wallet(agent_id: UUID) -> WalletResponse:
    """Return the wallet for *agent_id*, or raise ValueError if not found."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT wallet_id, agent_id, balance, updated_at
            FROM   wallets
            WHERE  agent_id = $1
            """,
            agent_id,
        )
    if row is None:
        raise ValueError(f"Wallet not found for agent: {agent_id}")
    return _row_to_wallet(row)


async def get_balance(agent_id: UUID) -> int:
    """Return the token balance for *agent_id*, or raise ValueError."""
    wallet = await get_wallet(agent_id)
    return wallet.balance


# ── Transfer ──────────────────────────────────────────────────────────────────

async def transfer_tokens(
    from_agent_id: UUID,
    to_agent_id: UUID,
    amount: int,
    tx_type: str = "transfer",
    related_id: UUID | None = None,
) -> TransactionResponse:
    """
    Atomically transfer *amount* tokens from one agent's wallet to another.

    Raises:
        ValueError: if either wallet does not exist, sender has insufficient
                    funds, or sender and receiver are the same agent.
    """
    if from_agent_id == to_agent_id:
        raise ValueError("Cannot transfer tokens to your own wallet")

    async with transaction() as conn:
        # Lock both wallets in one fixed order (by wallet_id) before touching
        # either. Without this, A→B and B→A at the same moment each hold one
        # row and wait for the other: Postgres kills one with a deadlock error.
        await conn.execute(
            """
            SELECT wallet_id FROM wallets
             WHERE agent_id = ANY($1::uuid[])
             ORDER BY wallet_id
               FOR UPDATE
            """,
            [from_agent_id, to_agent_id],
        )

        # ── Debit sender (atomic: only succeeds when balance >= amount) ────────
        debit_row = await conn.fetchrow(
            """
            UPDATE wallets
               SET balance    = balance - $1,
                   updated_at = CURRENT_TIMESTAMP
             WHERE agent_id = $2
               AND balance  >= $1
            RETURNING wallet_id
            """,
            amount,
            from_agent_id,
        )
        if debit_row is None:
            # Distinguish between "wallet missing" and "insufficient funds"
            exists = await conn.fetchval(
                "SELECT 1 FROM wallets WHERE agent_id = $1", from_agent_id
            )
            if not exists:
                raise ValueError(f"Sender wallet not found for agent: {from_agent_id}")
            raise ValueError(
                f"Insufficient funds: agent {from_agent_id} cannot transfer {amount} tokens"
            )

        from_wallet_id: UUID = debit_row["wallet_id"]

        # ── Credit receiver ───────────────────────────────────────────────────
        credit_row = await conn.fetchrow(
            """
            UPDATE wallets
               SET balance    = balance + $1,
                   updated_at = CURRENT_TIMESTAMP
             WHERE agent_id = $2
            RETURNING wallet_id
            """,
            amount,
            to_agent_id,
        )
        if credit_row is None:
            raise ValueError(f"Receiver wallet not found for agent: {to_agent_id}")

        to_wallet_id: UUID = credit_row["wallet_id"]

        # ── Ledger entry ──────────────────────────────────────────────────────
        tx = await _record_transaction(
            conn,
            from_wallet=from_wallet_id,
            to_wallet=to_wallet_id,
            amount=amount,
            tx_type=tx_type,
            related_id=related_id,
        )

    return tx


# ── Staking ───────────────────────────────────────────────────────────────────

async def stake_tokens(
    agent_id: UUID,
    amount: int,
    locked_until: datetime | None = None,
) -> StakeResponse:
    """
    Lock *amount* tokens from the agent's wallet into a stake record.

    Raises:
        ValueError: if wallet not found or insufficient funds.
    """
    async with transaction() as conn:
        # Debit wallet
        debit_row = await conn.fetchrow(
            """
            UPDATE wallets
               SET balance    = balance - $1,
                   updated_at = CURRENT_TIMESTAMP
             WHERE agent_id = $2
               AND balance  >= $1
            RETURNING wallet_id
            """,
            amount,
            agent_id,
        )
        if debit_row is None:
            exists = await conn.fetchval(
                "SELECT 1 FROM wallets WHERE agent_id = $1", agent_id
            )
            if not exists:
                raise ValueError(f"Wallet not found for agent: {agent_id}")
            raise ValueError(
                f"Insufficient funds: agent {agent_id} cannot stake {amount} tokens"
            )

        # Create stake record
        stake_row = await conn.fetchrow(
            """
            INSERT INTO stakes (agent_id, amount, locked_until)
            VALUES ($1, $2, $3)
            RETURNING stake_id, agent_id, amount, locked_until, released_at, created_at
            """,
            agent_id,
            amount,
            locked_until,
        )

        # Ledger entry: from_wallet → NULL (staked/locked)
        await _record_transaction(
            conn,
            from_wallet=debit_row["wallet_id"],
            to_wallet=None,
            amount=amount,
            tx_type="stake",
            related_id=stake_row["stake_id"],
        )

    return _row_to_stake(stake_row)


async def release_stake(stake_id: UUID, caller_agent_id: UUID) -> WalletResponse:
    """
    Release a stake back to its owner: credits the owner's wallet and sets
    released_at.

    Only the stake's owner may release it, and not before ``locked_until``.
    The stake row is locked (``FOR UPDATE``) before ``released_at`` is read, so
    two concurrent releases (or a release racing a slash) cannot both see it
    unreleased: the second waits for the first to commit, then is refused.

    Raises:
        ValueError:         stake not found.
        PermissionError:    caller does not own the stake.
        StakeConflictError: already released / slashed, or still locked.
    """
    async with transaction() as conn:
        stake_row = await conn.fetchrow(
            """
            SELECT stake_id, agent_id, amount, released_at,
                   (locked_until IS NOT NULL
                    AND locked_until > CURRENT_TIMESTAMP) AS still_locked
            FROM   stakes
            WHERE  stake_id = $1
            FOR UPDATE
            """,
            stake_id,
        )
        if stake_row is None:
            raise ValueError(f"Stake not found: {stake_id}")
        if stake_row["agent_id"] != caller_agent_id:
            raise PermissionError("Only the stake's owner can release it")
        if stake_row["released_at"] is not None:
            raise StakeConflictError(f"Stake already released or slashed: {stake_id}")
        if stake_row["still_locked"]:
            raise StakeConflictError(
                f"Stake is locked until its lock period ends: {stake_id}"
            )

        agent_id: UUID = stake_row["agent_id"]
        amount: int = stake_row["amount"]

        # Mark stake as released
        await conn.execute(
            "UPDATE stakes SET released_at = CURRENT_TIMESTAMP WHERE stake_id = $1",
            stake_id,
        )

        # Credit wallet
        wallet_row = await conn.fetchrow(
            """
            UPDATE wallets
               SET balance    = balance + $1,
                   updated_at = CURRENT_TIMESTAMP
             WHERE agent_id = $2
            RETURNING wallet_id, agent_id, balance, updated_at
            """,
            amount,
            agent_id,
        )
        if wallet_row is None:
            raise ValueError(f"Wallet not found for agent: {agent_id}")

        # Ledger entry: NULL (unstake) → wallet
        await _record_transaction(
            conn,
            from_wallet=None,
            to_wallet=wallet_row["wallet_id"],
            amount=amount,
            tx_type="unstake",
            related_id=stake_id,
        )

    return _row_to_wallet(wallet_row)


# ── History queries ───────────────────────────────────────────────────────────

async def get_transactions(
    agent_id: UUID,
    limit: int = 50,
) -> list[TransactionResponse]:
    """Return the most recent *limit* transactions where the agent is sender or receiver."""
    async with get_db() as conn:
        # Look up wallet_id for the agent
        wallet_id = await conn.fetchval(
            "SELECT wallet_id FROM wallets WHERE agent_id = $1", agent_id
        )
        if wallet_id is None:
            return []

        rows = await conn.fetch(
            """
            SELECT transaction_id, from_wallet, to_wallet, amount, type, related_id, timestamp
            FROM   transactions
            WHERE  from_wallet = $1 OR to_wallet = $1
            ORDER BY timestamp DESC
            LIMIT  $2
            """,
            wallet_id,
            limit,
        )

    return [_row_to_transaction(r) for r in rows]


async def get_stakes(agent_id: UUID) -> list[StakeResponse]:
    """Return all unreleased (active) stakes for *agent_id*."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT stake_id, agent_id, amount, locked_until, released_at, created_at
            FROM   stakes
            WHERE  agent_id    = $1
              AND  released_at IS NULL
            ORDER BY created_at DESC
            """,
            agent_id,
        )
    return [_row_to_stake(r) for r in rows]


# ── Task-escrow helpers (called by task_service) ──────────────────────────────

async def escrow_task_reward(
    creator_agent_id: UUID,
    task_id: UUID,
    amount: int,
    conn=None,
) -> None:
    """
    Lock *amount* tokens from the creator's wallet into task escrow.

    Debits the creator's wallet and increments tasks.escrowed_reward.
    Records a ledger entry with type="escrow" and related_id=task_id.

    Pass *conn* to run inside the caller's transaction, so that creating the
    task and funding it commit (or roll back) together.

    Raises:
        InsufficientFundsError: no wallet, or the wallet does not hold *amount*.
    """
    if amount <= 0:
        return

    if conn is not None:
        await _escrow_task_reward(conn, creator_agent_id, task_id, amount)
    else:
        async with transaction() as own_conn:
            await _escrow_task_reward(own_conn, creator_agent_id, task_id, amount)

    logger.debug(
        "token_service: escrowed %d tokens for task %s from agent %s",
        amount, task_id, creator_agent_id,
    )


async def _escrow_task_reward(
    conn,
    creator_agent_id: UUID,
    task_id: UUID,
    amount: int,
) -> None:
    # Debit creator wallet
    debit_row = await conn.fetchrow(
        """
        UPDATE wallets
           SET balance    = balance - $1,
               updated_at = CURRENT_TIMESTAMP
         WHERE agent_id = $2
           AND balance  >= $1
        RETURNING wallet_id
        """,
        amount,
        creator_agent_id,
    )
    if debit_row is None:
        exists = await conn.fetchval(
            "SELECT 1 FROM wallets WHERE agent_id = $1", creator_agent_id
        )
        if not exists:
            raise InsufficientFundsError(
                f"Insufficient funds: agent {creator_agent_id} has no wallet "
                f"to escrow {amount} tokens from"
            )
        raise InsufficientFundsError(
            f"Insufficient funds: agent {creator_agent_id} cannot escrow {amount} tokens"
        )

    # Track escrowed amount on the task
    await conn.execute(
        """
        UPDATE tasks
           SET escrowed_reward = escrowed_reward + $1
         WHERE task_id = $2
        """,
        amount,
        task_id,
    )

    # Ledger entry: creator wallet → NULL (held in escrow)
    await _record_transaction(
        conn,
        from_wallet=debit_row["wallet_id"],
        to_wallet=None,
        amount=amount,
        tx_type="escrow",
        related_id=task_id,
    )


async def _settle_task_escrow(
    conn,
    task_id: UUID,
    payee_agent_id: UUID,
    tx_type: str,
) -> int:
    """
    Pay a task's whole escrow to *payee_agent_id* inside the caller's
    transaction. Returns the amount paid (0 if nothing was escrowed).

    The task row is locked (``FOR UPDATE``) before ``escrowed_reward`` is read,
    so two concurrent settlements cannot both see a non-zero escrow: the second
    waits for the first to commit, then reads 0 and pays nothing.

    The payee's wallet is created if missing — the tokens come out of escrow,
    so this mints nothing — otherwise an agent with no wallet could never be
    paid and the escrow would be stuck for good.
    """
    escrowed = await conn.fetchval(
        "SELECT escrowed_reward FROM tasks WHERE task_id = $1 FOR UPDATE",
        task_id,
    )
    if not escrowed:
        return 0

    wallet_row = await conn.fetchrow(
        """
        INSERT INTO wallets (agent_id, balance)
        VALUES ($2, $1)
        ON CONFLICT (agent_id) DO UPDATE
            SET balance    = wallets.balance + EXCLUDED.balance,
                updated_at = CURRENT_TIMESTAMP
        RETURNING wallet_id
        """,
        escrowed,
        payee_agent_id,
    )

    await conn.execute(
        "UPDATE tasks SET escrowed_reward = 0 WHERE task_id = $1",
        task_id,
    )

    # Ledger entry: NULL (escrow) → payee wallet
    await _record_transaction(
        conn,
        from_wallet=None,
        to_wallet=wallet_row["wallet_id"],
        amount=escrowed,
        tx_type=tx_type,
        related_id=task_id,
    )
    return escrowed


async def release_task_escrow(
    task_id: UUID,
    executor_agent_id: UUID,
    conn=None,
) -> int:
    """
    Release escrowed task reward to the executor's wallet.

    Locks the task row, reads tasks.escrowed_reward, credits the executor's
    wallet, zeroes the escrowed_reward, and records a ledger entry
    (type='escrow_release'). Returns the amount released; 0 if the task had no
    escrow (or it was already paid out).

    Pass *conn* to run inside the caller's transaction, so that completing the
    task and paying for it commit (or roll back) together.
    """
    if conn is not None:
        released = await _settle_task_escrow(
            conn, task_id, executor_agent_id, "escrow_release"
        )
    else:
        async with transaction() as own_conn:
            released = await _settle_task_escrow(
                own_conn, task_id, executor_agent_id, "escrow_release"
            )

    if released:
        logger.debug(
            "token_service: released %d tokens from escrow for task %s to agent %s",
            released, task_id, executor_agent_id,
        )
    return released


# ── Refund task escrow to creator (on task failure) ──────────────────────────

async def refund_task_escrow(
    task_id: UUID,
    creator_agent_id: UUID,
    conn=None,
) -> int:
    """
    Refund escrowed task reward back to the creator (used when the creator
    cancels a task nobody took).

    Same locking as release_task_escrow; the ledger entry has
    type='escrow_refund'. Returns the amount refunded (0 if nothing escrowed).

    Pass *conn* to run inside the caller's transaction, so that cancelling the
    task and refunding it commit (or roll back) together.
    """
    if conn is not None:
        refunded = await _settle_task_escrow(
            conn, task_id, creator_agent_id, "escrow_refund"
        )
    else:
        async with transaction() as own_conn:
            refunded = await _settle_task_escrow(
                own_conn, task_id, creator_agent_id, "escrow_refund"
            )

    if refunded:
        logger.debug(
            "token_service: refunded %d tokens from escrow for task %s to creator %s",
            refunded, task_id, creator_agent_id,
        )
    return refunded


# ── Phase 8.5: Treasury-aware operations ─────────────────────────────────────

async def _get_treasury_wallet_id(conn) -> UUID | None:
    """Return the treasury wallet_id, or None if treasury hasn't been initialised."""
    return await conn.fetchval(
        "SELECT wallet_id FROM wallets WHERE wallet_type = 'treasury'"
    )


async def transfer_with_fee(
    from_agent_id: UUID,
    to_agent_id: UUID,
    amount: int,
    fee_bps: int = 0,
    tx_type: str = "transfer",
    related_id: UUID | None = None,
) -> TransactionResponse:
    """
    Transfer *amount* tokens from sender to receiver, deducting a fee that
    goes to the treasury wallet.

    Sender is debited *amount* in full.
    Receiver is credited *amount - fee*.
    Treasury is credited *fee*.

    fee = amount * fee_bps // 10000  (integer floor division)

    Raises:
        ValueError: wallet not found or insufficient funds.
    """
    fee = amount * fee_bps // 10000
    net = amount - fee

    async with transaction() as conn:
        # ── Debit sender (atomic) ─────────────────────────────────────────────
        debit_row = await conn.fetchrow(
            """
            UPDATE wallets
               SET balance    = balance - $1,
                   updated_at = CURRENT_TIMESTAMP
             WHERE agent_id = $2
               AND balance  >= $1
            RETURNING wallet_id
            """,
            amount,
            from_agent_id,
        )
        if debit_row is None:
            exists = await conn.fetchval(
                "SELECT 1 FROM wallets WHERE agent_id = $1", from_agent_id
            )
            if not exists:
                raise ValueError(f"Sender wallet not found for agent: {from_agent_id}")
            raise ValueError(
                f"Insufficient funds: agent {from_agent_id} cannot transfer {amount} tokens"
            )

        from_wallet_id: UUID = debit_row["wallet_id"]

        # ── Credit receiver ───────────────────────────────────────────────────
        credit_net = net if net > 0 else 0
        credit_row = await conn.fetchrow(
            """
            UPDATE wallets
               SET balance    = balance + $1,
                   updated_at = CURRENT_TIMESTAMP
             WHERE agent_id = $2
            RETURNING wallet_id
            """,
            credit_net,
            to_agent_id,
        )
        if credit_row is None:
            raise ValueError(f"Receiver wallet not found for agent: {to_agent_id}")

        to_wallet_id: UUID = credit_row["wallet_id"]

        # ── Credit treasury with fee ──────────────────────────────────────────
        if fee > 0:
            treasury_id = await _get_treasury_wallet_id(conn)
            if treasury_id:
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
                await _record_transaction(
                    conn,
                    from_wallet=from_wallet_id,
                    to_wallet=treasury_id,
                    amount=fee,
                    tx_type="fee",
                    related_id=related_id,
                )

        # ── Main ledger entry ─────────────────────────────────────────────────
        tx = await _record_transaction(
            conn,
            from_wallet=from_wallet_id,
            to_wallet=to_wallet_id,
            amount=credit_net or amount,
            tx_type=tx_type,
            related_id=related_id,
        )

    return tx


async def treasury_deposit(
    amount: int,
    reason: str = "deposit",
    related_id: UUID | None = None,
) -> TransactionResponse:
    """
    Deposit *amount* tokens into the treasury from the system (minting path).
    Creates a ledger entry with from_wallet = NULL.

    Raises:
        ValueError: if treasury not initialised.
    """
    async with transaction() as conn:
        treasury_id = await _get_treasury_wallet_id(conn)
        if treasury_id is None:
            raise ValueError("Treasury not initialised; call initialize_treasury() first")

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

        tx = await _record_transaction(
            conn,
            from_wallet=None,
            to_wallet=treasury_id,
            amount=amount,
            tx_type=reason,
            related_id=related_id,
        )

    return tx


async def treasury_withdraw(
    amount: int,
    reason: str = "withdraw",
    related_id: UUID | None = None,
) -> TransactionResponse:
    """
    Withdraw *amount* tokens from the treasury into the system (burning path).
    Creates a ledger entry with to_wallet = NULL.

    Raises:
        ValueError: treasury not initialised or insufficient funds.
    """
    async with transaction() as conn:
        treasury_row = await conn.fetchrow(
            """
            UPDATE wallets
               SET balance    = balance - $1,
                   updated_at = CURRENT_TIMESTAMP
             WHERE wallet_type = 'treasury'
               AND balance    >= $1
            RETURNING wallet_id
            """,
            amount,
        )
        if treasury_row is None:
            exists = await conn.fetchval(
                "SELECT 1 FROM wallets WHERE wallet_type = 'treasury'"
            )
            if not exists:
                raise ValueError("Treasury not initialised")
            raise ValueError(
                f"Treasury has insufficient funds to withdraw {amount} tokens"
            )

        tx = await _record_transaction(
            conn,
            from_wallet=treasury_row["wallet_id"],
            to_wallet=None,
            amount=amount,
            tx_type=reason,
            related_id=related_id,
        )

    return tx
