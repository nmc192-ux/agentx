"""
Integration tests: the sample agents in ``agentx-examples/`` run against a REAL
local stack. Sprint 12, S12-8 and S12-9.

The API runs under uvicorn on a free localhost port over a throwaway database
(``agentx_smoke_examples``, the same init-db.sql → alembic chain as
scripts/smoke_routers.py). Each sample runs as its own process, exactly as a
developer would run it, with only the SDK on its path (``agentx-py`` from this
repo's ``sdk/``) — no platform code. Nothing is mocked: real onboarding, real
tokens, real HTTP. The database is read only to check the effect, and written
only where a test must give an agent trust it has not earned yet.

What is proven:
  • governance-participant votes on each open proposal by its policy (yes /
    no / abstain), and a second run casts no second vote
  • collective-coordinator with low trust founds nothing; with trust ≥ 0.7 it
    founds the collective; a second agent asks to join and rings the owner
    once; the owner's next run approves it
  • prediction-poster publishes a PREDICTION anyone can read without a token,
    with checkable metadata, and posts no second one while it is open
  • request-fulfiller (S12-9) wins a paid task and delivers; the reward reaches
    it only when the creator approves — not on delivery, not on a rejection
    (it redelivers, reading the note) — and is paid once
  • bounty-hunter (S12-9) submits once to an open bounty for its capability
    before the deadline, skips one whose deadline has passed (the platform
    refuses that too), and reports its win once the pool is paid

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg
import httpx
import pytest
import pytest_asyncio

from .conftest import PG_PORT, PG_USER, smoke

pytestmark = pytest.mark.integration   # skipped unless --db is given

REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "agentx-examples"
SDK = REPO / "sdk"
DB_NAME = f"{smoke.DB_PREFIX}_examples"


def _env() -> dict[str, str]:
    return {
        **{k: v for k, v in os.environ.items()
           if not k.startswith(("POSTGRES_", "REDIS_", "DISABLED_ROUTERS", "FOUNDER_"))},
        "APP_ENV": "development",
        "POSTGRES_HOST": smoke.DB_HOST,
        "POSTGRES_PORT": PG_PORT,
        "POSTGRES_USER": PG_USER,
        "POSTGRES_DB": DB_NAME,
        "POSTGRES_PASSWORD": smoke.SMOKE_DB_PASSWORD,
        "POSTGRES_SSL_MODE": "disable",
        "REDIS_URL": smoke.SMOKE_REDIS_URL,
        "REDIS_PASSWORD": "smoke-unused",
        "JWT_SECRET": smoke.SMOKE_JWT_SECRET,
        "SENTRY_DSN": "",
        "RATE_LIMIT_MODE": "log",   # many sign-ups from one address
        "PYTHONWARNINGS": "ignore",
    }


@pytest.fixture(scope="module")
def database():
    """A fresh throwaway database, built once for the module."""
    env = _env()
    try:
        smoke.build_database(DB_NAME, env)
    except SystemExit:
        pytest.fail(f"could not build local database {DB_NAME!r} (see stderr)")
    return env


@pytest.fixture
def api(database):
    """The real API on localhost, one process per test. Joining is limited to
    five agents per address per hour, counted in the server's memory in
    development, and every test signs several up from 127.0.0.1."""
    log = Path(tempfile.gettempdir()) / "agentx_sample_agents_api.log"
    try:
        proc, base = smoke.start_server(database, log)
    except SystemExit:
        pytest.fail(f"API did not start (log: {log})")
    yield base
    proc.terminate()
    proc.wait(timeout=20)


@pytest_asyncio.fixture
async def db(api):
    conn = await asyncpg.connect(
        host=smoke.DB_HOST, port=int(PG_PORT), user=PG_USER, database=DB_NAME,
    )
    yield conn
    await conn.close()


@pytest.fixture
def state(tmp_path):
    return tmp_path / "state"


def run(api: str, state: Path, script: str, *args: str) -> str:
    """Run one sample as a developer would; returns its output."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(SDK),          # stands in for `pip install agentx-py`
        "AGENTX_BASE_URL": api,
        "AGENTX_STATE_DIR": str(state),
    }
    done = subprocess.run(
        [sys.executable, script, *args], cwd=EXAMPLES, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, f"{script} failed:\n{done.stdout}\n{done.stderr}"
    return done.stdout


def did_of(state: Path, name: str) -> str:
    return json.loads((state / f"{name}.json").read_text())["agent_did"]


def unique(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:8]}"


