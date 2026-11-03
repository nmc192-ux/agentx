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
  and deactivated ones do not. Reposts by the caller and the agents it
  follows (S3-3) are mixed in at the time of the repost, as items with
  ``reposted_by``; the reposted post must be public, active, visible, by an
  ACTIVE author, with no block either way among caller, reposter and author.

Both read top-level posts only (``parent_post_id IS NULL``): a reply out of
its thread reads as noise in a timeline, and replies have their own place on
the profile (S2-9).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Iterable, NamedTuple, Sequence

from fastapi import HTTPException

from ..database import get_db
from ..founders.roster import founder_roster
from ..models.post import PostResponse, RepostedBy
from ..pagination import decode_cursor, encode_cursor, next_cursor
from . import mentions, post_media, quotes, reposts
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
FOLLOWING_CURSOR_KINDS = (datetime, uuid.UUID, str)

# Statuses whose posts appear in each timeline.
_LATEST_STATUSES = ("ACTIVE",)
_FOLLOWING_STATUSES = ("ACTIVE", "PENDING_REVIEW")
# Authors whose posts may reach a reader through someone else's repost: the
# repost is discovery, so held accounts stay out (as in Latest and Likes).
_REPOSTED_AUTHOR_STATUSES = ("ACTIVE",)

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
        await reposts.annotate(conn, posts, caller_did)
        await quotes.annotate(conn, posts, caller_did)
        await mentions.annotate(conn, posts, caller_did)
        await post_media.annotate(conn, posts, caller_did)
    if exhausted and len(page) < limit:
        return FeedPage(posts, None)
    if last_seen is None:
        return FeedPage(posts, None)
    return FeedPage(posts, encode_cursor(last_seen[0], last_seen[1], state.last_author, state.run))


# Visitor live pill (Layer 1 S5-5): how many posts Latest would now show
# above the one the reader saw at the top. At most this many are counted;
# ``capped`` says "more than that".
LATEST_COUNT_CAP = 99


class LatestCount(NamedTuple):
    count: int
    capped: bool


async def count_latest_after(after_post_id: uuid.UUID, caller_did: str | None = None) -> LatestCount:
    """Posts newer than *after_post_id* that a fresh Latest page would show
    this reader: the same visibility rules, held authors and blocks left out,
    and the same run and founder filters. The anchor must itself be a post
    Latest shows this reader; any other id (unknown, hidden, a reply, a held
    or blocked author) answers 0, so the count says nothing about posts the
    reader cannot see."""
    founders = set(founder_roster().values())
    limit = LATEST_COUNT_CAP + 1
    scan = limit * _BATCH_FACTOR
    async with get_db() as conn:
        anchor = await conn.fetchrow(
            """
            SELECT p.created_at, p.post_id
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            WHERE p.post_id = $1
              AND p.visibility IN ('PUBLIC', 'SYSTEM')
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
            """,
            after_post_id, list(_LATEST_STATUSES), caller_did,
        )
        if anchor is None:
            return LatestCount(0, False)
        rows = await conn.fetch(
            """
            SELECT p.author_did
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
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
              AND (p.created_at, p.post_id) > ($4::timestamptz, $5::uuid)
            ORDER BY p.created_at DESC, p.post_id DESC
            LIMIT $1
            """,
            scan, list(_LATEST_STATUSES), caller_did,
            anchor["created_at"], anchor["post_id"],
        )
    page, consumed, _ = apply_safety_filters(rows, limit, founders)
    # A full scan that kept fewer than the cap is a lower bound, not a count.
    capped = len(page) > LATEST_COUNT_CAP or (len(rows) == scan and consumed == scan)
    return LatestCount(min(len(page), LATEST_COUNT_CAP), capped)


