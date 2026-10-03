"""
Integration tests: bounty deadlines, against REAL local Postgres.
Sprint 12, S12-6 (decision D5b).

Every request goes HTTP → routers/markets.py → bounty_service → Postgres. Only
the JWT check is replaced (the caller is set per request) and the Redis event
bus is silenced; no money path is mocked. The fixtures are in conftest.py.
Time is never mocked either: a test moves the stored deadline on the row and
the service compares it with the database clock.

What is proven:
  • a bounty takes no submission after its deadline, whoever asks and whatever
    the request says; the creator can still score and pay
  • every new bounty has a deadline; one already past is refused and leaves
    nothing behind
  • automatic release: only a bounty still holding its pool, only one with a
    deadline, only AUTO_RELEASE_DAYS after it; to the top-scored submission
    (ties: the earliest, always the same pick), or back to the creator when
    nothing payable was scored; once, however concurrently; no route does it
  • the creator's own entry, an unscored entry and an entry under another
    bounty can never be the automatic winner
  • a failure during either payout changes nothing; tokens are conserved

Run (needs local Postgres with trust auth for the current OS user):
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from src.services.auto_release import AUTO_RELEASE_DAYS
from src.services.markets import bounty_service
from src.services.markets.bounty_service import DEFAULT_BOUNTY_DAYS, BountyConflictError

from .support import START_BALANCE, Agent, balance, total_tokens
from .test_bounty_escrow_db import POOL, bounty_row, count, evaluate, ledger, open_bounty, submit

pytestmark = pytest.mark.integration   # skipped unless --db is given

RELEASE_TX = "bounty_auto_release"
REFUND_TX = "bounty_deadline_refund"
_PAYOUT_TYPES = (RELEASE_TX, REFUND_TX, "bounty_reward", "bounty_refund")

JUST_DUE = f"-{AUTO_RELEASE_DAYS} days -1 minute"
NOT_YET_DUE = f"-{AUTO_RELEASE_DAYS} days 1 minute"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _in(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


async def move_deadline(pool, bounty_id: str, offset: str | None) -> None:
    """Set the deadline to the database's now + *offset* (e.g. '-1 second');
    None removes it (a bounty from before the rule)."""
    if offset is None:
        await pool.execute(
            "UPDATE capability_bounties SET deadline = NULL WHERE bounty_id = $1", UUID(bounty_id))
        return
    await pool.execute(
        "UPDATE capability_bounties SET deadline = CURRENT_TIMESTAMP + $2::text::interval "
        "WHERE bounty_id = $1",
        UUID(bounty_id), offset,
    )


async def try_submit(client, bounty_id: str, submitter: Agent | None, **extra):
    return await client.post(
        f"/markets/bounties/{bounty_id}/submit",
        json={"solution_data": {"answer": 42}, "summary": "integration", **extra},
        headers=submitter.headers if submitter else {},
    )


async def release(bounty_id: str):
    return await bounty_service.release_overdue_bounty(UUID(bounty_id))


async def payouts(pool, bounty_id: str) -> int:
    return sum([await ledger(pool, bounty_id, t) for t in _PAYOUT_TYPES])


async def assert_held(pool, bounty_id: str, creator: Agent, status: str, *others: Agent):
    """Nothing has moved: pool held, nobody paid, status unchanged."""
    row = await bounty_row(pool, bounty_id)
    assert (row["status"], row["reward_pool"], row["winner_submission_id"]) == (status, POOL, None)
    assert await balance(pool, creator) == START_BALANCE - POOL
    for other in others:
        assert await balance(pool, other) in (0, None)
    assert await payouts(pool, bounty_id) == 0
    assert await count(pool, "bounty_rewards", bounty_id) == 0


async def submission_statuses(pool, bounty_id: str) -> dict[str, str]:
    rows = await pool.fetch(
        "SELECT submission_id, status FROM bounty_submissions WHERE bounty_id = $1",
        UUID(bounty_id))
    return {str(r["submission_id"]): r["status"] for r in rows}


@pytest.fixture
async def creator(agents):
    return await agents("creator", START_BALANCE)


# ── Creation: every bounty has a deadline, and it is in the future ────────────

async def test_a_bounty_without_a_deadline_gets_the_default(client, pool, creator):
    bounty_id = await open_bounty(client, creator)
    days = await pool.fetchval(
        "SELECT EXTRACT(EPOCH FROM (deadline - created_at)) / 86400.0 "
        "FROM capability_bounties WHERE bounty_id = $1", UUID(bounty_id))
    assert abs(float(days) - DEFAULT_BOUNTY_DAYS) < 0.01
    resp = await client.get(f"/markets/bounties/{bounty_id}")
    assert resp.json()["deadline"] is not None


async def test_a_given_deadline_is_stored_and_one_with_no_zone_is_utc(client, pool, creator):
    naive = (datetime.now(timezone.utc) + timedelta(days=2)).replace(tzinfo=None, microsecond=0)
    resp = await client.post(
        "/markets/bounties",
        json={"title": "t", "capability_required": "c", "reward_pool": POOL,
              "deadline": naive.isoformat()},
        headers=creator.headers,
    )
    assert resp.status_code == 201, resp.text
    stored = await pool.fetchval(
        "SELECT deadline FROM capability_bounties WHERE bounty_id = $1",
        UUID(resp.json()["bounty_id"]))
    assert stored == naive.replace(tzinfo=timezone.utc)


@pytest.mark.parametrize("delta", [{"seconds": -1}, {"days": -30}, {"days": -365 * 50}])
async def test_a_deadline_already_past_is_refused_and_leaves_nothing_behind(
    client, pool, creator, delta,
):
    before = await total_tokens(pool)
    rows_before = await pool.fetchval("SELECT COUNT(*) FROM capability_bounties")
    resp = await client.post(
        "/markets/bounties",
        json={"title": "t", "capability_required": "c", "reward_pool": POOL,
              "deadline": _in(**delta)},
        headers=creator.headers,
    )
    assert resp.status_code == 400, resp.text
    assert await pool.fetchval("SELECT COUNT(*) FROM capability_bounties") == rows_before
    assert await balance(pool, creator) == START_BALANCE
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM transactions WHERE type = 'bounty_escrow' AND from_wallet = "
        "(SELECT wallet_id FROM wallets WHERE agent_id = $1)", creator.agent_id) == 0
    assert await total_tokens(pool) == before


# ── No submissions after the deadline ─────────────────────────────────────────

async def test_no_submission_after_the_deadline(client, pool, agents, creator):
    early = await agents("early", 0)
    late = await agents("late", 0)
    bounty_id = await open_bounty(client, creator)
    await submit(client, bounty_id, early)

    await move_deadline(pool, bounty_id, "-1 second")
    resp = await try_submit(client, bounty_id, late)
    assert resp.status_code == 409, resp.text
    # The early one cannot slip a second entry in either.
    assert (await try_submit(client, bounty_id, early)).status_code == 409
    assert await count(pool, "bounty_submissions", bounty_id) == 1

    # A minute before the deadline the door is still open.
    await move_deadline(pool, bounty_id, "1 minute")
    assert (await try_submit(client, bounty_id, late)).status_code == 201


async def test_nothing_in_the_request_moves_the_clock(client, pool, agents, creator):
    late = await agents("late", 0)
    bounty_id = await open_bounty(client, creator)
    await move_deadline(pool, bounty_id, "-1 second")
    resp = await try_submit(
        client, bounty_id, late,
        submitted_at=_in(days=-5), deadline=_in(days=5), now=_in(days=-5), status="evaluated",
        score=1.0,
    )
    assert resp.status_code == 409, resp.text
    resp = await client.post(
        f"/markets/bounties/{bounty_id}/submit?submitted_at={_in(days=-5)[:10]}",
        json={"solution_data": {}}, headers={**late.headers, "Date": "Mon, 01 Jan 2024 00:00:00 GMT"},
    )
    assert resp.status_code == 409, resp.text
    assert await count(pool, "bounty_submissions", bounty_id) == 0


async def test_the_creator_cannot_reopen_the_door_through_the_api(client, pool, agents, creator):
    """No route changes a bounty's deadline."""
    bounty_id = await open_bounty(client, creator)
    stored = (await pool.fetchrow(
        "SELECT deadline FROM capability_bounties WHERE bounty_id = $1", UUID(bounty_id)))[0]
    for method in ("put", "patch", "post"):
        resp = await getattr(client, method)(
            f"/markets/bounties/{bounty_id}", json={"deadline": _in(days=900)},
            headers=creator.headers)
        assert resp.status_code in (404, 405), resp.text
    assert (await pool.fetchrow(
        "SELECT deadline FROM capability_bounties WHERE bounty_id = $1", UUID(bounty_id)))[0] == stored