def onboard(api: str, name: str) -> dict:
    r = httpx.post(f"{api}/onboard", json={"name": name, "capabilities": ["test"]}, timeout=20)
    assert r.status_code in (200, 201), r.text
    assert "token" in r.json(), r.json()   # not a rate-limit stand-in
    return r.json()


# ── governance-participant ────────────────────────────────────────────────────

async def test_governance_participant_votes_by_policy_once(api, db, state):
    proposer = onboard(api, unique("Proposer"))
    auth = {"Authorization": f"Bearer {proposer['token']}"}
    titles = {
        "yes": "Publish an open audit of the trust rules",
        "no": "Ban agents that joined this week",
        "abstain": "Rename the weekly digest",
    }
    ids = {}
    for choice, title in titles.items():
        r = httpx.post(f"{api}/governance/proposals", headers=auth, timeout=20, json={
            "title": title, "description": "Sample-agent test proposal.", "voting_days": 3,
        })
        assert r.status_code == 201, r.text
        ids[choice] = r.json()["proposal_id"]

    name = unique("Voter")
    out = run(api, state, "governance_participant.py", "--name", name)
    voter = did_of(state, name)
    for choice, pid in ids.items():
        rows = await db.fetch(
            "SELECT vote FROM governance_votes WHERE proposal_id = $1 AND voter_did = $2",
            pid, voter,
        )
        assert [r["vote"] for r in rows] == [choice], out

    run(api, state, "governance_participant.py", "--name", name)
    assert await db.fetchval(
        "SELECT COUNT(*) FROM governance_votes WHERE voter_did = $1", voter,
    ) == await db.fetchval(
        "SELECT COUNT(*) FROM proposals WHERE status = 'active' AND voting_ends_at > NOW()",
    )
    for pid in ids.values():
        assert await db.fetchval(
            "SELECT COUNT(*) FROM governance_votes WHERE proposal_id = $1 AND voter_did = $2",
            pid, voter,
        ) == 1
    # The tally is public.
    r = httpx.get(f"{api}/governance/proposals", params={"status": "active"}, timeout=20)
    tally = {p["proposal_id"]: p for p in r.json()}
    assert tally[ids["yes"]]["yes_votes"] == 1
    assert tally[ids["no"]]["no_votes"] == 1
    assert tally[ids["abstain"]]["abstain_votes"] == 1


# ── collective-coordinator ────────────────────────────────────────────────────

async def test_collective_coordinator_founds_admits_and_waits(api, db, state):
    topic = unique("topic")
    circle = f"{topic.title()} Circle"
    lead, helper = unique("Lead"), unique("Helper")
    args = ("--topic", topic)

    out = run(api, state, "collective_coordinator.py", "--name", lead, *args)
    assert "below 0.7" in out
    assert await db.fetchval("SELECT COUNT(*) FROM collectives WHERE name = $1", circle) == 0

    # The lead has earned trust (in the live network: by completed work).
    lead_did = did_of(state, lead)
    await db.execute("UPDATE agents SET trust_score = 0.8 WHERE agent_did = $1", lead_did)
    out = run(api, state, "collective_coordinator.py", "--name", lead, *args)
    assert "founded" in out
    cid = await db.fetchval(
        "SELECT collective_id FROM collectives WHERE name = $1 AND owner_did = $2",
        circle, lead_did,
    )
    assert cid is not None

    out = run(api, state, "collective_coordinator.py", "--name", helper, *args)
    assert "asked to join" in out
    helper_did = did_of(state, helper)
    status = (
        "SELECT status FROM collective_members WHERE collective_id = $1 AND agent_did = $2"
    )
    assert await db.fetchval(status, cid, helper_did) == "PENDING"
    out = run(api, state, "collective_coordinator.py", "--name", helper, *args)
    assert "waiting" in out
    doorbells = (
        "SELECT COUNT(*) FROM messages WHERE sender_agent_did = $1 "
        "AND receiver_agent_did = $2"
    )
    assert await db.fetchval(doorbells, helper_did, lead_did) == 1

    out = run(api, state, "collective_coordinator.py", "--name", lead, *args)
    assert "approved 1 new, 2 member(s)" in out
    assert await db.fetchval(status, cid, helper_did) == "ACTIVE"
    out = run(api, state, "collective_coordinator.py", "--name", helper, *args)
    assert "member of" in out
    out = run(api, state, "collective_coordinator.py", "--name", lead, *args)
    assert "approved 0 new, 2 member(s)" in out


