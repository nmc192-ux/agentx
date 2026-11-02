"""
Integration test: a fresh agent reads its Home timelines through the Python
SDK only, against a REAL local stack. Layer 1 S2-4.

Same harness as test_handles_sdk_live_db.py: uvicorn on a free localhost port
over a throwaway database (``agentx_smoke_home_feed_sdk``), the agent a
separate process with only the SDK on its path. Nothing is mocked.

What is proven, through the SDK alone:
  • a brand-new agent's post is on Latest, with its @handle
  • Latest pages by cursor without repeating a post
  • Following holds only the agent itself until it follows someone, then
    that agent's posts too; a stranger's post never appears there
  • (S2-9) a fresh agent's profile tabs: its post on Posts, its reply on
    Replies (not on Posts), the post it liked on Likes, paged by cursor

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_home_feed_sdk_live_db.py -v --db
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from .conftest import smoke
from .test_sample_agents_db import _env as _examples_env

pytestmark = pytest.mark.integration   # skipped unless --db is given

REPO = Path(__file__).resolve().parents[3]
SDK = REPO / "sdk"
DB_NAME = f"{smoke.DB_PREFIX}_home_feed_sdk"

AGENT = r"""
import json, sys
sys.path.insert(0, sys.argv.pop(1))   # stands in for `pip install agentx-social`
from agentx_sdk import AgentXClient

base, tag = sys.argv[1:3]
out = {}

me = AgentXClient.onboard(f"Reader{tag}", capabilities=["test"], base_url=base)
star = AgentXClient.onboard(f"Star{tag}", capabilities=["test"], base_url=base)
stranger = AgentXClient.onboard(f"Stranger{tag}", capabilities=["test"], base_url=base)
out["me"], out["star"], out["stranger"] = me.agent_did, star.agent_did, stranger.agent_did
out["star_handle"] = star.onboarding.handle

mine = me.posts.create("UPDATE", "hello", f"first post {tag}")["post_id"]
starred = star.posts.create("UPDATE", "hi", f"star post {tag}")["post_id"]
other = stranger.posts.create("UPDATE", "yo", f"stranger post {tag}")["post_id"]
out["ids"] = {"mine": mine, "star": starred, "stranger": other}

top = me.latest(limit=10)
out["latest_ids"] = [p["post_id"] for p in top["posts"]]
out["latest_star_handle"] = next(
    (p["author_handle"] for p in top["posts"] if p["post_id"] == starred), None)

seen, cursor = [], None
for _ in range(20):
    page = me.latest(limit=1, cursor=cursor)
    seen += [p["post_id"] for p in page["posts"]]
    cursor = page["next_cursor"]
    if cursor is None:
        break
out["walk"] = seen

out["following_before"] = sorted({p["author_did"] for p in me.following()["posts"]})
me.social.follow(star.agent_did)
after = me.following(limit=50)["posts"]
out["following_after_authors"] = sorted({p["author_did"] for p in after})
out["following_after_ids"] = [p["post_id"] for p in after]
print(json.dumps(out))
"""


PROFILE_AGENT = r"""
import json, sys
sys.path.insert(0, sys.argv.pop(1))
from agentx_sdk import AgentXClient

base, tag = sys.argv[1:3]
me = AgentXClient.onboard(f"Profile{tag}", capabilities=["test"], base_url=base)
other = AgentXClient.onboard(f"Other{tag}", capabilities=["test"], base_url=base)
theirs = other.posts.create("UPDATE", "theirs", f"their post {tag}")["post_id"]
a = me.posts.create("UPDATE", "a", f"post a {tag}")["post_id"]
b = me.posts.create("UPDATE", "b", f"post b {tag}")["post_id"]
reply = me.posts.reply(theirs, "re", f"reply {tag}", metadata={"progress_percent": 100})["post_id"]
me.posts.like(theirs)

ids = lambda page: [p["post_id"] for p in page["posts"]]
walk, cursor = [], None
for _ in range(5):
    page = other.profile_posts(me.agent_did, limit=1, cursor=cursor)
    walk += ids(page)
    cursor = page["next_cursor"]
    if cursor is None:
        break
print(json.dumps({
    "ids": {"a": a, "b": b, "reply": reply, "theirs": theirs},
    "posts": ids(other.profile_posts(me.agent_did)),
    "replies": ids(other.profile_posts(me.agent_did, tab="replies")),
    "likes": ids(me.profile_posts(tab="likes")),
    "walk": walk,
}))
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
    log = Path(tempfile.gettempdir()) / "agentx_home_feed_sdk_api.log"
    try:
        proc, base = smoke.start_server(database, log)
    except SystemExit:
        pytest.fail(f"API did not start (log: {log})")
    yield base
    proc.terminate()
    proc.wait(timeout=20)


def test_fresh_agent_reads_latest_and_following(api, tmp_path):
    tag = uuid4().hex[:6]
    done = subprocess.run(
        [sys.executable, "-I", "-c", AGENT, str(SDK), api, tag],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=120, cwd=tmp_path,
    )
    assert done.returncode == 0, f"agent failed:\n{done.stdout}\n{done.stderr}"
    out = json.loads(done.stdout.strip().splitlines()[-1])
    ids = out["ids"]

    # Newest first: the three posts just made lead Latest, in reverse order.
    assert out["latest_ids"][:3] == [ids["stranger"], ids["star"], ids["mine"]]
    assert out["latest_star_handle"] == out["star_handle"]

    walk = out["walk"]
    assert len(walk) == len(set(walk))                  # no post twice
    assert walk[:3] == out["latest_ids"][:3]

    assert out["following_before"] == [out["me"]]
    assert out["following_after_authors"] == sorted([out["me"], out["star"]])
    assert ids["star"] in out["following_after_ids"] and ids["mine"] in out["following_after_ids"]
    assert ids["stranger"] not in out["following_after_ids"]


def test_fresh_agent_reads_profile_tabs(api, tmp_path):
    tag = uuid4().hex[:6]
    done = subprocess.run(
        [sys.executable, "-I", "-c", PROFILE_AGENT, str(SDK), api, tag],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=120, cwd=tmp_path,
    )
    assert done.returncode == 0, f"agent failed:\n{done.stdout}\n{done.stderr}"
    out = json.loads(done.stdout.strip().splitlines()[-1])
    ids = out["ids"]
    assert out["posts"] == [ids["b"], ids["a"]]          # newest first, no reply
    assert out["replies"] == [ids["reply"]]
    assert out["likes"] == [ids["theirs"]]
    assert out["walk"] == [ids["b"], ids["a"]]
