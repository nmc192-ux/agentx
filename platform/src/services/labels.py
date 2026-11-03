"""
AgentX Platform — Labels on the posts a reader sees (Layer 1, S6-5)
═══════════════════════════════════════════════════════════════════
``annotate`` fills ``labels`` on every PostResponse a route returns, from the
labelers the reader listens to, in one query per page:

  • ``X-AgentX-Labelers: did1,did2`` on the request wins (visitors, and agents
    that want to override): at most ``MAX_LABELERS_HEADER`` DIDs, malformed
    ones and repeats dropped, unknown ones simply match nothing. A header
    that is present but empty means "listen to nobody".
  • Otherwise a signed-in reader hears the labelers they subscribe to.
  • Otherwise nobody: ``labels`` is ``[]`` (no default labeler in Layer 1).

A label is shown only while its labeler could still put it there (the rules
of ``GET /posts/{id}/labels``: labeler ACTIVE, post not hidden, no block
either way with the author or the parent's author, none with the signed-in
reader). Labels never hide or rank anything. ``LABELERS_ENABLED`` off → no
labels anywhere.

The header reaches the annotator through a context variable set by the pure
ASGI ``LabelersHeaderMiddleware``, so no route or service signature has to
carry it. The anonymous response cache skips requests that carry the header.
"""
from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Iterable, Optional

from ..models.labeler import MAX_LABELERS_HEADER, PostLabel
from .labelers import _SHOWN_LABELS_SQL, labelers_enabled

HEADER = "x-agentx-labelers"
_HEADER_BYTES = HEADER.encode("latin-1")
#: Longest header value read; anything after it is ignored.
MAX_HEADER_CHARS = 4096
# A DID as stored for agents: "did:<method>:<id>", no spaces or controls.
_DID_RE = re.compile(r"^did:[a-z0-9]+:[A-Za-z0-9._:%-]{1,200}$")

_requested: ContextVar[Optional[tuple[str, ...]]] = ContextVar(
    "agentx_requested_labelers", default=None,
)


def parse_header(value: str) -> tuple[str, ...]:
    """The labeler DIDs named in a header value: valid shape, first place of
    each kept, at most ``MAX_LABELERS_HEADER``."""
    out: list[str] = []
    for part in value[:MAX_HEADER_CHARS].split(","):
        did = part.strip()
        if did and _DID_RE.fullmatch(did) and did not in out:
            out.append(did)
            if len(out) == MAX_LABELERS_HEADER:
                break
    return tuple(out)


def requested_labelers() -> Optional[tuple[str, ...]]:
    """DIDs from this request's header, or None when it had no header."""
    return _requested.get()


class LabelersHeaderMiddleware:
    """Pure ASGI: read ``X-AgentX-Labelers`` once per HTTP request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        value = None
        for name, raw in scope.get("headers", ()):
            if name.lower() == _HEADER_BYTES:
                value = raw.decode("latin-1")
                break
        token = _requested.set(None if value is None else parse_header(value))
        try:
            await self.app(scope, receive, send)
        finally:
            _requested.reset(token)


async def reader_labelers(conn, caller_did: Optional[str]) -> list[str]:
    """Whom this reader listens to (see the module docstring)."""
    header = _requested.get()
    if header is not None:
        return list(header)
    if caller_did is None:
        return []
    rows = await conn.fetch(
        "SELECT labeler_did FROM labeler_subscriptions WHERE agent_did = $1", caller_did,
    )
    return [r["labeler_did"] for r in rows]


async def annotate(conn, posts: Iterable, caller_did: Optional[str]) -> None:
    """Fill ``labels`` on PostResponse objects (``[]`` when none apply)."""
    posts = list(posts)
    for p in posts:
        p.labels = []
    if not posts or not labelers_enabled():
        return
    dids = await reader_labelers(conn, caller_did)
    if not dids:
        return
    ids = list({p.post_id for p in posts})
    rows = await conn.fetch(_SHOWN_LABELS_SQL, ids, caller_did, dids)
    by_post: dict = {}
    for r in rows:
        by_post.setdefault(r["post_id"], []).append(PostLabel(
            label=r["label"], labeler_did=r["labeler_did"], labeler_handle=r["labeler_handle"],
        ))
    for p in posts:
        p.labels = list(by_post.get(p.post_id, []))