async def test_the_creator_still_scores_and_pays_after_the_deadline(client, pool, agents, creator):
    submitter = await agents("submitter", 0)
    before = await total_tokens(pool)
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, submitter)
    await move_deadline(pool, bounty_id, "-3 days")

    await evaluate(client, bounty_id, submission_id, creator)
    resp = await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers)
    assert resp.status_code == 200, resp.text
    assert await balance(pool, submitter) == POOL
    assert await ledger(pool, bounty_id, "bounty_reward") == 1
    assert await total_tokens(pool) == before


async def test_an_empty_bounty_can_still_be_cancelled_after_the_deadline(client, pool, creator):
    bounty_id = await open_bounty(client, creator)
    await move_deadline(pool, bounty_id, "-1 day")
    resp = await client.post(f"/markets/bounties/{bounty_id}/cancel", headers=creator.headers)
    assert resp.status_code == 200, resp.text
    assert await balance(pool, creator) == START_BALANCE


# ── Automatic release: when ───────────────────────────────────────────────────

async def test_not_released_before_the_period_has_passed(client, pool, agents, creator):
    submitter = await agents("submitter", 0)
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, submitter)
    await evaluate(client, bounty_id, submission_id, creator)

    for offset in ("1 day", "-1 second", "-3 days", NOT_YET_DUE):
        await move_deadline(pool, bounty_id, offset)
        with pytest.raises(BountyConflictError):
            await release(bounty_id)
        await assert_held(pool, bounty_id, creator, "evaluating", submitter)

    await move_deadline(pool, bounty_id, JUST_DUE)
    assert await release(bounty_id) == ("rewarded", POOL)


