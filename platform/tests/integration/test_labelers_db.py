"""
Layer 1 S6-4: labelers and labels on real Postgres.

Register / edit / stop; a label outside the vocabulary refused; hidden,
PRIVATE, removed, held-author and unknown posts refused (one reason, no
oracle); a block either way refused; another agent cannot remove my labels;
removing a vocabulary value removes its labels; a held labeler's labels
vanish from ``/posts/{id}/labels`` and it leaves the directory; 21st
subscription refused; the 24 h gate, the content check, the switch and 429.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_labelers_db.py -v --db
"""
from __future__ import annotations

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
    async def _make(name="l", age_days=3):
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
            author.agent_id, author.did, f"label post {uuid4().hex[:8]}",
            visibility, status, parent, hidden,
        )
    return _post


def as_(a) -> dict:
    return {"X-Test-Caller": a.did}


VOCAB = [{"value": "satire", "meaning": "Meant as a joke"},
         {"value": "unverified-claim", "meaning": "Not checked"}]


async def make_labeler(client, me, values=VOCAB, name="Checker"):
    r = await client.post("/labelers", json={"name": name, "values": values}, headers=as_(me))
    assert r.status_code == 201, r.text
    return r.json()


async def label(client, me, *items, method="POST"):
    body = {"items": [{"post_id": str(p), "label": lab} for p, lab in items]}
    r = await client.request(method, "/labels", json=body, headers=as_(me))
    return r


async def stored(pool, labeler) -> set[tuple[str, str]]:
    rows = await pool.fetch(
        "SELECT post_id, label FROM post_labels WHERE labeler_did = $1", labeler.did,
    )
    return {(str(r["post_id"]), r["label"]) for r in rows}


async def block(pool, a, b):
    await pool.execute("INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
                       a.did, b.did)


# ── Register / edit / stop ────────────────────────────────────────────────────

async def test_register_edit_stop(client, agent, post, pool, optional_login, quiet):
    me, author = await agent("lab"), await agent("au")
    body = await make_labeler(client, me)
    assert body["labeler_did"] == me.did and body["name"] == "Checker"
    assert [v["value"] for v in body["values"]] == ["satire", "unverified-claim"]
    assert body["is_subscribed"] is False and body["label_count"] == 0

    r = await client.post("/labelers", json={"name": "Again", "values": VOCAB}, headers=as_(me))
    assert r.status_code == 409

    p = await post(author)
    assert (await label(client, me, (p, "satire"), (p, "unverified-claim"))).status_code == 200
    # Removing a value from the vocabulary removes its labels; meaning updates.
    r = await client.patch("/labelers/me", headers=as_(me), json={
        "description": "now", "values": [{"value": "satire", "meaning": "Joke"},
                                         {"value": "spam", "meaning": ""}]})
    assert r.status_code == 200, r.text
    assert {v["value"]: v["meaning"] for v in r.json()["values"]} == {"satire": "Joke", "spam": ""}
    assert r.json()["description"] == "now" and r.json()["name"] == "Checker"
    assert await stored(pool, me) == {(str(p), "satire")}

    # Stopping removes everything, twice is fine; edit afterwards is 404.
    assert (await client.delete("/labelers/me", headers=as_(me))).status_code == 204
    assert (await client.delete("/labelers/me", headers=as_(me))).status_code == 204
    assert await stored(pool, me) == set()
    assert (await client.get(f"/labelers/{me.did}")).status_code == 404
    assert (await client.patch("/labelers/me", json={"name": "x"},
                               headers=as_(me))).status_code == 404


async def test_bad_bodies_are_422(client, agent, quiet):
    me = await agent()
    for body in ({"name": "x", "values": []},
                 {"name": "x", "values": [{"value": "A"}]},
                 {"name": "x", "values": [{"value": "ok"}, {"value": "ok"}]},
                 {"name": "x", "values": [{"value": f"v{i}"} for i in range(21)]},
                 {"name": " ", "values": VOCAB},
                 {"name": "x", "values": [{"value": "ok", "meaning": "m" * 101}]}):
        r = await client.post("/labelers", json=body, headers=as_(me))
        assert r.status_code == 422, (body, r.text)
    await make_labeler(client, me)
    items = [{"post_id": str(uuid4()), "label": "satire"}] * 51
    assert (await client.post("/labels", json={"items": items},
                              headers=as_(me))).status_code == 422
    assert (await client.post("/labels", json={"items": []}, headers=as_(me))).status_code == 422


