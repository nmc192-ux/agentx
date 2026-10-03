"""
Integration tests: the automatic-release job (src/jobs/auto_release.py)
against REAL local Postgres. Sprint 12, S12-7 (E6).

Items are made through the API, then aged on the row; the job compares them
with the database clock. No money path is mocked.

What is proven:
  • a due task result, contract delivery and bounty (scored → winner,
    unscored → creator) are each released by one run; a second run changes
    nothing
  • items not yet due, and already-settled items, are left alone
  • several runs at once still release each item once
  • one item failing is logged and skipped; the others are released, and the
    next run releases it
  • tokens are conserved throughout

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
import pytest_asyncio

from src.services.auto_release import AUTO_RELEASE_DAYS

from .support import START_BALANCE, balance, total_tokens
from .test_bounty_deadline_db import move_deadline as move_bounty_deadline
from .test_bounty_escrow_db import POOL, bounty_row, evaluate, open_bounty, submit
from .test_contract_deadline_db import age_delivery, submitted_contract
from .test_contract_escrow_db import BUDGET, contract_row
from .test_task_approval_db import (  # noqa: F401  (autouse fixtures)
    in_review_task,
    no_task_rate_limit,
    submitted_ago,
    treasury,
)
from .test_task_escrow_db import task_row

pytestmark = pytest.mark.integration   # skipped unless --db is given

DUE = f"{AUTO_RELEASE_DAYS} days 1 minute"
NOT_DUE = f"{AUTO_RELEASE_DAYS} days -1 minute"
BOUNTY_DUE = f"-{AUTO_RELEASE_DAYS} days -1 minute"
BOUNTY_NOT_DUE = f"-{AUTO_RELEASE_DAYS} days 1 minute"


@pytest_asyncio.fixture(autouse=True)
async def only_this_tests_items(pool):
    """The test database is shared by the whole run: make every item other
    test files left behind not yet due, so a run here sees only its own."""
    await pool.execute(
        "UPDATE tasks SET submitted_at = CURRENT_TIMESTAMP WHERE status = 'in_review'")
    await pool.execute(
        "UPDATE contract_results SET submitted_at = CURRENT_TIMESTAMP WHERE contract_id IN "
        "(SELECT contract_id FROM contracts WHERE status = 'submitted')")
    await pool.execute(
        "UPDATE capability_bounties SET deadline = CURRENT_TIMESTAMP + interval '1 day' "
        "WHERE status IN ('open', 'evaluating')")


async def _run():
    from src.jobs.auto_release import run_auto_release
    return await run_auto_release()


async def _world(client, pool, agents) -> dict:
    """One due and one not-due item of every kind."""
    creator = await agents("creator", START_BALANCE * 4, age_days=2)
    w = {"creator": creator}
    for name in ("task_worker", "task_waiting", "contractor", "contract_waiting",
                 "bounty_winner", "bounty_waiting", "bounty_unscored"):
        w[name] = await agents(name.replace("_", "-"), 0)

    w["task_due"] = await in_review_task(client, creator, w["task_worker"])
    w["task_not_due"] = await in_review_task(client, creator, w["task_waiting"])
    await submitted_ago(pool, w["task_due"], DUE)
    await submitted_ago(pool, w["task_not_due"], NOT_DUE)

    w["contract_due"] = await submitted_contract(client, creator, w["contractor"])
    w["contract_not_due"] = await submitted_contract(client, creator, w["contract_waiting"])
    await age_delivery(pool, w["contract_due"], DUE)
    await age_delivery(pool, w["contract_not_due"], NOT_DUE)

    w["bounty_scored"] = await open_bounty(client, creator)
    sub = await submit(client, w["bounty_scored"], w["bounty_winner"])
    await evaluate(client, w["bounty_scored"], sub, creator, 0.8)
    w["bounty_empty"] = await open_bounty(client, creator)
    await submit(client, w["bounty_empty"], w["bounty_unscored"])
    w["bounty_not_due"] = await open_bounty(client, creator)
    sub = await submit(client, w["bounty_not_due"], w["bounty_waiting"])
    await evaluate(client, w["bounty_not_due"], sub, creator, 0.8)
    await move_bounty_deadline(pool, w["bounty_scored"], BOUNTY_DUE)
    await move_bounty_deadline(pool, w["bounty_empty"], BOUNTY_DUE)
    await move_bounty_deadline(pool, w["bounty_not_due"], BOUNTY_NOT_DUE)
    return w


async def _assert_released_once(pool, w, creator_before: int):
    assert (await task_row(pool, w["task_due"]))["status"] == "COMPLETED"
    assert (await task_row(pool, w["task_not_due"]))["status"] == "in_review"
    assert (await contract_row(pool, w["contract_due"]))["status"] == "completed"
    assert (await contract_row(pool, w["contract_not_due"]))["status"] == "submitted"
    assert (await bounty_row(pool, w["bounty_scored"]))["status"] == "rewarded"
    assert (await bounty_row(pool, w["bounty_empty"]))["status"] == "cancelled"
    assert (await bounty_row(pool, w["bounty_not_due"]))["status"] == "evaluating"

    assert await balance(pool, w["task_worker"]) > 0
    assert await balance(pool, w["contractor"]) == BUDGET
    assert await balance(pool, w["bounty_winner"]) == POOL
    for waiting in ("task_waiting", "contract_waiting", "bounty_waiting", "bounty_unscored"):
        assert await balance(pool, w[waiting]) in (0, None), waiting
    # Only the unscored bounty's pool came back to the creator.
    assert await balance(pool, w["creator"]) == creator_before + POOL


async def test_due_items_are_released_once_and_others_left_alone(client, pool, agents):
    w = await _world(client, pool, agents)
    before = await total_tokens(pool)
    creator_before = await balance(pool, w["creator"])
    worker_paid = (await task_row(pool, w["task_due"]))["escrowed_reward"]

    first = await _run()

    assert first["errors"] == []
    for kind, released in (("tasks", 1), ("contracts", 1), ("bounties", 2)):
        assert first[kind] == {"released": released, "skipped": 0, "failed": 0}, (kind, first)
    await _assert_released_once(pool, w, creator_before)
    assert await balance(pool, w["task_worker"]) == worker_paid

    second = await _run()

    assert second["errors"] == []
    for kind in ("tasks", "contracts", "bounties"):
        assert second[kind] == {"released": 0, "skipped": 0, "failed": 0}, (kind, second)
    await _assert_released_once(pool, w, creator_before)
    assert await balance(pool, w["task_worker"]) == worker_paid
    assert await total_tokens(pool) == before


async def test_runs_at_the_same_time_release_each_item_once(client, pool, agents):
    w = await _world(client, pool, agents)
    before = await total_tokens(pool)
    creator_before = await balance(pool, w["creator"])
    worker_paid = (await task_row(pool, w["task_due"]))["escrowed_reward"]

    results = await asyncio.gather(*[_run() for _ in range(4)])

    for kind, released in (("tasks", 1), ("contracts", 1), ("bounties", 2)):
        assert sum(r[kind]["released"] for r in results) == released, (kind, results)
        assert sum(r[kind]["failed"] for r in results) == 0, (kind, results)
    await _assert_released_once(pool, w, creator_before)
    assert await balance(pool, w["task_worker"]) == worker_paid
    assert await total_tokens(pool) == before


async def test_one_failing_item_is_skipped_and_retried_next_run(
    client, pool, agents, monkeypatch,
):
    from src.services import task_service

    creator = await agents("creator", START_BALANCE, age_days=2)
    broken_worker = await agents("broken-worker", 0)
    fine_worker = await agents("fine-worker", 0)
    before = await total_tokens(pool)
    broken = await in_review_task(client, creator, broken_worker)
    fine = await in_review_task(client, creator, fine_worker)
    # The broken one is older, so the job meets it first.
    await submitted_ago(pool, broken, f"{AUTO_RELEASE_DAYS} days 2 minutes")
    await submitted_ago(pool, fine, DUE)

    real_release = task_service.release_overdue_result

    async def flaky(task_id: UUID):
        if task_id == UUID(broken):
            raise RuntimeError("ledger unavailable")
        return await real_release(task_id)

    monkeypatch.setattr(task_service, "release_overdue_result", flaky)
    first = await _run()

    assert first["tasks"] == {"released": 1, "skipped": 0, "failed": 1}
    assert (await task_row(pool, broken))["status"] == "in_review"
    assert (await task_row(pool, fine))["status"] == "COMPLETED"
    assert await balance(pool, broken_worker) in (0, None)

    monkeypatch.setattr(task_service, "release_overdue_result", real_release)
    second = await _run()

    assert second["tasks"] == {"released": 1, "skipped": 0, "failed": 0}
    assert (await task_row(pool, broken))["status"] == "COMPLETED"
    assert await balance(pool, broken_worker) > 0
    assert await total_tokens(pool) == before


async def test_an_item_settled_after_the_query_is_skipped(client, pool, agents, monkeypatch):
    """The creator approves between the job's query and its release call:
    the release function refuses, the job counts it skipped, nothing more moves."""
    from src.jobs import auto_release

    creator = await agents("creator", START_BALANCE, age_days=2)
    worker = await agents("worker", 0)
    before = await total_tokens(pool)
    task_id = await in_review_task(client, creator, worker)
    await submitted_ago(pool, task_id, DUE)

    real_due_ids = auto_release._due_ids

    async def due_then_approved(query: str, offset: int = 0):
        ids = await real_due_ids(query, offset)
        if UUID(task_id) in ids:
            resp = await client.post(f"/tasks/{task_id}/approve", headers=creator.headers)
            assert resp.status_code == 200, resp.text
        return ids

    monkeypatch.setattr(auto_release, "_due_ids", due_then_approved)
    reward = (await task_row(pool, task_id))["escrowed_reward"]
    summary = await _run()

    assert summary["tasks"] == {"released": 0, "skipped": 1, "failed": 0}
    assert (await task_row(pool, task_id))["status"] == "COMPLETED"
    assert await balance(pool, worker) == reward > 0
    assert await total_tokens(pool) == before


async def test_stuck_items_at_the_head_do_not_starve_a_due_item(client, pool, agents, monkeypatch):
    """S12-14a: with a page of one and the two oldest candidates failing every
    time, the due item behind them is still released in the same run."""
    from src.jobs import auto_release
    from src.services import task_service

    creator = await agents("creator", START_BALANCE, age_days=2)
    stuck_a, stuck_b, fine_worker = [await agents(n, 0) for n in ("stuck-a", "stuck-b", "fine")]
    before = await total_tokens(pool)
    stuck = [await in_review_task(client, creator, w) for w in (stuck_a, stuck_b)]
    fine = await in_review_task(client, creator, fine_worker)
    await submitted_ago(pool, stuck[0], f"{AUTO_RELEASE_DAYS} days 3 minutes")
    await submitted_ago(pool, stuck[1], f"{AUTO_RELEASE_DAYS} days 2 minutes")
    await submitted_ago(pool, fine, DUE)

    real_release = task_service.release_overdue_result

    async def flaky(task_id: UUID):
        if str(task_id) == stuck[0]:
            raise RuntimeError("ledger unavailable")
        if str(task_id) == stuck[1]:
            raise task_service.TaskConflictError("refused")
        return await real_release(task_id)

    monkeypatch.setattr(task_service, "release_overdue_result", flaky)
    monkeypatch.setattr(auto_release, "BATCH_LIMIT", 1)
    summary = await _run()

    assert summary["tasks"] == {"released": 1, "skipped": 1, "failed": 1}
    assert (await task_row(pool, fine))["status"] == "COMPLETED"
    assert await balance(pool, fine_worker) > 0
    for task_id in stuck:
        assert (await task_row(pool, task_id))["status"] == "in_review"
    assert await total_tokens(pool) == before


async def test_old_items_the_rules_exclude_are_never_released(client, pool, agents):
    """S12-14a: however old they are, the job pays nothing for a delivery
    that is disputed, a result the creator rejected, a task that was only
    backdated (no result under review), or a bounty with no deadline."""
    creator = await agents("creator", START_BALANCE * 4, age_days=2)
    contractor, worker, idle_worker, hunter = [
        await agents(n, 0) for n in ("contractor", "worker", "idle-worker", "hunter")
    ]
    before = await total_tokens(pool)
    old = f"{AUTO_RELEASE_DAYS * 10} days"

    disputed = await submitted_contract(client, creator, contractor)
    resp = await client.post(
        f"/contracts/{disputed}/dispute", json={"reason": "not what was asked"},
        headers=creator.headers,
    )
    assert resp.status_code == 201, resp.text
    await age_delivery(pool, disputed, old)

    rejected = await in_review_task(client, creator, worker)
    resp = await client.post(
        f"/tasks/{rejected}/reject", json={"reason": "empty"}, headers=creator.headers)
    assert resp.status_code == 200, resp.text
    # Even with a submission time forced back onto the row.
    await submitted_ago(pool, rejected, old)

    undelivered = await in_review_task(client, creator, idle_worker)
    await pool.execute(
        "UPDATE task_results SET verification_status = 'rejected' WHERE task_id = $1",
        UUID(undelivered),
    )
    await submitted_ago(pool, undelivered, old)   # 'in_review', due, nothing pending

    no_deadline = await open_bounty(client, creator)
    sub = await submit(client, no_deadline, hunter)
    await evaluate(client, no_deadline, sub, creator, 0.9)
    await move_bounty_deadline(pool, no_deadline, None)

    creator_before = await balance(pool, creator)
    for _ in range(2):
        summary = await _run()
        assert summary["errors"] == []
        assert summary["contracts"] == {"released": 0, "skipped": 0, "failed": 0}
        assert summary["bounties"] == {"released": 0, "skipped": 0, "failed": 0}
        # The task with nothing pending is a candidate; the service refuses it.
        assert summary["tasks"] == {"released": 0, "skipped": 1, "failed": 0}

    assert (await contract_row(pool, disputed))["status"] == "disputed"
    assert (await task_row(pool, rejected))["status"] == "assigned"
    assert (await task_row(pool, undelivered))["status"] == "in_review"
    assert (await bounty_row(pool, no_deadline))["status"] == "evaluating"
    for agent in (contractor, worker, idle_worker, hunter):
        assert await balance(pool, agent) in (0, None)
    assert await balance(pool, creator) == creator_before
    assert await total_tokens(pool) == before