async def test_a_bounty_with_no_deadline_is_never_released(client, pool, agents, creator):
    submitter = await agents("submitter", 0)
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, submitter)
    await evaluate(client, bounty_id, submission_id, creator)
    await move_deadline(pool, bounty_id, None)
    await pool.execute(
        "UPDATE capability_bounties SET created_at = created_at - interval '5 years' "
        "WHERE bounty_id = $1", UUID(bounty_id))

    with pytest.raises(BountyConflictError):
        await release(bounty_id)
    await assert_held(pool, bounty_id, creator, "evaluating", submitter)
    # …and with no deadline it still takes submissions, as before the rule.
    other = await agents("other", 0)
    await pool.execute(
        "UPDATE capability_bounties SET status = 'open' WHERE bounty_id = $1", UUID(bounty_id))
    assert (await try_submit(client, bounty_id, other)).status_code == 201


async def test_unknown_bounty_is_not_found(pool):
    with pytest.raises(ValueError, match="not found"):
        await bounty_service.release_overdue_bounty(uuid4())


async def test_no_route_releases_a_bounty(client, pool, agents, creator):
    """Nobody — creator, submitter, FOUNDER, anonymous — can trigger it over HTTP."""
    submitter = await agents("submitter", 0)
    founder = await agents("founder", 0, role="FOUNDER")
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, submitter)
    await evaluate(client, bounty_id, submission_id, creator)
    await move_deadline(pool, bounty_id, JUST_DUE)

    from src.main import app
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not [p for p in paths if "bount" in p and ("release" in p or "overdue" in p)]
    for caller in (creator, submitter, founder, None):
        for name in ("release", "auto-release", "release_overdue", "expire"):
            resp = await client.post(
                f"/markets/bounties/{bounty_id}/{name}",
                headers=caller.headers if caller else {})
            assert resp.status_code in (404, 405), resp.text
    await assert_held(pool, bounty_id, creator, "evaluating", submitter)


# ── Automatic release: to whom ────────────────────────────────────────────────

