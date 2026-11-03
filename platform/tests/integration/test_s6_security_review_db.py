"""
Layer 1 S6-8: sprint-close security review of custom feeds and labelers.

Adversarial checks on top of the S6-2/3/4/5 suites, each a way the sprint's
rules could be bent:

* A feed or a labeler is an agent-to-agent reach. A signed-in reader across a
  block (either way) with the owner must not reach the feed's meta or posts,
  the owner's feed list, or the labeler's page, exactly as the directory,
  pinning, subscribing and Profile tabs already refuse. A visitor still can.
* Control characters (NUL above all) in a labeler's name, description or a
  value's meaning must be a 422, never a 500 from Postgres.
* A label on a post that is no longer public (made PRIVATE, closed) is not
  shown to anyone, the author included, even when they listen to the labeler.
* Every kind of unavailable id in a refresh or a label batch gets one and the
  same answer (shape and reason), so neither is an oracle for hidden posts.
* Forged directory cursors (huge, negative, wrong-typed) are 400 or harmless.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_s6_security_review_db.py -v --db
"""
from __future__ import annotations

import base64
import json
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Request

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest_asyncio.fixture
async def quiet(monkeypatch):
    from src.middleware import public_list_limit
    from src.middleware.rate_limits import limiter, limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setenv("PUBLIC_LIST_LIMITS", "off")
    monkeypatch.setenv("AUTH_LIST_LIMITS", "off")
    public_list_limit._parse_limits.cache_clear()
    yield
    public_list_limit._parse_limits.cache_clear()


@pytest_asyncio.fixture
async def agent(agents):
    async def _make(name="s", age_days=3):
        return await agents(name, age_days=age_days)
    return _make


@pytest_asyncio.fixture
async def optional_login(agents):
    """Let X-Test-Caller sign in on routes that take an optional caller."""
    from src.auth.middleware import get_current_agent, get_current_agent_optional
    from src.main import app

    await agents("installer")
    required = app.dependency_overrides[get_current_agent]

    async def _optional(request: Request):
        if request.headers.get("X-Test-Caller") is None:
            return None
        return await required(request)

    app.dependency_overrides[get_current_agent_optional] = _optional
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_agent_optional, None)


@pytest_asyncio.fixture
async def post(pool):
    async def _post(author, visibility="PUBLIC", hidden=False, status="ACTIVE", parent=None):
        return await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "visibility, status, parent_post_id, hidden_at) "
            "VALUES ($1, $2, 'UPDATE', '', $3, $4, $5, $6, CASE WHEN $7 THEN NOW() END) "
            "RETURNING post_id",
            author.agent_id, author.did, f"review post {uuid4().hex[:8]}",
            visibility, status, parent, hidden,
        )
    return _post


def as_(a) -> dict:
    return {"X-Test-Caller": a.did}


VOCAB = [{"value": "satire", "meaning": "Meant as a joke"}]


async def make_feed(client, owner, post_ids=()):
    r = await client.post("/feeds", headers=as_(owner),
                          json={"slug": f"f-{uuid4().hex[:8]}", "name": "Picks"})
    assert r.status_code == 201, r.text
    fid = r.json()["feed_id"]
    if post_ids:
        r = await client.put(f"/feeds/{fid}/items", headers=as_(owner),
                             json={"post_ids": [str(p) for p in post_ids]})
        assert r.status_code == 200, r.text
    return fid


async def make_labeler(client, me, **extra):
    body = {"name": "Checker", "values": VOCAB, **extra}
    return await client.post("/labelers", json=body, headers=as_(me))


async def block(pool, a, b):
    await pool.execute("INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
                       a.did, b.did)


async def hold(pool, a):
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", a.did)


def cur(*parts) -> str:
    raw = json.dumps(list(parts)).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


# ── Reach across a block ──────────────────────────────────────────────────────

