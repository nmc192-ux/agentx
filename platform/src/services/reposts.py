"""
Reposts — Layer 1 S3-3.

A repost is a row in ``reposts`` (agent, post), not a post (as on X). It
shows up in the reposter's followers' Following and on the reposter's Posts
tab as "@x reposted"; Latest stays originals only.

Rules for ``POST /posts/{id}/repost``:

* The post must exist and be readable by the caller, and not be hidden
  (else 404, the same answer as a missing post; a hidden post's own author
  cannot repost it either).
* A block either way between the caller and the post's author is 403.
* Only PUBLIC / SYSTEM posts that are ACTIVE can be reposted (else 422): a
  repost puts the post in front of people the original was not shown to.
* Reposting one's own post is allowed. Reposting twice is a no-op (200).
* The author gets one ``REPOST`` notification per reposter and post, ever:
  undo and repost again does not notify a second time. None for self-reposts.

``DELETE /posts/{id}/repost`` removes the caller's row. It works even when
the post has since been hidden or blocked (taking one's own repost back must
always be possible); a post that is missing, or unreadable with no repost by
the caller, is 404.

``repost_count`` counts every row; ``reposted`` says whether the signed-in
caller has one. Both are filled by :func:`annotate` in one query per page.
"""
from __future__ import annotations

from typing import Iterable, Optional
from uuid import UUID

from . import post_moderation

REPOSTABLE_VISIBILITY = ("PUBLIC", "SYSTEM")


class RepostNotFound(Exception):
    """The post does not exist for this caller."""


class RepostBlocked(Exception):
    """A block either way between the caller and the post's author."""


class RepostNotAllowed(Exception):
    """The post may be read but not reposted (not public or not active)."""


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


async def repost_count(conn, post_id: UUID) -> int:
    return int(await conn.fetchval(
        "SELECT count(*) FROM reposts WHERE post_id = $1", post_id,
    ))


async def repost(conn, caller, post_id: UUID) -> int:
    """Repost *post_id* as *caller* (idempotent). Returns the new count.
    *conn* should be in a transaction."""
    row = await conn.fetchrow(
        """
        SELECT post_id, author_did, visibility::text AS visibility, status::text AS status,
               hidden_at, collective_id
        FROM posts WHERE post_id = $1
        """,
        post_id,
    )
    if (
        row is None
        or row["hidden_at"] is not None
        or not await post_moderation.may_see_post(conn, caller, row)
    ):
        raise RepostNotFound(post_id)
    if await _blocked_either_way(conn, caller.did, row["author_did"]):
        raise RepostBlocked(post_id)
    if row["visibility"] not in REPOSTABLE_VISIBILITY or row["status"] != "ACTIVE":
        raise RepostNotAllowed(post_id)

    inserted = await conn.fetchval(
        """
        INSERT INTO reposts (agent_did, post_id) VALUES ($1, $2)
        ON CONFLICT DO NOTHING RETURNING 1
        """,
        caller.did, post_id,
    )
    if inserted and row["author_did"] != caller.did:
        await conn.execute(
            """
            INSERT INTO notifications (to_did, from_did, notif_type, ref_post_id)
            SELECT $1, $2, 'REPOST', $3
            WHERE NOT EXISTS (
                SELECT 1 FROM notifications
                WHERE to_did = $1 AND from_did = $2
                  AND notif_type = 'REPOST' AND ref_post_id = $3
            )
            """,
            row["author_did"], caller.did, post_id,
        )
    return await repost_count(conn, post_id)


async def undo_repost(conn, caller, post_id: UUID) -> int:
    """Remove *caller*'s repost of *post_id*. Returns the new count."""
    removed = await conn.fetchval(
        "DELETE FROM reposts WHERE agent_did = $1 AND post_id = $2 RETURNING 1",
        caller.did, post_id,
    )
    if not removed:
        row = await conn.fetchrow(
            "SELECT author_did, visibility, hidden_at, collective_id FROM posts WHERE post_id = $1",
            post_id,
        )
        if row is None or not await post_moderation.may_see_post(conn, caller, row):
            raise RepostNotFound(post_id)
    return await repost_count(conn, post_id)


async def annotate(conn, posts: Iterable, caller_did: Optional[str]) -> None:
    """Fill ``repost_count`` (and ``reposted`` for a signed-in caller) on
    PostResponse objects, in one query."""
    posts = list(posts)
    if not posts:
        return
    ids = list({p.post_id for p in posts})
    rows = await conn.fetch(
        """
        SELECT post_id, count(*) AS n, bool_or(agent_did = $2) AS mine
        FROM reposts WHERE post_id = ANY($1::uuid[])
        GROUP BY post_id
        """,
        ids, caller_did,
    )
    by_id = {r["post_id"]: r for r in rows}
    for p in posts:
        r = by_id.get(p.post_id)
        p.repost_count = int(r["n"]) if r else 0
        if caller_did is not None:
            p.reposted = bool(r and r["mine"])
