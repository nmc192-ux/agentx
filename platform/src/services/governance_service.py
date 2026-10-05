"""
AgentX Platform — Governance Service
═════════════════════════════════════
Phase 9: On-chain-style governance with proposals, voting, and execution.

Public API
──────────
  create_proposal(caller_did, data)    → ProposalResponse
  list_proposals(status, limit, offset)→ list[ProposalResponse]
  list_results(limit, offset)          → list[ProposalResponse]
  list_parameters()                    → list[GovernanceParameterResponse]
  vote_on_proposal(caller_did, req)    → VoteResponse
  calculate_vote_power(agent_did)      → float
  finalize_proposal(proposal_id)       → ProposalResponse
  finalize_due_proposals(limit)        → int
  execute_proposal(proposal_id)        → ProposalResponse

Design notes
────────────
• Vote power = SUM(active stakes) × trust_score, computed inline within the
  write transaction using a single connection to avoid stale reads.
• Agent UUID (proposer_id / voter_id) is resolved from the caller's DID
  inside each write transaction — keeping routers free of DB lookups.
• One vote per (proposal_id, voter_id) enforced by DB UNIQUE constraint
  and an app-layer pre-check.
• Proposal lifecycle: active → passed | failed → executed.
• execute_proposal is service-layer only — no router endpoint exposes it.
  It is a status change with no side-effects: a passed proposal is a recorded
  decision, it does not change anything on the platform by itself.
• Events are fire-and-forget; failures are logged but do not fail the call.

Sprint 9 (S9-8) — what the review before enabling the router changed
────────────────────────────────────────────────────────────────────
• The stake behind a vote stays put. A vote's weight is the voter's unreleased
  stakes at the moment of voting, and a stake with no lock period could be
  released one second later, moved to a second account, staked and voted
  again: one pile of tokens, any number of votes. Now the vote locks the
  voter's stake rows (``FOR UPDATE``) while it counts them, and
  ``token_service.release_stake`` refuses (409) while the stake's owner has a
  weighted vote on a proposal that is still open. The stake row is the meeting
  point of the two transactions, so whichever comes first, the other sees it.
• A vote locks the proposal row and uses the database clock, so no vote lands
  after the close (a vote racing ``finalize_proposal`` used to be able to).
• Proposals close. Nothing ever called ``finalize_proposal``, so a proposal
  stayed 'active' for ever and /governance/results was always empty.
  ``finalize_due_proposals`` closes every proposal whose voting period is
  over; the two read routes call it first (and a scheduler may).
• The outcome follows the rules seeded in ``governance_parameters`` (which
  nothing read): the total vote power (yes + no + abstain) must reach
  ``quorum_threshold``, and yes / (yes + no) must be MORE than
  ``pass_threshold``. It used to be "yes > no", so a single vote of weight
  0.5 passed a proposal. The tally is recounted from the vote rows at close.
• An agent can have at most ``MAX_OPEN_PROPOSALS_PER_AGENT`` open proposals.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

import asyncpg

from ..database import get_db, transaction
from ..events.publisher import publish_event
from ..events.types import EventType
from ..models.governance import (
    GovernanceParameterResponse,
    ProposalCreate,
    ProposalResponse,
    VoteRequest,
    VoteResponse,
)

logger = logging.getLogger(__name__)

# One agent, at most this many proposals open for voting at the same time
# (anti-flood; a reversible default, the founding documents set no number).
MAX_OPEN_PROPOSALS_PER_AGENT = 3

# Used when a governance_parameters row is missing or unreadable. Same values
# as the rows migrations 020 / 039 seed.
DEFAULT_QUORUM_THRESHOLD = Decimal("100")
DEFAULT_PASS_THRESHOLD = Decimal("0.5")

FINAL_STATUSES = ("passed", "failed", "executed")


class GovernanceConflictError(Exception):
    """The request is understood but the state does not allow it (HTTP 409):
    voting closed, already voted, too many open proposals, not yet due."""


# ── Internal helpers ──────────────────────────────────────────────────────────

# A proposal with its tally in full. yes_power / no_power are the running
# counters on the row; the rest is read from the vote rows.
_PROPOSAL_SELECT = """
    SELECT p.proposal_id, p.proposer_did, p.proposer_id, p.title, p.description,
           p.proposal_type, p.status, p.payload, p.yes_power, p.no_power,
           p.voting_ends_at, p.created_at,
           COALESCE(t.abstain_power, 0) AS abstain_power,
           COALESCE(t.yes_votes, 0)     AS yes_votes,
           COALESCE(t.no_votes, 0)      AS no_votes,
           COALESCE(t.abstain_votes, 0) AS abstain_votes
    FROM   proposals p
    LEFT JOIN LATERAL (
        SELECT SUM(v.vote_power) FILTER (WHERE v.vote = 'abstain') AS abstain_power,
               COUNT(*) FILTER (WHERE v.vote = 'yes')              AS yes_votes,
               COUNT(*) FILTER (WHERE v.vote = 'no')               AS no_votes,
               COUNT(*) FILTER (WHERE v.vote = 'abstain')          AS abstain_votes
        FROM   governance_votes v
        WHERE  v.proposal_id = p.proposal_id
    ) t ON TRUE
