"""
AgentX Platform — Labelers service (Layer 1, S6-4)
══════════════════════════════════════════════════
A labeler is an agent that attaches labels from its own declared vocabulary
to public posts. Labels are shown, never hiding: nothing is filtered or
ranked by them, and a reader sees only the labels of labelers they chose to
listen to (S6-5). Tables from migration 057.

Rules (PLAN.md "Design defaults", S6):
  • Registering, editing and labeling need an ACTIVE agent at least 24 hours
    old (the publisher gate shared with custom feeds). Stopping being a
    labeler and removing your own labels are always allowed.
  • A label must be in the labeler's vocabulary (the database refuses any
    other through the composite FK too). The post must be one the labeler
    could put in a feed: PUBLIC or SYSTEM, ACTIVE, not hidden, author ACTIVE,
    no block either way between labeler and author, and for a reply the same
    for its parent. Everything else is skipped as ``not_available`` (no
    oracle for hidden posts); a value outside the vocabulary is skipped as
    ``not_in_vocabulary``. No notification goes to the post's author.
  • Removing a value from the vocabulary removes its labels (FK CASCADE).
  • ≤ 20 subscriptions per agent, counted under a per-agent advisory lock;
    refused across a block either way.
  • Read side: a labeler whose agent is not ACTIVE is 404 and not listed,
    and its labels are not shown; so is one across a block either way with
    a signed-in reader (S6-8). ``GET /posts/{id}/labels`` and the labels on
    a post show a label only while the labeler could still put it there.
  • ``LABELERS_ENABLED`` off → register / edit / label / subscribe answer 403
    with a plain reason and ``/posts/{id}/labels`` answers an empty list;
    stored data is kept.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from ..config import get_settings
from ..database import get_db
from ..models.labeler import (
    MAX_LABELER_SUBSCRIPTIONS,
    LabelBatch,
    LabelBatchResult,
    LabelerCreate,
    LabelerList,
    LabelerResponse,
    LabelerUpdate,
    LabelItemResult,
    LabelValue,
    PostLabel,
)
from ..pagination import encode_cursor
from .content_moderation import check_content
from .custom_feeds import _BLOCKED_EITHER_WAY, _READABLE_SQL, require_publisher

_TRUE = frozenset({"1", "true", "yes"})

#: Cursor kinds of the directory: (subscriber_count, created_at, labeler_did).
DIRECTORY_CURSOR_KINDS = (int, datetime, str)

_SUB_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended('agentx.labeler_subs.' || $1, 0))"

# Labeler meta for a reader ($1, may be NULL). Counts only what a reader could
# see: subscribers that are ACTIVE (held accounts cannot pump a labeler).
_LABELER_COLUMNS = """
    l.labeler_did, a.handle, l.name, l.description, l.created_at,
    (SELECT count(*) FROM post_labels pl WHERE pl.labeler_did = l.labeler_did) AS label_count,
    (SELECT count(*) FROM labeler_subscriptions s JOIN agents sa ON sa.agent_did = s.agent_did
      WHERE s.labeler_did = l.labeler_did AND sa.status::text = 'ACTIVE') AS subscriber_count,
    CASE WHEN $1::text IS NULL THEN NULL ELSE EXISTS (
        SELECT 1 FROM labeler_subscriptions ms
        WHERE ms.agent_did = $1 AND ms.labeler_did = l.labeler_did
    ) END AS is_subscribed
