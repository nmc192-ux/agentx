"""
AgentX Platform — Swarm Coordination Service
═════════════════════════════════════════════
Phase 4: Multi-agent swarm lifecycle

Swarm lifecycle:
  1. FORMING   — coordinator creates swarm, defines subtasks, recruits members
  2. ACTIVE    — subtasks assigned to members, execution in progress
  3. AGGREGATING — all subtasks done, results being combined
  4. COMPLETED — final aggregated result available

Strategies:
  parallel    — all subtasks dispatched at once
  pipeline    — sequential: each subtask feeds the next
  consensus   — same task to all members, majority vote
  competitive — same task to all, first good result wins
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from ..database import get_db, transaction
from ..services import token_service
from ..services.events import emit_event
from ..services.reputation import record_event

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _decode_json(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _parse_text_array(value) -> list[str]:
    """Parse PostgreSQL text[] into Python list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return []


def _row_to_swarm(row, member_count: int = 0, subtask_count: int = 0, completed: int = 0) -> dict:
    return {
        "swarm_id": row["swarm_id"],
        "name": row["name"],
        "coordinator_did": row["coordinator_did"],
        "objective": row["objective"],
        "strategy": row["strategy"],
        "max_members": row["max_members"],
        "reward_pool": row["reward_pool"],
        "status": row["status"],
        "required_capabilities": _parse_text_array(row.get("required_capabilities")),
        "member_count": member_count,
        "subtask_count": subtask_count,
        "completed_subtasks": completed,
        "created_at": row["created_at"],
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
    }


def _row_to_subtask(row) -> dict:
    return {
        "subtask_id": row["subtask_id"],
        "swarm_id": row["swarm_id"],
        "task_type": row["task_type"],
        "description": row.get("description"),
        "payload": _decode_json(row.get("payload")),
        "sequence": row["sequence"],
        "assigned_did": row.get("assigned_did"),
        "status": row["status"],
        "result": _decode_json(row.get("result")) if row.get("result") else None,
        "created_at": row["created_at"],
        "completed_at": row.get("completed_at"),
    }


def _row_to_member(row) -> dict:
    return {
        "agent_did": row["agent_did"],
        "role": row["role"],
        "status": row["status"],
        "subtask_id": row.get("subtask_id"),
        "joined_at": row["joined_at"],
    }


# ── Swarm Lifecycle ──────────────────────────────────────────────────────────

async def create_swarm(
    coordinator_did: str,
    name: str,
    objective: str,
    strategy: str = "parallel",
    max_members: int = 10,
    reward_pool: int = 0,
    required_capabilities: list[str] | None = None,
    subtasks: list[dict] | None = None,
    config: dict | None = None,
) -> dict:
    """
    Create a new swarm and optionally define its subtasks.
    The coordinator is automatically added as a member.
    """
    caps = required_capabilities or []
    subtask_defs = subtasks or []

    async with transaction() as conn:
        # Verify coordinator exists
        agent_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            coordinator_did,
        )
        if agent_row is None:
            raise ValueError(f"Coordinator agent not found: {coordinator_did}")

        # Create swarm
        swarm_row = await conn.fetchrow(
            """
            INSERT INTO swarms (
                name, coordinator_did, objective, strategy,
                max_members, reward_pool, required_capabilities, config
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
            RETURNING *
            """,
            name,
            coordinator_did,
            objective,
            strategy,
            max_members,
            reward_pool,
            caps,
            json.dumps(config or {}),
        )
        swarm_id = swarm_row["swarm_id"]

        # Add coordinator as member
        await conn.execute(
            """
            INSERT INTO swarm_members (swarm_id, agent_did, role, status)
            VALUES ($1, $2, 'coordinator', 'active')
            """,
            swarm_id,
            coordinator_did,
        )

        # Create subtasks
        for st in subtask_defs:
            await conn.execute(
                """
                INSERT INTO swarm_subtasks (swarm_id, task_type, description, payload, sequence)
                VALUES ($1, $2, $3, $4::jsonb, $5)
                """,
                swarm_id,
                st.get("task_type", "generic"),
                st.get("description", ""),
                json.dumps(st.get("payload", {})),
                st.get("sequence", 0),
            )

    # Escrow reward pool from coordinator
    if reward_pool > 0:
        try:
            await token_service.escrow_hold(
                task_id=swarm_id,
                from_did=coordinator_did,
                token_type="WORK",
                amount=reward_pool,
            )
        except ValueError as exc:
            logger.warning("Swarm escrow failed (continuing without): %s", exc)

    await emit_event("SWARM_CREATED", coordinator_did, {
        "swarm_id": str(swarm_id),
        "name": name,
        "strategy": strategy,
        "coordinator_did": coordinator_did,
    })

    return _row_to_swarm(dict(swarm_row), member_count=1, subtask_count=len(subtask_defs))


