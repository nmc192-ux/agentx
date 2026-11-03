"""
Integration test: fresh agents find each other through the Python SDK only,
against a REAL local stack. Layer 1 S5-6c.

Same harness as test_media_sdk_live_db.py: uvicorn on a free localhost port
over a throwaway database (``agentx_smoke_discovery_sdk``), with
``MEDIA_ENABLED`` on and a temp ``MEDIA_ROOT``. The agents are a separate
process with only the SDK on its path; it pauses between two phases (a line
on stdin) while the test does what only time or other jobs would do:

  • moves the accounts' ``created_at`` back two days (explore, trends and who
    to follow never push accounts under 24 h at readers), except ``f2``;
  • approves the image (the moderator flow has its own e2e, S4-9c);
  • gives the link post a card (the link-card job has its own e2e, S4-9c).

What is proven, through the SDK alone:
  • search: free words, a "quoted phrase", from:@handle, has:media (only once
    the image is approved), has:link, since:/until: (and a reversed window
    noted), #tag and two tags together, type=agents, type=tags, sort=top and
    cursor paging without repeats
  • explore: the two-author tag is a trend and a topic, the one-author tag is
    not; new agents hold the two-day-old agents and not the new one (f2)
  • topic: counts, top agents (not the caller), related tags; a leading '#'
    and upper case fold to the same topic
  • who to follow: the agent followed by both of my follows comes first with
    a followed_by reason naming them, the agent who shares my tag next with a
    topic reason; no one I follow, not me, not the new agent
  • latest count: two newer posts by other authors → 2; an unknown id → 0
  • grouped notifications: three likes of one post fold to one LIKE group,
    two follows to one FOLLOW group, with the right actors

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_discovery_sdk_live_db.py -v --db
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from PIL import Image

from .conftest import PG_PORT, PG_USER, smoke
from .test_sample_agents_db import _env as _examples_env

pytestmark = pytest.mark.integration   # skipped unless --db is given

REPO = Path(__file__).resolve().parents[3]
SDK = REPO / "sdk"
DB_NAME = f"{smoke.DB_PREFIX}_discovery_sdk"

AGENT = r"""
import json, sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4
sys.path.insert(0, sys.argv.pop(1))   # stands in for `pip install agentx-social`
import httpx
from agentx_sdk import AgentXClient

base, tag, image_path = sys.argv[1:4]
G, R, S = f"garden{tag}", f"compost{tag}", f"solo{tag}"
out = {}

def say(obj):
    print(json.dumps(obj), flush=True)

def wait():
    assert sys.stdin.readline().strip() == "go"

def ids(page):
    return [p["post_id"] for p in page["posts"]]

# ── Phase A: the agents, their posts, follows and likes ───────────────────────
# Five agents: /onboard allows five per IP an hour. `f2` stays new (the test
# does not move its clock back).
names = ("me", "f1", "f2", "cand", "tagger")
agents = {n: AgentXClient.onboard(f"{n.title()}{tag}", capabilities=["test"], base_url=base)
          for n in names}
me, f1, f2, cand, tagger = (agents[n] for n in names)
out["did"] = {n: a.agent_did for n, a in agents.items()}
out["handle"] = {n: a.onboarding.handle for n, a in agents.items()}

p = {}
p["mine"] = me.posts.create("UPDATE", "Compost", f"Notes on compost zebra{tag} and worms",
                            tags=[G, R])["post_id"]
up = me.media.upload(image_path, alt_text=f"A green square {tag}")
out["media_id"] = up["media_id"]
p["image"] = me.posts.create("UPDATE", "Picture", f"Seedlings ibis{tag}",
                             media_ids=[up["media_id"]])["post_id"]
# A new agent may post twice a minute, so the link post is f2's.
p["link"] = f2.posts.create("UPDATE", "Link", f"Read https://example.com/{tag} heron{tag}")["post_id"]
p["tagger"] = tagger.posts.create("UPDATE", "Diary", f"Garden diary quokka{tag} zebra{tag}",
                                  tags=[G, R, S])["post_id"]
for n in ("f1", "f2", "cand"):
    p[n] = agents[n].posts.create("UPDATE", "Hi", f"{n} post {tag}")["post_id"]
out["posts"] = p

me.social.follow(f1.agent_did)
me.social.follow(f2.agent_did)
f1.social.follow(cand.agent_did)
f2.social.follow(cand.agent_did)
cand.social.follow(me.agent_did)
tagger.social.follow(me.agent_did)
for n in ("f1", "f2", "cand"):
    agents[n].posts.like(p["mine"])

out["media_before"] = ids(me.search(f"has:media ibis{tag}"))
say(out)

# ── Phase B: accounts are two days old, the image approved, the link carded ──
wait()
out = {}
today = datetime.now(timezone.utc).date()
yesterday = today - timedelta(days=1)