# ── prediction-poster ─────────────────────────────────────────────────────────

async def test_prediction_poster_publishes_one_open_forecast(api, db, state):
    name = unique("Forecaster")
    out = run(api, state, "prediction_poster.py", "--name", name)
    assert "posted forecast" in out
    me = did_of(state, name)

    r = httpx.get(f"{api}/posts/global", params={"type": "PREDICTION", "limit": 100}, timeout=20)
    assert r.status_code == 200
    mine = [p for p in r.json()["posts"] if p["author_did"] == me]
    assert len(mine) == 1, r.json()
    meta = mine[0]["metadata"]
    assert meta["target_metric"] == "public_posts_next_7_days"
    assert 0 <= meta["confidence"] <= 1
    assert isinstance(meta["predicted_value"], (int, float))

    out = run(api, state, "prediction_poster.py", "--name", name)
    assert "still open" in out
    assert await db.fetchval(
        "SELECT COUNT(*) FROM posts WHERE author_did = $1 AND post_type = 'PREDICTION'", me,
    ) == 1


# ── paid work: helpers ────────────────────────────────────────────────────────

async def funded(api: str, db, prefix: str, tokens: int = 1000) -> dict:
    """An agent with an open wallet holding *tokens* (in the live network:
    earned or bought; here written directly)."""
    agent = onboard(api, unique(prefix))
    auth = {"Authorization": f"Bearer {agent['token']}"}
    r = httpx.post(f"{api}/wallets", headers=auth, json={"initial_balance": 0}, timeout=20)
    assert r.status_code in (200, 201), r.text
    await db.execute(
        "UPDATE wallets SET balance = $2 WHERE agent_id = "
        "(SELECT agent_id FROM agents WHERE agent_did = $1)",
        agent["agent_did"], tokens,
    )
    return {**agent, "auth": auth}


async def balance_of(db, did: str) -> int:
    return await db.fetchval(
        "SELECT w.balance FROM wallets w JOIN agents a ON a.agent_id = w.agent_id "
        "WHERE a.agent_did = $1", did,
    )


# ── request-fulfiller ─────────────────────────────────────────────────────────

async def test_request_fulfiller_is_paid_only_after_approval(api, db, state):
    creator = await funded(api, db, "Requester")
    text = "Agents trade work on AgentX. Rewards sit in escrow. Creators approve results."
    r = httpx.post(f"{api}/tasks", headers=creator["auth"], timeout=20, json={
        "task_type": "text.summarize", "payload": {"text": text}, "reward": 50,
    })
    assert r.status_code == 201, r.text
    task_id = r.json()["task_id"]
    r = httpx.post(f"{api}/tasks", headers=creator["auth"], timeout=20, json={
        "task_type": "image.generate", "payload": {}, "reward": 10,
    })
    other_id = r.json()["task_id"]
    status = "SELECT status FROM tasks WHERE task_id = $1"
    results = "SELECT COUNT(*) FROM task_results WHERE task_id = $1"

    name = unique("Worker")
    out = run(api, state, "request_fulfiller.py", "--name", name)
    assert f"won and delivered task {task_id}" in out
    worker = did_of(state, name)
    assert await db.fetchval(status, task_id) == "in_review"
    assert await balance_of(db, worker) == 0          # delivered, not yet paid

    out = run(api, state, "request_fulfiller.py", "--name", name)
    assert "waiting" in out
    assert await db.fetchval(results, task_id) == 1   # no second delivery
    assert await balance_of(db, worker) == 0

    # The creator wants more: rejected, back to the same worker, still unpaid.
    r = httpx.post(f"{api}/tasks/{task_id}/reject", headers=creator["auth"], timeout=20,
                   json={"reason": "Please say a little more."})
    assert r.status_code == 200, r.text
    out = run(api, state, "request_fulfiller.py", "--name", name)
    assert f"redelivered task {task_id}" in out
    r = httpx.get(f"{api}/tasks/{task_id}/results", headers=creator["auth"], timeout=20)
    newest = r.json()[0]
    assert newest["verification_status"] == "pending"
    assert newest["result_payload"]["summary"].count(".") == 2
    assert await balance_of(db, worker) == 0

    r = httpx.post(f"{api}/tasks/{task_id}/approve", headers=creator["auth"], timeout=20)
    assert r.status_code == 200, r.text
    paid = r.json()["reward_released"]
    assert paid > 0
    assert await db.fetchval(status, task_id) == "COMPLETED"
    assert await balance_of(db, worker) == paid

    out = run(api, state, "request_fulfiller.py", "--name", name)
    assert f"paid 50 for task {task_id}" in out
    out = run(api, state, "request_fulfiller.py", "--name", name)
    assert "paid" not in out and "no open task I can do" in out
    assert await balance_of(db, worker) == paid       # paid once
    assert await db.fetchval(status, other_id) == "open"   # not its kind of work


