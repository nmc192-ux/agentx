"""
Integration tests: /governance (and the stake release it constrains) against
REAL local Postgres. Sprint 9, S9-8 — the proof behind enabling `governance`.

Every request goes HTTP → router → service → Postgres. Only the JWT check is
replaced (the caller is set per request); nothing else is mocked. The fixtures
are in conftest.py.

What is proven:
  • nobody proposes or votes without a login, and a vote is recorded under the
    logged-in agent whatever the request body says
  • propose → vote → tally: weight = unreleased stake × trust score
  • one vote per agent per proposal, however often or however concurrently it
    is tried, and the tally counts it once
  • the stakes behind a weighted vote cannot be released while the proposal is
    open — so the same tokens cannot be moved to a second account to vote
    again — and can be released once voting has closed; a vote racing a
    release never ends with both a weighted vote and the tokens back
  • no vote lands after the close; a closed proposal leaves the active list
    and shows up in the results
  • the outcome follows the seeded rules: quorum (abstentions count) and a
    strict majority of yes over yes + no; a tie fails
  • an agent has at most 3 proposals open at a time, also under concurrency
  • bounded input: description, type, payload, page size
  • tokens are conserved throughout

Run (needs local Postgres with trust auth for the current OS user):
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from .support import START_BALANCE, Agent, balance, total_tokens

pytestmark = pytest.mark.integration   # skipped unless --db is given

TRUST = 0.5
QUORUM = 100            # governance_parameters.quorum_threshold, as seeded


@pytest_asyncio.fixture
async def voters(agents, pool):
    """Factory: an agent with a funded wallet and a known trust score."""
    async def make(name: str, funds: int = START_BALANCE, trust: float = TRUST) -> Agent:
        agent = await agents(name, funds)
        await pool.execute(
            "UPDATE agents SET trust_score = $1 WHERE agent_id = $2", trust, agent.agent_id,
        )
        return agent
    return make


# ── Flow helpers ──────────────────────────────────────────────────────────────

async def propose(client, proposer: Agent, **extra) -> str:
    body = {"title": f"Proposal {uuid4().hex[:8]}", "description": "A test proposal", **extra}
    resp = await client.post("/governance/proposals", json=body, headers=proposer.headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["proposal_id"]


def vote(client, voter: Agent, proposal_id: str, choice: str = "yes", **extra):
    return client.post(
        "/governance/vote",
        json={"proposal_id": proposal_id, "vote": choice, **extra},
        headers=voter.headers,
    )


async def stake(client, owner: Agent, amount: int) -> str:
    resp = await client.post("/stakes", json={"amount": amount}, headers=owner.headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["stake_id"]


def release(client, stake_id: str, caller: Agent):
    return client.post(f"/stakes/{stake_id}/release", headers=caller.headers)


async def end_voting(pool, proposal_id: str) -> None:
    """Move the proposal's closing time into the past (stands in for waiting)."""
    await pool.execute(
        "UPDATE proposals SET voting_ends_at = CURRENT_TIMESTAMP - INTERVAL '1 second' "
        "WHERE proposal_id = $1",
        UUID(proposal_id),
    )


async def proposal_row(pool, proposal_id: str):
    return await pool.fetchrow(
        "SELECT status, yes_power, no_power FROM proposals WHERE proposal_id = $1",
        UUID(proposal_id),
    )


async def vote_rows(pool, proposal_id: str):
    return await pool.fetch(
        "SELECT voter_id, voter_did, vote, vote_power FROM governance_votes "
        "WHERE proposal_id = $1",
        UUID(proposal_id),
    )


async def listed(client, path: str, proposal_id: str) -> dict | None:
    resp = await client.get(path, params={"limit": 200})
    assert resp.status_code == 200, resp.text
    return next((p for p in resp.json() if p["proposal_id"] == proposal_id), None)


