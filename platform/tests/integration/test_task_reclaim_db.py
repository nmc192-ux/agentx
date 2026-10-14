"""
Integration tests: the task work deadline against REAL local Postgres
Sprint 21, BT-1 (decision D10, default b).

Every request goes HTTP → routers/tasks.py → task_service / token_service →
Postgres. No money path is mocked. Time is moved by back-dating the rows the
service reads (task_assignments.started_at, task_results.created_at); the
service itself compares them with the DATABASE clock and takes no time from
any caller.

What is proven:
  • a reclaim refunds the escrow to the creator exactly once, keeps the
    platform fee, marks the task 'cancelled' and the assignment 'failed',
    and writes one 'task_work_deadline_refund' ledger entry; tokens are
    conserved
  • it is refused (nothing changes) before the work deadline, while a result
    is under review, after the reward was paid, for an open, cancelled or
    direct task, a second time, for anyone but the creator, anonymously and
    while TASK_WORK_DAYS is 0
  • a rejection restarts the worker's clock
  • 10 concurrent reclaims refund once; a reclaim racing a result submission
    ends in exactly one outcome; a late submission, approval or automatic
    release after a reclaim pays nothing
  • no trust event is written (BT-3 adds that)

Run (needs local Postgres with trust auth for the current OS user):
    cd platform && .venv/bin/python -m pytest tests/integration/test_task_reclaim_db.py -v --db
"""
from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
import pytest_asyncio

from .support import START_BALANCE, Agent, balance, total_tokens
from .test_task_escrow_db import (
    assigned_task, ledger, open_task, releases, task_row, treasury_balance, trust_events,
)

pytestmark = pytest.mark.integration   # skipped unless --db is given

WORK_DAYS = 7
REFUND = "task_work_deadline_refund"
REWARD = 100
# The platform fee (250 bps, seeded by initialize_treasury) comes out of the
# escrow when the task is created: 100 posted → 98 held, 2 to the treasury.
ESCROW = REWARD - REWARD * 250 // 10_000


@pytest_asyncio.fixture(autouse=True)
async def treasury(pool):
    from src.services import economy_service
    await economy_service.initialize_treasury()


@pytest.fixture(autouse=True)
def no_task_rate_limit(monkeypatch):
    from src.middleware.rate_limits import limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)


@pytest.fixture(autouse=True)
def reclaim_on(monkeypatch):
    """The shipped default is 0 (off); these tests run with it on."""
    from src.config import get_settings
    monkeypatch.setattr(get_settings(), "task_work_days", WORK_DAYS)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def taken_ago(pool, task_id: str, interval: str) -> None:
    await pool.execute(
        "UPDATE task_assignments SET started_at = CURRENT_TIMESTAMP - $2::text::interval "
        "WHERE task_id = $1",
        UUID(task_id), interval,
    )


async def results_ago(pool, task_id: str, interval: str) -> None:
    await pool.execute(
        "UPDATE task_results SET created_at = CURRENT_TIMESTAMP - $2::text::interval "
        "WHERE task_id = $1",
        UUID(task_id), interval,
    )


async def overdue_task(client, pool, creator: Agent, executor: Agent, reward: int = 100) -> str:
    task_id = await assigned_task(client, creator, executor, reward)
    await taken_ago(pool, task_id, f"{WORK_DAYS} days 1 minute")
    return task_id


async def assignment(pool, task_id: str):
    return await pool.fetchrow(
        "SELECT status, started_at, completed_at FROM task_assignments WHERE task_id = $1",
        UUID(task_id),
    )


async def reclaim(client, task_id: str, caller: Agent | None):
    return await client.post(
        f"/tasks/{task_id}/reclaim", headers=caller.headers if caller else None,
    )


async def submit(client, task_id: str, executor: Agent):
    return await client.post(
        f"/tasks/{task_id}/result", json={"result_payload": {"done": True}},
        headers=executor.headers,
    )


# ── The happy path ────────────────────────────────────────────────────────────

