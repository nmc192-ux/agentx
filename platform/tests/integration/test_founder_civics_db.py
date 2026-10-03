"""
Integration tests: the founders' weekly bounty and governance proposal in
the heartbeat tick (src/jobs/founder_heartbeat.py + src/founders/civics.py)
against REAL local Postgres. Sprint 10, S10-7. No money or vote path is
mocked: the tick calls bounty_service (create, submit, evaluate, distribute,
cancel), governance_service (create_proposal, vote_on_proposal) and
token_service.stake_tokens, which escrow, pay, refund and lock through the
same code the public routes use.

What is proven:
  • one bounty end to end: posted at its planned moment, not before, with
    the pool escrowed from the creator's own wallet (ledger: one
    bounty_escrow); the matching founder and the planned others submit on
    their moments, not before, once each; the creator judges after
    BOUNTY_JUDGE_AFTER, not before: every submission scored, the best paid
    the whole pool once (ledger: one bounty_reward), the bounty 'rewarded';
    wallets + escrow add up throughout; no trust event (bounties are not a
    counted event under S9-9b); a later tick changes nothing
  • a bounty nobody submitted to is cancelled and the pool comes back
  • an outside agent's submission stops the founder from judging: the
    bounty stays open, the pool stays in escrow, the tick says why
  • an outside agent's bounty gets no founder submission; an outside
    agent's proposal gets no founder vote
  • a short or missing wallet means no bounty and no ledger entry; the pool
    is clamped to FOUNDER_BOUNTY_POOL_MAX; 0 switches bounties off
  • one proposal: posted at its planned moment with the heartbeat payload;
    at least three other founders vote on their moments, each staking
    FOUNDER_VOTE_STAKE once first (ledger: one stake each, wallet down,
    stake row unreleased) so vote power = stake × trust; nobody votes twice;
    the proposer never votes; the proposal closes through
    finalize_due_proposals with the tally the votes add up to
  • FOUNDER_VOTE_STAKE = 0: votes are cast unweighted and nothing is locked;
    a founder that cannot afford the stake still votes, unweighted

The eight seeded `-001` founders are used with wallets the test funds and
restores; every test cleans up bounties, submissions, rewards, proposals,
votes, stakes, ledger entries and events it made. Run:
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from src.config import Settings
from src.founders import civics as fc
from src.founders import messages as fm
from src.founders.generation import GeneratedPost
from src.founders.personas import FOUNDER_NAMES, PERSONAS
from src.founders.roster import founder_roster
from src.jobs import founder_heartbeat as fh
from src.services import governance_service

from .support import total_tokens

pytestmark = pytest.mark.integration   # skipped unless --db is given

WEEK = (2026, 41)                       # Monday 2026-10-05
DEV = founder_roster("", "development")
FOUNDER_DIDS = tuple(DEV[n] for n in FOUNDER_NAMES)
BY_DID = {DEV[n]: n for n in FOUNDER_NAMES}
OUTSIDER = "did:agentx:outsider-707"
START = 500
ON = Settings(_env_file=None, founder_heartbeat_enabled="true", founder_llm_provider="")


def settings_with(**kw) -> Settings:
    return Settings(_env_file=None, founder_heartbeat_enabled="true", founder_llm_provider="", **kw)


class SilentGenerator:
    """No top-level posts (so no replies either)."""
    async def generate(self, persona, context, rng, now=None) -> GeneratedPost:
        raise RuntimeError("no posts in this test")


@pytest.fixture(autouse=True)
def only_civics(monkeypatch):
    """Tasks are S10-6's and DMs S10-5's; keep both out of the ledger here."""
    monkeypatch.setattr(fh, "due_task_plans", lambda *_a, **_k: [])
    monkeypatch.setattr(fh, "due_openings", lambda *_a, **_k: [])
    monkeypatch.setattr(fh, "plan_answer", lambda *_a, **_k: fm.AnswerPlan(False, 0.0))


@pytest_asyncio.fixture
async def clean(pool):
    everyone = list(FOUNDER_DIDS) + [OUTSIDER]
    wallets_before = {r["agent_did"]: r["balance"] for r in await pool.fetch(
        "SELECT a.agent_did, w.balance FROM wallets w JOIN agents a ON a.agent_id = w.agent_id "
        "WHERE a.agent_did = ANY($1::text[])", list(FOUNDER_DIDS),
    )}

    async def wipe():
        await pool.execute(
            "DELETE FROM transactions WHERE related_id IN "
            "(SELECT bounty_id FROM capability_bounties WHERE creator_did = ANY($1::text[]))", everyone,
        )
        await pool.execute(
            "DELETE FROM transactions WHERE related_id IN (SELECT stake_id FROM stakes s "
            "JOIN agents a ON a.agent_id = s.agent_id WHERE a.agent_did = ANY($1::text[]))", everyone,
        )
        await pool.execute(
            "DELETE FROM transactions WHERE from_wallet IN (SELECT wallet_id FROM wallets w "
            "JOIN agents a ON a.agent_id = w.agent_id WHERE a.agent_did = ANY($1::text[])) "
            "OR to_wallet IN (SELECT wallet_id FROM wallets w JOIN agents a "
            "ON a.agent_id = w.agent_id WHERE a.agent_did = ANY($1::text[]))", everyone,
        )
        await pool.execute(
            "DELETE FROM capability_bounties WHERE creator_did = ANY($1::text[])", everyone,
        )   # submissions and rewards cascade
        await pool.execute("DELETE FROM governance_votes WHERE voter_did = ANY($1::text[])", everyone)
        await pool.execute("DELETE FROM proposals WHERE proposer_did = ANY($1::text[])", everyone)
        await pool.execute(
            "DELETE FROM stakes WHERE agent_id IN "
            "(SELECT agent_id FROM agents WHERE agent_did = ANY($1::text[]))", everyone,
        )
        await pool.execute("DELETE FROM trust_events WHERE agent_did = ANY($1::text[])", everyone)
        await pool.execute("DELETE FROM events WHERE agent_did = ANY($1::text[])", everyone)
        await pool.execute(
            "UPDATE agents SET last_seen_at = NULL WHERE agent_did = ANY($1::text[])", list(FOUNDER_DIDS),
        )
        await pool.execute(
            "DELETE FROM wallets WHERE agent_id IN "
            "(SELECT agent_id FROM agents WHERE agent_did = ANY($1::text[]))", everyone,
        )
        await pool.execute("DELETE FROM agents WHERE agent_did = $1", OUTSIDER)

    await wipe()
    await pool.execute(
        "INSERT INTO agents (agent_did, display_name, created_at) "
        "VALUES ($1, 'Outsider', CURRENT_TIMESTAMP - INTERVAL '30 days')", OUTSIDER,
    )
    yield
    await wipe()
    for did, balance in wallets_before.items():
        await pool.execute(
            "INSERT INTO wallets (agent_id, balance) SELECT agent_id, $2 FROM agents "
            "WHERE agent_did = $1", did, balance,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def fund(pool, *dids: str, balance: int = START) -> None:
    for did in dids:
        await pool.execute(
            "INSERT INTO wallets (agent_id, balance) SELECT agent_id, $2 FROM agents "
            "WHERE agent_did = $1 ON CONFLICT (agent_id) DO UPDATE SET balance = EXCLUDED.balance",
            did, balance,
        )


async def balance(pool, did: str) -> int | None:
    return await pool.fetchval(
        "SELECT w.balance FROM wallets w JOIN agents a ON a.agent_id = w.agent_id "
        "WHERE a.agent_did = $1", did,
    )


async def tick(now: datetime, seed: str, **kw) -> dict:
    kw.setdefault("roster", DEV)
    kw.setdefault("settings", ON)
    summary = await fh.run_tick(
        now=now, generator=SilentGenerator(), rng=random.Random(5), civic_seed=seed, **kw,
    )
    assert summary["bounty_errors"] == {} and summary["gov_errors"] == {}, summary
    return summary


async def bounties(pool) -> list[dict]:
    return [dict(r) for r in await pool.fetch(
        "SELECT bounty_id, creator_did, capability_required, reward_pool, status, deadline, "
        "winner_submission_id FROM capability_bounties WHERE creator_did = ANY($1::text[]) "
        "ORDER BY created_at, bounty_id", list(FOUNDER_DIDS) + [OUTSIDER],
    )]


async def submissions(pool, bounty_id) -> list[dict]:
    out = []
    for r in await pool.fetch(
        "SELECT submission_id, submitter_did, status, score, solution_data, summary "
        "FROM bounty_submissions WHERE bounty_id = $1 ORDER BY submitted_at, submission_id", bounty_id,
    ):
        d = dict(r)
        if isinstance(d["solution_data"], str):
            d["solution_data"] = json.loads(d["solution_data"])
        out.append(d)
    return out


async def ledger(pool, related_id, tx_type: str) -> list[int]:
    return [r["amount"] for r in await pool.fetch(
        "SELECT amount FROM transactions WHERE related_id = $1 AND type = $2 ORDER BY timestamp",
        related_id, tx_type,
    )]


async def proposals(pool) -> list[dict]:
    out = []
    for r in await pool.fetch(
        "SELECT proposal_id, proposer_did, title, status, payload, yes_power, no_power, "
        "voting_ends_at FROM proposals WHERE proposer_did = ANY($1::text[]) ORDER BY created_at",
        list(FOUNDER_DIDS) + [OUTSIDER],
    ):
        d = dict(r)
        if isinstance(d["payload"], str):
            d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


async def votes(pool, proposal_id) -> list[dict]:
    return [dict(r) for r in await pool.fetch(
        "SELECT voter_did, vote, vote_power FROM governance_votes WHERE proposal_id = $1 "
        "ORDER BY created_at", proposal_id,
    )]


async def stakes(pool, did: str) -> list[dict]:
    return [dict(r) for r in await pool.fetch(
        "SELECT s.stake_id, s.amount, s.released_at FROM stakes s JOIN agents a ON a.agent_id = s.agent_id "
        "WHERE a.agent_did = $1 ORDER BY s.created_at", did,
    )]


async def trust_events(pool) -> int:
    return await pool.fetchval(
        "SELECT COUNT(*) FROM trust_events WHERE agent_did = ANY($1::text[])", list(FOUNDER_DIDS),
    )


def planned_submitters(plan: fc.BountyPlan, seed: str) -> dict[str, datetime]:
    out = {}
    for n in FOUNDER_NAMES:
        at = fc.plan_submission(PERSONAS[n], plan.creator, plan.match, plan.at, seed)
        if at is not None:
            out[n] = at
    return out


def planned_voters(plan: fc.ProposalPlan, seed: str) -> dict[str, fc.VotePlan]:
    return {n: v for n in FOUNDER_NAMES
            if (v := fc.plan_vote(PERSONAS[n], plan.proposer, plan.at, seed)).wants}


def find_seed(creator: str | None = None, *, voters_at_least: int = 3) -> str:
    """A civic seed under which the week's bounty is *creator*'s (any
    founder's when None), its moment and every planned moment after it
    (submissions, judging, votes) fall while the acting founder is awake,
    and at least *voters_at_least* founders plan to vote on the proposal;
    the bounty and the proposal are more than 2 days apart so a test's
    ticks can look at one without the other."""
    for i in range(50_000):
        seed = f"c{i}"
        plan = fc.plan_bounty(WEEK, seed)
        if creator is not None and plan.creator != creator:
            continue
        subs = planned_submitters(plan, seed)
        if any(PERSONAS[n].is_quiet(at) for n, at in subs.items()):
            continue
        if PERSONAS[plan.creator].is_quiet(plan.at + fc.BOUNTY_JUDGE_AFTER):
            continue
        prop = fc.plan_proposal(WEEK, seed)
        voters = planned_voters(prop, seed)
        if len(voters) < voters_at_least or any(PERSONAS[n].is_quiet(v.at) for n, v in voters.items()):
            continue
        if abs(prop.at - plan.at) < timedelta(days=2, hours=12):
            continue
        return seed
    raise AssertionError("no seed found")


# ── One bounty end to end ─────────────────────────────────────────────────────

async def test_one_bounty_is_posted_submitted_judged_and_paid_once(pool, clean):
    seed = find_seed("thea")
    plan = fc.plan_bounty(WEEK, seed)
    thea = DEV["thea"]
    subs = planned_submitters(plan, seed)
    assert plan.match in subs and "thea" not in subs
    await fund(pool, *FOUNDER_DIDS)
    supply = await total_tokens(pool)

    early = await tick(plan.at - timedelta(minutes=1), seed)
    assert early["bounty_posted"] == {} and await bounties(pool) == []

    posted = await tick(plan.at + timedelta(minutes=1), seed)
    (bounty,) = await bounties(pool)
    bid = bounty["bounty_id"]
    assert posted["bounty_posted"] == {"thea": str(bid)} and posted["bounty_skipped"] == {}
    assert bounty["creator_did"] == thea and bounty["status"] == "open"
    assert bounty["capability_required"] == plan.capability
    assert bounty["reward_pool"] == plan.pool and bounty["deadline"] == plan.deadline
    assert await ledger(pool, bid, "bounty_escrow") == [plan.pool]
    assert await balance(pool, thea) == START - plan.pool
    assert await total_tokens(pool) == supply
    # The same tick again: nothing more.
    again = await tick(plan.at + timedelta(minutes=2), seed)
    assert again["bounty_posted"] == {} and len(await bounties(pool)) == 1

    # Submissions land on their moments, not before, once each.
    for name, at in sorted(subs.items(), key=lambda kv: kv[1]):
        before = await tick(at - timedelta(minutes=1), seed)
        assert name not in before["bounty_submitted"]
        assert all(s["submitter_did"] != DEV[name] for s in await submissions(pool, bid))
        done = await tick(at + timedelta(minutes=1), seed)
        assert done["bounty_submitted"].get(name) == str(bid), done
    rows = await submissions(pool, bid)
    assert sorted(BY_DID[s["submitter_did"]] for s in rows) == sorted(subs)
    assert all(s["status"] == "pending" and s["score"] is None for s in rows)
    assert all(s["solution_data"]["heartbeat"]["kind"] == fc.KIND_SUBMISSION for s in rows)
    assert (await bounties(pool))[0]["status"] == "open"
    assert await total_tokens(pool) == supply

    # Judging: not before BOUNTY_JUDGE_AFTER; then every entry scored and the
    # best paid the whole pool once.
    judge_at = plan.at + fc.BOUNTY_JUDGE_AFTER
    before = await tick(judge_at - timedelta(minutes=1), seed)
    assert before["bounty_judged"] == {} and (await bounties(pool))[0]["status"] == "open"
    judged = await tick(judge_at, seed)
    assert judged["bounty_judged"] == {"thea": str(bid)}
    rows = await submissions(pool, bid)
    expected = {s["submission_id"]: fc.plan_score(PERSONAS["thea"], s["submission_id"], seed) for s in rows}
    assert {s["submission_id"]: s["score"] for s in rows} == pytest.approx(expected)
    winner_row = max(rows, key=lambda s: s["score"])
    winner = BY_DID[winner_row["submitter_did"]]
    assert judged["bounty_paid"] == {winner: plan.pool}
    assert [s["status"] for s in rows] == ["won" if s is winner_row else "closed" for s in rows]
    (bounty,) = await bounties(pool)
    assert bounty["status"] == "rewarded" and bounty["winner_submission_id"] == winner_row["submission_id"]
    assert await ledger(pool, bid, "bounty_reward") == [plan.pool]
    assert await balance(pool, thea) == START - plan.pool
    assert await balance(pool, DEV[winner]) == START + plan.pool
    assert await total_tokens(pool) == supply
    assert await trust_events(pool) == 0     # bounties are not a counted trust event

    later = await tick(judge_at + timedelta(hours=1), seed)
    assert later["bounty_judged"] == {} and later["bounty_submitted"] == {} and later["bounty_posted"] == {}
    assert await ledger(pool, bid, "bounty_reward") == [plan.pool]
    assert await total_tokens(pool) == supply


async def test_a_bounty_nobody_submitted_to_is_cancelled_and_refunded(pool, clean, monkeypatch):
    seed = find_seed("bruno")
    plan = fc.plan_bounty(WEEK, seed)
    bruno = DEV["bruno"]
    await fund(pool, *FOUNDER_DIDS)
    supply = await total_tokens(pool)
    monkeypatch.setattr(fh, "plan_submission", lambda *_a, **_k: None)

    posted = await tick(plan.at + timedelta(minutes=1), seed)
    (bounty,) = await bounties(pool)
    bid = bounty["bounty_id"]
    assert posted["bounty_posted"] == {"bruno": str(bid)}
    assert await balance(pool, bruno) == START - plan.pool

    mid = await tick(plan.at + timedelta(hours=20), seed)
    assert mid["bounty_submitted"] == {} and await submissions(pool, bid) == []

    judged = await tick(plan.at + fc.BOUNTY_JUDGE_AFTER, seed)
    assert judged["bounty_cancelled"] == {"bruno": str(bid)} and judged["bounty_judged"] == {}
    (bounty,) = await bounties(pool)
    assert bounty["status"] == "cancelled"
    assert await ledger(pool, bid, "bounty_escrow") == [plan.pool]
    assert await ledger(pool, bid, "bounty_refund") == [plan.pool]
    assert await balance(pool, bruno) == START
    assert await total_tokens(pool) == supply


async def test_an_outsiders_submission_stops_the_founder_from_judging(pool, clean):
    seed = find_seed("marcus")
    plan = fc.plan_bounty(WEEK, seed)
    await fund(pool, *FOUNDER_DIDS)
    supply = await total_tokens(pool)

    await tick(plan.at + timedelta(minutes=1), seed)
    (bounty,) = await bounties(pool)
    bid = bounty["bounty_id"]
    await pool.execute(
        "INSERT INTO bounty_submissions (bounty_id, submitter_did, submitter_id, solution_data, summary) "
        "SELECT $1, agent_did, agent_id, '{}'::jsonb, 'real work' FROM agents WHERE agent_did = $2",
        bid, OUTSIDER,
    )
    for name, at in planned_submitters(plan, seed).items():
        await tick(at + timedelta(minutes=1), seed)

    judged = await tick(plan.at + fc.BOUNTY_JUDGE_AFTER, seed)
    assert judged["bounty_skipped"] == {"marcus": "outsider_submitted"}
    assert judged["bounty_judged"] == {} and judged["bounty_cancelled"] == {}
    (bounty,) = await bounties(pool)
    assert bounty["status"] == "open"
    rows = await submissions(pool, bid)
    assert all(s["status"] == "pending" and s["score"] is None for s in rows)
    assert await ledger(pool, bid, "bounty_reward") == []
    assert await balance(pool, DEV["marcus"]) == START - plan.pool
    assert await total_tokens(pool) == supply
    # ...and a day later it is still waiting for a person.
    later = await tick(plan.at + fc.BOUNTY_JUDGE_AFTER + timedelta(days=1), seed)
    assert later["bounty_skipped"] == {"marcus": "outsider_submitted"}
    assert (await bounties(pool))[0]["status"] == "open"


async def test_outsiders_bounties_and_proposals_are_left_alone(pool, clean):
    seed = find_seed()
    plan = fc.plan_bounty(WEEK, seed)
    prop = fc.plan_proposal(WEEK, seed)
    await fund(pool, *FOUNDER_DIDS, OUTSIDER)
    # An outsider's bounty dressed up like the week's founder bounty...
    await pool.execute(
        "INSERT INTO capability_bounties (creator_did, creator_id, title, description, "
        "capability_required, reward_pool, deadline) "
        "SELECT agent_did, agent_id, 'Looks founder-made', '', $2, 15, $3 FROM agents WHERE agent_did = $1",
        OUTSIDER, plan.capability, plan.deadline,
    )
    # ...and an outsider's proposal with the heartbeat payload.
    await pool.execute(
        "INSERT INTO proposals (proposer_did, proposer_id, title, description, payload, voting_ends_at) "
        "SELECT agent_did, agent_id, 'Outsider proposal', 'text', $2::jsonb, CURRENT_TIMESTAMP + INTERVAL '3 days' "
        "FROM agents WHERE agent_did = $1",
        OUTSIDER, json.dumps(fc.proposal_payload(prop, prop.at)),
    )
    # Keep the founders' own bounty and proposal of the week out of the way.
    settings = settings_with(founder_bounty_pool_max=0)
    end = max(plan.at + fc.BOUNTY_JUDGE_AFTER, prop.at + timedelta(hours=fc.VOTE_DELAY_HOURS[1]))
    t = min(plan.at, prop.at)
    while t <= end + timedelta(hours=1):
        s = await tick(t, seed, settings=settings)
        assert s["bounty_submitted"] == {}, s     # the only bounty around is the outsider's
        t += timedelta(hours=3)
    (outsider_bounty,) = [b for b in await bounties(pool) if b["creator_did"] == OUTSIDER]
    assert await submissions(pool, outsider_bounty["bounty_id"]) == []
    (outsider_prop,) = [p for p in await proposals(pool) if p["proposer_did"] == OUTSIDER]
    assert await votes(pool, outsider_prop["proposal_id"]) == []
    # The founders did vote this week — on their own proposal, nowhere else.
    founder_votes = await pool.fetch(
        "SELECT p.proposer_did FROM governance_votes v JOIN proposals p ON p.proposal_id = v.proposal_id "
        "WHERE v.voter_did = ANY($1::text[])", list(FOUNDER_DIDS),
    )
    assert founder_votes and all(r["proposer_did"] in FOUNDER_DIDS for r in founder_votes)


# ── Funding and caps ──────────────────────────────────────────────────────────

async def test_a_short_or_missing_wallet_means_no_bounty(pool, clean):
    seed = find_seed("quinn")
    plan = fc.plan_bounty(WEEK, seed)
    quinn = DEV["quinn"]
    at = plan.at + timedelta(minutes=1)

    none = await tick(at, seed)
    assert none["bounty_skipped"] == {"quinn": "no_wallet"} and none["bounty_posted"] == {}

    await fund(pool, quinn, balance=plan.pool - 1)
    short = await tick(at, seed)
    assert short["bounty_skipped"] == {"quinn": "wallet_short"} and short["bounty_posted"] == {}
    assert await bounties(pool) == []
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM transactions tx JOIN wallets w ON w.wallet_id = tx.from_wallet "
        "JOIN agents a ON a.agent_id = w.agent_id WHERE a.agent_did = $1", quinn) == 0

    await fund(pool, quinn, balance=plan.pool)
    ok = await tick(at, seed)
    assert ok["bounty_posted"] == {"quinn": str((await bounties(pool))[0]["bounty_id"])}
    assert await balance(pool, quinn) == 0


async def test_the_pool_is_clamped_by_the_setting_and_zero_switches_bounties_off(pool, clean):
    seed = find_seed("gia")
    plan = fc.plan_bounty(WEEK, seed)
    gia = DEV["gia"]
    await fund(pool, *FOUNDER_DIDS)
    at = plan.at + timedelta(minutes=1)

    off = await tick(at, seed, settings=settings_with(founder_bounty_pool_max=0))
    assert off["bounty_posted"] == {} and off["bounty_skipped"] == {} and await bounties(pool) == []

    cap = plan.pool - 3
    clamped = await tick(at, seed, settings=settings_with(founder_bounty_pool_max=cap))
    (bounty,) = await bounties(pool)
    assert clamped["bounty_posted"] == {"gia": str(bounty["bounty_id"])}
    assert bounty["reward_pool"] == cap
    assert await ledger(pool, bounty["bounty_id"], "bounty_escrow") == [cap]
    assert await balance(pool, gia) == START - cap


# ── One proposal, voted on by at least three founders ─────────────────────────

async def test_one_proposal_gets_staked_votes_and_closes(pool, clean):
    seed = find_seed(voters_at_least=3)
    prop = fc.plan_proposal(WEEK, seed)
    voters = planned_voters(prop, seed)
    proposer = DEV[prop.proposer]
    assert len(voters) >= 3 and prop.proposer not in voters
    await fund(pool, *FOUNDER_DIDS)
    supply = await total_tokens(pool)
    stake = ON.founder_vote_stake
    assert stake > 0
    trust = {r["agent_did"]: float(r["trust_score"] or 0.0) for r in await pool.fetch(
        "SELECT agent_did, trust_score FROM agents WHERE agent_did = ANY($1::text[])", list(FOUNDER_DIDS),
    )}

    early = await tick(prop.at - timedelta(minutes=1), seed)
    assert early["proposal_posted"] == {} and await proposals(pool) == []

    posted = await tick(prop.at + timedelta(minutes=1), seed)
    (p,) = await proposals(pool)
    pid = p["proposal_id"]
    assert posted["proposal_posted"] == {prop.proposer: str(pid)} and posted["gov_skipped"] == {}
    assert p["proposer_did"] == proposer and p["status"] == "active"
    assert p["payload"]["heartbeat"]["kind"] == fc.KIND_PROPOSAL
    assert p["payload"]["heartbeat"]["at"] == prop.at.isoformat()
    assert p["payload"]["heartbeat"]["week"] == "2026-W41"
    assert prop.topic in p["title"]
    again = await tick(prop.at + timedelta(minutes=2), seed)
    assert again["proposal_posted"] == {} and len(await proposals(pool)) == 1

    # Votes land on their moments, not before, once each, staked first.
    for name, plan in sorted(voters.items(), key=lambda kv: kv[1].at):
        before = await tick(plan.at - timedelta(minutes=1), seed)
        assert name not in before["voted"]
        assert all(v["voter_did"] != DEV[name] for v in await votes(pool, pid))
        done = await tick(plan.at + timedelta(minutes=1), seed)
        assert done["voted"].get(name) == plan.choice, done
        assert done["staked"].get(name) == stake
        assert done["vote_power"][name] == pytest.approx(stake * trust[DEV[name]])
        (row,) = await stakes(pool, DEV[name])
        assert row["amount"] == stake and row["released_at"] is None
        assert await ledger(pool, row["stake_id"], "stake") == [stake]
        assert await balance(pool, DEV[name]) == START - stake
    cast = await votes(pool, pid)
    assert sorted(BY_DID[v["voter_did"]] for v in cast) == sorted(voters)
    assert {BY_DID[v["voter_did"]]: v["vote"] for v in cast} == {n: v.choice for n, v in voters.items()}
    assert all(v["voter_did"] != proposer for v in cast)
    assert await balance(pool, proposer) == START
    assert await total_tokens(pool) == supply
    assert await trust_events(pool) == 0

    # Nobody votes or stakes twice.
    later = await tick(prop.at + timedelta(hours=fc.VOTE_DELAY_HOURS[1] + 1), seed)
    assert later["voted"] == {} and later["staked"] == {}
    assert len(await votes(pool, pid)) == len(voters)
    for name in voters:
        assert len(await stakes(pool, DEV[name])) == 1

    # The proposal closes through the service everyone's proposals close by.
    await pool.execute(
        "UPDATE proposals SET voting_ends_at = CURRENT_TIMESTAMP - INTERVAL '1 second' "
        "WHERE proposal_id = $1", pid,
    )
    assert await governance_service.finalize_due_proposals() >= 1
    (p,) = await proposals(pool)
    assert p["status"] in ("passed", "failed")
    yes = sum(float(v["vote_power"]) for v in cast if v["vote"] == "yes")
    no = sum(float(v["vote_power"]) for v in cast if v["vote"] == "no")
    abstain = sum(float(v["vote_power"]) for v in cast if v["vote"] == "abstain")
    assert float(p["yes_power"]) == pytest.approx(yes) and float(p["no_power"]) == pytest.approx(no)
    from decimal import Decimal
    expected = governance_service.decide_outcome(
        Decimal(str(yes)), Decimal(str(no)), Decimal(str(abstain)),
        governance_service.DEFAULT_QUORUM_THRESHOLD, governance_service.DEFAULT_PASS_THRESHOLD,
    )
    assert p["status"] == expected
    assert await total_tokens(pool) == supply


async def test_votes_without_a_stake_are_cast_unweighted(pool, clean):
    seed = find_seed(voters_at_least=3)
    prop = fc.plan_proposal(WEEK, seed)
    voters = planned_voters(prop, seed)
    poor, *rest = sorted(voters)
    await fund(pool, *FOUNDER_DIDS)
    await fund(pool, DEV[poor], balance=ON.founder_vote_stake - 1)
    end = prop.at + timedelta(hours=fc.VOTE_DELAY_HOURS[1] + 1)

    # Setting 0: votes, no stakes, nothing locked.
    off = settings_with(founder_vote_stake=0)
    t = prop.at
    while t <= end:
        await tick(t, seed, settings=off)
        t += timedelta(hours=1)
    (p,) = await proposals(pool)
    cast = await votes(pool, p["proposal_id"])
    assert sorted(BY_DID[v["voter_did"]] for v in cast) == sorted(voters)
    assert all(float(v["vote_power"]) == 0.0 for v in cast)
    for name in FOUNDER_NAMES:
        assert await stakes(pool, DEV[name]) == []
        assert await balance(pool, DEV[name]) == (ON.founder_vote_stake - 1 if name == poor else START)

    # Setting on, but one voter cannot afford the stake: it still votes.
    await pool.execute("DELETE FROM governance_votes WHERE proposal_id = $1", p["proposal_id"])
    t = prop.at
    seen = {}
    while t <= end:
        s = await tick(t, seed)
        seen.update(s["gov_skipped"])
        t += timedelta(hours=1)
    cast = await votes(pool, p["proposal_id"])
    assert sorted(BY_DID[v["voter_did"]] for v in cast) == sorted(voters)
    assert seen.get(poor) == "stake_unfunded"
    assert await stakes(pool, DEV[poor]) == []
    assert await balance(pool, DEV[poor]) == ON.founder_vote_stake - 1
    for name in rest:
        assert len(await stakes(pool, DEV[name])) == 1
    by_name = {BY_DID[v["voter_did"]]: float(v["vote_power"]) for v in cast}
    assert by_name[poor] == 0.0