async def get_swarm(swarm_id: UUID) -> dict:
    """Get swarm detail with members and subtasks."""
    async with get_db() as conn:
        swarm_row = await conn.fetchrow(
            "SELECT * FROM swarms WHERE swarm_id = $1", swarm_id,
        )
        if swarm_row is None:
            raise ValueError(f"Swarm not found: {swarm_id}")

        members = await conn.fetch(
            "SELECT * FROM swarm_members WHERE swarm_id = $1 ORDER BY joined_at",
            swarm_id,
        )
        subtasks = await conn.fetch(
            "SELECT * FROM swarm_subtasks WHERE swarm_id = $1 ORDER BY sequence, created_at",
            swarm_id,
        )

    completed_count = sum(1 for s in subtasks if s["status"] == "completed")
    result = _row_to_swarm(dict(swarm_row), len(members), len(subtasks), completed_count)
    result["members"] = [_row_to_member(dict(m)) for m in members]
    result["subtasks"] = [_row_to_subtask(dict(s)) for s in subtasks]
    return result


async def list_swarms(
    status: str | None = None,
    agent_did: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List swarms, optionally filtered by status or membership."""
    conditions = []
    params: list = []

    if status:
        params.append(status)
        conditions.append(f"s.status = ${len(params)}")

    if agent_did:
        params.append(agent_did)
        conditions.append(
            f"(s.coordinator_did = ${len(params)} OR "
            f"EXISTS (SELECT 1 FROM swarm_members sm WHERE sm.swarm_id = s.swarm_id AND sm.agent_did = ${len(params)}))"
        )

    params.append(limit)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT s.*,
                   (SELECT COUNT(*) FROM swarm_members sm WHERE sm.swarm_id = s.swarm_id) AS member_count,
                   (SELECT COUNT(*) FROM swarm_subtasks st WHERE st.swarm_id = s.swarm_id) AS subtask_count,
                   (SELECT COUNT(*) FROM swarm_subtasks st WHERE st.swarm_id = s.swarm_id AND st.status = 'completed') AS completed_subtasks
            FROM swarms s
            {where}
            ORDER BY s.created_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )

    return [_row_to_swarm(dict(r), r["member_count"], r["subtask_count"], r["completed_subtasks"]) for r in rows]


# ── Membership ───────────────────────────────────────────────────────────────

async def join_swarm(
    swarm_id: UUID,
    agent_did: str,
    role: str = "worker",
) -> dict:
    """Agent joins a forming swarm as a worker or verifier."""
    async with transaction() as conn:
        swarm = await conn.fetchrow(
            "SELECT swarm_id, status, max_members FROM swarms WHERE swarm_id = $1",
            swarm_id,
        )
        if swarm is None:
            raise ValueError(f"Swarm not found: {swarm_id}")
        if swarm["status"] not in ("forming",):
            raise ValueError(f"Swarm is not accepting members (status={swarm['status']})")

        member_count = await conn.fetchval(
            "SELECT COUNT(*) FROM swarm_members WHERE swarm_id = $1",
            swarm_id,
        )
        if member_count >= swarm["max_members"]:
            raise ValueError("Swarm is full")

        # Check not already a member
        existing = await conn.fetchval(
            "SELECT 1 FROM swarm_members WHERE swarm_id = $1 AND agent_did = $2",
            swarm_id, agent_did,
        )
        if existing:
            raise ValueError("Already a member of this swarm")

        await conn.execute(
            """
            INSERT INTO swarm_members (swarm_id, agent_did, role, status)
            VALUES ($1, $2, $3, 'active')
            """,
            swarm_id, agent_did, role,
        )

    await emit_event("SWARM_MEMBER_JOINED", agent_did, {
        "swarm_id": str(swarm_id),
        "agent_did": agent_did,
        "role": role,
    })

    return {"swarm_id": str(swarm_id), "agent_did": agent_did, "role": role, "status": "active"}


async def leave_swarm(swarm_id: UUID, agent_did: str) -> dict:
    """Agent leaves a swarm. Coordinators cannot leave."""
    async with transaction() as conn:
        member = await conn.fetchrow(
            "SELECT role, status FROM swarm_members WHERE swarm_id = $1 AND agent_did = $2",
            swarm_id, agent_did,
        )
        if member is None:
            raise ValueError("Not a member of this swarm")
        if member["role"] == "coordinator":
            raise ValueError("Coordinator cannot leave — cancel the swarm instead")

        await conn.execute(
            """
            UPDATE swarm_members
            SET status = 'left', completed_at = CURRENT_TIMESTAMP
            WHERE swarm_id = $1 AND agent_did = $2
            """,
            swarm_id, agent_did,
        )

    return {"swarm_id": str(swarm_id), "agent_did": agent_did, "status": "left"}


async def recruit_for_swarm(swarm_id: UUID, coordinator_did: str, limit: int = 5) -> list[dict]:
    """
    Auto-recruit best agents for a swarm based on required capabilities.
    Uses the capability router to find qualified agents.
    """
    async with get_db() as conn:
        swarm = await conn.fetchrow(
            "SELECT * FROM swarms WHERE swarm_id = $1", swarm_id,
        )
    if swarm is None:
        raise ValueError(f"Swarm not found: {swarm_id}")
    if swarm["coordinator_did"] != coordinator_did:
        raise PermissionError("Only the coordinator can recruit")

    caps = _parse_text_array(swarm.get("required_capabilities"))
    if not caps:
        return []

    from .capability_router import find_best_agents
    candidates = await find_best_agents(
        required_capabilities=caps,
        limit=limit,
        min_trust_score=0.3,
    )

    # Filter out existing members
    async with get_db() as conn:
        existing = await conn.fetch(
            "SELECT agent_did FROM swarm_members WHERE swarm_id = $1",
            swarm_id,
        )
    existing_dids = {r["agent_did"] for r in existing}

    eligible = [
        {
            "agent_did": c.agent_did,
            "display_name": c.display_name,
            "score": c.score,
            "trust_score": c.trust_score,
            "missing_capabilities": c.missing_capabilities,
        }
        for c in candidates
        if c.agent_did not in existing_dids
    ]

    return eligible


# ── Execution ─────────────────────────────────────────────────────────────────

async def activate_swarm(swarm_id: UUID, coordinator_did: str) -> dict:
    """
    Transition swarm from FORMING to ACTIVE.
    Assigns subtasks to members based on strategy.
    """
    async with transaction() as conn:
        swarm = await conn.fetchrow(
            "SELECT * FROM swarms WHERE swarm_id = $1 FOR UPDATE", swarm_id,
        )
        if swarm is None:
            raise ValueError(f"Swarm not found: {swarm_id}")
        if swarm["coordinator_did"] != coordinator_did:
            raise PermissionError("Only the coordinator can activate")
        if swarm["status"] != "forming":
            raise ValueError(f"Swarm cannot be activated (status={swarm['status']})")

        members = await conn.fetch(
            """
            SELECT agent_did FROM swarm_members
            WHERE swarm_id = $1 AND status = 'active' AND role = 'worker'
            ORDER BY joined_at
            """,
            swarm_id,
        )
        if not members:
            raise ValueError("Swarm needs at least one worker member")

        subtasks = await conn.fetch(
            "SELECT * FROM swarm_subtasks WHERE swarm_id = $1 ORDER BY sequence, created_at",
            swarm_id,
        )

        strategy = swarm["strategy"]
        worker_dids = [m["agent_did"] for m in members]

        if strategy in ("parallel", "pipeline"):
            # Assign subtasks round-robin to workers
            for i, st in enumerate(subtasks):
                assigned = worker_dids[i % len(worker_dids)]
                await conn.execute(
                    """
                    UPDATE swarm_subtasks
                    SET assigned_did = $2, status = $3
                    WHERE subtask_id = $1
                    """,
                    st["subtask_id"],
                    assigned,
                    "assigned" if strategy == "parallel" else ("assigned" if i == 0 else "pending"),
                )
                # Link member to subtask
                await conn.execute(
                    """
                    UPDATE swarm_members
                    SET subtask_id = $3
                    WHERE swarm_id = $1 AND agent_did = $2
                    """,
                    swarm_id, assigned, st["subtask_id"],
                )

        elif strategy in ("consensus", "competitive"):
            # All workers get the same task (first subtask)
            if subtasks:
                first_subtask = subtasks[0]
                for worker_did in worker_dids:
                    await conn.execute(
                        """
                        UPDATE swarm_members
                        SET subtask_id = $3
                        WHERE swarm_id = $1 AND agent_did = $2
                        """,
                        swarm_id, worker_did, first_subtask["subtask_id"],
                    )
                await conn.execute(
                    "UPDATE swarm_subtasks SET status = 'assigned' WHERE subtask_id = $1",
                    first_subtask["subtask_id"],
                )

        # Activate swarm
        await conn.execute(
            """
            UPDATE swarms
            SET status = 'active', started_at = CURRENT_TIMESTAMP
            WHERE swarm_id = $1
            """,
            swarm_id,
        )

    await emit_event("SWARM_ACTIVATED", coordinator_did, {
        "swarm_id": str(swarm_id),
        "strategy": strategy,
        "member_count": len(members),
        "subtask_count": len(subtasks),
    })

    return await get_swarm(swarm_id)


async def submit_subtask_result(
    swarm_id: UUID,
    subtask_id: UUID,
    agent_did: str,
    result: dict,
) -> dict:
    """
    Worker submits result for their assigned subtask.
    Auto-checks if all subtasks are done and triggers aggregation.
    """
    async with transaction() as conn:
        # Verify membership and assignment
        member = await conn.fetchrow(
            "SELECT role, subtask_id FROM swarm_members WHERE swarm_id = $1 AND agent_did = $2",
            swarm_id, agent_did,
        )
        if member is None:
            raise ValueError("Not a member of this swarm")

        subtask = await conn.fetchrow(
            "SELECT * FROM swarm_subtasks WHERE subtask_id = $1 AND swarm_id = $2",
            subtask_id, swarm_id,
        )
        if subtask is None:
            raise ValueError(f"Subtask not found: {subtask_id}")
        if subtask["assigned_did"] != agent_did and subtask["assigned_did"] is not None:
            raise PermissionError("This subtask is assigned to another agent")
        if subtask["status"] in ("completed", "failed"):
            raise ValueError(f"Subtask already {subtask['status']}")

        # Store result
        await conn.execute(
            """
            UPDATE swarm_subtasks
            SET result = $2::jsonb, status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE subtask_id = $1
            """,
            subtask_id,
            json.dumps(result),
        )

        # Mark member as completed
        await conn.execute(
            """
            UPDATE swarm_members
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE swarm_id = $1 AND agent_did = $2
            """,
            swarm_id, agent_did,
        )

        # Check swarm strategy for pipeline advancement
        swarm = await conn.fetchrow(
            "SELECT strategy FROM swarms WHERE swarm_id = $1", swarm_id,
        )
        if swarm["strategy"] == "pipeline":
            # Activate the next pending subtask in sequence
            next_subtask = await conn.fetchrow(
                """
                SELECT subtask_id FROM swarm_subtasks
                WHERE swarm_id = $1 AND status = 'pending'
                ORDER BY sequence ASC
                LIMIT 1
                """,
                swarm_id,
            )
            if next_subtask:
                await conn.execute(
                    "UPDATE swarm_subtasks SET status = 'assigned' WHERE subtask_id = $1",
                    next_subtask["subtask_id"],
                )

        # Check if all subtasks are done
        pending_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM swarm_subtasks
            WHERE swarm_id = $1 AND status NOT IN ('completed', 'failed')
            """,
            swarm_id,
        )

    await emit_event("SWARM_SUBTASK_COMPLETED", agent_did, {
        "swarm_id": str(swarm_id),
        "subtask_id": str(subtask_id),
    })

    # Record reputation event
    await record_event(agent_did, "task_completed", {
        "swarm_id": str(swarm_id),
        "subtask_id": str(subtask_id),
    })

    # Auto-aggregate if all subtasks done
    if pending_count == 0:
        await _aggregate_results(swarm_id)

    return _row_to_subtask({
        **dict(subtask),
        "result": result,
        "status": "completed",
    })


