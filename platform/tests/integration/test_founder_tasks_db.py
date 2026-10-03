"""
Integration tests: paid task handoffs between founders in the heartbeat tick
(src/jobs/founder_heartbeat.py + src/founders/tasks.py) against REAL local
Postgres. Sprint 10, S10-6. No money path is mocked: the tick calls
task_service.create_task / submit_bid / submit_result, which escrow, charge
the fee and release through token_service and economy_service.

What is proven:
  • one handoff: the task is posted at its planned moment, not before, funded
    from the creator's own wallet (ledger: one escrow entry, one fee entry if
    a fee applies) and assigned to the intended peer in the same tick; the
    peer submits after its delay, not before; the escrow is released to the
    peer once; wallets + escrow + treasury add up throughout; the peer gets
    exactly one `task_completed` trust event with the creator as
    counterparty; a later tick changes nothing
  • a wallet that cannot cover the reward, or no wallet at all, means no task
    and no ledger entry
  • the daily spend cap holds: below the reward nothing is posted; with room
    for one task the second plan of the day is refused and one escrow exists
  • an outside agent's task is never bid on and never finished, whatever its
    payload claims; a peer the guard refuses gets no task; a task another
    agent took first is left alone
  • the route's task limit and quiet hours hold
  • three simulated days of ticks keep every rule and conserve tokens

The eight seeded `-001` founders are used (made 30 days old, so the trust
rules count them as established) with wallets the test funds and restores;
every test cleans up tasks, ledger entries, trust events, messages and
events it made. Run:
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import json
import random
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from src.config import Settings
from src.founders import messages as fm
from src.founders import tasks as ft
from src.founders.generation import GeneratedPost
from src.founders.personas import FOUNDER_NAMES, PERSONAS
from src.founders.roster import founder_roster
from src.jobs import founder_heartbeat as fh
from src.services import task_service

from .support import total_tokens

pytestmark = pytest.mark.integration   # skipped unless --db is given

DAY_START = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
DEV = founder_roster("", "development")
FOUNDER_DIDS = tuple(DEV[n] for n in FOUNDER_NAMES)
OUTSIDER = "did:agentx:outsider-606"
START = 500
ON = Settings(_env_file=None, founder_heartbeat_enabled="true", founder_llm_provider="")


def settings_with(**kw) -> Settings:
    return Settings(_env_file=None, founder_heartbeat_enabled="true", founder_llm_provider="", **kw)


class SilentGenerator:
    """No top-level posts (so no replies either): only tasks are written."""
    async def generate(self, persona, context, rng, now=None) -> GeneratedPost:
        raise RuntimeError("no posts in this test")


@pytest_asyncio.fixture(autouse=True)
async def treasury(pool):
    """The app creates the treasury (and the fee policy) at startup; the
    tests do not run the startup hooks (idempotent)."""
    from src.services import economy_service
    await economy_service.initialize_treasury()


@pytest.fixture(autouse=True)
def no_dms(monkeypatch):
    """Direct messages are S10-5's; keep them out of the trust ledger here."""
    monkeypatch.setattr(fh, "due_openings", lambda *_a, **_k: [])
    monkeypatch.setattr(fh, "plan_answer", lambda *_a, **_k: fm.AnswerPlan(False, 0.0))


