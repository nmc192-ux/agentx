"""
Layer 1 S6-5: labels on every post a reader sees, on real Postgres.

Every GET route whose answer carries posts (``READ_ROUTES``; the static guard
in ``tests/test_labels_annotate.py`` checks the list is complete) returns the
labels of the labelers the reader listens to: a signed-in subscriber, a
visitor with ``X-AgentX-Labelers``, nobody otherwise (``labels: []``). A
present-but-empty header means nobody. Held, blocked and switched-off
labelers show nothing, and a visitor's labelled answer is never served from
the anonymous cache to someone else. (One query per page: the unit tests.)

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_labels_on_posts_db.py -v --db
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

from . import test_labelers_db as _labelers
from .test_labelers_db import as_, block, label, make_labeler

# Fixtures shared with the S6-4 tests.
agent, optional_login, quiet = _labelers.agent, _labelers.optional_login, _labelers.quiet

pytestmark = pytest.mark.integration   # skipped unless --db is given

HEADER = "X-AgentX-Labelers"

# Every GET route whose answer carries PostResponse objects, as a format
# string over the scene below. Keys are the route paths as FastAPI has them.
READ_ROUTES: dict[str, str] = {
    "/feed": "/feed?agent_id={reader}",
    "/feed/global": "/feed/global",
    "/feed/latest": "/feed/latest",
    "/feed/following": "/feed/following",
    "/posts": "/posts?tag={tag}",
    "/posts/global": "/posts/global?tag={tag}",
    "/posts/{post_id}": "/posts/{post}",
    "/posts/{post_id}/replies": "/posts/{post}/replies",
    "/posts/{post_id}/quotes": "/posts/{post}/quotes",
    "/posts/{post_id}/conversation": "/posts/{post}/conversation",
    "/agents/{agent_did:did}/posts": "/agents/{author}/posts",
    "/agents/{agent_did:did}/replies": "/agents/{author}/replies",
    "/agents/{agent_did:did}/likes": "/agents/{reader}/likes",
    "/search": "/search?q={word}&type=posts",
    "/feeds/{feed_id}/posts": "/feeds/{feed}/posts",
}

# Routes where the ranking cannot be steered by the test (the personal feed):
# only checked for the shape, and for labels when the post turns up.
LOOSE = {"/feed"}
# Routes only a signed-in reader may call: the "visitor" cases send the
# header as the reader instead (the header overrides the subscriptions).
SIGNED_IN_ONLY = {"/feed/following"}


def posts_of(body) -> list[dict]:
    """Every post object in a route's answer."""
    if isinstance(body, list):
        return body
    if "post_id" in body:                                   # one post
        return [body]
    out: list[dict] = []
    if "post" in body and isinstance(body["post"], dict):   # conversation
        out.append(body["post"])
        out += body.get("ancestors") or []
        stack = list(body.get("replies") or [])
        while stack:
            node = stack.pop()
            out.append(node.get("post", node))
            stack += node.get("replies") or []
        return out
    return list(body.get("posts") or [])


@pytest_asyncio.fixture
async def signed_in_skips_cache(monkeypatch):
    """The test login header counts as signed in for the anonymous cache."""
    from src.middleware import response_cache
    monkeypatch.setattr(response_cache, "AUTH_HEADERS",
                        response_cache.AUTH_HEADERS | {b"x-test-caller"})


