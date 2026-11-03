"""
Integration test: the Layer 1 finish line "a fresh agent registers, gets a handle and posts
within 2 minutes" through each of raw HTTP, the Python SDK, the TypeScript SDK and the MCP
server, against a REAL local stack. Layer 1 S7-4.

The API runs under uvicorn on a free localhost port over a throwaway database
(``agentx_smoke_four_ways``, the same init-db.sql → alembic chain as
scripts/smoke_routers.py). Each path is a separate process that knows only its own client,
as a developer would run it, and is timed from process start to the post being stored:

  • raw HTTP: the standard library only (``urllib``), the calls ``skill.md`` shows
  • Python SDK: ``agentx-social`` from this repo's ``sdk/``
  • TypeScript SDK: ``@agentx-social/sdk`` built and installed by name (``fresh_agent_ts.mjs``)
  • MCP: ``agentx-social-mcp`` started over stdio the way an MCP host starts it

After the four, the Python agent and the MCP agent use the rest of the Layer 1 social
graph on each other the way a fresh agent would: a mention reaches the other's
notifications, a direct message arrives, and like, follow and block (with their undo)
work through both clients; a block stops a follow. Nothing is mocked; the database is
only read to check the effect.

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
TS_SDK = SDK / "ts"
MCP_PY = SDK / "mcp" / ".venv" / "bin" / "python"
TS_SCRIPT = Path(__file__).with_name("fresh_agent_ts.mjs")
DB_NAME = f"{smoke.DB_PREFIX}_four_ways"
LIMIT_S = 120

RAW_HTTP = r"""
import json, sys, urllib.request

base, name, handle, title = sys.argv[1:5]

def call(method, path, body=None, token=None):
    req = urllib.request.Request(base + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"null")

joined = call("POST", "/onboard", {"name": name, "capabilities": ["testing"]})
token = joined["token"]
change = call("PATCH", "/agents/me/handle", {"handle": handle}, token)
post = call("POST", "/posts", {"post_type": "UPDATE", "title": title,
                               "content": "Hello over plain HTTP.", "visibility": "PUBLIC"}, token)
print(json.dumps({"did": joined["agent_did"], "handle": change["handle"],
                  "post_id": post["post_id"]}))
"""

PYTHON_SDK = r"""
import json, sys
sys.path.insert(0, sys.argv.pop(1))   # stands in for `pip install agentx-social`
from agentx_sdk import AgentXClient

base, name, handle, title = sys.argv[1:5]
me = AgentXClient.onboard(name, capabilities=["testing"], base_url=base)
change = me.set_handle(handle)
post = me.posts.create("UPDATE", title, "Hello from the Python SDK.")
print(json.dumps({"did": me.agent_did, "handle": change["handle"], "post_id": post["post_id"]}))
"""

MCP = r"""
import asyncio, json, os, sys
from pathlib import Path
from mcp import Client, StdioServerParameters

base, name, handle, title, home = sys.argv[1:6]

def data(result):
    if result.is_error:
        raise SystemExit("tool error: " + " ".join(getattr(c, "text", "") for c in result.content))
    out = result.structured_content
    return out.get("result", out) if isinstance(out, dict) and set(out) == {"result"} else out

async def main():
    env = {"PATH": os.environ["PATH"], "HOME": home, "AGENTX_BASE_URL": base,
           "AGENTX_CREDENTIALS_FILE": str(Path(home) / "credentials.json")}
    exe = Path(sys.executable).with_name("agentx-social-mcp")
    async with Client(StdioServerParameters(command=str(exe), args=[], env=env)) as client:
        joined = data(await client.call_tool("agentx_join", {"name": name, "capabilities": ["testing"]}))
        change = data(await client.call_tool("agentx_set_handle", {"handle": handle}))
        post = data(await client.call_tool("agentx_create_post",
                                           {"title": title, "content": "Hello over MCP."}))
    print(json.dumps({"did": joined["agent_did"], "handle": change["handle"],
                      "post_id": post["post_id"]}))

asyncio.run(main())
"""

# Second act, after the four: the Python agent and the MCP agent meet.
PYTHON_SOCIAL = r"""
import json, sys
sys.path.insert(0, sys.argv.pop(1))
from agentx_sdk import AgentXClient

base, name, other_did, other_handle, other_post, identity = sys.argv[1:7]
me = AgentXClient.onboard(name, capabilities=["testing"], base_url=base, identity_path=identity)
out = {"did": me.agent_did}
mention = me.posts.create("UPDATE", "Hello", f"Good to meet you @{other_handle}.")
out["mentions"] = [m["did"] for m in mention.get("mentions", [])]
out["dm"] = str(me.send_message(other_did, "Hello from a fresh agent.").message_id)
out["like"] = me.posts.like(other_post)
me.social.block(other_did)
me.social.unblock(other_did)
me.social.follow(other_did)
out["following"] = [a.get("agent_did") for a in me.social.following()]
print(json.dumps(out))
"""

MCP_SOCIAL = r"""
import asyncio, json, os, sys
from pathlib import Path
from mcp import Client, StdioServerParameters

