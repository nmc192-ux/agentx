"""
Integration tests: trust events cannot be farmed (Sprint 9, S9-9b), against
REAL local Postgres. Trust is half of every governance vote's weight
(stake × trust), so each test is a way of raising a trust score without doing
anything anyone valued — and proves the score does not move.

What is proven (HTTP → router → service → Postgres, nothing in the trust path
mocked):
  • one finished task is one trust event, however many code paths report it
    (route, service, both bus consumers) and however concurrently
  • a task counts only if a reward was really paid out of escrow, by another
    account, at least a day old; direct tasks and 0-reward tasks earn nothing
  • two accounts give each other one counted task a day, in either direction;
    no agent gains more than MAX_DAILY_GAIN a day, whoever the others are
  • a message earns nothing unless it answers one; each message is answered
    for credit once; a pair earns one reply a day
  • a verification vote earns nothing when cast; when the verification is
    final, only the winning side earns, once per contract
  • a failure costs trust only when the executor reports it themselves
  • a bus message cannot name who earns: the task row decides
  • events recorded before these rules (no dedupe key) are never applied
  • the database itself refuses a second event with the same key

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from .support import START_BALANCE, Agent
from .test_contract_escrow_db import open_verification, submitted_contract
from .test_task_escrow_db import (  # noqa: F401  (fixtures: treasury, no_task_rate_limit)
    assigned_task,
    no_task_rate_limit,
    treasury,
)

pytestmark = pytest.mark.integration   # skipped unless --db is given

OLD = 30   # days: an account old enough to count as a counterparty


@pytest_asyncio.fixture(autouse=True)
async def quiet_side_channels(monkeypatch):
    """Redis is not under test (the trust path does not use it)."""
    import src.main  # noqa: F401  (registers the 'did' path convertor the router needs)
    from src.routers import messages

    async def _none(*_a, **_k):
        return None

    from src.services import message_service
    monkeypatch.setattr(message_service, "_legacy_id_columns", None)
    for name in ("cache_get", "cache_set", "cache_delete"):
        monkeypatch.setattr(messages, name, _none)


# ── DB probes ─────────────────────────────────────────────────────────────────

async def events(pool, agent: Agent, event_type: str | None = None) -> int:
    return await pool.fetchval(
        "SELECT COUNT(*) FROM trust_events WHERE agent_id = $1 "
        "AND ($2::text IS NULL OR event_type = $2)",
        agent.agent_id, event_type,
    )


async def gained(pool, agent: Agent) -> float:
    return float(await pool.fetchval(
        "SELECT COALESCE(SUM(event_weight), 0) FROM trust_events WHERE agent_id = $1",
        agent.agent_id,
    ))


async def score(pool, agent: Agent) -> float:
    return float(await pool.fetchval(
        "SELECT trust_score FROM agents WHERE agent_id = $1", agent.agent_id,
    ))


async def a_day_later(pool, *agents: Agent) -> None:
    """Move these agents' trust events 25 hours into the past."""
    await pool.execute(
        "UPDATE trust_events SET created_at = created_at - INTERVAL '25 hours' "
        "WHERE agent_id = ANY($1::uuid[])",
        [a.agent_id for a in agents],
    )


# ── Flow helpers ──────────────────────────────────────────────────────────────

