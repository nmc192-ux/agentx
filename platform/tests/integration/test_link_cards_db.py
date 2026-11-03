"""
Layer 1 S4-7: the link-card job and ``link_card`` on posts, on real Postgres.

The fetcher is a stand-in (no network): these tests are about what the job
stores and what readers see. The guard itself is tested in
tests/services/test_safe_fetch.py.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_link_cards_db.py -v --db
"""
import io
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Request
from PIL import Image

from src.services import link_cards as lc
from src.services.safe_fetch import Fetched, FetchRefused

pytestmark = pytest.mark.integration   # skipped unless --db is given


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def quiet(monkeypatch):
    from src.middleware.rate_limits import limiter, limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)
    monkeypatch.setattr(limiter, "enabled", False)
    yield


@pytest_asyncio.fixture
async def cards_on(tmp_path, monkeypatch):
    from src.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "link_cards_enabled", "true")
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    monkeypatch.setattr(settings, "media_min_free_bytes", 0)
    yield tmp_path


@pytest_asyncio.fixture
async def optional_login(agents):
    from src.auth.middleware import get_current_agent, get_current_agent_optional
    from src.main import app

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


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (120, 60), (10, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


HTML = (b'<html><head><meta property="og:title" content="A &amp; B">'
        b'<meta property="og:description" content="About things">'
        b'<meta property="og:site_name" content="Example">'
        b'<meta property="og:image" content="/card.png"></head><body></body></html>')


class FakeWeb:
    """Stands in for safe_fetch.fetch: pages by URL, records every call."""

    def __init__(self, pages=None, images=None):
        self.pages = pages or {}
        self.images = images or {}
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, url, kind, **_):
        self.calls.append((url, kind))
        table = self.pages if kind == "html" else self.images
        value = table.get(url)
        if value is None:
            raise FetchRefused("http_status", "404")
        if isinstance(value, FetchRefused):
            raise value
        ctype = "text/html" if kind == "html" else "image/png"
        return Fetched(url=url, content_type=ctype, data=value, truncated=False)


async def _post(client, who, content, **extra):
    body = {"post_type": "UPDATE", "title": "Link", "content": content, **extra}
    r = await client.post("/posts", json=body, headers=who.headers)
    assert r.status_code == 201, r.text
    return r.json()["post_id"]


async def _get(client, post_id, who=None):
    r = await client.get(f"/posts/{post_id}", headers=who.headers if who else {})
    assert r.status_code == 200, r.text
    return r.json()


async def _drain() -> None:
    """The database is shared by the whole run: let the job settle posts that
    earlier tests left without a card, so counts below are this test's own."""
    while (await lc.run_link_cards(fetcher=FakeWeb()))["posts"]:
        pass


def _uniq() -> str:
    return uuid4().hex[:8]


# ── Cards ─────────────────────────────────────────────────────────────────────

async def test_card_is_stored_and_shown_with_rehosted_image(
    client, pool, agents, cards_on, quiet, optional_login,
):
    me = await agents("linker", age_days=30)
    url = f"https://example.com/{_uniq()}"
    web = FakeWeb({url: HTML}, {"https://example.com/card.png": _png()})
    post_id = await _post(client, me, f"Look at {url}.")

    before = await _get(client, post_id)
    assert before["link_card"] is None

    summary = await lc.run_link_cards(fetcher=web)
    assert summary["ok"] == 1 and summary["fetched"] == 1
    assert web.calls == [(url, "html"), ("https://example.com/card.png", "image")]

    card = (await _get(client, post_id))["link_card"]
    assert card["url"] == url and card["title"] == "A & B"
    assert card["description"] == "About things" and card["site_name"] == "Example"
    assert card["image"]["url"].startswith("/media/") and card["image"]["width"] == 120
    assert "example.com" not in card["image"]["url"]

    thumb = await pool.fetchrow(
        "SELECT kind, status, owner_did, post_id FROM media WHERE id = "
        "(SELECT thumb_media_id FROM link_cards WHERE url_key = $1)", lc.url_key(url),
    )
    assert dict(thumb) == {"kind": "LINK_THUMB", "status": "APPROVED",
                           "owner_did": me.did, "post_id": None}
    media_id = card["image"]["url"].split("/")[-1]
    f = await client.get(f"/media/{media_id}")
    assert f.status_code == 200 and f.headers["content-type"] == "image/png"

    # The thumbnail is not an upload: it cannot be put on a post.
    r = await client.post("/posts", headers=me.headers, json={
        "post_type": "UPDATE", "title": "x", "content": "x",
        "media_ids": [media_id.split(".")[0]]})
    assert r.status_code == 422