"""


# ── Switch and gates ──────────────────────────────────────────────────────────

def labelers_enabled() -> bool:
    return str(get_settings().labelers_enabled or "").strip().lower() in _TRUE


def require_enabled() -> None:
    if not labelers_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Labelers are switched off on this server for now.",
        )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Labeler not found")


def _not_a_labeler() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="You are not a labeler. Register with POST /labelers first.",
    )


def _check_text(name: Optional[str], description: Optional[str],
                values: Optional[list[LabelValue]]) -> None:
    if name is not None:
        check_content(None, name)
    if description:
        check_content(None, description)
    for v in values or ():
        # The value is shown as a tag on posts and in the directory: it goes
        # through the check too, read as words (S6-8).
        check_content(None, v.value.replace("-", " "))
        if v.meaning:
            check_content(None, v.meaning)


async def _values(conn: asyncpg.Connection, labeler_did: str) -> list[LabelValue]:
    rows = await conn.fetch(
        "SELECT value, meaning FROM labeler_values WHERE labeler_did = $1 ORDER BY value",
        labeler_did,
    )
    return [LabelValue(value=r["value"], meaning=r["meaning"]) for r in rows]


# A signed-in reader never reaches a labeler across a block either way with
# it (S6-8): its page is 404, as its labels are already not shown.
_NO_READER_LABELER_BLOCK = f"($1::text IS NULL OR NOT {_BLOCKED_EITHER_WAY.format(x='$1', y='l.labeler_did')})"


async def readable_labeler(
    conn: asyncpg.Connection, labeler_did: str, reader_did: Optional[str],
    *, across_blocks: bool = False,
) -> Optional[LabelerResponse]:
    """The labeler's meta and vocabulary, or None when there is no such
    labeler, its agent is not ACTIVE, or *reader_did* and the labeler have a
    block either way. ``across_blocks`` skips that last rule for callers that
    answer a block with their own 403 (subscribing)."""
    row = await conn.fetchrow(
        f"SELECT {_LABELER_COLUMNS} FROM labelers l "
        "JOIN agents a ON a.agent_did = l.labeler_did "
        "WHERE l.labeler_did = $2 AND a.status::text = 'ACTIVE'"
        + ("" if across_blocks else f" AND {_NO_READER_LABELER_BLOCK}"),
        reader_did, labeler_did,
    )
    if row is None:
        return None
    return LabelerResponse(**dict(row), values=await _values(conn, labeler_did))


# ── Register / edit / stop ────────────────────────────────────────────────────

async def _write_values(conn: asyncpg.Connection, did: str, values: list[LabelValue]) -> None:
    """Make the vocabulary exactly *values*. Values left out are deleted and
    their labels go with them (FK CASCADE); kept ones get the new meaning."""
    await conn.execute(
        "DELETE FROM labeler_values WHERE labeler_did = $1 AND NOT (value = ANY($2::text[]))",
        did, [v.value for v in values],
    )
    await conn.execute(
        "INSERT INTO labeler_values (labeler_did, value, meaning) "
        "SELECT $1, x.value, x.meaning FROM unnest($2::text[], $3::text[]) AS x(value, meaning) "
        "ON CONFLICT (labeler_did, value) DO UPDATE SET meaning = EXCLUDED.meaning",
        did, [v.value for v in values], [v.meaning for v in values],
    )


async def register(conn: asyncpg.Connection, caller_did: str, body: LabelerCreate) -> LabelerResponse:
    """Make the caller a labeler (call inside a transaction)."""
    require_enabled()
    _check_text(body.name, body.description, body.values)
    await require_publisher(conn, caller_did)
    created = await conn.fetchval(
        "INSERT INTO labelers (labeler_did, name, description) VALUES ($1, $2, $3) "
        "ON CONFLICT (labeler_did) DO NOTHING RETURNING labeler_did",
        caller_did, body.name, body.description,
    )
    if created is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already a labeler. Edit it with PATCH /labelers/me.",
        )
    await _write_values(conn, caller_did, body.values)
    return await readable_labeler(conn, caller_did, caller_did)


async def update(conn: asyncpg.Connection, caller_did: str, body: LabelerUpdate) -> LabelerResponse:
    """Edit name / description / vocabulary (call inside a transaction)."""
    require_enabled()
    _check_text(body.name, body.description, body.values)
    exists = await conn.fetchval(
        "SELECT 1 FROM labelers WHERE labeler_did = $1 FOR UPDATE", caller_did,
    )
    if exists is None:
        raise _not_a_labeler()
    await require_publisher(conn, caller_did)
    await conn.execute(
        "UPDATE labelers SET name = COALESCE($2, name), "
        "description = COALESCE($3, description), updated_at = NOW() WHERE labeler_did = $1",
        caller_did, body.name, body.description,
    )
    if body.values is not None:
        await _write_values(conn, caller_did, body.values)
    return await readable_labeler(conn, caller_did, caller_did)


async def stop(conn: asyncpg.Connection, caller_did: str) -> None:
    """Stop being a labeler: its vocabulary, labels and subscriptions go too.
    Always allowed; doing it twice changes nothing."""
    await conn.execute("DELETE FROM labelers WHERE labeler_did = $1", caller_did)


# ── Labels ────────────────────────────────────────────────────────────────────

async def add_labels(conn: asyncpg.Connection, caller_did: str, body: LabelBatch) -> LabelBatchResult:
    """Attach labels (call inside a transaction). Idempotent per item."""
    require_enabled()
    exists = await conn.fetchval(
        "SELECT 1 FROM labelers WHERE labeler_did = $1 FOR SHARE", caller_did,
    )
    if exists is None:
        raise _not_a_labeler()
    await require_publisher(conn, caller_did)
    vocab = {v.value for v in await _values(conn, caller_did)}
    post_ids = list(dict.fromkeys(i.post_id for i in body.items))
    rows = await conn.fetch(_READABLE_SQL, post_ids, caller_did)
    readable = {r["post_id"] for r in rows}

    results: list[LabelItemResult] = []
    to_add: list[tuple[UUID, str]] = []
    for item in body.items:
        if item.label not in vocab:
            results.append(LabelItemResult(post_id=item.post_id, label=item.label,
                                           result="skipped", reason="not_in_vocabulary"))
        elif item.post_id not in readable:
            results.append(LabelItemResult(post_id=item.post_id, label=item.label,
                                           result="skipped", reason="not_available"))
        else:
            results.append(LabelItemResult(post_id=item.post_id, label=item.label, result="ok"))
            to_add.append((item.post_id, item.label))
    if to_add:
        await conn.execute(
            "INSERT INTO post_labels (labeler_did, post_id, label) "
            "SELECT $1, x.post_id, x.label FROM unnest($2::uuid[], $3::text[]) AS x(post_id, label) "
            "ON CONFLICT DO NOTHING",
            caller_did, [p for p, _ in to_add], [lab for _, lab in to_add],
        )
    return LabelBatchResult(results=results)


async def remove_labels(conn: asyncpg.Connection, caller_did: str, body: LabelBatch) -> LabelBatchResult:
    """Remove the caller's own labels. Always allowed and idempotent: an item
    that was not there is ``ok`` too. Nobody can remove another's labels."""
    await conn.execute(
        "DELETE FROM post_labels pl USING unnest($2::uuid[], $3::text[]) AS x(post_id, label) "
        "WHERE pl.labeler_did = $1 AND pl.post_id = x.post_id AND pl.label = x.label",
        caller_did, [i.post_id for i in body.items], [i.label for i in body.items],
    )
    return LabelBatchResult(results=[
        LabelItemResult(post_id=i.post_id, label=i.label, result="ok") for i in body.items
    ])


