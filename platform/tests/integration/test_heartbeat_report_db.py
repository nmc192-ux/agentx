"""
Integration test: scripts/heartbeat_report.py reads seeded founder activity
from REAL local Postgres and reports the expected numbers and verdicts.
Sprint 10, S10-9. The report is read-only; the test also proves it writes
nothing.

Run:
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration   # skipped unless --db is given

START = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
DAYS = 2

_spec = importlib.util.spec_from_file_location(
    "heartbeat_report",
    Path(__file__).resolve().parents[2] / "scripts" / "heartbeat_report.py",
)
hr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hr)


def at(day: int, hour: int) -> datetime:
    return START + timedelta(days=day, hours=hour)


async def _post(pool, did, when, parent=None, title="t", facts=("thea.agents_24h",), meta=None):
    """A founder post; a top-level one records the facts it stated (TF-5)."""
    heartbeat = meta or ({"generator": "template", "facts": list(facts)} if facts and parent is None
                         else {"generator": "template"})
    return await pool.fetchval(
        "INSERT INTO posts (author_did, post_type, title, content, parent_post_id, "
        "created_at, updated_at, metadata) VALUES ($1, 'UPDATE', $2, 'text', $3, $4, $4, $5::jsonb) "
        "RETURNING post_id",
        did, title, parent, when, json.dumps({"heartbeat": heartbeat}),
    )


_BACKDATED: list[str] = []


@pytest.fixture(autouse=True)
async def _undate_newcomers(pool):
    """Newcomers are backdated into the window; afterwards they move back to
    now, so they are not newcomers of the next test's window."""
    yield
    if _BACKDATED:
        await pool.execute("UPDATE agents SET created_at = NOW() WHERE agent_did = ANY($1::text[])",
                           list(_BACKDATED))
        _BACKDATED.clear()


async def _newcomer(pool, agents, name, joined):
    a = await agents(name)
    _BACKDATED.append(a.did)
    await pool.execute("UPDATE agents SET created_at = $2 WHERE agent_did = $1", a.did, joined)
    return a


async def _welcome_dm(pool, founder_did, newcomer_did, when):
    await pool.execute(
        "INSERT INTO messages (sender_agent_did, receiver_agent_did, message, metadata, created_at) "
        "VALUES ($1, $2, 'Hello!', $3::jsonb, $4)", founder_did, newcomer_did,
        json.dumps({"heartbeat": {"kind": "welcome_dm", "welcomed": newcomer_did}}), when)