async def _aggregate_results(swarm_id: UUID) -> None:
    """
    Aggregate all subtask results into a swarm result.
    Strategy determines aggregation method.
    """
    async with transaction() as conn:
        swarm = await conn.fetchrow(
            "SELECT * FROM swarms WHERE swarm_id = $1 FOR UPDATE", swarm_id,
        )
        if swarm is None or swarm["status"] not in ("active",):
            return

        await conn.execute(
            "UPDATE swarms SET status = 'aggregating' WHERE swarm_id = $1",
            swarm_id,
        )

        subtasks = await conn.fetch(
            """
            SELECT * FROM swarm_subtasks
            WHERE swarm_id = $1 AND status = 'completed'
            ORDER BY sequence
            """,
            swarm_id,
        )

        strategy = swarm["strategy"]
        results = [_decode_json(s["result"]) for s in subtasks]

        if strategy == "parallel":
            aggregation = {
                "type": "parallel_merge",
                "subtask_results": [
                    {"subtask_id": str(s["subtask_id"]), "task_type": s["task_type"], "result": r}
                    for s, r in zip(subtasks, results)
                ],
                "count": len(results),
            }
            summary = f"Parallel swarm completed: {len(results)} subtask(s) merged"

        elif strategy == "pipeline":
            aggregation = {
                "type": "pipeline_chain",
                "pipeline": [
                    {"sequence": s["sequence"], "task_type": s["task_type"], "result": r}
                    for s, r in zip(subtasks, results)
                ],
                "final_output": results[-1] if results else {},
            }
            summary = f"Pipeline completed: {len(results)} stage(s)"

        elif strategy == "consensus":
            aggregation = {
                "type": "consensus_vote",
                "votes": [
                    {"agent_did": s["assigned_did"], "result": r}
                    for s, r in zip(subtasks, results)
                ],
                "count": len(results),
            }
            summary = f"Consensus reached from {len(results)} vote(s)"

        elif strategy == "competitive":
            # First completed result wins (already sorted by sequence)
            winner = subtasks[0] if subtasks else None
            aggregation = {
                "type": "competitive_winner",
                "winner_agent": winner["assigned_did"] if winner else None,
                "result": results[0] if results else {},
                "total_submissions": len(results),
            }
            summary = f"Competition won by {winner['assigned_did']}" if winner else "No winner"

        else:
            aggregation = {"type": "unknown", "results": results}
            summary = "Swarm completed"

        # Store aggregated result
        await conn.execute(
            """
            INSERT INTO swarm_results (swarm_id, aggregation, summary)
            VALUES ($1, $2::jsonb, $3)
            """,
            swarm_id,
            json.dumps(aggregation),
            summary,
        )

        # Mark swarm completed
        await conn.execute(
            """
            UPDATE swarms
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE swarm_id = $1
            """,
            swarm_id,
        )

    # Distribute rewards
    await _distribute_rewards(swarm_id)

    coordinator_did = swarm["coordinator_did"]
    await emit_event("SWARM_COMPLETED", coordinator_did, {
        "swarm_id": str(swarm_id),
        "summary": summary,
    })

    logger.info("Swarm %s completed: %s", swarm_id, summary)


