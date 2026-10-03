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


async def _post(pool, did, when, parent=None, title="t"):
    return await pool.fetchval(
        "INSERT INTO posts (author_did, post_type, title, content, parent_post_id, "
        "created_at, updated_at) VALUES ($1, 'UPDATE', $2, 'text', $3, $4, $4) RETURNING post_id",
        did, title, parent, when,
    )


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
    assert data["trust"]["ann"] == {"start": 0.5, "end": pytest.approx(0.6)}
    assert data["trust"]["bob"]["start"] == data["trust"]["bob"]["end"]

    verdict = {v["criterion"]: v["verdict"] for v in result["verdicts"]}
    assert len(verdict) == 10
    assert set(verdict.values()) == {"PASS"}, result["verdicts"]
    text = hr.render(roster, data, result["verdicts"], START, DAYS)
    assert "PASS  at least one DM answered" in text and "ann" in text


async def test_report_fails_without_activity_and_over_limits(pool, agents):
    ann, bob = await agents("ann"), await agents("bob")
    roster = {"ann": ann.did, "bob": bob.did}
    for k in range(11):                          # 11 posts inside one hour
        await _post(pool, ann.did, START + timedelta(minutes=k))
    async with pool.acquire() as conn:
        result = await hr.report(conn, roster, START, DAYS)
    verdict = {v["criterion"]: v["verdict"] for v in result["verdicts"]}
    assert verdict["every founder posts on each day"] == "FAIL"     # bob never posts
    assert verdict["no founder exceeds the post limits"] == "FAIL"
    assert verdict["at least one DM answered"] == "FAIL"
    assert verdict["one proposal with at least 3 founder votes"] == "FAIL"
    assert verdict["one bounty posted, claimed, escrowed and paid"] == "FAIL"
    assert verdict["at least one paid task handed off between founders"] == "FAIL"
    assert verdict["at least one room invitation accepted"] == "FAIL"
