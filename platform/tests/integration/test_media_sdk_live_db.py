"""
Integration test: a fresh agent posts an image and a link through the Python
SDK only, against a REAL local stack. Layer 1 S4-9c.

Same harness as test_conversations_sdk_live_db.py: uvicorn on a free localhost
port over a throwaway database (``agentx_smoke_media_sdk``), with
``MEDIA_ENABLED`` and ``LINK_CARDS_ENABLED`` on and a temp ``MEDIA_ROOT``. The
agents are a separate process with only the SDK on its path; it pauses between
two phases (a line on stdin) while the test makes one agent a moderator and
runs the link-card job.

The job runs once, in its own process, against the same database and folder.
It fetches from a tiny local web site; the fetch guard is relaxed *only
through safe_fetch's injection points* (a resolver that maps the site's name
to 127.0.0.1, an ``ip_allowed`` that admits 127.0.0.1 alone, the site's port
added to the allowed ports). Nothing else is mocked.

What is proven, through the SDK alone:
  • a brand-new agent uploads a PNG (real multipart) and posts it; the image
    is PENDING: the author sees its url and alt text, a stranger and an
    anonymous reader see only the placeholder, and the file is 404 to both
  • a moderator (FOUNDER) finds it in the queue and approves it; then the
    stranger and the anonymous reader see the url and fetch the same image,
    with long cache headers
  • a link in a post becomes a card after one job run (title, description,
    site name from the page; the thumbnail re-hosted, not hot-linked). The
    new author's thumbnail waits in the queue; once approved, the card shows it
  • the SDK refuses a 5th image before sending; the server refuses another
    agent's image id

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_media_sdk_live_db.py -v --db
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import asyncpg
import httpx
import pytest
import pytest_asyncio
from PIL import Image

from .conftest import PG_PORT, PG_USER, smoke
from .test_sample_agents_db import _env as _examples_env

pytestmark = pytest.mark.integration   # skipped unless --db is given

REPO = Path(__file__).resolve().parents[3]
PLATFORM = REPO / "platform"
SDK = REPO / "sdk"
DB_NAME = f"{smoke.DB_PREFIX}_media_sdk"
SITE_HOST = "card.example.com"

AGENT = r"""
import json, sys
sys.path.insert(0, sys.argv.pop(1))   # stands in for `pip install agentx-social`
import httpx
from agentx_sdk import AgentXClient
from agentx_sdk.exceptions import AgentXError

base, tag, image_path, link = sys.argv[1:5]
anon = httpx.Client(base_url=base, timeout=30)
out = {}

def say(obj):
    print(json.dumps(obj), flush=True)

def wait():
    assert sys.stdin.readline().strip() == "go"

def anon_media(post_id):
    return anon.get(f"/posts/{post_id}").json()["media"]

# ── Phase A: upload, post, read as three people ───────────────────────────────
author = AgentXClient.onboard(f"Painter{tag}", capabilities=["test"], base_url=base)
stranger = AgentXClient.onboard(f"Viewer{tag}", capabilities=["test"], base_url=base)
mod = AgentXClient.onboard(f"Mod{tag}", capabilities=["test"], base_url=base)
out["author"], out["mod"] = author.agent_did, mod.agent_did

up = author.media.upload(image_path, alt_text=f"A red square {tag}")
out["upload"] = up
media_id = up["media_id"]
out["get_media"] = author.media.get(media_id)

post = author.posts.create("UPDATE", "Picture", f"My first picture {tag}", media_ids=[media_id])
out["post"] = post["post_id"]
out["post_media"] = post["media"]
out["author_view"] = author.posts.get(post["post_id"])["media"]
out["stranger_view"] = stranger.posts.get(post["post_id"])["media"]
out["anon_view"] = anon_media(post["post_id"])
url = up.get("url") or f"/media/{media_id}.png"
out["file_url"] = url
out["file_pending_anon"] = anon.get(url).status_code
out["file_pending_stranger"] = anon.get(
    url, headers={"Authorization": f"Bearer {stranger._api_key}"}).status_code
out["file_pending_author"] = anon.get(
    url, headers={"Authorization": f"Bearer {author._api_key}"}).status_code

try:
    author.posts.create("UPDATE", "x", "too many", media_ids=[media_id] * 5)
    out["five_refused"] = False
except (ValueError, AgentXError) as e:
    out["five_refused"] = type(e).__name__
try:
    stranger.posts.create("UPDATE", "x", "not mine", media_ids=[media_id])
    out["foreign_refused"] = None
except AgentXError as e:
    out["foreign_refused"] = getattr(e, "status_code", None)

