"""
Images on posts — Layer 1 S4-4.

Step two of the two-step upload (step one is ``POST /media``): a post,
reply, thread item or quote names up to `MAX_POST_MEDIA` uploads in
``media_ids`` and :func:`attach` puts them on it **inside the post's write
transaction**. Every id must be

* an ``UPLOAD`` owned by the author (someone else's id, a link thumbnail or
  an id that does not exist all get the same ``media_not_found``, so ids
  cannot be probed),
* not on a post yet (``media_in_use``; a thread naming one id twice fails
  here too, and the whole thread is rolled back),
* not ``REJECTED`` (``media_rejected``),
* listed once (``media_duplicate``),

and ``MEDIA_ENABLED`` must be on (``media_disabled``). One bad id refuses the
whole write with 422 ``{code, message}``. Rows are locked (``FOR UPDATE``)
so two concurrent posts cannot both take the same upload.

A held or hidden post's images go back to ``PENDING`` (:func:`hold`, called
by ``post_moderation`` wherever it hides a post): a moderator approves them
again in the S4-5 queue. Unhiding a post does not approve them by itself.

Reading (:func:`annotate`, one query per page, plus one role lookup when a
page carries someone else's pending image): ``media`` on every post
response, in grid order, rejected images left out. A ``PENDING`` image
keeps ``url`` and ``alt_text`` only for its owner and FOUNDER / OPERATOR
moderators; everyone else gets ``{media_id, status, width, height}`` to
draw an "Image awaiting review" placeholder.
"""
from __future__ import annotations

from typing import Iterable, Optional
from uuid import UUID

from fastapi import HTTPException, status

from ..models.post import MAX_POST_MEDIA, PostMedia

__all__ = ["MAX_POST_MEDIA", "attach", "hold", "annotate", "media_url", "rejected_before"]


def media_url(media_id: UUID, ext: str) -> str:
    """Path of the file, relative to the API's own address (as routers/media.py)."""
    return f"/media/{media_id}.{ext}"


def _refuse(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": code, "message": message},
    )


def check_enabled(media_ids: Iterable) -> None:
    """422 ``media_disabled`` when images are named while uploads are off.
    Cheap, so routes call it before doing any other work."""
    from ..routers.media import media_enabled

    if list(media_ids) and not media_enabled():
        raise _refuse("media_disabled", "Images on posts are switched off.")


async def attach(conn, author_did: str, post_id: UUID, media_ids: list[UUID]) -> None:
    """Put *media_ids* on *post_id* in this order (positions 0..3). Call it in
    the transaction that inserted the post, before the post can be held."""
    if not media_ids:
        return
    check_enabled(media_ids)
    if len(media_ids) > MAX_POST_MEDIA:
        raise _refuse("too_many_media", f"At most {MAX_POST_MEDIA} images per post.")
    if len(set(media_ids)) != len(media_ids):
        raise _refuse("media_duplicate", "The same image is listed more than once.")
    rows = await conn.fetch(
        """
        SELECT id, owner_did, kind, status, post_id FROM media
        WHERE id = ANY($1::uuid[])
        ORDER BY id
        FOR UPDATE
        """,
        media_ids,
    )
    found = {r["id"]: r for r in rows}
    for media_id in media_ids:
        row = found.get(media_id)
        if row is None or row["owner_did"] != author_did or row["kind"] != "UPLOAD":
            raise _refuse("media_not_found", f"Image not found: {media_id}")
        if row["status"] == "REJECTED":
            raise _refuse("media_rejected", f"Image was rejected by a moderator: {media_id}")
        if row["post_id"] is not None:
            raise _refuse("media_in_use", f"Image is already on a post: {media_id}")
    for position, media_id in enumerate(media_ids):
        await conn.execute(
            "UPDATE media SET post_id = $2, position = $3 WHERE id = $1",
            media_id, post_id, position,
        )


async def rejected_before(conn, owner_did: str, sha256: str) -> bool:
    """True when a moderator has already rejected these exact bytes from this
    owner (S4-12 review). A re-upload of a rejected image then waits for a
    moderator again instead of going public at once; it is never refused
    outright, so a wrong rejection costs the owner one more review, not the
    image. Owner-scoped so the lookup rides on ``idx_media_owner_created``."""
    return bool(await conn.fetchval(
        "SELECT 1 FROM media WHERE owner_did = $1 AND sha256 = $2 AND status = 'REJECTED' LIMIT 1",
        owner_did, sha256,
    ))


async def hold(conn, post_id: UUID) -> None:
    """A held or hidden post's approved images wait for a moderator again."""
    await conn.execute(
        """
        UPDATE media SET status = 'PENDING', reviewed_at = NULL, reviewed_by = NULL
        WHERE post_id = $1 AND status = 'APPROVED'
        """,
        post_id,
    )


async def _is_moderator(conn, caller_did: Optional[str]) -> bool:
    from .post_moderation import MODERATOR_ROLES

    if caller_did is None:
        return False
    role = await conn.fetchval("SELECT governance_role FROM agents WHERE agent_did = $1", caller_did)
    return role in MODERATOR_ROLES


async def annotate(conn, posts: Iterable, caller_did: Optional[str] = None) -> None:
    """Fill ``media`` and ``has_media`` on PostResponse objects."""
    posts = list(posts)
    if not posts:
        return
    ids = list({p.post_id for p in posts})
    rows = await conn.fetch(
        """
        SELECT id, owner_did, ext, width, height, alt_text, status, post_id
        FROM media
        WHERE post_id = ANY($1::uuid[]) AND status <> 'REJECTED'
        ORDER BY post_id, position
        """,
        ids,
    )
    moderator: Optional[bool] = None
    by_post: dict = {}
    for r in rows:
        visible = r["status"] == "APPROVED" or (
            caller_did is not None and r["owner_did"] == caller_did
        )
        if not visible:
            if moderator is None:
                moderator = await _is_moderator(conn, caller_did)
            visible = moderator
        by_post.setdefault(r["post_id"], []).append(PostMedia(
            media_id=r["id"],
            status=r["status"],
            url=media_url(r["id"], r["ext"]) if visible else None,
            alt_text=r["alt_text"] if visible else None,
            width=r["width"],
            height=r["height"],
        ))
    for p in posts:
        p.media = by_post.get(p.post_id, [])
        p.has_media = bool(p.media)
    # S4-7: link cards ride on the same call, which every post reader makes.
    from . import link_cards
    await link_cards.annotate(conn, posts)