"""


def _row_to_proposal(row) -> ProposalResponse:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload) if payload else None
    return ProposalResponse(
        proposal_id=row["proposal_id"],
        proposer_did=row["proposer_did"],
        proposer_id=row.get("proposer_id"),
        title=row["title"],
        description=row["description"],
        proposal_type=row["proposal_type"],
        status=row["status"],
        payload=payload,
        yes_power=float(row["yes_power"]),
        no_power=float(row["no_power"]),
        abstain_power=float(row.get("abstain_power") or 0),
        yes_votes=int(row.get("yes_votes") or 0),
        no_votes=int(row.get("no_votes") or 0),
        abstain_votes=int(row.get("abstain_votes") or 0),
        voting_ends_at=row["voting_ends_at"],
        created_at=row["created_at"],
    )


def _row_to_vote(row) -> VoteResponse:
    return VoteResponse(
        vote_id=row["vote_id"],
        proposal_id=row["proposal_id"],
        voter_did=row["voter_did"],
        vote=row["vote"],
        vote_power=float(row["vote_power"]),
        created_at=row["created_at"],
    )


async def _fetch_proposal(conn, proposal_id: UUID):
    return await conn.fetchrow(
        _PROPOSAL_SELECT + " WHERE p.proposal_id = $1", proposal_id,
    )


def _parameter(values: dict, name: str, default: Decimal, upper: Decimal | None) -> Decimal:
    """A numeric governance parameter, or *default* when the row is missing,
    not a number, negative, or not below *upper* (when given)."""
    raw = values.get(name)
    if raw is None:
        return default
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        value = None
    if value is None or not value.is_finite() or value < 0 or (upper is not None and value >= upper):
        logger.warning(
            "governance_service: governance_parameters.%s = %r is not usable; using %s",
            name, raw, default,
        )
        return default
    return value


async def _read_rules(conn) -> tuple[Decimal, Decimal]:
    """(quorum_threshold, pass_threshold) from governance_parameters."""
    rows = await conn.fetch(
        """
        SELECT name, value FROM governance_parameters
        WHERE  name IN ('quorum_threshold', 'pass_threshold')
        """
    )
    values = {r["name"]: r["value"] for r in rows}
    return (
        _parameter(values, "quorum_threshold", DEFAULT_QUORUM_THRESHOLD, None),
        _parameter(values, "pass_threshold", DEFAULT_PASS_THRESHOLD, Decimal("1")),
    )


def decide_outcome(
    yes_power: Decimal,
    no_power: Decimal,
    abstain_power: Decimal,
    quorum_threshold: Decimal,
    pass_threshold: Decimal,
) -> str:
    """'passed' or 'failed'.

    Passed needs BOTH: the total vote power cast (abstentions included) reaches
    the quorum, and yes is MORE than ``pass_threshold`` of the yes + no power.
    A tie, or no yes / no power at all, fails.
    """
    decisive = yes_power + no_power
    if yes_power + no_power + abstain_power < quorum_threshold or decisive <= 0:
        return "failed"
    return "passed" if yes_power > pass_threshold * decisive else "failed"


async def _close_locked(conn, proposal_id: UUID) -> str:
    """Close an 'active' proposal whose row the caller has locked: recount the
    vote rows, decide, store. Returns the new status."""
    tally = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(vote_power) FILTER (WHERE vote = 'yes'), 0)     AS yes_power,
               COALESCE(SUM(vote_power) FILTER (WHERE vote = 'no'), 0)      AS no_power,
               COALESCE(SUM(vote_power) FILTER (WHERE vote = 'abstain'), 0) AS abstain_power
        FROM   governance_votes
        WHERE  proposal_id = $1
        """,
        proposal_id,
    )
    yes_power = Decimal(str(tally["yes_power"]))
    no_power = Decimal(str(tally["no_power"]))
    abstain_power = Decimal(str(tally["abstain_power"]))
    quorum_threshold, pass_threshold = await _read_rules(conn)
    new_status = decide_outcome(
        yes_power, no_power, abstain_power, quorum_threshold, pass_threshold,
    )
    await conn.execute(
        """
        UPDATE proposals
           SET status = $1, yes_power = $3, no_power = $4
         WHERE proposal_id = $2 AND status = 'active'
        """,
        new_status, proposal_id, yes_power, no_power,
    )
    logger.info(
        "governance_service: closed proposal %s → %s "
        "(yes=%s, no=%s, abstain=%s, quorum=%s, pass_threshold=%s)",
        proposal_id, new_status, yes_power, no_power, abstain_power,
        quorum_threshold, pass_threshold,
    )
    return new_status


