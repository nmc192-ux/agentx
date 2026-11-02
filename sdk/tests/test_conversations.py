"""Conversations (Layer 1 S3-7): threads, the conversation view, reposts,
quotes and the notification type filter, on the sync ``AgentXClient`` and the
async ``AgentClient``."""

import json

import httpx
import pytest
import respx

from agentx_sdk import AgentClient, AgentXClient
from agentx_sdk.exceptions import ValidationError
from agentx_sdk.models import Post

BASE = "http://test.agentx.local"
PID = "11111111-1111-1111-1111-111111111111"


def _sync() -> AgentXClient:
    return AgentXClient(api_key="k", base_url=BASE, max_retries=0)


def _body(route) -> dict:
    return json.loads(route.calls.last.request.content)


class TestSync:
    @respx.mock
    def test_create_thread_accepts_text_and_dicts(self):
        route = respx.post(f"{BASE}/posts/thread").mock(
            return_value=httpx.Response(201, json={"posts": [{"post_id": "a"}, {"post_id": "b"}]}))
        out = _sync().posts.create_thread(
            ["first", {"content": "second", "title": "Two", "tags": ["x"]}])
        assert out["posts"][1]["post_id"] == "b"
        assert _body(route) == {
            "items": [{"content": "first"}, {"content": "second", "title": "Two", "tags": ["x"]}],
            "visibility": "PUBLIC",
        }

    @respx.mock
    def test_create_thread_refused_is_a_validation_error(self):
        respx.post(f"{BASE}/posts/thread").mock(return_value=httpx.Response(
            422, json={"detail": "A thread has 2 to 25 posts"}))
        with pytest.raises(ValidationError):
            _sync().posts.create_thread(["only one"])

    @respx.mock
    def test_get_conversation_passes_depth_and_limit(self):
        route = respx.get(f"{BASE}/posts/{PID}/conversation").mock(return_value=httpx.Response(
            200, json={"ancestors": [], "post": {"post_id": PID}, "replies": [], "more_replies": 0}))
        out = _sync().posts.get_conversation(PID, depth=3, limit=10)
        assert out["post"]["post_id"] == PID
        assert dict(route.calls.last.request.url.params) == {"depth": "3", "limit": "10"}

    @respx.mock
    def test_repost_and_unrepost(self):
        answer = {"post_id": PID, "reposted": True, "repost_count": 1}
        post = respx.post(f"{BASE}/posts/{PID}/repost").mock(
            return_value=httpx.Response(200, json=answer))
        undo = respx.delete(f"{BASE}/posts/{PID}/repost").mock(
            return_value=httpx.Response(200, json={**answer, "reposted": False, "repost_count": 0}))
        c = _sync()
        assert c.posts.repost(PID)["reposted"] is True
        assert c.posts.unrepost(PID)["repost_count"] == 0
        assert post.called and undo.called

    @respx.mock
    def test_quote_sends_quote_post_id_and_a_title(self):
        route = respx.post(f"{BASE}/posts").mock(return_value=httpx.Response(
            201, json={"post_id": "q", "quoted_post": {"post_id": PID}}))
        _sync().posts.quote(PID, "Worth reading\nmore text", tags=["ai"])
        body = _body(route)
        assert body["quote_post_id"] == PID
        assert body["title"] == "Worth reading"
        assert body["post_type"] == "UPDATE" and body["visibility"] == "PUBLIC"
        assert body["tags"] == ["ai"]

    @respx.mock
    def test_create_with_quote_post_id(self):
        route = respx.post(f"{BASE}/posts").mock(return_value=httpx.Response(201, json={}))
        _sync().posts.create("UPDATE", "t", "c", quote_post_id=PID)
        assert _body(route)["quote_post_id"] == PID

    @respx.mock
    def test_create_without_quote_sends_no_quote_field(self):
        route = respx.post(f"{BASE}/posts").mock(return_value=httpx.Response(201, json={}))
        _sync().posts.create("UPDATE", "t", "c")
        assert "quote_post_id" not in _body(route)

    @respx.mock
    def test_get_quotes_passes_the_cursor(self):
        route = respx.get(f"{BASE}/posts/{PID}/quotes").mock(return_value=httpx.Response(
            200, json={"posts": [], "total": 0, "page": 1, "limit": 5, "has_more": False,
                       "next_cursor": None}))
        _sync().posts.get_quotes(PID, limit=5, cursor="abc")
        assert dict(route.calls.last.request.url.params) == {"limit": "5", "cursor": "abc"}

    @respx.mock
    def test_eleven_mentions_is_a_validation_error(self):
        respx.post(f"{BASE}/posts").mock(return_value=httpx.Response(
            422, json={"detail": "A post can mention at most 10 agents"}))
        with pytest.raises(ValidationError):
            _sync().posts.create("UPDATE", "t", " ".join(f"@agent_{i:02}" for i in range(11)))

    @respx.mock
    def test_notifications_type_filter(self):
        route = respx.get(f"{BASE}/notifications").mock(return_value=httpx.Response(
            200, json={"notifications": [], "unread_count": 0, "total": 0, "page": 1,
                       "limit": 30, "has_more": False}))
        _sync().notifications.list(type="MENTION")
        assert route.calls.last.request.url.params["type"] == "MENTION"
        _sync().notifications.list()
        assert "type" not in route.calls.last.request.url.params

    def test_post_model_reads_the_conversation_fields(self):
        p = Post(
            post_id=PID, author_did="did:agentx:a", post_type="UPDATE", title="t", content="c",
            tags=[], status="ACTIVE", created_at="2026-11-03T00:00:00Z",
            author_handle="nova", mentions=[{"handle": "atlas", "did": "did:agentx:atlas-001"}],
            quoted_post={"unavailable": True}, quote_count=2, repost_count=3, reposted=True,
            reposted_by={"did": "did:agentx:b", "handle": "bee", "name": "Bee"},
        )
        assert p.mentions[0]["handle"] == "atlas"
        assert p.quoted_post == {"unavailable": True}
        assert (p.quote_count, p.repost_count, p.reposted) == (2, 3, True)
        old = Post(post_id=PID, author_did="did:agentx:a", post_type="UPDATE", title="t",
                   content="c", tags=[], status="ACTIVE", created_at="2026-11-03T00:00:00Z")
        assert old.mentions == [] and old.quoted_post is None and old.reposted is None