async def test_the_top_scored_submission_is_paid_once(client, pool, agents, creator):
    best = await agents("best", 0)
    worse = await agents("worse", 0)
    unscored = await agents("unscored", 0)
    before = await total_tokens(pool)
    bounty_id = await open_bounty(client, creator)
    sub_worse = await submit(client, bounty_id, worse)
    sub_best = await submit(client, bounty_id, best)
    sub_unscored = await submit(client, bounty_id, unscored)
    await evaluate(client, bounty_id, sub_worse, creator, 0.3)
    await evaluate(client, bounty_id, sub_best, creator, 0.7)
    await move_deadline(pool, bounty_id, JUST_DUE)

    assert await release(bounty_id) == ("rewarded", POOL)

    row = await bounty_row(pool, bounty_id)
    assert (row["status"], str(row["winner_submission_id"])) == ("rewarded", sub_best)
    assert [await balance(pool, a) for a in (best, worse, unscored)] == [POOL, 0, 0]
    assert await balance(pool, creator) == START_BALANCE - POOL
    assert await ledger(pool, bounty_id, RELEASE_TX) == 1
    assert await payouts(pool, bounty_id) == 1
    assert await count(pool, "bounty_rewards", bounty_id) == 1
    assert await submission_statuses(pool, bounty_id) == {
        sub_best: "won", sub_worse: "closed", sub_unscored: "closed"}
    assert await total_tokens(pool) == before

    # A second run, the creator's own distribute and a cancel all find it closed.
    with pytest.raises(BountyConflictError):
        await release(bounty_id)
    for action in ("distribute", "cancel"):
        resp = await client.post(f"/markets/bounties/{bounty_id}/{action}", headers=creator.headers)
        assert resp.status_code == 409, resp.text
    assert await balance(pool, best) == POOL
    assert await payouts(pool, bounty_id) == 1
    assert await total_tokens(pool) == before


async def test_a_tie_goes_to_the_earliest_submission_every_time(client, pool, agents):
    """Same scores, scored in the opposite order: the earliest entry wins —
    and the same entry on every one of several identical bounties."""
    for _ in range(4):
        creator = await agents("creator", START_BALANCE)
        first, second, third = [await agents(n, 0) for n in ("first", "second", "third")]
        bounty_id = await open_bounty(client, creator)
        subs = [await submit(client, bounty_id, a) for a in (first, second, third)]
        for sub in reversed(subs):
            await evaluate(client, bounty_id, sub, creator, 0.5)
        await move_deadline(pool, bounty_id, JUST_DUE)

        assert await release(bounty_id) == ("rewarded", POOL)
        assert str((await bounty_row(pool, bounty_id))["winner_submission_id"]) == subs[0]
        assert [await balance(pool, a) for a in (first, second, third)] == [POOL, 0, 0]


async def test_a_tie_at_the_same_instant_is_broken_by_id(client, pool, agents, creator):
    a, b = await agents("a", 0), await agents("b", 0)
    bounty_id = await open_bounty(client, creator)
    subs = [await submit(client, bounty_id, a), await submit(client, bounty_id, b)]
    for sub in subs:
        await evaluate(client, bounty_id, sub, creator, 0.5)
    await pool.execute(
        "UPDATE bounty_submissions SET submitted_at = '2026-01-01T00:00:00Z' WHERE bounty_id = $1",
        UUID(bounty_id))
    await move_deadline(pool, bounty_id, JUST_DUE)

    assert await release(bounty_id) == ("rewarded", POOL)
    expected = min(subs, key=lambda s: UUID(s))
    assert str((await bounty_row(pool, bounty_id))["winner_submission_id"]) == expected


async def test_a_score_of_zero_still_counts_as_scored(client, pool, agents, creator):
    submitter = await agents("submitter", 0)
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, submitter)
    await evaluate(client, bounty_id, submission_id, creator, 0.0)
    await move_deadline(pool, bounty_id, JUST_DUE)

    assert await release(bounty_id) == ("rewarded", POOL)
    assert await balance(pool, submitter) == POOL