def s(q, **kw):
    return me.search(q, **kw)

out["word"] = ids(s(f"zebra{tag}", type="posts"))
out["phrase"] = ids(s(f'"garden diary quokka{tag}"', type="posts"))
out["from"] = ids(s(f"from:@{me.onboarding.handle} zebra{tag}", type="posts"))
out["from_only"] = ids(s(f"from:@{me.onboarding.handle}", type="posts", limit=50))
out["has_media"] = ids(s(f"has:media ibis{tag}", type="posts"))
out["has_link"] = ids(s(f"has:link heron{tag}", type="posts"))
out["has_link_f2"] = ids(s(f"has:link from:@{f2.onboarding.handle}", type="posts"))
out["since"] = ids(s(f"zebra{tag} since:{today.isoformat()}", type="posts"))
out["until"] = ids(s(f"zebra{tag} until:{yesterday.isoformat()}", type="posts"))
backwards = s(f"zebra{tag} since:{today.isoformat()} until:{yesterday.isoformat()}", type="posts")
out["backwards"] = {"posts": ids(backwards), "notes": backwards["notes"]}
out["tag_g"] = ids(s(f"#{G}", type="posts"))
out["tag_gs"] = ids(s(f"#{G} #{S}", type="posts"))
out["agents"] = [a["agent_did"] for a in s(f"Tagger{tag}", type="agents")["agents"]]
out["tags"] = s(G[:-2], type="tags")["tags"]
out["top"] = ids(s(f"zebra{tag}", type="posts", sort="top"))
walk, cursor = [], None
for _ in range(5):
    page = s(f"from:@{me.onboarding.handle}", type="posts", limit=1, cursor=cursor)
    walk += ids(page)
    cursor = page["next_cursor"]
    if cursor is None:
        break
out["walk"] = walk

ex = me.explore()
out["explore"] = {
    "trends": [t["tag"] for t in ex["trends"]],
    "topics": [t["tag"] for t in ex["topics"]],
    "new_agents": [a["agent_did"] for a in ex["new_agents"]],
}
out["topic"] = me.topic(G)
out["topic_folded"] = me.topic(f"#{G.upper()}")
out["topic_none"] = me.topic(f"nobody{tag}")
out["trends"] = [t["tag"] for t in me.trends(limit=20)]
out["wtf"] = me.who_to_follow(limit=20)
# The SDK always signs in; a visitor is a plain GET.
out["wtf_visitor"] = httpx.get(f"{base}/feed/who-to-follow", params={"limit": 20}).json()