@pytest_asyncio.fixture
async def clean(pool):
    everyone = list(FOUNDER_DIDS) + [OUTSIDER]
    created = {r["agent_did"]: r["created_at"] for r in await pool.fetch(
        "SELECT agent_did, created_at FROM agents WHERE agent_did = ANY($1::text[])",
        list(FOUNDER_DIDS),
    )}
    wallets_before = {r["agent_did"]: r["balance"] for r in await pool.fetch(
        "SELECT a.agent_did, w.balance FROM wallets w JOIN agents a ON a.agent_id = w.agent_id "
        "WHERE a.agent_did = ANY($1::text[])", list(FOUNDER_DIDS),
    )}

    async def wipe():
        await pool.execute(
            "DELETE FROM transactions WHERE related_id IN "
            "(SELECT task_id FROM tasks WHERE requester_agent_did = ANY($1::text[]))", everyone,
        )
        await pool.execute(
            "DELETE FROM transactions WHERE from_wallet IN (SELECT wallet_id FROM wallets w "
            "JOIN agents a ON a.agent_id = w.agent_id WHERE a.agent_did = ANY($1::text[])) "
            "OR to_wallet IN (SELECT wallet_id FROM wallets w JOIN agents a "
            "ON a.agent_id = w.agent_id WHERE a.agent_did = ANY($1::text[]))", everyone,
        )
        await pool.execute(
            "DELETE FROM tasks WHERE requester_agent_did = ANY($1::text[])", everyone,
        )
        await pool.execute(
            "DELETE FROM trust_events WHERE agent_did = ANY($1::text[])", everyone,
        )
        await pool.execute(
            "DELETE FROM messages WHERE sender_agent_did = ANY($1::text[]) "
            "OR receiver_agent_did = ANY($1::text[])", everyone,
        )
        await pool.execute("DELETE FROM posts WHERE author_did = ANY($1::text[])", everyone)
        await pool.execute("DELETE FROM events WHERE agent_did = ANY($1::text[])", everyone)
        await pool.execute(
            "UPDATE agents SET posts_count = 0, last_seen_at = NULL WHERE agent_did = ANY($1::text[])",
            list(FOUNDER_DIDS),
        )
        await pool.execute(
            "DELETE FROM wallets WHERE agent_id IN "
            "(SELECT agent_id FROM agents WHERE agent_did = ANY($1::text[]))", everyone,
        )
        await pool.execute("DELETE FROM agents WHERE agent_did = $1", OUTSIDER)

    await wipe()
    await pool.execute(
        "UPDATE agents SET created_at = CURRENT_TIMESTAMP - INTERVAL '30 days' "
        "WHERE agent_did = ANY($1::text[])", list(FOUNDER_DIDS),
    )
    await pool.execute(
        "INSERT INTO agents (agent_did, display_name, created_at) "
        "VALUES ($1, 'Outsider', CURRENT_TIMESTAMP - INTERVAL '30 days')", OUTSIDER,
    )
    yield
    await wipe()
    for did, at in created.items():
        await pool.execute("UPDATE agents SET created_at = $2 WHERE agent_did = $1", did, at)
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
        now=now, generator=SilentGenerator(), rng=random.Random(5), task_seed=seed, **kw,
    )
    assert summary["task_errors"] == {}, summary
    return summary


async def tasks(pool) -> list[dict]:
    rows = await pool.fetch(
        "SELECT task_id, requester_agent_did, executor_agent_did, task_type, reward, status, "
        "escrowed_reward, task_fee, payload FROM tasks "
        "WHERE requester_agent_did = ANY($1::text[]) ORDER BY created_at, task_id",
        list(FOUNDER_DIDS) + [OUTSIDER],
    )
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d["payload"], str):
            d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


async def ledger(pool, task_id, tx_type: str) -> list[int]:
    return [r["amount"] for r in await pool.fetch(
        "SELECT amount FROM transactions WHERE related_id = $1 AND type = $2 ORDER BY timestamp",
        task_id, tx_type,
    )]


async def completed_events(pool) -> list[dict]:
    return [dict(r) for r in await pool.fetch(
        "SELECT agent_did, counterparty_did, dedupe_key FROM trust_events "
        "WHERE event_type = 'task_completed' AND agent_did = ANY($1::text[])",
        list(FOUNDER_DIDS) + [OUTSIDER],
    )]


def _nobody_plans(seed: str, days, *, but: str | None = None, on=None) -> bool:
    """No founder (except *but* on *on*) plans a handoff on any of *days*."""
    return not any(
        ft.plan_task(PERSONAS[n], d, seed).wants
        for n in FOUNDER_NAMES for d in days
        if not (n == but and d == on)
    )


def find_seed(creator: str, *, day=DAY_START) -> str:
    """A task seed under which *creator* plans a handoff on *day*, the peer is
    awake at the plan's moment and for the whole result window after it, and
    nobody else plans one on that day, the day before or the day after (so a
    test's ticks see this one handoff and nothing else)."""
    days = [day.date() + timedelta(days=k) for k in (-1, 0, 1)]
    for i in range(50_000):
        seed = f"t{i}"
        plan = ft.plan_task(PERSONAS[creator], day.date(), seed)
        if not plan.wants:
            continue
        peer = PERSONAS[plan.peer]
        high = ft.TASK_RESULT_DELAY_MINUTES[1]
        if any(peer.is_quiet(plan.at + timedelta(minutes=m)) for m in range(0, int(high) + 10, 30)):
            continue
        if _nobody_plans(seed, days, but=creator, on=day.date()):
            return seed
    raise AssertionError("no seed found")