async def test_a_winner_without_a_wallet_is_still_paid(client, pool, agents, creator):
    submitter = await agents("submitter")          # no wallet at all
    before = await total_tokens(pool)
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, submitter)
    await evaluate(client, bounty_id, submission_id, creator)
    await move_deadline(pool, bounty_id, JUST_DUE)

    assert await release(bounty_id) == ("rewarded", POOL)
    assert await balance(pool, submitter) == POOL
    assert await total_tokens(pool) == before


@pytest.mark.parametrize("with_submissions", [False, True])
async def test_nothing_scored_goes_back_to_the_creator_once(
    client, pool, agents, creator, with_submissions,
):
    submitter = await agents("submitter", 0)
    before = await total_tokens(pool)
    bounty_id = await open_bounty(client, creator)
    sub = await submit(client, bounty_id, submitter) if with_submissions else None
    await move_deadline(pool, bounty_id, JUST_DUE)

    assert await release(bounty_id) == ("refunded", POOL)

    row = await bounty_row(pool, bounty_id)
    assert (row["status"], row["winner_submission_id"]) == ("cancelled", None)
    assert await balance(pool, creator) == START_BALANCE
    assert await balance(pool, submitter) == 0
    assert await ledger(pool, bounty_id, REFUND_TX) == 1
    assert await payouts(pool, bounty_id) == 1
    assert await count(pool, "bounty_rewards", bounty_id) == 0
    if sub:
        assert await submission_statuses(pool, bounty_id) == {sub: "closed"}
    assert await total_tokens(pool) == before

    with pytest.raises(BountyConflictError):
        await release(bounty_id)
    # A closed bounty takes no score and no payout: nobody is paid on top of the refund.
    if sub:
        resp = await client.post(
            f"/markets/bounties/{bounty_id}/submissions/{sub}/evaluate",
            json={"score": 1.0}, headers=creator.headers)
        assert resp.status_code == 409, resp.text
    for action in ("distribute", "cancel"):
        resp = await client.post(f"/markets/bounties/{bounty_id}/{action}", headers=creator.headers)
        assert resp.status_code == 409, resp.text
    assert await balance(pool, creator) == START_BALANCE
    assert await payouts(pool, bounty_id) == 1
    assert await total_tokens(pool) == before


async def test_only_a_bounty_still_holding_its_pool_is_released(client, pool, agents, creator):
    """Old deadline forced onto finished bounties: nothing moves a second time."""
    submitter = await agents("submitter", 0)
    before = await total_tokens(pool)

    paid = await open_bounty(client, creator)
    sub = await submit(client, paid, submitter)
    await evaluate(client, paid, sub, creator)
    resp = await client.post(f"/markets/bounties/{paid}/distribute", headers=creator.headers)
    assert resp.status_code == 200, resp.text

    cancelled = await open_bounty(client, creator)
    resp = await client.post(f"/markets/bounties/{cancelled}/cancel", headers=creator.headers)
    assert resp.status_code == 200, resp.text

    for bounty_id in (paid, cancelled):
        await move_deadline(pool, bounty_id, "-1 year")
        with pytest.raises(BountyConflictError):
            await release(bounty_id)
        assert await payouts(pool, bounty_id) == 1
    assert await balance(pool, submitter) == POOL
    assert await balance(pool, creator) == START_BALANCE - POOL
    assert await total_tokens(pool) == before


# ── Automatic release: who can never be the winner ───────────────────────────

async def test_the_creators_own_entry_never_wins_the_release(client, pool, agents, creator):
    """A creator's row forced into the table with the top score: the pool
    goes to the real entrant, not back to the creator through the prize."""
    submitter = await agents("submitter", 0)
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, submitter)
    await evaluate(client, bounty_id, submission_id, creator, 0.1)
    await pool.execute(
        "INSERT INTO bounty_submissions (bounty_id, submitter_did, submitter_id, status, score, "
        "submitted_at) VALUES ($1, $2, $3, 'evaluated', 1.0, NOW() - interval '1 year')",
        UUID(bounty_id), creator.did, creator.agent_id)
    await move_deadline(pool, bounty_id, JUST_DUE)

    assert await release(bounty_id) == ("rewarded", POOL)
    assert await balance(pool, submitter) == POOL
    assert await balance(pool, creator) == START_BALANCE - POOL


