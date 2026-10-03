"""
Trust events and the trust score they add up to.

Recording (S9-9b). Trust is half of every governance vote's weight, so an
event may only be recorded when it stands for something that really happened
between two different, established accounts:

  • every event names its occurrence (``dedupe_key``, UNIQUE in the table):
    the same finished task, answered message or verification vote can be
    recorded once, whichever code path reports it and however often;
  • a positive event needs a counterparty: another ACTIVE agent whose account
    is at least MIN_COUNTERPARTY_AGE old;
  • two agents can give each other at most PAIR_DAILY_LIMIT positive events of
    one type per 24 hours (in either direction);
  • an agent gains at most MAX_DAILY_GAIN per 24 hours, whatever the source.

The callers do not decide any of this: they report what happened
(``record_task_completed`` …) and the rules are checked here, against the
database, not against what a request or a bus message claims.

Replay. ``recalculate_agent_trust`` applies recorded events to
``agents.trust_score``. Rows without a dedupe_key were recorded before these
rules existed (one per message sent, up to four per task) and are never applied.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

from ..cache import agent_key, cache_delete, trust_score_key
from ..database import get_db, transaction
from ..models.reputation import AgentTrustScoreResponse, ReputationHistoryEntry

logger = logging.getLogger(__name__)

DEFAULT_TRUST_SCORE = 0.5

# pg_advisory_xact_lock key for the replay below: two runs at once (the
# scheduled job, a request, a second machine) would otherwise both read the
# same unapplied events and apply them twice.
TRUST_REPLAY_LOCK_KEY = 0x7472757374  # "trust"

# First key of the two-key advisory lock record_event takes per agent, so the
# cap checks of two events for the same agent (or pair) run one after the other.
TRUST_RECORD_LOCK_NS = 0x7472  # "tr"

EVENT_WEIGHTS = {
    "task_completed": 0.05,
    "task_success": 0.05,
    "task_failed": -0.10,
    "task_failure": -0.10,
    "service_used": 0.02,
    "peer_validation": 0.03,
    "prediction_accuracy": 0.04,
    "message_replied": 0.01,
    "spam_flag": -0.20,
    "system_penalty": -0.25,
}

# The other side of a positive event must be an account at least this old
# (same age the post-flag rule uses), so a just-created account cannot vouch.
MIN_COUNTERPARTY_AGE = timedelta(hours=24)
# Positive events of one type that two agents can give each other per 24 h.
PAIR_DAILY_LIMIT = 1
# Most an agent's score can rise per 24 h, all sources together.
MAX_DAILY_GAIN = 0.10
# A message is a reply if it answers one received within this window.
MESSAGE_REPLY_WINDOW = timedelta(days=7)

# record_event outcomes. Only RECORDED writes a row.
RECORDED = "recorded"
DUPLICATE = "duplicate"
NO_COUNTERPARTY = "no_counterparty"
COUNTERPARTY_NOT_ESTABLISHED = "counterparty_not_established"
PAIR_CAP = "pair_cap"
DAILY_CAP = "daily_cap"


def _normalize_event_type(event_type: str) -> str:
    return event_type.strip().lower()


def _clamp_score(score: float) -> float:
    return round(max(0.0, min(1.0, score)), 2)


def _decode_metadata(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


async def record_event(
    agent_did: str,
    event_type: str,
    metadata: dict | None = None,
    *,
    dedupe_key: str,
    counterparty_did: str | None = None,
) -> str:
    """
    Record one trust event for *agent_did*, if the rules in the module
    docstring allow it. Returns RECORDED, or the reason nothing was written.

    *dedupe_key* names the occurrence (e.g. ``task_completed:<task_id>``) and
    is required: an event that cannot say what it is about is not recorded.
    Negative events are deduplicated but not capped, and need no counterparty.

    Raises:
        ValueError: unknown event type, empty dedupe_key, or unknown agent.
    """
    normalized_type = _normalize_event_type(event_type)
    event_weight = EVENT_WEIGHTS.get(normalized_type)
    if event_weight is None:
        raise ValueError(f"Unsupported reputation event type: {event_type}")
    if not dedupe_key:
        raise ValueError("A trust event needs a dedupe_key")

    async with transaction() as conn:
        agent_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            agent_did,
        )
        if agent_row is None:
            raise ValueError(f"Agent not found: {agent_did}")

        if event_weight > 0:
            if not counterparty_did or counterparty_did == agent_did:
                return NO_COUNTERPARTY
            established = await conn.fetchval(
                """
                SELECT 1 FROM agents
                WHERE agent_did = $1
                  AND status = 'ACTIVE'
                  AND created_at <= CURRENT_TIMESTAMP - $2::interval
                """,
                counterparty_did,
                MIN_COUNTERPARTY_AGE,
            )
            if not established:
                return COUNTERPARTY_NOT_ESTABLISHED

            # Both agents' locks, in a fixed order: the counts below cannot be
            # passed twice by two events recorded at the same moment.
            for did in sorted((agent_did, counterparty_did)):
                await conn.execute(
                    "SELECT pg_advisory_xact_lock($1, hashtext($2))",
                    TRUST_RECORD_LOCK_NS,
                    did,
                )

            if await conn.fetchval(
                "SELECT 1 FROM trust_events WHERE dedupe_key = $1", dedupe_key,
            ):
                return DUPLICATE

            between_pair = await conn.fetchval(
                """
                SELECT COUNT(*) FROM trust_events
                WHERE event_type = $1
                  AND dedupe_key IS NOT NULL
                  AND COALESCE(event_weight, event_value) > 0
                  AND created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
                  AND (
                        (agent_did = $2 AND counterparty_did = $3)
                     OR (agent_did = $3 AND counterparty_did = $2)
                  )
                """,
                normalized_type,
                agent_did,
                counterparty_did,
            )
            if between_pair >= PAIR_DAILY_LIMIT:
                return PAIR_CAP

            gained_today = await conn.fetchval(
                """
                SELECT COALESCE(SUM(COALESCE(event_weight, event_value)), 0.0)
                FROM trust_events
                WHERE agent_did = $1
                  AND dedupe_key IS NOT NULL
                  AND COALESCE(event_weight, event_value) > 0
                  AND created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
                """,
                agent_did,
            )
            if float(gained_today) + event_weight > MAX_DAILY_GAIN + 1e-9:
                return DAILY_CAP

        event_id = await conn.fetchval(
            """
            INSERT INTO trust_events (
                event_id,
                agent_id,
                agent_did,
                event_type,
                event_weight,
                event_value,
                metadata,
                dedupe_key,
                counterparty_did
            )
            VALUES (
                gen_random_uuid(),
                $1,
                $2,
                $3,
                $4,
                $4,
                $5::jsonb,
                $6,
                $7
            )
            ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING
            RETURNING event_id
            """,
            agent_row["agent_id"],
            agent_did,
            normalized_type,
            event_weight,
            json.dumps(metadata or {}),
            dedupe_key,
            counterparty_did,
        )
    return RECORDED if event_id is not None else DUPLICATE


# ── What happened → trust events ──────────────────────────────────────────────
# Called after the caller's own transaction has committed. They never raise:
# a trust event that could not be recorded must not fail the request that
# finished the task or sent the message.

def _as_uuid(value: Any) -> UUID | None:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _task_parties(task_id: UUID) -> dict | None:
    """The task's status, both parties' DIDs, and what the escrow paid the executor."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                t.status,
                COALESCE(t.executor_agent_did, ex.agent_did)  AS executor_did,
                COALESCE(t.requester_agent_did, rq.agent_did) AS requester_did,
                (
                    SELECT COALESCE(SUM(tx.amount), 0)
                    FROM transactions tx
                    JOIN wallets w ON w.wallet_id = tx.to_wallet
                    JOIN agents payee ON payee.agent_id = w.agent_id
                    WHERE tx.related_id = t.task_id
                      AND tx.type = 'escrow_release'
                      AND payee.agent_did = COALESCE(t.executor_agent_did, ex.agent_did)
                ) AS paid
            FROM tasks t
            LEFT JOIN agents ex ON ex.agent_id = t.executor_agent_id
            LEFT JOIN agents rq
                   ON rq.agent_id = COALESCE(t.creator_agent_id, t.requester_agent_id)
            WHERE t.task_id = $1
            """,
            task_id,
        )
    return dict(row) if row is not None else None


async def record_task_completed(task_id: Any, *, source: str = "direct") -> str:
    """
    One ``task_completed`` for the executor of a finished task, if a funded
    reward was really paid out of escrow to that executor by someone else.
    A task with no reward (every direct task, a 0-reward marketplace task)
    earns nothing: completing it proves no work anyone valued.

    Safe to call from every path that learns of the completion (router,
    service, both bus consumers): the task row decides, and the dedupe key
    makes the second and later calls a no-op.
    """
    task_uuid = _as_uuid(task_id)
    if task_uuid is None:
        return "unknown_task"
    try:
        task = await _task_parties(task_uuid)
        if task is None or not task["executor_did"]:
            return "unknown_task"
        if task["status"] != "COMPLETED":
            return "not_completed"
        if not task["paid"]:
            return "unfunded"
        outcome = await record_event(
            task["executor_did"],
            "task_completed",
            {"task_id": str(task_uuid), "reward_paid": int(task["paid"]), "source": source},
            dedupe_key=f"task_completed:{task_uuid}",
            counterparty_did=task["requester_did"],
        )
    except Exception:
        logger.exception("reputation: recording completion of task %s failed", task_id)
        return "error"
    logger.info("reputation: task %s completion (%s) -> %s", task_uuid, source, outcome)
    return outcome


async def record_task_failed(task_id: Any, *, reported_by_did: str) -> str:
    """
    One ``task_failed`` for an executor who reports their own task as failed.
    A failure set by anyone else (a FOUNDER, the system worker acting for the
    executor) costs the executor nothing: a requester names the executor of a
    direct task without asking, so it must not be able to cost them trust.
    """
    task_uuid = _as_uuid(task_id)
    if task_uuid is None:
        return "unknown_task"
    try:
        task = await _task_parties(task_uuid)
        if task is None or not task["executor_did"]:
            return "unknown_task"
        if task["status"] != "FAILED":
            return "not_failed"
        if task["executor_did"] != reported_by_did:
            return "not_reported_by_executor"
        if task["requester_did"] == task["executor_did"]:
            return NO_COUNTERPARTY
        outcome = await record_event(
            task["executor_did"],
            "task_failed",
            {"task_id": str(task_uuid)},
            dedupe_key=f"task_failed:{task_uuid}",
            counterparty_did=task["requester_did"],
        )
    except Exception:
        logger.exception("reputation: recording failure of task %s failed", task_id)
        return "error"
    return outcome


async def record_message_reply(sender_did: str, receiver_did: str, message_id: Any) -> str:
    """
    One ``message_replied`` for *sender_did* if the message just sent answers
    one *receiver_did* sent them within MESSAGE_REPLY_WINDOW. Sending a message
    nobody asked for earns nothing. The event is keyed on the message being
    answered (the latest one received), so each can be answered for credit once.
    """
    message_uuid = _as_uuid(message_id)
    if message_uuid is None:
        return "unknown_message"
    try:
        async with get_db() as conn:
            answered_id = await conn.fetchval(
                """
                SELECT m.message_id
                FROM messages m
                WHERE m.sender_agent_did = $2
                  AND m.receiver_agent_did = $1
                  AND m.created_at > CURRENT_TIMESTAMP - $4::interval
                  AND m.created_at <= (
                        SELECT created_at FROM messages WHERE message_id = $3
                  )
                ORDER BY m.created_at DESC
                LIMIT 1
                """,
                sender_did,
                receiver_did,
                message_uuid,
                MESSAGE_REPLY_WINDOW,
            )
        if answered_id is None:
            return "not_a_reply"
        return await record_event(
            sender_did,
            "message_replied",
            {"message_id": str(message_uuid), "answered_message_id": str(answered_id)},
            dedupe_key=f"message_replied:{answered_id}",
            counterparty_did=receiver_did,
        )
    except Exception:
        logger.exception("reputation: recording reply %s failed", message_id)
        return "error"


async def record_verification_outcome(verification_id: Any) -> dict[str, str]:
    """
    ``peer_validation`` for the verifiers who voted with the final outcome of
    a finalised verification — nothing for casting a vote as such, nothing for
    the losing side. Keyed per contract and voter, so opening several
    verifications on one contract result pays a voter once.

    Returns {verifier_did: outcome}; empty if the verification is not final.
    """
    verification_uuid = _as_uuid(verification_id)
    if verification_uuid is None:
        return {}
    outcomes: dict[str, str] = {}
    try:
        async with get_db() as conn:
            verification = await conn.fetchrow(
                """
                SELECT status, requester_did, contract_id
                FROM verifications WHERE verification_id = $1
                """,
                verification_uuid,
            )
            if verification is None or verification["status"] not in ("verified", "failed"):
                return {}
            winning_vote = "approve" if verification["status"] == "verified" else "reject"
            voters = await conn.fetch(
                """
                SELECT verifier_did FROM verification_votes
                WHERE verification_id = $1 AND vote = $2
                ORDER BY created_at
                """,
                verification_uuid,
                winning_vote,
            )
        for voter in voters:
            verifier_did = voter["verifier_did"]
            outcomes[verifier_did] = await record_event(
                verifier_did,
                "peer_validation",
                {
                    "verification_id": str(verification_uuid),
                    "contract_id": str(verification["contract_id"]),
                    "outcome": verification["status"],
                },
                dedupe_key=f"peer_validation:{verification['contract_id']}:{verifier_did}",
                counterparty_did=verification["requester_did"],
            )
    except Exception:
        logger.exception(
            "reputation: recording outcome of verification %s failed", verification_id,
        )
    return outcomes


async def recalculate_agent_trust(
    *,
    agent_id: UUID | None = None,
    agent_did: str | None = None,
) -> dict[str, int]:
    processed_events = 0
    updated_agents: set[UUID] = set()

    async with transaction() as conn:
        await conn.execute("SELECT pg_advisory_xact_lock($1)", TRUST_REPLAY_LOCK_KEY)
        rows = await conn.fetch(
            """
            SELECT
                te.event_id,
                te.agent_id,
                a.agent_did,
                te.event_type,
                COALESCE(te.event_weight, te.event_value, 0.0) AS event_weight,
                te.created_at
            FROM trust_events te
            JOIN agents a ON a.agent_id = te.agent_id
            LEFT JOIN agent_reputation_history arh ON arh.event_id = te.event_id
            WHERE arh.event_id IS NULL
              AND te.dedupe_key IS NOT NULL
              AND ($1::uuid IS NULL OR te.agent_id = $1)
              AND ($2::text IS NULL OR a.agent_did = $2)
            ORDER BY te.created_at ASC, te.event_id ASC
            """,
            agent_id,
            agent_did,
        )

        current_scores: dict[UUID, float] = {}
        initial_scores: dict[UUID, float] = {}

        for row in rows:
            agent_uuid = row["agent_id"]
            if agent_uuid not in current_scores:
                current_score = await conn.fetchval(
                    """
                    SELECT COALESCE(ts.current_score, a.trust_score, $2)
                    FROM agents a
                    LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
                    WHERE a.agent_id = $1
                    """,
                    agent_uuid,
                    DEFAULT_TRUST_SCORE,
                )
                current_scores[agent_uuid] = float(current_score if current_score is not None else DEFAULT_TRUST_SCORE)
                initial_scores[agent_uuid] = current_scores[agent_uuid]

            score_before = current_scores[agent_uuid]
            score_after = _clamp_score(score_before + float(row["event_weight"]))

            await conn.execute(
                """
                INSERT INTO trust_scores (agent_id, current_score, last_updated)
                VALUES ($1, $2, CURRENT_TIMESTAMP)
                ON CONFLICT (agent_id)
                DO UPDATE SET
                    current_score = EXCLUDED.current_score,
                    last_updated = EXCLUDED.last_updated
                """,
                agent_uuid,
                score_after,
            )
            await conn.execute(
                "UPDATE agents SET trust_score = $1 WHERE agent_id = $2",
                score_after,
                agent_uuid,
            )
            await conn.execute(
                """
                INSERT INTO agent_reputation_history (
                    history_id,
                    agent_id,
                    score_before,
                    score_after,
                    event_id,
                    created_at
                )
                VALUES (
                    gen_random_uuid(),
                    $1,
                    $2,
                    $3,
                    $4,
                    CURRENT_TIMESTAMP
                )
                """,
                agent_uuid,
                score_before,
                score_after,
                row["event_id"],
            )

            current_scores[agent_uuid] = score_after
            processed_events += 1
            updated_agents.add(agent_uuid)

    if updated_agents:
        # The profile (GET /agents/{did}) caches trust_score too; clear it only
        # where the score actually moved, so a no-op replay keeps the cache.
        changed_agents = {
            agent_uuid for agent_uuid in updated_agents
            if current_scores[agent_uuid] != initial_scores[agent_uuid]
        }
        async with get_db() as conn:
            did_rows = await conn.fetch(
                "SELECT agent_id, agent_did FROM agents WHERE agent_id = ANY($1::uuid[])",
                list(updated_agents),
            )
        for did_row in did_rows:
            await cache_delete(trust_score_key(did_row["agent_did"]))
            if did_row["agent_id"] in changed_agents:
                await cache_delete(agent_key(did_row["agent_did"]))

    return {
        "processed_events": processed_events,
        "updated_agents": len(updated_agents),
    }


async def update_trust_score(agent_did: str) -> float:
    await recalculate_agent_trust(agent_did=agent_did)
    trust = await get_agent_trust_by_did(agent_did)
    return trust.current_score


async def get_agent_trust(agent_id: UUID) -> AgentTrustScoreResponse:
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                a.agent_id,
                COALESCE(ts.current_score, a.trust_score, $2) AS current_score,
                ts.last_updated
            FROM agents a
            LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
            WHERE a.agent_id = $1
            """,
            agent_id,
            DEFAULT_TRUST_SCORE,
        )
    if row is None:
        raise ValueError(f"Agent not found: {agent_id}")

    return AgentTrustScoreResponse(
        agent_id=row["agent_id"],
        current_score=float(row["current_score"]),
        last_updated=row["last_updated"],
    )