def quiet_seed(day=DAY_START) -> str:
    """A task seed under which nobody plans anything around *day*."""
    days = [day.date() + timedelta(days=k) for k in (-1, 0, 1)]
    return next(s for s in (f"q{i}" for i in range(50_000)) if _nobody_plans(s, days))


# ── One handoff ───────────────────────────────────────────────────────────────

async def test_one_handoff_is_funded_taken_paid_and_counted_once(pool, clean):
    seed = find_seed("marcus")
    plan = ft.plan_task(PERSONAS["marcus"], DAY_START.date(), seed)
    marcus, peer = DEV["marcus"], DEV[plan.peer]
    await fund(pool, *FOUNDER_DIDS)
    supply = await total_tokens(pool)

    early = await tick(plan.at - timedelta(minutes=1), seed)
    assert early["task_posted"] == {} and await tasks(pool) == []

    posted = await tick(plan.at + timedelta(minutes=1), seed)
    (task,) = await tasks(pool)
    tid = task["task_id"]
    assert posted["task_posted"] == {"marcus": str(tid)}
    assert posted["task_taken"] == {plan.peer: str(tid)}
    assert posted["task_not_taken"] == {} and posted["task_skipped"] == {}
    assert task["requester_agent_did"] == marcus and task["executor_agent_did"] == peer
    assert task["status"] == "assigned" and task["task_type"] == plan.task_type
    assert task["reward"] == plan.reward
    assert task["payload"]["heartbeat"] == {
        "kind": ft.KIND_HANDOFF, "day": "2026-10-05", "for": peer,
        "at": (plan.at + timedelta(minutes=1)).isoformat(), "capability": plan.task_type,
    }
    fee = task["task_fee"]
    assert task["escrowed_reward"] == plan.reward - fee
    assert await ledger(pool, tid, "escrow") == [plan.reward]
    assert await ledger(pool, tid, "fee") == ([fee] if fee else [])
    assert await ledger(pool, tid, "escrow_release") == []
    assert await balance(pool, marcus) == START - plan.reward
    assert await balance(pool, peer) == START
    assert await total_tokens(pool) == supply
    assert await completed_events(pool) == []

    delay = ft.plan_result_delay(PERSONAS[plan.peer], tid, seed)
    done_at = plan.at + timedelta(minutes=1) + timedelta(minutes=delay)
    before = await tick(done_at - timedelta(minutes=1), seed)
    assert before["task_submitted"] == {} and before["task_posted"] == {}
    assert (await tasks(pool))[0]["status"] == "assigned"

    done = await tick(done_at, seed)
    assert done["task_submitted"] == {plan.peer: str(tid)}
    # S12-2: a submitted result pays nothing; the creator founder approves it
    # on its next turn (this tick if it comes later in the roster and is awake).
    approved, approved_at = done, done_at
    if not done["task_approved"]:
        (task,) = await tasks(pool)
        assert task["status"] == "in_review" and task["escrowed_reward"] == plan.reward - fee
        assert await ledger(pool, tid, "escrow_release") == []
        assert await balance(pool, peer) == START
        assert await completed_events(pool) == []
        for _ in range(48):
            approved_at += timedelta(minutes=30)
            approved = await tick(approved_at, seed)
            if approved["task_approved"]:
                break
    assert approved["task_approved"] == {"marcus": str(tid)}
    assert approved["task_paid"] == {plan.peer: plan.reward - fee}
    assert approved["task_trust"] == {plan.peer: "recorded"}
    (task,) = await tasks(pool)
    assert task["status"] == "COMPLETED" and task["escrowed_reward"] == 0
    assert await ledger(pool, tid, "escrow_release") == [plan.reward - fee]
    assert await balance(pool, marcus) == START - plan.reward
    assert await balance(pool, peer) == START + plan.reward - fee
    assert await total_tokens(pool) == supply
    assert await completed_events(pool) == [{
        "agent_did": peer, "counterparty_did": marcus, "dedupe_key": f"task_completed:{tid}",
    }]
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM task_results WHERE task_id = $1", tid) == 1
    done_at = approved_at

    again = await tick(done_at + timedelta(hours=1), seed)
    assert again["task_submitted"] == {} and again["task_approved"] == {}
    assert await ledger(pool, tid, "escrow_release") == [plan.reward - fee]
    assert len(await completed_events(pool)) == 1
    assert await total_tokens(pool) == supply


# ── Funding ───────────────────────────────────────────────────────────────────