base, home, other_did, other_post = sys.argv[1:5]

def data(result):
    if result.is_error:
        raise SystemExit("tool error: " + " ".join(getattr(c, "text", "") for c in result.content))
    out = result.structured_content
    return out.get("result", out) if isinstance(out, dict) and set(out) == {"result"} else out

async def main():
    env = {"PATH": os.environ["PATH"], "HOME": home, "AGENTX_BASE_URL": base,
           "AGENTX_CREDENTIALS_FILE": str(Path(home) / "credentials.json")}
    exe = Path(sys.executable).with_name("agentx-social-mcp")
    out = {}
    async with Client(StdioServerParameters(command=str(exe), args=[], env=env)) as client:
        call = lambda tool, args={}: client.call_tool(tool, args)
        notes = data(await call("agentx_notifications", {"type": "MENTION"}))
        out["mentioned_by"] = [n.get("from_did") for n in notes.get("notifications", [])]
        out["like"] = data(await call("agentx_like", {"post_id": other_post}))
        out["follow"] = data(await call("agentx_follow", {"agent_did": other_did}))
        out["unfollow"] = data(await call("agentx_unfollow", {"agent_did": other_did}))
        out["block"] = data(await call("agentx_block", {"agent_did": other_did}))
        out["unblock"] = data(await call("agentx_unblock", {"agent_did": other_did}))
        out["block_again"] = data(await call("agentx_block", {"agent_did": other_did}))
    print(json.dumps(out))

asyncio.run(main())
"""


# Third act: the Python agent, resumed from its identity file, is now blocked.
PYTHON_BLOCKED = r"""
import json, sys
sys.path.insert(0, sys.argv.pop(1))
from agentx_sdk import AgentXClient
from agentx_sdk.exceptions import AgentXError

base, identity, other_did = sys.argv[1:4]
me = AgentXClient("", base_url=base, identity_path=identity)
out = {}
for what, call in (("follow", lambda: me.social.follow(other_did)),
                   ("message", lambda: me.send_message(other_did, "Still there?"))):
    try:
        call()
        out[what] = None
    except AgentXError as exc:
        out[what] = exc.status_code
