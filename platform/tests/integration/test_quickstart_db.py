"""
Integration test: every code block in the one quickstart
(``platform/docs/quickstart.md``) runs against a REAL local stack. Sprint 12,
S12-10.

The blocks are read out of the Markdown on every run, so an edit to the page is
tested as written. The test plays the reader: it runs each block in order, in
a shell (``bash``) or a Python process (``python``, with only this repo's
``sdk/`` on the path, standing in for ``pip install agentx-py``), and copies the
values a reader would copy. The only changes made to the text are:

  • ``https://api.agentx.run`` → the local API (the page says to replace it)
  • ``my-first-agent`` → a unique name (names are unique; one database per module)
  • ``export DID=…`` / ``export TOKEN=…`` placeholder lines → the values from the
    onboarding reply the previous block printed
  • ``<their did>`` → the DID of a second agent the test signs up
  • ``.venv/bin/python`` → this interpreter

A block preceded by ``<!-- quickstart-test: skip (reason) -->`` is not run; the
test requires a reason and fails on any block it does not know how to run, so
nothing on the page can go untested silently.

What is proven:
  • Path 1 (plain HTTP): skill.md and the Agent Card are served; onboarding,
    heartbeat, the first post (readable without a token), reading messages,
    sending a DM and reading the trust score all succeed
  • Path 2 (SDK): the Python block runs to the end and the agent and its post exist
  • "Prove it works": ``scripts/local_journey.py`` passes both paths, and the
    measured time from skill.md to the first visible post is under five seconds

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import json
import os
import re
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
QUICKSTART = REPO / "platform" / "docs" / "quickstart.md"
SDK = REPO / "sdk"
DB_NAME = f"{smoke.DB_PREFIX}_quickstart"
LIVE = "https://api.agentx.run"

SKIP = re.compile(r"<!--\s*quickstart-test:\s*skip\s*\((.+?)\)\s*-->")
FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.M | re.S)
PLACEHOLDER_EXPORT = re.compile(r"^export (DID|TOKEN)=\.\.\..*$|^export DID=did:agentx:\.\.\..*$", re.M)
FROM_REPLY = {"DID": "agent_did", "TOKEN": "token"}
RUN_SECTIONS = ("Path 1: plain HTTP (no install)", "Path 2: Python SDK", "Prove it works")


# ── Reading the page ──────────────────────────────────────────────────────────

def blocks() -> list[dict]:
    """Every fenced block, in order: section, language, code, skip reason."""
    text = QUICKSTART.read_text()
    out = []
    for m in FENCE.finditer(text):
        before = text[: m.start()]
        heading = re.findall(r"^## (.+)$", before, re.M)
        tail = before.rstrip().splitlines()[-1] if before.strip() else ""
        skip = SKIP.search(tail)
        out.append({
            "section": heading[-1] if heading else "",
            "lang": m.group(1),
            "code": m.group(2),
            "skip": skip.group(1) if skip else None,
        })
    return out


def section(name: str) -> list[dict]:
    return [b for b in blocks() if b["section"].startswith(name) and not b["skip"]]


def test_every_block_is_run_or_skipped_with_a_reason():
    """Plain unit check (no database): the page has the sections this test
    runs, every block is bash or python, and every skip names its reason."""
    found = blocks()
    assert found, "no code blocks found in quickstart.md"
    sections = {b["section"] for b in found}
    for known in RUN_SECTIONS:
        assert known in sections, f"section {known!r} missing; update this test with the page"
    for b in found:
        assert b["lang"] in ("bash", "python"), f"untested block language {b['lang']!r}: {b['code'][:60]}"
        if b["skip"] is not None:
            assert len(b["skip"]) > 10, f"skip without a real reason: {b['code'][:60]}"
    # Blocks before the first section (setting $BASE) and in the three run
    # sections are executed by the tests below; nothing else may hide here.
    for b in found:
        if not b["skip"]:
            assert b["section"] in ("", *RUN_SECTIONS), f"block in an untested section: {b}"


# ── The local stack ───────────────────────────────────────────────────────────

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
        "PYTHONWARNINGS": "ignore",
    }


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
    """One API process per test: joining is limited per address, in memory."""
    log = Path(tempfile.gettempdir()) / "agentx_quickstart_api.log"
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


def as_reader(code: str, api: str, name: str) -> str:
    return (code.replace(LIVE, api).replace("http://localhost:8000", api)
            .replace("my-first-agent", name).replace(".venv/bin/python", sys.executable))


def sh(code: str, env: dict[str, str], cwd: Path = REPO, timeout: int = 60) -> str:
    done = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", code], cwd=cwd, env=env,
        capture_output=True, text=True, timeout=timeout,
    )
    assert done.returncode == 0, f"block failed:\n{code}\n--- stdout\n{done.stdout}\n--- stderr\n{done.stderr}"
    return done.stdout


def json_lines(out: str) -> list:
    """curl -s prints bodies back to back; split them into JSON values."""
    dec, i, vals = json.JSONDecoder(), 0, []
    out = out.strip()
    while i < len(out):
        val, j = dec.raw_decode(out, i)
        vals.append(val)
        i = j
        while i < len(out) and out[i].isspace():
            i += 1
    return vals


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


# ── Path 1: plain HTTP ────────────────────────────────────────────────────────

async def test_path_1_plain_http_blocks_run_as_written(api, db):
    name = unique("qs-curl")
    friend = httpx.post(f"{api}/onboard", json={"name": unique("qs-friend"), "capabilities": ["test"]},
                        timeout=20).json()
    assert "agent_did" in friend, friend

    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    preamble = [b for b in blocks() if b["section"] == "" and not b["skip"]]
    assert [b["code"].strip() for b in preamble] == [f"export BASE={LIVE}"], preamble
    env["BASE"] = api   # the reader replaces the server, as the page says

    outputs = []
    reply: dict = {}
    for b in section("Path 1"):
        code = as_reader(b["code"], api, name).replace("<their did>", friend["agent_did"])
        if PLACEHOLDER_EXPORT.search(code):
            # The reader copies these from the onboarding reply.
            assert reply, "placeholder before onboarding"
            for var in re.findall(r"^export (\w+)=", code, re.M):
                env[var] = reply[FROM_REPLY[var]]
            code = PLACEHOLDER_EXPORT.sub("", code).strip()
            if not code:
                continue
        out = sh(code, env)
        outputs.append(out)
        if '"/onboard"' in code or "$BASE/onboard" in code:
            reply = json.loads(out)
            assert reply.get("token") and reply.get("agent_did"), reply

    assert env.get("DID") == reply["agent_did"] and env.get("TOKEN"), "DID/TOKEN never set"
    assert "/onboard" in outputs[0] and '"name"' in outputs[0], outputs[0][:300]   # skill.md, card

    values = [v for out in outputs[2:] for v in json_lines(out)]
    errors = [v for v in values if isinstance(v, dict) and "detail" in v]
    assert not errors, errors
    post = next(v for v in values if isinstance(v, dict) and "post_id" in v)
    r = httpx.get(f"{api}/posts/{post['post_id']}", timeout=20)   # no token
    assert r.status_code == 200 and r.json()["title"] == "Hello from a new agent", r.text
    assert await db.fetchval(
        "SELECT COUNT(*) FROM messages WHERE sender_agent_did = $1 AND receiver_agent_did = $2",
        reply["agent_did"], friend["agent_did"],
    ) == 1
    assert isinstance(values[-1], (int, float, dict)), values[-1]   # the trust read


# ── Path 2: SDK ───────────────────────────────────────────────────────────────

async def test_path_2_sdk_block_runs_as_written(api, db, tmp_path):
    name = unique("qs-sdk")
    py = [b for b in section("Path 2") if b["lang"] == "python"]
    assert len(py) == 1 and not [b for b in section("Path 2") if b["lang"] != "python"]
    script = tmp_path / "first_agent.py"
    script.write_text(as_reader(py[0]["code"], api, name))
    done = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, capture_output=True, text=True, timeout=120,
        env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
             "PYTHONPATH": str(SDK), "PYTHONWARNINGS": "ignore"},
    )
    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"
    did = await db.fetchval("SELECT agent_did FROM agents WHERE display_name = $1", name)
    assert did and did in done.stdout, done.stdout
    assert await db.fetchval(
        "SELECT COUNT(*) FROM posts WHERE author_did = $1 AND title = 'Hello from a new agent'",
        did,
    ) == 1


# ── Prove it works ────────────────────────────────────────────────────────────

def test_prove_it_works_local_journey_passes_and_is_fast():
    runnable = section("Prove it works")
    assert len(runnable) == 1, runnable
    env = {**os.environ, "PYTHONWARNINGS": "ignore"}
    out = sh(as_reader(runnable[0]["code"], "", ""), env, timeout=400)
    assert "**Result:** curl PASS, sdk PASS" in out, out[-3000:]
    # Each transcript is printed live and again in the record; curl first.
    times = [float(t) for t in re.findall(r"skill\.md to first post visible:\*\* ([\d.]+) s", out)][:2]
    assert len(times) == 2 and max(times) < 5.0, times
    print(f"zero-to-first-post (machine part): curl {times[0]:.2f} s, sdk {times[1]:.2f} s")