async def test_a_short_or_missing_wallet_means_no_task(pool, clean):
    seed = find_seed("thea")
    plan = ft.plan_task(PERSONAS["thea"], DAY_START.date(), seed)
    thea = DEV["thea"]
    at = plan.at + timedelta(minutes=1)

    none = await tick(at, seed)
    assert none["task_skipped"] == {"thea": "no_wallet"} and none["task_posted"] == {}

    await fund(pool, thea, balance=plan.reward - 1)
    short = await tick(at, seed)
    assert short["task_skipped"] == {"thea": "wallet_short"} and short["task_posted"] == {}
    assert await tasks(pool) == []
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM transactions tx JOIN wallets w ON w.wallet_id = tx.from_wallet "
        "JOIN agents a ON a.agent_id = w.agent_id WHERE a.agent_did = $1", thea) == 0
    assert await balance(pool, thea) == plan.reward - 1

    await fund(pool, thea, balance=plan.reward)
    exact = await tick(at, seed)
    assert exact["task_posted"].keys() == {"thea"}
    assert await balance(pool, thea) == 0


async def test_the_daily_spend_cap_holds(pool, clean, monkeypatch):
    seed = find_seed("bruno")
    plan = ft.plan_task(PERSONAS["bruno"], DAY_START.date(), seed)
    bruno = DEV["bruno"]
    await fund(pool, *FOUNDER_DIDS)
    at = plan.at + timedelta(minutes=1)

    below = settings_with(founder_task_daily_spend=plan.reward - 1)
    nothing = await tick(at, seed, settings=below)
    assert nothing["task_skipped"] == {"bruno": "spend_cap"} and await tasks(pool) == []

    off = settings_with(founder_task_daily_spend=0)
    assert (await tick(at, seed, settings=off))["task_posted"] == {}
    assert await tasks(pool) == []

    # Room for exactly one: a second plan "for tomorrow" that is also due now
    # (forced) is refused by the cap, and one escrow exists.
    second = replace(plan, at=plan.at + timedelta(days=1), reward=plan.reward)
    monkeypatch.setattr(
        fh, "due_task_plans", lambda persona, *_a, **_k: [plan, second] if persona.name == "bruno" else [],
    )
    room_for_one = settings_with(founder_task_daily_spend=plan.reward)
    first = await tick(at, seed, settings=room_for_one)
    assert first["task_posted"].keys() == {"bruno"}
    capped = await tick(at + timedelta(minutes=5), seed, settings=room_for_one)
    assert capped["task_posted"] == {} and capped["task_skipped"] == {"bruno": "spend_cap"}
    rows = await tasks(pool)
    assert len(rows) == 1 and rows[0]["payload"]["heartbeat"]["day"] == "2026-10-05"
    assert await balance(pool, bruno) == START - plan.reward

    # Once 24 hours have passed the cap is free again (the second plan is
    # outside its grace by then, so only the forced one matters).
    monkeypatch.setattr(
        fh, "due_task_plans", lambda persona, *_a, **_k: [second] if persona.name == "bruno" else [],
    )
    later = await tick(at + timedelta(hours=24, minutes=1), seed, settings=room_for_one)
    assert later["task_posted"].keys() == {"bruno"}
    assert len(await tasks(pool)) == 2


# ── Only founders, only their own tasks ───────────────────────────────────────

async def test_an_outsiders_task_is_never_bid_on_or_finished(pool, clean):
    seed = quiet_seed()
    quinn = DEV["quinn"]
    await fund(pool, *FOUNDER_DIDS, OUTSIDER)
    noon = DAY_START + timedelta(hours=12)

    # An outsider posts a funded task that claims to be a handoff for QUINN.
    payload = ft.handoff_payload(
        PERSONAS["atlas"], "QUINN", quinn,
        ft.TaskPlan(True, "quinn", noon, "testing", 10), noon - timedelta(hours=7),
    )
    open_task = await task_service.create_task(OUTSIDER, "testing", payload, 10)
    # ...and another the outsider managed to assign to QUINN directly.
    assigned = await task_service.create_task(OUTSIDER, "qa", payload, 10)
    await pool.execute(
        "UPDATE tasks SET status = 'assigned', executor_agent_did = $2, executor_agent_id = "
        "(SELECT agent_id FROM agents WHERE agent_did = $2) WHERE task_id = $1",
        assigned.task_id, quinn,
    )
    supply = await total_tokens(pool)

    for hours in (0, 3, 7, 12):
        summary = await tick(noon + timedelta(hours=hours), seed)
        assert summary["task_submitted"] == {} and summary["task_taken"] == {}
    rows = {r["task_id"]: r for r in await tasks(pool)}
    assert rows[open_task.task_id]["status"] == "open"
    assert rows[assigned.task_id]["status"] == "assigned"
    assert await pool.fetchval("SELECT COUNT(*) FROM task_bids WHERE task_id = $1", open_task.task_id) == 0
    assert await ledger(pool, assigned.task_id, "escrow_release") == []
    assert await completed_events(pool) == []
    assert await total_tokens(pool) == supply


