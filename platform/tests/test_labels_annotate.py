"""
Layer 1 S6-5: the label annotator without a database.

Header parsing (cap, shape, repeats, hostile values), whom a reader listens
to, one query per page, the switch, and a guard that every GET route whose
answer carries posts is covered by the ``--db`` route test (or listed here
with the reason it is left out).
"""
from __future__ import annotations

import inspect
import typing
from uuid import uuid4

import pytest
from pydantic import BaseModel

from src.models.labeler import MAX_LABELERS_HEADER
from src.services import labels


# ── Header parsing ────────────────────────────────────────────────────────────

def test_parse_header_keeps_valid_dids_in_order_once():
    v = " did:agentx:a-001 ,did:agentx:b-002,did:agentx:a-001,, did:web:example.com "
    assert labels.parse_header(v) == ("did:agentx:a-001", "did:agentx:b-002", "did:web:example.com")


@pytest.mark.parametrize("bad", [
    "", " ", ",,,", "not-a-did", "did:", "did:agentx:", "DID:agentx:x", "did:agentx:a b",
    "did:agentx:a\x00b", "did:agentx:a;DROP TABLE agents", "did:agentx:" + "x" * 201,
    "did:agentx:a'--", "did:agentx:%' OR 1=1",
])
def test_parse_header_drops_malformed(bad):
    assert labels.parse_header(bad) == ()


def test_parse_header_caps_count_and_length():
    many = ",".join(f"did:agentx:l{i}-001" for i in range(100))
    assert len(labels.parse_header(many)) == MAX_LABELERS_HEADER
    huge = "did:agentx:a-001," + "x" * 100_000 + ",did:agentx:b-002"
    assert labels.parse_header(huge) == ("did:agentx:a-001",)


# ── Fake connection ───────────────────────────────────────────────────────────

class Post(BaseModel):
    post_id: object
    labels: list = []


class FakeConn:
    def __init__(self, subs=(), label_rows=()):
        self.subs, self.label_rows, self.calls = list(subs), list(label_rows), []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        if "labeler_subscriptions" in sql and "post_labels" not in sql:
            return [{"labeler_did": d} for d in self.subs]
        return [r for r in self.label_rows if r["post_id"] in args[0]]


def row(pid, label="satire", did="did:agentx:lab-001"):
    return {"post_id": pid, "label": label, "labeler_did": did, "labeler_handle": "lab"}


@pytest.fixture
def switch(monkeypatch):
    def _set(value):
        monkeypatch.setattr(labels, "labelers_enabled", lambda: value)
    _set(True)
    return _set


async def _with_header(value, coro_fn):
    token = labels._requested.set(None if value is None else labels.parse_header(value))
    try:
        return await coro_fn()
    finally:
        labels._requested.reset(token)


async def test_nobody_listened_to_means_empty_and_no_query(switch):
    posts = [Post(post_id=uuid4(), labels=["stale"]) for _ in range(3)]
    conn = FakeConn()
    await labels.annotate(conn, posts, None)
    assert all(p.labels == [] for p in posts) and conn.calls == []
    # Present-but-empty header: nobody, even for a subscriber; no query at all.
    conn = FakeConn(subs=["did:agentx:lab-001"])
    await _with_header("", lambda: labels.annotate(conn, posts, "did:agentx:me-001"))
    assert all(p.labels == [] for p in posts) and conn.calls == []


async def test_one_query_per_page_for_a_subscriber(switch):
    posts = [Post(post_id=uuid4()) for _ in range(50)]
    posts.append(Post(post_id=posts[0].post_id))   # a repost item of the same post
    conn = FakeConn(subs=["did:agentx:lab-001"],
                    label_rows=[row(posts[0].post_id), row(posts[1].post_id, "spam")])
    await labels.annotate(conn, posts, "did:agentx:me-001")
    assert len(conn.calls) == 2                     # subscriptions + labels
    assert len(conn.calls[1][1][0]) == 50           # each post id once
    assert [x.label for x in posts[0].labels] == ["satire"]
    assert [x.label for x in posts[-1].labels] == ["satire"]
    assert posts[-1].labels is not posts[0].labels  # no shared list between items
    assert [x.label for x in posts[1].labels] == ["spam"]
    assert all(p.labels == [] for p in posts[2:-1])