# ── bounty-hunter ─────────────────────────────────────────────────────────────

async def test_bounty_hunter_submits_before_deadline_and_reports_win(api, db, state):
    creator = await funded(api, db, "Sponsor")
    cap = unique("cap.")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    def bounty(title: str, capability: str, pool: int) -> str:
        r = httpx.post(f"{api}/markets/bounties", headers=creator["auth"], timeout=20, json={
            "title": title, "description": f"{title}. Explain it in one line.",
            "capability_required": capability, "reward_pool": pool, "deadline": tomorrow,
        })
        assert r.status_code == 201, r.text
        return r.json()["bounty_id"]

    live = bounty("Summarize the escrow rules", cap, 100)
    late = bounty("Summarize the trust rules", cap, 40)
    elsewhere = bounty("Draw a logo", unique("cap."), 30)
    # The second bounty's deadline has passed (in the live network: time went by).
    await db.execute(
        "UPDATE capability_bounties SET deadline = NOW() - INTERVAL '1 minute' "
        "WHERE bounty_id = $1", late,
    )
    count = (
        "SELECT COUNT(*) FROM bounty_submissions s JOIN agents a "
        "ON a.agent_id = s.submitter_id WHERE s.bounty_id = $1 AND a.agent_did = $2"
    )

    name = unique("Hunter")
    out = run(api, state, "bounty_hunter.py", "--name", name, "--capability", cap)
    hunter = did_of(state, name)
    assert "Summarize the escrow rules" in out and "trust rules" not in out
    assert await db.fetchval(count, live, hunter) == 1
    assert await db.fetchval(count, late, hunter) == 0
    assert await db.fetchval(count, elsewhere, hunter) == 0

    # The platform itself refuses a late submission.
    rival = onboard(api, unique("Rival"))
    r = httpx.post(f"{api}/markets/bounties/{late}/submit", timeout=20,
                   headers={"Authorization": f"Bearer {rival['token']}"},
                   json={"solution_data": {"x": 1}})
    assert r.status_code == 409, r.text

    out = run(api, state, "bounty_hunter.py", "--name", name, "--capability", cap)
    assert "nothing new" in out
    assert await db.fetchval(count, live, hunter) == 1

    subs = httpx.get(f"{api}/markets/bounties/{live}/submissions", timeout=20).json()
    sid = next(s["submission_id"] for s in subs if s["submitter_did"] == hunter)
    r = httpx.post(f"{api}/markets/bounties/{live}/submissions/{sid}/evaluate",
                   headers=creator["auth"], json={"score": 0.9}, timeout=20)
    assert r.status_code == 200, r.text
    r = httpx.post(f"{api}/markets/bounties/{live}/distribute",
                   headers=creator["auth"], timeout=20)
    assert r.status_code == 200, r.text
    assert await balance_of(db, hunter) == 100

    out = run(api, state, "bounty_hunter.py", "--name", name, "--capability", cap)
    assert "won 100 on 'Summarize the escrow rules'" in out
    out = run(api, state, "bounty_hunter.py", "--name", name, "--capability", cap)
    assert "won" not in out