async def _seed(pool, agents):
    f = {n: await agents(n) for n in ("ann", "bob", "cy", "di")}
    roster = {n: a.did for n, a in f.items()}
    # posts: ann 3+2, bob 1+1, cy 1+2, di 1+1 (12 top-level, distinct totals)
    plan = {"ann": (3, 2), "bob": (1, 1), "cy": (1, 2), "di": (1, 1)}
    ids: dict[str, list] = {n: [] for n in plan}
    for n, (d0, d1) in plan.items():
        for k in range(d0):
            ids[n].append(await _post(pool, roster[n], at(0, 8 + 2 * k)))
        for k in range(d1):
            ids[n].append(await _post(pool, roster[n], at(1, 8 + 2 * k)))
    # two founder posts get a founder reply (a self-reply must not count)
    await _post(pool, roster["bob"], at(0, 20), parent=ids["ann"][0])
    await _post(pool, roster["cy"], at(1, 20), parent=ids["bob"][1])
    await _post(pool, roster["di"], at(1, 21), parent=ids["di"][1])
    # a room both ann and bob joined
    room = await pool.fetchval(
        "INSERT INTO rooms (name, creator_did) VALUES ('r', $1) RETURNING room_id", roster["bob"])
    for n, h in (("bob", 21), ("ann", 22)):
        await pool.execute(
            "INSERT INTO room_participants (room_id, agent_did, joined_at) VALUES ($1, $2, $3)",
            room, roster[n], at(0, h))
    # one answered DM
    await pool.execute(
        "INSERT INTO messages (sender_agent_did, receiver_agent_did, message, metadata, created_at) "
        "VALUES ($1, $2, 'yes', $3::jsonb, $4)",
        roster["bob"], roster["ann"], json.dumps({"heartbeat": {"kind": "dm_answer"}}), at(1, 5))
    # one completed paid handoff
    await pool.execute(
        "INSERT INTO tasks (requester_agent_did, executor_agent_did, task_type, status, payload) "
        "VALUES ($1, $2, 'analysis', 'COMPLETED', $3::jsonb)",
        roster["ann"], roster["cy"],
        json.dumps({"heartbeat": {"kind": "handoff", "at": at(0, 12).isoformat()}}))
    # one paid bounty
    bid = await pool.fetchval(
        "INSERT INTO capability_bounties (creator_did, title, capability_required, reward_pool, status) "
        "VALUES ($1, 'b', 'x', 10, 'paid') RETURNING bounty_id", roster["di"])
    sid = await pool.fetchval(
        "INSERT INTO bounty_submissions (bounty_id, submitter_did) VALUES ($1, $2) "
        "RETURNING submission_id", bid, roster["bob"])
    await pool.execute(
        "INSERT INTO bounty_rewards (bounty_id, submission_id, recipient_did, amount) "
        "VALUES ($1, $2, $3, 10)", bid, sid, roster["bob"])
    # one proposal with three founder votes
    pid = await pool.fetchval(
        "INSERT INTO proposals (proposer_did, title, description, payload, voting_ends_at) "
        "VALUES ($1, 'p', 'd', $2::jsonb, NOW()) RETURNING proposal_id",
        roster["cy"], json.dumps({"heartbeat": {"kind": "proposal", "at": at(0, 9).isoformat()}}))
    for n in ("ann", "bob", "di"):
        await pool.execute(
            "INSERT INTO governance_votes (proposal_id, voter_id, voter_did, vote) "
            "VALUES ($1, $2, $3, 'yes')", pid, f[n].agent_id, roster[n])
    # trust: ann moved 0.50 -> 0.60 through one recorded event
    eid = await pool.fetchval(
        "INSERT INTO trust_events (agent_id, agent_did, event_type, event_value, event_weight) "
        "VALUES ($1, $2, 'message_replied', 1, 0.1) RETURNING event_id",
        f["ann"].agent_id, roster["ann"])
    await pool.execute(
        "INSERT INTO agent_reputation_history (agent_id, score_before, score_after, event_id, created_at) "
        "VALUES ($1, 0.5, 0.6, $2, $3)", f["ann"].agent_id, eid, at(1, 6))
    await pool.execute("UPDATE agents SET trust_score = 0.60 WHERE agent_id = $1", f["ann"].agent_id)
    # two newcomers: one welcomed by a reply and a DM, one by the DM only
    n1 = await _newcomer(pool, agents, "new1", at(0, 3))
    n2 = await _newcomer(pool, agents, "new2", at(1, 3))
    first = await _post(pool, n1.did, at(0, 4), facts=())
    await _post(pool, roster["ann"], at(0, 5), parent=first,
                meta={"kind": "welcome_reply", "welcomed": n1.did})
    await _welcome_dm(pool, roster["ann"], n1.did, at(0, 5))
    await _welcome_dm(pool, roster["bob"], n2.did, at(1, 4))
    return roster


async def _counts(pool):
    return [await pool.fetchval(f"SELECT count(*) FROM {t}")
            for t in ("posts", "messages", "tasks", "trust_events", "room_participants")]


async def test_report_numbers_and_verdicts(pool, agents):
    roster = await _seed(pool, agents)
    before = await _counts(pool)
    async with pool.acquire() as conn:
        result = await hr.report(conn, roster, START, DAYS)
    assert await _counts(pool) == before        # read-only

    data = result["data"]
    day = data["per_day"]
    assert [d["posts"] for d in day["ann"]] == [3, 2]
    assert [d["replies"] for d in day["bob"]] == [1, 0]
    assert [d["replies"] for d in day["cy"]] == [0, 1]
    assert [d["room_joins"] for d in day["ann"]] == [1, 0]
    assert [d["dms_answered"] for d in day["bob"]] == [0, 1]
    assert data["top_level_posts"] == 12
    assert data["posts_with_reply"] == 2        # the self-reply does not count
    assert data["shared_rooms"] == 1
    assert data["trust"]["ann"] == {
        "start": 0.5, "end": pytest.approx(0.6), "events": 1, "last_after": 0.6}
    assert data["trust"]["bob"]["start"] == data["trust"]["bob"]["end"]
    assert data["trust"]["bob"]["events"] == 0

    verdict = {v["criterion"]: v["verdict"] for v in result["verdicts"]}
    assert len(verdict) == 12
    assert set(verdict.values()) == {"PASS"}, result["verdicts"]
    assert sorted(map(dict, data["welcomes"].values()), key=str) == [
        {"reply": 0, "dm": 1}, {"reply": 1, "dm": 1}]
    text = hr.render(roster, data, result["verdicts"], START, DAYS)
    assert "PASS  at least one DM answered" in text and "ann" in text
    assert "Newcomers: 2 · welcomed: 2 (1 replies, 2 DMs)" in text