async def get_agent_trust_by_did(agent_did: str) -> AgentTrustScoreResponse:
    async with get_db() as conn:
        agent_id = await conn.fetchval(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            agent_did,
        )
    if agent_id is None:
        raise ValueError(f"Agent not found: {agent_did}")
    return await get_agent_trust(agent_id)


async def get_reputation_history(agent_id: UUID, limit: int = 50) -> list[ReputationHistoryEntry]:
    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_id = $1",
            agent_id,
        )
        if not exists:
            raise ValueError(f"Agent not found: {agent_id}")

        rows = await conn.fetch(
            """
            SELECT
                arh.history_id,
                arh.agent_id,
                arh.score_before,
                arh.score_after,
                arh.event_id,
                te.event_type,
                COALESCE(te.event_weight, te.event_value, 0.0) AS event_weight,
                te.metadata,
                arh.created_at
            FROM agent_reputation_history arh
            JOIN trust_events te ON te.event_id = arh.event_id
            WHERE arh.agent_id = $1
            ORDER BY arh.created_at DESC
            LIMIT $2
            """,
            agent_id,
            limit,
        )

    return [
        ReputationHistoryEntry(
            history_id=row["history_id"],
            agent_id=row["agent_id"],
            event_id=row["event_id"],
            event_type=row["event_type"],
            event_weight=float(row["event_weight"]),
            score_before=float(row["score_before"]),
            score_after=float(row["score_after"]),
            metadata=_decode_metadata(row["metadata"]),
            created_at=row["created_at"],
        )
        for row in rows
    ]