# ── Proposal creation ─────────────────────────────────────────────────────────

async def create_proposal(caller_did: str, data: ProposalCreate) -> ProposalResponse:
    """
    Create a new governance proposal.

    Resolves caller's agent_id from their DID inside the transaction, then
    inserts the proposal row. The agent row is locked while the caller's open
    proposals are counted, so concurrent creates cannot pass the cap together.

    Args:
        caller_did: DID of the proposer (from AgentRecord.did).
        data:       Validated ProposalCreate payload.

    Returns:
        ProposalResponse for the newly created proposal.

    Raises:
        ValueError:              Agent not found.
        GovernanceConflictError: the caller already has
                                 MAX_OPEN_PROPOSALS_PER_AGENT open proposals.
    """
    voting_ends_at = datetime.now(UTC) + timedelta(days=data.voting_days)

    async with transaction() as conn:
        # Resolve DID → agent_id (NO KEY: does not block rows that reference
        # the agent, only another create by the same agent)
        agent_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1 FOR NO KEY UPDATE",
            caller_did,
        )
        if agent_row is None:
            raise ValueError(f"Agent not found: {caller_did}")
        caller_id = agent_row["agent_id"]

        open_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM proposals
            WHERE  proposer_id = $1
              AND  status = 'active'
              AND  voting_ends_at > CURRENT_TIMESTAMP
            """,
            caller_id,
        ) or 0
        if open_count >= MAX_OPEN_PROPOSALS_PER_AGENT:
            raise GovernanceConflictError(
                f"You already have {open_count} proposals open for voting "
                f"(the limit is {MAX_OPEN_PROPOSALS_PER_AGENT}); wait for one to close"
            )

        row = await conn.fetchrow(
            """
            INSERT INTO proposals
                (proposer_did, proposer_id, title, description, proposal_type,
                 payload, voting_ends_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
            RETURNING
                proposal_id, proposer_did, proposer_id, title, description,
                proposal_type, status, payload, yes_power, no_power,
                voting_ends_at, created_at
            """,
            caller_did,
            caller_id,
            data.title,
            data.description,
            data.proposal_type,
            json.dumps(data.payload) if data.payload else None,
            voting_ends_at,
        )

    proposal = _row_to_proposal(row)

    try:
        await publish_event(
            EventType.PROPOSAL_CREATED,
            {
                "proposal_id": str(proposal.proposal_id),
                "proposer_did": caller_did,
                "title": data.title,
                "proposal_type": data.proposal_type,
            },
            source_agent_did=caller_did,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "governance_service: failed to publish PROPOSAL_CREATED", exc_info=True
        )

    logger.info(
        "governance_service: created proposal %s ('%s') by %s",
        proposal.proposal_id, data.title, caller_did,
    )
    return proposal


# ── Proposal listing ──────────────────────────────────────────────────────────

async def list_proposals(
    status: str | None = "active",
    limit: int = 50,
    offset: int = 0,
) -> list[ProposalResponse]:
    """
    Return proposals filtered by status, newest first, one page at a time.

    Args:
        status: Filter value ('active', 'passed', 'failed', 'executed', or None
                for all proposals).
        limit:  Page size.
        offset: Rows to skip.

    Returns:
        List of ProposalResponse objects ordered by created_at DESC.
    """
    async with get_db() as conn:
        if status is None:
            rows = await conn.fetch(
                _PROPOSAL_SELECT
                + " ORDER BY p.created_at DESC, p.proposal_id LIMIT $1 OFFSET $2",
                limit, offset,
            )
        else:
            rows = await conn.fetch(
                _PROPOSAL_SELECT
                + " WHERE p.status = $1"
                + " ORDER BY p.created_at DESC, p.proposal_id LIMIT $2 OFFSET $3",
                status, limit, offset,
            )
    return [_row_to_proposal(r) for r in rows]


async def list_results(limit: int = 50, offset: int = 0) -> list[ProposalResponse]:
    """Closed proposals (passed / failed / executed), newest first."""
    async with get_db() as conn:
        rows = await conn.fetch(
            _PROPOSAL_SELECT
            + " WHERE p.status = ANY($1::text[])"
            + " ORDER BY p.created_at DESC, p.proposal_id LIMIT $2 OFFSET $3",
            list(FINAL_STATUSES), limit, offset,
        )
    return [_row_to_proposal(r) for r in rows]


async def list_parameters() -> list[GovernanceParameterResponse]:
    """The rules a proposal is decided by (quorum, pass threshold, …)."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT param_id, name, value, description, updated_at
            FROM   governance_parameters
            ORDER BY name
            """
        )
    return [
        GovernanceParameterResponse(
            param_id=r["param_id"], name=r["name"], value=r["value"],
            description=r["description"], updated_at=r["updated_at"],
        )
        for r in rows
    ]


# ── Vote power calculation ─────────────────────────────────────────────────────

async def calculate_vote_power(agent_did: str) -> float:
    """
    Compute an agent's current vote power using a fresh DB connection.

    vote_power = SUM(active stake amounts) × trust_score

    Intended for external/read-only use. Within a write transaction prefer
    to compute inline (see vote_on_proposal).

    Args:
        agent_did: DID of the agent.

    Returns:
        Computed vote power as a float.
    """
    async with get_db() as conn:
        agent_row = await conn.fetchrow(
            "SELECT agent_id, COALESCE(trust_score, 0.0) AS trust_score FROM agents WHERE agent_did = $1",
            agent_did,
        )
        if agent_row is None:
            return 0.0

        total_stake = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM   stakes
            WHERE  agent_id = $1
              AND  released_at IS NULL
            """,
            agent_row["agent_id"],
        ) or 0

    return float(total_stake) * float(agent_row["trust_score"])


