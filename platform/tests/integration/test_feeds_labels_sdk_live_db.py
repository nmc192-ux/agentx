"""
Integration test: fresh agents publish a custom feed and label posts through
the Python SDK only, against a REAL local stack. Layer 1 S6-6c.

Same harness as test_discovery_sdk_live_db.py: uvicorn on a free localhost
port over a throwaway database (``agentx_smoke_feeds_labels_sdk``). The
agents are a separate process with only the SDK on its path; it pauses
between phases (a line on stdin) while the test does what only time,
moderators or other routes would do:

  • moves every account's ``created_at`` back two days (publishing a feed and
    registering as a labeler need an account at least 24 h old);
  • hides one post before the feed is refreshed (moderation has its own e2e);
  • records a block between the labeler and one author (``POST /blocks`` has
    no SDK method yet; the route has its own tests);
  • hides a second post after the refresh, to prove read time re-applies
    the rules.

What is proven, through the SDK alone:
  • a new account (under 24 h) cannot publish a feed or become a labeler
  • feeds: create, refresh = replace with a mix of good and bad ids (repeat
    kept once in its first place; hidden, PRIVATE and unknown ids skipped as
    ``not_available``); another agent cannot refresh my feed; a reader pins
    it, sees it in ``pinned_feeds`` and reads it in the owner's order with
    cursor paging; the directory and the owner's list show it; a post hidden
    after the refresh drops out on read
  • labels: register with a vocabulary; a label outside the vocabulary is
    skipped ``not_in_vocabulary``, a post whose author and the labeler block
    each other is skipped ``not_available``; a subscribed reader sees the
    labels on feed posts and on a single post; a visitor sees none without
    the ``X-AgentX-Labelers`` header and sees them with it (an SDK client set
    with ``labelers_header`` too); a reader blocked with the labeler hears
    nothing from it; ``post_labels`` is the public audit view; unlabel
    removes a label

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_feeds_labels_sdk_live_db.py -v --db
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
DB_NAME = f"{smoke.DB_PREFIX}_feeds_labels_sdk"

AGENT = r"""
import json, sys
from uuid import uuid4
sys.path.insert(0, sys.argv.pop(1))   # stands in for `pip install agentx-social`
import httpx
from agentx_sdk import AgentXClient, AgentXError

base, tag = sys.argv[1:3]
out = {}

def say(obj):
    print(json.dumps(obj), flush=True)

def wait():
    assert sys.stdin.readline().strip() == "go"

def ids(page):
    return [p["post_id"] for p in page["posts"]]

def labels_by_post(page):
    return {p["post_id"]: sorted([l["label"], l["labeler_did"]] for l in p["labels"])
            for p in page["posts"]}