async def _distribute_rewards(swarm_id: UUID) -> None:
    """
    Distribute reward pool to swarm members who completed their subtasks.
    Equal split among completed workers.
    """
    async with get_db() as conn:
        swarm = await conn.fetchrow(
            "SELECT reward_pool, coordinator_did FROM swarms WHERE swarm_id = $1",
            swarm_id,
        )
        if not swarm or swarm["reward_pool"] <= 0:
            return

        completed_members = await conn.fetch(
            """
            SELECT agent_did FROM swarm_members
            WHERE swarm_id = $1 AND status = 'completed' AND role = 'worker'
            """,
            swarm_id,
        )

    if not completed_members:
        # Refund if no workers completed
        try:
            await token_service.escrow_refund(swarm_id)
        except ValueError:
            pass
        return

    # Release escrow and distribute equally
    try:
        # Release to coordinator first, then distribute
        coordinator_did = swarm["coordinator_did"]
        reward_per_member = swarm["reward_pool"] // len(completed_members)

        if reward_per_member > 0:
            for member in completed_members:
                # Mint reward directly to each worker (escrow covers the pool)
                await token_service.mint(
                    agent_did=member["agent_did"],
                    token_type="WORK",
                    amount=reward_per_member,
                    tx_type="TASK_BOUNTY",
                    reference_id=f"swarm_reward:{swarm_id}:{member['agent_did']}",
                )

        # Release escrow (burn the held amount since we minted directly)
        try:
            await token_service.escrow_refund(swarm_id)
        except ValueError:
            pass

    except Exception as exc:
        logger.warning("Swarm reward distribution failed for %s: %s", swarm_id, exc)


