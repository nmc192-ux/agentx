"""
Integration tests: bounties stored with no deadline, against REAL local
Postgres. Phase C, Sprint 21, BT-2.

A bounty from before Sprint 12 has ``deadline IS NULL``. With the setting
LEGACY_BOUNTY_DAYS off (the default) nothing about it changes: it takes
submissions, is never released, and reads back with no deadline. With it set
to N days, every rule reads the bounty's deadline as created_at + N: no row is
written. Time is never mocked: a test moves ``created_at`` on the row and the
service compares with the database clock.

What is proven (with the rule on, unless said otherwise):
  • a legacy bounty older than N + AUTO_RELEASE_DAYS is released: to the
    top-scored submission, or back to the creator when nothing was scored;
    a younger one is held, including one past N but inside the release period
  • the stored deadline stays NULL and created_at is untouched
  • submissions close N days after creation; the creator can still score and pay
  • get / list report the effective deadline (null with the rule off)
  • the setting's number is honoured; an unusable one means off; off means
    today's behaviour, however old the bounty
  • the scheduled job releases the due legacy bounties and leaves the rest;
    a second run changes nothing; tokens are conserved
  • once, however concurrently
  • a new bounty's default deadline follows DEFAULT_BOUNTY_DAYS

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from src.config import get_settings
from src.services.auto_release import AUTO_RELEASE_DAYS
from src.services.markets.bounty_service import DEFAULT_BOUNTY_DAYS, BountyConflictError

from .support import START_BALANCE, balance, total_tokens
from .test_auto_release_job_db import only_this_tests_items  # noqa: F401  (autouse)
from .test_bounty_deadline_db import assert_held, payouts, release, submission_statuses, try_submit
from .test_bounty_escrow_db import POOL, bounty_row, count, evaluate, open_bounty, submit

pytestmark = pytest.mark.integration   # skipped unless --db is given

LEGACY_DAYS = DEFAULT_BOUNTY_DAYS                      # 30: the recommended value
RELEASE_AGE = LEGACY_DAYS + AUTO_RELEASE_DAYS          # 37 days: released from here
JUST_RELEASABLE = f"{RELEASE_AGE} days 1 minute"
NOT_YET_RELEASABLE = f"{RELEASE_AGE} days -1 minute"
JUST_CLOSED = f"{LEGACY_DAYS} days 1 minute"
STILL_OPEN = f"{LEGACY_DAYS} days -1 minute"


@pytest_asyncio.fixture
async def legacy_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "legacy_bounty_days", LEGACY_DAYS)


@pytest.fixture
async def creator(agents):
    return await agents("creator", START_BALANCE)


async def make_legacy(pool, bounty_id: str, age: str) -> None:
    """Turn a bounty into one from before the deadline rule: no deadline,
    created *age* (a Postgres interval) ago by the database clock."""
    await pool.execute(
        "UPDATE capability_bounties SET deadline = NULL, "
        "created_at = CURRENT_TIMESTAMP - $2::text::interval WHERE bounty_id = $1",
        UUID(bounty_id), age,
    )


async def stored(pool, bounty_id: str):
    return await pool.fetchrow(
        "SELECT deadline, created_at FROM capability_bounties WHERE bounty_id = $1",
        UUID(bounty_id))


async def effective_deadline(pool, bounty_id: str, days: int):
    return await pool.fetchval(
        "SELECT created_at + make_interval(days => $2) FROM capability_bounties "
        "WHERE bounty_id = $1", UUID(bounty_id), days)


# ── Release ───────────────────────────────────────────────────────────────────

async def test_an_old_legacy_bounty_is_paid_to_the_top_score_once(
        client, pool, agents, creator, legacy_on):
    before = await total_tokens(pool)
    low, high = await agents("low", 0), await agents("high", 0)
    bounty_id = await open_bounty(client, creator)
    low_sub, high_sub = await submit(client, bounty_id, low), await submit(client, bounty_id, high)
    await evaluate(client, bounty_id, low_sub, creator, 0.4)
    await evaluate(client, bounty_id, high_sub, creator, 0.9)
    await make_legacy(pool, bounty_id, JUST_RELEASABLE)
    was = await stored(pool, bounty_id)

    assert await release(bounty_id) == ("rewarded", POOL)

    row = await bounty_row(pool, bounty_id)
    assert row["status"] == "rewarded"
    assert await balance(pool, high) == POOL
    assert await balance(pool, low) == 0
    assert await balance(pool, creator) == START_BALANCE - POOL
    assert await payouts(pool, bounty_id) == 1
    assert await count(pool, "bounty_rewards", bounty_id) == 1
    assert await total_tokens(pool) == before
    # No data change: the row still has no deadline and its creation time.
    now = await stored(pool, bounty_id)
    assert now["deadline"] is None and now["created_at"] == was["created_at"]
    with pytest.raises(BountyConflictError):
        await release(bounty_id)


async def test_an_old_legacy_bounty_with_nothing_scored_is_refunded(
        client, pool, agents, creator, legacy_on):
    before = await total_tokens(pool)
    submitter = await agents("submitter", 0)
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, submitter)
    await make_legacy(pool, bounty_id, JUST_RELEASABLE)

    assert await release(bounty_id) == ("refunded", POOL)

    row = await bounty_row(pool, bounty_id)
    assert (row["status"], row["winner_submission_id"]) == ("cancelled", None)
    assert await balance(pool, creator) == START_BALANCE
    assert await balance(pool, submitter) == 0
    assert await payouts(pool, bounty_id) == 1
    assert await submission_statuses(pool, bounty_id) == {submission_id: "closed"}
    assert (await stored(pool, bounty_id))["deadline"] is None
    assert await total_tokens(pool) == before


@pytest.mark.parametrize("age", [NOT_YET_RELEASABLE, JUST_CLOSED, "1 day", "0 seconds"])
async def test_a_younger_legacy_bounty_is_held(client, pool, agents, creator, legacy_on, age):
    submitter = await agents("submitter", 0)
    bounty_id = await open_bounty(client, creator)
    await evaluate(client, bounty_id, await submit(client, bounty_id, submitter), creator)
    await make_legacy(pool, bounty_id, age)

    with pytest.raises(BountyConflictError, match="still has time"):
        await release(bounty_id)
    await assert_held(pool, bounty_id, creator, "evaluating", submitter)
    assert (await stored(pool, bounty_id))["deadline"] is None


# ── Submissions close at the effective deadline ───────────────────────────────

async def test_submissions_close_n_days_after_creation(client, pool, agents, creator, legacy_on):
    early, late = await agents("early", 0), await agents("late", 0)
    bounty_id = await open_bounty(client, creator)

    await make_legacy(pool, bounty_id, STILL_OPEN)
    assert (await try_submit(client, bounty_id, early)).status_code == 201

    await make_legacy(pool, bounty_id, JUST_CLOSED)
    resp = await try_submit(client, bounty_id, late)
    assert resp.status_code == 409, resp.text
    assert "deadline" in resp.text.lower()
    assert await count(pool, "bounty_submissions", bounty_id) == 1
    assert (await stored(pool, bounty_id))["deadline"] is None

    # The creator can still score and pay after the effective deadline.
    (submission_id,) = (await submission_statuses(pool, bounty_id)).keys()
    await evaluate(client, bounty_id, submission_id, creator)
    resp = await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers)
    assert resp.status_code == 200, resp.text
    assert await balance(pool, early) == POOL
    assert (await bounty_row(pool, bounty_id))["status"] == "rewarded"


# ── What clients see ──────────────────────────────────────────────────────────

async def test_get_and_list_report_the_effective_deadline(
        client, pool, agents, creator, monkeypatch):
    # The test database is shared by the whole run: list by a capability of our own.
    capability = f"legacy-{uuid4().hex[:8]}"
    resp = await client.post(
        "/markets/bounties",
        json={"title": "legacy", "capability_required": capability, "reward_pool": POOL},
        headers=creator.headers)
    assert resp.status_code == 201, resp.text
    bounty_id = resp.json()["bounty_id"]
    await make_legacy(pool, bounty_id, "10 days")

    async def listed():
        rows = (await client.get(f"/markets/bounties?capability={capability}")).json()
        assert [b["bounty_id"] for b in rows] == [bounty_id]
        return rows[0]["deadline"]

    monkeypatch.setattr(get_settings(), "legacy_bounty_days", 0)
    assert (await client.get(f"/markets/bounties/{bounty_id}")).json()["deadline"] is None
    assert await listed() is None

    monkeypatch.setattr(get_settings(), "legacy_bounty_days", LEGACY_DAYS)
    expected = await effective_deadline(pool, bounty_id, LEGACY_DAYS)
    got = (await client.get(f"/markets/bounties/{bounty_id}")).json()["deadline"]
    assert got is not None
    assert abs(expected.timestamp() - datetime.fromisoformat(got).timestamp()) < 1
    assert await listed() == got
    assert (await stored(pool, bounty_id))["deadline"] is None

    # A stored deadline is reported as stored, whatever the setting.
    other_id = await open_bounty(client, creator)
    stored_deadline = (await client.get(f"/markets/bounties/{other_id}")).json()["deadline"]
    monkeypatch.setattr(get_settings(), "legacy_bounty_days", 1)
    assert (await client.get(f"/markets/bounties/{other_id}")).json()["deadline"] == stored_deadline


# ── The switch ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [0, -5])
async def test_off_keeps_todays_behaviour_however_old(
        client, pool, agents, creator, monkeypatch, value):
    monkeypatch.setattr(get_settings(), "legacy_bounty_days", value)
    submitter, other = await agents("submitter", 0), await agents("other", 0)
    bounty_id = await open_bounty(client, creator)
    await evaluate(client, bounty_id, await submit(client, bounty_id, submitter), creator)
    await make_legacy(pool, bounty_id, "5 years")

    with pytest.raises(BountyConflictError, match="no deadline"):
        await release(bounty_id)
    await assert_held(pool, bounty_id, creator, "evaluating", submitter)
    await pool.execute(
        "UPDATE capability_bounties SET status = 'open' WHERE bounty_id = $1", UUID(bounty_id))
    assert (await try_submit(client, bounty_id, other)).status_code == 201

    from src.jobs.auto_release import run_auto_release
    summary = await run_auto_release()
    assert summary["bounties"] == {"released": 0, "skipped": 0, "failed": 0}
    assert (await bounty_row(pool, bounty_id))["status"] == "open"


async def test_the_number_of_days_is_honoured(client, pool, agents, creator, monkeypatch):
    monkeypatch.setattr(get_settings(), "legacy_bounty_days", 10)
    submitter = await agents("submitter", 0)
    bounty_id = await open_bounty(client, creator)
    await evaluate(client, bounty_id, await submit(client, bounty_id, submitter), creator)

    await make_legacy(pool, bounty_id, f"{10 + AUTO_RELEASE_DAYS} days -1 minute")
    with pytest.raises(BountyConflictError, match="still has time"):
        await release(bounty_id)
    await assert_held(pool, bounty_id, creator, "evaluating", submitter)

    await make_legacy(pool, bounty_id, f"{10 + AUTO_RELEASE_DAYS} days 1 minute")
    assert await release(bounty_id) == ("rewarded", POOL)
    assert await balance(pool, submitter) == POOL


# ── The scheduled job ─────────────────────────────────────────────────────────

async def test_the_job_releases_due_legacy_bounties_and_leaves_the_rest(
        client, pool, agents, creator, legacy_on):
    from src.jobs.auto_release import run_auto_release

    before = await total_tokens(pool)
    winner, unscored, waiting = (
        await agents("winner", 0), await agents("unscored", 0), await agents("waiting", 0))
    scored_old = await open_bounty(client, creator)
    await evaluate(client, scored_old, await submit(client, scored_old, winner), creator, 0.8)
    empty_old = await open_bounty(client, creator)
    await submit(client, empty_old, unscored)
    young = await open_bounty(client, creator)
    await evaluate(client, young, await submit(client, young, waiting), creator, 0.8)
    await make_legacy(pool, scored_old, JUST_RELEASABLE)
    await make_legacy(pool, empty_old, JUST_RELEASABLE)
    await make_legacy(pool, young, NOT_YET_RELEASABLE)

    summary = await run_auto_release()
    assert summary["bounties"] == {"released": 2, "skipped": 0, "failed": 0}
    assert (await bounty_row(pool, scored_old))["status"] == "rewarded"
    assert (await bounty_row(pool, empty_old))["status"] == "cancelled"
    assert (await bounty_row(pool, young))["status"] == "evaluating"
    assert await balance(pool, winner) == POOL
    assert await balance(pool, unscored) == 0
    assert await balance(pool, waiting) == 0
    assert await balance(pool, creator) == START_BALANCE - 3 * POOL + POOL
    for bounty_id in (scored_old, empty_old, young):
        assert (await stored(pool, bounty_id))["deadline"] is None
    assert await total_tokens(pool) == before

    again = await run_auto_release()
    assert again["bounties"] == {"released": 0, "skipped": 0, "failed": 0}
    assert await total_tokens(pool) == before


# ── Once, however concurrently ────────────────────────────────────────────────

@pytest.mark.parametrize("scored", [True, False])
async def test_concurrent_releases_of_a_legacy_bounty_pay_once(
        client, pool, agents, creator, legacy_on, scored):
    submitter = await agents("submitter", 0)
    before = await total_tokens(pool)
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, submitter)
    if scored:
        await evaluate(client, bounty_id, submission_id, creator)
    await make_legacy(pool, bounty_id, JUST_RELEASABLE)

    results = await asyncio.gather(*[release(bounty_id) for _ in range(12)], return_exceptions=True)

    done = [r for r in results if not isinstance(r, Exception)]
    assert done == [("rewarded" if scored else "refunded", POOL)]
    assert all(isinstance(r, BountyConflictError) for r in results if isinstance(r, Exception))
    assert await balance(pool, submitter) == (POOL if scored else 0)
    assert await balance(pool, creator) == START_BALANCE - (POOL if scored else 0)
    assert await payouts(pool, bounty_id) == 1
    assert await total_tokens(pool) == before


# ── The creation default is a setting ─────────────────────────────────────────

@pytest.mark.parametrize("value, expected", [(12, 12), (0, DEFAULT_BOUNTY_DAYS), (-3, DEFAULT_BOUNTY_DAYS)])
async def test_a_new_bounty_gets_default_bounty_days(
        client, pool, creator, monkeypatch, value, expected):
    monkeypatch.setattr(get_settings(), "default_bounty_days", value)
    bounty_id = await open_bounty(client, creator)
    days = await pool.fetchval(
        "SELECT EXTRACT(EPOCH FROM (deadline - created_at)) / 86400.0 "
        "FROM capability_bounties WHERE bounty_id = $1", UUID(bounty_id))
    assert abs(float(days) - expected) < 0.01