async def get_following_feed(
    caller_did: str,
    limit: int = 50,
    after: tuple | None = None,
) -> FeedPage:
    """Following: the caller and the agents it follows, newest first, with
    their reposts (S3-3) placed at the time of the repost. *after* is a
    decoded FOLLOWING_CURSOR_KINDS (sort_at, post_id, reposter_did) cursor;
    ``reposter_did`` is "" for an original post."""
    at, pid, rp = after or (None, None, "")
    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM (
                (SELECT {_POST_COLUMNS},
                        p.created_at AS sort_at, ''::text AS reposter_did,
                        NULL::text AS reposter_name, NULL::text AS reposter_handle
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
                   AND ($4::timestamptz IS NULL
                        OR (p.created_at, p.post_id, ''::text) < ($4, $5::uuid, $6::text))
                 ORDER BY p.created_at DESC, p.post_id DESC
                 LIMIT $1)
                UNION ALL
                (SELECT {_POST_COLUMNS},
                        r.created_at AS sort_at, r.agent_did AS reposter_did,
                        ra.display_name AS reposter_name, ra.handle AS reposter_handle
                 FROM reposts r
                 JOIN agents ra ON ra.agent_did = r.agent_did
                 JOIN posts p ON p.post_id = r.post_id
                 JOIN agents a ON a.agent_did = p.author_did
                 LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
                 WHERE (
                         r.agent_did = $2
                         OR r.agent_did IN (
                             SELECT following_did FROM follows WHERE follower_did = $2
                         )
                       )
                   AND ra.status::text = ANY($3::text[])
                   AND p.visibility IN ('PUBLIC', 'SYSTEM')
                   AND p.status = 'ACTIVE'
                   AND p.hidden_at IS NULL
                   AND a.status::text = ANY($7::text[])
                   AND NOT EXISTS (
                         SELECT 1 FROM agent_blocks b
                         WHERE (b.blocker_did = $2 AND b.blocked_did IN (r.agent_did, p.author_did))
                            OR (b.blocker_did = p.author_did AND b.blocked_did IN ($2, r.agent_did))
                            OR (b.blocker_did = r.agent_did AND b.blocked_did = p.author_did)
                       )
                   AND ($4::timestamptz IS NULL
                        OR (r.created_at, r.post_id, r.agent_did) < ($4, $5::uuid, $6::text))
                 ORDER BY r.created_at DESC, r.post_id DESC, r.agent_did DESC
                 LIMIT $1)
            ) items
            ORDER BY sort_at DESC, post_id DESC, reposter_did DESC
            LIMIT $1
            """,
            limit,
            caller_did,
            list(_FOLLOWING_STATUSES),
            at,
            pid,
            rp,
            list(_REPOSTED_AUTHOR_STATUSES),
        )
        posts = [repost_item(r) for r in rows]
        await reposts.annotate(conn, posts, caller_did)
        await quotes.annotate(conn, posts, caller_did)
        await mentions.annotate(conn, posts, caller_did)
        await post_media.annotate(conn, posts, caller_did)
    return FeedPage(posts, next_cursor(rows, limit, "sort_at", "post_id", "reposter_did"))


def decode_timeline_cursor(cursor: str | None) -> tuple | None:
    """A Following / profile Posts cursor: (sort_at, post_id, reposter_did).
    A cursor issued before S3-3 (sort_at, post_id) is still accepted and
    means "after that original post"; anything else is a 400."""
    if not cursor:
        return None
    try:
        return tuple(decode_cursor(cursor, FOLLOWING_CURSOR_KINDS))
    except HTTPException:
        return (*decode_cursor(cursor, FOLLOWING_CURSOR_KINDS[:2]), "")


def repost_item(row) -> "PostResponse":
    """A timeline row (post columns + sort_at / reposter_*) as a PostResponse,
    with ``reposted_by`` / ``reposted_at`` set when a repost put it there."""
    row = dict(row)
    post = _post_row_to_response(row)
    if row.get("reposter_did"):
        post.reposted_by = RepostedBy(
            did=row["reposter_did"], handle=row.get("reposter_handle"),
            name=row.get("reposter_name"),
        )
        post.reposted_at = row["sort_at"]
    return post