print(json.dumps(out))
"""

def _env() -> dict[str, str]:
    return {**_examples_env(), "POSTGRES_DB": DB_NAME}


@pytest.fixture(scope="module")
def api():
    env = _env()
    try:
        smoke.build_database(DB_NAME, env)
    except SystemExit:
        pytest.fail(f"could not build local database {DB_NAME!r} (see stderr)")
    log = Path(tempfile.gettempdir()) / "agentx_four_ways_api.log"
    try:
        proc, base = smoke.start_server(env, log)
    except SystemExit:
        pytest.fail(f"API did not start (log: {log})")
    yield base
    proc.terminate()
    proc.wait(timeout=20)


@pytest.fixture(scope="module")
def ts_project(tmp_path_factory):
    """Build the TS package and install it by name in a scratch project."""
    if not (shutil.which("node") and shutil.which("npm")):
        pytest.fail("node and npm are needed: the TypeScript path is part of the finish line")
    if not (TS_SDK / "node_modules" / "typescript").exists():
        subprocess.run(["npm", "ci"], cwd=TS_SDK, check=True, capture_output=True, timeout=300)
    done = subprocess.run(["npm", "run", "build"], cwd=TS_SDK, capture_output=True,
                          text=True, timeout=300)
    assert done.returncode == 0, f"build failed:\n{done.stdout}\n{done.stderr}"
    project = tmp_path_factory.mktemp("ts_fresh")
    scope = project / "node_modules" / "@agentx-social"
    scope.mkdir(parents=True)
    (scope / "sdk").symlink_to(TS_SDK, target_is_directory=True)
    shutil.copy(TS_SCRIPT, project / TS_SCRIPT.name)
    return project


@pytest.fixture(scope="module")
def mcp_python():
    if not (MCP_PY.exists() and MCP_PY.with_name("agentx-social-mcp").exists()):
        pytest.fail(f"the MCP server is not installed in {MCP_PY.parent} (uv sync in sdk/mcp)")
    return MCP_PY


@pytest_asyncio.fixture
async def db(api):
    conn = await asyncpg.connect(
        host=smoke.DB_HOST, port=int(PG_PORT), user=PG_USER, database=DB_NAME,
    )
    yield conn
    await conn.close()


def _run(argv: list[str], cwd: Path, env: dict[str, str] | None = None) -> tuple[dict, float]:
    """Run one fresh agent; returns its JSON line and the wall-clock seconds it took."""
    started = time.monotonic()
    done = subprocess.run(argv, env=env or {"PATH": "/usr/bin:/bin"}, capture_output=True,
                          text=True, timeout=LIMIT_S, cwd=cwd)
    took = time.monotonic() - started
    assert done.returncode == 0, f"{argv[:2]} failed:\n{done.stdout}\n{done.stderr}"
    return json.loads(done.stdout.strip().splitlines()[-1]), took


async def test_fresh_agent_registers_gets_a_handle_and_posts_four_ways(
    api, db, ts_project, mcp_python, tmp_path,
):
    tag = uuid4().hex[:6]
    node_env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
                "AGENTX_BASE_URL": api}
    mcp_home = tmp_path / "mcp_home"
    mcp_home.mkdir()
    ways = {
        "http": [sys.executable, "-I", "-c", RAW_HTTP, api],
        "python": [sys.executable, "-I", "-c", PYTHON_SDK, str(SDK), api],
        "ts": ["node", TS_SCRIPT.name],
        "mcp": [str(mcp_python), "-I", "-c", MCP, api],
    }
    results: dict[str, dict] = {}
    for way, argv in ways.items():
        handle, title = f"{way}_{tag}", f"Fresh over {way} {tag}"
        args = [f"Fresh{way.title()}{tag}", handle, title]
        if way == "ts":
            out, took = _run(argv + args, ts_project, node_env)
        elif way == "mcp":
            out, took = _run(argv + args + [str(mcp_home)], tmp_path,
                             {"PATH": os.environ.get("PATH", "")})
        else:
            out, took = _run(argv + args, tmp_path)
        print(f"{way}: {took:.1f} s")
        assert took < LIMIT_S, f"{way} took {took:.1f} s"
        assert out["handle"] == handle, way

        row = await db.fetchrow(
            "SELECT a.handle, a.status, p.title, p.visibility, p.status AS post_status "
            "FROM posts p JOIN agents a ON a.agent_did = p.author_did "
            "WHERE p.post_id = $1::uuid AND p.author_did = $2",
            out["post_id"], out["did"],
        )
        assert row is not None, f"{way}: the post is not stored under the new agent"
        assert (row["handle"], row["status"]) == (handle, "ACTIVE"), way
        assert (row["title"], row["visibility"], row["post_status"]) == (title, "PUBLIC", "ACTIVE")
        results[way] = {**out, "seconds": round(took, 1)}

    assert len({r["did"] for r in results.values()}) == 4      # four different agents

    # Second act: the Python agent meets the MCP agent (already joined, credentials on disk).
    mcp_agent = results["mcp"]
    identity = tmp_path / "python_agent.json"
    py, _ = _run([sys.executable, "-I", "-c", PYTHON_SOCIAL, str(SDK), api, f"Meet{tag}",
                  mcp_agent["did"], mcp_agent["handle"], mcp_agent["post_id"], str(identity)],
                 tmp_path)
    assert py["mentions"] == [mcp_agent["did"]]
    assert py["like"]["liked"] is True
    assert mcp_agent["did"] in py["following"]
    assert await db.fetchval(
        "SELECT COUNT(*) FROM messages WHERE sender_agent_did = $1 AND receiver_agent_did = $2",
        py["did"], mcp_agent["did"]) == 1

    py_post = await db.fetchval(
        "SELECT post_id::text FROM posts WHERE author_did = $1 ORDER BY created_at LIMIT 1",
        py["did"])
    mcp, _ = _run([str(mcp_python), "-I", "-c", MCP_SOCIAL, api, str(mcp_home), py["did"],
                   py_post], tmp_path, {"PATH": os.environ.get("PATH", "")})
    assert py["did"] in mcp["mentioned_by"]
    assert mcp["like"]["liked"] is True
    assert mcp["follow"] == {"agent_did": py["did"], "following": True}
    assert mcp["unfollow"]["following"] is False
    assert mcp["block"]["blocked"] is True and mcp["unblock"]["blocked"] is False
    assert mcp["block_again"]["blocked"] is True
    assert await db.fetchval(
        "SELECT COUNT(*) FROM post_likes WHERE post_id = $1::uuid AND agent_did = $2",
        py_post, mcp_agent["did"]) == 1
    assert await db.fetchval(
        "SELECT COUNT(*) FROM agent_blocks WHERE blocker_did = $1 AND blocked_did = $2",
        mcp_agent["did"], py["did"]) == 1

    # The agent the MCP agent blocked can no longer follow or message it.
    blocked, _ = _run([sys.executable, "-I", "-c", PYTHON_BLOCKED, str(SDK), api,
                       str(identity), mcp_agent["did"]], tmp_path)
    assert blocked == {"follow": 403, "message": 403}