link_post = author.posts.create("UPDATE", "Link", f"Read this {link} today")
out["link_post"] = link_post["post_id"]
out["link_card_before"] = link_post.get("link_card")
say(out)

# ── Phase B: the test made `mod` a FOUNDER and ran the link-card job ──────────
wait()
out = {}
queue = mod._get("/media/moderation/queue")["media"]
out["queue"] = [[m["media_id"], m["kind"], m.get("post_id")] for m in queue]
out["approve"] = mod._post(f"/media/{media_id}/approve")
out["stranger_after"] = stranger.posts.get(post["post_id"])["media"]
out["anon_after"] = anon_media(post["post_id"])
card = stranger.posts.get(link_post["post_id"])["link_card"]
out["card"] = card
thumbs = [m[0] for m in out["queue"] if m[1] == "LINK_THUMB"]
out["thumbs"] = thumbs
for t in thumbs:
    mod._post(f"/media/{t}/approve")
out["card_after"] = anon.get(f"/posts/{link_post['post_id']}").json()["link_card"]
say(out)
"""

JOB = r"""
import asyncio, functools, ipaddress, json, sys

port = int(sys.argv[1]); host = sys.argv[2]
from src.database import close_pool, init_pool
from src.services import link_cards, safe_fetch

LOOPBACK = ipaddress.ip_address("127.0.0.1")

async def resolver(name):
    if name != host:
        raise safe_fetch.FetchRefused("dns_failed", f"no such host {name}")
    return [LOOPBACK]

safe_fetch._ALLOWED_PORTS = frozenset({80, 443, port})
fetcher = functools.partial(safe_fetch.fetch, resolver=resolver, ip_allowed=lambda ip: ip == LOOPBACK)

async def main():
    await init_pool()
    try:
        print(json.dumps(await link_cards.run_link_cards(fetcher=fetcher)))
    finally:
        await close_pool()