async def close_and_get(client, pool, proposal_id: str) -> dict:
    await end_voting(pool, proposal_id)
    result = await listed(client, "/governance/results", proposal_id)
    assert result is not None, "a proposal past its closing time must be in the results"
    return result


# ── Nobody acts without a login; identity comes from the login ────────────────

async def test_no_governance_write_without_a_login(client, pool, voters):
    proposer = await voters("proposer")
    proposal_id = await propose(client, proposer)

    create = await client.post(
        "/governance/proposals",
        json={"title": "x", "description": "y", "proposer_did": proposer.did},
    )
    cast = await client.post(
        "/governance/vote",
        json={"proposal_id": proposal_id, "vote": "yes", "voter_did": proposer.did},
    )

    assert create.status_code == 401
    assert cast.status_code == 401
    assert await vote_rows(pool, proposal_id) == []


async def test_a_vote_is_recorded_under_the_login_whatever_the_body_says(client, pool, voters):
    proposer = await voters("proposer")
    voter = await voters("voter")
    rich = await voters("rich")
    await stake(client, rich, 800)
    proposal_id = await propose(client, proposer, proposer_did=rich.did, proposer_id=str(rich.agent_id))

    resp = await vote(
        client, voter, proposal_id,
        voter_did=rich.did, voter_id=str(rich.agent_id), agent_id=str(rich.agent_id),
        vote_power=1_000_000,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["voter_did"] == voter.did
    assert resp.json()["vote_power"] == 0          # the voter has no stake
    rows = await vote_rows(pool, proposal_id)
    assert [(r["voter_id"], float(r["vote_power"])) for r in rows] == [(voter.agent_id, 0.0)]
    stored = await pool.fetchrow(
        "SELECT proposer_did, proposer_id FROM proposals WHERE proposal_id = $1",
        UUID(proposal_id),
    )
    assert (stored["proposer_did"], stored["proposer_id"]) == (proposer.did, proposer.agent_id)


# ── Propose → vote → tally ────────────────────────────────────────────────────

async def test_propose_vote_tally(client, pool, voters):
    proposer = await voters("proposer")
    yes_a = await voters("yes-a")
    yes_b = await voters("yes-b", trust=0.8)
    no_c = await voters("no-c")
    abstainer = await voters("abstainer")
    await stake(client, yes_a, 200)
    await stake(client, yes_a, 100)             # two stakes: both count
    await stake(client, yes_b, 100)
    await stake(client, no_c, 120)
    await stake(client, abstainer, 40)
    before = await total_tokens(pool)
    proposal_id = await propose(client, proposer, voting_days=3)

    a = await vote(client, yes_a, proposal_id, "yes")
    b = await vote(client, yes_b, proposal_id, "yes")
    c = await vote(client, no_c, proposal_id, "no")
    d = await vote(client, abstainer, proposal_id, "abstain")

    assert [r.status_code for r in (a, b, c, d)] == [201] * 4
    assert a.json()["vote_power"] == pytest.approx(300 * TRUST)
    assert b.json()["vote_power"] == pytest.approx(100 * 0.8)
    assert c.json()["vote_power"] == pytest.approx(120 * TRUST)
    shown = await listed(client, "/governance/proposals", proposal_id)
    assert shown["status"] == "active"
    assert shown["yes_power"] == pytest.approx(230)
    assert shown["no_power"] == pytest.approx(60)
    assert shown["abstain_power"] == pytest.approx(20)
    assert (shown["yes_votes"], shown["no_votes"], shown["abstain_votes"]) == (2, 1, 1)
    assert await listed(client, "/governance/results", proposal_id) is None
    assert await total_tokens(pool) == before    # voting moves no tokens


async def test_released_and_slashed_stakes_carry_no_weight(client, pool, agents, voters):
    from src.services import economy_service
    await economy_service.initialize_treasury()
    founder = await agents("founder", 0, role="FOUNDER")
    proposer = await voters("proposer")
    voter = await voters("voter")
    released = await stake(client, voter, 300)
    slashed = await stake(client, voter, 200)
    kept = await stake(client, voter, 50)
    assert (await release(client, released, voter)).status_code == 200
    slash = await client.post(
        "/economy/slash", json={"stake_id": slashed, "reason": "test"}, headers=founder.headers,
    )
    assert slash.status_code in (200, 201), slash.text
    proposal_id = await propose(client, proposer)

    resp = await vote(client, voter, proposal_id)

    assert resp.status_code == 201, resp.text
    assert resp.json()["vote_power"] == pytest.approx(50 * TRUST)
    assert kept


# ── One vote per agent per proposal ───────────────────────────────────────────

async def test_second_vote_is_refused_and_not_counted(client, pool, voters):
    proposer = await voters("proposer")
    voter = await voters("voter")
    await stake(client, voter, 200)
    proposal_id = await propose(client, proposer)

    first = await vote(client, voter, proposal_id, "yes")
    again = await vote(client, voter, proposal_id, "yes")
    flipped = await vote(client, voter, proposal_id, "no")

    assert first.status_code == 201
    assert again.status_code == 409
    assert flipped.status_code == 409
    row = await proposal_row(pool, proposal_id)
    assert (float(row["yes_power"]), float(row["no_power"])) == (pytest.approx(100), 0)
    assert len(await vote_rows(pool, proposal_id)) == 1


async def test_concurrent_votes_by_one_agent_count_once(client, pool, voters):
    proposer = await voters("proposer")
    voter = await voters("voter")
    await stake(client, voter, 200)
    proposal_id = await propose(client, proposer)

    responses = await asyncio.gather(*[vote(client, voter, proposal_id, "yes") for _ in range(12)])

    codes = sorted(r.status_code for r in responses)
    assert codes == [201] + [409] * 11, codes
    row = await proposal_row(pool, proposal_id)
    assert float(row["yes_power"]) == pytest.approx(100)
    assert len(await vote_rows(pool, proposal_id)) == 1


async def test_concurrent_votes_by_many_agents_all_count(client, pool, voters):
    proposer = await voters("proposer")
    crowd = [await voters(f"v{i}") for i in range(10)]
    for agent in crowd:
        await stake(client, agent, 100)
    proposal_id = await propose(client, proposer)

    responses = await asyncio.gather(*[
        vote(client, agent, proposal_id, "yes" if i % 2 == 0 else "no")
        for i, agent in enumerate(crowd)
    ])

    assert [r.status_code for r in responses] == [201] * 10
    row = await proposal_row(pool, proposal_id)
    assert float(row["yes_power"]) == pytest.approx(5 * 100 * TRUST)
    assert float(row["no_power"]) == pytest.approx(5 * 100 * TRUST)


# ── The stake behind a vote stays put while the proposal is open ──────────────

async def test_stake_behind_a_vote_cannot_be_released_while_voting_is_open(client, pool, voters):
    proposer = await voters("proposer")
    voter = await voters("voter")
    stake_id = await stake(client, voter, 400)
    proposal_id = await propose(client, proposer)
    assert (await vote(client, voter, proposal_id)).status_code == 201
    before = await total_tokens(pool)

    resp = await release(client, stake_id, voter)

    assert resp.status_code == 409, resp.text
    assert "open" in resp.json()["detail"]
    assert await balance(pool, voter) == START_BALANCE - 400
    released_at = await pool.fetchval(
        "SELECT released_at FROM stakes WHERE stake_id = $1", UUID(stake_id))
    assert released_at is None
    assert await total_tokens(pool) == before


async def test_same_tokens_cannot_vote_twice_through_a_second_account(client, pool, voters):
    """The attack: stake, vote, release, send the tokens to a second account,
    stake there, vote again."""
    proposer = await voters("proposer")
    first = await voters("first", funds=500)
    second = await voters("second", funds=0)
    stake_id = await stake(client, first, 500)
    proposal_id = await propose(client, proposer)
    assert (await vote(client, first, proposal_id, "yes")).status_code == 201

    unstake = await release(client, stake_id, first)
    move = await client.post(
        "/wallets/transfer",
        json={"to_id": str(second.agent_id), "amount": 500}, headers=first.headers,
    )
    restake = await client.post("/stakes", json={"amount": 500}, headers=second.headers)
    second_vote = await vote(client, second, proposal_id, "yes")

    assert unstake.status_code == 409
    assert move.status_code == 400           # nothing in the wallet to send
    assert restake.status_code == 400
    assert second_vote.status_code == 201    # may vote, but with no weight
    assert second_vote.json()["vote_power"] == 0
    row = await proposal_row(pool, proposal_id)
    assert float(row["yes_power"]) == pytest.approx(500 * TRUST)


async def test_stake_is_released_once_voting_has_closed(client, pool, voters):
    proposer = await voters("proposer")
    voter = await voters("voter")
    stake_id = await stake(client, voter, 400)
    proposal_id = await propose(client, proposer)
    assert (await vote(client, voter, proposal_id)).status_code == 201
    assert (await release(client, stake_id, voter)).status_code == 409

    await end_voting(pool, proposal_id)
    resp = await release(client, stake_id, voter)

    assert resp.status_code == 200, resp.text
    assert await balance(pool, voter) == START_BALANCE


async def test_a_vote_without_weight_does_not_hold_later_stakes(client, pool, voters):
    proposer = await voters("proposer")
    voter = await voters("voter")
    proposal_id = await propose(client, proposer)
    resp = await vote(client, voter, proposal_id)
    assert resp.status_code == 201 and resp.json()["vote_power"] == 0

    stake_id = await stake(client, voter, 100)

    assert (await release(client, stake_id, voter)).status_code == 200
    assert await balance(pool, voter) == START_BALANCE


async def test_a_vote_racing_a_release_never_keeps_both(client, pool, voters):
    """Fired together, one of two things happens: the release wins and the
    vote has no weight, or the vote has weight and the release is refused."""
    proposer = await voters("proposer")
    outcomes = set()
    for i in range(3):
        proposal_id = await propose(client, proposer)
        racers = [await voters(f"racer{i}-{n}") for n in range(8)]
        stake_ids = [await stake(client, r, 200) for r in racers]

        async def later(call, delay):
            await asyncio.sleep(delay)
            return await call

        # Half start the vote first, half the release, at slightly different moments.
        results = await asyncio.gather(*[
            later(call, delay)
            for n, (racer, stake_id) in enumerate(zip(racers, stake_ids))
            for call, delay in (
                (vote(client, racer, proposal_id), 0.002 * (n % 2) * (i + 1)),
                (release(client, stake_id, racer), 0.002 * ((n + 1) % 2) * (i + 1)),
            )
        ])

        for n, racer in enumerate(racers):
            cast, unstake = results[2 * n], results[2 * n + 1]
            assert cast.status_code == 201, cast.text
            weight = cast.json()["vote_power"]
            if unstake.status_code == 200:
                assert weight == 0, "tokens came back AND the vote kept their weight"
                assert await balance(pool, racer) == START_BALANCE
            else:
                assert unstake.status_code == 409, unstake.text
                assert weight == pytest.approx(200 * TRUST)
                assert await balance(pool, racer) == START_BALANCE - 200
            outcomes.add(unstake.status_code)
    assert outcomes <= {200, 409}


async def test_release_waits_for_a_vote_in_flight_and_is_then_refused(client, pool, voters):
    """The vote has counted the stake but not committed yet. A release fired
    in that moment must wait for it, then be refused."""
    proposer = await voters("proposer")
    voter = await voters("voter")
    stake_id = await stake(client, voter, 200)
    proposal_id = await propose(client, proposer)

    async with pool.acquire() as blocker:
        tx = blocker.transaction()
        await tx.start()
        # Hold the voter's agent row: the real vote passes its checks, locks
        # the stake rows, then waits here when its INSERT checks the voter
        # reference.
        await blocker.execute(
            "SELECT 1 FROM agents WHERE agent_id = $1 FOR UPDATE", voter.agent_id)
        cast_task = asyncio.create_task(vote(client, voter, proposal_id))
        await asyncio.sleep(0.4)
        unstake_task = asyncio.create_task(release(client, stake_id, voter))
        await asyncio.sleep(0.4)
        in_flight = (cast_task.done(), unstake_task.done())
        await tx.rollback()
    cast, unstake = await asyncio.gather(cast_task, unstake_task)

    assert in_flight == (False, False), "the release did not wait for the vote"
    assert cast.status_code == 201, cast.text
    assert cast.json()["vote_power"] == pytest.approx(200 * TRUST)
    assert unstake.status_code == 409, unstake.text
    assert await balance(pool, voter) == START_BALANCE - 200


async def test_vote_waits_for_a_release_in_flight_and_then_has_no_weight(client, pool, voters):
    """The release has marked the stake but not committed yet. A vote fired in
    that moment must wait for it, then not count the stake."""
    proposer = await voters("proposer")
    voter = await voters("voter")
    stake_id = await stake(client, voter, 200)
    proposal_id = await propose(client, proposer)

    async with pool.acquire() as blocker:
        tx = blocker.transaction()
        await tx.start()
        # Hold the wallet row: the release locks and marks the stake, then
        # waits here before it can credit the wallet.
        await blocker.execute(
            "SELECT 1 FROM wallets WHERE agent_id = $1 FOR UPDATE", voter.agent_id)
        unstake_task = asyncio.create_task(release(client, stake_id, voter))
        await asyncio.sleep(0.4)
        cast_task = asyncio.create_task(vote(client, voter, proposal_id))
        await asyncio.sleep(0.4)
        in_flight = (unstake_task.done(), cast_task.done())
        await tx.rollback()
    unstake, cast = await asyncio.gather(unstake_task, cast_task)

    assert in_flight == (False, False), "the vote did not wait for the release"
    assert unstake.status_code == 200, unstake.text
    assert cast.status_code == 201, cast.text
    assert cast.json()["vote_power"] == 0
    assert await balance(pool, voter) == START_BALANCE
    assert float((await proposal_row(pool, proposal_id))["yes_power"]) == 0


# ── Closing ───────────────────────────────────────────────────────────────────

async def test_no_vote_after_the_close(client, pool, voters):
    proposer = await voters("proposer")
    voter = await voters("voter")
    await stake(client, voter, 400)
    proposal_id = await propose(client, proposer)
    await end_voting(pool, proposal_id)

    late = await vote(client, voter, proposal_id)                 # due, not yet closed
    result = await listed(client, "/governance/results", proposal_id)   # closes it
    later = await vote(client, voter, proposal_id)                # closed

    assert late.status_code == 409
    assert later.status_code == 409
    assert result["status"] == "failed"                           # nobody voted
    assert await vote_rows(pool, proposal_id) == []
    assert await listed(client, "/governance/proposals", proposal_id) is None


async def test_unknown_proposal_is_404(client, pool, voters):
    voter = await voters("voter")
    resp = await vote(client, voter, str(uuid4()))
    assert resp.status_code == 404


async def test_passes_with_quorum_and_a_majority(client, pool, voters):
    proposer = await voters("proposer")
    yes, no = await voters("yes"), await voters("no")
    await stake(client, yes, 300)       # 150
    await stake(client, no, 100)        # 50
    proposal_id = await propose(client, proposer)
    await vote(client, yes, proposal_id, "yes")
    await vote(client, no, proposal_id, "no")

    result = await close_and_get(client, pool, proposal_id)

    assert result["status"] == "passed"
    assert (result["yes_power"], result["no_power"]) == (pytest.approx(150), pytest.approx(50))
    assert (result["yes_votes"], result["no_votes"]) == (1, 1)


async def test_fails_without_quorum_even_if_every_vote_is_yes(client, pool, voters):
    proposer = await voters("proposer")
    lone = await voters("lone")
    await stake(client, lone, 2 * QUORUM - 2)      # weight 99: one short
    proposal_id = await propose(client, proposer)
    assert (await vote(client, lone, proposal_id, "yes")).status_code == 201

    result = await close_and_get(client, pool, proposal_id)

    assert result["status"] == "failed"
    assert result["yes_power"] == pytest.approx(QUORUM - 1)


async def test_abstentions_count_towards_the_quorum_only(client, pool, voters):
    proposer = await voters("proposer")
    yes, abstainer = await voters("yes"), await voters("abstainer")
    await stake(client, yes, 60)            # 30
    await stake(client, abstainer, 140)     # 70 → total 100 = quorum
    proposal_id = await propose(client, proposer)
    await vote(client, yes, proposal_id, "yes")
    await vote(client, abstainer, proposal_id, "abstain")

    result = await close_and_get(client, pool, proposal_id)

    assert result["status"] == "passed"
    assert result["abstain_power"] == pytest.approx(70)


async def test_a_tie_fails_and_so_does_a_no_majority(client, pool, voters):
    proposer = await voters("proposer")
    a, b, c = await voters("a"), await voters("b"), await voters("c")
    await stake(client, a, 200)
    await stake(client, b, 200)
    await stake(client, c, 300)
    tie = await propose(client, proposer)
    lost = await propose(client, proposer)
    await vote(client, a, tie, "yes")
    await vote(client, b, tie, "no")
    await vote(client, a, lost, "yes")
    await vote(client, c, lost, "no")

    assert (await close_and_get(client, pool, tie))["status"] == "failed"
    assert (await close_and_get(client, pool, lost))["status"] == "failed"


async def test_outcome_is_recounted_from_the_vote_rows(client, pool, voters):
    """The running counters on the proposal row are not what decides."""
    proposer = await voters("proposer")
    no = await voters("no")
    await stake(client, no, 400)
    proposal_id = await propose(client, proposer)
    await vote(client, no, proposal_id, "no")
    await pool.execute(
        "UPDATE proposals SET yes_power = 999999 WHERE proposal_id = $1", UUID(proposal_id))

    result = await close_and_get(client, pool, proposal_id)

    assert result["status"] == "failed"
    assert (result["yes_power"], result["no_power"]) == (0, pytest.approx(200))


async def test_finalize_refuses_an_open_proposal_and_is_idempotent(client, pool, voters):
    from src.services import governance_service
    proposer = await voters("proposer")
    yes = await voters("yes")
    await stake(client, yes, 300)
    proposal_id = await propose(client, proposer)
    await vote(client, yes, proposal_id, "yes")

    with pytest.raises(governance_service.GovernanceConflictError):
        await governance_service.finalize_proposal(UUID(proposal_id))
    assert (await proposal_row(pool, proposal_id))["status"] == "active"

    await end_voting(pool, proposal_id)
    first = await governance_service.finalize_proposal(UUID(proposal_id))
    second = await governance_service.finalize_proposal(UUID(proposal_id))
    swept = await asyncio.gather(*[governance_service.finalize_due_proposals() for _ in range(5)])

    assert first.status == second.status == "passed"
    assert (await proposal_row(pool, proposal_id))["status"] == "passed"
    assert all(isinstance(n, int) for n in swept)


async def test_unusable_rules_fall_back_to_the_defaults(client, pool, voters):
    proposer = await voters("proposer")
    lone = await voters("lone")
    await stake(client, lone, 20)           # weight 10: far below the quorum
    proposal_id = await propose(client, proposer)
    await vote(client, lone, proposal_id, "yes")
    await pool.execute(
        "UPDATE governance_parameters SET value = 'not-a-number' WHERE name = 'quorum_threshold'")
    await pool.execute(
        "UPDATE governance_parameters SET value = '-1' WHERE name = 'pass_threshold'")
    try:
        result = await close_and_get(client, pool, proposal_id)
    finally:
        await pool.execute(
            "UPDATE governance_parameters SET value = '100' WHERE name = 'quorum_threshold'")
        await pool.execute(
            "UPDATE governance_parameters SET value = '0.5' WHERE name = 'pass_threshold'")

    assert result["status"] == "failed"     # default quorum (100) still applies


async def test_parameters_are_public(client, pool):
    resp = await client.get("/governance/parameters")

    assert resp.status_code == 200, resp.text
    rules = {p["name"]: p["value"] for p in resp.json()}
    assert rules["quorum_threshold"] == "100"
    assert rules["pass_threshold"] == "0.5"


# ── Anti-flood and bounds ─────────────────────────────────────────────────────

async def test_at_most_three_open_proposals_per_agent(client, pool, voters):
    proposer = await voters("proposer")
    other = await voters("other")
    ids = [await propose(client, proposer) for _ in range(3)]

    fourth = await client.post(
        "/governance/proposals", json={"title": "4", "description": "d"},
        headers=proposer.headers,
    )
    assert fourth.status_code == 409, fourth.text
    assert await propose(client, other)                 # the cap is per agent

    await end_voting(pool, ids[0])                      # one closes → room again
    assert await propose(client, proposer)


async def test_concurrent_creates_cannot_pass_the_cap(client, pool, voters):
    proposer = await voters("proposer")

    responses = await asyncio.gather(*[
        client.post(
            "/governance/proposals", json={"title": f"p{i}", "description": "d"},
            headers=proposer.headers,
        )
        for i in range(10)
    ])

    codes = sorted(r.status_code for r in responses)
    assert codes == [201] * 3 + [409] * 7, codes
    count = await pool.fetchval(
        "SELECT COUNT(*) FROM proposals WHERE proposer_id = $1", proposer.agent_id)
    assert count == 3


@pytest.mark.parametrize("body", [
    {"title": "t", "description": "x" * 10_001},
    {"title": "t" * 201, "description": "d"},
    {"title": "t", "description": "d", "proposal_type": "Not A Slug!"},
    {"title": "t", "description": "d", "proposal_type": "x" * 41},
    {"title": "t", "description": "d", "payload": {"blob": "x" * 20_000}},
    {"title": "t", "description": "d", "voting_days": 31},
    {"title": "t", "description": "d", "voting_days": 0},
])
async def test_oversized_or_malformed_proposals_are_refused(client, pool, voters, body):
    proposer = await voters("proposer")

    resp = await client.post("/governance/proposals", json=body, headers=proposer.headers)

    assert resp.status_code == 422, resp.text
    count = await pool.fetchval(
        "SELECT COUNT(*) FROM proposals WHERE proposer_id = $1", proposer.agent_id)
    assert count == 0


async def test_bad_vote_values_and_page_sizes_are_refused(client, pool, voters):
    proposer = await voters("proposer")
    proposal_id = await propose(client, proposer)

    assert (await vote(client, proposer, proposal_id, "maybe")).status_code == 422
    assert (await vote(client, proposer, "not-a-uuid")).status_code == 422
    for path in ("/governance/proposals", "/governance/results"):
        assert (await client.get(path, params={"limit": 201})).status_code == 422
        assert (await client.get(path, params={"limit": 0})).status_code == 422
        assert (await client.get(path, params={"offset": -1})).status_code == 422
        assert (await client.get(path, params={"limit": 1})).status_code == 200