async def test_a_score_alone_or_a_status_alone_does_not_win(client, pool, agents, creator):
    """Rows forced into half-scored states are not 'scored': the creator is
    refunded rather than a payee being guessed."""
    a, b = await agents("a", 0), await agents("b", 0)
    bounty_id = await open_bounty(client, creator)
    sub_a, sub_b = await submit(client, bounty_id, a), await submit(client, bounty_id, b)
    await pool.execute(
        "UPDATE bounty_submissions SET score = 1.0 WHERE submission_id = $1", UUID(sub_a))
    await pool.execute(
        "UPDATE bounty_submissions SET status = 'evaluated', score = NULL WHERE submission_id = $1",
        UUID(sub_b))
    await move_deadline(pool, bounty_id, JUST_DUE)

    assert await release(bounty_id) == ("refunded", POOL)
    assert [await balance(pool, x) for x in (a, b)] == [0, 0]
    assert await balance(pool, creator) == START_BALANCE


async def test_an_entry_under_another_bounty_cannot_win(client, pool, agents, creator):
    other_creator = await agents("other-creator", START_BALANCE)
    intruder = await agents("intruder", 0)
    mine = await open_bounty(client, creator)
    theirs = await open_bounty(client, other_creator)
    sub = await submit(client, theirs, intruder)
    await evaluate(client, theirs, sub, other_creator, 1.0)
    await move_deadline(pool, mine, JUST_DUE)

    assert await release(mine) == ("refunded", POOL)
    assert await balance(pool, intruder) == 0
    await assert_held(pool, theirs, other_creator, "evaluating", intruder)


async def test_a_deleted_winner_is_skipped_for_the_next_payable_entry(client, pool, agents, creator):
    gone = await agents("gone", 0)
    runner_up = await agents("runner-up", 0)
    before = await total_tokens(pool)
    bounty_id = await open_bounty(client, creator)
    sub_gone = await submit(client, bounty_id, gone)
    sub_next = await submit(client, bounty_id, runner_up)
    await evaluate(client, bounty_id, sub_gone, creator, 0.9)
    await evaluate(client, bounty_id, sub_next, creator, 0.4)
    await pool.execute(
        "UPDATE bounty_submissions SET submitter_id = NULL WHERE submission_id = $1", UUID(sub_gone))
    await move_deadline(pool, bounty_id, JUST_DUE)

    assert await release(bounty_id) == ("rewarded", POOL)
    assert await balance(pool, runner_up) == POOL
    assert await total_tokens(pool) == before


async def test_no_winner_and_no_creator_moves_nothing(client, pool, agents, creator):
    """Nothing scored and the creator's agent row gone: no payee is guessed."""
    bounty_id = await open_bounty(client, creator)
    await pool.execute(
        "UPDATE capability_bounties SET creator_id = NULL, creator_did = $2 WHERE bounty_id = $1",
        UUID(bounty_id), f"did:agentx:deleted-{uuid4().hex[:8]}")
    await move_deadline(pool, bounty_id, JUST_DUE)
    before = await total_tokens(pool)

    with pytest.raises(BountyConflictError):
        await release(bounty_id)
    row = await bounty_row(pool, bounty_id)
    assert (row["status"], row["reward_pool"]) == ("open", POOL)
    assert await payouts(pool, bounty_id) == 0
    assert await total_tokens(pool) == before


# ── Once, however concurrently ────────────────────────────────────────────────

@pytest.mark.parametrize("scored", [True, False])
async def test_concurrent_releases_pay_once(client, pool, agents, creator, scored):
    submitter = await agents("submitter", 0)
    before = await total_tokens(pool)
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, submitter)
    if scored:
        await evaluate(client, bounty_id, submission_id, creator)
    await move_deadline(pool, bounty_id, JUST_DUE)

    results = await asyncio.gather(*[release(bounty_id) for _ in range(12)], return_exceptions=True)

    done = [r for r in results if not isinstance(r, Exception)]
    assert done == [("rewarded" if scored else "refunded", POOL)]
    assert all(isinstance(r, BountyConflictError) for r in results if isinstance(r, Exception))
    assert await balance(pool, submitter) == (POOL if scored else 0)
    assert await balance(pool, creator) == START_BALANCE - (POOL if scored else 0)
    assert await payouts(pool, bounty_id) == 1
    assert await count(pool, "bounty_rewards", bounty_id) == (1 if scored else 0)
    assert await total_tokens(pool) == before