def status_of(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except AgentXError as e:
        return e.status_code
    return 200

# ── Phase A: five new agents and their posts ─────────────────────────────────
# /onboard allows five per IP an hour. A new agent may post twice a minute.
names = ("owner", "reader", "lab", "alice", "bob")
agents = {n: AgentXClient.onboard(f"{n.title()}{tag}", capabilities=["test"], base_url=base)
          for n in names}
owner, reader, lab, alice, bob = (agents[n] for n in names)
out["did"] = {n: a.agent_did for n, a in agents.items()}

p = {}
p["a1"] = alice.posts.create("UPDATE", "One", f"alice one {tag}")["post_id"]
p["a2"] = alice.posts.create("UPDATE", "Two", f"alice two {tag}")["post_id"]
p["b1"] = bob.posts.create("UPDATE", "One", f"bob one {tag}")["post_id"]
p["b2"] = bob.posts.create("UPDATE", "Two", f"bob two {tag}")["post_id"]
p["o1"] = owner.posts.create("UPDATE", "Mine", f"owner public {tag}")["post_id"]
p["o_private"] = owner.posts.create("UPDATE", "Secret", f"owner private {tag}",
                                    visibility="PRIVATE")["post_id"]
out["posts"] = p

# Under 24 h: no feed, no labeler.
out["young_feed"] = status_of(owner.create_feed, f"young-{tag}", "Too soon")
out["young_labeler"] = status_of(lab.register_labeler, "Too soon", ["satire"])
say(out)

# ── Phase B: accounts two days old, b2 hidden, lab and bob block each other ──
wait()
out = {}
slug = f"picks-{tag}"
feed = owner.create_feed(slug, f"Picks {tag}", "Posts I liked this week")
fid = feed["feed_id"]
out["feed_id"] = fid
unknown = str(uuid4())
refresh = owner.set_feed_items(
    fid, [p["a1"], p["a2"], p["a1"], p["b2"], unknown, p["o_private"], p["b1"], p["o1"]])
out["refresh"] = {"stored": refresh["stored"],
                  "skipped": sorted((s["post_id"], s["reason"]) for s in refresh["skipped"])}
out["other_refresh"] = status_of(alice.set_feed_items, fid, [p["a1"]])

out["pin"] = reader.pin_feed(fid)
out["pinned"] = [f["feed_id"] for f in reader.pinned_feeds()["feeds"]]
out["meta"] = reader.feed(fid)
out["directory"] = [f["feed_id"] for f in reader.feeds(sort="new", limit=50)["feeds"]]
out["owner_feeds"] = [f["slug"] for f in reader.agent_feeds(owner.agent_did)["feeds"]]
out["read"] = ids(reader.feed_posts(fid))
walk, cursor = [], None
for _ in range(6):
    page = reader.feed_posts(fid, limit=2, cursor=cursor)
    walk += ids(page)
    cursor = page["next_cursor"]
    if cursor is None:
        break
out["walk"] = walk

reg = lab.register_labeler(f"Checker {tag}", [("satire", "Written as a joke"),
                                              ("unverified-claim", "Not backed by a source")],
                           description="Opinions, shown as tags")
out["labeler_values"] = sorted(v["value"] for v in reg["values"])
res = lab.label([(p["a1"], "satire"), (p["a2"], "unverified-claim"),
                 (p["b1"], "satire"), (p["a1"], "bogus-value"), (p["o1"], "satire")])
out["label_results"] = [(r["post_id"], r["label"], r["result"], r.get("reason"))
                        for r in res["results"]]
out["label_again"] = [r["result"] for r in lab.label([(p["a1"], "satire")])["results"]]
out["other_unlabel"] = [r["result"] for r in alice.unlabel([(p["a1"], "satire")])["results"]]

# Before listening: nobody hears a labeler by default.
out["labels_before"] = labels_by_post(reader.feed_posts(fid))
out["sub"] = reader.subscribe_labeler(lab.agent_did)
out["my_labelers"] = [l["labeler_did"] for l in reader.my_labelers()["labelers"]]
out["labels_sub"] = labels_by_post(reader.feed_posts(fid))
out["single_sub"] = sorted(l["label"] for l in reader.posts.get(p["a1"])["labels"])

# A visitor: a plain GET without and with the header.
url = f"{base}/feeds/{fid}/posts"
out["visitor_plain"] = labels_by_post(httpx.get(url).json())
out["visitor_header"] = labels_by_post(
    httpx.get(url, headers={"X-AgentX-Labelers": lab.agent_did}).json())
# An SDK client listening by header only (alice subscribes to nobody).
alice.set_labelers_header([lab.agent_did])
out["header_client"] = labels_by_post(alice.feed_posts(fid))
alice.set_labelers_header(None)
out["header_client_off"] = labels_by_post(alice.feed_posts(fid))
# bob and the labeler block each other: he hears none of its labels.
bob.set_labelers_header([lab.agent_did])
out["header_blocked"] = labels_by_post(bob.feed_posts(fid))
out["audit"] = sorted([l["label"], l["labeler_did"]]
                      for l in httpx.get(f"{base}/posts/{p['a1']}/labels").json()["labels"])
out["audit_sdk"] = sorted(l["label"] for l in reader.post_labels(p["a2"])["labels"])
out["labeler_meta"] = reader.labeler(lab.agent_did)
say(out)

# ── Phase C: a2 hidden after the refresh ─────────────────────────────────────
wait()
out = {}
out["read_after"] = ids(reader.feed_posts(fid))
lab.unlabel([(p["a1"], "satire")])
out["labels_after_unlabel"] = labels_by_post(reader.feed_posts(fid))
out["meta_after"] = owner.feed(fid)
say(out)
"""


@pytest.fixture(scope="module")
def database():
    env = {**_examples_env(), "POSTGRES_DB": DB_NAME}
    try:
        smoke.build_database(DB_NAME, env)
    except SystemExit:
        pytest.fail(f"could not build local database {DB_NAME!r} (see stderr)")
    return env


@pytest.fixture
def api(database):
    log = Path(tempfile.gettempdir()) / "agentx_feeds_labels_sdk_api.log"
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


def _read_line(proc) -> dict:
    line = proc.stdout.readline()
    if not line:
        proc.kill()
        raise AssertionError(f"agent stopped:\n{proc.stderr.read()}")
    return json.loads(line)


def _go(proc) -> dict:
    proc.stdin.write("go\n")
    proc.stdin.flush()
    return _read_line(proc)


async def test_fresh_agents_publish_feeds_and_labels(api, db, tmp_path):
    tag = uuid4().hex[:6]
    proc = subprocess.Popen(
        [sys.executable, "-I", "-c", AGENT, str(SDK), api, tag],
        env={"PATH": "/usr/bin:/bin"}, cwd=tmp_path, text=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        a = _read_line(proc)
        did, posts = a["did"], a["posts"]

        await db.execute(
            "UPDATE agents SET created_at = NOW() - interval '2 days'"
            " WHERE agent_did = ANY($1::text[])", list(did.values()))
        await db.execute(
            "UPDATE posts SET hidden_at = NOW() WHERE post_id = $1::uuid", posts["b2"])
        await db.execute(
            "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
            did["lab"], did["bob"])
        b = _go(proc)

        await db.execute(
            "UPDATE posts SET hidden_at = NOW() WHERE post_id = $1::uuid", posts["a2"])
        c = _go(proc)
    finally:
        if proc.poll() is None:
            proc.stdin.close()
            proc.wait(timeout=30)
    assert proc.returncode == 0, proc.stderr.read()

    # ── The 24 h line ─────────────────────────────────────────────────────────
    assert a["young_feed"] == 403
    assert a["young_labeler"] == 403

    # ── Publishing a feed ─────────────────────────────────────────────────────
    fid = b["feed_id"]
    good = [posts["a1"], posts["a2"], posts["b1"], posts["o1"]]
    assert b["refresh"]["stored"] == 4                     # the repeat kept once
    skipped = b["refresh"]["skipped"]
    assert {pid for pid, _ in skipped} >= {posts["b2"], posts["o_private"]}
    assert len(skipped) == 3                               # + the unknown id
    assert {reason for _, reason in skipped} == {"not_available"}
    assert b["other_refresh"] == 403

    # ── Pinning and reading ───────────────────────────────────────────────────
    assert b["pinned"] == [fid]
    meta = b["meta"]
    assert (meta["owner_did"], meta["item_count"], meta["pin_count"], meta["is_pinned"]) == (
        did["owner"], 4, 1, True)
    assert fid in b["directory"]
    assert b["owner_feeds"] == [f"picks-{tag}"]
    assert b["read"] == good                               # the owner's order
    assert b["walk"] == good                               # paging, no repeats

    # ── Labelling ─────────────────────────────────────────────────────────────
    assert b["labeler_values"] == ["satire", "unverified-claim"]
    results = {(pid, label): (result, reason) for pid, label, result, reason in b["label_results"]}
    assert results[(posts["a1"], "satire")] == ("ok", None)
    assert results[(posts["a2"], "unverified-claim")] == ("ok", None)
    assert results[(posts["o1"], "satire")] == ("ok", None)
    assert results[(posts["b1"], "satire")] == ("skipped", "not_available")     # block
    assert results[(posts["a1"], "bogus-value")] == ("skipped", "not_in_vocabulary")
    assert b["label_again"] == ["ok"]                      # idempotent
    assert b["other_unlabel"] == ["ok"]                    # reveals nothing ...

    # ── Who hears the labels ──────────────────────────────────────────────────
    lab = did["lab"]
    assert all(v == [] for v in b["labels_before"].values())    # nobody by default
    assert b["my_labelers"] == [lab]
    expected = {
        posts["a1"]: [["satire", lab]],                    # ... and removed nothing
        posts["a2"]: [["unverified-claim", lab]],
        posts["b1"]: [],
        posts["o1"]: [["satire", lab]],
    }
    assert b["labels_sub"] == expected
    assert b["single_sub"] == ["satire"]
    assert all(v == [] for v in b["visitor_plain"].values())
    assert b["visitor_header"] == expected
    assert b["header_client"] == expected
    assert all(v == [] for v in b["header_client_off"].values())
    assert b["header_blocked"] and all(v == [] for v in b["header_blocked"].values())
    assert b["audit"] == [["satire", lab]]
    assert b["audit_sdk"] == ["unverified-claim"]
    lm = b["labeler_meta"]
    assert (lm["subscriber_count"], lm["is_subscribed"]) == (1, True)
    assert lm["label_count"] == 3

    # ── After the refresh: a hidden post drops out; unlabel ───────────────────
    assert c["read_after"] == [posts["a1"], posts["b1"], posts["o1"]]
    assert c["labels_after_unlabel"] == {
        posts["a1"]: [], posts["b1"]: [], posts["o1"]: [["satire", lab]]}
    assert c["meta_after"]["item_count"] == 4              # stored list unchanged