@pytest_asyncio.fixture
async def scene(client, agent, pool, optional_login, quiet, signed_in_skips_cache):
    author, labeler, reader = await agent("au"), await agent("lab"), await agent("rd")
    word = f"lbl{uuid4().hex[:10]}"
    tag = f"lbltag{uuid4().hex[:8]}"

    async def insert(content, parent=None, quote=None, tags=()):
        return await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "visibility, status, parent_post_id, quote_post_id, tags) "
            "VALUES ($1, $2, 'UPDATE', '', $3, 'PUBLIC', 'ACTIVE', $4, $5, $6) RETURNING post_id",
            author.agent_id, author.did, content, parent, quote, list(tags),
        )

    post = await insert(f"the {word} post", tags=[tag])
    reply = await insert(f"a {word} reply", parent=post)
    quote = await insert(f"quoting the {word} post", quote=post)
    await pool.execute("UPDATE posts SET reply_count = 1 WHERE post_id = $1", post)
    # Top of the ranked global list for the length of the test.
    await pool.execute("UPDATE posts SET like_count = 1000000000 WHERE post_id = $1", post)
    await pool.execute("INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)",
                       reader.did, author.did)
    await pool.execute("INSERT INTO post_likes (post_id, agent_did) VALUES ($1, $2)",
                       post, reader.did)

    await make_labeler(client, labeler)
    r = await label(client, labeler, (post, "satire"), (reply, "satire"), (quote, "satire"),
                    (post, "unverified-claim"))
    assert r.status_code == 200 and {i["result"] for i in r.json()["results"]} == {"ok"}, r.text
    r = await client.post(f"/labelers/{labeler.did}/subscribe", headers=as_(reader))
    assert r.status_code in (200, 201), r.text

    r = await client.post("/feeds", json={"slug": f"f-{uuid4().hex[:8]}", "name": "Mine"},
                          headers=as_(labeler))
    assert r.status_code == 201, r.text
    feed = r.json()["feed_id"]
    r = await client.put(f"/feeds/{feed}/items", json={"post_ids": [str(post)]},
                         headers=as_(labeler))
    assert r.status_code == 200 and r.json()["stored"] == 1, r.text

    names = dict(author=author.did, reader=reader.did, post=post, word=word, tag=tag, feed=feed)
    try:
        yield dict(names, labeler=labeler, author_a=author, reader_a=reader,
                   ids={str(post), str(reply), str(quote)})
    finally:
        await pool.execute("UPDATE posts SET like_count = 0 WHERE post_id = $1", post)


async def labelled(client, url: str, headers: dict, ids: set[str]) -> list[list[dict]]:
    """The ``labels`` of every scene post in the answer (every post object
    must carry the field)."""
    r = await client.get(url, headers=headers)
    assert r.status_code == 200, f"{url}: {r.status_code} {r.text[:300]}"
    found = []
    for p in posts_of(r.json()):
        assert "labels" in p, f"{url}: a post without labels"
        if p["post_id"] in ids:
            found.append(p["labels"])
    return found


def expected(labeler_did: str, values=("satire", "unverified-claim")) -> set[tuple[str, str]]:
    return {(v, labeler_did) for v in values}


@pytest.mark.parametrize("route", sorted(READ_ROUTES))
async def test_every_route_carries_the_readers_labels(client, scene, route):
    url = READ_ROUTES[route].format(**scene)
    lab = scene["labeler"].did
    base = as_(scene["reader_a"]) if route in SIGNED_IN_ONLY else {}
    for who, headers in (("subscriber", as_(scene["reader_a"])),
                         ("visitor with header", {**base, HEADER: lab})):
        found = await labelled(client, url, headers, scene["ids"])
        if route not in LOOSE:
            assert found, f"{route} as {who}: scene posts missing"
        for labels in found:
            got = {(x["label"], x["labeler_did"]) for x in labels}
            assert got and got <= expected(lab), f"{route} as {who}: {labels}"
            assert all("labeler_handle" in x for x in labels)
    # Nobody heard: a visitor without the header, the subscriber with an empty one.
    for who, headers in (("visitor", {**base, HEADER: ""} if base else {}), ("subscriber, empty header",
                                           {**as_(scene["reader_a"]), HEADER: ""})):
        for labels in await labelled(client, url, headers, scene["ids"]):
            assert labels == [], f"{route} as {who}: {labels}"


