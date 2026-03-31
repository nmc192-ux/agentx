"""
AgentX Platform — Token Settlement Engine & Escrow System
═════════════════════════════════════════════════════════
Phase 4+: Making rewards actually flow.

Core settlement functions:
  get_balance()       — query an agent's token balance
  transfer()          — atomic peer-to-peer token transfer
  mint()              — create new tokens (grants, rewards)
  escrow_hold()       — hold task reward funds from the creator
  escrow_release()    — release escrowed funds to executor on completion
  escrow_refund()     — refund escrowed funds on cancellation/failure

All operations are atomic via the existing transaction() context manager.
Escrow state is tracked in the escrow_holds table (migration 037).
"""
from __future__ import annotations

import logging
from uuid import UUID

from ..database import get_db, transaction

logger = logging.getLogger(__name__)


# ── Balance Queries ───────────────────────────────────────────────────────────

async def get_balance(agent_did: str, token_type: str) -> int:
    """
    Return the current balance for an agent and token type.

    Returns 0 if no balance row exists (agent has never received this token).
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT balance
            FROM token_balances
            WHERE agent_did = $1 AND token_type = $2::token_type
            """,
            agent_did,
            token_type,
        )
    return int(row["balance"]) if row else 0


# ── Minting ───────────────────────────────────────────────────────────────────

async def mint(
    agent_did: str,
    token_type: str,
    amount: int,
    tx_type: str = "MINT",
    reference_id: str | None = None,
) -> None:
    """
    Create tokens by crediting an agent's balance.

    Used for initial grants, platform rewards, and treasury distributions.
    Creates a token_transactions record with from_did = NULL (minted).
    """
    if amount <= 0:
        raise ValueError("Mint amount must be positive")

    async with transaction() as conn:
        # Upsert balance: create row if first mint, otherwise add
        await conn.execute(
            """
            INSERT INTO token_balances (agent_did, token_type, balance, updated_at)
            VALUES ($1, $2::token_type, $3, CURRENT_TIMESTAMP)
            ON CONFLICT (agent_did, token_type)
            DO UPDATE SET
                balance    = token_balances.balance + EXCLUDED.balance,
                updated_at = CURRENT_TIMESTAMP
            """,
            agent_did,
            token_type,
            amount,
        )

        # Record the minting transaction (from_did is NULL for mints)
        await conn.execute(
            """
            INSERT INTO token_transactions
                (tx_id, from_did, to_did, token_type, transaction_type, amount, reference_id)
            VALUES
                (gen_random_uuid(), NULL, $1, $2::token_type, $3::transaction_type, $4, $5)
            """,
            agent_did,
            token_type,
            tx_type,
            amount,
            reference_id,
        )

    logger.info(
        "Minted %d %s to %s (tx_type=%s, ref=%s)",
        amount, token_type, agent_did, tx_type, reference_id,
    )


# ── Transfers ─────────────────────────────────────────────────────────────────

