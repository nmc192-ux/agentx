"""
Integration test: a fresh agent and its @handle, through the Python SDK only,
against a REAL local stack. Layer 1 S2-3.

The API runs under uvicorn on a free localhost port over a throwaway database
(``agentx_smoke_handles_sdk``, the same init-db.sql → alembic chain as
scripts/smoke_routers.py). The agent is a separate process with only the SDK on
its path (``agentx-social`` from this repo's ``sdk/``), as a developer would run
it. Nothing is mocked. The database is read only to check the effect.

What is proven, through the SDK alone:
  • onboarding returns a handle made from the new DID, and it is in the profile
  • another agent finds it by that handle (``@`` and capitals folded)
  • the agent chooses a new handle; the old one still finds it (current handle
    in the answer); a second change inside 30 days is refused with 409 and
    changes nothing; a founder's name is refused with 403
  • a name another agent holds is refused with 409

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from .conftest import PG_PORT, PG_USER, smoke
from .test_sample_agents_db import _env as _examples_env

pytestmark = pytest.mark.integration   # skipped unless --db is given

REPO = Path(__file__).resolve().parents[3]
SDK = REPO / "sdk"
DB_NAME = f"{smoke.DB_PREFIX}_handles_sdk"

AGENT = r"""
import json, sys
sys.path.insert(0, sys.argv.pop(1))   # stands in for `pip install agentx-social`
from agentx_sdk import AgentXClient
from agentx_sdk.exceptions import AgentXError

base, name, other_name, new_handle = sys.argv[1:5]
out = {}

me = AgentXClient.onboard(name, capabilities=["test"], base_url=base)
other = AgentXClient.onboard(other_name, capabilities=["test"], base_url=base)
out["did"] = me.agent_did
out["onboard_handle"] = me.onboarding.handle
out["profile_handle"] = me.get_agent(me.agent_did).handle
found = other.get_agent_by_handle("@" + me.onboarding.handle.upper())
out["found_did"] = found.agent_did

change = me.set_handle(new_handle)
out["change"] = {k: change[k] for k in ("handle", "previous_handle", "changed")}
out["next_change_at"] = change["next_change_at"]
out["by_new"] = other.get_agent_by_handle(new_handle).agent_did
old = other.get_agent_by_handle(me.onboarding.handle)
out["by_old"] = [old.agent_did, old.handle]

def refusal(client, handle):
    try:
        client.set_handle(handle)
    except AgentXError as exc:
        return exc.status_code
    return None

out["second_change"] = refusal(me, new_handle + "_x")
out["taken"] = refusal(other, new_handle)
out["founder"] = refusal(other, "atlas")
out["same_again"] = other.set_handle(other.onboarding.handle)["changed"]
print(json.dumps(out))
"""


def _env() -> dict[str, str]:
    return {**_examples_env(), "POSTGRES_DB": DB_NAME}


@pytest.fixture(scope="module")
def database():
    env = _env()
    try:
        smoke.build_database(DB_NAME, env)
    except SystemExit:
        pytest.fail(f"could not build local database {DB_NAME!r} (see stderr)")
    return env


@pytest.fixture
def api(database):
    log = Path(tempfile.gettempdir()) / "agentx_handles_sdk_api.log"
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


async def test_fresh_agent_gets_finds_and_changes_its_handle(api, db, tmp_path):
    tag = uuid4().hex[:6]
    new_handle = f"picked_{tag}"
    done = subprocess.run(
        [sys.executable, "-I", "-c", AGENT, str(SDK), api, f"Fresh{tag}", f"Other{tag}",
         new_handle],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=120, cwd=tmp_path,
    )
    assert done.returncode == 0, f"agent failed:\n{done.stdout}\n{done.stderr}"
    out = json.loads(done.stdout.strip().splitlines()[-1])

    derived = out["did"].removeprefix("did:agentx:").replace("-", "_")
    assert out["onboard_handle"] == derived
    assert out["profile_handle"] == derived
    assert out["found_did"] == out["did"]

    assert out["change"] == {"handle": new_handle, "previous_handle": derived, "changed": True}
    assert out["next_change_at"]
    assert out["by_new"] == out["did"]
    assert out["by_old"] == [out["did"], new_handle]      # old name still finds it

    assert out["second_change"] == 409
    assert out["taken"] == 409
    assert out["founder"] == 403
    assert out["same_again"] is False

    row = await db.fetchrow("SELECT handle FROM agents WHERE agent_did = $1", out["did"])
    assert row["handle"] == new_handle                     # the refused change did nothing
    redirect = await db.fetchrow(
        "SELECT agent_did, expires_at > NOW() AS live FROM handle_redirects WHERE old_handle = $1",
        derived,
    )
    assert redirect["agent_did"] == out["did"] and redirect["live"]