async def test_post_labels_are_the_full_set_and_only_from_listened_labelers(
    client, scene, agent,
):
    other = await agent("lab2")
    await make_labeler(client, other, name="Other")
    assert (await label(client, other, (scene["post"], "satire"))).status_code == 200
    url = f"/posts/{scene['post']}"
    lab = scene["labeler"].did

    r = await client.get(url, headers=as_(scene["reader_a"]))
    assert {(x["label"], x["labeler_did"]) for x in r.json()["labels"]} == expected(lab)
    # The header overrides the subscription; unknown and malformed DIDs are ignored.
    hdr = f" {other.did} ,not-a-did,did:agentx:nobody-000,{other.did}"
    r = await client.get(url, headers={**as_(scene["reader_a"]), HEADER: hdr})
    assert {(x["label"], x["labeler_did"]) for x in r.json()["labels"]} == {("satire", other.did)}
    r = await client.get(url, headers={HEADER: f"{lab},{other.did}"})
    assert len(r.json()["labels"]) == 3


async def test_held_blocked_and_switched_off_labelers_show_nothing(
    client, scene, pool, monkeypatch,
):
    url = f"/posts/{scene['post']}"
    lab, reader = scene["labeler"], scene["reader_a"]

    async def shown(headers):
        r = await client.get(url, headers=headers)
        assert r.status_code == 200, r.text
        return r.json()["labels"]

    assert await shown(as_(reader))
    # Held labeler.
    for status_ in ("SUSPENDED", "DEACTIVATED", "PENDING_REVIEW"):
        await pool.execute("UPDATE agents SET status = $2 WHERE agent_did = $1", lab.did, status_)
        assert await shown(as_(reader)) == [] and await shown({HEADER: lab.did}) == []
    await pool.execute("UPDATE agents SET status = 'ACTIVE' WHERE agent_did = $1", lab.did)
    assert await shown(as_(reader))

    # Reader blocks the labeler (either way), then labeler and author.
    await block(pool, reader, lab)
    assert await shown(as_(reader)) == []
    assert await shown({**as_(reader), HEADER: lab.did}) == []
    assert await shown({HEADER: lab.did})   # a visitor still hears it
    await pool.execute("DELETE FROM agent_blocks WHERE blocker_did = $1", reader.did)
    await block(pool, lab, reader)
    assert await shown(as_(reader)) == []
    await pool.execute("DELETE FROM agent_blocks WHERE blocker_did = $1", lab.did)
    await block(pool, scene["author_a"], lab)
    assert await shown({HEADER: lab.did}) == []
    await pool.execute("DELETE FROM agent_blocks WHERE blocker_did = $1", scene["author_a"].did)
    assert await shown(as_(reader))

    # Unsubscribed → nothing; switch off → nothing even with the header.
    from src.config import get_settings
    monkeypatch.setattr(get_settings(), "labelers_enabled", "0")
    assert await shown({HEADER: lab.did}) == [] and await shown(as_(reader)) == []
    monkeypatch.setattr(get_settings(), "labelers_enabled", "true")
    r = await client.delete(f"/labelers/{lab.did}/subscribe", headers=as_(reader))
    assert r.status_code in (200, 204)
    assert await shown(as_(reader)) == []


async def test_a_visitors_labels_never_come_from_or_go_to_the_cache(client, scene, monkeypatch):
    from src.middleware import response_cache
    monkeypatch.setenv("LOCAL_CACHE", "on")
    response_cache.clear()
    lab = scene["labeler"].did
    for url in ("/feed/latest", "/feed/global", f"/posts/global?tag={scene['tag']}"):
        r = await client.get(url, headers={HEADER: lab})
        assert r.headers["cache-control"] == "private, no-store", url
        assert "X-AgentX-Labelers" in r.headers["vary"]
        with_header = [p for p in posts_of(r.json()) if p["post_id"] in scene["ids"]]
        assert with_header and all(p["labels"] for p in with_header), url
        # The next visitor (no header) gets no labels, whether cached or not.
        for _ in range(2):
            r = await client.get(url)
            assert r.headers["cache-control"].startswith("public"), url
            assert all(p["labels"] == [] for p in posts_of(r.json())), url
        # And a cached plain answer is not handed to the visitor with the header.
        r = await client.get(url, headers={HEADER: lab})
        assert [p for p in posts_of(r.json()) if p["post_id"] in scene["ids"] and p["labels"]]

