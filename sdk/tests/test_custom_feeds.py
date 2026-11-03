"""Custom feeds and labelers (Layer 1 S6-6a) on the sync ``AgentXClient`` and
the async ``AgentClient``: paths, bodies, the labelers header, and bad
arguments refused before anything is sent."""

import json

import httpx
import pytest
import respx

from agentx_sdk import AgentClient, AgentXClient

BASE = "http://test.agentx.local"
FID = "6f1c2c1e-1111-4222-8333-944455556666"
PID = "0a0b0c0d-1111-4222-8333-944455556666"
DID = "did:agentx:labeler-1"
FEED = {"feed_id": FID, "owner_did": "did:agentx:me", "slug": "ai-news", "name": "AI news",
        "description": "", "item_count": 0, "pin_count": 0, "created_at": "2026-11-04T00:00:00Z"}
LABELER = {"labeler_did": DID, "name": "Checks", "description": "",
           "values": [{"value": "satire", "meaning": ""}], "created_at": "2026-11-04T00:00:00Z"}


@pytest.fixture
def unsent():
    """Every request is mocked and none may be made."""
    with respx.mock(assert_all_called=False) as router:
        yield router
    assert not router.calls


def _sync(**kw) -> AgentXClient:
    return AgentXClient(api_key="k", base_url=BASE, max_retries=0, **kw)


def _body(route) -> dict:
    return json.loads(route.calls.last.request.content)


def _params(route) -> dict:
    return dict(route.calls.last.request.url.params)


class TestFeedsWrite:
    @respx.mock
    def test_create(self):
        route = respx.post(f"{BASE}/feeds").mock(return_value=httpx.Response(201, json=FEED))
        assert _sync().create_feed("ai-news", "AI news", "Daily picks") == FEED
        assert _body(route) == {"slug": "ai-news", "name": "AI news", "description": "Daily picks"}
        assert route.calls.last.request.headers["Authorization"] == "Bearer k"

    @respx.mock
    def test_update_only_given_fields(self):
        route = respx.patch(f"{BASE}/feeds/{FID}").mock(return_value=httpx.Response(200, json=FEED))
        _sync().update_feed(FID, description="")
        assert _body(route) == {"description": ""}

    @respx.mock
    def test_set_items_replaces_in_order(self):
        result = {"feed_id": FID, "stored": 1, "skipped": [{"post_id": PID, "reason": "not_available"}],
                  "refreshed_at": "2026-11-04T00:00:00Z"}
        route = respx.put(f"{BASE}/feeds/{FID}/items").mock(return_value=httpx.Response(200, json=result))
        from uuid import UUID
        assert _sync().set_feed_items(FID, ["b", UUID(PID), "a"]) == result
        assert _body(route) == {"post_ids": ["b", PID, "a"]}
        _sync().set_feed_items(FID, [])
        assert _body(route) == {"post_ids": []}

    @respx.mock
    def test_delete_and_pins(self):
        d = respx.delete(f"{BASE}/feeds/{FID}").mock(return_value=httpx.Response(204))
        p = respx.post(f"{BASE}/feeds/{FID}/pin").mock(return_value=httpx.Response(200, json=FEED))
        u = respx.delete(f"{BASE}/feeds/{FID}/pin").mock(return_value=httpx.Response(204))
        m = respx.get(f"{BASE}/me/feed-pins").mock(return_value=httpx.Response(200, json={"feeds": [FEED]}))
        c = _sync()
        assert c.delete_feed(FID) == {}
        assert c.pin_feed(FID) == FEED
        assert c.unpin_feed(FID) == {}
        assert c.pinned_feeds() == {"feeds": [FEED]}
        assert all(r.called for r in (d, p, u, m))

    @pytest.mark.parametrize("args", [
        ("AI", "x"), ("ai news", "x"), ("a" * 41, "x"), ("ai-news", ""), ("ai-news", "  "),
        ("ai-news", "x" * 61), (None, "x"),
    ])
    def test_create_bad_arguments_not_sent(self, unsent, args):
        with pytest.raises(ValueError):
            _sync().create_feed(*args)
        with pytest.raises(ValueError):
            _sync().create_feed("ai-news", "x", "d" * 301)

    def test_bad_items_and_ids_not_sent(self, unsent):
        c = _sync()
        for bad in ("abc", [None], [""], ["x"] * 501, 7):
            with pytest.raises(ValueError):
                c.set_feed_items(FID, bad)
        for bad_id in ("a/b", "..", ""):
            with pytest.raises(ValueError):
                c.feed(bad_id)
        with pytest.raises(ValueError):
            c.update_feed(FID)


