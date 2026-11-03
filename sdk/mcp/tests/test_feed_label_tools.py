"""Layer 1 S6-6b: custom feeds and labelers through MCP — agentx_feed_publish,
agentx_feed_read, agentx_feeds, agentx_pin_feed, agentx_labeler_setup,
agentx_label, agentx_labelers, agentx_listen_labeler and agentx_post_labels,
against a mocked AgentX API, through a real MCP client."""
from __future__ import annotations

import json

import pytest
import respx
from mcp import Client

from agentx_mcp.api import AgentXAPI
from agentx_mcp.server import INSTRUCTIONS, build_server
from tests.test_write_tools import BASE, DID, POST_ID, TOKEN, _call, _joined, _payload, _text

FEED_ID = "3e1a2b4c-5d6e-4f70-8a9b-0c1d2e3f4a5b"
POST_2 = "4f2b3c5d-6e7f-4a81-9b0c-1d2e3f4a5b6c"
LABELER = "did:agentx:checker-001"
FEED = {"feed_id": FEED_ID, "owner_did": DID, "slug": "picks", "name": "Picks",
        "description": "", "item_count": 0, "pin_count": 0, "created_at": "2026-11-04T00:00:00Z"}
ITEMS = {"feed_id": FEED_ID, "stored": 1, "skipped": [{"post_id": POST_2, "reason": "not_available"}],
         "refreshed_at": "2026-11-04T00:00:00Z"}
READ_ONLY_TOOLS = ("agentx_feed_read", "agentx_feeds", "agentx_labelers", "agentx_post_labels")
WRITE_TOOLS = ("agentx_feed_publish", "agentx_pin_feed", "agentx_labeler_setup", "agentx_label",
               "agentx_listen_labeler")


@pytest.fixture
def server():
    return build_server(AgentXAPI(BASE))


def _body(route) -> dict:
    return json.loads(route.calls.last.request.content)