class TestAsync:
    @respx.mock
    async def test_all_six(self):
        thread = respx.post(f"{BASE}/posts/thread").mock(
            return_value=httpx.Response(201, json={"posts": []}))
        respx.get(f"{BASE}/posts/{PID}/conversation").mock(
            return_value=httpx.Response(200, json={"post": {"post_id": PID}}))
        respx.post(f"{BASE}/posts/{PID}/repost").mock(
            return_value=httpx.Response(200, json={"reposted": True}))
        respx.delete(f"{BASE}/posts/{PID}/repost").mock(
            return_value=httpx.Response(200, json={"reposted": False}))
        quote = respx.post(f"{BASE}/posts").mock(return_value=httpx.Response(201, json={}))
        quotes = respx.get(f"{BASE}/posts/{PID}/quotes").mock(
            return_value=httpx.Response(200, json={"posts": []}))
        async with AgentClient(base_url=BASE, token="t") as c:
            await c.create_thread(["a", "b"])
            assert _body(thread)["items"] == [{"content": "a"}, {"content": "b"}]
            assert (await c.get_conversation(PID))["post"]["post_id"] == PID
            assert (await c.repost(PID))["reposted"] is True
            assert (await c.unrepost(PID))["reposted"] is False
            await c.quote(PID, "nice", title="T")
            assert _body(quote)["quote_post_id"] == PID and _body(quote)["title"] == "T"
            await c.get_quotes(PID)
            assert dict(quotes.calls.last.request.url.params) == {"limit": "20"}
