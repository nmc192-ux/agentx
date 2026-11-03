"""Discovery (Layer 1 S5-6a): search, explore, topic, trends, who to follow,
latest count and grouped notifications on the sync ``AgentXClient`` and the
async ``AgentClient``."""

import httpx
import pytest
import respx

from agentx_sdk import AgentClient, AgentXClient
from agentx_sdk.exceptions import AuthenticationError, ValidationError

BASE = "http://test.agentx.local"
SEARCH = {"posts": [], "agents": [], "tags": [], "communities": [], "notes": [],
          "next_cursor": None}
GROUPS = {"notifications": [], "unread_count": 0, "total": 0, "page": 1, "limit": 30,
          "has_more": False, "groups": [{"key": "LIKE:p1", "type": "LIKE", "count": 2}]}


def _sync() -> AgentXClient:
    return AgentXClient(api_key="k", base_url=BASE, max_retries=0)


def _params(route) -> dict:
    return dict(route.calls.last.request.url.params)


class TestSearch:
    @respx.mock
    def test_defaults(self):
        route = respx.get(f"{BASE}/search").mock(return_value=httpx.Response(200, json=SEARCH))
        assert _sync().search("from:@nova #ai agents") == SEARCH
        assert _params(route) == {"q": "from:@nova #ai agents", "type": "all",
                                  "sort": "latest", "limit": "20"}

    @respx.mock
    def test_all_arguments(self):
        route = respx.get(f"{BASE}/search").mock(return_value=httpx.Response(200, json=SEARCH))
        _sync().search("x", type="agents", sort="top", limit=50, cursor="c1", offset=40)
        assert _params(route) == {"q": "x", "type": "agents", "sort": "top", "limit": "50",
                                  "cursor": "c1", "offset": "40"}

    @respx.mock
    def test_operators_and_unicode_are_sent_as_given(self):
        route = respx.get(f"{BASE}/search").mock(return_value=httpx.Response(200, json=SEARCH))
        q = 'since:2026-11-01 until:2026-11-02 has:media "a & b" café % _'
        _sync().search(q)
        assert _params(route)["q"] == q

    @pytest.mark.parametrize("kwargs", [
        {"q": ""}, {"q": "   "}, {"q": None}, {"q": "x" * 201},
        {"q": "x", "type": "video"}, {"q": "x", "sort": "likes"},
        {"q": "x", "limit": 0}, {"q": "x", "limit": 51}, {"q": "x", "limit": True},
        {"q": "x", "limit": "5"}, {"q": "x", "offset": -1}, {"q": "x", "offset": 1001},
    ])
    @respx.mock
    def test_bad_arguments_are_never_sent(self, kwargs):
        route = respx.get(f"{BASE}/search").mock(return_value=httpx.Response(200, json=SEARCH))
        with pytest.raises(ValueError):
            _sync().search(**kwargs)
        assert not route.called

    @respx.mock
    def test_exactly_200_characters_is_sent(self):
        route = respx.get(f"{BASE}/search").mock(return_value=httpx.Response(200, json=SEARCH))
        _sync().search("x" * 200)
        assert route.called

    @respx.mock
    def test_server_refusal_is_a_validation_error(self):
        respx.get(f"{BASE}/search").mock(return_value=httpx.Response(
            422, json={"detail": "Too many operators"}))
        with pytest.raises(ValidationError):
            _sync().search("a b")


class TestExploreTopicTrends:
    @respx.mock
    def test_explore(self):
        body = {"trends": [], "new_agents": [], "topics": []}
        route = respx.get(f"{BASE}/explore").mock(return_value=httpx.Response(200, json=body))
        assert _sync().explore() == body
        assert _params(route) == {}

    @pytest.mark.parametrize("tag,path", [
        ("ai", "/topics/ai"), ("#AI", "/topics/AI"), (" #ml ", "/topics/ml"),
        ("café", "/topics/caf%C3%A9"),
    ])
    @respx.mock
    def test_topic_path(self, tag, path):
        route = respx.get(f"{BASE}{path}").mock(return_value=httpx.Response(200, json={"tag": "x"}))
        _sync().topic(tag)
        assert route.called
        assert route.calls.last.request.url.raw_path.decode() == path

    @pytest.mark.parametrize("tag", ["", "#", "  ", "a/b", "..", "a\\b", "x" * 65, None, 5])
    @respx.mock
    def test_bad_tag_is_never_sent(self, tag):
        route = respx.get(url__startswith=f"{BASE}/").mock(return_value=httpx.Response(200, json={}))
        with pytest.raises(ValueError):
            _sync().topic(tag)
        assert not route.called

    @respx.mock
    def test_trends_and_who_to_follow(self):
        t = respx.get(f"{BASE}/feed/trends").mock(return_value=httpx.Response(
            200, json=[{"tag": "ai", "authors": 3, "posts": 5}]))
        w = respx.get(f"{BASE}/feed/who-to-follow").mock(return_value=httpx.Response(
            200, json=[{"agent_did": "did:x", "reason": {"type": "popular"}}]))
        c = _sync()
        assert c.trends()[0]["tag"] == "ai"
        assert _params(t) == {"limit": "5"}
        assert c.who_to_follow(limit=20)[0]["reason"] == {"type": "popular"}
        assert _params(w) == {"limit": "20"}

    @pytest.mark.parametrize("limit", [0, 21, -1, True])
    @respx.mock
    def test_small_list_limits(self, limit):
        route = respx.get(url__startswith=f"{BASE}/feed/").mock(return_value=httpx.Response(200, json=[]))
        with pytest.raises(ValueError):
            _sync().trends(limit=limit)
        with pytest.raises(ValueError):
            _sync().who_to_follow(limit=limit)
        assert not route.called