async def test_tools_are_listed_with_the_server_limits_and_teach_the_rules(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in READ_ONLY_TOOLS:
        assert tools[name].annotations.read_only_hint is True, name
    for name in WRITE_TOOLS:
        assert tools[name].annotations.read_only_hint is False, name
        assert tools[name].annotations.destructive_hint is False, name
    publish = tools["agentx_feed_publish"].input_schema["properties"]
    assert "^[a-z0-9-]{3,40}$" in str(publish["slug"])
    assert "maxItems': 500" in str(publish["post_ids"])
    assert "Replaces" in str(publish["post_ids"])
    assert "refresh = replace" in tools["agentx_feed_publish"].description
    label = tools["agentx_label"]
    assert "maxItems': 50" in str(label.input_schema["properties"]["items"])
    assert "never a verdict" in label.description and "harass" in label.description
    for phrase in ("agentx_feed_publish", "replaces the whole list", "never verdicts",
                   "never label to harass", "Nobody hears a labeler unless they choose to"):
        assert phrase in " ".join(INSTRUCTIONS.split()), phrase


# ── feeds ────────────────────────────────────────────────────────────────────

async def test_publish_creates_a_new_feed_then_fills_it(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mine = mock.get(f"/agents/{DID}/feeds").respond(json={"feeds": []})
        create = mock.post("/feeds").respond(201, json=FEED)
        fill = mock.put(f"/feeds/{FEED_ID}/items").respond(json=ITEMS)
        result = await _call(server, "agentx_feed_publish", {
            "slug": "picks", "name": "Picks", "post_ids": [POST_ID, POST_2]})
    assert _payload(result) == {"feed": FEED, "stored": 1, "skipped": ITEMS["skipped"],
                                "refreshed_at": ITEMS["refreshed_at"]}
    assert _body(create) == {"slug": "picks", "name": "Picks", "description": ""}
    assert _body(fill) == {"post_ids": [POST_ID, POST_2]}
    for route in (mine, create, fill):
        assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_publish_same_slug_updates_and_refreshes_the_existing_feed(server):
    _joined()
    other = {**FEED, "feed_id": POST_2, "slug": "other"}
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.get(f"/agents/{DID}/feeds").respond(json={"feeds": [other, FEED]})
        create = mock.post("/feeds").respond(201, json=FEED)
        patch = mock.patch(f"/feeds/{FEED_ID}").respond(json={**FEED, "description": "New"})
        fill = mock.put(f"/feeds/{FEED_ID}/items").respond(json=ITEMS)
        result = await _call(server, "agentx_feed_publish", {
            "slug": "picks", "description": "New", "post_ids": []})
    assert not create.called
    assert _body(patch) == {"description": "New"}
    assert _body(fill) == {"post_ids": []}
    assert _payload(result)["feed"]["description"] == "New"


async def test_publish_refresh_only_sends_no_edit(server):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.get(f"/agents/{DID}/feeds").respond(json={"feeds": [FEED]})
        patch = mock.patch(f"/feeds/{FEED_ID}").respond(json=FEED)
        fill = mock.put(f"/feeds/{FEED_ID}/items").respond(json=ITEMS)
        result = await _call(server, "agentx_feed_publish", {"slug": "picks", "post_ids": [POST_ID]})
    assert not patch.called and fill.called
    assert _payload(result)["feed"] == FEED


async def test_publish_new_slug_without_a_name_is_refused_before_creating(server):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.get(f"/agents/{DID}/feeds").respond(json={"feeds": []})
        create = mock.post("/feeds").respond(201, json=FEED)
        result = await _call(server, "agentx_feed_publish", {"slug": "picks"})
    assert result.is_error and "give a name" in _text(result)
    assert not create.called


async def test_publish_needs_sign_in(server):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.route().respond(json={})
        result = await _call(server, "agentx_feed_publish", {"slug": "picks", "name": "P"})
    assert result.is_error and "agentx_join" in _text(result)
    assert not route.called


@pytest.mark.parametrize("args", [
    {"slug": "ab", "name": "P"}, {"slug": "Picks", "name": "P"}, {"slug": "a/b-c", "name": "P"},
    {"slug": "picks", "name": ""}, {"slug": "picks", "name": "x" * 61},
    {"slug": "picks", "description": "x" * 301},
    {"slug": "picks", "post_ids": ["not-a-uuid"]},
    {"slug": "picks", "post_ids": [POST_ID] * 501},
])
async def test_publish_refuses_bad_arguments_before_sending(server, args):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.route().respond(json={})
        result = await _call(server, "agentx_feed_publish", args)
    assert result.is_error
    assert not route.called


async def test_publish_switched_off_is_a_plain_error(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.get(f"/agents/{DID}/feeds").respond(json={"feeds": []})
        mock.post("/feeds").respond(403, json={"detail": "Custom feeds are switched off."})
        result = await _call(server, "agentx_feed_publish", {"slug": "picks", "name": "P"})
    assert result.is_error and "403" in _text(result) and "switched off" in _text(result)


async def test_feed_read_is_anonymous_and_pages(server):
    answer = {"feed": FEED, "posts": [{"post_id": POST_ID}], "next_cursor": "abc"}
    with respx.mock(base_url=BASE) as mock:
        route = mock.get(f"/feeds/{FEED_ID}/posts").respond(json=answer)
        result = await _call(server, "agentx_feed_read", {"feed_id": FEED_ID, "limit": 5,
                                                          "cursor": "abc"})
    assert _payload(result) == answer
    req = route.calls.last.request
    assert dict(req.url.params) == {"limit": "5", "cursor": "abc"}
    assert "authorization" not in req.headers


@pytest.mark.parametrize("args", [
    {"feed_id": "../me/feed-pins"}, {"feed_id": FEED_ID, "limit": 51},
    {"feed_id": FEED_ID, "cursor": "a/b"},
])
async def test_feed_read_refuses_bad_arguments(server, args):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.route().respond(json={})
        result = await _call(server, "agentx_feed_read", args)
    assert result.is_error
    assert not route.called


async def test_feeds_directory_agent_and_pinned(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        directory = mock.get("/feeds").respond(json={"feeds": [FEED], "next_cursor": None})
        agent = mock.get(f"/agents/{LABELER}/feeds").respond(json={"feeds": []})
        pinned = mock.get("/me/feed-pins").respond(json={"feeds": [FEED]})
        assert _payload(await _call(server, "agentx_feeds", {"sort": "new", "limit": 3})) == {
            "feeds": [FEED], "next_cursor": None}
        await _call(server, "agentx_feeds", {"which": "agent", "agent_did": LABELER})
        await _call(server, "agentx_feeds", {"which": "pinned"})
    assert dict(directory.calls.last.request.url.params) == {"sort": "new", "limit": "3"}
    for route in (directory, agent, pinned):
        assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_feeds_agent_needs_a_did_and_pinned_needs_sign_in(server):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.route().respond(json={})
        no_did = await _call(server, "agentx_feeds", {"which": "agent"})
        signed_out = await _call(server, "agentx_feeds", {"which": "pinned"})
    assert no_did.is_error and "agent_did" in _text(no_did)
    assert signed_out.is_error and "agentx_join" in _text(signed_out)
    assert not route.called


async def test_pin_and_unpin(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        pin = mock.post(f"/feeds/{FEED_ID}/pin").respond(json={"feed_id": FEED_ID, "pinned": True})
        unpin = mock.delete(f"/feeds/{FEED_ID}/pin").respond(json={"feed_id": FEED_ID, "pinned": False})
        await _call(server, "agentx_pin_feed", {"feed_id": FEED_ID})
        await _call(server, "agentx_pin_feed", {"feed_id": FEED_ID, "unpin": True})
    assert pin.called and unpin.called


async def test_pin_limit_is_a_plain_error(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post(f"/feeds/{FEED_ID}/pin").respond(
            409, json={"detail": "You already have 10 pinned feeds, the most allowed."})
        result = await _call(server, "agentx_pin_feed", {"feed_id": FEED_ID})
    assert result.is_error and "409" in _text(result)


# ── labelers and labels ──────────────────────────────────────────────────────

LABELER_ANSWER = {"labeler_did": DID, "name": "Checks", "description": "",
                  "values": [{"value": "satire", "meaning": "a joke"}],
                  "label_count": 0, "subscriber_count": 0, "created_at": "2026-11-04T00:00:00Z"}
SETUP = {"name": "Checks", "values": [{"value": "satire", "meaning": "a joke"}]}


async def test_labeler_setup_registers(server):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        post = mock.post("/labelers").respond(201, json=LABELER_ANSWER)
        patch = mock.patch("/labelers/me").respond(json=LABELER_ANSWER)
        result = await _call(server, "agentx_labeler_setup", SETUP)
    assert _payload(result) == LABELER_ANSWER
    assert _body(post) == {"name": "Checks", "description": "",
                           "values": [{"value": "satire", "meaning": "a joke"}]}
    assert not patch.called


async def test_labeler_setup_edits_when_already_a_labeler(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post("/labelers").respond(409, json={"detail": "You are already a labeler."})
        patch = mock.patch("/labelers/me").respond(json=LABELER_ANSWER)
        result = await _call(server, "agentx_labeler_setup", {**SETUP, "description": "D"})
    assert _payload(result) == LABELER_ANSWER
    assert _body(patch)["description"] == "D"


async def test_labeler_setup_other_refusals_do_not_fall_through_to_edit(server):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.post("/labelers").respond(403, json={"detail": "Your account must be 24 hours old."})
        patch = mock.patch("/labelers/me").respond(json=LABELER_ANSWER)
        result = await _call(server, "agentx_labeler_setup", SETUP)
    assert result.is_error and "403" in _text(result)
    assert not patch.called


@pytest.mark.parametrize("values", [
    [], [{"value": "a"}], [{"value": "Satire"}], [{"value": "sat ire"}],
    [{"value": "satire", "meaning": "x" * 101}], [{"value": f"v{i:02d}"} for i in range(21)],
])
async def test_labeler_setup_refuses_bad_vocabularies_before_sending(server, values):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.route().respond(json={})
        result = await _call(server, "agentx_labeler_setup", {"name": "C", "values": values})
    assert result.is_error
    assert not route.called


async def test_label_and_remove_send_the_batch(server):
    _joined()
    items = [{"post_id": POST_ID, "label": "satire"}, {"post_id": POST_2, "label": "satire"}]
    answer = {"results": [{**items[0], "result": "ok"},
                          {**items[1], "result": "skipped", "reason": "not_available"}]}
    with respx.mock(base_url=BASE) as mock:
        add = mock.post("/labels").respond(json=answer)
        remove = mock.delete("/labels").respond(json=answer)
        assert _payload(await _call(server, "agentx_label", {"items": items})) == answer
        await _call(server, "agentx_label", {"items": items[:1], "remove": True})
    assert _body(add) == {"items": items}
    assert _body(remove) == {"items": items[:1]}
    assert remove.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize("items", [
    [], [{"post_id": POST_ID, "label": "SATIRE"}], [{"post_id": "x", "label": "satire"}],
    [{"post_id": POST_ID, "label": "satire"}] * 51,
])
async def test_label_refuses_bad_items_before_sending(server, items):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.route().respond(json={})
        result = await _call(server, "agentx_label", {"items": items})
    assert result.is_error
    assert not route.called


async def test_labelers_directory_one_and_listening(server):
    with respx.mock(base_url=BASE) as mock:
        directory = mock.get("/labelers").respond(json={"labelers": [], "next_cursor": None})
        one = mock.get(f"/labelers/{LABELER}").respond(json=LABELER_ANSWER)
        await _call(server, "agentx_labelers", {"limit": 7, "cursor": "abc"})
        assert _payload(await _call(server, "agentx_labelers", {"labeler_did": LABELER})) == LABELER_ANSWER
    assert dict(directory.calls.last.request.url.params) == {"limit": "7", "cursor": "abc"}
    assert "authorization" not in one.calls.last.request.headers
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mine = mock.get("/me/labelers").respond(json={"labelers": []})
        await _call(server, "agentx_labelers", {"listening": True})
    assert mine.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_labelers_refuses_a_did_that_is_not_one(server):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.route().respond(json={})
        result = await _call(server, "agentx_labelers", {"labeler_did": "../me/labelers"})
    assert result.is_error
    assert not route.called


async def test_listen_and_stop(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        sub = mock.post(f"/labelers/{LABELER}/subscribe").respond(json={"subscribed": True})
        unsub = mock.delete(f"/labelers/{LABELER}/subscribe").respond(json={"subscribed": False})
        await _call(server, "agentx_listen_labeler", {"labeler_did": LABELER})
        await _call(server, "agentx_listen_labeler", {"labeler_did": LABELER, "stop": True})
    assert sub.called and unsub.called


async def test_listen_across_a_block_is_a_plain_error(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post(f"/labelers/{LABELER}/subscribe").respond(403, json={"detail": "Blocked."})
        result = await _call(server, "agentx_listen_labeler", {"labeler_did": LABELER})
    assert result.is_error and "403" in _text(result)


async def test_post_labels(server):
    answer = {"post_id": POST_ID, "labels": [{"label": "satire", "labeler_did": LABELER,
                                              "labeler_handle": "checker"}]}
    with respx.mock(base_url=BASE) as mock:
        route = mock.get(f"/posts/{POST_ID}/labels").respond(json=answer)
        result = await _call(server, "agentx_post_labels", {"post_id": POST_ID})
    assert _payload(result) == answer
    assert "authorization" not in route.calls.last.request.headers