# ── Voting ────────────────────────────────────────────────────────────────────

async def vote_on_proposal(caller_did: str, req: VoteRequest) -> VoteResponse:
    """
    Cast a vote on an active proposal.

    Resolves caller's agent_id from their DID inside the transaction, then
    locks the proposal row, validates its state against the database clock,
    locks and counts the voter's stakes, and inserts the vote.

    The stakes counted here cannot be released while the proposal is open
    (``token_service.release_stake``), so the same tokens cannot be moved to
    another account and vote again.

    Args:
        caller_did: DID of the voter (from AgentRecord.did).
        req:        VoteRequest containing proposal_id and vote direction.

    Returns:
        VoteResponse for the recorded vote.

    Raises:
        ValueError:              Agent not found or proposal not found.
        GovernanceConflictError: proposal not active, voting closed, or the
                                 caller has already voted.
    """
    async with transaction() as conn:
        # 1. Resolve voter DID → agent_id
        voter_row = await conn.fetchrow(
            "SELECT agent_id, COALESCE(trust_score, 0.0) AS trust_score FROM agents WHERE agent_did = $1",
            caller_did,
        )
        if voter_row is None:
            raise ValueError(f"Agent not found: {caller_did}")
        caller_id   = voter_row["agent_id"]
        trust_score = float(voter_row["trust_score"])

        # 2. Lock the proposal: votes on it (and its close) happen one at a time
        proposal = await conn.fetchrow(
            """
            SELECT proposal_id, status,
                   (voting_ends_at <= CURRENT_TIMESTAMP) AS voting_closed
            FROM   proposals
            WHERE  proposal_id = $1
            FOR UPDATE
            """,
            req.proposal_id,
        )
        if proposal is None:
            raise ValueError(f"Proposal not found: {req.proposal_id}")
        if proposal["status"] != "active":
            raise GovernanceConflictError(
                f"Proposal {req.proposal_id} is not active (status={proposal['status']})"
            )
        if proposal["voting_closed"]:
            raise GovernanceConflictError(
                f"Voting period closed for proposal {req.proposal_id}"
            )

        # 3. Check for duplicate vote (the proposal lock makes this reliable;
        #    the DB UNIQUE constraint stays as the backstop)
        existing_vote = await conn.fetchval(
            """
            SELECT vote_id FROM governance_votes
            WHERE  proposal_id = $1 AND voter_id = $2
            """,
            req.proposal_id,
            caller_id,
        )
        if existing_vote is not None:
            raise GovernanceConflictError(
                f"Agent {caller_did} has already voted on proposal {req.proposal_id}"
            )

        # 4. Lock and count the voter's stakes. A release (or slash) that got
        #    there first is waited for and then not counted; one that comes
        #    after waits for this vote and is then refused while the proposal
        #    is open.
        stake_rows = await conn.fetch(
            """
            SELECT amount
            FROM   stakes
            WHERE  agent_id = $1 AND released_at IS NULL
            ORDER BY stake_id
            FOR UPDATE
            """,
            caller_id,
        )
        total_stake = sum(int(r["amount"]) for r in stake_rows)

        vote_power = float(total_stake) * trust_score

        # 5. Insert vote
        try:
            vote_row = await conn.fetchrow(
                """
                INSERT INTO governance_votes
                    (proposal_id, voter_id, voter_did, vote, vote_power)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING vote_id, proposal_id, voter_did, vote, vote_power, created_at
                """,
                req.proposal_id,
                caller_id,
                caller_did,
                req.vote,
                vote_power,
            )
        except asyncpg.UniqueViolationError as exc:
            raise GovernanceConflictError(
                f"Agent {caller_did} has already voted on proposal {req.proposal_id}"
            ) from exc

        # 6. Update running tallies on proposal
        if req.vote == "yes":
            await conn.execute(
                """
                UPDATE proposals
                   SET yes_power = yes_power + $1
                 WHERE proposal_id = $2
                """,
                vote_power,
                req.proposal_id,
            )
        elif req.vote == "no":
            await conn.execute(
                """
                UPDATE proposals
                   SET no_power = no_power + $1
                 WHERE proposal_id = $2
                """,
                vote_power,
                req.proposal_id,
            )
        # abstain: tallies unchanged (vote is still recorded)

    vote = _row_to_vote(vote_row)

    try:
        await publish_event(
            EventType.VOTE_CAST,
            {
                "vote_id": str(vote.vote_id),
                "proposal_id": str(vote.proposal_id),
                "voter_did": caller_did,
                "vote": req.vote,
                "vote_power": vote_power,
            },
            source_agent_did=caller_did,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "governance_service: failed to publish VOTE_CAST", exc_info=True
        )

    logger.info(
        "governance_service: vote %s cast by %s on proposal %s (power=%.4f)",
        req.vote, caller_did, req.proposal_id, vote_power,
    )
    return vote


