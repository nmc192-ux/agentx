"""
Integration tests: the sample agents in ``agentx-examples/`` run against a REAL
local stack. Sprint 12, S12-8.

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

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
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
def api():
    """The real API on localhost over a fresh throwaway database."""
    env = _env()
    try:
        smoke.build_database(DB_NAME, env)
    except SystemExit:
        pytest.fail(f"could not build local database {DB_NAME!r} (see stderr)")
    log = Path(tempfile.gettempdir()) / "agentx_sample_agents_api.log"
    try:
        proc, base = smoke.start_server(env, log)
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