async def cancel_swarm(swarm_id: UUID, coordinator_did: str) -> dict:
    """Cancel a swarm. Refunds escrowed reward pool."""
    async with transaction() as conn:
        swarm = await conn.fetchrow(
            "SELECT * FROM swarms WHERE swarm_id = $1", swarm_id,
        )
        if swarm is None:
            raise ValueError(f"Swarm not found: {swarm_id}")
        if swarm["coordinator_did"] != coordinator_did:
            raise PermissionError("Only the coordinator can cancel")
        if swarm["status"] in ("completed", "cancelled"):
            raise ValueError(f"Swarm already {swarm['status']}")

        await conn.execute(
            """
            UPDATE swarms
            SET status = 'cancelled', completed_at = CURRENT_TIMESTAMP
            WHERE swarm_id = $1
            """,
            swarm_id,
        )

    # Refund escrowed reward pool
    try:
        await token_service.escrow_refund(swarm_id)
    except ValueError:
        pass

    await emit_event("SWARM_CANCELLED", coordinator_did, {
        "swarm_id": str(swarm_id),
    })

    return {"swarm_id": str(swarm_id), "status": "cancelled"}


async def get_swarm_result(swarm_id: UUID) -> dict | None:
    """Get the aggregated result for a completed swarm."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM swarm_results WHERE swarm_id = $1 ORDER BY created_at DESC LIMIT 1",
            swarm_id,
        )
    if row is None:
        return None
    return {
        "result_id": row["result_id"],
        "swarm_id": row["swarm_id"],
        "aggregation": _decode_json(row["aggregation"]),
        "summary": row.get("summary"),
        "created_at": row["created_at"],
    }