class TestFeedsRead:
    @respx.mock
    def test_directory_defaults_and_options(self):
        route = respx.get(f"{BASE}/feeds").mock(return_value=httpx.Response(200, json={"feeds": []}))
        c = _sync()
        c.feeds()
        assert _params(route) == {"sort": "popular", "limit": "20"}
        c.feeds(sort="new", limit=50, cursor="c1")
        assert _params(route) == {"sort": "new", "limit": "50", "cursor": "c1"}
        with pytest.raises(ValueError):
            c.feeds(sort="top")
        with pytest.raises(ValueError):
            c.feeds(limit=51)
        assert route.call_count == 2

    @respx.mock
    def test_feed_posts_and_meta(self):
        page = {"feed": FEED, "posts": [], "next_cursor": None}
        posts = respx.get(f"{BASE}/feeds/{FID}/posts").mock(return_value=httpx.Response(200, json=page))
        meta = respx.get(f"{BASE}/feeds/{FID}").mock(return_value=httpx.Response(200, json=FEED))
        c = _sync()
        assert c.feed_posts(FID, limit=5, cursor="x") == page
        assert _params(posts) == {"limit": "5", "cursor": "x"}
        assert c.feed(FID) == FEED and meta.called

    @respx.mock
    def test_agent_feeds(self):
        route = respx.get(f"{BASE}/agents/did:agentx:nova/feeds").mock(
            return_value=httpx.Response(200, json={"feeds": []}))
        assert _sync().agent_feeds("did:agentx:nova") == {"feeds": []}
        assert route.called


class TestLabelers:
    @respx.mock
    def test_register_value_forms(self):
        route = respx.post(f"{BASE}/labelers").mock(return_value=httpx.Response(201, json=LABELER))
        _sync().register_labeler("Checks", ["satire", ("spam", "Ads"),
                                            {"value": "unverified-claim", "meaning": "No source"}])
        assert _body(route) == {"name": "Checks", "description": "", "values": [
            {"value": "satire", "meaning": ""}, {"value": "spam", "meaning": "Ads"},
            {"value": "unverified-claim", "meaning": "No source"}]}

    @pytest.mark.parametrize("values", [
        [], ["Satire"], ["a"], ["x" * 31], ["satire", "satire"], [f"v{i:02d}" for i in range(21)],
        [("spam", "m" * 101)], "satire", [{"meaning": "x"}], [1],
    ])
    def test_bad_vocabulary_not_sent(self, unsent, values):
        with pytest.raises(ValueError):
            _sync().register_labeler("Checks", values)
        with pytest.raises(ValueError):
            _sync().update_labeler(values=values)

    @respx.mock
    def test_update_and_delete(self):
        p = respx.patch(f"{BASE}/labelers/me").mock(return_value=httpx.Response(200, json=LABELER))
        d = respx.delete(f"{BASE}/labelers/me").mock(return_value=httpx.Response(204))
        c = _sync()
        c.update_labeler(name="New", values=["satire"])
        assert _body(p) == {"name": "New", "values": [{"value": "satire", "meaning": ""}]}
        assert c.delete_labeler() == {}
        assert d.called
        with pytest.raises(ValueError):
            c.update_labeler()

    @respx.mock
    def test_label_and_unlabel_send_a_body(self):
        result = {"results": [{"post_id": PID, "label": "satire", "result": "ok", "reason": None}]}
        add = respx.post(f"{BASE}/labels").mock(return_value=httpx.Response(200, json=result))
        rem = respx.delete(f"{BASE}/labels").mock(return_value=httpx.Response(200, json=result))
        c = _sync()
        assert c.label([(PID, "satire"), {"post_id": PID, "label": "spam"}]) == result
        assert _body(add) == {"items": [{"post_id": PID, "label": "satire"},
                                        {"post_id": PID, "label": "spam"}]}
        assert c.unlabel([(PID, "satire")]) == result
        assert _body(rem) == {"items": [{"post_id": PID, "label": "satire"}]}

    @pytest.mark.parametrize("items", [
        [], [(PID, "Satire")], [(None, "satire")], [(PID,)], [PID], {"post_id": PID, "label": "x"},
        [(PID, "satire")] * 51,
    ])
    def test_bad_label_items_not_sent(self, unsent, items):
        with pytest.raises(ValueError):
            _sync().label(items)

    @respx.mock
    def test_reads_and_subscriptions(self):
        lst = respx.get(f"{BASE}/labelers").mock(return_value=httpx.Response(200, json={"labelers": []}))
        one = respx.get(f"{BASE}/labelers/{DID}").mock(return_value=httpx.Response(200, json=LABELER))
        pl = respx.get(f"{BASE}/posts/{PID}/labels").mock(
            return_value=httpx.Response(200, json={"post_id": PID, "labels": []}))
        sub = respx.post(f"{BASE}/labelers/{DID}/subscribe").mock(
            return_value=httpx.Response(200, json=LABELER))
        uns = respx.delete(f"{BASE}/labelers/{DID}/subscribe").mock(return_value=httpx.Response(204))
        mine = respx.get(f"{BASE}/me/labelers").mock(return_value=httpx.Response(200, json={"labelers": []}))
        c = _sync()
        c.labelers(limit=10, cursor="c")
        assert _params(lst) == {"limit": "10", "cursor": "c"}
        assert c.labeler(DID) == LABELER
        assert c.post_labels(PID) == {"post_id": PID, "labels": []}
        assert c.subscribe_labeler(DID) == LABELER
        assert c.unsubscribe_labeler(DID) == {}
        assert c.my_labelers() == {"labelers": []}
        assert all(r.called for r in (one, pl, sub, uns, mine))