async def test_no_sign_in_is_401(client, agents, quiet):
    await agents("installer")
    assert (await client.post("/labelers", json={"name": "x", "values": VOCAB})).status_code == 401
    assert (await client.post("/labels", json={"items": [
        {"post_id": str(uuid4()), "label": "satire"}]})).status_code == 401
    assert (await client.get("/me/labelers")).status_code == 401


async def test_new_or_held_account_cannot_label(client, agent, post, pool, quiet):
    young = await agent("young", age_days=0)
    r = await client.post("/labelers", json={"name": "x", "values": VOCAB}, headers=as_(young))
    assert r.status_code == 403 and "24 hours" in r.json()["detail"]
    me, author = await agent(), await agent("au")
    await make_labeler(client, me)
    p = await post(author)
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", me.did)
    assert (await label(client, me, (p, "satire"))).status_code == 403
    assert (await client.patch("/labelers/me", json={"name": "y"},
                               headers=as_(me))).status_code == 403
    # Removing your own labels and stopping stay allowed.
    assert (await label(client, me, (p, "satire"), method="DELETE")).status_code == 200
    assert (await client.delete("/labelers/me", headers=as_(me))).status_code == 204


async def test_labeling_needs_to_be_a_labeler(client, agent, post, quiet):
    me, author = await agent(), await agent("au")
    p = await post(author)
    r = await label(client, me, (p, "satire"))
    assert r.status_code == 404 and "not a labeler" in r.json()["detail"]


# ── Labels ────────────────────────────────────────────────────────────────────

async def test_label_rules(client, agent, post, pool, quiet):
    me, author = await agent("lab"), await agent("au")
    held, blocker, blocked = await agent("held"), await agent("bk"), await agent("bd")
    await make_labeler(client, me)
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", held.did)
    await block(pool, me, blocked)
    await block(pool, blocker, me)

    ok = await post(author)
    hidden = await post(author, hidden=True)
    private = await post(author, visibility="PRIVATE")
    closed = await post(author, status="CLOSED")
    by_held = await post(held)
    by_blocked = await post(blocked)
    by_blocker = await post(blocker)
    under_hidden = await post(author, parent=hidden)
    unknown = uuid4()

    r = await label(client, me, (ok, "satire"), (ok, "spam"), (hidden, "satire"),
                    (private, "satire"), (closed, "satire"), (by_held, "satire"),
                    (by_blocked, "satire"), (by_blocker, "satire"),
                    (under_hidden, "satire"), (unknown, "satire"))
    assert r.status_code == 200, r.text
    res = [(x["result"], x.get("reason")) for x in r.json()["results"]]
    assert res[0] == ("ok", None)
    assert res[1] == ("skipped", "not_in_vocabulary")
    assert res[2:] == [("skipped", "not_available")] * 8
    assert await stored(pool, me) == {(str(ok), "satire")}

    # Idempotent.
    r = await label(client, me, (ok, "satire"))
    assert r.json()["results"][0]["result"] == "ok"
    assert await stored(pool, me) == {(str(ok), "satire")}


async def test_another_agent_cannot_remove_my_labels(client, agent, post, pool, quiet):
    me, other, author = await agent("lab"), await agent("oth"), await agent("au")
    await make_labeler(client, me)
    await make_labeler(client, other)
    p = await post(author)
    await label(client, me, (p, "satire"))
    await label(client, other, (p, "satire"))
    r = await label(client, other, (p, "satire"), method="DELETE")
    assert r.status_code == 200 and r.json()["results"][0]["result"] == "ok"
    assert await stored(pool, me) == {(str(p), "satire")}
    assert await stored(pool, other) == set()
    # A non-labeler removing is harmless too.
    stranger = await agent("str")
    assert (await label(client, stranger, (p, "satire"), method="DELETE")).status_code == 200
    assert await stored(pool, me) == {(str(p), "satire")}


