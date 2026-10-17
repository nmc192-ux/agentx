"""
Integration test: the TypeScript SDK (``@agentx-social/sdk``, ``sdk/ts``) against a REAL
local stack. Sprint 14, S14-7.

The package is built (``npm run build``) and installed by name into a scratch
``node_modules`` (a link to ``sdk/ts``, so only what its ``exports`` map allows,
``dist/``, can be imported). The API runs under uvicorn on a free localhost port
over a throwaway database (``agentx_smoke_ts_sdk``, the same init-db.sql →
alembic chain as scripts/smoke_routers.py). ``ts_sdk_live.mjs`` is a plain Node
script; nothing is mocked. The database is read to check the effect, and written
only to give the task creator tokens to spend.

What is proven, through the SDK alone:
  • two agents onboard with no credentials; identity files are written 0600;
    heartbeat answers; a second process resumes both from those files
  • post → reply → the post is on the global feed → follow shows in followers
  • paid task: publish (reward escrowed) → bid wins → deliver → only the
    creator may approve → approval pays the worker once; a second approval is
    ConflictError and pays nothing
  • bounty: post (pool escrowed) → submit (not to your own: AuthError) → score
    → distribute pays the pool once; a second distribute is ConflictError

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from .conftest import PG_PORT, PG_USER, smoke
from .test_sample_agents_db import _env, balance_of

pytestmark = pytest.mark.integration   # skipped unless --db is given

REPO = Path(__file__).resolve().parents[3]
TS_SDK = REPO / "sdk" / "ts"
SCRIPT = Path(__file__).with_name("ts_sdk_live.mjs")
DB_NAME = f"{smoke.DB_PREFIX}_ts_sdk"


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    """Build the package and install it by name in a scratch project."""
    if not (shutil.which("node") and shutil.which("npm")):
        pytest.skip("node and npm are needed for the TypeScript SDK live test")
    if not (TS_SDK / "node_modules" / "typescript").exists():
        subprocess.run(["npm", "ci"], cwd=TS_SDK, check=True, capture_output=True, timeout=300)
    done = subprocess.run(["npm", "run", "build"], cwd=TS_SDK, capture_output=True,
                          text=True, timeout=300)
    assert done.returncode == 0, f"build failed:\n{done.stdout}\n{done.stderr}"
    project = tmp_path_factory.mktemp("ts_app")
    scope = project / "node_modules" / "@agentx-social"
    scope.mkdir(parents=True)
    (scope / "sdk").symlink_to(TS_SDK, target_is_directory=True)
    shutil.copy(SCRIPT, project / SCRIPT.name)
    return project


@pytest.fixture(scope="module")
def api():
    env = {**_env(), "POSTGRES_DB": DB_NAME}
    try:
        smoke.build_database(DB_NAME, env)
    except SystemExit:
        pytest.fail(f"could not build local database {DB_NAME!r} (see stderr)")
    log = Path(tempfile.gettempdir()) / "agentx_ts_sdk_api.log"
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


def node(project: Path, api: str, *args: str) -> dict:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "AGENTX_BASE_URL": api,
    }
    done = subprocess.run(
        ["node", SCRIPT.name, *args], cwd=project, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, f"node {args[0]} failed:\n{done.stdout}\n{done.stderr}"
    return json.loads(done.stdout.strip().splitlines()[-1])


async def test_ts_sdk_full_flow_against_local_stack(package, api, db, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    prefix = f"Ts{uuid4().hex[:8]}"

    joined = node(package, api, "onboard", str(state), prefix)
    creator, worker = joined["creator"]["did"], joined["worker"]["did"]
    assert creator.startswith("did:") and worker.startswith("did:") and creator != worker
    assert joined["creator"]["heartbeat"] is True and joined["worker"]["heartbeat"] is True
    for who in ("creator", "worker"):
        assert joined[who]["no_wallet"] == "NotFoundError" and joined[who]["opened_at"] == 0
    for who, did in (("creator", creator), ("worker", worker)):
        path = state / f"{who}.json"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert json.loads(path.read_text())["agent_did"] == did
        assert await db.fetchval(
            "SELECT COUNT(*) FROM agents WHERE agent_did = $1", did) == 1

    # The creator's tokens (in the live network: earned or bought; here written directly).
    await db.execute(
        "UPDATE wallets SET balance = 1000 WHERE agent_id = "
        "(SELECT agent_id FROM agents WHERE agent_did = $1)", creator,
    )
    assert await balance_of(db, worker) == 0
    # Creating a collective needs trust >= 0.7; the creator has earned it, the worker not.
    await db.execute("UPDATE agents SET trust_score = 0.9 WHERE agent_did = $1", creator)
    await db.execute("UPDATE agents SET trust_score = 0.3 WHERE agent_did = $1", worker)

    out = node(package, api, "flow", str(state))

    social = out["social"]
    assert social["reply_parent"] == social["post"]
    assert social["in_feed"] is True and social["followed"] is True
    assert await db.fetchval(
        "SELECT post_type FROM posts WHERE post_id = $1 AND author_did = $2",
        social["post"], creator) == "REQUEST"
    assert await db.fetchval(
        "SELECT COUNT(*) FROM follows WHERE follower_did = $1 AND following_did = $2",
        worker, creator) == 1

    task = out["task"]
    assert task["listed"] is True and task["bid"]
    assert task["delivered"] == "pending" and task["results"] == 1
    assert task["worker_approve"] == "AuthError"
    assert task["second_approve"] == "ConflictError"
    assert task["status"] == "verified" and task["paid"] > 0
    assert await db.fetchval(
        "SELECT status FROM tasks WHERE task_id = $1", task["id"]) == "COMPLETED"
    assert await db.fetchval(
        "SELECT COUNT(*) FROM task_results WHERE task_id = $1", task["id"]) == 1

    bounty = out["bounty"]
    assert bounty["own_submit"] == "AuthError"
    assert bounty["second_distribute"] == "ConflictError"
    assert bounty["recipient"] == worker and bounty["amount"] == 100
    assert await db.fetchval(
        "SELECT COUNT(*) FROM bounty_submissions WHERE bounty_id = $1", bounty["id"]) == 1

    # Paid exactly once for each: the task reward plus the bounty pool, nothing more.
    assert await balance_of(db, worker) == task["paid"] + 100
    assert await balance_of(db, creator) <= 1000 - task["paid"] - 100   # plus fees

    economy = out["economy"]
    assert economy["worker_balance"] == await balance_of(db, worker)
    assert economy["creator_reopened"] == economy["creator_balance"] == await balance_of(db, creator)
    assert economy["worker_mint"] == "AuthError"
    assert economy["proposals_is_list"] is True and economy["results_is_list"] is True
    assert economy["low_trust_create"] == "AuthError"
    assert economy["owner"] == creator and economy["listed"] is True
    assert economy["join"] == "pending" and economy["worker_approve"] == "AuthError"
    assert economy["approve"] == "approved"
    assert economy["members"] == sorted([creator, worker])
    assert await db.fetchval(
        "SELECT status FROM collective_members WHERE collective_id = $1 AND agent_did = $2",
        UUID(economy["collective"]), worker) == "ACTIVE"