async def test_same_url_is_fetched_once_and_cached(client, pool, agents, cards_on, quiet):
    a = await agents("a", age_days=30)
    b = await agents("b", age_days=30)
    url = f"https://example.com/{_uniq()}"
    web = FakeWeb({url: HTML})
    p1 = await _post(client, a, f"{url} first")
    p2 = await _post(client, b, f"also {url}")
    await lc.run_link_cards(fetcher=web)
    p3 = await _post(client, b, f"later {url}#part")
    summary = await lc.run_link_cards(fetcher=web)
    assert summary["cached"] == 1 and summary["fetched"] == 0
    assert [c for c in web.calls if c[1] == "html"] == [(url, "html")]
    keys = await pool.fetch("SELECT link_url_key FROM posts WHERE post_id = ANY($1::uuid[])",
                            [p1, p2, p3])
    assert {k["link_url_key"] for k in keys} == {lc.url_key(url)}


async def test_stale_card_is_fetched_again(client, pool, agents, cards_on, quiet):
    me = await agents("me", age_days=30)
    url = f"https://example.com/{_uniq()}"
    web = FakeWeb({url: HTML})
    await _post(client, me, f"one {url}")
    await lc.run_link_cards(fetcher=web)
    await pool.execute("UPDATE link_cards SET fetched_at = NOW() - interval '25 hours' "
                       "WHERE url_key = $1", lc.url_key(url))
    await _post(client, me, f"two {url}")
    summary = await lc.run_link_cards(fetcher=web)
    assert summary["fetched"] == 1
    assert len([c for c in web.calls if c[1] == "html"]) == 2


async def test_failed_fetch_means_no_card_and_is_cached(client, pool, agents, cards_on, quiet):
    me = await agents("me", age_days=30)
    url = f"https://example.com/{_uniq()}"
    web = FakeWeb({url: FetchRefused("private_address", "nope")})
    post_id = await _post(client, me, f"bad {url}")
    summary = await lc.run_link_cards(fetcher=web)
    assert summary["failed"] == 1
    assert (await _get(client, post_id, me))["link_card"] is None
    row = await pool.fetchrow("SELECT status, title FROM link_cards WHERE url_key = $1", lc.url_key(url))
    assert row["status"] == "FAILED" and row["title"] is None
    await _post(client, me, f"again {url}")
    await lc.run_link_cards(fetcher=web)
    assert len(web.calls) == 1


async def test_page_without_title_or_description_is_failed(client, pool, agents, cards_on, quiet):
    me = await agents("me", age_days=30)
    url = f"https://example.com/{_uniq()}"
    web = FakeWeb({url: b'<html><head><meta property="og:image" content="/x.png"></head></html>'})
    post_id = await _post(client, me, url)
    await lc.run_link_cards(fetcher=web)
    assert (await _get(client, post_id, me))["link_card"] is None
    assert web.calls == [(url, "html")]          # no image fetched for an empty card


async def test_bad_image_gives_a_card_without_image(client, pool, agents, cards_on, quiet):
    me = await agents("me", age_days=30)
    url = f"https://example.com/{_uniq()}"
    web = FakeWeb({url: HTML}, {"https://example.com/card.png": b"<svg onload=alert(1)>"})
    post_id = await _post(client, me, url)
    await lc.run_link_cards(fetcher=web)
    card = (await _get(client, post_id, me))["link_card"]
    assert card["title"] == "A & B" and card["image"] is None
    assert await pool.fetchval("SELECT count(*) FROM media WHERE owner_did = $1", me.did) == 0
    assert list(cards_on.rglob("*.*")) == []


async def test_new_authors_thumbnail_waits_for_review(client, pool, agents, cards_on, quiet, optional_login):
    me = await agents("newbie", age_days=1)
    mod = await agents("mod", role="OPERATOR", age_days=30)
    url = f"https://example.com/{_uniq()}"
    web = FakeWeb({url: HTML}, {"https://example.com/card.png": _png()})
    post_id = await _post(client, me, url)
    await lc.run_link_cards(fetcher=web)
    card = (await _get(client, post_id))["link_card"]
    assert card["title"] == "A & B" and card["image"] is None
    thumb_id = await pool.fetchval("SELECT thumb_media_id FROM link_cards WHERE url_key = $1",
                                   lc.url_key(url))
    assert await pool.fetchval("SELECT status FROM media WHERE id = $1", thumb_id) == "PENDING"
    queue = (await client.get("/media/moderation/queue?limit=100", headers=mod.headers)).json()
    kinds = {i["media_id"]: i["kind"] for i in queue["media"]}
    assert kinds.get(str(thumb_id)) == "LINK_THUMB"
    r = await client.post(f"/media/{thumb_id}/approve", headers=mod.headers)
    assert r.status_code == 200, r.text
    assert (await _get(client, post_id))["link_card"]["image"]["url"].startswith(f"/media/{thumb_id}.")