async def transfer(
    from_did: str,
    to_did: str,
    token_type: str,
    amount: int,
    tx_type: str,
    reference_id: str | None = None,
) -> None:
    """
    Atomic peer-to-peer token transfer.

    Debits the sender and credits the receiver within a single DB transaction.
    Raises ValueError if the sender has insufficient balance.
    """
    if amount <= 0:
        raise ValueError("Transfer amount must be positive")
    if from_did == to_did:
        raise ValueError("Cannot transfer to self")

    async with transaction() as conn:
        # Lock sender row and check balance (SELECT ... FOR UPDATE)
        sender_row = await conn.fetchrow(
            """
            SELECT balance
            FROM token_balances
            WHERE agent_did = $1 AND token_type = $2::token_type
            FOR UPDATE
            """,
            from_did,
            token_type,
        )

        current_balance = int(sender_row["balance"]) if sender_row else 0
        if current_balance < amount:
            raise ValueError(
                f"Insufficient {token_type} balance: "
                f"{from_did} has {current_balance}, needs {amount}"
            )

        # Debit sender
        await conn.execute(
            """
            UPDATE token_balances
            SET balance = balance - $3, updated_at = CURRENT_TIMESTAMP
            WHERE agent_did = $1 AND token_type = $2::token_type
            """,
            from_did,
            token_type,
            amount,
        )

        # Credit receiver (upsert in case they have no balance row yet)
        await conn.execute(
            """
            INSERT INTO token_balances (agent_did, token_type, balance, updated_at)
            VALUES ($1, $2::token_type, $3, CURRENT_TIMESTAMP)
            ON CONFLICT (agent_did, token_type)
            DO UPDATE SET
                balance    = token_balances.balance + EXCLUDED.balance,
                updated_at = CURRENT_TIMESTAMP
            """,
            to_did,
            token_type,
            amount,
        )

        # Record the transaction
        await conn.execute(
            """
            INSERT INTO token_transactions
                (tx_id, from_did, to_did, token_type, transaction_type, amount, reference_id)
            VALUES
                (gen_random_uuid(), $1, $2, $3::token_type, $4::transaction_type, $5, $6)
            """,
            from_did,
            to_did,
            token_type,
            tx_type,
            amount,
            reference_id,
        )

    logger.info(
        "Transferred %d %s: %s -> %s (tx_type=%s, ref=%s)",
        amount, token_type, from_did, to_did, tx_type, reference_id,
    )


# ── Escrow ────────────────────────────────────────────────────────────────────

async def escrow_hold(
    task_id: UUID,
    from_did: str,
    token_type: str,
    amount: int,
) -> UUID:
    """
    Hold funds for a task by debiting the holder and creating an escrow record.

    Returns the escrow_id of the created hold.
    Raises ValueError if the holder has insufficient balance.
    """
    if amount <= 0:
        raise ValueError("Escrow amount must be positive")

    async with transaction() as conn:
        # Lock sender row and check balance
        sender_row = await conn.fetchrow(
            """
            SELECT balance
            FROM token_balances
            WHERE agent_did = $1 AND token_type = $2::token_type
            FOR UPDATE
            """,
            from_did,
            token_type,
        )

        current_balance = int(sender_row["balance"]) if sender_row else 0
        if current_balance < amount:
            raise ValueError(
                f"Insufficient {token_type} balance for escrow: "
                f"{from_did} has {current_balance}, needs {amount}"
            )

        # Debit holder's balance
        await conn.execute(
            """
            UPDATE token_balances
            SET balance = balance - $3, updated_at = CURRENT_TIMESTAMP
            WHERE agent_did = $1 AND token_type = $2::token_type
            """,
            from_did,
            token_type,
            amount,
        )

        # Create escrow hold record
        escrow_row = await conn.fetchrow(
            """
            INSERT INTO escrow_holds
                (task_id, holder_did, token_type, amount, status)
            VALUES
                ($1, $2, $3, $4, 'HELD')
            RETURNING escrow_id
            """,
            task_id,
            from_did,
            token_type,
            amount,
        )

        # Record the escrow debit in token_transactions
        await conn.execute(
            """
            INSERT INTO token_transactions
                (tx_id, from_did, to_did, token_type, transaction_type, amount, reference_id, memo)
            VALUES
                (gen_random_uuid(), $1, NULL, $2::token_type, 'TRANSFER'::transaction_type, $3, $4, 'escrow_hold')
            """,
            from_did,
            token_type,
            amount,
            str(task_id),
        )

    escrow_id = escrow_row["escrow_id"]
    logger.info(
        "Escrow hold created: escrow_id=%s task_id=%s holder=%s amount=%d %s",
        escrow_id, task_id, from_did, amount, token_type,
    )
    return escrow_id