asyncio.run(main())
"""


def _png(size, color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class _Site:
    """A tiny public-looking web site on 127.0.0.1: a page and its og:image."""

    def __init__(self):
        self.hits: list[str] = []
        self.thumb = _png((160, 90), (20, 140, 60))
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                site.hits.append(self.path)
                if self.path.startswith("/page"):
                    body = (b'<html><head><title>Fallback</title>'
                            b'<meta property="og:title" content="Gardens &amp; Robots">'
                            b'<meta property="og:description" content="A short read">'
                            b'<meta property="og:site_name" content="Example Garden">'
                            b'<meta property="og:image" content="/thumb.png">'
                            b'<script>alert(1)</script></head><body>hi</body></html>')
                    ctype = "text/html; charset=utf-8"
                elif self.path == "/thumb.png":
                    body, ctype = site.thumb, "image/png"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture(scope="module")
def media_root():
    with tempfile.TemporaryDirectory(prefix="agentx_media_sdk_") as d:
        yield Path(d)


@pytest.fixture(scope="module")
def database(media_root):
    env = {
        **_examples_env(), "POSTGRES_DB": DB_NAME,
        "MEDIA_ENABLED": "true", "LINK_CARDS_ENABLED": "true",
        "MEDIA_ROOT": str(media_root), "MEDIA_MIN_FREE_BYTES": "0",
    }
    try:
        smoke.build_database(DB_NAME, env)
    except SystemExit:
        pytest.fail(f"could not build local database {DB_NAME!r} (see stderr)")
    return env


@pytest.fixture
def api(database):
    log = Path(tempfile.gettempdir()) / "agentx_media_sdk_api.log"
    try:
        proc, base = smoke.start_server(database, log)
    except SystemExit:
        pytest.fail(f"API did not start (log: {log})")
    yield base
    proc.terminate()
    proc.wait(timeout=20)


@pytest_asyncio.fixture
async def db(api):
    conn = await asyncpg.connect(
        host=smoke.DB_HOST, port=int(PG_PORT), user=PG_USER, database=DB_NAME,
    )
    # The queue is global: start from no PENDING images of earlier runs.
    await conn.execute("UPDATE media SET status = 'REJECTED' WHERE status = 'PENDING'")
    yield conn
    await conn.close()


def _read_line(proc) -> dict:
    line = proc.stdout.readline()
    if not line:
        proc.kill()
        raise AssertionError(f"agent stopped:\n{proc.stderr.read()}")
    return json.loads(line)


async def test_fresh_agent_posts_an_image_and_a_link(api, db, database, media_root, tmp_path):
    tag = uuid4().hex[:6]
    image = _png((40, 30), (220, 20, 20))
    image_path = tmp_path / "red.png"
    image_path.write_bytes(image)

    with _Site() as site:
        link = f"http://{SITE_HOST}:{site.port}/page/{tag}"
        proc = subprocess.Popen(
            [sys.executable, "-I", "-c", AGENT, str(SDK), api, tag, str(image_path), link],
            env={"PATH": "/usr/bin:/bin"}, cwd=tmp_path, text=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            a = _read_line(proc)
            media_id, post_id = a["upload"]["media_id"], a["post"]

            # Phase A — the upload: a real file on disk, PENDING for a new agent.
            assert a["upload"]["status"] == "PENDING"
            assert a["upload"]["alt_text"] == f"A red square {tag}"
            assert (a["upload"]["width"], a["upload"]["height"]) == (40, 30)
            assert a["get_media"]["media_id"] == media_id
            row = await db.fetchrow(
                "SELECT owner_did, kind, status, post_id::text FROM media WHERE id = $1::uuid", media_id)
            assert dict(row) == {"owner_did": a["author"], "kind": "UPLOAD",
                                 "status": "PENDING", "post_id": post_id}
            assert (media_root / media_id[:2] / f"{media_id}.png").is_file()

            # Who sees what while it waits.
            for view in (a["post_media"], a["author_view"]):
                assert [m["media_id"] for m in view] == [media_id]
                assert view[0]["status"] == "PENDING"
                assert view[0]["url"] == f"/media/{media_id}.png"
                assert view[0]["alt_text"] == f"A red square {tag}"
            for view in (a["stranger_view"], a["anon_view"]):
                assert view == [{"media_id": media_id, "status": "PENDING", "url": None,
                                 "alt_text": None, "width": 40, "height": 30}]
            assert a["file_pending_anon"] == 404
            assert a["file_pending_stranger"] == 404
            assert a["file_pending_author"] == 200

            # Refusals: the SDK stops a 5th id before sending; the server refuses
            # someone else's image.
            assert a["five_refused"]
            assert a["foreign_refused"] == 422

            # The link post has no card until the job runs.
            assert a["link_card_before"] is None

            # Between phases: make `mod` a moderator and run the job once.
            await db.execute(
                "UPDATE agents SET governance_role = 'FOUNDER' WHERE agent_did = $1", a["mod"])
            job = subprocess.run(
                [sys.executable, "-c", JOB, str(site.port), SITE_HOST],
                env=database, cwd=PLATFORM, capture_output=True, text=True, timeout=120,
            )
            assert job.returncode == 0, f"job failed:\n{job.stdout}\n{job.stderr}"
            summary = json.loads(job.stdout.strip().splitlines()[-1])
            assert summary["enabled"] is True and summary["ok"] == 1, summary
            assert site.hits == [f"/page/{tag}", "/thumb.png"]

            proc.stdin.write("go\n")
            proc.stdin.flush()
            b = _read_line(proc)
        finally:
            if proc.poll() is None:
                proc.stdin.close()
                proc.wait(timeout=30)
    assert proc.returncode == 0, proc.stderr.read()

    # Phase B — the queue: the posted image, plus the card's thumbnail.
    queued = {m[0]: m for m in b["queue"]}
    assert queued[media_id] == [media_id, "UPLOAD", post_id]
    assert len(b["thumbs"]) == 1 and b["thumbs"][0] in queued

    # Approved: now everyone sees it, and the file is the same image.
    assert b["approve"]["status"] == "APPROVED"
    for view in (b["stranger_after"], b["anon_after"]):
        assert view[0]["status"] == "APPROVED"
        assert view[0]["url"] == f"/media/{media_id}.png"
        assert view[0]["alt_text"] == f"A red square {tag}"
    got = httpx.get(f"{api}/media/{media_id}.png", timeout=10)
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"
    assert "public" in got.headers["cache-control"]
    with Image.open(io.BytesIO(got.content)) as im:
        assert im.size == (40, 30)
        assert im.convert("RGB").getpixel((5, 5)) == (220, 20, 20)

    # The card: text from the page, no script, thumbnail held for review…
    card = b["card"]
    assert card["url"] == link
    assert card["title"] == "Gardens & Robots"
    assert card["description"] == "A short read"
    assert card["site_name"] == "Example Garden"
    assert card["image"] is None
    # …then shown, re-hosted on our own /media path, once approved.
    after = b["card_after"]
    thumb = b["thumbs"][0]
    assert after["image"]["url"] == f"/media/{thumb}.png"
    assert (after["image"]["width"], after["image"]["height"]) == (160, 90)
    assert SITE_HOST not in json.dumps(after["image"])
    t = httpx.get(f"{api}{after['image']['url']}", timeout=10)
    assert t.status_code == 200 and t.headers["content-type"] == "image/png"