async def test_a_peer_the_guard_refuses_gets_no_task(pool, clean):
    seed = find_seed("daria")
    plan = ft.plan_task(PERSONAS["daria"], DAY_START.date(), seed)
    await fund(pool, *FOUNDER_DIDS)
    roster = {n: d for n, d in DEV.items() if n != plan.peer}

    summary = await tick(plan.at + timedelta(minutes=1), seed, roster=roster)
    assert summary["task_skipped"] == {"daria": "peer_unavailable"}
    assert summary["task_posted"] == {} and await tasks(pool) == []
    assert await balance(pool, DEV["daria"]) == START


async def test_a_task_another_agent_took_first_is_left_alone(pool, clean, monkeypatch):
    seed = find_seed("nova")
    plan = ft.plan_task(PERSONAS["nova"], DAY_START.date(), seed)
    nova, peer = DEV["nova"], DEV[plan.peer]
    await fund(pool, *FOUNDER_DIDS, OUTSIDER)
    supply = await total_tokens(pool)

    real_bid = task_service.submit_bid

    async def sniped(task_id, agent_did, confidence, bid_price):
        # The outsider's bid lands first; then the peer's own bid is refused.
        await real_bid(task_id, OUTSIDER, 0.95, bid_price)
        return await real_bid(task_id, agent_did, confidence, bid_price)

    monkeypatch.setattr(fh, "submit_bid", sniped)
    posted = await tick(plan.at + timedelta(minutes=1), seed)
    (task,) = await tasks(pool)
    assert posted["task_posted"] == {"nova": str(task["task_id"])}
    assert posted["task_taken"] == {}
    assert posted["task_not_taken"] == {"nova": "bid_refused:ValueError"}
    assert task["executor_agent_did"] == OUTSIDER and task["status"] == "assigned"

    # The peer never "finishes" a task that is not its own.
    late = plan.at + timedelta(minutes=1) + timedelta(minutes=ft.TASK_RESULT_DELAY_MINUTES[1] + 5)
    summary = await tick(late, seed)
    assert summary["task_submitted"] == {}
    assert (await tasks(pool))[0]["status"] == "assigned"
    assert await ledger(pool, task["task_id"], "escrow_release") == []
    assert await balance(pool, nova) == START - plan.reward and await balance(pool, peer) == START
    assert await total_tokens(pool) == supply

    # S12-2: the outsider submits a result. No founder approves a result that
    # did not come from a founder; it is left to the automatic release.
    await task_service.submit_result(task["task_id"], OUTSIDER, {"output": "junk"})
    for hours in (1, 4, 9, 14, 20):
        summary = await tick(late + timedelta(hours=hours), seed)
        assert summary["task_approved"] == {} and summary["task_paid"] == {}
    assert (await tasks(pool))[0]["status"] == "in_review"
    assert await ledger(pool, task["task_id"], "escrow_release") == []
    assert await balance(pool, OUTSIDER) == START
    assert await completed_events(pool) == []
    assert await total_tokens(pool) == supply


# ── Limits ────────────────────────────────────────────────────────────────────