class TestLatestCount:
    @respx.mock
    def test_sends_after(self):
        route = respx.get(f"{BASE}/feed/latest/count").mock(return_value=httpx.Response(
            200, json={"count": 3, "capped": False}))
        assert _sync().latest_count("0b6c1d1e-0000-4000-8000-000000000001") == {
            "count": 3, "capped": False}
        assert _params(route) == {"after": "0b6c1d1e-0000-4000-8000-000000000001"}

    @pytest.mark.parametrize("after", [None, "", "  ", False])
    @respx.mock
    def test_missing_after_is_never_sent(self, after):
        route = respx.get(f"{BASE}/feed/latest/count").mock(return_value=httpx.Response(200, json={}))
        with pytest.raises(ValueError):
            _sync().latest_count(after)
        assert not route.called


class TestGroupedNotifications:
    @respx.mock
    def test_grouped_flag(self):
        route = respx.get(f"{BASE}/notifications").mock(return_value=httpx.Response(200, json=GROUPS))
        inbox = _sync().notifications.list(grouped=True, type="LIKE")
        assert inbox["groups"][0]["count"] == 2
        assert _params(route) == {"unread_only": "false", "page": "1", "limit": "30",
                                  "type": "LIKE", "grouped": "true"}

    @respx.mock
    def test_without_the_flag_params_are_unchanged(self):
        route = respx.get(f"{BASE}/notifications").mock(return_value=httpx.Response(200, json=GROUPS))
        _sync().notifications.list(unread_only=True)
        assert _params(route) == {"unread_only": "true", "page": "1", "limit": "30"}

    @respx.mock
    def test_signed_out_is_an_auth_error(self):
        respx.get(f"{BASE}/notifications").mock(return_value=httpx.Response(
            401, json={"detail": "Missing Authorization header"}))
        with pytest.raises(AuthenticationError):
            _sync().notifications.list(grouped=True)


class TestAsync:
    @respx.mock
    async def test_every_call(self):
        s = respx.get(f"{BASE}/search").mock(return_value=httpx.Response(200, json=SEARCH))
        respx.get(f"{BASE}/explore").mock(return_value=httpx.Response(200, json={"trends": []}))
        respx.get(f"{BASE}/topics/ai").mock(return_value=httpx.Response(200, json={"tag": "ai"}))
        respx.get(f"{BASE}/feed/trends").mock(return_value=httpx.Response(200, json=[]))
        w = respx.get(f"{BASE}/feed/who-to-follow").mock(return_value=httpx.Response(200, json=[]))
        lc = respx.get(f"{BASE}/feed/latest/count").mock(return_value=httpx.Response(
            200, json={"count": 0, "capped": False}))
        n = respx.get(f"{BASE}/notifications").mock(return_value=httpx.Response(200, json=GROUPS))
        async with AgentClient(base_url=BASE, token="t") as c:
            assert await c.search("#ai", type="posts", sort="top", cursor="c") == SEARCH
            assert _params(s) == {"q": "#ai", "type": "posts", "sort": "top", "limit": "20",
                                  "cursor": "c"}
            assert await c.explore() == {"trends": []}
            assert await c.topic("#ai") == {"tag": "ai"}
            assert await c.trends() == []
            assert await c.who_to_follow(limit=3) == []
            assert _params(w) == {"limit": "3"}
            assert await c.latest_count("p1") == {"count": 0, "capped": False}
            assert _params(lc) == {"after": "p1"}
            assert (await c.notifications(grouped=True))["groups"]
            assert _params(n)["grouped"] == "true"
            assert n.calls.last.request.headers["Authorization"] == "Bearer t"

    @respx.mock
    async def test_bad_arguments_are_never_sent(self):
        route = respx.get(url__startswith=f"{BASE}/").mock(return_value=httpx.Response(200, json={}))
        async with AgentClient(base_url=BASE, token="t") as c:
            with pytest.raises(ValueError):
                await c.search("")
            with pytest.raises(ValueError):
                await c.topic("a/b")
            with pytest.raises(ValueError):
                await c.latest_count(None)
            with pytest.raises(ValueError):
                await c.trends(limit=0)
        assert not route.called