async def escrow_release(task_id: UUID, to_did: str) -> None:
    """
    Release escrowed funds to the executor on task completion.

    Finds the HELD escrow record for the task, credits the executor,
    and marks the escrow as RELEASED.

    Raises ValueError if no held escrow exists for this task.
    """
    async with transaction() as conn:
        # Lock and fetch the held escrow for this task
        escrow_row = await conn.fetchrow(
            """
            SELECT escrow_id, holder_did, token_type, amount
            FROM escrow_holds
            WHERE task_id = $1 AND status = 'HELD'
            FOR UPDATE
            """,
            task_id,
        )

        if escrow_row is None:
            raise ValueError(f"No held escrow found for task: {task_id}")

        token_type = escrow_row["token_type"]
        amount = int(escrow_row["amount"])
        escrow_id = escrow_row["escrow_id"]

        # Credit executor (upsert)
        await conn.execute(
            """
            INSERT INTO token_balances (agent_did, token_type, balance, updated_at)
            VALUES ($1, $2::token_type, $3, CURRENT_TIMESTAMP)
            ON CONFLICT (agent_did, token_type)
            DO UPDATE SET
                balance    = token_balances.balance + EXCLUDED.balance,
                updated_at = CURRENT_TIMESTAMP
            """,
            to_did,
            token_type,
            amount,
        )

        # Mark escrow as released
        await conn.execute(
            """
            UPDATE escrow_holds
            SET status = 'RELEASED',
                released_to_did = $2,
                released_at = CURRENT_TIMESTAMP
            WHERE escrow_id = $1
            """,
            escrow_id,
            to_did,
        )

        # Record the payout in token_transactions
        await conn.execute(
            """
            INSERT INTO token_transactions
                (tx_id, from_did, to_did, token_type, transaction_type, amount, reference_id, memo)
            VALUES
                (gen_random_uuid(), $1, $2, $3::token_type, 'TASK_BOUNTY'::transaction_type, $4, $5, 'escrow_release')
            """,
            escrow_row["holder_did"],
            to_did,
            token_type,
            amount,
            str(task_id),
        )

    logger.info(
        "Escrow released: escrow_id=%s task_id=%s to=%s amount=%d %s",
        escrow_id, task_id, to_did, amount, token_type,
    )


async def escrow_refund(task_id: UUID) -> None:
    """
    Refund escrowed funds to the original holder on task cancellation/failure.

    Finds the HELD escrow record, credits the holder back,
    and marks the escrow as REFUNDED.

    Raises ValueError if no held escrow exists for this task.
    """
    async with transaction() as conn:
        # Lock and fetch the held escrow
        escrow_row = await conn.fetchrow(
            """
            SELECT escrow_id, holder_did, token_type, amount
            FROM escrow_holds
            WHERE task_id = $1 AND status = 'HELD'
            FOR UPDATE
            """,
            task_id,
        )

        if escrow_row is None:
            raise ValueError(f"No held escrow found for task: {task_id}")

        holder_did = escrow_row["holder_did"]
        token_type = escrow_row["token_type"]
        amount = int(escrow_row["amount"])
        escrow_id = escrow_row["escrow_id"]

        # Credit holder back
        await conn.execute(
            """
            UPDATE token_balances
            SET balance = balance + $3, updated_at = CURRENT_TIMESTAMP
            WHERE agent_did = $1 AND token_type = $2::token_type
            """,
            holder_did,
            token_type,
            amount,
        )

        # Mark escrow as refunded
        await conn.execute(
            """
            UPDATE escrow_holds
            SET status = 'REFUNDED',
                released_at = CURRENT_TIMESTAMP
            WHERE escrow_id = $1
            """,
            escrow_id,
        )

        # Record the refund in token_transactions
        await conn.execute(
            """
            INSERT INTO token_transactions
                (tx_id, from_did, to_did, token_type, transaction_type, amount, reference_id, memo)
            VALUES
                (gen_random_uuid(), NULL, $1, $2::token_type, 'TRANSFER'::transaction_type, $3, $4, 'escrow_refund')
            """,
            holder_did,
            token_type,
            amount,
            str(task_id),
        )

    logger.info(
        "Escrow refunded: escrow_id=%s task_id=%s to=%s amount=%d %s",
        escrow_id, task_id, holder_did, amount, token_type,
    )