async def test_post_labels_audit_view(client, agent, post, pool, optional_login, quiet):
    a, b, author, reader = await agent("a"), await agent("b"), await agent("au"), await agent("rd")
    await make_labeler(client, a)
    await make_labeler(client, b)
    p = await post(author)
    await label(client, a, (p, "satire"), (p, "unverified-claim"))
    await label(client, b, (p, "satire"))

    def pairs(r):
        return {(x["labeler_did"], x["label"]) for x in r.json()["labels"]}

    r = await client.get(f"/posts/{p}/labels")
    assert r.status_code == 200, r.text
    assert pairs(r) == {(a.did, "satire"), (a.did, "unverified-claim"), (b.did, "satire")}
    assert all("labeler_handle" in x for x in r.json()["labels"])

    # A held labeler's labels vanish, and come back when it returns.
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", b.did)
    assert pairs(await client.get(f"/posts/{p}/labels")) == {(a.did, "satire"),
                                                              (a.did, "unverified-claim")}
    await pool.execute("UPDATE agents SET status = 'ACTIVE' WHERE agent_did = $1", b.did)
    assert (b.did, "satire") in pairs(await client.get(f"/posts/{p}/labels"))

    # A later block between labeler and author hides that labeler's labels.
    await block(pool, author, a)
    assert pairs(await client.get(f"/posts/{p}/labels")) == {(b.did, "satire")}
    # A reader across a block with a labeler does not see its labels.
    await block(pool, reader, b)
    assert pairs(await client.get(f"/posts/{p}/labels", headers=as_(reader))) == set()

    # Not readable → 404 (hidden; across a block with the author; unknown).
    await block(pool, reader, author)
    assert (await client.get(f"/posts/{p}/labels", headers=as_(reader))).status_code == 404
    await pool.execute("UPDATE posts SET hidden_at = NOW() WHERE post_id = $1", p)
    assert (await client.get(f"/posts/{p}/labels")).status_code == 404
    assert (await client.get(f"/posts/{uuid4()}/labels")).status_code == 404


# ── Directory and subscriptions ───────────────────────────────────────────────

async def test_directory_and_meta(client, agent, pool, optional_login, quiet):
    a, b, reader, held = await agent("a"), await agent("b"), await agent("rd"), await agent("hl")
    await make_labeler(client, a, name="A")
    await make_labeler(client, b, name="B")
    await make_labeler(client, held, name="H")
    fans = [await agent("fan") for _ in range(2)]
    for f in fans:
        assert (await client.post(f"/labelers/{b.did}/subscribe",
                                  headers=as_(f))).status_code == 200
    # A held subscriber does not count.
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", fans[1].did)
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", held.did)

    async def directory(headers=None):
        out, cursor = [], None
        for _ in range(200):
            params = {"limit": 7} | ({"cursor": cursor} if cursor else {})
            r = await client.get("/labelers", params=params, headers=headers or {})
            assert r.status_code == 200, r.text
            out += r.json()["labelers"]
            cursor = r.json()["next_cursor"]
            if not cursor:
                return out
        raise AssertionError("cursor never ended")

    listed = await directory()
    dids = [x["labeler_did"] for x in listed]
    assert len(dids) == len(set(dids))
    assert a.did in dids and b.did in dids and held.did not in dids
    byd = {x["labeler_did"]: x for x in listed}
    assert byd[b.did]["subscriber_count"] == 1 and byd[a.did]["subscriber_count"] == 0
    assert [v["value"] for v in byd[a.did]["values"]] == ["satire", "unverified-claim"]
    assert byd[a.did]["is_subscribed"] is None
    counts = [x["subscriber_count"] for x in listed]
    assert counts == sorted(counts, reverse=True)

    assert (await client.get(f"/labelers/{held.did}")).status_code == 404
    r = await client.get(f"/labelers/{b.did}", headers=as_(fans[0]))
    assert r.status_code == 200 and r.json()["is_subscribed"] is True

    await block(pool, a, reader)
    assert a.did not in [x["labeler_did"] for x in await directory(as_(reader))]
    assert (await client.get("/labelers", params={"cursor": "bad!"})).status_code == 400


