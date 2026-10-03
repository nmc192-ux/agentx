"""
Integration tests: creator approval of task results against REAL local Postgres
Sprint 12, S12-2 (E1, decision D2c) — the proof behind switching `tasks` back on.

Every request goes HTTP → routers/tasks.py → task_service / token_service →
Postgres; the automatic release is called as the scheduled job will call it
(task_service.release_overdue_result). No money path is mocked.

What is proven:
  • submitting a result pays nothing: the task is 'in_review', escrow intact
  • only the task's creator can approve or reject — not the executor, not a
    stranger, not a FOUNDER, not an anonymous caller
  • a reward is paid once, however approvals, rejections and the automatic
    release race, and only to the executor on the task row
  • a rejection moves no token and never lets the creator take the reward back
  • the automatic release pays only a result left unanswered for
    AUTO_RELEASE_DAYS by the database clock; nothing a caller sends, and no
    route, can bring it forward
  • tokens are conserved throughout

Run (needs local Postgres with trust auth for the current OS user):
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

from .support import START_BALANCE, Agent, balance, total_tokens
from .test_task_escrow_db import assigned_task, open_task, releases, task_row, trust_events

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest_asyncio.fixture(autouse=True)
async def treasury(pool):
    from src.services import economy_service
    await economy_service.initialize_treasury()


@pytest.fixture(autouse=True)
def no_task_rate_limit(monkeypatch):
    from src.middleware.rate_limits import limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)


async def in_review_task(client, creator: Agent, executor: Agent, reward: int = 100) -> str:
    task_id = await assigned_task(client, creator, executor, reward)
    resp = await client.post(
        f"/tasks/{task_id}/result", json={"result_payload": {"done": True}},
        headers=executor.headers,
    )
    assert resp.status_code == 201, resp.text
    return task_id


async def submitted_ago(pool, task_id: str, interval: str) -> None:
    """Move the submission into the past (the release reads the DB clock)."""
    await pool.execute(
        "UPDATE tasks SET submitted_at = CURRENT_TIMESTAMP - $2::text::interval WHERE task_id = $1",
        UUID(task_id), interval,
    )


async def result_states(pool, task_id: str) -> list[str]:
    return [r["verification_status"] for r in await pool.fetch(
        "SELECT verification_status FROM task_results WHERE task_id = $1 "
        "ORDER BY created_at, result_id", UUID(task_id),
    )]


# ── Submitting pays nothing ───────────────────────────────────────────────────

async def test_a_submitted_result_is_held_for_review_and_pays_nothing(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=2)
    executor = await agents("executor", 0)
    before = await total_tokens(pool)
    task_id = await assigned_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]

    resp = await client.post(
        f"/tasks/{task_id}/result", json={"result_payload": {"x": 1}}, headers=executor.headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["verification_status"] == "pending" and body["reward_released"] == 0

    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("in_review", escrowed)
    assert await balance(pool, executor) == 0
    assert await releases(pool, task_id) == 0
    assert await trust_events(pool, executor) == 0
    assert await total_tokens(pool) == before

    # The creator can find it and sees when it would be released without them.
    listed = (await client.get("/tasks", params={"status": "in_review"})).json()
    mine = next(t for t in listed if t["task_id"] == task_id)
    assert mine["submitted_at"] and mine["auto_release_at"] > mine["submitted_at"]
    assert mine["executor_agent_id"] == str(executor.agent_id)


async def test_approval_pays_the_executor_once_and_counts_once(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=2)
    executor = await agents("executor", 0)
    before = await total_tokens(pool)
    task_id = await in_review_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]
    creator_after_escrow = await balance(pool, creator)

    resp = await client.post(f"/tasks/{task_id}/approve", headers=creator.headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["verification_status"] == "verified"
    assert resp.json()["reward_released"] == escrowed

    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("COMPLETED", 0)
    assert await balance(pool, executor) == escrowed
    assert await balance(pool, creator) == creator_after_escrow
    assert await releases(pool, task_id) == 1
    assert await trust_events(pool, executor) == 1
    assert await result_states(pool, task_id) == ["verified"]

    for again in ("approve", "reject"):
        resp = await client.post(f"/tasks/{task_id}/{again}", headers=creator.headers)
        assert resp.status_code == 409, resp.text
    assert await balance(pool, executor) == escrowed
    assert await releases(pool, task_id) == 1
    assert await trust_events(pool, executor) == 1
    assert await total_tokens(pool) == before


# ── Who may approve or reject ─────────────────────────────────────────────────

@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_only_the_creator_can_approve_or_reject(client, pool, agents, action):
    creator = await agents("creator", START_BALANCE, age_days=2)
    executor = await agents("executor", 0)
    attacker = await agents("attacker", 0)
    founder = await agents("founder", 0, role="FOUNDER")
    task_id = await in_review_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]

    for caller in (executor, attacker, founder):
        # Body fields naming the creator change nothing: the JWT caller decides.
        resp = await client.post(
            f"/tasks/{task_id}/{action}", headers=caller.headers,
            json={"creator_agent_did": creator.did, "agent_did": creator.did, "reason": "x"},
        )
        assert resp.status_code == 403, (caller.did, resp.text)
    assert (await client.post(f"/tasks/{task_id}/{action}")).status_code == 401

    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("in_review", escrowed)
    assert await result_states(pool, task_id) == ["pending"]
    assert await releases(pool, task_id) == 0
    assert await balance(pool, executor) == 0 and await balance(pool, attacker) == 0
    assert await trust_events(pool, executor) == 0


@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_nothing_to_review_means_409_and_no_payment(client, pool, agents, action):
    creator = await agents("creator", START_BALANCE)
    executor = await agents("executor", 0)
    before = await total_tokens(pool)

    open_id = await open_task(client, creator)
    assigned_id = await assigned_task(client, creator, executor)
    cancelled_id = await open_task(client, creator)
    assert (await client.post(
        f"/tasks/{cancelled_id}/cancel", headers=creator.headers)).status_code == 200

    for task_id in (open_id, assigned_id, cancelled_id):
        resp = await client.post(f"/tasks/{task_id}/{action}", headers=creator.headers)
        assert resp.status_code == 409, resp.text
        assert await releases(pool, task_id) == 0
    assert (await client.post(
        f"/tasks/00000000-0000-0000-0000-000000000000/{action}",
        headers=creator.headers)).status_code == 404
    assert await balance(pool, executor) == 0
    assert await total_tokens(pool) == before


async def test_a_direct_task_cannot_be_approved_by_anyone(client, pool, agents):
    """A direct task has no marketplace creator and no escrow: nobody passes."""
    requester = await agents("requester", START_BALANCE)
    executor = await agents("executor", 0)
    resp = await client.post(
        "/tasks/create", json={"executor_agent_did": executor.did, "task_type": "x"},
        headers=requester.headers,
    )
    assert resp.status_code == 201, resp.text
    task_id = resp.json()["task_id"]
    for caller in (requester, executor):
        for action in ("approve", "reject"):
            resp = await client.post(f"/tasks/{task_id}/{action}", headers=caller.headers)
            assert resp.status_code == 403, resp.text
    assert (await task_row(pool, task_id))["status"] == "PENDING"


async def test_a_task_under_review_cannot_be_moved_through_update(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    executor = await agents("executor", 0)
    founder = await agents("founder", 0, role="FOUNDER")
    task_id = await in_review_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]
    for caller in (executor, founder):
        for target in ("COMPLETED", "FAILED", "IN_PROGRESS"):
            resp = await client.post(
                f"/tasks/{task_id}/update", json={"status": target}, headers=caller.headers)
            assert resp.status_code == 409, resp.text
    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("in_review", escrowed)
    assert await releases(pool, task_id) == 0


# ── Races ─────────────────────────────────────────────────────────────────────

async def test_concurrent_approvals_pay_once(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=2)
    executor = await agents("executor", 0)
    before = await total_tokens(pool)
    task_id = await in_review_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]

    responses = await asyncio.gather(*[
        client.post(f"/tasks/{task_id}/approve", headers=creator.headers) for _ in range(12)
    ])
    assert sorted(r.status_code for r in responses) == [200] + [409] * 11

    assert await balance(pool, executor) == escrowed
    assert await releases(pool, task_id) == 1
    assert await trust_events(pool, executor) == 1
    assert await total_tokens(pool) == before


async def test_approve_racing_reject_ends_in_exactly_one_outcome(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=2)
    executor = await agents("executor", 0)
    before = await total_tokens(pool)
    task_id = await in_review_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]

    responses = await asyncio.gather(*[
        client.post(f"/tasks/{task_id}/{action}", headers=creator.headers)
        for action in ["approve", "reject"] * 6
    ])
    assert sorted(r.status_code for r in responses) == [200] + [409] * 11

    row = await task_row(pool, task_id)
    if row["status"] == "COMPLETED":
        assert row["escrowed_reward"] == 0 and await balance(pool, executor) == escrowed
        assert await releases(pool, task_id) == 1
        assert await result_states(pool, task_id) == ["verified"]
    else:
        assert (row["status"], row["escrowed_reward"]) == ("assigned", escrowed)
        assert await balance(pool, executor) == 0 and await releases(pool, task_id) == 0
        assert await result_states(pool, task_id) == ["rejected"]
    assert await total_tokens(pool) == before


async def test_approval_racing_the_automatic_release_pays_once(client, pool, agents):
    from src.services import task_service

    creator = await agents("creator", START_BALANCE, age_days=2)
    executor = await agents("executor", 0)
    before = await total_tokens(pool)
    task_id = await in_review_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]
    await submitted_ago(pool, task_id, "8 days")

    async def auto():
        try:
            return await task_service.release_overdue_result(UUID(task_id))
        except task_service.TaskConflictError:
            return "conflict"

    outcomes = await asyncio.gather(
        *[auto() for _ in range(6)],
        *[client.post(f"/tasks/{task_id}/approve", headers=creator.headers) for _ in range(6)],
    )
    paid = [o for o in outcomes[:6] if o != "conflict"] + [
        r for r in outcomes[6:] if r.status_code == 200]
    assert len(paid) == 1, outcomes

    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("COMPLETED", 0)
    assert await balance(pool, executor) == escrowed
    assert await releases(pool, task_id) == 1
    assert await trust_events(pool, executor) == 1
    assert await total_tokens(pool) == before


# ── Rejecting ─────────────────────────────────────────────────────────────────

async def test_rejection_moves_no_token_and_the_executor_can_resubmit(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=2)
    executor = await agents("executor", 0)
    before = await total_tokens(pool)
    task_id = await in_review_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]
    creator_after_escrow = await balance(pool, creator)

    resp = await client.post(
        f"/tasks/{task_id}/reject", json={"reason": "  missing the numbers  "},
        headers=creator.headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["verification_status"] == "rejected"
    assert resp.json()["review_note"] == "missing the numbers"
    assert resp.json()["reward_released"] == 0

    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("assigned", escrowed)
    assert await pool.fetchval(
        "SELECT submitted_at FROM tasks WHERE task_id = $1", UUID(task_id)) is None
    assert await balance(pool, creator) == creator_after_escrow
    assert await balance(pool, executor) == 0
    assert await releases(pool, task_id) == 0
    assert await trust_events(pool, executor) == 0

    # Rejecting is not a way to get the reward back: still no cancel, no refund.
    assert (await client.post(
        f"/tasks/{task_id}/cancel", headers=creator.headers)).status_code == 409
    # Nor to approve the rejected result later.
    assert (await client.post(
        f"/tasks/{task_id}/approve", headers=creator.headers)).status_code == 409
    assert await balance(pool, creator) == creator_after_escrow

    again = await client.post(
        f"/tasks/{task_id}/result", json={"result_payload": {"v": 2}}, headers=executor.headers)
    assert again.status_code == 201, again.text
    assert (await client.post(
        f"/tasks/{task_id}/approve", headers=creator.headers)).status_code == 200
    assert await result_states(pool, task_id) == ["rejected", "verified"]
    assert await balance(pool, executor) == escrowed
    assert await releases(pool, task_id) == 1
    assert await trust_events(pool, executor) == 1
    assert await total_tokens(pool) == before


async def test_reject_needs_no_body_and_bounds_the_reason(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    executor = await agents("executor", 0)
    task_id = await in_review_task(client, creator, executor)

    too_long = await client.post(
        f"/tasks/{task_id}/reject", json={"reason": "x" * 1001}, headers=creator.headers)
    assert too_long.status_code == 422
    assert (await task_row(pool, task_id))["status"] == "in_review"

    resp = await client.post(f"/tasks/{task_id}/reject", headers=creator.headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["review_note"] is None


# ── Reading results ───────────────────────────────────────────────────────────

async def test_results_are_for_the_creator_and_the_executor_only(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    executor = await agents("executor", 0)
    stranger = await agents("stranger", 0)
    task_id = await in_review_task(client, creator, executor)

    for caller in (creator, executor):
        resp = await client.get(f"/tasks/{task_id}/results", headers=caller.headers)
        assert resp.status_code == 200, resp.text
        (result,) = resp.json()
        assert result["result_payload"] == {"done": True}
        assert result["verification_status"] == "pending"
    assert (await client.get(
        f"/tasks/{task_id}/results", headers=stranger.headers)).status_code == 403
    assert (await client.get(f"/tasks/{task_id}/results")).status_code == 401
    assert (await client.get(
        "/tasks/00000000-0000-0000-0000-000000000000/results",
        headers=creator.headers)).status_code == 404


# ── Automatic release ─────────────────────────────────────────────────────────

async def test_automatic_release_only_after_the_period_and_only_once(client, pool, agents):
    from src.services import task_service
    from src.services.auto_release import AUTO_RELEASE_DAYS

    assert AUTO_RELEASE_DAYS == 7
    creator = await agents("creator", START_BALANCE, age_days=2)
    executor = await agents("executor", 0)
    before = await total_tokens(pool)
    task_id = await in_review_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]

    for ago in ("0 seconds", "6 days 23 hours 59 minutes"):
        await submitted_ago(pool, task_id, ago)
        with pytest.raises(task_service.TaskConflictError):
            await task_service.release_overdue_result(UUID(task_id))
        row = await task_row(pool, task_id)
        assert (row["status"], row["escrowed_reward"]) == ("in_review", escrowed)
        assert await releases(pool, task_id) == 0 and await balance(pool, executor) == 0

    await submitted_ago(pool, task_id, "7 days 1 minute")
    assert await task_service.release_overdue_result(UUID(task_id)) == escrowed

    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("COMPLETED", 0)
    assert await balance(pool, executor) == escrowed
    assert await releases(pool, task_id) == 1
    assert await trust_events(pool, executor) == 1
    assert await result_states(pool, task_id) == ["verified"]

    with pytest.raises(task_service.TaskConflictError):
        await task_service.release_overdue_result(UUID(task_id))
    assert await balance(pool, executor) == escrowed and await releases(pool, task_id) == 1
    # The creator's late approval pays nothing more.
    assert (await client.post(
        f"/tasks/{task_id}/approve", headers=creator.headers)).status_code == 409
    assert await total_tokens(pool) == before


async def test_concurrent_automatic_releases_pay_once(client, pool, agents):
    from src.services import task_service

    creator = await agents("creator", START_BALANCE, age_days=2)
    executor = await agents("executor", 0)
    before = await total_tokens(pool)
    task_id = await in_review_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]
    await submitted_ago(pool, task_id, "30 days")

    outcomes = await asyncio.gather(
        *[task_service.release_overdue_result(UUID(task_id)) for _ in range(10)],
        return_exceptions=True,
    )
    assert [o for o in outcomes if not isinstance(o, Exception)] == [escrowed]
    assert all(isinstance(o, task_service.TaskConflictError)
               for o in outcomes if isinstance(o, Exception))
    assert await balance(pool, executor) == escrowed
    assert await releases(pool, task_id) == 1
    assert await total_tokens(pool) == before


async def test_automatic_release_refuses_every_task_not_under_review(client, pool, agents):
    """Even with an old submission time forced onto the row, only 'in_review'
    releases; a missing submission time never does."""
    from src.services import task_service

    creator = await agents("creator", START_BALANCE)
    executor = await agents("executor", 0)
    before = await total_tokens(pool)

    open_id = await open_task(client, creator)
    assigned_id = await assigned_task(client, creator, executor)
    cancelled_id = await open_task(client, creator)
    assert (await client.post(
        f"/tasks/{cancelled_id}/cancel", headers=creator.headers)).status_code == 200
    for task_id in (open_id, assigned_id, cancelled_id):
        await submitted_ago(pool, task_id, "60 days")
        with pytest.raises(task_service.TaskConflictError):
            await task_service.release_overdue_result(UUID(task_id))
        assert await releases(pool, task_id) == 0

    no_time = await in_review_task(client, creator, executor)
    await pool.execute("UPDATE tasks SET submitted_at = NULL WHERE task_id = $1", UUID(no_time))
    with pytest.raises(task_service.TaskConflictError):
        await task_service.release_overdue_result(UUID(no_time))
    assert await releases(pool, no_time) == 0

    with pytest.raises(ValueError):
        await task_service.release_overdue_result(
            UUID("00000000-0000-0000-0000-000000000000"))
    assert await balance(pool, executor) == 0
    assert await total_tokens(pool) == before


async def test_a_rejection_restarts_the_release_period(client, pool, agents):
    from src.services import task_service

    creator = await agents("creator", START_BALANCE)
    executor = await agents("executor", 0)
    task_id = await in_review_task(client, creator, executor)
    await submitted_ago(pool, task_id, "6 days")
    assert (await client.post(
        f"/tasks/{task_id}/reject", headers=creator.headers)).status_code == 200

    # Rejected: nothing under review, however old the first submission was.
    with pytest.raises(task_service.TaskConflictError):
        await task_service.release_overdue_result(UUID(task_id))
    assert (await client.post(
        f"/tasks/{task_id}/result", json={"result_payload": {}},
        headers=executor.headers)).status_code == 201
    # Resubmitted: the period counts from the new submission.
    with pytest.raises(task_service.TaskConflictError):
        await task_service.release_overdue_result(UUID(task_id))
    assert await releases(pool, task_id) == 0 and await balance(pool, executor) == 0


async def test_no_route_releases_early(client, pool, agents):
    """The automatic release has no HTTP door, and no request field carries a time."""
    creator = await agents("creator", START_BALANCE)
    executor = await agents("executor", 0)
    task_id = await in_review_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]

    for path in ("release", "auto-release", "release_overdue", "complete", "payout"):
        for caller in (executor, creator):
            resp = await client.post(f"/tasks/{task_id}/{path}", headers=caller.headers)
            assert resp.status_code in (404, 405), (path, resp.status_code)
    # A resubmit carrying a forged submission time is refused outright.
    resp = await client.post(
        f"/tasks/{task_id}/result",
        json={"result_payload": {}, "submitted_at": "2000-01-01T00:00:00Z"},
        headers=executor.headers,
    )
    assert resp.status_code == 409
    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("in_review", escrowed)
    assert await releases(pool, task_id) == 0 and await balance(pool, executor) == 0


# ── Edges ─────────────────────────────────────────────────────────────────────

async def test_a_task_without_a_reward_follows_the_same_steps(client, pool, agents):
    creator = await agents("creator", None, age_days=2)
    executor = await agents("executor", None)
    task_id = await in_review_task(client, creator, executor, reward=0)

    resp = await client.post(f"/tasks/{task_id}/approve", headers=creator.headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["reward_released"] == 0
    assert (await task_row(pool, task_id))["status"] == "COMPLETED"
    assert await releases(pool, task_id) == 0
    assert await trust_events(pool, executor) == 0      # unfunded work earns no trust


async def test_in_review_without_a_pending_result_pays_nothing(client, pool, agents):
    """Fail closed: a row forced to 'in_review' with no result cannot be paid."""
    from src.services import task_service

    creator = await agents("creator", START_BALANCE)
    executor = await agents("executor", 0)
    task_id = await assigned_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]
    await pool.execute(
        "UPDATE tasks SET status = 'in_review', submitted_at = CURRENT_TIMESTAMP - INTERVAL "
        "'30 days' WHERE task_id = $1", UUID(task_id))

    assert (await client.post(
        f"/tasks/{task_id}/approve", headers=creator.headers)).status_code == 409
    with pytest.raises(task_service.TaskConflictError):
        await task_service.release_overdue_result(UUID(task_id))
    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("in_review", escrowed)
    assert await releases(pool, task_id) == 0 and await balance(pool, executor) == 0


async def test_database_accepts_in_review_and_still_refuses_junk(pool, agents):
    creator = await agents("creator", None)
    insert = (
        "INSERT INTO tasks (task_id, creator_agent_id, requester_agent_id, requester_agent_did, "
        "task_type, status) VALUES (gen_random_uuid(), $1, $1, $2, 'x', $3)"
    )
    await pool.execute(insert, creator.agent_id, creator.did, "in_review")
    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute(insert, creator.agent_id, creator.did, "submitted")
