"""
Integration tests: /markets/bounties against REAL local Postgres
Sprint 9, S9-6c — the proof behind enabling `markets`.

Every request goes HTTP → routers/markets.py → bounty_service → Postgres. Only
the JWT check is replaced (the caller is set per request) and the Redis event
bus is silenced; no money path is mocked. The fixtures are in conftest.py.

What is proven:
  • a bounty's reward pool leaves the creator's own wallet when it is created,
    or there is no bounty
  • the pool leaves escrow exactly once: to the winning submitter when the
    creator distributes, or back to the creator when the creator cancels a
    bounty nobody submitted to — however often or however concurrently it is
    tried
  • only the creator evaluates, distributes and cancels; the creator cannot
    submit to, or win, their own bounty; nobody acts without a login
  • a finished bounty takes no more submissions, scores or payouts
  • the database itself refuses a second reward row for a bounty (migration 041)
  • tokens are conserved: wallets + escrow never change in total

Run (needs local Postgres with trust auth for the current OS user):
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
from uuid import UUID

import asyncpg
import pytest

from .support import START_BALANCE, Agent, balance, total_tokens

pytestmark = pytest.mark.integration   # skipped unless --db is given

POOL = 100


# ── DB probes ─────────────────────────────────────────────────────────────────

async def bounty_row(pool, bounty_id: str):
    return await pool.fetchrow(
        "SELECT status, reward_pool, winner_submission_id, creator_did "
        "FROM capability_bounties WHERE bounty_id = $1",
        UUID(bounty_id),
    )


async def ledger(pool, bounty_id: str, tx_type: str) -> int:
    return await pool.fetchval(
        "SELECT COUNT(*) FROM transactions WHERE related_id = $1 AND type = $2",
        UUID(bounty_id), tx_type,
    )


async def count(pool, table: str, bounty_id: str) -> int:
    assert table in {"bounty_submissions", "bounty_rewards"}
    return await pool.fetchval(
        f"SELECT COUNT(*) FROM {table} WHERE bounty_id = $1", UUID(bounty_id))


# ── Flow helpers ──────────────────────────────────────────────────────────────

async def open_bounty(client, creator: Agent, reward_pool: int = POOL) -> str:
    resp = await client.post(
        "/markets/bounties",
        json={"title": "escrow test", "capability_required": "testing", "reward_pool": reward_pool},
        headers=creator.headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["bounty_id"]


async def submit(client, bounty_id: str, submitter: Agent) -> str:
    resp = await client.post(
        f"/markets/bounties/{bounty_id}/submit",
        json={"solution_data": {"answer": 42}, "summary": "integration"},
        headers=submitter.headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["submission_id"]


async def evaluate(client, bounty_id: str, submission_id: str, creator: Agent, score: float = 0.9):
    resp = await client.post(
        f"/markets/bounties/{bounty_id}/submissions/{submission_id}/evaluate",
        json={"score": score}, headers=creator.headers,
    )
    assert resp.status_code == 200, resp.text


async def evaluated_bounty(client, creator: Agent, submitter: Agent) -> tuple[str, str]:
    """A bounty with one scored submission: ready to be paid out."""
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, submitter)
    await evaluate(client, bounty_id, submission_id, creator)
    return bounty_id, submission_id


# ── Create: the pool is escrowed, or there is no bounty ───────────────────────

async def test_pool_is_escrowed_from_the_callers_own_wallet(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    victim = await agents("victim", START_BALANCE)
    before = await total_tokens(pool)

    # A body naming somebody else is ignored: the bounty is the caller's.
    resp = await client.post(
        "/markets/bounties",
        json={"title": "t", "capability_required": "c", "reward_pool": POOL,
              "creator_did": victim.did, "creator_id": str(victim.agent_id)},
        headers=creator.headers,
    )
    assert resp.status_code == 201, resp.text
    bounty_id = resp.json()["bounty_id"]

    assert (await bounty_row(pool, bounty_id))["creator_did"] == creator.did
    assert await balance(pool, creator) == START_BALANCE - POOL
    assert await balance(pool, victim) == START_BALANCE
    assert await ledger(pool, bounty_id, "bounty_escrow") == 1
    assert await total_tokens(pool) == before


async def test_unfunded_bounty_is_refused_and_leaves_nothing_behind(client, pool, agents):
    no_wallet = await agents("nowallet")
    poor = await agents("poor", POOL - 1)
    before = await total_tokens(pool)
    bounties_before = await pool.fetchval("SELECT COUNT(*) FROM capability_bounties")

    for caller in (no_wallet, poor):
        resp = await client.post(
            "/markets/bounties",
            json={"title": "t", "capability_required": "c", "reward_pool": POOL},
            headers=caller.headers,
        )
        assert resp.status_code == 400, resp.text
        assert "Insufficient funds" in resp.json()["detail"]

    assert await pool.fetchval("SELECT COUNT(*) FROM capability_bounties") == bounties_before
    assert await balance(pool, poor) == POOL - 1
    assert await balance(pool, no_wallet) is None
    assert await total_tokens(pool) == before


async def test_concurrent_creates_cannot_overdraw_the_wallet(client, pool, agents):
    creator = await agents("creator", POOL * 3)
    before = await total_tokens(pool)

    responses = await asyncio.gather(*[
        client.post(
            "/markets/bounties",
            json={"title": "t", "capability_required": "c", "reward_pool": POOL},
            headers=creator.headers,
        )
        for _ in range(10)
    ])
    codes = sorted(r.status_code for r in responses)
    assert codes == [201] * 3 + [400] * 7, codes
    assert await balance(pool, creator) == 0
    assert await total_tokens(pool) == before


# ── Who may do what ───────────────────────────────────────────────────────────

async def test_no_write_without_a_login(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    submitter = await agents("submitter", 0)
    bounty_id, submission_id = await evaluated_bounty(client, creator, submitter)
    before = await total_tokens(pool)

    calls = [
        ("/markets/bounties", {"title": "t", "capability_required": "c", "reward_pool": 1}),
        (f"/markets/bounties/{bounty_id}/submit", {"solution_data": {}}),
        (f"/markets/bounties/{bounty_id}/submissions/{submission_id}/evaluate", {"score": 1.0}),
        (f"/markets/bounties/{bounty_id}/distribute", None),
        (f"/markets/bounties/{bounty_id}/cancel", None),
    ]
    for path, body in calls:
        resp = await client.post(path, json=body)
        assert resp.status_code == 401, (path, resp.status_code, resp.text)

    assert (await bounty_row(pool, bounty_id))["status"] == "evaluating"
    assert await count(pool, "bounty_submissions", bounty_id) == 1
    assert await balance(pool, submitter) == 0
    assert await total_tokens(pool) == before


async def test_creator_cannot_submit_to_own_bounty(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    bounty_id = await open_bounty(client, creator)

    resp = await client.post(
        f"/markets/bounties/{bounty_id}/submit",
        json={"solution_data": {"mine": True}}, headers=creator.headers,
    )
    assert resp.status_code == 403, resp.text
    assert await count(pool, "bounty_submissions", bounty_id) == 0


async def test_only_the_creator_evaluates(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    submitter = await agents("submitter", 0)
    outsider = await agents("outsider", START_BALANCE)
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, submitter)

    for caller in (submitter, outsider):
        resp = await client.post(
            f"/markets/bounties/{bounty_id}/submissions/{submission_id}/evaluate",
            json={"score": 1.0}, headers=caller.headers,
        )
        assert resp.status_code == 403, resp.text

    row = await pool.fetchrow(
        "SELECT status, score FROM bounty_submissions WHERE submission_id = $1",
        UUID(submission_id),
    )
    assert (row["status"], row["score"]) == ("pending", None)
    assert (await bounty_row(pool, bounty_id))["status"] == "open"


async def test_a_submission_is_scored_only_under_its_own_bounty(client, pool, agents):
    """The creator of bounty A cannot score a submission that belongs to bounty B."""
    creator_a = await agents("creatora", START_BALANCE)
    creator_b = await agents("creatorb", START_BALANCE)
    submitter = await agents("submitter", 0)
    bounty_a = await open_bounty(client, creator_a)
    bounty_b = await open_bounty(client, creator_b)
    submission_b = await submit(client, bounty_b, submitter)

    resp = await client.post(
        f"/markets/bounties/{bounty_a}/submissions/{submission_b}/evaluate",
        json={"score": 1.0}, headers=creator_a.headers,
    )
    assert resp.status_code == 404, resp.text
    status = await pool.fetchval(
        "SELECT status FROM bounty_submissions WHERE submission_id = $1", UUID(submission_b))
    assert status == "pending"


async def test_only_the_creator_distributes_and_the_winner_is_paid(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    submitter = await agents("submitter", 0)
    outsider = await agents("outsider", START_BALANCE)
    before = await total_tokens(pool)
    bounty_id, submission_id = await evaluated_bounty(client, creator, submitter)

    for caller in (submitter, outsider):
        resp = await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=caller.headers)
        assert resp.status_code == 403, resp.text
    assert await balance(pool, submitter) == 0
    assert (await bounty_row(pool, bounty_id))["status"] == "evaluating"

    resp = await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["recipient_did"], body["amount"], body["submission_id"]) == (
        submitter.did, POOL, submission_id)

    row = await bounty_row(pool, bounty_id)
    assert (row["status"], str(row["winner_submission_id"])) == ("rewarded", submission_id)
    assert await balance(pool, submitter) == POOL
    assert await balance(pool, creator) == START_BALANCE - POOL
    assert await balance(pool, outsider) == START_BALANCE
    assert await ledger(pool, bounty_id, "bounty_reward") == 1
    assert await count(pool, "bounty_rewards", bounty_id) == 1
    assert await total_tokens(pool) == before


async def test_highest_score_wins_and_a_tie_goes_to_the_earliest(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    first = await agents("first", 0)
    second = await agents("second", 0)
    low = await agents("low", 0)
    bounty_id = await open_bounty(client, creator)
    sub_first = await submit(client, bounty_id, first)
    sub_second = await submit(client, bounty_id, second)
    sub_low = await submit(client, bounty_id, low)
    await evaluate(client, bounty_id, sub_low, creator, 0.2)
    await evaluate(client, bounty_id, sub_second, creator, 0.8)
    await evaluate(client, bounty_id, sub_first, creator, 0.8)

    resp = await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["submission_id"] == sub_first
    assert [await balance(pool, a) for a in (first, second, low)] == [POOL, 0, 0]


async def test_a_winner_without_a_wallet_is_still_paid(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    submitter = await agents("submitter")          # no wallet at all
    before = await total_tokens(pool)
    bounty_id, _ = await evaluated_bounty(client, creator, submitter)

    resp = await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers)
    assert resp.status_code == 200, resp.text
    assert await balance(pool, submitter) == POOL
    assert await total_tokens(pool) == before


# ── Distribute: the pool is paid once ─────────────────────────────────────────

async def test_cannot_distribute_before_a_submission_is_scored(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    submitter = await agents("submitter", 0)
    before = await total_tokens(pool)
    bounty_id = await open_bounty(client, creator)

    resp = await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers)
    assert resp.status_code == 409, resp.text
    await submit(client, bounty_id, submitter)          # submitted but not scored
    resp = await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers)
    assert resp.status_code == 409, resp.text

    assert (await bounty_row(pool, bounty_id))["status"] == "open"
    assert await balance(pool, submitter) == 0
    assert await count(pool, "bounty_rewards", bounty_id) == 0
    assert await total_tokens(pool) == before


async def test_distributing_twice_pays_once(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    submitter = await agents("submitter", 0)
    before = await total_tokens(pool)
    bounty_id, _ = await evaluated_bounty(client, creator, submitter)

    first = await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers)
    second = await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers)
    assert (first.status_code, second.status_code) == (200, 409), second.text

    assert await balance(pool, submitter) == POOL
    assert await ledger(pool, bounty_id, "bounty_reward") == 1
    assert await count(pool, "bounty_rewards", bounty_id) == 1
    assert await total_tokens(pool) == before


async def test_concurrent_distributes_pay_once(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    submitter = await agents("submitter", 0)
    before = await total_tokens(pool)
    bounty_id, _ = await evaluated_bounty(client, creator, submitter)

    responses = await asyncio.gather(*[
        client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers)
        for _ in range(12)
    ])
    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [409] * 11, codes

    assert await balance(pool, submitter) == POOL
    assert await ledger(pool, bounty_id, "bounty_reward") == 1
    assert await count(pool, "bounty_rewards", bounty_id) == 1
    assert (await bounty_row(pool, bounty_id))["status"] == "rewarded"
    assert await total_tokens(pool) == before


async def test_the_database_refuses_a_second_reward_row(client, pool, agents):
    """Migration 041 backstop: even code that skipped every check in the
    service could not record a second payout for the same bounty."""
    creator = await agents("creator", START_BALANCE)
    submitter = await agents("submitter", 0)
    bounty_id, submission_id = await evaluated_bounty(client, creator, submitter)
    resp = await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers)
    assert resp.status_code == 200, resp.text

    with pytest.raises(asyncpg.UniqueViolationError):
        await pool.execute(
            """
            INSERT INTO bounty_rewards (bounty_id, submission_id, recipient_did, recipient_id, amount)
            VALUES ($1, $2, $3, $4, $5)
            """,
            UUID(bounty_id), UUID(submission_id), submitter.did, submitter.agent_id, POOL,
        )
    assert await count(pool, "bounty_rewards", bounty_id) == 1


async def test_a_creators_own_submission_can_never_win(client, pool, agents):
    """A creator submission cannot be made through the API any more; one left
    over from before the fix (written here straight into the table, with the
    top score) is passed over when the reward is paid."""
    creator = await agents("creator", START_BALANCE)
    submitter = await agents("submitter", 0)
    before = await total_tokens(pool)
    bounty_id = await open_bounty(client, creator)
    await pool.execute(
        """
        INSERT INTO bounty_submissions
            (bounty_id, submitter_did, submitter_id, status, score, evaluated_at)
        VALUES ($1, $2, $3, 'evaluated', 1.0, NOW())
        """,
        UUID(bounty_id), creator.did, creator.agent_id,
    )

    # Only the creator's own submission is scored: nobody can be paid.
    resp = await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers)
    assert resp.status_code == 409, resp.text
    assert await balance(pool, creator) == START_BALANCE - POOL

    # NB: 'evaluating' is set by the first real evaluation; the bounty is
    # still 'open' here, so a real submission can come in.
    submission_id = await submit(client, bounty_id, submitter)
    await evaluate(client, bounty_id, submission_id, creator, 0.1)
    resp = await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["recipient_did"] == submitter.did

    assert await balance(pool, submitter) == POOL
    assert await balance(pool, creator) == START_BALANCE - POOL
    assert await total_tokens(pool) == before


# ── Cancel: refund once, and only a bounty nobody submitted to ────────────────

async def test_creator_cancels_an_open_bounty_and_is_refunded_once(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    outsider = await agents("outsider", START_BALANCE)
    before = await total_tokens(pool)
    bounty_id = await open_bounty(client, creator)

    resp = await client.post(f"/markets/bounties/{bounty_id}/cancel", headers=outsider.headers)
    assert resp.status_code == 403, resp.text
    assert await balance(pool, creator) == START_BALANCE - POOL

    responses = await asyncio.gather(*[
        client.post(f"/markets/bounties/{bounty_id}/cancel", headers=creator.headers)
        for _ in range(8)
    ])
    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [409] * 7, codes

    assert (await bounty_row(pool, bounty_id))["status"] == "cancelled"
    assert await balance(pool, creator) == START_BALANCE
    assert await balance(pool, outsider) == START_BALANCE
    assert await ledger(pool, bounty_id, "bounty_refund") == 1
    assert await total_tokens(pool) == before


async def test_creator_cannot_pull_the_pool_back_once_someone_has_submitted(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    submitter = await agents("submitter", 0)
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, submitter)

    resp = await client.post(f"/markets/bounties/{bounty_id}/cancel", headers=creator.headers)
    assert resp.status_code == 409, resp.text
    await evaluate(client, bounty_id, submission_id, creator)
    resp = await client.post(f"/markets/bounties/{bounty_id}/cancel", headers=creator.headers)
    assert resp.status_code == 409, resp.text

    assert (await bounty_row(pool, bounty_id))["status"] == "evaluating"
    assert await balance(pool, creator) == START_BALANCE - POOL
    assert await ledger(pool, bounty_id, "bounty_refund") == 0


async def test_cancel_racing_submit_has_exactly_one_winner(client, pool, agents):
    """Cancel and submit at the same moment: either the creator is refunded and
    there is no submission, or the submission is in and the pool stays put.
    Never a refunded bounty that somebody did the work for."""
    outcomes = set()
    for _ in range(8):
        creator = await agents("creator", START_BALANCE)
        submitter = await agents("submitter", 0)
        before = await total_tokens(pool)
        bounty_id = await open_bounty(client, creator)

        cancel, submitted = await asyncio.gather(
            client.post(f"/markets/bounties/{bounty_id}/cancel", headers=creator.headers),
            client.post(
                f"/markets/bounties/{bounty_id}/submit",
                json={"solution_data": {"answer": 42}}, headers=submitter.headers),
        )
        assert sorted([cancel.status_code, submitted.status_code]) in ([200, 409], [201, 409]), (
            cancel.status_code, submitted.status_code)

        row = await bounty_row(pool, bounty_id)
        if cancel.status_code == 200:
            assert row["status"] == "cancelled"
            assert await count(pool, "bounty_submissions", bounty_id) == 0
            assert await balance(pool, creator) == START_BALANCE
        else:
            assert row["status"] == "open"
            assert await count(pool, "bounty_submissions", bounty_id) == 1
            assert await balance(pool, creator) == START_BALANCE - POOL
        outcomes.add(cancel.status_code)
        assert await total_tokens(pool) == before
    assert outcomes <= {200, 409}


# ── A finished bounty is finished ─────────────────────────────────────────────

async def test_a_finished_bounty_takes_no_more_submissions_scores_or_payouts(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    submitter = await agents("submitter", 0)
    late = await agents("late", 0)
    before = await total_tokens(pool)

    rewarded, rewarded_sub = await evaluated_bounty(client, creator, submitter)
    resp = await client.post(f"/markets/bounties/{rewarded}/distribute", headers=creator.headers)
    assert resp.status_code == 200, resp.text
    cancelled = await open_bounty(client, creator)
    resp = await client.post(f"/markets/bounties/{cancelled}/cancel", headers=creator.headers)
    assert resp.status_code == 200, resp.text

    for bounty_id in (rewarded, cancelled):
        resp = await client.post(
            f"/markets/bounties/{bounty_id}/submit",
            json={"solution_data": {}}, headers=late.headers)
        assert resp.status_code == 409, resp.text
        for action in ("distribute", "cancel"):
            resp = await client.post(
                f"/markets/bounties/{bounty_id}/{action}", headers=creator.headers)
            assert resp.status_code == 409, (action, resp.text)

    # Re-scoring after the payout cannot change who won.
    resp = await client.post(
        f"/markets/bounties/{rewarded}/submissions/{rewarded_sub}/evaluate",
        json={"score": 0.0}, headers=creator.headers,
    )
    assert resp.status_code == 409, resp.text

    assert await balance(pool, submitter) == POOL
    assert await balance(pool, late) == 0
    assert await balance(pool, creator) == START_BALANCE - POOL
    assert await total_tokens(pool) == before