# ── Finalization ──────────────────────────────────────────────────────────────

async def finalize_proposal(proposal_id: UUID) -> ProposalResponse:
    """
    Finalize an active proposal whose voting period has closed.

    The outcome is decided by ``decide_outcome`` (quorum and pass threshold
    from governance_parameters) on a recount of the vote rows, with the
    proposal row locked. Idempotent if already finalized.

    Args:
        proposal_id: UUID of the proposal to finalize.

    Returns:
        Updated ProposalResponse.

    Raises:
        ValueError:              Proposal not found.
        GovernanceConflictError: the voting period is not over yet.
    """
    async with transaction() as conn:
        proposal = await conn.fetchrow(
            """
            SELECT proposal_id, status,
                   (voting_ends_at <= CURRENT_TIMESTAMP) AS voting_closed
            FROM   proposals
            WHERE  proposal_id = $1
            FOR UPDATE
            """,
            proposal_id,
        )
        if proposal is None:
            raise ValueError(f"Proposal not found: {proposal_id}")

        if proposal["status"] == "active":
            if not proposal["voting_closed"]:
                raise GovernanceConflictError(
                    f"Voting on proposal {proposal_id} is still open"
                )
            await _close_locked(conn, proposal_id)

        row = await _fetch_proposal(conn, proposal_id)

    return _row_to_proposal(row)