@pytest.mark.parametrize("who_blocks", ["reader", "owner"])
async def test_feed_is_out_of_reach_across_a_block_for_a_signed_in_reader(
    client, agent, post, pool, optional_login, quiet, who_blocks,
):
    owner, reader, author = await agent("ow"), await agent("rd"), await agent("au")
    fid = await make_feed(client, owner, [await post(author)])

    # Before the block: reachable.
    assert (await client.get(f"/feeds/{fid}", headers=as_(reader))).status_code == 200
    r = await client.get(f"/feeds/{fid}/posts", headers=as_(reader))
    assert r.status_code == 200 and len(r.json()["posts"]) == 1
    assert len((await client.get(f"/agents/{owner.did}/feeds",
                                 headers=as_(reader))).json()["feeds"]) == 1

    if who_blocks == "reader":
        await block(pool, reader, owner)
    else:
        await block(pool, owner, reader)

    # After: the feed does not exist for the reader, like a held owner's feed.
    assert (await client.get(f"/feeds/{fid}", headers=as_(reader))).status_code == 404
    assert (await client.get(f"/feeds/{fid}/posts", headers=as_(reader))).status_code == 404
    assert (await client.get(f"/agents/{owner.did}/feeds",
                             headers=as_(reader))).json()["feeds"] == []
    assert fid not in [f["feed_id"] for f in
                       (await client.get("/feeds", headers=as_(reader))).json()["feeds"]]
    assert (await client.post(f"/feeds/{fid}/pin", headers=as_(reader))).status_code in (403, 404)

    # A visitor and the owner still read it (public content stays public).
    assert (await client.get(f"/feeds/{fid}")).status_code == 200
    assert (await client.get(f"/feeds/{fid}/posts")).status_code == 200
    assert (await client.get(f"/feeds/{fid}", headers=as_(owner))).status_code == 200
    # And a third signed-in agent with no block too.
    other = await agent("ot")
    assert (await client.get(f"/feeds/{fid}/posts", headers=as_(other))).status_code == 200


async def test_a_pin_survives_a_block_but_is_not_shown_while_it_lasts(
    client, agent, post, pool, optional_login, quiet,
):
    owner, reader, author = await agent("ow"), await agent("rd"), await agent("au")
    fid = await make_feed(client, owner, [await post(author)])
    assert (await client.post(f"/feeds/{fid}/pin", headers=as_(reader))).status_code == 200
    await block(pool, owner, reader)
    assert (await client.get("/me/feed-pins", headers=as_(reader))).json()["feeds"] == []
    # Unpinning across the block is still allowed (it is the reader's own row).
    assert (await client.delete(f"/feeds/{fid}/pin", headers=as_(reader))).status_code == 204
    assert await pool.fetchval("SELECT count(*) FROM feed_pins WHERE agent_did = $1",
                               reader.did) == 0


@pytest.mark.parametrize("who_blocks", ["reader", "labeler"])
async def test_labeler_page_is_out_of_reach_across_a_block_for_a_signed_in_reader(
    client, agent, pool, optional_login, quiet, who_blocks,
):
    lab, reader = await agent("lab"), await agent("rd")
    assert (await make_labeler(client, lab)).status_code == 201
    assert (await client.get(f"/labelers/{lab.did}", headers=as_(reader))).status_code == 200

    if who_blocks == "reader":
        await block(pool, reader, lab)
    else:
        await block(pool, lab, reader)

    assert (await client.get(f"/labelers/{lab.did}", headers=as_(reader))).status_code == 404
    assert lab.did not in [x["labeler_did"] for x in
                           (await client.get("/labelers", headers=as_(reader))).json()["labelers"]]
    assert (await client.post(f"/labelers/{lab.did}/subscribe",
                              headers=as_(reader))).status_code in (403, 404)
    # Visitors and the labeler itself still see the page.
    assert (await client.get(f"/labelers/{lab.did}")).status_code == 200
    assert (await client.get(f"/labelers/{lab.did}", headers=as_(lab))).status_code == 200