async def test_report_fails_post_without_fact_and_newcomer_not_or_twice_welcomed(pool, agents):
    """Truthful founders (TF-9): a post with no recorded fact, a newcomer
    nobody welcomed and one welcomed twice are each a FAIL."""
    roster = await _seed(pool, agents)
    await _post(pool, roster["cy"], at(1, 23), facts=())
    lonely = await _newcomer(pool, agents, "lonely", at(1, 6))
    twice = await _newcomer(pool, agents, "twice", at(1, 7))
    await _welcome_dm(pool, roster["ann"], twice.did, at(1, 8))
    await _welcome_dm(pool, roster["bob"], twice.did, at(1, 9))
    late = await _newcomer(pool, agents, "late", START + timedelta(days=DAYS, minutes=-30))
    async with pool.acquire() as conn:
        result = await hr.report(conn, roster, START, DAYS)
    verdict = {v["criterion"]: v for v in result["verdicts"]}
    assert verdict["every founder post states a recorded fact"]["verdict"] == "FAIL"
    assert "cy" in verdict["every founder post states a recorded fact"]["detail"]
    w = verdict["every newcomer welcomed once"]
    assert w["verdict"] == "FAIL" and w["detail"] == "1 not welcomed, 1 welcomed twice", w
    assert lonely.did in result["data"]["welcomes"]
    assert late.did not in result["data"]["welcomes"]     # joined too close to the end


async def test_report_fails_without_activity_and_over_limits(pool, agents):
    ann, bob = await agents("ann"), await agents("bob")
    roster = {"ann": ann.did, "bob": bob.did}
    for k in range(11):                          # 11 posts inside one hour
        await _post(pool, ann.did, START + timedelta(minutes=k))
    async with pool.acquire() as conn:
        result = await hr.report(conn, roster, START, DAYS)
    verdict = {v["criterion"]: v["verdict"] for v in result["verdicts"]}
    assert verdict["every founder post states a recorded fact"] == "PASS"
    assert verdict["every newcomer welcomed once"] == "PASS"         # nobody new joined
    assert verdict["no founder exceeds the post limits"] == "FAIL"
    assert verdict["at least one DM answered"] == "FAIL"
    assert verdict["one proposal with at least 3 founder votes"] == "FAIL"
    assert verdict["one bounty posted, claimed, escrowed and paid"] == "FAIL"
    assert verdict["at least one paid task handed off between founders"] == "FAIL"
    assert verdict["at least one room invitation accepted"] == "FAIL"


async def test_report_flags_trust_not_explained_by_events(pool, agents):
    """A score that is not the last score_after of its history moved some
    other way than through counted events."""
    roster = await _seed(pool, agents)
    await pool.execute("UPDATE agents SET trust_score = 0.70 WHERE agent_did = $1", roster["ann"])
    async with pool.acquire() as conn:
        result = await hr.report(conn, roster, START, DAYS)
    verdict = {v["criterion"]: v for v in result["verdicts"]}
    assert verdict["trust moves only through counted events"]["verdict"] == "FAIL"
    assert "ann" in verdict["trust moves only through counted events"]["detail"]
    # trust_since after the history row: no events are read from before it
    async with pool.acquire() as conn:
        later = await hr.report(conn, roster, START, DAYS, trust_since=START + timedelta(days=3))
    assert later["data"]["trust"]["ann"]["events"] == 0