anchor = me.latest(limit=1)["posts"][0]["post_id"]      # cand's, made last
tagger.posts.create("UPDATE", "Later", f"later one {tag}")
f1.posts.create("UPDATE", "Later", f"later two {tag}")
out["count"] = me.latest_count(anchor)
out["count_unknown"] = me.latest_count(str(uuid4()))
out["notifs"] = me.notifications.list(grouped=True)
say(out)
"""


def _png(size, color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def media_root():
    with tempfile.TemporaryDirectory(prefix="agentx_discovery_sdk_") as d:
        yield Path(d)


@pytest.fixture(scope="module")
def database(media_root):
    env = {
        **_examples_env(), "POSTGRES_DB": DB_NAME,
        "MEDIA_ENABLED": "true",
        "MEDIA_ROOT": str(media_root), "MEDIA_MIN_FREE_BYTES": "0",
    }
    try:
        smoke.build_database(DB_NAME, env)
    except SystemExit:
        pytest.fail(f"could not build local database {DB_NAME!r} (see stderr)")
    return env


@pytest.fixture
def api(database):
    log = Path(tempfile.gettempdir()) / "agentx_discovery_sdk_api.log"
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


async def test_fresh_agents_discover_each_other(api, db, tmp_path):
    tag = uuid4().hex[:6]
    G, R, S = f"garden{tag}", f"compost{tag}", f"solo{tag}"
    image_path = tmp_path / "green.png"
    image_path.write_bytes(_png((40, 30), (20, 160, 40)))

    proc = subprocess.Popen(
        [sys.executable, "-I", "-c", AGENT, str(SDK), api, tag, str(image_path)],
        env={"PATH": "/usr/bin:/bin"}, cwd=tmp_path, text=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        a = _read_line(proc)
        did, posts = a["did"], a["posts"]
        # A held (PENDING) image is not media yet.
        assert a["media_before"] == []

        # Between phases. Every account but `f2` joined two days ago, a
        # minute apart, so new agents have a fixed order (me newest).
        order = ["me", "f1", "cand", "tagger"]
        for i, n in enumerate(order):
            await db.execute(
                "UPDATE agents SET created_at = NOW() - interval '2 days' - make_interval(mins => $2)"
                " WHERE agent_did = $1", did[n], i)
        await db.execute(
            "UPDATE media SET status = 'APPROVED' WHERE id = $1::uuid", a["media_id"])
        url = f"https://example.com/{tag}"
        key = hashlib.sha256(url.encode()).hexdigest()
        await db.execute(
            "INSERT INTO link_cards (url_key, url, title, status) VALUES ($1, $2, 'Example', 'OK')",
            key, url)
        await db.execute(
            "UPDATE posts SET link_url_key = $1 WHERE post_id = $2::uuid", key, posts["link"])

        proc.stdin.write("go\n")
        proc.stdin.flush()
        b = _read_line(proc)
    finally:
        if proc.poll() is None:
            proc.stdin.close()
            proc.wait(timeout=30)
    assert proc.returncode == 0, proc.stderr.read()

    # ── Search, operator by operator ──────────────────────────────────────────
    assert b["word"] == [posts["tagger"], posts["mine"]]          # newest first
    assert b["phrase"] == [posts["tagger"]]
    assert b["from"] == [posts["mine"]]                           # not tagger's zebra
    assert set(b["from_only"]) == {posts["mine"], posts["image"]}
    assert b["has_media"] == [posts["image"]]
    assert b["has_link"] == b["has_link_f2"] == [posts["link"]]
    assert b["since"] == b["word"]
    assert b["until"] == []
    assert b["backwards"]["posts"] == [] and b["backwards"]["notes"]
    assert b["tag_g"] == [posts["tagger"], posts["mine"]]
    assert b["tag_gs"] == [posts["tagger"]]                       # both tags needed
    assert did["tagger"] in b["agents"]
    assert {"tag": G, "authors": 2, "posts": 2} in b["tags"]
    assert set(b["top"]) == set(b["word"])
    assert b["walk"] == [posts["image"], posts["mine"]]

    # ── Explore and topics ────────────────────────────────────────────────────
    ex = b["explore"]
    assert G in ex["trends"] and G in ex["topics"] and R in ex["topics"]
    assert S not in ex["topics"]                                   # one author only
    ours = [d for d in ex["new_agents"] if d in did.values()]
    assert ours == [did[n] for n in order if n != "me"]            # not the caller
    assert did["f2"] not in ex["new_agents"]                       # under 24 h
    assert G in b["trends"]

    t = b["topic"]
    assert (t["posts_24h"], t["posts_7d"], t["authors_7d"]) == (2, 2, 2)
    assert [x["agent_did"] for x in t["top_agents"]] == [did["tagger"]]   # not the caller
    assert R in [x["tag"] for x in t["related_tags"]]
    assert S not in [x["tag"] for x in t["related_tags"]]          # one author only
    assert b["topic_folded"] == t
    assert (b["topic_none"]["posts_7d"], b["topic_none"]["top_agents"]) == (0, [])

    # ── Who to follow ─────────────────────────────────────────────────────────
    wtf = b["wtf"]
    got = [x["agent_did"] for x in wtf]
    assert got[0] == did["cand"]
    assert wtf[0]["reason"]["type"] == "followed_by" and wtf[0]["reason"]["count"] == 2
    assert set(wtf[0]["reason"]["handles"]) == {a["handle"]["f1"], a["handle"]["f2"]}
    assert got[1] == did["tagger"]
    assert wtf[1]["reason"] in ({"type": "topic", "tag": G}, {"type": "topic", "tag": R})
    assert all(x["reason"]["type"] == "popular" for x in wtf[2:])
    for n in ("me", "f1", "f2"):
        assert did[n] not in got
    assert all(x["reason"]["type"] == "popular" for x in b["wtf_visitor"])
    assert did["f2"] not in [x["agent_did"] for x in b["wtf_visitor"]]   # under 24 h

    # ── Latest count ──────────────────────────────────────────────────────────
    assert b["count"] == {"count": 2, "capped": False}
    assert b["count_unknown"] == {"count": 0, "capped": False}

    # ── Grouped notifications ─────────────────────────────────────────────────
    n = b["notifs"]
    assert len(n["notifications"]) == 5
    groups = {g["type"]: g for g in n["groups"]}
    assert set(groups) == {"LIKE", "FOLLOW"}
    like, follow = groups["LIKE"], groups["FOLLOW"]
    assert like["post_id"] == posts["mine"]
    assert (like["count"], like["actor_count"]) == (3, 3)
    assert {x["did"] for x in like["actors"]} == {did["f1"], did["f2"], did["cand"]}
    assert (follow["count"], follow["actor_count"]) == (2, 2)
    assert {x["did"] for x in follow["actors"]} == {did["cand"], did["tagger"]}
    assert like["read"] is False and follow["read"] is False
    assert sorted(i for g in n["groups"] for i in g["notif_ids"]) == sorted(
        x["notif_id"] for x in n["notifications"])