async def paid_task(client, creator: Agent, executor: Agent, reward: int = 100) -> str:
    """A marketplace task with a funded reward, taken and finished by
    *executor* and approved (so paid, S12-2) by *creator*."""
    task_id = await assigned_task(client, creator, executor, reward)
    resp = await client.post(
        f"/tasks/{task_id}/result", json={"result_payload": {"done": True}},
        headers=executor.headers,
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(f"/tasks/{task_id}/approve", headers=creator.headers)
    assert resp.status_code == 200, resp.text
    return task_id


async def direct_task(client, requester: Agent, executor: Agent, status: str = "COMPLETED",
                      marked_by: Agent | None = None) -> str:
    created = await client.post(
        "/tasks/create",
        json={"executor_agent_did": executor.did, "task_type": "direct.test"},
        headers=requester.headers,
    )
    assert created.status_code in (200, 201), created.text
    task_id = created.json()["task_id"]
    done = await client.post(
        f"/tasks/{task_id}/update", json={"status": status},
        headers=(marked_by or executor).headers,
    )
    assert done.status_code == 200, done.text
    return task_id


async def send(client, sender: Agent, receiver: Agent, text: str = "hello") -> str:
    resp = await client.post(
        "/messages/send",
        json={"sender_agent_did": sender.did, "receiver_agent_did": receiver.did,
              "message": text},
        headers=sender.headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["message_id"]


async def vote(client, verification_id: str, verifier: Agent, choice: str):
    return await client.post(
        f"/verifications/{verification_id}/vote", json={"vote": choice},
        headers=verifier.headers,
    )


# ── Tasks ─────────────────────────────────────────────────────────────────────

async def test_two_accounts_handing_each_other_direct_tasks_earn_nothing(client, pool, agents):
    """The cycle-9 route: +0.07 per direct task, no work, no reward, no limit."""
    a, b = await agents("a", age_days=OLD), await agents("b", age_days=OLD)

    for _ in range(5):
        await direct_task(client, a, b)
        await direct_task(client, b, a)

    assert (await events(pool, a), await events(pool, b)) == (0, 0)


async def test_a_task_with_no_reward_earns_nothing(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    executor = await agents("executor", 0)

    await paid_task(client, creator, executor, reward=0)

    assert await events(pool, executor) == 0


async def test_a_paid_task_is_one_event_whichever_paths_report_it(client, pool, agents):
    """Route + service + both bus consumers used to add up to four events."""
    from src.events.handlers import reputation_handler
    from src.events.types import AgentXEvent, EventType
    from src.services import reputation
    from src.services.consumers import reputation_consumer

    creator = await agents("creator", START_BALANCE, age_days=OLD)
    executor = await agents("executor", 0)
    task_id = await paid_task(client, creator, executor)
    assert await events(pool, executor) == 1

    bus_event = AgentXEvent(
        event_type=EventType.TASK_COMPLETED, payload={"task_id": task_id},
        source_agent_did=executor.did,
    )
    for _ in range(3):
        await reputation_handler.handle(bus_event)
        await reputation_consumer.handle(bus_event)
    assert await reputation.record_task_completed(task_id) == reputation.DUPLICATE
    results = await asyncio.gather(
        *[reputation.record_task_completed(task_id, source="race") for _ in range(8)]
    )

    assert set(results) == {reputation.DUPLICATE}
    assert await events(pool, executor) == 1
    assert await gained(pool, executor) == pytest.approx(0.05)
    row = await pool.fetchrow(
        "SELECT event_type, dedupe_key, counterparty_did FROM trust_events WHERE agent_id = $1",
        executor.agent_id,
    )
    assert dict(row) == {
        "event_type": "task_completed",
        "dedupe_key": f"task_completed:{task_id}",
        "counterparty_did": creator.did,
    }


async def test_a_bus_message_cannot_name_who_earns(client, pool, agents):
    """The bus payload is not trusted: an event naming an outsider as the
    agent, or a task that is not finished, records nothing for anyone."""
    from src.events.handlers import reputation_handler
    from src.events.types import AgentXEvent, EventType
    from src.services.consumers import reputation_consumer

    creator = await agents("creator", START_BALANCE, age_days=OLD)
    executor = await agents("executor", 0)
    outsider = await agents("outsider", age_days=OLD)
    unfinished = await assigned_task(client, creator, executor)

    for task_id in (unfinished, str(uuid4()), "not-a-uuid"):
        forged = AgentXEvent(
            event_type=EventType.TASK_COMPLETED,
            payload={"task_id": task_id, "agent_did": outsider.did},
            source_agent_did=outsider.did,
        )
        await reputation_handler.handle(forged)
        await reputation_consumer.handle(forged)

    assert (await events(pool, outsider), await events(pool, executor)) == (0, 0)


async def test_a_reward_from_a_just_created_account_does_not_count(client, pool, agents):
    """Sign up a second account, fund it, hire yourself: nothing."""
    puppet = await agents("puppet", START_BALANCE)            # created just now
    executor = await agents("executor", 0, age_days=OLD)

    await paid_task(client, puppet, executor)

    assert await events(pool, executor) == 0


async def test_a_pair_counts_once_a_day_in_either_direction(client, pool, agents):
    a = await agents("a", START_BALANCE, age_days=OLD)
    b = await agents("b", START_BALANCE, age_days=OLD)

    for _ in range(3):
        await paid_task(client, a, b)       # b works for a
    await paid_task(client, b, a)           # a works for b: the same pair
    assert (await events(pool, b), await events(pool, a)) == (1, 0)

    await a_day_later(pool, a, b)
    await paid_task(client, b, a)
    assert (await events(pool, b), await events(pool, a)) == (1, 1)


async def test_no_agent_gains_more_than_the_daily_cap(client, pool, agents):
    """A ring of old, funded accounts all hiring one agent."""
    from src.services.reputation import MAX_DAILY_GAIN

    executor = await agents("executor", 0, age_days=OLD)
    ring = [await agents(f"ring{i}", START_BALANCE, age_days=OLD) for i in range(5)]

    for creator in ring:
        await paid_task(client, creator, executor)

    assert await gained(pool, executor) == pytest.approx(MAX_DAILY_GAIN)
    assert await events(pool, executor) == 2

    await a_day_later(pool, executor)
    await paid_task(client, await agents("late", START_BALANCE, age_days=OLD), executor)
    assert await events(pool, executor) == 3


async def test_the_caps_hold_when_everything_arrives_at_once(client, pool, agents):
    """Same pair, different tasks, recorded concurrently: still one. And many
    counterparties at once still stop at the daily cap."""
    from src.services import reputation

    executor = await agents("executor", 0, age_days=OLD)
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    same_pair = await asyncio.gather(*[
        reputation.record_event(
            executor.did, "task_completed", dedupe_key=f"test:{uuid4()}",
            counterparty_did=creator.did,
        )
        for _ in range(10)
    ])
    assert sorted(same_pair) == [reputation.PAIR_CAP] * 9 + [reputation.RECORDED]

    others = [await agents(f"other{i}", age_days=OLD) for i in range(10)]
    many = await asyncio.gather(*[
        reputation.record_event(
            executor.did, "task_completed", dedupe_key=f"test:{uuid4()}",
            counterparty_did=other.did,
        )
        for other in others
    ])
    assert many.count(reputation.RECORDED) == 1          # 0.05 already + 0.05 = the cap
    assert many.count(reputation.DAILY_CAP) == 9
    assert await gained(pool, executor) == pytest.approx(reputation.MAX_DAILY_GAIN)


# ── Failures ──────────────────────────────────────────────────────────────────

async def test_a_failure_costs_trust_only_when_the_executor_reports_it(client, pool, agents):
    requester = await agents("requester", age_days=OLD)
    honest = await agents("honest")
    victim = await agents("victim")
    founder = await agents("founder", role="FOUNDER")

    task_id = await direct_task(client, requester, honest, status="FAILED")
    await direct_task(client, requester, victim, status="FAILED", marked_by=founder)

    assert await gained(pool, honest) == pytest.approx(-0.10)
    assert await events(pool, victim) == 0

    # Reported again by any path: still one.
    from src.services import reputation
    assert await reputation.record_task_failed(
        task_id, reported_by_did=honest.did) == reputation.DUPLICATE
    assert await events(pool, honest) == 1


# ── Messages ──────────────────────────────────────────────────────────────────

async def test_sending_messages_earns_nothing(client, pool, agents):
    """It was +0.01 for every message sent: 50 messages took 0.50 to 1.00."""
    spammer = await agents("spammer", age_days=OLD)
    targets = [await agents(f"target{i}", age_days=OLD) for i in range(5)]

    for n in range(50):
        await send(client, spammer, targets[n % 5], f"message {n}")

    assert await events(pool, spammer) == 0


async def test_an_answer_earns_once_and_a_pair_earns_once_a_day(client, pool, agents):
    alice, bob = await agents("alice", age_days=OLD), await agents("bob", age_days=OLD)

    await send(client, alice, bob, "question")
    assert await events(pool, alice) == 0                    # nobody asked alice anything
    await send(client, bob, alice, "answer")
    assert await gained(pool, bob) == pytest.approx(0.01)
    await send(client, bob, alice, "and another thing")      # the question is answered already
    assert await events(pool, bob) == 1

    for n in range(10):                                      # ping-pong
        await send(client, alice, bob, f"ping {n}")
        await send(client, bob, alice, f"pong {n}")

    assert (await events(pool, alice), await events(pool, bob)) == (0, 1)


async def test_one_question_cannot_be_answered_for_credit_day_after_day(client, pool, agents):
    carol, dave = await agents("carol", age_days=OLD), await agents("dave", age_days=OLD)
    await send(client, carol, dave, "one question")
    await send(client, dave, carol, "answer")
    assert await events(pool, dave) == 1

    for _ in range(3):                       # the pair's daily allowance is free again…
        await a_day_later(pool, carol, dave)
        await send(client, dave, carol, "answering it again")

    assert await events(pool, dave) == 1     # …but the question was answered already


async def test_answering_a_just_created_account_earns_nothing(client, pool, agents):
    puppet = await agents("puppet")                          # created just now
    farmer = await agents("farmer", age_days=OLD)

    await send(client, puppet, farmer, "say something")
    await send(client, farmer, puppet, "something")

    assert await events(pool, farmer) == 0


# ── Verification votes ────────────────────────────────────────────────────────

async def test_votes_earn_only_on_the_winning_side_once_final(client, pool, agents):
    """It was +0.03 for every vote the moment it was cast, whichever way."""
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    contractor = await agents("contractor", 0)
    yes1, yes2, no1 = [await agents(n, 0) for n in ("yes1", "yes2", "no1")]
    contract_id = await submitted_contract(client, creator, contractor)
    verification_id = await open_verification(client, pool, creator, contract_id)

    assert (await vote(client, verification_id, yes1, "approve")).status_code == 201
    assert (await vote(client, verification_id, no1, "reject")).status_code == 201
    assert [await events(pool, v) for v in (yes1, no1)] == [0, 0]     # not final yet

    assert (await vote(client, verification_id, yes2, "approve")).status_code == 201
    status = await pool.fetchval(
        "SELECT status FROM verifications WHERE verification_id = $1", UUID(verification_id))
    assert status == "verified"

    assert [await gained(pool, v) for v in (yes1, yes2)] == [pytest.approx(0.03)] * 2
    assert await events(pool, no1) == 0
    assert (await events(pool, creator), await events(pool, contractor)) == (0, 0)


async def test_a_second_verification_of_the_same_contract_pays_nobody_twice(client, pool, agents):
    from src.services import reputation

    creator = await agents("creator", START_BALANCE, age_days=OLD)
    contractor = await agents("contractor", 0)
    verifiers = [await agents(f"verifier{i}", 0) for i in range(3)]
    contract_id = await submitted_contract(client, creator, contractor)

    for _ in range(3):
        verification_id = await open_verification(client, pool, creator, contract_id)
        for v in verifiers:
            assert (await vote(client, verification_id, v, "approve")).status_code == 201
        # …and the bus consumer reporting the same outcome again.
        again = await reputation.record_verification_outcome(verification_id)
        assert set(again.values()) == {reputation.DUPLICATE}

    assert [await events(pool, v) for v in verifiers] == [1, 1, 1]


async def test_votes_for_a_just_created_requester_earn_nothing(client, pool, agents):
    """Three fresh accounts approving a fresh account's contract: nothing."""
    creator = await agents("creator", START_BALANCE)          # created just now
    contractor = await agents("contractor", 0)
    verifiers = [await agents(f"verifier{i}", 0) for i in range(3)]
    contract_id = await submitted_contract(client, creator, contractor)
    verification_id = await open_verification(client, pool, creator, contract_id)

    for v in verifiers:
        assert (await vote(client, verification_id, v, "approve")).status_code == 201

    assert [await events(pool, v) for v in verifiers] == [0, 0, 0]


# ── The rules themselves ──────────────────────────────────────────────────────

async def test_a_positive_event_needs_another_established_agent(pool, agents):
    from src.services import reputation

    agent = await agents("agent", age_days=OLD)
    fresh = await agents("fresh")
    suspended = await agents("suspended", age_days=OLD)
    await pool.execute(
        "UPDATE agents SET status = 'SUSPENDED' WHERE agent_id = $1", suspended.agent_id)

    async def record(counterparty):
        return await reputation.record_event(
            agent.did, "task_completed", dedupe_key=f"test:{uuid4()}",
            counterparty_did=counterparty,
        )

    assert await record(None) == reputation.NO_COUNTERPARTY
    assert await record(agent.did) == reputation.NO_COUNTERPARTY
    assert await record(fresh.did) == reputation.COUNTERPARTY_NOT_ESTABLISHED
    assert await record(suspended.did) == reputation.COUNTERPARTY_NOT_ESTABLISHED
    assert await record("did:agentx:nobody-000") == reputation.COUNTERPARTY_NOT_ESTABLISHED
    assert await events(pool, agent) == 0
    with pytest.raises(ValueError):
        await reputation.record_event(agent.did, "task_completed", dedupe_key="")


async def test_the_database_refuses_a_second_event_with_the_same_key(pool, agents):
    agent = await agents("agent")
    insert = (
        "INSERT INTO trust_events (agent_id, agent_did, event_type, event_weight, "
        "event_value, dedupe_key) VALUES ($1, $2, 'task_completed', 0.05, 0.05, $3)"
    )
    key = f"test:{uuid4()}"
    await pool.execute(insert, agent.agent_id, agent.did, key)

    with pytest.raises(asyncpg.UniqueViolationError):
        await pool.execute(insert, agent.agent_id, agent.did, key)


async def test_events_recorded_before_these_rules_are_never_applied(pool, agents):
    """Production holds one event per message ever sent and several per task.
    They carry no dedupe key; the replay leaves them where they are."""
    from src.services.reputation import recalculate_agent_trust

    farmer = await agents("farmer")
    for _ in range(40):
        await pool.execute(
            "INSERT INTO trust_events (agent_id, agent_did, event_type, event_weight, "
            "event_value) VALUES ($1, $2, 'message_replied', 0.01, 0.01)",
            farmer.agent_id, farmer.did,
        )

    await recalculate_agent_trust()

    assert await score(pool, farmer) == pytest.approx(0.5)
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM agent_reputation_history WHERE agent_id = $1",
        farmer.agent_id) == 0
    assert await events(pool, farmer) == 40      # kept, not deleted


async def test_end_to_end_farming_moves_no_score_and_real_work_does(client, pool, agents):
    """Everything above at once, then the scheduled job: the farmers stay at
    0.50, the agent who was paid for a task by an established account moves."""
    from src.jobs.scheduled_maintenance import run_maintenance

    farmer_a = await agents("farmer-a", START_BALANCE)
    farmer_b = await agents("farmer-b", START_BALANCE)
    for _ in range(3):
        await direct_task(client, farmer_a, farmer_b)
        await direct_task(client, farmer_b, farmer_a)
        await paid_task(client, farmer_a, farmer_b, reward=1)
        await paid_task(client, farmer_b, farmer_a, reward=1)
    for n in range(20):
        await send(client, farmer_a, farmer_b, f"ping {n}")
        await send(client, farmer_b, farmer_a, f"pong {n}")

    client_agent = await agents("client", START_BALANCE, age_days=OLD)
    worker = await agents("worker", 0)
    await paid_task(client, client_agent, worker)

    summary = await run_maintenance()

    assert summary["errors"] == []
    assert [await score(pool, a) for a in (farmer_a, farmer_b)] == [pytest.approx(0.5)] * 2
    assert await score(pool, worker) == pytest.approx(0.55)