async def test_reclaim_refunds_the_reward_once_and_keeps_the_fee(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0)
    before_total = await total_tokens(pool)
    task_id = await overdue_task(client, pool, creator, worker, 100)
    row = await task_row(pool, task_id)
    escrowed, fee = row["escrowed_reward"], row["task_fee"]
    assert escrowed == ESCROW and fee == REWARD - ESCROW
    treasury_before = await treasury_balance(pool)

    resp = await reclaim(client, task_id, creator)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "cancelled" and body["task_id"] == task_id
    assert body["executor_agent_id"] == str(worker.agent_id)

    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("cancelled", 0)
    assert row["task_fee"] == fee                        # the fee stays
    assert await treasury_balance(pool) == treasury_before
    assert await balance(pool, creator) == START_BALANCE - fee
    assert await balance(pool, worker) in (0, None)
    assert await ledger(pool, task_id, REFUND) == 1
    assert await ledger(pool, task_id, "escrow_refund") == 0
    assert await releases(pool, task_id) == 0
    a = await assignment(pool, task_id)
    assert a["status"] == "failed" and a["completed_at"] is not None
    assert await total_tokens(pool) == before_total
    assert await trust_events(pool, worker) == 0
    assert await trust_events(pool, creator) == 0

    # It shows as cancelled everywhere a task is read.
    assert (await client.get(f"/tasks/{task_id}")).json()["status"] == "cancelled"
    cancelled = (await client.get("/tasks", params={"status": "cancelled", "limit": 200})).json()
    assert task_id in [t["task_id"] for t in cancelled]


async def test_exactly_at_the_deadline_is_due(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0)
    task_id = await assigned_task(client, creator, worker)
    await taken_ago(pool, task_id, f"{WORK_DAYS} days 2 seconds")
    assert (await reclaim(client, task_id, creator)).status_code == 200


# ── Refusals: nothing changes ─────────────────────────────────────────────────

async def _unchanged(pool, task_id: str, status: str, escrow: int) -> None:
    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == (status, escrow)
    assert await ledger(pool, task_id, REFUND) == 0


async def test_too_early_is_refused(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0)
    task_id = await assigned_task(client, creator, worker)
    for interval in ("0 seconds", "1 day", f"{WORK_DAYS - 1} days 23 hours 59 minutes"):
        await taken_ago(pool, task_id, interval)
        resp = await reclaim(client, task_id, creator)
        assert resp.status_code == 409, (interval, resp.text)
        assert "still has time" in resp.json()["detail"]
    await _unchanged(pool, task_id, "assigned", ESCROW)
    assert (await assignment(pool, task_id))["status"] == "assigned"
    assert await balance(pool, creator) < START_BALANCE


async def test_no_assignment_time_is_refused(client, pool, agents):
    """Nothing to count from → not due (fails closed)."""
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0)
    task_id = await assigned_task(client, creator, worker)
    await pool.execute(
        "UPDATE task_assignments SET started_at = NULL WHERE task_id = $1", UUID(task_id),
    )
    assert (await reclaim(client, task_id, creator)).status_code == 409
    await _unchanged(pool, task_id, "assigned", ESCROW)


async def test_a_result_under_review_blocks_the_reclaim(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0)
    task_id = await overdue_task(client, pool, creator, worker)
    assert (await submit(client, task_id, worker)).status_code == 201
    await results_ago(pool, task_id, "30 days")          # however old
    resp = await reclaim(client, task_id, creator)
    assert resp.status_code == 409 and "status=in_review" in resp.json()["detail"]
    await _unchanged(pool, task_id, "in_review", ESCROW)


async def test_a_rejection_restarts_the_workers_clock(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0)
    task_id = await assigned_task(client, creator, worker)
    await taken_ago(pool, task_id, "30 days")
    assert (await submit(client, task_id, worker)).status_code == 201
    resp = await client.post(
        f"/tasks/{task_id}/reject", json={"reason": "no"}, headers=creator.headers,
    )
    assert resp.status_code == 200, resp.text
    # Rejected just now: the worker has WORK_DAYS again.
    resp = await reclaim(client, task_id, creator)
    assert resp.status_code == 409 and "still has time" in resp.json()["detail"]
    await _unchanged(pool, task_id, "assigned", ESCROW)

    # Rejected result older than the deadline: due.
    await results_ago(pool, task_id, f"{WORK_DAYS} days 1 minute")
    assert (await reclaim(client, task_id, creator)).status_code == 200
    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("cancelled", 0)
    assert await ledger(pool, task_id, REFUND) == 1


async def test_the_newest_result_counts_even_after_an_old_one(client, pool, agents):
    """Two rejected results: the clock runs from the newest."""
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0)
    task_id = await assigned_task(client, creator, worker)
    await taken_ago(pool, task_id, "40 days")
    for _ in range(2):
        assert (await submit(client, task_id, worker)).status_code == 201
        assert (await client.post(
            f"/tasks/{task_id}/reject", headers=creator.headers,
        )).status_code == 200
    await pool.execute(
        "UPDATE task_results SET created_at = CURRENT_TIMESTAMP - INTERVAL '20 days' "
        "WHERE result_id = (SELECT result_id FROM task_results WHERE task_id = $1 "
        "ORDER BY created_at LIMIT 1)",
        UUID(task_id),
    )
    assert (await reclaim(client, task_id, creator)).status_code == 409
    await _unchanged(pool, task_id, "assigned", ESCROW)