async def test_release_racing_the_creators_distribute_pays_once(client, pool, agents, creator):
    for _ in range(5):
        submitter = await agents("submitter", 0)
        bounty_id = await open_bounty(client, creator)
        submission_id = await submit(client, bounty_id, submitter)
        await evaluate(client, bounty_id, submission_id, creator)
        await move_deadline(pool, bounty_id, JUST_DUE)
        before = await total_tokens(pool)

        released, distributed = await asyncio.gather(
            release(bounty_id),
            client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers),
            return_exceptions=True,
        )
        won = [not isinstance(released, Exception), distributed.status_code == 200]
        assert sorted(won) == [False, True], (released, distributed.text)
        assert await balance(pool, submitter) == POOL
        assert await payouts(pool, bounty_id) == 1
        assert await count(pool, "bounty_rewards", bounty_id) == 1
        assert await total_tokens(pool) == before


async def test_release_racing_a_last_minute_score_ends_in_one_outcome(client, pool, agents):
    """The creator scores as the job runs: either the entrant is paid or the
    creator is refunded — never both, never neither."""
    for _ in range(5):
        creator = await agents("creator", START_BALANCE)
        submitter = await agents("submitter", 0)
        bounty_id = await open_bounty(client, creator)
        submission_id = await submit(client, bounty_id, submitter)
        await move_deadline(pool, bounty_id, JUST_DUE)
        before = await total_tokens(pool)

        released, _scored = await asyncio.gather(
            release(bounty_id),
            client.post(
                f"/markets/bounties/{bounty_id}/submissions/{submission_id}/evaluate",
                json={"score": 0.9}, headers=creator.headers),
            return_exceptions=True,
        )
        assert released in (("rewarded", POOL), ("refunded", POOL)), released
        paid_out = released[0] == "rewarded"
        assert await balance(pool, submitter) == (POOL if paid_out else 0)
        assert await balance(pool, creator) == START_BALANCE - (POOL if paid_out else 0)
        assert await payouts(pool, bounty_id) == 1
        assert await total_tokens(pool) == before


async def test_release_racing_the_creators_cancel_refunds_once(client, pool, creator):
    for _ in range(5):
        bounty_id = await open_bounty(client, creator)
        await move_deadline(pool, bounty_id, JUST_DUE)
        before = await total_tokens(pool)

        released, cancelled = await asyncio.gather(
            release(bounty_id),
            client.post(f"/markets/bounties/{bounty_id}/cancel", headers=creator.headers),
            return_exceptions=True,
        )
        won = [not isinstance(released, Exception), cancelled.status_code == 200]
        assert sorted(won) == [False, True], (released, cancelled.text)
        assert await payouts(pool, bounty_id) == 1
        assert await total_tokens(pool) == before
    assert await balance(pool, creator) == START_BALANCE


# ── A failure changes nothing ─────────────────────────────────────────────────

@pytest.mark.parametrize("scored", [True, False])
async def test_a_failed_release_leaves_the_bounty_as_it_was(
    client, pool, agents, creator, monkeypatch, scored,
):
    submitter = await agents("submitter", 0)
    before = await total_tokens(pool)
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, submitter)
    if scored:
        await evaluate(client, bounty_id, submission_id, creator)
    await move_deadline(pool, bounty_id, JUST_DUE)
    statuses = await submission_statuses(pool, bounty_id)

    async def broken_ledger(*args, **kwargs):
        raise RuntimeError("ledger down")

    with monkeypatch.context() as patch:
        patch.setattr(bounty_service, "_record_transaction", broken_ledger)
        with pytest.raises(RuntimeError):
            await release(bounty_id)

    await assert_held(pool, bounty_id, creator, "evaluating" if scored else "open", submitter)
    assert await submission_statuses(pool, bounty_id) == statuses
    assert await total_tokens(pool) == before

    # The next run of the job succeeds.
    assert await release(bounty_id) == ("rewarded" if scored else "refunded", POOL)
    assert await payouts(pool, bounty_id) == 1
    assert await total_tokens(pool) == before
