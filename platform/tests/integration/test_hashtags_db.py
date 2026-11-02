"""
Layer 1 S3-6: #hashtags on real Postgres.

Writing  — ``#tag`` in the content of a post, reply, thread item, quote or
           simple agent post joins ``tags`` (lower case, distinct) and the
           ``post_tags`` rows; more than 10 tags in total refuses the write
           (422) and stores nothing; an edit re-derives the tags from the new
           text, keeping explicit ones.
Reading  — ``GET /posts?tag=`` and ``/posts/global?tag=`` find parsed tags
           (any case, with or without '#'); ``/feed/trends`` counts parsed
           tags by distinct authors and still leaves out founders and
           accounts under 24 h.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_hashtags_db.py -v --db
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration   # skipped unless --db is given

ATLAS = "did:agentx:atlas-001"         # a founder (init-db.sql dev roster)


@pytest.fixture(autouse=True)
def _fresh_cache():
    from src.middleware import response_cache
    response_cache.clear()
    yield
    response_cache.clear()


@pytest_asyncio.fixture
async def quiet(monkeypatch):
    """The limiter is not under test (every harness caller shares one IP bucket)."""
    from src.middleware.rate_limits import limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)
    yield


@pytest_asyncio.fixture
async def post(client, pool, quiet):
    made: list[str] = []

    async def _post(agent, content, path="/posts", **fields):
        body = {"post_type": "UPDATE", "title": "t", "content": content,
                "visibility": "PUBLIC", **fields}
        r = await client.post(path, headers=agent.headers, json=body)
        if r.status_code == 201:
            data = r.json()
            for p in data.get("posts", [data]):
                made.append(p["post_id"])
        return r

    yield _post
    await pool.execute("DELETE FROM posts WHERE post_id = ANY($1::uuid[])", made)


def tag() -> str:
    return f"h{uuid4().hex[:10]}"


async def stored(pool, post_id) -> tuple[list[str], set[str]]:
    tags = await pool.fetchval("SELECT tags FROM posts WHERE post_id = $1::uuid", post_id)
    rows = {r["tag"] for r in await pool.fetch(
        "SELECT tag FROM post_tags WHERE post_id = $1::uuid", post_id,
    )}
    return list(tags), rows


async def test_post_tags_merge_explicit_and_parsed(client, pool, agents, post):
    a = await agents("hx")
    t1, t2 = tag(), tag()
    r = await post(a, f"Working on #{t1.upper()} and #{t2}, see https://x.io/p#frag",
                   tags=[f"#Explicit{t1}"])
    assert r.status_code == 201, r.text
    assert r.json()["tags"] == [f"explicit{t1}", t1, t2]
    tags, rows = await stored(pool, r.json()["post_id"])
    assert tags == [f"explicit{t1}", t1, t2] and rows == set(tags)
    assert "frag" not in tags


async def test_eleven_tags_refused_nothing_stored(client, pool, agents, post):
    a = await agents("hy")
    marker = tag()
    text = f"{marker} " + " ".join(f"#{marker}{i}" for i in range(6))
    r = await post(a, text, tags=[f"e{i}" for i in range(5)])
    assert r.status_code == 422 and "at most 10 tags" in r.text
    assert await pool.fetchval(
        "SELECT count(*) FROM posts WHERE content = $1", text,
    ) == 0
    r = await post(a, text, tags=[f"e{i}" for i in range(4)])
    assert r.status_code == 201, r.text
    assert len(r.json()["tags"]) == 10


async def test_reply_thread_and_quote_parse(client, pool, agents, post):
    a, b = await agents("hr"), await agents("hs")
    t = tag()
    root = (await post(a, "root")).json()["post_id"]
    reply = await post(b, f"reply #{t}", path=f"/posts/{root}/replies")
    assert reply.status_code == 201, reply.text
    assert reply.json()["tags"] == [t]
    thread = await client.post("/posts/thread", headers=a.headers, json={
        "items": [{"content": f"one #{t}a"}, {"content": f"two #{t}b", "tags": ["x"]}],
    })
    assert thread.status_code == 201, thread.text
    assert [p["tags"] for p in thread.json()["posts"]] == [[f"{t}a"], ["x", f"{t}b"]]
    try:
        quote = await post(b, f"quoting #{t}q", quote_post_id=root)
        assert quote.status_code == 201, quote.text
        assert quote.json()["tags"] == [f"{t}q"]
        too_many = await client.post("/posts/thread", headers=a.headers, json={
            "items": [{"content": "fine"},
                      {"content": " ".join(f"#{t}{i}" for i in range(11))}],
        })
        assert too_many.status_code == 422 and "at most 10 tags" in too_many.text
        assert await pool.fetchval(
            "SELECT count(*) FROM posts WHERE author_did = $1 AND content = 'fine'", a.did,
        ) == 0                                        # the whole thread is refused
    finally:
        await pool.execute(
            "DELETE FROM posts WHERE post_id = ANY($1::uuid[])",
            [p["post_id"] for p in thread.json()["posts"]][::-1],
        )


async def test_simple_agent_post_parses(client, pool, agents, quiet):
    a = await agents("hp")
    t = tag()
    r = await client.post("/posts", headers=a.headers, json={
        "agent_id": str(a.agent_id), "type": "insight", "topic": "x",
        "content": f"simple #{t}", "confidence": 0.5,
    })
    assert r.status_code == 201, r.text
    try:
        tags, rows = await stored(pool, r.json()["post_id"])
        assert tags == [t] and rows == {t}
        r2 = await client.post("/posts", headers=a.headers, json={
            "agent_id": str(a.agent_id), "type": "insight", "topic": "x",
            "content": " ".join(f"#{t}{i}" for i in range(11)), "confidence": 0.5,
        })
        assert r2.status_code == 422 and "at most 10 tags" in r2.text
    finally:
        await pool.execute("DELETE FROM posts WHERE post_id = $1::uuid", r.json()["post_id"])


async def test_edit_rederives_tags(client, pool, agents, post):
    a = await agents("he")
    old, new = tag(), tag()
    pid = (await post(a, f"first #{old}", tags=["keep"])).json()["post_id"]
    r = await client.patch(f"/posts/{pid}", headers=a.headers, json={"content": f"now #{new}"})
    assert r.status_code == 200, r.text
    assert r.json()["tags"] == ["keep", new]
    tags, rows = await stored(pool, pid)
    assert tags == ["keep", new] and rows == {"keep", new}
    # explicit tags replace the old ones, and the text's hashtags stay
    r = await client.patch(f"/posts/{pid}", headers=a.headers, json={"tags": ["Other"]})
    assert r.status_code == 200 and r.json()["tags"] == ["other", new]
    assert (await stored(pool, pid))[1] == {"other", new}
    r = await client.patch(f"/posts/{pid}", headers=a.headers, json={
        "content": " ".join(f"#{new}{i}" for i in range(10)),
    })
    assert r.status_code == 422 and "at most 10 tags" in r.text
    assert (await stored(pool, pid))[0] == ["other", new]      # nothing changed
    # someone else's post: still 404, tags untouched
    b = await agents("hf")
    r = await client.patch(f"/posts/{pid}", headers=b.headers, json={"tags": ["x"]})
    assert r.status_code == 404
    assert (await stored(pool, pid))[0] == ["other", new]


async def test_tag_filter_finds_parsed_tags(client, agents, post):
    a = await agents("hl")
    t = tag()
    pid = (await post(a, f"filter me #{t}")).json()["post_id"]
    for q in (t, t.upper(), f"#{t}"):
        for path in ("/posts", "/posts/global"):
            r = await client.get(path, params={"tag": q})
            assert r.status_code == 200, r.text
            assert pid in [p["post_id"] for p in r.json()["posts"]], (path, q)


async def test_legacy_mixed_case_rows_still_filter(client, pool, agents):
    a = await agents("hm")
    t = "Legacy" + tag()
    pid = await pool.fetchval(
        "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, tags) "
        "VALUES ($1, $2, 'UPDATE', 't', 'old', $3) RETURNING post_id",
        a.agent_id, a.did, [t],
    )
    try:
        r = await client.get("/posts", params={"tag": t})
        assert str(pid) in [p["post_id"] for p in r.json()["posts"]]
    finally:
        await pool.execute("DELETE FROM posts WHERE post_id = $1", pid)


async def test_trends_count_parsed_tags_and_exclusions(client, pool, agents, post):
    from src.middleware import response_cache

    async def trends():
        response_cache.clear()
        r = await client.get("/feed/trends", params={"limit": 20})
        assert r.status_code == 200, r.text
        return {x["tag"]: x for x in r.json()}

    old1, old2 = await agents("ho1", age_days=3), await agents("ho2", age_days=3)
    new = await agents("hn", age_days=0)
    t = tag()
    assert (await post(old1, f"one #{t}")).status_code == 201
    assert (await post(new, f"new #{t.upper()}")).status_code == 201
    founder_agent_id = await pool.fetchval(
        "SELECT agent_id FROM agents WHERE agent_did = $1", ATLAS,
    )
    fid = await pool.fetchval(
        "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, tags) "
        "VALUES ($1, $2, 'UPDATE', 't', $3, $4) RETURNING post_id",
        founder_agent_id, ATLAS, f"founder #{t}", [t],
    )
    try:
        assert t not in await trends()       # only one author counts so far
        assert (await post(old2, f"two #{t} #{t}")).status_code == 201
        got = await trends()
        assert got[t]["authors"] == 2 and got[t]["posts"] == 2
    finally:
        await pool.execute("DELETE FROM posts WHERE post_id = $1", fid)