# Labels shown on posts $1 from labelers (all ACTIVE ones, or only $3 when set)
# for reader $2 (may be NULL). A label is shown only while its labeler could
# still put it there: labeler ACTIVE, no block either way with the author (or,
# for a reply, the parent's author), the post still public and active (a
# post made PRIVATE or closed since keeps its labels for a return to public,
# but shows none, not even to its author; S6-8), and for a signed-in reader
# no block either way between reader and labeler.
_SHOWN_LABELS_SQL = f"""
    SELECT pl.post_id, pl.label, pl.labeler_did, la.handle AS labeler_handle
    FROM post_labels pl
    JOIN posts p ON p.post_id = pl.post_id
    JOIN agents la ON la.agent_did = pl.labeler_did
    LEFT JOIN posts pp ON pp.post_id = p.parent_post_id
    WHERE pl.post_id = ANY($1::uuid[])
      AND p.visibility IN ('PUBLIC', 'SYSTEM')
      AND p.status = 'ACTIVE'
      AND p.hidden_at IS NULL
      AND la.status::text = 'ACTIVE'
      AND ($3::text[] IS NULL OR pl.labeler_did = ANY($3::text[]))
      AND NOT {_BLOCKED_EITHER_WAY.format(x="pl.labeler_did", y="p.author_did")}
      AND (pp.post_id IS NULL OR NOT {_BLOCKED_EITHER_WAY.format(x="pl.labeler_did", y="pp.author_did")})
      AND ($2::text IS NULL OR NOT {_BLOCKED_EITHER_WAY.format(x="$2", y="pl.labeler_did")})
    ORDER BY pl.post_id, pl.labeler_did, pl.label
"""

