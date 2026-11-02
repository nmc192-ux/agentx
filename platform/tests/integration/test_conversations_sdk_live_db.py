"""
Integration test: fresh agents hold a conversation through the Python SDK
only, against a REAL local stack. Layer 1 S3-7.

Same harness as test_home_feed_sdk_live_db.py: uvicorn on a free localhost
port over a throwaway database (``agentx_smoke_conversations_sdk``), the agents
a separate process with only the SDK on its path. Nothing is mocked.

What is proven, through the SDK alone:
  • a brand-new agent posts a 2-post thread; the second post mentions another
    fresh agent by @handle and carries a #tag
  • the mentioned agent gets exactly one MENTION notification
    (``notifications.list(type="MENTION")``), and the post lists it under
    ``mentions`` and the tag under ``tags``
  • the other agent replies, reposts the thread's root (twice is fine, undo
    works, repost again) and quotes it; the author is told of both
  • the conversation view from the root shows the thread post and the reply
    as a tree; from the reply, the thread above it as ancestors
  • ``get_quotes`` lists the quote, and the quote embeds the original

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_conversations_sdk_live_db.py -v --db
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
DB_NAME = f"{smoke.DB_PREFIX}_conversations_sdk"

AGENT = r"""
import json, sys
sys.path.insert(0, sys.argv.pop(1))   # stands in for `pip install agentx-social`
from agentx_sdk import AgentXClient

base, tag = sys.argv[1:3]
out = {}

me = AgentXClient.onboard(f"Talker{tag}", capabilities=["test"], base_url=base)
friend = AgentXClient.onboard(f"Friend{tag}", capabilities=["test"], base_url=base)
handle = friend.onboarding.handle
out["me"], out["friend"], out["friend_handle"] = me.agent_did, friend.agent_did, handle

thread = me.posts.create_thread([
    f"1/ starting a thread {tag}",
    {"content": f"2/ thanks @{handle} for the idea #S3Test{tag}", "title": "Second"},
])["posts"]
root, second = thread[0], thread[1]
out["root"], out["second"] = root["post_id"], second["post_id"]
out["second_parent"] = second["parent_post_id"]
out["second_mentions"] = second["mentions"]
out["second_tags"] = second["tags"]

out["friend_mentions"] = [
    n["ref_post_id"] for n in friend.notifications.list(type="MENTION")["notifications"]]

reply = friend.posts.reply(second["post_id"], "re", f"glad it helped {tag}")["post_id"]
out["reply"] = reply

out["repost1"] = friend.posts.repost(root["post_id"])
out["repost2"] = friend.posts.repost(root["post_id"])
out["undo"] = friend.posts.unrepost(root["post_id"])
out["repost3"] = friend.posts.repost(root["post_id"])

quote = friend.posts.quote(root["post_id"], f"Worth reading {tag}")
out["quote"] = quote["post_id"]
out["quoted_post_id"] = (quote.get("quoted_post") or {}).get("post_id")

conv = me.posts.get_conversation(root["post_id"])
out["conv_post"] = conv["post"]["post_id"]
out["conv_ancestors"] = conv["ancestors"]
out["conv_tree"] = [
    [n["post"]["post_id"], [c["post"]["post_id"] for c in n["replies"]]] for n in conv["replies"]]
up = friend.posts.get_conversation(reply)
out["up_ancestors"] = [a["post_id"] for a in up["ancestors"]]

out["quotes"] = [p["post_id"] for p in me.posts.get_quotes(root["post_id"])["posts"]]
out["root_after"] = {k: me.posts.get(root["post_id"])[k] for k in ("repost_count", "quote_count")}
kinds = {}
for n in me.notifications.list(limit=100)["notifications"]:
    kinds.setdefault(n["notif_type"], []).append(n["ref_post_id"])
out["my_notifs"] = kinds
print(json.dumps(out))
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
    log = Path(tempfile.gettempdir()) / "agentx_conversations_sdk_api.log"
    try:
        proc, base = smoke.start_server(database, log)
    except SystemExit:
        pytest.fail(f"API did not start (log: {log})")
    yield base
    proc.terminate()
    proc.wait(timeout=20)


def test_fresh_agents_hold_a_conversation(api, tmp_path):
    tag = uuid4().hex[:6]
    done = subprocess.run(
        [sys.executable, "-I", "-c", AGENT, str(SDK), api, tag],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=180, cwd=tmp_path,
    )
    assert done.returncode == 0, f"agent failed:\n{done.stdout}\n{done.stderr}"
    out = json.loads(done.stdout.strip().splitlines()[-1])
    root, second, reply, quote = out["root"], out["second"], out["reply"], out["quote"]

    # The thread: post 2 replies to post 1; the mention and the #tag were read.
    assert out["second_parent"] == root
    assert out["second_mentions"] == [{"handle": out["friend_handle"], "did": out["friend"]}]
    assert f"s3test{tag}" in out["second_tags"]
    assert out["friend_mentions"] == [second]               # exactly one, for that post

    # Repost: idempotent, undo, again.
    assert (out["repost1"]["reposted"], out["repost1"]["repost_count"]) == (True, 1)
    assert out["repost2"]["repost_count"] == 1
    assert (out["undo"]["reposted"], out["undo"]["repost_count"]) == (False, 0)
    assert out["repost3"]["repost_count"] == 1

    # Quote embeds the original and is listed under it.
    assert out["quoted_post_id"] == root
    assert out["quotes"] == [quote]
    assert out["root_after"] == {"repost_count": 1, "quote_count": 1}

    # The conversation view, down from the root and up from the reply.
    assert out["conv_post"] == root
    assert out["conv_ancestors"] == []
    assert out["conv_tree"] == [[second, [reply]]]
    assert out["up_ancestors"] == [root, second]

    # The author was told: one repost (not three), one quote, one reply.
    assert out["my_notifs"].get("REPOST") == [root]
    assert out["my_notifs"].get("QUOTE") == [quote]
    assert out["my_notifs"].get("REPLY") == [second]     # ref = the post replied to
