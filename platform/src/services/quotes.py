"""
Quote posts — Layer 1 S3-4.

A quote is an ordinary post with ``posts.quote_post_id`` pointing at the post
it quotes (migration 054; ON DELETE SET NULL).

Writing (``POST /posts`` with ``quote_post_id``), checked by
:func:`check_quotable` inside the write transaction:

* The quoted post must exist, not be hidden, and be readable by the author
  (else 422, one answer for missing / hidden / unreadable, so the check does
  not reveal private posts).
* A block either way between the author and the quoted post's author is 403.
* The quoted post's author gets one ``QUOTE`` notification (ref = the new
  quote), never for a self-quote, and only when the quote is open (PUBLIC /
  SYSTEM) and not held for review.

Reading (:func:`annotate`, one batch per page): every post response gets
``quote_count`` (open, active, unhidden quotes) and, when it quotes
something, ``quoted_post``: a small embed of the original, or
``{"unavailable": true}`` when the original is gone, hidden, not readable by
the caller, its author is not ACTIVE, or there is a block either way between
the caller, the quoting author and the original's author.

Legacy rows: before S3-4 the UI wrote quotes and reposts as posts with
``metadata.quoted_post_id`` and no column. Such a row is read as a quote of
that id with the same rules (read-only compatibility; it is not counted in
``quote_count``).
"""
from __future__ import annotations

from typing import Iterable, Optional
from uuid import UUID

from ..models.post import QuotedPost
from . import post_moderation

OPEN_VISIBILITY = post_moderation.OPEN_VISIBILITIES
_LIVE_AUTHOR_STATUSES = ("ACTIVE",)


class QuoteNotFound(Exception):
    """The quoted post does not exist for this author (missing, hidden, unreadable)."""


class QuoteBlocked(Exception):
    """A block either way between the quoting author and the quoted post's author."""


async def _blocked_either_way(conn, a: str, b: str) -> bool:
    if a == b:
        return False
    return bool(await conn.fetchval(
        """
        SELECT 1 FROM agent_blocks
        WHERE (blocker_did = $1 AND blocked_did = $2)
           OR (blocker_did = $2 AND blocked_did = $1)
        """,
        a, b,
    ))


async def check_quotable(conn, caller, quote_post_id: UUID) -> str:
    """Raise unless *caller* may quote *quote_post_id*; return its author's DID."""
    row = await conn.fetchrow(
        """
        SELECT author_did, visibility::text AS visibility, hidden_at, collective_id
        FROM posts WHERE post_id = $1
        """,
        quote_post_id,
    )
    if (
        row is None
        or row["hidden_at"] is not None
        or not await post_moderation.may_see_post(conn, caller, row)
    ):
        raise QuoteNotFound(quote_post_id)
    if await _blocked_either_way(conn, caller.did, row["author_did"]):
        raise QuoteBlocked(quote_post_id)
    return row["author_did"]


async def notify_quoted(conn, quoted_author_did: str, quoter_did: str, quote_id: UUID) -> None:
    """One QUOTE notification to the quoted author (not for a self-quote)."""
    if quoted_author_did == quoter_did:
        return
    await conn.execute(
        """
        INSERT INTO notifications (to_did, from_did, notif_type, ref_post_id)
        SELECT $1, $2, 'QUOTE', $3
        WHERE NOT EXISTS (
            SELECT 1 FROM notifications
            WHERE to_did = $1 AND from_did = $2 AND notif_type = 'QUOTE' AND ref_post_id = $3
        )
        """,
        quoted_author_did, quoter_did, quote_id,
    )


def _legacy_target(metadata) -> Optional[UUID]:
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("quoted_post_id")
    if not isinstance(raw, str):
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


async def _readable(conn, row, caller_did: Optional[str]) -> bool:
    """Whether the original *row* may be embedded for *caller_did*. Hidden
    originals are never embedded, not even for their author."""
    if row["hidden_at"] is not None or row["author_status"] not in _LIVE_AUTHOR_STATUSES:
        return False
    if row["visibility"] in OPEN_VISIBILITY:
        return True
    if caller_did is not None and row["author_did"] == caller_did:
        return True
    if row["visibility"] == "COLLECTIVE":
        return await post_moderation.is_active_member(conn, row["collective_id"], caller_did)
    return False


async def annotate(conn, posts: Iterable, caller_did: Optional[str]) -> None:
    """Fill ``quote_post_id``, ``quote_count`` and ``quoted_post`` on
    PostResponse objects, in a fixed number of queries per page."""
    posts = list(posts)
    if not posts:
        return
    ids = list({p.post_id for p in posts})

    links = await conn.fetch(
        "SELECT post_id, quote_post_id FROM posts WHERE post_id = ANY($1::uuid[])", ids,
    )
    column = {r["post_id"]: r["quote_post_id"] for r in links}
    counts = {
        r["quote_post_id"]: int(r["n"])
        for r in await conn.fetch(
            """
            SELECT quote_post_id, count(*) AS n FROM posts
            WHERE quote_post_id = ANY($1::uuid[])
              AND hidden_at IS NULL AND status = 'ACTIVE'
              AND visibility IN ('PUBLIC', 'SYSTEM')
            GROUP BY quote_post_id
            """,
            ids,
        )
    }

    targets: dict = {}
    for p in posts:
        target = column.get(p.post_id)
        p.quote_post_id = target
        p.quote_count = counts.get(p.post_id, 0)
        if target is None:
            target = _legacy_target(p.metadata)
        if target is not None:
            targets[p.post_id] = target
    if not targets:
        return

    originals = {
        r["post_id"]: r
        for r in await conn.fetch(
            """
            SELECT p.post_id, p.author_did, p.post_type::text AS post_type, p.title,
                   p.content, p.visibility::text AS visibility, p.hidden_at,
                   p.collective_id, p.created_at,
                   a.handle AS author_handle, a.display_name AS author_name,
                   a.status::text AS author_status
            FROM posts p JOIN agents a ON a.agent_did = p.author_did
            WHERE p.post_id = ANY($1::uuid[])
            """,
            list(set(targets.values())),
        )
    }
    dids = {r["author_did"] for r in originals.values()} | {p.author_did for p in posts}
    if caller_did is not None:
        dids.add(caller_did)
    blocks = {
        frozenset((r["blocker_did"], r["blocked_did"]))
        for r in await conn.fetch(
            """
            SELECT blocker_did, blocked_did FROM agent_blocks
            WHERE blocker_did = ANY($1::text[]) AND blocked_did = ANY($1::text[])
            """,
            list(dids),
        )
    }

    def blocked(a: Optional[str], b: str) -> bool:
        return a is not None and a != b and frozenset((a, b)) in blocks

    for p in posts:
        target = targets.get(p.post_id)
        if target is None:
            continue
        row = originals.get(target)
        if (
            row is None
            or blocked(caller_did, row["author_did"])
            or blocked(p.author_did, row["author_did"])
            or not await _readable(conn, row, caller_did)
        ):
            p.quoted_post = QuotedPost(unavailable=True)
            continue
        p.quoted_post = QuotedPost(
            post_id=row["post_id"],
            author_did=row["author_did"],
            author_handle=row["author_handle"],
            author_name=row["author_name"],
            post_type=row["post_type"],
            title=row["title"],
            content=row["content"],
            created_at=row["created_at"],
        )
