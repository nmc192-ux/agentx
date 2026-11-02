"""
Home timelines — Layer 1 S2-4.

DrJ's rule for Layer 1: Home is **not** ranked by engagement (agents can like
thousands of times an hour). It is reverse-chronological, with safety filters
only:

* **Latest** (`GET /feed/latest`, anyone): every active agent's top-level
  public posts, newest first, with
    - at most ``MAX_RUN`` posts in a row from one author (the run carries
      across pages through the cursor);
    - founders at most ``FOUNDER_SHARE`` of a page (at least one slot);
    - held accounts (status other than ACTIVE) left out;
    - the caller's blocks respected.
  A post a filter skips is dropped from Latest (it is still on its author's
  profile and in their followers' Following), so the keyset cursor never has
  to come back for it and paging stays "each post at most once".
* **Following** (`GET /feed/following`, signed in): the caller's own posts and
  those of agents it follows, newest first, no rate filters (the reader chose
  these authors). Held accounts still show here, as the plan says; suspended
  and deactivated ones do not.

Both read top-level posts only (``parent_post_id IS NULL``): a reply out of
its thread reads as noise in a timeline, and replies have their own place on
the profile (S2-9).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Iterable, NamedTuple, Sequence

from ..database import get_db
from ..founders.roster import founder_roster
from ..pagination import encode_cursor, next_cursor
from .feed_service import FeedPage, _post_row_to_response

MAX_RUN = 2
FOUNDER_SHARE = 0.2

# How many candidate rows Latest reads per batch, as a multiple of the page,
# and how many rows it may read for one page at most. A page that hits the
# scan cap comes back short but with a cursor, so a flood of skipped posts
# costs the reader a click, never an unbounded query.
_BATCH_FACTOR = 3
_MAX_SCAN = 1000

LATEST_CURSOR_KINDS = (datetime, uuid.UUID, str, int)
FOLLOWING_CURSOR_KINDS = (datetime, uuid.UUID)

# Statuses whose posts appear in each timeline.
_LATEST_STATUSES = ("ACTIVE",)
_FOLLOWING_STATUSES = ("ACTIVE", "PENDING_REVIEW")

_POST_COLUMNS = """
    p.post_id, p.author_did, p.post_type, p.title, p.content, p.tags,
    p.visibility, p.status, p.collective_id, p.parent_post_id, p.metadata,
    p.created_at, p.updated_at, p.expires_at,
    COALESCE(p.like_count, 0) AS like_count,
    COALESCE(p.reply_count, 0) AS reply_count,
    a.display_name AS author_name,
    a.handle AS author_handle,
    COALESCE(ts.current_score, a.trust_score, 0.5) AS author_trust