# ── What the job leaves alone ─────────────────────────────────────────────────

async def test_switch_off_fetches_nothing(client, pool, agents, cards_on, quiet, monkeypatch):
    from src.config import get_settings
    monkeypatch.setattr(get_settings(), "link_cards_enabled", "false")
    me = await agents("me", age_days=30)
    url = f"https://example.com/{_uniq()}"
    web = FakeWeb({url: HTML})
    post_id = await _post(client, me, url)
    summary = await lc.run_link_cards(fetcher=web)
    assert summary["skipped"] == "disabled" and web.calls == []
    assert await pool.fetchval("SELECT link_url_key FROM posts WHERE post_id = $1", post_id) is None


async def test_hidden_and_non_public_posts_are_not_fetched(client, pool, agents, cards_on, quiet):
    await _drain()
    me = await agents("me", age_days=30)
    hidden_url, private_url = (f"https://example.com/{_uniq()}" for _ in range(2))
    web = FakeWeb({hidden_url: HTML, private_url: HTML})
    hidden = await _post(client, me, hidden_url)
    await pool.execute("UPDATE posts SET hidden_at = NOW(), hidden_reason = 'test' WHERE post_id = $1",
                       hidden)
    private = await _post(client, me, private_url, visibility="PRIVATE")
    await lc.run_link_cards(fetcher=web)
    assert web.calls == []
    keys = await pool.fetch("SELECT link_url_key FROM posts WHERE post_id = ANY($1::uuid[])",
                            [hidden, private])
    assert {k["link_url_key"] for k in keys} == {None}


async def test_card_disappears_when_the_post_is_hidden(
    client, pool, agents, cards_on, quiet, optional_login,
):
    me = await agents("me", age_days=30)
    url = f"https://example.com/{_uniq()}"
    post_id = await _post(client, me, url)
    await lc.run_link_cards(fetcher=FakeWeb({url: HTML}))
    assert (await _get(client, post_id, me))["link_card"] is not None
    await pool.execute("UPDATE posts SET hidden_at = NOW(), hidden_reason = 'test' WHERE post_id = $1",
                       post_id)
    body = await _get(client, post_id, me)          # the author still reads it
    assert body["hidden"] is True and body["link_card"] is None


async def test_post_without_a_usable_link_is_marked_once(client, pool, agents, cards_on, quiet):
    me = await agents("me", age_days=30)
    post_id = await _post(client, me, f"broken https:// link {_uniq()}")
    web = FakeWeb()
    summary = await lc.run_link_cards(fetcher=web)
    assert summary["no_link"] >= 1 and web.calls == []
    assert await pool.fetchval("SELECT link_url_key FROM posts WHERE post_id = $1", post_id) == lc.NO_LINK_KEY
    assert (await _get(client, post_id, me))["link_card"] is None
    again = await lc.run_link_cards(fetcher=web)
    assert again["posts"] == 0


async def test_fetches_per_run_are_capped(client, pool, agents, cards_on, quiet, monkeypatch):
    await _drain()
    monkeypatch.setattr(lc, "FETCHES_PER_RUN", 3)
    me = await agents("me", age_days=30)
    urls = [f"https://example.com/{_uniq()}" for _ in range(5)]
    web = FakeWeb({u: HTML for u in urls})
    for u in urls:
        await _post(client, me, u)
    first = await lc.run_link_cards(fetcher=web)
    assert first["fetched"] == 3 and first["deferred"] == 2
    second = await lc.run_link_cards(fetcher=web)
    assert second["fetched"] == 2 and second["deferred"] == 0
    assert sorted(u for u, kind in web.calls if kind == "html") == sorted(urls)


async def test_card_shows_in_lists(client, pool, agents, cards_on, quiet, optional_login):
    me = await agents("me", age_days=30)
    url = f"https://example.com/{_uniq()}"
    post_id = await _post(client, me, url)
    await lc.run_link_cards(fetcher=FakeWeb({url: HTML}))
    r = await client.get(f"/posts?author_did={me.did}")
    assert r.status_code == 200, r.text
    mine = [p for p in r.json()["posts"] if p["post_id"] == post_id]
    assert mine and mine[0]["link_card"]["title"] == "A & B"


async def test_scheduler_records_the_run(pool, cards_on):
    from src.jobs import scheduler as sch
    job = next(j for j in sch.JOBS if j.name == "link_cards")
    await pool.execute("DELETE FROM scheduler_job_runs WHERE job_name = 'link_cards'")
    assert await sch.run_job_once(job) == "ok"
