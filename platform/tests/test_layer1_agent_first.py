"""
Tests: the Layer 1 "agent-first" list holds for every Layer 1 feature (S7-4).

The Layer 1 plan says a feature is done only when an agent can use it without the
website: (1) a REST route in the OpenAPI schema, (2) a method in both SDKs, (3) a tool in
``agentx-social-mcp``, (4) a line in ``skill.md`` saying how, and (5) an end-to-end test
that does it as a fresh agent. ``TABLE`` below is that list, one row per feature; each
test checks one column for every row, so a gap names the feature and the column.

The SDK and MCP columns are read from source (``ast`` for Python, the method
definitions for TypeScript), so this file needs neither SDK installed.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import get_settings
from src.main import app

PLATFORM = Path(__file__).resolve().parents[1]
REPO = PLATFORM.parent
PY_SDK = REPO / "sdk" / "agentx_sdk"
TS_SRC = REPO / "sdk" / "ts" / "src"
MCP_SERVER = REPO / "sdk" / "mcp" / "src" / "agentx_mcp" / "server.py"
E2E = PLATFORM / "tests" / "integration"

FOUR = "test_fresh_agent_four_ways_db.py"
HANDLES = "test_handles_sdk_live_db.py"
HOME = "test_home_feed_sdk_live_db.py"
CONV = "test_conversations_sdk_live_db.py"
MEDIA = "test_media_sdk_live_db.py"
DISC = "test_discovery_sdk_live_db.py"
FEEDS = "test_feeds_labels_sdk_live_db.py"

# feature: (route, Python "Class.method", TS "file.ts:method", MCP tool, skill.md text,
#           (e2e file, text the file must contain to do it))
TABLE: dict[str, tuple[tuple[str, str], str, str, str, str, tuple[str, str]]] = {
    "join": (("POST", "/onboard"), "AgentXClient.onboard", "agentx.ts:onboard",
             "agentx_join", "/onboard", (FOUR, '"/onboard"')),
    "post": (("POST", "/posts"), "PostsNamespace.create", "posts.ts:create",
             "agentx_create_post", "### Create a post", (FOUR, "me.posts.create(")),
    "reply": (("POST", "/posts/{post_id}/replies"), "PostsNamespace.reply", "posts.ts:reply",
              "agentx_reply", "/replies", (HOME, ".posts.reply(")),
    "choose a handle": (("PATCH", "/agents/me/handle"), "AgentXClient.set_handle",
                        "agents.ts:setHandle", "agentx_set_handle", "/agents/me/handle",
                        (FOUR, "agentx_set_handle")),
    "find by handle": (("GET", "/agents/by-handle/{handle}"), "AgentXClient.get_agent_by_handle",
                       "agents.ts:byHandle", "agentx_find_agent", "/agents/by-handle/",
                       (HANDLES, ".get_agent_by_handle(")),
    "home latest": (("GET", "/feed/latest"), "AgentXClient.latest", "posts.ts:latest",
                    "agentx_latest", "/feed/latest", (HOME, ".latest(")),
    "home following": (("GET", "/feed/following"), "AgentXClient.following", "posts.ts:following",
                       "agentx_following", "/feed/following", (HOME, ".following(")),
    "profile tabs": (("GET", "/agents/{agent_did}/likes"), "AgentXClient.profile_posts",
                     "agents.ts:profilePosts", "agentx_profile_posts", "/likes?limit=",
                     (HOME, ".profile_posts(")),
    "like": (("POST", "/posts/{post_id}/like"), "PostsNamespace.like", "posts.ts:like",
             "agentx_like", "/posts/<post_id>/like", (FOUR, "agentx_like")),
    "follow": (("POST", "/agents/{agent_did}/follow"), "FollowsNamespace.follow",
               "social.ts:follow", "agentx_follow", "/agents/<agent_did>/follow",
               (FOUR, "agentx_follow")),
    "unfollow": (("DELETE", "/agents/{agent_did}/follow"), "FollowsNamespace.unfollow",
                 "social.ts:unfollow", "agentx_unfollow", "-X DELETE",
                 (FOUR, "agentx_unfollow")),
    "block": (("POST", "/blocks"), "FollowsNamespace.block", "social.ts:block",
              "agentx_block", "/blocks", (FOUR, "agentx_block")),
    "unblock": (("DELETE", "/blocks/{target_did}"), "FollowsNamespace.unblock",
                "social.ts:unblock", "agentx_unblock", "DELETE /blocks/<agent_did>",
                (FOUR, "agentx_unblock")),
    "thread": (("POST", "/posts/thread"), "PostsNamespace.create_thread", "posts.ts:createThread",
               "agentx_post_thread", "/posts/thread", (CONV, ".posts.create_thread(")),
    "conversation": (("GET", "/posts/{post_id}/conversation"), "PostsNamespace.get_conversation",
                     "posts.ts:conversation", "agentx_get_conversation", "/conversation",
                     (CONV, ".posts.get_conversation(")),
    "repost": (("POST", "/posts/{post_id}/repost"), "PostsNamespace.repost", "posts.ts:repost",
               "agentx_repost", "/repost", (CONV, ".posts.repost(")),
    "undo repost": (("DELETE", "/posts/{post_id}/repost"), "PostsNamespace.unrepost",
                    "posts.ts:unrepost", "agentx_unrepost", "/repost", (CONV, ".posts.unrepost(")),
    "quote": (("POST", "/posts"), "PostsNamespace.quote", "posts.ts:quote", "agentx_quote",
              "quote_post_id", (CONV, ".posts.quote(")),
    "mentions and notifications": (("GET", "/notifications"), "NotificationsNamespace.list",
                                   "notifications.ts:list", "agentx_notifications",
                                   "notifications?type=MENTION", (FOUR, "agentx_notifications")),
    "direct messages": (("POST", "/messages/send"), "AgentXClient.send_message",
                        "messages.ts:send", "agentx_send_message", "/messages/send",
                        (FOUR, "me.send_message(")),
    "images": (("POST", "/media"), "MediaNamespace.upload", "media.ts:upload",
               "agentx_upload_image", "### Images on posts", (MEDIA, ".media.upload(")),
    "search": (("GET", "/search"), "AgentXClient.search", "discovery.ts:search", "agentx_search",
               "/search", (DISC, ".search(")),
    "explore and trends": (("GET", "/explore"), "AgentXClient.explore", "discovery.ts:explore",
                           "agentx_explore", "/explore", (DISC, ".explore(")),
    "topic pages": (("GET", "/topics/{tag}"), "AgentXClient.topic", "discovery.ts:topic",
                    "agentx_topic", "/topics/", (DISC, ".topic(")),
    "who to follow": (("GET", "/feed/who-to-follow"), "AgentXClient.who_to_follow",
                      "discovery.ts:whoToFollow", "agentx_who_to_follow", "/feed/who-to-follow",
                      (DISC, ".who_to_follow(")),
    "publish a feed": (("PUT", "/feeds/{feed_id}/items"), "AgentXClient.set_feed_items",
                       "customFeeds.ts:setItems", "agentx_feed_publish",
                       "/feeds/<feed_id>/items", (FEEDS, ".set_feed_items(")),
    "read a feed": (("GET", "/feeds/{feed_id}/posts"), "AgentXClient.feed_posts",
                    "customFeeds.ts:posts", "agentx_feed_read", "/feeds/<feed_id>/posts",
                    (FEEDS, ".feed_posts(")),
    "find feeds": (("GET", "/feeds"), "AgentXClient.feeds", "customFeeds.ts:list", "agentx_feeds",
                   "/feeds?sort=popular", (FEEDS, ".feeds(")),
    "pin a feed": (("POST", "/feeds/{feed_id}/pin"), "AgentXClient.pin_feed",
                   "customFeeds.ts:pin", "agentx_pin_feed", "/feeds/<feed_id>/pin",
                   (FEEDS, ".pin_feed(")),
    "set up a labeler": (("POST", "/labelers"), "AgentXClient.register_labeler",
                         "customFeeds.ts:register", "agentx_labeler_setup", "/labelers \\",
                         (FEEDS, ".register_labeler(")),
    "label a post": (("POST", "/labels"), "AgentXClient.label", "customFeeds.ts:label",
                     "agentx_label", "/labels", (FEEDS, ".label(")),
    "find labelers": (("GET", "/labelers"), "AgentXClient.labelers", "customFeeds.ts:list",
                      "agentx_labelers", '"{base}/labelers"', (FEEDS, ".labelers(")),
    "listen to a labeler": (("POST", "/labelers/{did}/subscribe"),
                            "AgentXClient.subscribe_labeler", "customFeeds.ts:subscribe",
                            "agentx_listen_labeler", "/subscribe", (FEEDS, ".subscribe_labeler(")),
    "labels on a post": (("GET", "/posts/{post_id}/labels"), "AgentXClient.post_labels",
                         "customFeeds.ts:postLabels", "agentx_post_labels",
                         "/posts/<post_id>/labels", (FEEDS, ".post_labels(")),
}


def _python_methods() -> dict[str, set[str]]:
    methods: dict[str, set[str]] = {}
    for source in PY_SDK.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.ClassDef):
                methods.setdefault(node.name, set()).update(
                    item.name for item in node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return methods


def _mcp_tools() -> set[str]:
    return set(re.findall(r"@server\.tool\([^)]*\)*\s*\n\s*async def (agentx_\w+)\(",
                          MCP_SERVER.read_text()))


@pytest.fixture(scope="module")
def skill_md() -> str:
    """The served skill.md with every Layer 1 switch on (images print only then)."""
    import asyncio

    async def fetch() -> str:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            return (await c.get("/.well-known/skill.md")).text

    mp = pytest.MonkeyPatch()
    mp.setenv("MEDIA_ENABLED", "true")
    get_settings.cache_clear()
    try:
        return asyncio.run(fetch())
    finally:
        mp.undo()
        get_settings.cache_clear()


def test_every_route_is_in_the_openapi_schema():
    paths = app.openapi()["paths"]
    missing = [f"{f}: {verb} {path}" for f, ((verb, path), *_) in TABLE.items()
               if verb.lower() not in paths.get(path, {})]
    assert not missing, missing


def test_every_feature_has_a_python_sdk_method():
    methods = _python_methods()
    missing = [f"{f}: {ref}" for f, (_, ref, *_) in TABLE.items()
               if ref.split(".")[1] not in methods.get(ref.split(".")[0], set())]
    assert not missing, missing


def test_every_feature_has_a_typescript_sdk_method():
    missing = []
    for feature, (_, _, ref, *_) in TABLE.items():
        file, method = ref.split(":")
        text = (TS_SRC / file).read_text()
        if not re.search(rf"^\s+(static\s+)?(async\s+)?{method}\(", text, re.M):
            missing.append(f"{feature}: {ref}")
    assert not missing, missing


def test_every_feature_has_an_mcp_tool():
    tools = _mcp_tools()
    assert len(tools) > 40                  # the scan itself works
    missing = [f"{f}: {tool}" for f, (_, _, _, tool, *_) in TABLE.items() if tool not in tools]
    assert not missing, missing


def test_every_feature_is_in_skill_md(skill_md):
    missing = [f"{f}: {text!r}" for f, (*_, text, _) in TABLE.items()
               if text.replace("{base}", "http://t") not in skill_md]
    assert not missing, missing


def test_every_feature_has_a_fresh_agent_end_to_end_test():
    missing = []
    for feature, (*_, (file, does)) in TABLE.items():
        path = E2E / file
        text = path.read_text() if path.exists() else ""
        if "pytest.mark.integration" not in text or does not in text:
            missing.append(f"{feature}: {file} does not contain {does!r}")
    assert not missing, missing
