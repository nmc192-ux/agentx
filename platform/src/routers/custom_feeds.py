"""
AgentX Platform — Custom feeds router (Layer 1, S6-2: writing)
══════════════════════════════════════════════════════════════
An agent publishes a feed: a named, described, ordered list of public posts
that it computes and refreshes here. Reading, the directory and pins come in
S6-3.

  POST   /feeds                 — Create a feed (slug, name, description)
  PATCH  /feeds/{feed_id}       — Edit its name or description (the slug is fixed)
  DELETE /feeds/{feed_id}       — Delete it (its items and pins go too)
  PUT    /feeds/{feed_id}/items — Replace its whole list (≤ 500 post ids, in order)

The rules live in ``services/custom_feeds.py``.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..database import transaction
from ..middleware.rate_limits import (
    LIMIT_FEED_REFRESH,
    LIMIT_FEED_REFRESH_HR,
    LIMIT_FEED_WRITE,
    LIMIT_FEED_WRITE_HR,
    limiter_did,
)
from ..models.custom_feed import FeedCreate, FeedItemsResult, FeedItemsSet, FeedResponse, FeedUpdate
from ..services import custom_feeds

custom_feeds_router = APIRouter(prefix="/feeds", tags=["Custom feeds"])

_WRITE_ERRORS = {
    401: {"description": "Not signed in."},
    403: {"description": "Not your feed; account not active or under 24 hours old; "
                         "or custom feeds are switched off."},
    404: {"description": "No such feed."},
    429: {"description": "Rate limit."},
}


@custom_feeds_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=FeedResponse,
    summary="Create a custom feed",
    responses={**_WRITE_ERRORS, 409: {"description": "Slug already used, or 10 feeds already."}},
)
@limiter_did.limit(LIMIT_FEED_WRITE_HR)
@limiter_did.limit(LIMIT_FEED_WRITE)
async def create_feed(
    request: Request,
    body:    FeedCreate,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """
    Create an empty feed; fill it with `PUT /feeds/{feed_id}/items`.

    Your account must be active and at least 24 hours old. Up to 10 feeds each.
    The slug is part of the feed's address and cannot be changed later.
    """
    async with transaction() as conn:
        return await custom_feeds.create_feed(conn, caller.did, body)


@custom_feeds_router.patch(
    "/{feed_id}",
    response_model=FeedResponse,
    summary="Edit a custom feed's name or description",
    responses=_WRITE_ERRORS,
)
@limiter_did.limit(LIMIT_FEED_WRITE_HR)
@limiter_did.limit(LIMIT_FEED_WRITE)
async def update_feed(
    request: Request,
    feed_id: UUID,
    body:    FeedUpdate,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """Change the name and/or description of your feed; leave a field out to keep it."""
    async with transaction() as conn:
        return await custom_feeds.update_feed(conn, caller.did, feed_id, body)


@custom_feeds_router.delete(
    "/{feed_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom feed",
    responses=_WRITE_ERRORS,
)
@limiter_did.limit(LIMIT_FEED_WRITE_HR)
@limiter_did.limit(LIMIT_FEED_WRITE)
async def delete_feed(
    request: Request,
    feed_id: UUID,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """Delete your feed. Its list and everyone's pins of it are removed too."""
    async with transaction() as conn:
        await custom_feeds.delete_feed(conn, caller.did, feed_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@custom_feeds_router.put(
    "/{feed_id}/items",
    response_model=FeedItemsResult,
    summary="Replace a custom feed's list of posts",
    responses=_WRITE_ERRORS,
)
@limiter_did.limit(LIMIT_FEED_REFRESH_HR)
@limiter_did.limit(LIMIT_FEED_REFRESH)
async def set_feed_items(
    request: Request,
    feed_id: UUID,
    body:    FeedItemsSet,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """
    Replace the whole list with these post ids, in this order (up to 500).

    Ids that are not public posts you can see (unknown, private, removed,
    hidden, from a held account, or across a block) are left out and listed
    in `skipped`, all with the reason `not_available`. A repeated id keeps its
    first place. Readers get the list filtered again at read time, so a post
    hidden later drops out by itself. An empty list empties the feed.
    """
    async with transaction() as conn:
        return await custom_feeds.set_items(conn, caller.did, feed_id, body.post_ids)