async def test_open_paid_cancelled_and_direct_tasks_cannot_be_reclaimed(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0, age_days=3)

    open_id = await open_task(client, creator)
    resp = await reclaim(client, open_id, creator)
    assert resp.status_code == 409 and "status=open" in resp.json()["detail"]
    await _unchanged(pool, open_id, "open", ESCROW)

    paid_id = await overdue_task(client, pool, creator, worker)
    assert (await submit(client, paid_id, worker)).status_code == 201
    assert (await client.post(f"/tasks/{paid_id}/approve", headers=creator.headers)).status_code == 200
    resp = await reclaim(client, paid_id, creator)
    assert resp.status_code == 409 and "status=COMPLETED" in resp.json()["detail"]
    await _unchanged(pool, paid_id, "COMPLETED", 0)
    assert await balance(pool, worker) == ESCROW

    cancelled_id = await open_task(client, creator)
    assert (await client.post(f"/tasks/{cancelled_id}/cancel", headers=creator.headers)).status_code == 200
    resp = await reclaim(client, cancelled_id, creator)
    assert resp.status_code == 409 and "status=cancelled" in resp.json()["detail"]
    assert await ledger(pool, cancelled_id, REFUND) == 0

    # A direct task has no marketplace creator: nobody passes the creator check.
    resp = await client.post(
        "/tasks/create",
        json={"executor_agent_did": worker.did, "task_type": "direct.test", "payload": {}},
        headers=creator.headers,
    )
    assert resp.status_code in (200, 201), resp.text
    direct_id = resp.json()["task_id"]
    assert (await reclaim(client, direct_id, creator)).status_code == 403

    assert (await reclaim(client, "00000000-0000-4000-8000-000000000000", creator)).status_code == 404


async def test_only_the_creator_can_reclaim(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0)
    stranger = await agents("stranger", START_BALANCE)
    founder = await agents("founder", START_BALANCE, role="FOUNDER")
    task_id = await overdue_task(client, pool, creator, worker)

    for who in (worker, stranger, founder):
        resp = await reclaim(client, task_id, who)
        assert resp.status_code == 403, (who.did, resp.text)
    assert (await reclaim(client, task_id, None)).status_code == 401
    await _unchanged(pool, task_id, "assigned", ESCROW)
    assert await balance(pool, stranger) == START_BALANCE

    # The creator still can, and only once.
    assert (await reclaim(client, task_id, creator)).status_code == 200
    resp = await reclaim(client, task_id, creator)
    assert resp.status_code == 409 and "status=cancelled" in resp.json()["detail"]
    assert await ledger(pool, task_id, REFUND) == 1


async def test_switched_off_refuses_and_moves_nothing(client, pool, agents, monkeypatch):
    from src.config import get_settings
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0)
    task_id = await overdue_task(client, pool, creator, worker)
    before = await total_tokens(pool)

    monkeypatch.setattr(get_settings(), "task_work_days", 0)
    resp = await reclaim(client, task_id, creator)
    assert resp.status_code == 409 and "switched off" in resp.json()["detail"]
    await _unchanged(pool, task_id, "assigned", ESCROW)
    assert await total_tokens(pool) == before

    # Read per request: switching it on needs no restart.
    monkeypatch.setattr(get_settings(), "task_work_days", WORK_DAYS)
    assert (await reclaim(client, task_id, creator)).status_code == 200


async def test_a_longer_setting_is_honoured(client, pool, agents, monkeypatch):
    from src.config import get_settings
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0)
    task_id = await overdue_task(client, pool, creator, worker)     # 7 days + 1 minute
    monkeypatch.setattr(get_settings(), "task_work_days", 14)
    resp = await reclaim(client, task_id, creator)
    assert resp.status_code == 409 and "14 days" in resp.json()["detail"]
    await _unchanged(pool, task_id, "assigned", ESCROW)


# ── After a reclaim, the worker cannot be paid ────────────────────────────────