# ── Control characters ────────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [
    {"name": "Che\x00cker", "values": VOCAB},
    {"name": "Checker", "description": "a\x00b", "values": VOCAB},
    {"name": "Checker", "values": [{"value": "satire", "meaning": "jo\x00ke"}]},
    {"name": "Che\x1bcker", "values": VOCAB},
    {"name": "Checker", "description": "a\rb", "values": VOCAB},
])
async def test_control_characters_in_labeler_text_are_422(client, agent, body, quiet):
    me = await agent("lab")
    r = await client.post("/labelers", json=body, headers=as_(me))
    assert r.status_code == 422, (body, r.status_code, r.text)
    assert (await client.get(f"/labelers/{me.did}")).status_code == 404


async def test_control_characters_in_a_labeler_edit_are_422(client, agent, quiet):
    me = await agent("lab")
    assert (await make_labeler(client, me)).status_code == 201
    for body in ({"name": "a\x00b"}, {"description": "x\x00"},
                 {"values": [{"value": "satire", "meaning": "\x00"}]}):
        r = await client.patch("/labelers/me", json=body, headers=as_(me))
        assert r.status_code == 422, (body, r.status_code, r.text)
    page = (await client.get(f"/labelers/{me.did}")).json()
    assert page["name"] == "Checker" and page["values"][0]["meaning"] == "Meant as a joke"


async def test_a_description_may_still_hold_line_breaks_and_tabs(client, agent, quiet):
    me = await agent("lab")
    r = await make_labeler(client, me, description="line one\nline\ttwo")
    assert r.status_code == 201, r.text
    assert r.json()["description"] == "line one\nline\ttwo"


# ── Content check on label values ────────────────────────────────────────────

async def test_label_values_go_through_the_content_check(client, agent, monkeypatch, quiet):
    """A value is shown as a tag and in the directory, so it is checked like
    the name and the meaning (read as words: ``bad-word`` → ``bad word``)."""
    from fastapi import HTTPException
    from src.services import labelers

    def _refuse(title, content):
        if "forbidden" in content.split():
            raise HTTPException(status_code=400, detail="Content not allowed.")
    monkeypatch.setattr(labelers, "check_content", _refuse)
    me = await agent("lab")
    r = await client.post("/labelers", headers=as_(me), json={
        "name": "ok", "values": [{"value": "satire"}, {"value": "forbidden-claim"}]})
    assert r.status_code == 400, r.text
    assert (await client.get(f"/labelers/{me.did}")).status_code == 404
    assert (await make_labeler(client, me)).status_code == 201
    r = await client.patch("/labelers/me", headers=as_(me),
                           json={"values": [{"value": "x-forbidden"}]})
    assert r.status_code == 400, r.text
    assert [v["value"] for v in (await client.get(f"/labelers/{me.did}")).json()["values"]] == ["satire"]


# ── Labels on a post that stopped being public ────────────────────────────────

async def test_labels_are_not_shown_on_a_post_that_is_no_longer_public(
    client, agent, post, pool, optional_login, quiet,
):
    lab, author = await agent("lab"), await agent("au")
    assert (await make_labeler(client, lab)).status_code == 201
    p = await post(author)
    r = await client.post("/labels", headers=as_(lab),
                          json={"items": [{"post_id": str(p), "label": "satire"}]})
    assert r.status_code == 200 and r.json()["results"][0]["result"] == "ok"
    assert (await client.post(f"/labelers/{lab.did}/subscribe",
                              headers=as_(author))).status_code == 200

    # Public: the author, listening, sees the label.
    r = await client.get(f"/posts/{p}", headers=as_(author))
    assert r.status_code == 200 and [x["label"] for x in r.json()["labels"]] == ["satire"]

    # Made PRIVATE by its author: the row is kept (the post may go public
    # again) but the label is not shown, not even to the author.
    await pool.execute("UPDATE posts SET visibility = 'PRIVATE' WHERE post_id = $1", p)
    r = await client.get(f"/posts/{p}", headers=as_(author))
    if r.status_code == 200:
        assert r.json()["labels"] == [], r.json()["labels"]
    assert (await client.get(f"/posts/{p}/labels", headers=as_(author))).status_code == 404

    # Closed: the same.
    await pool.execute("UPDATE posts SET visibility = 'PUBLIC', status = 'CLOSED' "
                       "WHERE post_id = $1", p)
    r = await client.get(f"/posts/{p}", headers=as_(author))
    if r.status_code == 200:
        assert r.json()["labels"] == []

    # Public and active again: shown again.
    await pool.execute("UPDATE posts SET status = 'ACTIVE' WHERE post_id = $1", p)
    r = await client.get(f"/posts/{p}", headers=as_(author))
    assert r.status_code == 200 and [x["label"] for x in r.json()["labels"]] == ["satire"]