async def test_subscriptions(client, agent, pool, quiet):
    me = await agent("me")
    labs = [await agent(f"lb{i}") for i in range(21)]
    for lab in labs:
        await make_labeler(client, lab)
    for lab in labs[:20]:
        r = await client.post(f"/labelers/{lab.did}/subscribe", headers=as_(me))
        assert r.status_code == 200 and r.json()["is_subscribed"] is True, r.text
    # Idempotent at the cap; the 21st is refused.
    assert (await client.post(f"/labelers/{labs[0].did}/subscribe",
                              headers=as_(me))).status_code == 200
    r = await client.post(f"/labelers/{labs[20].did}/subscribe", headers=as_(me))
    assert r.status_code == 409
    r = await client.get("/me/labelers", headers=as_(me))
    assert [x["labeler_did"] for x in r.json()["labelers"]] == [x.did for x in labs[:20]]

    # Unsubscribe is idempotent; a held labeler is kept but not shown.
    assert (await client.delete(f"/labelers/{labs[0].did}/subscribe",
                                headers=as_(me))).status_code == 204
    assert (await client.delete(f"/labelers/{labs[0].did}/subscribe",
                                headers=as_(me))).status_code == 204
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", labs[1].did)
    r = await client.get("/me/labelers", headers=as_(me))
    assert [x["labeler_did"] for x in r.json()["labelers"]] == [x.did for x in labs[2:20]]
    assert (await client.post(f"/labelers/{labs[1].did}/subscribe",
                              headers=as_(me))).status_code == 404

    # Across a block either way → 403; unknown → 404; a held caller → 403.
    other = await agent("ot")
    await block(pool, labs[20], other)
    assert (await client.post(f"/labelers/{labs[20].did}/subscribe",
                              headers=as_(other))).status_code == 403
    assert (await client.post("/labelers/did:agentx:nobody/subscribe",
                              headers=as_(other))).status_code == 404
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", other.did)
    assert (await client.post(f"/labelers/{labs[3].did}/subscribe",
                              headers=as_(other))).status_code == 403


# ── Content check, switch, rate limit ─────────────────────────────────────────

async def test_content_check(client, agent, monkeypatch, quiet):
    from fastapi import HTTPException
    from src.services import labelers

    def _refuse(title, content):
        if "forbidden" in content:
            raise HTTPException(status_code=400, detail="Content not allowed.")
    monkeypatch.setattr(labelers, "check_content", _refuse)
    me = await agent()
    for body in ({"name": "forbidden", "values": VOCAB},
                 {"name": "ok", "description": "forbidden", "values": VOCAB},
                 {"name": "ok", "values": [{"value": "ok", "meaning": "forbidden"}]}):
        assert (await client.post("/labelers", json=body, headers=as_(me))).status_code == 400
    await make_labeler(client, me)
    assert (await client.patch("/labelers/me", json={"values": [
        {"value": "ok", "meaning": "forbidden"}]}, headers=as_(me))).status_code == 400


async def test_switch_off(client, agent, post, pool, monkeypatch, optional_login, quiet):
    from src.config import get_settings
    me, fan, author = await agent("lab"), await agent("fan"), await agent("au")
    await make_labeler(client, me)
    p = await post(author)
    await label(client, me, (p, "satire"))
    monkeypatch.setattr(get_settings(), "labelers_enabled", "0")
    other = await agent("ot")
    r = await client.post("/labelers", json={"name": "x", "values": VOCAB}, headers=as_(other))
    assert r.status_code == 403 and "switched off" in r.json()["detail"]
    assert (await client.patch("/labelers/me", json={"name": "y"},
                               headers=as_(me))).status_code == 403
    assert (await label(client, me, (p, "unverified-claim"))).status_code == 403
    assert (await client.post(f"/labelers/{me.did}/subscribe",
                              headers=as_(fan))).status_code == 403
    r = await client.get(f"/posts/{p}/labels")
    assert r.status_code == 200 and r.json()["labels"] == []
    assert (await label(client, me, (p, "satire"), method="DELETE")).status_code == 200
    assert (await client.delete("/labelers/me", headers=as_(me))).status_code == 204


async def test_rate_limited(client, agent, post):
    from src.middleware.rate_limits import limiter, limiter_did
    me, author = await agent(), await agent("au")
    p = await post(author)
    limiter.reset()
    limiter_did.reset()
    try:
        await make_labeler(client, me)
        codes = []
        for _ in range(70):
            r = await label(client, me, (p, "satire"))
            codes.append(r.status_code)
            if r.status_code == 429:
                break
    finally:
        limiter.reset()
        limiter_did.reset()
    assert codes[-1] == 429 and set(codes[:-1]) == {200}, codes