async def test_after_a_reclaim_nothing_pays_the_worker(client, pool, agents):
    from src.services import task_service
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0)
    task_id = await overdue_task(client, pool, creator, worker)
    assert (await reclaim(client, task_id, creator)).status_code == 200
    before = await total_tokens(pool)

    late = await submit(client, task_id, worker)
    assert late.status_code == 409, late.text
    assert (await client.post(f"/tasks/{task_id}/approve", headers=creator.headers)).status_code == 409
    with pytest.raises(task_service.TaskConflictError):
        await task_service.release_overdue_result(UUID(task_id))
    # The worker cannot bid it back either: it is not open.
    resp = await client.post(
        f"/tasks/{task_id}/bid", json={"confidence": 0.9, "bid_price": 1}, headers=worker.headers,
    )
    assert resp.status_code in (400, 409, 422), resp.text

    assert await releases(pool, task_id) == 0
    assert await balance(pool, worker) in (0, None)
    assert await total_tokens(pool) == before
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM task_results WHERE task_id = $1", UUID(task_id),
    ) == 0


# ── Races ─────────────────────────────────────────────────────────────────────

async def test_concurrent_reclaims_refund_once(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0)
    task_id = await overdue_task(client, pool, creator, worker)
    fee = (await task_row(pool, task_id))["task_fee"]
    before = await total_tokens(pool)

    responses = await asyncio.gather(*[reclaim(client, task_id, creator) for _ in range(10)])
    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [409] * 9, codes

    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("cancelled", 0)
    assert await ledger(pool, task_id, REFUND) == 1
    assert await balance(pool, creator) == START_BALANCE - fee
    assert await total_tokens(pool) == before
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM task_assignments WHERE task_id = $1 AND status = 'failed'",
        UUID(task_id),
    ) == 1


@pytest.mark.parametrize("attempt", range(4))
async def test_reclaim_racing_a_submission_ends_in_exactly_one_outcome(client, pool, agents, attempt):
    """Either the reclaim wins (cancelled, refunded, the submission is 409) or
    the submission wins (in_review, escrow intact, the reclaim is 409). Never
    both, never neither."""
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0)
    task_id = await overdue_task(client, pool, creator, worker)
    before = await total_tokens(pool)

    async def late(coro, delay):
        await asyncio.sleep(delay)
        return await coro

    r1, r2 = await asyncio.gather(
        late(reclaim(client, task_id, creator), 0.0 if attempt % 2 else 0.005),
        late(submit(client, task_id, worker), 0.005 if attempt % 2 else 0.0),
    )
    row = await task_row(pool, task_id)
    refunds = await ledger(pool, task_id, REFUND)
    results = await pool.fetchval(
        "SELECT COUNT(*) FROM task_results WHERE task_id = $1", UUID(task_id),
    )
    if r1.status_code == 200:
        assert r2.status_code == 409, r2.text
        assert (row["status"], row["escrowed_reward"], refunds, results) == ("cancelled", 0, 1, 0)
    else:
        assert (r1.status_code, r2.status_code) == (409, 201), (r1.text, r2.text)
        assert (row["status"], row["escrowed_reward"], refunds, results) == ("in_review", ESCROW, 0, 1)
    assert await total_tokens(pool) == before


async def test_reclaim_racing_an_approval_pays_exactly_one_side(client, pool, agents):
    """A result is in and under review: a reclaim can never win against the
    approval, however they interleave."""
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0, age_days=3)
    task_id = await overdue_task(client, pool, creator, worker)
    assert (await submit(client, task_id, worker)).status_code == 201
    before = await total_tokens(pool)

    responses = await asyncio.gather(
        reclaim(client, task_id, creator),
        client.post(f"/tasks/{task_id}/approve", headers=creator.headers),
        reclaim(client, task_id, creator),
    )
    assert [r.status_code for r in responses] == [409, 200, 409], [r.text for r in responses]
    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("COMPLETED", 0)
    assert await ledger(pool, task_id, REFUND) == 0
    assert await releases(pool, task_id) == 1
    assert await balance(pool, worker) == ESCROW
    assert await total_tokens(pool) == before


# ── Nothing but the route reaches the service ─────────────────────────────────

async def test_no_other_path_reclaims(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    worker = await agents("worker", 0)
    task_id = await overdue_task(client, pool, creator, worker)
    for path in ("cancel", "withdraw", "refund", "reclaim-escrow", "deadline"):
        resp = await client.post(f"/tasks/{task_id}/{path}", headers=creator.headers)
        assert resp.status_code in (404, 405, 409), (path, resp.status_code)
    # /cancel in particular: an assigned task is not open.
    assert (await client.post(f"/tasks/{task_id}/cancel", headers=creator.headers)).status_code == 409
    await _unchanged(pool, task_id, "assigned", ESCROW)