async def finalize_due_proposals(limit: int = 100) -> int:
    """
    Close every 'active' proposal whose voting period is over (oldest first,
    at most *limit* per call). Safe to call from several workers at once: a
    proposal another transaction is working on is skipped, not waited for.

    Returns:
        How many proposals were closed.
    """
    async with transaction() as conn:
        due = await conn.fetch(
            """
            SELECT proposal_id
            FROM   proposals
            WHERE  status = 'active' AND voting_ends_at <= CURRENT_TIMESTAMP
            ORDER BY voting_ends_at
            LIMIT  $1
            FOR UPDATE SKIP LOCKED
            """,
            limit,
        )
        for row in due:
            await _close_locked(conn, row["proposal_id"])
    return len(due)


# ── Execution ─────────────────────────────────────────────────────────────────

async def execute_proposal(proposal_id: UUID) -> ProposalResponse:
    """
    Execute a passed proposal (transition to 'executed' status).

    In Phase 9 execution is a status transition only; payload-driven
    side-effects can be added in future phases.

    Args:
        proposal_id: UUID of the proposal to execute.

    Returns:
        Updated ProposalResponse.

    Raises:
        ValueError: Proposal not found or not in 'passed' status.
    """
    async with transaction() as conn:
        proposal = await conn.fetchrow(
            "SELECT status FROM proposals WHERE proposal_id = $1 FOR UPDATE",
            proposal_id,
        )
        if proposal is None:
            raise ValueError(f"Proposal not found: {proposal_id}")
        if proposal["status"] != "passed":
            raise ValueError(
                f"Proposal {proposal_id} cannot be executed (status={proposal['status']})"
            )

        row = await conn.fetchrow(
            """
            UPDATE proposals
               SET status = 'executed'
             WHERE proposal_id = $1
            RETURNING
                proposal_id, proposer_did, proposer_id, title, description,
                proposal_type, status, payload, yes_power, no_power,
                voting_ends_at, created_at
            """,
            proposal_id,
        )

    result = _row_to_proposal(row)

    try:
        await publish_event(
            EventType.PROPOSAL_EXECUTED,
            {
                "proposal_id": str(proposal_id),
                "yes_power": result.yes_power,
                "no_power": result.no_power,
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "governance_service: failed to publish PROPOSAL_EXECUTED", exc_info=True
        )

    logger.info("governance_service: executed proposal %s", proposal_id)
    return result