async def test_header_overrides_subscriptions_with_one_query(switch):
    posts = [Post(post_id=uuid4())]
    conn = FakeConn(subs=["did:agentx:sub-001"], label_rows=[row(posts[0].post_id)])
    await _with_header("did:agentx:lab-001",
                       lambda: labels.annotate(conn, posts, "did:agentx:me-001"))
    assert len(conn.calls) == 1
    assert conn.calls[0][1][2] == ["did:agentx:lab-001"]   # the header, not the subscription
    assert conn.calls[0][1][1] == "did:agentx:me-001"      # reader blocks still apply


async def test_switch_off_shows_nothing(switch):
    switch(False)
    posts = [Post(post_id=uuid4())]
    conn = FakeConn(subs=["did:agentx:lab-001"], label_rows=[row(posts[0].post_id)])
    await _with_header("did:agentx:lab-001", lambda: labels.annotate(conn, posts, "did:agentx:me-001"))
    assert posts[0].labels == [] and conn.calls == []


async def test_middleware_sets_and_resets_the_header():
    seen = []

    async def app(scope, receive, send):
        seen.append(labels.requested_labelers())

    mw = labels.LabelersHeaderMiddleware(app)
    await mw({"type": "http", "headers": [(b"x-agentx-labelers", b"did:agentx:a-001,junk")]},
             None, None)
    await mw({"type": "http", "headers": []}, None, None)
    await mw({"type": "http", "headers": [(b"X-AgentX-Labelers", b"")]}, None, None)
    assert seen == [("did:agentx:a-001",), None, ()]
    assert labels.requested_labelers() is None


def test_cors_allows_the_header():
    from src.main import app
    cors = [m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware"]
    assert cors and "X-AgentX-Labelers" in cors[0].kwargs["allow_headers"]


# ── Guard: every route that returns posts is covered ──────────────────────────

# Routes that return PostResponse but are deliberately not label-annotated.
EXEMPT = {
    # Writes answer the writer about the post just written or changed; labels
    # are read through the GET routes.
    ("POST", "/posts"), ("POST", "/posts/thread"), ("POST", "/posts/{post_id}/replies"),
    ("PATCH", "/posts/{post_id}"), ("POST", "/posts/{post_id}/close"),
    ("POST", "/posts/{post_id}/assign"),
    # Work layer (communities, channels): hidden in Layer 1 and without any of
    # the Layer 1 annotators.
    ("GET", "/communities/{community_id}/feed"), ("GET", "/channels/{channel_id}/feed"),
}


def _carries_posts(t, seen=None) -> bool:
    from src.models.post import PostResponse
    seen = set() if seen is None else seen
    if t is PostResponse:
        return True
    if typing.get_origin(t) is not None:
        return any(_carries_posts(a, seen) for a in typing.get_args(t))
    if inspect.isclass(t) and issubclass(t, BaseModel) and t not in seen:
        seen.add(t)
        return any(_carries_posts(f.annotation, seen) for f in t.model_fields.values())
    return False


def test_every_route_returning_posts_is_covered():
    from src.main import app
    from tests.integration.test_labels_on_posts_db import READ_ROUTES

    found = set()
    for r in app.routes:
        model = getattr(r, "response_model", None)
        if model is not None and _carries_posts(model):
            for m in r.methods:
                found.add((m, r.path))
    covered = {("GET", p) for p in READ_ROUTES}
    missing = found - covered - EXEMPT
    assert not missing, f"routes returning posts without the label test: {sorted(missing)}"
    stale = (covered | EXEMPT) - found
    assert not stale, f"listed routes that no longer return posts: {sorted(stale)}"