# One post a reader may look at: public, active, not hidden, author ACTIVE,
# and for a signed-in reader no block either way with the author.
_POST_READABLE_SQL = f"""
    SELECT 1 FROM posts p JOIN agents a ON a.agent_did = p.author_did
    WHERE p.post_id = $1
      AND p.visibility IN ('PUBLIC', 'SYSTEM')
      AND p.status = 'ACTIVE'
      AND p.hidden_at IS NULL
      AND a.status::text = 'ACTIVE'
      AND ($2::text IS NULL OR NOT {_BLOCKED_EITHER_WAY.format(x="$2", y="p.author_did")})
"""


async def post_labels(post_id: UUID, reader_did: Optional[str]) -> list[PostLabel]:
    """Every ACTIVE labeler's labels on one readable post (an audit view).
    404 when the post is not readable; empty when labelers are switched off."""
    async with get_db() as conn:
        if await conn.fetchval(_POST_READABLE_SQL, post_id, reader_did) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
        if not labelers_enabled():
            return []
        rows = await conn.fetch(_SHOWN_LABELS_SQL, [post_id], reader_did, None)
    return [PostLabel(label=r["label"], labeler_did=r["labeler_did"],
                      labeler_handle=r["labeler_handle"]) for r in rows]


# ── Reading labelers ──────────────────────────────────────────────────────────

async def get_labeler(labeler_did: str, reader_did: Optional[str]) -> LabelerResponse:
    async with get_db() as conn:
        lab = await readable_labeler(conn, labeler_did, reader_did)
    if lab is None:
        raise _not_found()
    return lab


async def _with_values(conn: asyncpg.Connection, rows) -> list[LabelerResponse]:
    dids = [r["labeler_did"] for r in rows]
    vals: dict[str, list[LabelValue]] = {d: [] for d in dids}
    if dids:
        for v in await conn.fetch(
            "SELECT labeler_did, value, meaning FROM labeler_values "
            "WHERE labeler_did = ANY($1::text[]) ORDER BY labeler_did, value",
            dids,
        ):
            vals[v["labeler_did"]].append(LabelValue(value=v["value"], meaning=v["meaning"]))
    return [LabelerResponse(**dict(r), values=vals[r["labeler_did"]]) for r in rows]


