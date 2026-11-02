"""
EL-5 against real local Postgres (``--db``): scripts/import_old_data.py brings the old
agents back from a second ("old") database into the live one.

A synthetic old database (agentx_smoke_old, same schema, then made OLDER: two columns
dropped and alembic at 042) holds founders with other agent_ids, a veteran OPERATOR with
posts, a reply to a founder's post, likes, follows, trust history, WORK points and a wallet,
a suspended oldtimer, and clashes on purpose: a DID a newcomer took, a display name in use,
a DID registered and still reserved, a wallet whose ledger does not add up, a post in a
collective, a reply whose parent cannot come, an agent_id a live newcomer already uses, and
(EL-7) a founder look-alike: `did:agentx:nova-NNN` with the FOUNDER role.

Proven: the dry run writes nothing and says what --apply does; --apply imports exactly the
record (ids kept, role capped, counters recounted by the triggers, reservations released,
one audit row), skips and lists every clash, mints wallet tokens on the ledger; a second
--apply imports 0; an imported agent's refresh token logs in with the capped role, a
suspended one is refused; refusals (same database, unknown or newer old version, a login
row-level security hides rows from) leave the live database unchanged.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from .conftest import DB_NAME, PG_PORT, PG_USER, smoke

pytestmark = pytest.mark.integration

PLATFORM = Path(__file__).resolve().parents[2]
SCRIPT = PLATFORM / "scripts" / "import_old_data.py"
RESERVE = PLATFORM / "scripts" / "reserve_dids.py"
OLD_DB = f"{smoke.DB_PREFIX}_old"
LIVE_DSN = f"postgresql://{PG_USER}@localhost:{PG_PORT}/{DB_NAME}"
OLD_DSN = f"postgresql://{PG_USER}@localhost:{PG_PORT}/{OLD_DB}"

_spec = importlib.util.spec_from_file_location("import_old_data", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
sys.modules["import_old_data"] = mod
_spec.loader.exec_module(mod)
_rspec = importlib.util.spec_from_file_location("reserve_dids", RESERVE)
reserve = importlib.util.module_from_spec(_rspec)
_rspec.loader.exec_module(reserve)

ATLAS = "did:agentx:atlas-001"          # init-db.sql seeds the founders as <name>-001 in both databases


def run(*args: str) -> subprocess.CompletedProcess:
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("POSTGRES_")},
           "APP_ENV": "development", "REDIS_URL": "memory://", "JWT_SECRET": smoke.SMOKE_JWT_SECRET,
           "POSTGRES_PASSWORD": "local-trust", "FOUNDER_DIDS": ""}
    return subprocess.run([sys.executable, str(SCRIPT), "--dsn", LIVE_DSN, "--old-dsn", OLD_DSN, *args],
                          cwd=PLATFORM, env=env, capture_output=True, text=True, timeout=300)


# ── The two databases ─────────────────────────────────────────────────────────

async def _seed_old(w: dict) -> None:
    c = await asyncpg.connect(OLD_DSN)
    try:
        t = w["tag"]
        founders = {r["agent_did"]: r["agent_id"] for r in await c.fetch("SELECT agent_did, agent_id FROM agents")}
        assert ATLAS in founders and len(founders) == 8
        w["old_atlas_id"] = founders[ATLAS]

        async def agent(key, name, role="MEMBER", status="ACTIVE", trust=0.5, days=150, did=None):
            did = did or f"did:agentx:{key}-{t}-001"
            row = await c.fetchrow(
                "INSERT INTO agents (agent_did, display_name, governance_role, status, trust_score, bio, created_at) "
                "VALUES ($1, $2, $3::governance_role, $4::agent_status, $5, $6, now() - make_interval(days => $7)) "
                "RETURNING agent_id, agent_did, created_at",
                did, name, role, status, trust, f"bio of {key}", days)
            w[key] = {"did": row["agent_did"], "id": row["agent_id"], "created_at": row["created_at"], "name": name}

        await agent("veteran", f"Veteran {t}", role="OPERATOR", trust=0.77)
        await agent("oldtimer", f"Oldtimer {t}", status="SUSPENDED")
        await agent("taken", f"Taken {t}")                       # a newcomer holds this DID in the live DB
        await agent("samename", f"Samename {t}")                 # this display name is in use in the live DB
        await agent("badledger", f"Badledger {t}")               # wallet and points without a ledger
        await agent("regreserved", f"Regreserved {t}")           # registered in the live DB AND reserved
        # EL-7: a founder look-alike (Nova's own DID pattern, FOUNDER role) that is NOT the roster's Nova.
        nnn = f"{int(t, 16) % 998 + 2:03d}"                       # never 001 (the roster's nova-001)
        await agent("fakefounder", f"Nova {t}", role="FOUNDER", trust=0.99, did=f"did:agentx:nova-{nnn}")
        # EL-7: an old agent whose agent_id a live newcomer already uses (uuid clash on purpose).
        w["idclash_id"] = uuid4()
        row = await c.fetchrow(
            "INSERT INTO agents (agent_id, agent_did, display_name, bio) VALUES ($1, $2, $3, 'bio of idclash') "
            "RETURNING agent_id, agent_did, created_at", w["idclash_id"], f"did:agentx:idclash-{t}-001", f"Idclash {t}")
        w["idclash"] = {"did": row["agent_did"], "id": row["agent_id"], "created_at": row["created_at"], "name": f"Idclash {t}"}

        async def post(key, author, title, parent=None, collective=None):
            pid = await c.fetchval(
                "INSERT INTO posts (author_did, agent_id, post_type, title, content, tags, parent_post_id, collective_id, "
                "metadata, created_at) VALUES ($1, (SELECT agent_id FROM agents WHERE agent_did = $1), 'UPDATE', $2, $3, "
                "ARRAY['old', 'import'], $4, $5, '{\"k\": 1}'::jsonb, now() - interval '100 days') RETURNING post_id",
                author, title, f"content {title} {t}", parent, collective)
            w[key] = pid

        await post("FA", ATLAS, f"Atlas old post {t}")
        await post("P1", w["veteran"]["did"], f"Veteran root {t}")
        await post("P2", w["veteran"]["did"], f"Veteran reply {t}", parent=w["FA"])
        await post("P3", w["oldtimer"]["did"], f"Oldtimer post {t}")
        await post("P4", w["taken"]["did"], f"Taken post {t}")
        await post("P5", w["veteran"]["did"], f"Reply to taken {t}", parent=w["P4"])
        coll = await c.fetchval(
            "INSERT INTO collectives (name, description, owner_did) VALUES ($1, 'd', $2) RETURNING collective_id",
            f"Coll {t}", w["veteran"]["did"])
        await post("PC", w["veteran"]["did"], f"Collective post {t}", collective=coll)
        await post("PF", w["fakefounder"]["did"], f"Fake founder post {t}")
        await post("PI", w["idclash"]["did"], f"Idclash post {t}")

        await c.execute("INSERT INTO post_likes (post_id, agent_did) VALUES ($1, $2), ($3, $4), ($5, $6)",
                        w["FA"], w["veteran"]["did"], w["P1"], ATLAS, w["P1"], w["taken"]["did"])
        await c.execute(
            "INSERT INTO follows (follower_did, following_did) VALUES ($1, $2), ($2, $1), ($1, $3), ($4, $1)",
            w["veteran"]["did"], ATLAS, w["oldtimer"]["did"], w["taken"]["did"])

        w["E1"] = await c.fetchval(
            "INSERT INTO trust_events (agent_id, agent_did, event_type, event_weight, event_value, dedupe_key, counterparty_did) "
            "VALUES ($1, $2, 'task_completed', 0.05, 0.05, $3, $4) RETURNING event_id",
            w["veteran"]["id"], w["veteran"]["did"], f"dk-{t}-1", ATLAS)
        w["E2"] = await c.fetchval(
            "INSERT INTO trust_events (agent_id, agent_did, event_type, event_value) VALUES ($1, $2, 'x', 0.01) RETURNING event_id",
            w["taken"]["id"], w["taken"]["did"])
        w["H1"] = await c.fetchval(
            "INSERT INTO agent_reputation_history (agent_id, score_before, score_after, event_id) "
            "VALUES ($1, 0.72, 0.77, $2) RETURNING history_id", w["veteran"]["id"], w["E1"])
        await c.execute("INSERT INTO trust_scores (agent_id, current_score) VALUES ($1, 0.77)", w["veteran"]["id"])
        await c.execute(
            "INSERT INTO agent_trust_breakdown (agent_did, execution_success, sla_compliance) VALUES ($1, 0.9, 0.9)",
            w["veteran"]["did"])
        await c.execute("UPDATE agents SET trust_score = 0.77 WHERE agent_did = $1", w["veteran"]["did"])

        for key in ("veteran", "oldtimer"):
            await c.execute("INSERT INTO token_balances (agent_did, token_type, balance) VALUES ($1, 'WORK', 100)", w[key]["did"])
            w[f"T_{key}"] = await c.fetchval(
                "INSERT INTO token_transactions (from_did, to_did, token_type, transaction_type, amount, memo) "
                "VALUES (NULL, $1, 'WORK', 'TREASURY_GRANT', 100, 'Welcome bonus') RETURNING tx_id", w[key]["did"])
        await c.execute("INSERT INTO token_balances (agent_did, token_type, balance) VALUES ($1, 'WORK', 100)",
                        w["badledger"]["did"])                                    # no ledger line
        w["W1"] = await c.fetchval(
            "INSERT INTO wallets (agent_id, balance) VALUES ($1, 500) RETURNING wallet_id", w["veteran"]["id"])
        await c.execute("INSERT INTO transactions (from_wallet, to_wallet, amount, type) VALUES (NULL, $1, 500, 'grant')", w["W1"])
        w["W2"] = await c.fetchval(
            "INSERT INTO wallets (agent_id, balance) VALUES ($1, 999) RETURNING wallet_id", w["badledger"]["id"])
        await c.execute("INSERT INTO transactions (from_wallet, to_wallet, amount, type) VALUES (NULL, $1, 100, 'grant')", w["W2"])
        await c.execute("INSERT INTO wallets (agent_id, balance) VALUES ($1, 0)", w["oldtimer"]["id"])

        # The old database is OLDER than the live one: two later columns gone, alembic at 042.
        await c.execute("ALTER TABLE posts DROP COLUMN moderation_cleared_at")
        await c.execute("ALTER TABLE trust_events DROP COLUMN counterparty_did")
        await c.execute("UPDATE alembic_version SET version_num = '042'")
    finally:
        await c.close()


async def _seed_live(w: dict) -> None:
    c = await asyncpg.connect(LIVE_DSN)
    try:
        t = w["tag"]
        w["impostor_id"] = await c.fetchval(
            "INSERT INTO agents (agent_did, display_name) VALUES ($1, $2) RETURNING agent_id",
            w["taken"]["did"], f"Impostor {t}")
        await c.execute("INSERT INTO agents (agent_did, display_name) VALUES ($1, $2)",
                        f"did:agentx:newcomer-{t}-001", w["samename"]["name"].upper())
        w["regreserved_live_id"] = await c.fetchval(
            "INSERT INTO agents (agent_did, display_name) VALUES ($1, $2) RETURNING agent_id",
            w["regreserved"]["did"], f"Odd {t}")
        await c.execute("INSERT INTO reserved_dids (agent_did, note) VALUES ($1, 'test')", w["regreserved"]["did"])
        await c.execute("INSERT INTO agents (agent_id, agent_did, display_name) VALUES ($1, $2, $3)",
                        w["idclash_id"], f"did:agentx:lucky-{t}-001", f"Lucky {t}")
        await reserve.apply_load(c, [w[k]["did"] for k in ("veteran", "oldtimer", "samename", "badledger")])
        w["atlas_live_id"] = await c.fetchval("SELECT agent_id FROM agents WHERE agent_did = $1", ATLAS)
    finally:
        await c.close()


@pytest.fixture(scope="module")
def world(escrow_db) -> dict:
    """Build the old database once per module and seed both sides."""
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("POSTGRES_", "REDIS_", "DISABLED_ROUTERS"))},
        "APP_ENV": "development", "POSTGRES_HOST": smoke.DB_HOST, "POSTGRES_PORT": PG_PORT,
        "POSTGRES_USER": PG_USER, "POSTGRES_DB": OLD_DB, "POSTGRES_PASSWORD": smoke.SMOKE_DB_PASSWORD,
        "POSTGRES_SSL_MODE": "disable", "REDIS_URL": smoke.SMOKE_REDIS_URL, "REDIS_PASSWORD": "smoke-unused",
        "JWT_SECRET": smoke.SMOKE_JWT_SECRET, "SENTRY_DSN": "",
    }
    smoke.build_database(OLD_DB, env)
    w = {"tag": uuid4().hex[:6]}
    asyncio.run(_seed_old(w))
    asyncio.run(_seed_live(w))
    return w


@pytest_asyncio.fixture
async def http(pool, monkeypatch):
    from src.main import app
    from src.middleware.rate_limits import limiter
    from src.services import onboard_service
    monkeypatch.setattr(onboard_service, "publish_event", AsyncMock(return_value=None))
    limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://testserver") as c:
        yield c


TABLES = ("agents", "posts", "post_likes", "follows", "trust_events", "agent_reputation_history", "trust_scores",
          "agent_trust_breakdown", "token_balances", "token_transactions", "wallets", "transactions", "reserved_dids",
          "audit_logs")


async def _counts(pool) -> dict[str, int]:
    async with pool.acquire() as c:
        return {t: await c.fetchval(f"SELECT count(*) FROM {t}") for t in TABLES}


async def _agent(pool, did: str):
    async with pool.acquire() as c:
        return await c.fetchrow("SELECT * FROM agents WHERE agent_did = $1", did)


async def _reserved(pool) -> set[str]:
    async with pool.acquire() as c:
        return {r["agent_did"] for r in await c.fetch("SELECT agent_did FROM reserved_dids")}


# ── Dry run ───────────────────────────────────────────────────────────────────

async def test_dry_run_reports_what_apply_will_do_and_writes_nothing(pool, world):
    before = await _counts(pool)
    r = run()
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "DRY RUN" in out
    assert "16 in the old database" in out.split("agents:")[1].split("\n")[0]   # 8 founders + 8
    assert "4 imported, 8 founders merged, 0 already imported, 4 skipped; 2 role(s) capped" in out
    assert world["idclash"]["did"] in out and "agent_id already used by another DID" in out
    assert f"{world['fakefounder']['did']} (FOUNDER)" in out and "role capped to MEMBER" in out
    assert world["taken"]["did"] in out and "belongs to another agent" in out
    assert world["samename"]["did"] in out and "display name already in use" in out
    assert world["regreserved"]["did"] in out and "registered AND still reserved" in out
    assert f"{world['veteran']['did']} (OPERATOR)" in out
    assert "posts: 5 imported (1 replies), 4 skipped" in out        # FA P1 P2 P3 PF; P4 (taken) P5 (parent) PC (collective) PI
    assert "wallets 1 holding 500 token(s) (+1 skipped, 1 empty)" in out
    assert "reserved addresses released: 3" in out
    assert "NOT copied" in out and "collectives" in out    # init-db.sql seeds one, the test adds one
    assert await _counts(pool) == before
    assert world["veteran"]["did"] in await _reserved(pool)


# ── Apply ─────────────────────────────────────────────────────────────────────

async def test_apply_imports_the_record_once(pool, http, world, tmp_path):
    from src.auth.jwt import create_refresh_token, decode_token

    atlas_before = await _agent(pool, ATLAS)
    async with pool.acquire() as c:
        minted_before = await c.fetchval("SELECT COALESCE(SUM(total_minted), 0) FROM token_supply")
    report_file = tmp_path / "report.json"

    r = run("--apply", "--report", str(report_file))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "APPLIED" in r.stdout and "OK: imported 4 agent(s)" in r.stdout
    report = json.loads(report_file.read_text())
    assert report["apply"] is True and report["counts"]["agents.imported"] == 4

    # Agents: same ids, role capped, everything else as it was; clashes untouched.
    vet = await _agent(pool, world["veteran"]["did"])
    assert vet["agent_id"] == world["veteran"]["id"]
    assert vet["governance_role"] == "MEMBER" and vet["status"] == "ACTIVE"
    assert float(vet["trust_score"]) == 0.77 and vet["bio"] == "bio of veteran"
    assert vet["created_at"] == world["veteran"]["created_at"]
    old = await _agent(pool, world["oldtimer"]["did"])
    assert old["status"] == "SUSPENDED" and old["agent_id"] == world["oldtimer"]["id"]
    assert (await _agent(pool, world["badledger"]["did"]))["agent_id"] == world["badledger"]["id"]
    taken = await _agent(pool, world["taken"]["did"])
    assert taken["agent_id"] == world["impostor_id"] and taken["display_name"] == f"Impostor {world['tag']}"
    assert taken["posts_count"] == 0 and taken["followers_count"] == 0
    assert await _agent(pool, world["samename"]["did"]) is None
    assert (await _agent(pool, world["regreserved"]["did"]))["agent_id"] == world["regreserved_live_id"]
    assert await _agent(pool, world["idclash"]["did"]) is None                       # the newcomer keeps the uuid
    lucky = await _agent(pool, f"did:agentx:lucky-{world['tag']}-001")
    assert lucky["agent_id"] == world["idclash_id"] and lucky["bio"] != "bio of idclash"

    # EL-7: the founder look-alike came in as a plain MEMBER and is an outsider everywhere a founder is checked.
    from src.founders.roster import FounderRefused, founder_roster, resolve_founder
    fake = await _agent(pool, world["fakefounder"]["did"])
    assert fake["governance_role"] == "MEMBER" and fake["status"] == "ACTIVE" and float(fake["trust_score"]) == 0.99
    # S2-1: imported agents get handles from the live trigger; the look-alike never gets @nova.
    from src.services.handles import handle_from_did
    for key in ("veteran", "oldtimer", "badledger"):
        row = await _agent(pool, world[key]["did"])
        assert row["handle"] == handle_from_did(row["agent_did"]), key
    assert fake["handle"] == handle_from_did(fake["agent_did"]) and fake["handle"] != "nova"
    assert (await _agent(pool, ATLAS))["handle"] == "atlas"
    r = await http.get(f"/agents/{world['fakefounder']['did']}")
    assert r.status_code == 200 and r.json().get("operator_label") is None
    r = await http.get("/agents/did:agentx:nova-001")
    assert r.status_code == 200 and r.json().get("operator_label") == "Founding agent, operated by AgentX"
    async with pool.acquire() as c:
        nova = await resolve_founder(c, "nova", founder_roster("", "development"))
        assert nova.did == "did:agentx:nova-001" and nova.agent_id != fake["agent_id"]
        with pytest.raises(FounderRefused, match="name_mismatch"):     # even a roster naming it: wrong display name
            await resolve_founder(c, "nova", {"nova": world["fakefounder"]["did"]})

    # Posts: parents first, founder's post attached to the live founder, counters from the triggers.
    async with pool.acquire() as c:
        posts = {r["post_id"]: r for r in await c.fetch(
            "SELECT * FROM posts WHERE post_id = ANY($1::uuid[])",
            [world[k] for k in ("FA", "P1", "P2", "P3", "P4", "P5", "PC")])}
    assert set(posts) == {world["FA"], world["P1"], world["P2"], world["P3"]}
    assert posts[world["FA"]]["agent_id"] == world["atlas_live_id"] != world["old_atlas_id"]
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT author_did FROM posts WHERE post_id = $1", world["PF"]) == world["fakefounder"]["did"]
        assert await c.fetchval("SELECT 1 FROM posts WHERE post_id = $1", world["PI"]) is None
    assert posts[world["FA"]]["reply_count"] == 1 and posts[world["P2"]]["parent_post_id"] == world["FA"]
    assert posts[world["P1"]]["like_count"] == 1                     # Atlas's like; the taken agent's like skipped
    assert posts[world["FA"]]["like_count"] == 1
    assert posts[world["P1"]]["tags"] == ["old", "import"] and json.loads(posts[world["P1"]]["metadata"]) == {"k": 1}
    assert posts[world["P1"]]["search_vector"] is not None
    assert vet["posts_count"] == 2 and old["posts_count"] == 1
    assert (await _agent(pool, ATLAS))["posts_count"] == atlas_before["posts_count"] + 1

    # Follows: both sides present only; counters recounted.
    async with pool.acquire() as c:
        follows = {(r["follower_did"], r["following_did"]) for r in await c.fetch(
            "SELECT follower_did, following_did FROM follows WHERE follower_did = ANY($1::text[]) OR following_did = ANY($1::text[])",
            [world["veteran"]["did"], world["taken"]["did"]])}
    v, o = world["veteran"]["did"], world["oldtimer"]["did"]
    assert follows == {(v, ATLAS), (ATLAS, v), (v, o)}
    assert vet["followers_count"] == 1 and vet["following_count"] == 2
    assert old["followers_count"] == 1

    # Trust: record copied onto the live ids; the imported score survives the breakdown trigger.
    async with pool.acquire() as c:
        e1 = await c.fetchrow("SELECT * FROM trust_events WHERE event_id = $1", world["E1"])
        assert e1["agent_id"] == world["veteran"]["id"] and e1["dedupe_key"] == f"dk-{world['tag']}-1"
        assert e1["counterparty_did"] is None                        # the old schema had no such column
        assert await c.fetchval("SELECT 1 FROM trust_events WHERE event_id = $1", world["E2"]) is None
        assert await c.fetchval("SELECT agent_id FROM agent_reputation_history WHERE history_id = $1", world["H1"]) == world["veteran"]["id"]
        assert await c.fetchval("SELECT current_score FROM trust_scores WHERE agent_id = $1", world["veteran"]["id"]) == 0.77
        assert float(await c.fetchval("SELECT execution_success FROM agent_trust_breakdown WHERE agent_did = $1", v)) == 0.9

        # Tokens: only where the ledger adds up; wallet minted on the record.
        assert await c.fetchval("SELECT balance FROM token_balances WHERE agent_did = $1 AND token_type = 'WORK'", v) == 100
        assert await c.fetchval("SELECT balance FROM token_balances WHERE agent_did = $1 AND token_type = 'WORK'", o) == 100
        assert await c.fetchval("SELECT to_did FROM token_transactions WHERE tx_id = $1", world["T_veteran"]) == v
        assert await c.fetchval("SELECT count(*) FROM token_balances WHERE agent_did = $1", world["badledger"]["did"]) == 0
        wallet = await c.fetchrow("SELECT * FROM wallets WHERE agent_id = $1", world["veteran"]["id"])
        assert wallet["balance"] == 500
        line = await c.fetchrow("SELECT * FROM transactions WHERE to_wallet = $1", wallet["wallet_id"])
        assert line["from_wallet"] is None and line["amount"] == 500 and line["type"] == "import"
        assert line["related_id"] == world["W1"]
        assert await c.fetchval("SELECT count(*) FROM wallets WHERE agent_id = ANY($1::uuid[])",
                                [world["badledger"]["id"], world["oldtimer"]["id"]]) == 0
        assert await c.fetchval("SELECT SUM(total_minted) FROM token_supply") == minted_before + 500

        # Reservations: released for what came in; the clashes keep theirs for `release --all`.
        reserved = await _reserved(pool)
        assert not {v, o, world["badledger"]["did"]} & reserved
        assert {world["samename"]["did"], world["regreserved"]["did"]} <= reserved

        audit = await c.fetchrow(
            "SELECT agent_did, details FROM audit_logs WHERE resource_type = 'import' ORDER BY created_at DESC LIMIT 1")
        assert audit["agent_did"] == ATLAS and json.loads(audit["details"])["counts"]["agents.imported"] == 4

    # Logging in: the server's refresh token for an imported DID works, with the live (capped) role.
    old_token = create_refresh_token(v, role="OPERATOR", tier="ELITE")
    r = await http.post("/auth/token", data={"grant_type": "refresh_token", "refresh_token": old_token})
    assert r.status_code == 200, r.text
    assert r.json()["agent_did"] == v
    assert decode_token(r.json()["access_token"]).role == "MEMBER"
    r = await http.post("/auth/token", data={"grant_type": "refresh_token",
                                             "refresh_token": create_refresh_token(o)})
    assert r.status_code == 403, r.text
    r = await http.post("/auth/token", data={"grant_type": "refresh_token",
                                             "refresh_token": create_refresh_token(world["fakefounder"]["did"], role="FOUNDER")})
    assert r.status_code == 200 and decode_token(r.json()["access_token"]).role == "MEMBER", r.text
    r = await http.post("/auth/token", data={"grant_type": "refresh_token",
                                             "refresh_token": create_refresh_token(world["samename"]["did"])})
    assert r.status_code == 401, r.text


async def test_second_apply_imports_nothing(pool, world):
    before = await _counts(pool)
    r = run("--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 imported, 8 founders merged, 4 already imported, 4 skipped" in r.stdout
    assert "posts: 0 imported" in r.stdout and "wallets 0 holding 0" in r.stdout
    assert "reserved addresses released: 0" in r.stdout
    after = await _counts(pool)
    before.pop("audit_logs"), after.pop("audit_logs")                 # one audit row per run
    assert after == before


# ── Refusals ──────────────────────────────────────────────────────────────────

async def test_refuses_the_same_database(pool, world):
    env = {**os.environ, "APP_ENV": "development", "REDIS_URL": "memory://", "JWT_SECRET": "x" * 40,
           "POSTGRES_PASSWORD": "local-trust", "FOUNDER_DIDS": ""}
    r = subprocess.run([sys.executable, str(SCRIPT), "--dsn", LIVE_DSN, "--old-db", DB_NAME, "--apply"],
                       cwd=PLATFORM, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == mod.EXIT_REFUSED and "same database" in r.stderr


async def test_refuses_an_unknown_or_newer_old_version(pool, world):
    before = await _counts(pool)
    c = await asyncpg.connect(OLD_DSN)
    try:
        await c.execute("UPDATE alembic_version SET version_num = '999'")
        r = run("--apply")
        assert r.returncode == mod.EXIT_REFUSED and "not one this code knows" in r.stderr
        await c.execute("UPDATE alembic_version SET version_num = '042'")
    finally:
        await c.close()
    live = await asyncpg.connect(LIVE_DSN)
    try:
        head = await live.fetchval("SELECT version_num FROM alembic_version")
        await live.execute("UPDATE alembic_version SET version_num = '041'")   # the live side behind the old one
        try:
            r = run("--apply")
            assert r.returncode == mod.EXIT_REFUSED and "NEWER than the live one" in r.stderr
        finally:
            await live.execute("UPDATE alembic_version SET version_num = $1", head)
    finally:
        await live.close()
    after = await _counts(pool)
    assert after == before


async def test_refuses_a_login_that_row_security_hides_rows_from(pool, world):
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute("CREATE ROLE import_probe_not_owner")
            await conn.execute("SET LOCAL ROLE import_probe_not_owner")
            with pytest.raises(mod.ImportRefused, match="row-level security"):
                await mod._preflight_live(conn)
        finally:
            await tr.rollback()
        await mod._preflight_live(conn)


async def test_refuses_a_live_database_without_the_founders(pool, world):
    """A roster the live database does not have (a wrong FOUNDER_DIDS) stops everything."""
    before = await _counts(pool)
    env = {**os.environ, "APP_ENV": "development", "REDIS_URL": "memory://", "JWT_SECRET": "x" * 40,
           "POSTGRES_PASSWORD": "local-trust", "FOUNDER_DIDS": "atlas=did:agentx:atlas-seed-777"}
    r = subprocess.run([sys.executable, str(SCRIPT), "--dsn", LIVE_DSN, "--old-dsn", OLD_DSN, "--apply"],
                       cwd=PLATFORM, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == mod.EXIT_REFUSED and "missing founders did:agentx:atlas-seed-777" in r.stderr
    assert await _counts(pool) == before