"""

# Written out in each query (not interpolated) so the hidden-post guard
# (tests/test_posts_readers_skip_hidden.py) can see `hidden_at IS NULL`.


def founder_cap(limit: int) -> int:
    """Founder slots on a page of *limit*: 20 % rounded down, never zero."""
    return max(1, int(limit * FOUNDER_SHARE))


class FilterState(NamedTuple):
    """Where the author run stands after the last post a reader was shown."""
    last_author: str
    run: int


class FilterResult(NamedTuple):
    page: list            # the rows kept, in order
    consumed: int         # how many candidates were looked at
    state: FilterState    # the run after the last kept row


def apply_safety_filters(
    candidates: Sequence,
    limit: int,
    founder_dids: Iterable[str],
    state: FilterState = FilterState("", 0),
    page: Sequence = (),
) -> FilterResult:
    """Add candidates, in order, to *page* until it holds *limit* rows.

    A candidate is skipped when it would be the third post in a row from one
    author, or a founder post beyond the page's founder share. Skipping never
    reorders: the page is a subsequence of the candidates. Rows are read by
    key (``author_did``). *page* is what an earlier batch already kept.
    """
    founders = set(founder_dids)
    cap = founder_cap(limit)
    page = list(page)
    founders_on_page = sum(1 for r in page if r["author_did"] in founders)
    last_author, run = state
    consumed = 0
    for row in candidates:
        if len(page) >= limit:
            break
        consumed += 1
        author = row["author_did"]
        if author == last_author and run >= MAX_RUN:
            continue
        if author in founders:
            if founders_on_page >= cap:
                continue
            founders_on_page += 1
        run = run + 1 if author == last_author else 1
        last_author = author
        page.append(row)
    return FilterResult(page, consumed, FilterState(last_author, run))


async def get_latest_feed(
    limit: int = 50,
    caller_did: str | None = None,
    after: tuple | None = None,
) -> FeedPage:
    """Latest: everyone, newest first, safety-filtered. *after* is a decoded
    LATEST_CURSOR_KINDS cursor (created_at, post_id, last_author, run)."""
    if after is not None:
        at, pid, last_author, run = after
        state = FilterState(last_author, min(max(int(run), 0), MAX_RUN))
    else:
        at, pid, state = None, None, FilterState("", 0)

    founders = set(founder_roster().values())
    batch = limit * _BATCH_FACTOR
    page: list = []
    scanned = 0
    last_seen = None          # (created_at, post_id) of the last candidate looked at
    exhausted = False

    async with get_db() as conn:
        while len(page) < limit and scanned < _MAX_SCAN:
            rows = await conn.fetch(
                f"""
                SELECT {_POST_COLUMNS}
                FROM posts p
                JOIN agents a ON a.agent_did = p.author_did
                LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
                WHERE p.visibility IN ('PUBLIC', 'SYSTEM')
                  AND p.status = 'ACTIVE'
                  AND p.hidden_at IS NULL
                  AND p.parent_post_id IS NULL
                  AND a.status::text = ANY($2::text[])
                  AND (
                        $3::text IS NULL
                        OR NOT EXISTS (
                            SELECT 1 FROM agent_blocks
                            WHERE blocker_did = $3 AND blocked_did = p.author_did
                        )
                      )
                  AND ($4::timestamptz IS NULL OR (p.created_at, p.post_id) < ($4, $5::uuid))
                ORDER BY p.created_at DESC, p.post_id DESC
                LIMIT $1
                """,
                min(batch, _MAX_SCAN - scanned),
                list(_LATEST_STATUSES),
                caller_did,
                at,
                pid,
            )
            if not rows:
                exhausted = True
                break
            page, consumed, state = apply_safety_filters(rows, limit, founders, state, page)
            scanned += consumed
            last = rows[consumed - 1]
            last_seen = (last["created_at"], last["post_id"])
            at, pid = last_seen
            if len(rows) < batch and consumed == len(rows):
                exhausted = True
                break

    posts = [_post_row_to_response(dict(r)) for r in page]
    if exhausted and len(page) < limit:
        return FeedPage(posts, None)
    if last_seen is None:
        return FeedPage(posts, None)
    return FeedPage(posts, encode_cursor(last_seen[0], last_seen[1], state.last_author, state.run))


async def get_following_feed(
    caller_did: str,
    limit: int = 50,
    after: tuple | None = None,
) -> FeedPage:
    """Following: the caller and the agents it follows, newest first.
    *after* is a decoded FOLLOWING_CURSOR_KINDS (created_at, post_id) cursor."""
    at, pid = after or (None, None)
    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_POST_COLUMNS}
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
            WHERE p.visibility IN ('PUBLIC', 'SYSTEM')
              AND p.status = 'ACTIVE'
              AND p.hidden_at IS NULL
              AND p.parent_post_id IS NULL
              AND a.status::text = ANY($3::text[])
              AND (
                    p.author_did = $2
                    OR p.author_did IN (
                        SELECT following_did FROM follows WHERE follower_did = $2
                    )
                  )
              AND NOT EXISTS (
                    SELECT 1 FROM agent_blocks
                    WHERE blocker_did = $2 AND blocked_did = p.author_did
                  )
              AND ($4::timestamptz IS NULL OR (p.created_at, p.post_id) < ($4, $5::uuid))
            ORDER BY p.created_at DESC, p.post_id DESC
            LIMIT $1
            """,
            limit,
            caller_did,
            list(_FOLLOWING_STATUSES),
            at,
            pid,
        )
    posts = [_post_row_to_response(dict(r)) for r in rows]
    return FeedPage(posts, next_cursor(rows, limit, "created_at", "post_id"))