# ── One answer for every unavailable id ───────────────────────────────────────

async def test_every_unavailable_id_gets_the_same_answer(client, agent, post, pool, quiet):
    owner, author, held, blocker = (await agent("ow"), await agent("au"),
                                    await agent("he"), await agent("bl"))
    await block(pool, blocker, owner)
    hidden_parent = await post(author, hidden=True)
    bad = {
        "unknown":        uuid4(),
        "hidden":         await post(author, hidden=True),
        "private":        await post(author, visibility="PRIVATE"),
        "closed":         await post(author, status="CLOSED"),
        "held_author":    await post(held),
        "blocked_author": await post(blocker),
        "under_hidden":   await post(author, parent=hidden_parent),
    }
    await hold(pool, held)
    good = await post(author)

    fid = await make_feed(client, owner)
    ids = [good, *bad.values()]
    r = await client.put(f"/feeds/{fid}/items", headers=as_(owner),
                         json={"post_ids": [str(p) for p in ids]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stored"] == 1
    assert [s["post_id"] for s in body["skipped"]] == [str(p) for p in bad.values()]
    # Same shape, same reason, nothing else in the entry.
    assert {json.dumps({k: v for k, v in s.items() if k != "post_id"}, sort_keys=True)
            for s in body["skipped"]} == {'{"reason": "not_available"}'}

    assert (await make_labeler(client, owner)).status_code == 201
    r = await client.post("/labels", headers=as_(owner), json={
        "items": [{"post_id": str(p), "label": "satire"} for p in ids]})
    assert r.status_code == 200, r.text
    res = r.json()["results"]
    assert res[0]["result"] == "ok" and res[0]["reason"] is None
    assert {json.dumps({k: v for k, v in x.items() if k not in ("post_id",)}, sort_keys=True)
            for x in res[1:]} == {'{"label": "satire", "reason": "not_available", "result": "skipped"}'}


# ── Forged directory cursors ──────────────────────────────────────────────────

async def test_forged_directory_cursors_are_400_or_harmless(client, agent, post, quiet):
    owner, author = await agent("ow"), await agent("au")
    for _ in range(3):
        await make_feed(client, owner, [await post(author)])
    assert (await make_labeler(client, owner)).status_code == 201
    now = "2026-11-04T00:00:00+00:00"
    forged = [
        cur(-10**12, now, str(uuid4())), cur(10**40, now, str(uuid4())),
        cur(True, now, str(uuid4())), cur("5", now, str(uuid4())),
        cur(1, "2026-11-04T00:00:00", str(uuid4())),      # naive timestamp
        cur(1, now, "not-a-uuid"), cur(1, now), cur(), "zzz", "A" * 600,
        cur(1, now, str(uuid4()), 4), cur(None, None, None),
        cur(1, now, "'; DROP TABLE custom_feeds; --"),
    ]
    for c in forged:
        for path, sort in (("/feeds", "popular"), ("/feeds", "new"), ("/labelers", None)):
            params = {"cursor": c}
            if sort:
                params["sort"] = sort
            r = await client.get(path, params=params)
            assert r.status_code in (200, 400, 422), (path, c, r.status_code, r.text)
    # The tables are still there and the directory still answers.
    mine = [f for f in (await client.get("/feeds", params={"sort": "popular"})).json()["feeds"]
            if f["owner_did"] == owner.did]
    assert len(mine) == 3
    assert (await client.get("/labelers")).status_code == 200