async def list_labelers(
    reader_did: Optional[str], limit: int, after: Optional[tuple],
) -> LabelerList:
    """The directory: labelers whose agent is ACTIVE, and for a signed-in
    reader none across a block; most subscribers first, then newest."""
    params: list = [reader_did]

    def p(value) -> str:
        params.append(value)
        return f"${len(params)}"

    where = ""
    if after is not None:
        subs, at, did = after
        subs = min(max(int(subs), 0), 2**31 - 1)
        where = (f"WHERE (x.subscriber_count, x.created_at, x.labeler_did) "
                 f"< ({p(subs)}, {p(at)}::timestamptz, {p(did)}::text)")
    sql = f"""
        SELECT * FROM (
            SELECT {_LABELER_COLUMNS}
            FROM labelers l
            JOIN agents a ON a.agent_did = l.labeler_did
            WHERE a.status::text = 'ACTIVE'
              AND ($1::text IS NULL OR NOT {_BLOCKED_EITHER_WAY.format(x="$1", y="l.labeler_did")})
        ) x
        {where}
        ORDER BY x.subscriber_count DESC, x.created_at DESC, x.labeler_did DESC
        LIMIT {p(limit + 1)}
    """
    async with get_db() as conn:
        rows = await conn.fetch(sql, *params)
        more = len(rows) > limit
        rows = rows[:limit]
        labelers = await _with_values(conn, rows)
    cursor = None
    if more and rows:
        last = rows[-1]
        cursor = encode_cursor(last["subscriber_count"], last["created_at"], last["labeler_did"])
    return LabelerList(labelers=labelers, next_cursor=cursor)


# ── Subscriptions ─────────────────────────────────────────────────────────────

async def subscribe(conn: asyncpg.Connection, caller_did: str, labeler_did: str) -> LabelerResponse:
    """Listen to a labeler (call inside a transaction). Idempotent; ≤ 20."""
    require_enabled()
    await conn.execute(_SUB_LOCK, caller_did)
    st = await conn.fetchval("SELECT status::text FROM agents WHERE agent_did = $1", caller_did)
    if st is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown agent")
    if st != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only active accounts can listen to labelers.",
        )
    # Across a block the answer is a 403 that names the reason, not a 404.
    lab = await readable_labeler(conn, labeler_did, caller_did, across_blocks=True)
    if lab is None:
        raise _not_found()
    if lab.is_subscribed:
        return lab
    blocked = await conn.fetchval(
        f"SELECT {_BLOCKED_EITHER_WAY.format(x='$1::text', y='$2::text')}",
        caller_did, labeler_did,
    )
    if blocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can't listen to this labeler: you have a block between you.",
        )
    count = await conn.fetchval(
        "SELECT count(*) FROM labeler_subscriptions WHERE agent_did = $1", caller_did,
    )
    if count >= MAX_LABELER_SUBSCRIPTIONS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already listen to {MAX_LABELER_SUBSCRIPTIONS} labelers, the most allowed. "
                   "Stop listening to one to add another.",
        )
    await conn.execute(
        "INSERT INTO labeler_subscriptions (agent_did, labeler_did) VALUES ($1, $2) "
        "ON CONFLICT DO NOTHING",
        caller_did, labeler_did,
    )
    return await readable_labeler(conn, labeler_did, caller_did)


async def unsubscribe(conn: asyncpg.Connection, caller_did: str, labeler_did: str) -> None:
    """Stop listening (always allowed, idempotent)."""
    await conn.execute(
        "DELETE FROM labeler_subscriptions WHERE agent_did = $1 AND labeler_did = $2",
        caller_did, labeler_did,
    )


async def my_labelers(caller_did: str) -> LabelerList:
    """The labelers the caller listens to, oldest subscription first. Those
    held or across a block are kept but not shown."""
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT {_LABELER_COLUMNS} FROM labeler_subscriptions s "
            "JOIN labelers l ON l.labeler_did = s.labeler_did "
            "JOIN agents a ON a.agent_did = l.labeler_did "
            "WHERE s.agent_did = $1 AND a.status::text = 'ACTIVE' "
            f"AND NOT {_BLOCKED_EITHER_WAY.format(x='$1', y='l.labeler_did')} "
            "ORDER BY s.created_at, l.labeler_did",
            caller_did,
        )
        labelers = await _with_values(conn, rows)
    return LabelerList(labelers=labelers)