async def test_the_route_limit_and_quiet_hours_hold(pool, clean, monkeypatch):
    seed = find_seed("gia")
    plan = ft.plan_task(PERSONAS["gia"], DAY_START.date(), seed)
    gia = DEV["gia"]
    await fund(pool, *FOUNDER_DIDS)
    at = plan.at + timedelta(minutes=1)

    monkeypatch.setattr(fh, "TASK_LIMITS", ((1, timedelta(days=1), "1/day"),))
    agent_id = await pool.fetchval("SELECT agent_id FROM agents WHERE agent_did = $1", gia)
    await pool.execute(
        "INSERT INTO tasks (task_id, creator_agent_id, requester_agent_id, requester_agent_did, "
        "task_type, payload, reward, status, created_at) VALUES (gen_random_uuid(), $1, $1, $2, "
        "'qa', '{}'::jsonb, 0, 'open', $3)", agent_id, gia, at - timedelta(hours=2),
    )
    limited = await tick(at, seed)
    assert limited["task_skipped"] == {"gia": "1/day"} and limited["task_posted"] == {}
    assert await balance(pool, gia) == START

    monkeypatch.setattr(fh, "TASK_LIMITS", ())
    quiet_start = PERSONAS["gia"].quiet_hours[0]
    quiet_at = DAY_START.replace(hour=quiet_start, minute=30)
    monkeypatch.setattr(
        fh, "due_task_plans",
        lambda persona, *_a, **_k: [replace(plan, at=quiet_at)] if persona.name == "gia" else [],
    )
    quiet = await tick(quiet_at, seed)
    assert quiet["task_posted"] == {} and "gia" not in quiet["task_skipped"]


# ── Three days ────────────────────────────────────────────────────────────────

async def test_three_days_of_ticks_keep_every_rule(pool, clean):
    seed = "three-days-of-tasks"
    await fund(pool, *FOUNDER_DIDS)
    supply = await total_tokens(pool)
    cap = int(ON.founder_task_daily_spend)

    now = DAY_START
    end = DAY_START + timedelta(days=3)
    while now < end:
        await tick(now, seed)
        now += timedelta(minutes=30)

    rows = await tasks(pool)
    assert rows, "three days of ticks posted no handoff at all"
    by_creator_day: dict[tuple[str, str], int] = {}
    for r in rows:
        hb = r["payload"]["heartbeat"]
        assert hb["kind"] == ft.KIND_HANDOFF
        assert r["requester_agent_did"] in FOUNDER_DIDS
        assert r["executor_agent_did"] in FOUNDER_DIDS and r["executor_agent_did"] == hb["for"]
        assert r["executor_agent_did"] != r["requester_agent_did"]
        peer_name = next(n for n in FOUNDER_NAMES if DEV[n] == r["executor_agent_did"])
        assert r["task_type"] in PERSONAS[peer_name].capabilities
        assert ft.TASK_REWARD_RANGE[0] <= r["reward"] <= ft.TASK_REWARD_RANGE[1] <= cap
        assert r["status"] in ("assigned", "in_review", "COMPLETED")
        key = (r["requester_agent_did"], hb["day"])
        by_creator_day[key] = by_creator_day.get(key, 0) + 1
        posted_at = datetime.fromisoformat(hb["at"])
        creator_name = next(n for n in FOUNDER_NAMES if DEV[n] == r["requester_agent_did"])
        assert not PERSONAS[creator_name].is_quiet(posted_at)
        releases = await ledger(pool, r["task_id"], "escrow_release")
        if r["status"] == "COMPLETED":
            assert releases == [r["reward"] - r["task_fee"]] and r["escrowed_reward"] == 0
        else:
            assert releases == [] and r["escrowed_reward"] == r["reward"] - r["task_fee"]
    assert max(by_creator_day.values()) == 1
    # Spend inside any 24 hours never exceeds the cap, per creator.
    for did in FOUNDER_DIDS:
        mine = sorted(
            (datetime.fromisoformat(r["payload"]["heartbeat"]["at"]), r["reward"])
            for r in rows if r["requester_agent_did"] == did
        )
        for i, (at, _) in enumerate(mine):
            window = sum(rw for a, rw in mine[i:] if a < at + timedelta(hours=24))
            assert window <= cap
    completed = [r for r in rows if r["status"] == "COMPLETED"]
    assert completed, "no handoff was finished in three days"
    events = await completed_events(pool)
    assert len(events) == len(completed)
    assert {e["dedupe_key"] for e in events} == {f"task_completed:{r['task_id']}" for r in completed}
    for e in events:
        task = next(r for r in rows if f"task_completed:{r['task_id']}" == e["dedupe_key"])
        assert e["agent_did"] == task["executor_agent_did"]
        assert e["counterparty_did"] == task["requester_agent_did"]
    assert await total_tokens(pool) == supply
    spent = {did: 0 for did in FOUNDER_DIDS}
    earned = {did: 0 for did in FOUNDER_DIDS}
    for r in rows:
        spent[r["requester_agent_did"]] += r["reward"]
        if r["status"] == "COMPLETED":
            earned[r["executor_agent_did"]] += r["reward"] - r["task_fee"]
    for did in FOUNDER_DIDS:
        assert await balance(pool, did) == START - spent[did] + earned[did]