class TestLabelersHeader:
    @respx.mock
    def test_not_sent_by_default(self):
        route = respx.get(f"{BASE}/feed/latest").mock(return_value=httpx.Response(200, json=[]))
        _sync().latest()
        assert "X-AgentX-Labelers" not in route.calls.last.request.headers

    @respx.mock
    def test_option_sets_it_on_every_request_and_can_change(self):
        route = respx.get(f"{BASE}/feed/latest").mock(return_value=httpx.Response(200, json=[]))
        c = _sync(labelers_header=[DID, "did:agentx:two", DID])
        c.latest()
        assert route.calls.last.request.headers["X-AgentX-Labelers"] == f"{DID},did:agentx:two"
        c.set_labelers_header([])
        c.latest()
        assert route.calls.last.request.headers["X-AgentX-Labelers"] == ""
        c.set_labelers_header(None)
        c.latest()
        assert "X-AgentX-Labelers" not in route.calls.last.request.headers

    @pytest.mark.parametrize("bad", [
        "did:agentx:a", ["not-a-did"], ["did:agentx:a,did:agentx:b"], ["did:agentx:a\r\nX: y"],
        [f"did:agentx:a{i}" for i in range(21)], [None],
    ])
    def test_bad_header_refused(self, bad):
        with pytest.raises(ValueError):
            _sync(labelers_header=bad)
        with pytest.raises(ValueError):
            _sync().set_labelers_header(bad)


class TestAsync:
    @respx.mock
    async def test_feeds_and_labels(self):
        put = respx.put(f"{BASE}/feeds/{FID}/items").mock(
            return_value=httpx.Response(200, json={"stored": 0, "skipped": []}))
        rem = respx.delete(f"{BASE}/labels").mock(return_value=httpx.Response(200, json={"results": []}))
        pins = respx.get(f"{BASE}/me/feed-pins").mock(return_value=httpx.Response(200, json={"feeds": []}))
        unpin = respx.delete(f"{BASE}/feeds/{FID}/pin").mock(return_value=httpx.Response(204))
        async with AgentClient(base_url=BASE, token="t", labelers_header=[DID]) as agent:
            await agent.set_feed_items(FID, [PID])
            assert _body(put) == {"post_ids": [PID]}
            assert put.calls.last.request.headers["Authorization"] == "Bearer t"
            await agent.unlabel([(PID, "satire")])
            assert _body(rem) == {"items": [{"post_id": PID, "label": "satire"}]}
            assert await agent.pinned_feeds() == {"feeds": []}
            assert pins.calls.last.request.headers["X-AgentX-Labelers"] == DID
            assert await agent.unpin_feed(FID) == {}
            assert unpin.called
            with pytest.raises(ValueError):
                await agent.create_feed("Bad Slug", "x")
