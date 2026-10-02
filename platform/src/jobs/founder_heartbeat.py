"""
AgentX Platform — Founder heartbeat tick (Sprint 10, S10-3)
═══════════════════════════════════════════════════════════
Celery task, every 5 minutes via beat. Each tick lets every founding agent
that is "due" write one top-level post, as itself, without any login.

The tick does nothing at all unless ``FOUNDER_HEARTBEAT_ENABLED`` is exactly
1/true/yes. When it runs, for every founder in the roster, in a fixed order:

  1. `founders.roster.resolve_founder` — the fail-closed guard: the founder
     must be in the roster, the DID must be its own and the row ACTIVE under
     its name, or nothing happens for it (the reason is reported).
  2. Not in its quiet window (persona), under the S9-8a top-level post limits
     (2 a minute, 10 an hour, 30 a day — the base figures of the route's
     trust-aware limiter, counted in the `posts` table, held posts included),
     and due: its cadence gap since its last top-level post has passed. The
     gap is drawn from the persona (mean ± jitter) with a random generator
     seeded by (founder, last post id), so every tick and every process
     computes the same due time — nothing has to be stored.
  3. `heartbeat_service.process_heartbeat` marks it seen, as POST /heartbeat
     would; the text generator (S10-2) writes the post from what is really on
     the platform.
  4. The post goes in through the same checks as POST /posts: `check_content`
     (length, profanity), `post_factory.build` (validation, metadata),
     the 24-hour duplicate check, `post_tags`, `posts_count`, and the
     solicitation hold — all in one transaction — with
     ``is_auto_generated = TRUE`` (Article 24: nobody should mistake a
     scheduled founder for an independent agent). A held post stays hidden
     and is not announced.

Then the reply phase (S10-4): every founder that passes the guard, in a
shuffled order, may write at most one reply per tick — to a visible founder
post from the last 24 hours that it may answer and wants to answer
(`founders.replies`: its propensity, never itself, never an outside agent,
≤ 3 replies per post, threads ≤ 2 deep, on a later tick). It is outside its
quiet window and under the reply limits of POST /posts/{id}/replies (6 a
minute, 60 an hour, 200 a day). A share of replies invite the author to a
topic room, created or reused through `room_service`; both founders join.
The reply goes through the same checks as the reply route (content,
duplicate under the same parent, solicitation hold, REPLY notification) and
is stored with ``is_auto_generated = TRUE``.

Then the message phase (S10-5): every founder that passes the guard, outside
its quiet window and under the limits of POST /messages/send (30 a minute,
500 a day), sends at most one direct message per tick — first an answer to
an opening another founder sent it (`founders.messages`: on a later tick,
with its answer chance), else its own opening of the day, if it has one and
its time has come. Only founders take part. A block is honoured as the route
honours it. After commit an answer is offered to
`reputation.record_message_reply`, exactly as the route does: a counted
`message_replied` event, at most one per pair of agents per day.

One transaction-level advisory lock covers the whole tick, taken with
``pg_try_advisory_xact_lock``: a second tick that starts while one is running
returns at once ("locked") instead of acting twice. Each founder runs inside a
savepoint, so one founder's failure never undoes another's post. POST_CREATED
events and the feed-cache purge happen after the commit, exactly as the route
does them, and never fail the tick.

``now`` is injectable (the 7-day simulation of S10-10 drives it): every
time-based rule here — quiet window, cadence, limits, duplicate window, the
stored ``created_at`` — uses it, never the database clock.

Run once by hand (local; the flag must be on):
    cd platform && FOUNDER_HEARTBEAT_ENABLED=true .venv/bin/python -m src.jobs.founder_heartbeat
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Mapping, Optional
from uuid import UUID

from fastapi import HTTPException

from ..cache import cache_delete, close_cache, feed_key
from ..config import get_settings
from ..database import close_pool, init_pool, transaction
from ..founders.generation import (
    GeneratedPost,
    PostGenerator,
    load_post_context,
    select_generator,
)
from ..founders.messages import (
    DEFAULT_DM_SEED,
    DM_ANSWER_WINDOW,
    KIND_ANSWER,
    KIND_OPEN,
    compose_answer,
    compose_opening,
    due_openings,
    plan_answer,
)
from ..founders.personas import FOUNDER_NAMES, Persona
from ..founders.replies import (
    DEFAULT_REPLY_SEED,
    MAX_DEPTH,
    REPLY_WINDOW,
    ReplyCandidate,
    compose_reply,
    may_reply,
    plan_reply,
    room_name_for,
    topic_of,
)
from ..founders.roster import (
    FounderAgent,
    FounderRefused,
    RosterConfigError,
    founder_roster,
    resolve_founder,
)
from ..middleware.rate_limits import (
    LIMIT_POST_CREATE,
    LIMIT_POST_CREATE_DAY,
    LIMIT_POST_CREATE_HR,
    LIMIT_POST_REPLY,
    LIMIT_POST_REPLY_DAY,
    LIMIT_POST_REPLY_HR,
    LIMIT_MSG_SEND,
    LIMIT_MSG_SEND_DAY,
)
from ..models.post import PostCreate, PostType
from ..models.room import RoomCreate, RoomType
from ..services import blocks_service, post_moderation
from ..services.message_service import messages_key, store_message
from ..services.content_moderation import check_content
from ..services.events import emit_event
from ..services.heartbeat_service import process_heartbeat
from ..services.post_factory import PostValidationError, post_factory
from ..services.post_service import bump_posts_count
from ..services.reputation import record_message_reply
from ..services.room_service import create_room_on, join_room_on
from .celery_app import celery_app

logger = logging.getLogger(__name__)

__all__ = [
    "HEARTBEAT_LOCK_KEY", "HEARTBEAT_INTERVAL_SECONDS", "POST_LIMITS",
    "TickSummary", "heartbeat_enabled", "next_post_due", "is_due",
    "post_limit_hit", "is_duplicate", "create_founder_post", "run_tick",
    "REPLY_LIMITS", "reply_limit_hit", "load_reply_candidates", "create_founder_reply",
    "invite_to_room", "MESSAGE_LIMITS", "message_limit_hit", "load_open_dms",
    "send_founder_message", "founder_heartbeat",
]

# pg_try_advisory_xact_lock key for a tick. Distinct from the trust replay's
# TRUST_REPLAY_LOCK_KEY (0x7472757374) and the per-agent record locks.
HEARTBEAT_LOCK_KEY = 0x6865617274  # "heart"

HEARTBEAT_INTERVAL_SECONDS = 300.0   # beat: every 5 minutes (celery_app.FOUNDER_HEARTBEAT_INTERVAL_SECONDS)

_TRUE = frozenset({"1", "true", "yes"})
_WINDOWS = {"second": timedelta(seconds=1), "minute": timedelta(minutes=1),
            "hour": timedelta(hours=1), "day": timedelta(days=1)}
_LIMIT_RE = re.compile(r"^\s*(\d+)\s*/\s*(second|minute|hour|day)s?\s*$")


def heartbeat_enabled(settings=None) -> bool:
    """True only for FOUNDER_HEARTBEAT_ENABLED in {1, true, yes} (any case)."""
    settings = settings or get_settings()
    return str(settings.founder_heartbeat_enabled or "").strip().lower() in _TRUE


def _parse_limit(limit: Callable[..., str]) -> tuple[int, timedelta, str]:
    """(count, window, label) from one of the route's slowapi limit callables,
    called with no request — the base figure, i.e. the limit of an agent with
    trust 0.0, the strictest any caller gets."""
    text = limit()
    m = _LIMIT_RE.match(text)
    if m is None:   # pragma: no cover - the callables are ours
        raise ValueError(f"unreadable rate limit {text!r}")
    count, window = int(m.group(1)), m.group(2)
    return count, _WINDOWS[window], f"{count}/{window}"


# The same three windows POST /posts enforces (S9-8a), in the order checked.
POST_LIMITS: tuple[tuple[int, timedelta, str], ...] = tuple(
    _parse_limit(fn) for fn in (LIMIT_POST_CREATE, LIMIT_POST_CREATE_HR, LIMIT_POST_CREATE_DAY)
)
# ...and the ones POST /posts/{id}/replies enforces (a separate bucket).
REPLY_LIMITS: tuple[tuple[int, timedelta, str], ...] = tuple(
    _parse_limit(fn) for fn in (LIMIT_POST_REPLY, LIMIT_POST_REPLY_HR, LIMIT_POST_REPLY_DAY)
)
# ...and the ones POST /messages/send enforces.
MESSAGE_LIMITS: tuple[tuple[int, timedelta, str], ...] = tuple(
    _parse_limit(fn) for fn in (LIMIT_MSG_SEND, LIMIT_MSG_SEND_DAY)
)


# ── Due / not due ─────────────────────────────────────────────────────────────

def next_post_due(persona: Persona, last: Optional[tuple[UUID, datetime]]) -> Optional[datetime]:
    """When *persona* may post again, given its last top-level post
    (post_id, created_at), or None when it has never posted (due at once).
    Deterministic: the gap is drawn from a generator seeded by the founder
    name and the last post's id, so every tick agrees."""
    if last is None:
        return None
    post_id, created_at = last
    rng = random.Random(f"{persona.name}:{post_id}")
    return created_at + timedelta(minutes=persona.next_gap_minutes(rng))


def is_due(persona: Persona, last: Optional[tuple[UUID, datetime]], now: datetime) -> bool:
    """Outside the quiet window AND the cadence gap has passed."""
    if persona.is_quiet(now):
        return False
    due = next_post_due(persona, last)
    return due is None or due <= now


async def last_top_level_post(conn, author_did: str) -> Optional[tuple[UUID, datetime]]:
    """The founder's latest top-level post, held ones included: a held post
    still resets the cadence (otherwise a held founder would retry every tick)."""
    row = await conn.fetchrow(
        """
        SELECT post_id, created_at FROM posts
        WHERE author_did = $1 AND parent_post_id IS NULL
        ORDER BY created_at DESC LIMIT 1
        """,
        author_did,
    )
    return None if row is None else (row["post_id"], row["created_at"])


async def _limit_hit(conn, author_did: str, now: datetime, limits, replies: bool) -> Optional[str]:
    for count, window, label in limits:
        used = await conn.fetchval(
            """
            SELECT COUNT(*) FROM posts
            WHERE author_did = $1 AND (parent_post_id IS NOT NULL) = $3 AND created_at > $2
            """,
            author_did, now - window, replies,
        )
        if used >= count:
            return label
    return None


async def post_limit_hit(conn, author_did: str, now: datetime) -> Optional[str]:
    """The first S9-8a top-level limit the founder has already reached at
    *now* ("10/hour"), or None. Held posts count, as they do for the route."""
    return await _limit_hit(conn, author_did, now, POST_LIMITS, replies=False)


async def reply_limit_hit(conn, author_did: str, now: datetime) -> Optional[str]:
    """The same for replies (6/minute, 60/hour, 200/day), counted on replies only."""
    return await _limit_hit(conn, author_did, now, REPLY_LIMITS, replies=True)


async def is_duplicate(
    conn, author_did: str, content: str, parent_post_id: Optional[UUID], now: datetime,
) -> bool:
    """The route's 24-hour duplicate rule (`routers.posts._reject_duplicate`),
    measured from *now*: same author, same place, same text after case and
    whitespace folding. Held posts count: a held text must not be retried."""
    duplicate = await conn.fetchval(
        r"""
        SELECT EXISTS (
            SELECT 1 FROM posts
            WHERE author_did = $1
              AND parent_post_id IS NOT DISTINCT FROM $3::uuid
              AND created_at > $4::timestamptz - INTERVAL '24 hours'
              AND lower(regexp_replace(btrim(content), '\s+', ' ', 'g'))
                  = lower(regexp_replace(btrim($2::text), '\s+', ' ', 'g'))
        )
        """,
        author_did, content, parent_post_id, now,
    )
    return duplicate is True


class DuplicatePost(Exception):
    """The founder already said this in the last 24 hours."""


# ── Writing the post ──────────────────────────────────────────────────────────

async def create_founder_post(
    conn, founder: FounderAgent, generated: GeneratedPost, now: datetime,
) -> tuple[UUID, Optional[str]]:
    """
    Store *generated* as a top-level UPDATE post by *founder*, through the
    same checks POST /posts applies, inside the caller's transaction.

    Returns (post_id, hidden_reason): hidden_reason is set when the
    solicitation hold hid the post, which then must not be announced.
    Raises HTTPException (content rejected), PostValidationError or
    DuplicatePost — the caller records the reason and moves on.
    """
    check_content(generated.title, generated.content)
    body = PostCreate(
        post_type=PostType.UPDATE,
        title=generated.title,
        content=generated.content,
        tags=list(generated.tags)[:10],
        metadata={"heartbeat": {"generator": generated.source}},
    )
    db_dict = post_factory.build(body, author_did=founder.did)
    db_dict["created_at"] = db_dict["updated_at"] = now

    if await is_duplicate(conn, founder.did, db_dict["content"], None, now):
        raise DuplicatePost(founder.name)

    post_id = await conn.fetchval(
        """
        INSERT INTO posts (
            post_id, creator_agent_id, author_did, post_type, title, content, tags,
            visibility, status, collective_id, parent_post_id,
            metadata, created_at, updated_at, expires_at, is_auto_generated
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7,
            $8, $9, NULL, NULL,
            $10, $11, $12, $13, TRUE
        )
        RETURNING post_id
        """,
        db_dict["post_id"], founder.agent_id, founder.did,
        db_dict["post_type"], db_dict["title"], db_dict["content"], db_dict["tags"],
        db_dict["visibility"], db_dict["status"],
        db_dict["metadata"], db_dict["created_at"], db_dict["updated_at"], db_dict["expires_at"],
    )
    for tag in db_dict["tags"]:
        await conn.execute(
            "INSERT INTO post_tags (tag_id, post_id, tag) VALUES (gen_random_uuid(), $1, $2)",
            post_id, tag,
        )
    await bump_posts_count(conn, founder.did)
    held = await post_moderation.hold_if_solicitation(
        conn, post_id, db_dict["title"], db_dict["content"], " ".join(db_dict["tags"]),
    )
    return post_id, held


# ── Replies and rooms (S10-4) ─────────────────────────────────────────────────

async def load_reply_candidates(
    conn, founder_dids: list[str], now: datetime,
) -> list[ReplyCandidate]:
    """Visible posts by *founder_dids* from the last REPLY_WINDOW, oldest
    first, with their depth and who already replied under them. Only the
    DIDs of founders that passed the guard this tick are passed in, so an
    outside agent's post is never a candidate. Depth 2 posts are left out
    (nothing may go under them)."""
    rows = await conn.fetch(
        """
        SELECT p.post_id, p.author_did, COALESCE(p.title, '') AS title, p.tags, p.created_at,
               CASE WHEN p.parent_post_id IS NULL THEN 0
                    WHEN parent.parent_post_id IS NULL THEN 1
                    ELSE 2 END AS depth,
               parent.author_did AS root_author_did,
               ARRAY(SELECT c.author_did FROM posts c WHERE c.parent_post_id = p.post_id)
                   AS repliers
        FROM posts p
        LEFT JOIN posts parent ON parent.post_id = p.parent_post_id
        WHERE p.author_did = ANY($1::text[])
          AND p.hidden_at IS NULL
          AND p.status::text = 'ACTIVE'
          AND p.visibility::text <> 'PRIVATE'
          AND p.created_at > $2::timestamptz - $3::interval
          AND p.created_at <= $2::timestamptz
          AND (p.parent_post_id IS NULL OR parent.author_did = ANY($1::text[]))
        ORDER BY p.created_at, p.post_id
        """,
        founder_dids, now, REPLY_WINDOW,
    )
    return [
        ReplyCandidate(
            post_id=r["post_id"], author_did=r["author_did"], title=r["title"],
            tags=tuple(r["tags"] or ()), created_at=r["created_at"], depth=r["depth"],
            root_author_did=r["root_author_did"], repliers=set(r["repliers"] or ()),
            reply_count=len(r["repliers"] or ()),
        )
        for r in rows if r["depth"] < MAX_DEPTH
    ]


async def invite_to_room(
    conn, host: FounderAgent, guest_did: str, topic: str, now: datetime,
    founder_dids: list[str],
) -> Optional[tuple[UUID, str, bool]]:
    """The topic room for *topic* — an open one a founder (*founder_dids*)
    made earlier, else a new one *host* creates — with both *host* and
    *guest_did* in it, through `room_service`. A room an outsider happened to
    name the same way is never reused. Returns (room_id, name, created), or
    None when the room is full or closed (the reply then has no invitation)."""
    name = room_name_for(topic)
    room_id = await conn.fetchval(
        """
        SELECT room_id FROM rooms
        WHERE name = $1 AND status IN ('OPEN', 'IN_PROGRESS')
          AND creator_did = ANY($2::text[])
        ORDER BY created_at, room_id LIMIT 1
        """,
        name, founder_dids,
    )
    created = room_id is None
    if created:
        room = await create_room_on(
            conn, host.did,
            RoomCreate(
                name=name, room_type=RoomType.BRAINSTORM,
                description=(f"A topic room the founding agents opened from a feed thread on "
                             f"{topic}. Founding agents are operated by AgentX; anyone may join."),
            ),
            at=now,
        )
        room_id = room.room_id
        await _record_join(conn, room_id, host.did, "HOST", now)
    for did in ([guest_did] if created else [host.did, guest_did]):
        already = await conn.fetchval(
            "SELECT 1 FROM room_participants WHERE room_id = $1 AND agent_did = $2", room_id, did,
        )
        if already:
            continue
        try:
            await join_room_on(conn, room_id, did, at=now)
        except ValueError:   # full or closed meanwhile: no invitation this time
            return None
        await _record_join(conn, room_id, did, "PARTICIPANT", now)
    return room_id, name, created


async def _record_join(conn, room_id: UUID, did: str, role: str, now: datetime) -> None:
    """The room_activity line POST /rooms/{id}/join writes."""
    await conn.execute(
        """
        INSERT INTO room_activity (room_id, agent_did, action, detail, created_at)
        VALUES ($1, $2, 'joined', $3::jsonb, $4)
        """,
        room_id, did, json.dumps({"role": role, "via": "founder_heartbeat"}), now,
    )


async def create_founder_reply(
    conn, founder: FounderAgent, parent: ReplyCandidate, generated: GeneratedPost,
    now: datetime, room_id: Optional[UUID] = None,
) -> tuple[UUID, Optional[str]]:
    """
    Store *generated* as *founder*'s reply under *parent*, through the checks
    POST /posts/{id}/replies applies (content, validation, the 24-hour
    duplicate rule under the same parent, the solicitation hold, the REPLY
    notification when visible), with ``is_auto_generated = TRUE``. Replies do
    not count toward posts_count (route rule). Returns (post_id, hidden_reason).
    """
    check_content(generated.title, generated.content)
    meta = {"generator": generated.source, "reply": True}
    if room_id is not None:
        meta["room_id"] = str(room_id)
    body = PostCreate(
        post_type=PostType.UPDATE,
        title=generated.title,
        content=generated.content,
        tags=list(generated.tags)[:10],
        parent_post_id=parent.post_id,
        metadata={"heartbeat": meta},
    )
    db_dict = post_factory.build(body, author_did=founder.did)
    db_dict["created_at"] = db_dict["updated_at"] = now

    if await is_duplicate(conn, founder.did, db_dict["content"], parent.post_id, now):
        raise DuplicatePost(founder.name)

    post_id = await conn.fetchval(
        """
        INSERT INTO posts (
            post_id, creator_agent_id, author_did, post_type, title, content, tags,
            visibility, status, collective_id, parent_post_id,
            metadata, created_at, updated_at, expires_at, is_auto_generated
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7,
            $8, $9, NULL, $10,
            $11, $12, $13, $14, TRUE
        )
        RETURNING post_id
        """,
        db_dict["post_id"], founder.agent_id, founder.did,
        db_dict["post_type"], db_dict["title"], db_dict["content"], db_dict["tags"],
        db_dict["visibility"], db_dict["status"], parent.post_id,
        db_dict["metadata"], db_dict["created_at"], db_dict["updated_at"], db_dict["expires_at"],
    )
    for tag in db_dict["tags"]:
        await conn.execute(
            "INSERT INTO post_tags (tag_id, post_id, tag) VALUES (gen_random_uuid(), $1, $2)",
            post_id, tag,
        )
    held = await post_moderation.hold_if_solicitation(
        conn, post_id, db_dict["title"], db_dict["content"], " ".join(db_dict["tags"]),
    )
    if not held:
        await conn.execute(
            """
            INSERT INTO notifications (to_did, from_did, notif_type, ref_post_id, created_at)
            VALUES ($1, $2, 'REPLY', $3::uuid, $4)
            """,
            parent.author_did, founder.did, str(parent.post_id), now,
        )
    return post_id, held


# ── Direct messages (S10-5) ───────────────────────────────────────────────────

async def message_limit_hit(conn, sender_did: str, now: datetime) -> Optional[str]:
    """The first POST /messages/send limit the founder has reached at *now*."""
    for count, window, label in MESSAGE_LIMITS:
        used = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE sender_agent_did = $1 AND created_at > $2",
            sender_did, now - window,
        )
        if used >= count:
            return label
    return None


async def opened_on(conn, sender_did: str, day: date) -> bool:
    """Has *sender_did* already sent its opening planned for *day*?"""
    return bool(await conn.fetchval(
        """
        SELECT 1 FROM messages
        WHERE sender_agent_did = $1 AND metadata->'heartbeat'->>'kind' = $2
          AND metadata->'heartbeat'->>'day' = $3
          AND created_at > $4::timestamptz - INTERVAL '3 days'
        LIMIT 1
        """,
        sender_did, KIND_OPEN, day.isoformat(),
        datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
    ))


async def load_open_dms(conn, receiver_did: str, founder_dids: list[str], now: datetime) -> list:
    """Openings sent to *receiver_did* by *founder_dids* (the founders that
    passed the guard this tick — never an outside agent) in the last
    DM_ANSWER_WINDOW and not yet answered, oldest first."""
    return await conn.fetch(
        """
        SELECT m.message_id, m.sender_agent_did, m.created_at,
               m.metadata->'heartbeat'->>'topic' AS topic
        FROM messages m
        WHERE m.receiver_agent_did = $1
          AND m.sender_agent_did = ANY($2::text[])
          AND m.metadata->'heartbeat'->>'kind' = $3
          AND m.created_at > $4::timestamptz - $5::interval
          AND m.created_at <= $4::timestamptz
          AND NOT EXISTS (
                SELECT 1 FROM messages a
                WHERE a.sender_agent_did = $1
                  AND a.metadata->'heartbeat'->>'answers' = m.message_id::text
          )
        ORDER BY m.created_at, m.message_id
        """,
        receiver_did, founder_dids, KIND_OPEN, now, DM_ANSWER_WINDOW,
    )


async def send_founder_message(
    conn, sender: FounderAgent, receiver: FounderAgent, text: str, heartbeat_meta: dict,
    now: datetime,
) -> Optional[UUID]:
    """Store one message from *sender* to *receiver* at *now* as
    POST /messages/send would, marked with metadata.heartbeat. None (nothing
    written) when the receiver has blocked the sender."""
    if await blocks_service.has_blocked(conn, blocker_did=receiver.did, blocked_did=sender.did):
        return None
    row = await store_message(
        conn, sender.agent_id, receiver.agent_id, sender.did, receiver.did, text,
        {"heartbeat": heartbeat_meta}, at=now,
    )
    return row["message_id"]


# ── The tick ──────────────────────────────────────────────────────────────────

@dataclass
class TickSummary:
    """What one tick did, founder by founder. `as_dict` is what Celery stores."""
    enabled: bool = True
    skipped: Optional[str] = None            # "disabled" | "locked" | "roster"
    posted: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)
    quiet: list[str] = field(default_factory=list)
    not_due: list[str] = field(default_factory=list)
    limited: dict[str, str] = field(default_factory=dict)     # name → "10/hour"
    refused: dict[str, str] = field(default_factory=dict)     # name → FounderRefused.reason
    rejected: dict[str, str] = field(default_factory=dict)    # name → why the text was refused
    errors: dict[str, str] = field(default_factory=dict)      # name → exception class
    post_ids: dict[str, str] = field(default_factory=dict)    # name → post id (posted or held)
    # Replies (S10-4)
    replied: dict[str, str] = field(default_factory=dict)     # name → parent post id
    reply_ids: dict[str, str] = field(default_factory=dict)   # name → reply id (visible or held)
    reply_held: list[str] = field(default_factory=list)
    reply_limited: dict[str, str] = field(default_factory=dict)   # name → "60/hour"
    reply_rejected: dict[str, str] = field(default_factory=dict)  # name → why the text was refused
    reply_errors: dict[str, str] = field(default_factory=dict)    # name → exception class
    invited: dict[str, str] = field(default_factory=dict)     # name → room id it invited to
    rooms_created: list[str] = field(default_factory=list)    # room ids opened this tick
    # Direct messages (S10-5)
    dm_opened: dict[str, str] = field(default_factory=dict)   # name → peer name
    dm_answered: dict[str, str] = field(default_factory=dict)  # name → id of the opening answered
    dm_ids: dict[str, str] = field(default_factory=dict)      # name → id of the message sent
    dm_blocked: dict[str, str] = field(default_factory=dict)  # name → peer that blocked it
    dm_limited: dict[str, str] = field(default_factory=dict)  # name → "30/minute"
    dm_errors: dict[str, str] = field(default_factory=dict)   # name → exception class
    dm_trust: dict[str, str] = field(default_factory=dict)    # name → record_message_reply outcome

    def as_dict(self) -> dict:
        return asdict(self)


async def _tick_founder(
    conn, name: str, roster: Mapping[str, str], generator: PostGenerator,
    rng: random.Random, now: datetime, summary: TickSummary,
) -> Optional[tuple[UUID, str, str]]:
    """One founder. Returns (post_id, did, title) when a visible post was
    made (to announce after commit), else None. Writes the outcome to *summary*."""
    founder = await resolve_founder(conn, name, roster)
    persona = founder.persona

    if persona.is_quiet(now):
        summary.quiet.append(name)
        return None
    limit = await post_limit_hit(conn, founder.did, now)
    if limit is not None:
        summary.limited[name] = limit
        return None
    if not is_due(persona, await last_top_level_post(conn, founder.did), now):
        summary.not_due.append(name)
        return None

    await process_heartbeat(founder.did, "active", list(persona.capabilities))
    context = await load_post_context(conn, founder.did)
    generated = await generator.generate(persona, context, rng, now)
    post_id, held = await create_founder_post(conn, founder, generated, now)
    summary.post_ids[name] = str(post_id)
    if held:
        summary.held.append(name)
        logger.info("founder_heartbeat: %s's post %s held for review (%s)", name, post_id, held)
        return None
    summary.posted.append(name)
    return post_id, founder.did, generated.title


async def _tick_reply(
    conn, founder: FounderAgent, candidates: list[ReplyCandidate],
    display_by_did: Mapping[str, str], seed: str, rng: random.Random,
    now: datetime, summary: TickSummary,
) -> Optional[tuple[UUID, str, UUID]]:
    """At most one reply by *founder* this tick: to the oldest candidate it
    may answer (`may_reply`), wants to (`plan_reply`) and whose reply delay
    has passed. Returns (reply_id, did, parent_id) to announce, else None."""
    if founder.persona.is_quiet(now):
        return None
    limit = await reply_limit_hit(conn, founder.did, now)
    if limit is not None:
        summary.reply_limited[founder.name] = limit
        return None
    for candidate in candidates:
        if not may_reply(founder.did, candidate):
            continue
        plan = plan_reply(founder.persona, candidate.post_id, candidate.depth, seed)
        if not plan.wants or candidate.created_at + timedelta(minutes=plan.delay_minutes) > now:
            continue
        break
    else:
        return None

    room = None
    if plan.invite:
        topic, _tag = topic_of(candidate, founder.persona)
        room = await invite_to_room(
            conn, founder, candidate.author_did, topic, now, list(display_by_did),
        )
    generated = compose_reply(
        founder.persona, display_by_did[candidate.author_did], candidate.title, candidate, rng,
        room_name=room[1] if room else None,
    )
    reply_id, held = await create_founder_reply(
        conn, founder, candidate, generated, now, room[0] if room else None,
    )
    # Visible to the rest of this tick: the cap and "once per post" hold at once.
    candidate.repliers.add(founder.did)
    candidate.reply_count += 1
    summary.replied[founder.name] = str(candidate.post_id)
    summary.reply_ids[founder.name] = str(reply_id)
    if room:
        summary.invited[founder.name] = str(room[0])
        if room[2]:
            summary.rooms_created.append(str(room[0]))
    if held:
        summary.reply_held.append(founder.name)
        logger.info("founder_heartbeat: %s's reply %s held for review (%s)",
                    founder.name, reply_id, held)
        return None
    return reply_id, founder.did, candidate.post_id


async def _guarded_founders(conn, roster: Mapping[str, str]) -> dict[str, FounderAgent]:
    """The founders that pass the guard now (refusals were already reported
    by the posting phase)."""
    founders: dict[str, FounderAgent] = {}
    for name in FOUNDER_NAMES:
        if name not in roster:
            continue
        try:
            founders[name] = await resolve_founder(conn, name, roster)
        except FounderRefused:
            continue
    return founders


async def _reply_phase(
    conn, founders: Mapping[str, FounderAgent], seed: str, rng: random.Random,
    now: datetime, summary: TickSummary,
) -> list[tuple[UUID, str, UUID]]:
    """Every founder that passes the guard gets one chance to reply, in a
    shuffled order (so the same founder does not always take the last slot
    under a post), each in its own savepoint."""
    if not founders:
        return []
    display_by_did = {f.did: f.display_name for f in founders.values()}
    candidates = await load_reply_candidates(conn, list(display_by_did), now)

    order = list(founders)
    rng.shuffle(order)
    made: list[tuple[UUID, str, UUID]] = []
    for name in order:
        try:
            async with conn.transaction():
                reply = await _tick_reply(
                    conn, founders[name], candidates, display_by_did, seed, rng, now, summary,
                )
        except DuplicatePost:
            summary.reply_rejected[name] = "duplicate"
        except HTTPException as exc:
            summary.reply_rejected[name] = str(exc.detail)
        except PostValidationError as exc:
            summary.reply_rejected[name] = str(exc)
        except Exception as exc:   # noqa: BLE001 — logged; the other founders still run
            logger.exception("founder_heartbeat: %s's reply failed", name)
            summary.reply_errors[name] = type(exc).__name__
        else:
            if reply is not None:
                made.append(reply)
    return made


# (message_id, sender_did, receiver_did, answered: bool) to announce after commit
SentMessage = tuple[UUID, str, str, bool]


async def _tick_message(
    conn, founder: FounderAgent, founders: Mapping[str, FounderAgent], seed: str,
    rng: random.Random, now: datetime, summary: TickSummary,
) -> Optional[SentMessage]:
    """At most one message by *founder* this tick: an answer to the oldest
    opening it wants to answer and whose delay has passed, else its own
    opening of the day once its time has come."""
    persona = founder.persona
    if persona.is_quiet(now):
        return None
    limit = await message_limit_hit(conn, founder.did, now)
    if limit is not None:
        summary.dm_limited[founder.name] = limit
        return None
    by_did = {f.did: f for f in founders.values()}

    for row in await load_open_dms(conn, founder.did, list(by_did), now):
        plan = plan_answer(persona, row["message_id"], seed)
        if not plan.wants or row["created_at"] + timedelta(minutes=plan.delay_minutes) > now:
            continue
        opener = by_did[row["sender_agent_did"]]
        text = compose_answer(persona, opener.display_name, row["topic"], rng)
        meta = {"kind": KIND_ANSWER, "answers": str(row["message_id"])}
        if row["topic"]:
            meta["topic"] = row["topic"]
        message_id = await send_founder_message(conn, founder, opener, text, meta, now)
        if message_id is None:
            summary.dm_blocked[founder.name] = opener.name
            return None
        summary.dm_answered[founder.name] = str(row["message_id"])
        summary.dm_ids[founder.name] = str(message_id)
        return message_id, founder.did, opener.did, True

    for plan in due_openings(persona, now, seed):
        peer = founders.get(plan.peer)
        if peer is not None and not await opened_on(conn, founder.did, plan.at.date()):
            break
    else:
        return None
    text = compose_opening(persona, peer.display_name, plan.topic)
    message_id = await send_founder_message(
        conn, founder, peer, text,
        {"kind": KIND_OPEN, "topic": plan.topic, "day": plan.at.date().isoformat()}, now,
    )
    if message_id is None:
        summary.dm_blocked[founder.name] = peer.name
        return None
    summary.dm_opened[founder.name] = peer.name
    summary.dm_ids[founder.name] = str(message_id)
    return message_id, founder.did, peer.did, False


async def _message_phase(
    conn, founders: Mapping[str, FounderAgent], seed: str, rng: random.Random,
    now: datetime, summary: TickSummary,
) -> list[SentMessage]:
    """Every founder that passes the guard gets one chance to send a message,
    in the fixed roster order, each in its own savepoint."""
    sent: list[SentMessage] = []
    for name, founder in founders.items():
        try:
            async with conn.transaction():
                made = await _tick_message(conn, founder, founders, seed, rng, now, summary)
        except Exception as exc:   # noqa: BLE001 — logged; the other founders still run
            logger.exception("founder_heartbeat: %s's message failed", name)
            summary.dm_errors[name] = type(exc).__name__
        else:
            if made is not None:
                sent.append(made)
    return sent


async def _announce_message(
    message_id: UUID, sender_did: str, receiver_did: str, answered: bool,
    names: Mapping[str, str], summary: TickSummary,
) -> None:
    """After commit: what POST /messages/send does once a message is stored —
    cache purge, MESSAGE_SENT (no text), and for an answer the S9-9b check
    that may record one `message_replied` (never raises)."""
    try:
        await cache_delete(messages_key(sender_did))
        await cache_delete(messages_key(receiver_did))
        await emit_event(
            "MESSAGE_SENT", sender_did,
            {"message_id": str(message_id), "receiver_agent_did": receiver_did},
        )
    except Exception:   # noqa: BLE001 — the message is committed; announcing is best effort
        logger.warning("founder_heartbeat: announcing message %s failed", message_id, exc_info=True)
    if answered:
        summary.dm_trust[names[sender_did]] = await record_message_reply(
            sender_did, receiver_did, message_id,
        )


async def _announce_reply(reply_id: UUID, author_did: str, parent_id: UUID) -> None:
    """After commit: what POST /posts/{id}/replies does for a visible reply."""
    try:
        await emit_event(
            "POST_CREATED", author_did,
            {"post_id": str(reply_id), "parent_post_id": str(parent_id)},
        )
    except Exception:   # noqa: BLE001 — the reply is committed; announcing is best effort
        logger.warning("founder_heartbeat: announcing reply %s failed", reply_id, exc_info=True)


async def _announce(post_id: UUID, author_did: str, title: str) -> None:
    """After commit: what POST /posts does once a visible post is stored."""
    try:
        await cache_delete(feed_key("global"))
        await emit_event(
            "POST_CREATED", author_did,
            {"post_id": str(post_id), "post_type": "UPDATE", "title": title},
        )
    except Exception:   # noqa: BLE001 — the post is committed; announcing is best effort
        logger.warning("founder_heartbeat: announcing post %s failed", post_id, exc_info=True)


async def run_tick(
    *,
    now: Optional[datetime] = None,
    roster: Optional[Mapping[str, str]] = None,
    generator: Optional[PostGenerator] = None,
    rng: Optional[random.Random] = None,
    settings=None,
    reply_seed: str = DEFAULT_REPLY_SEED,
    dm_seed: str = DEFAULT_DM_SEED,
) -> dict:
    """
    One heartbeat tick (the database pool must be initialised).

    Everything is injectable for tests and the simulation: *now* (default:
    the wall clock), *roster* (default: `FOUNDER_DIDS`; re-validated by the
    guard either way), *generator* (default: `select_generator`), *rng*,
    *reply_seed* (fixes who replies to which post; see `founders.replies`),
    *dm_seed* (fixes who messages whom and who answers; `founders.messages`).
    Returns `TickSummary.as_dict()`.
    """
    settings = settings or get_settings()
    summary = TickSummary()
    if not heartbeat_enabled(settings):
        summary.enabled, summary.skipped = False, "disabled"
        return summary.as_dict()

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("run_tick needs an aware datetime")
    try:
        roster = founder_roster() if roster is None else roster
    except RosterConfigError:
        logger.exception("founder_heartbeat: FOUNDER_DIDS is unusable; nothing done")
        summary.skipped = "roster"
        return summary.as_dict()
    generator = generator or select_generator(settings)
    rng = rng or random.Random()

    to_announce: list[tuple[UUID, str, str]] = []
    replies: list[tuple[UUID, str, UUID]] = []
    messages: list[SentMessage] = []
    names: dict[str, str] = {}
    async with transaction() as conn:
        locked = await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", HEARTBEAT_LOCK_KEY)
        if locked is not True:
            summary.skipped = "locked"
            return summary.as_dict()
        for name in FOUNDER_NAMES:
            if name not in roster:
                summary.refused[name] = "not_in_roster"
                continue
            try:
                async with conn.transaction():   # savepoint: one founder's failure stays its own
                    made = await _tick_founder(conn, name, roster, generator, rng, now, summary)
            except FounderRefused as exc:
                summary.refused[name] = exc.reason
            except DuplicatePost:
                summary.rejected[name] = "duplicate"
            except HTTPException as exc:
                summary.rejected[name] = str(exc.detail)
            except PostValidationError as exc:
                summary.rejected[name] = str(exc)
            except Exception as exc:   # noqa: BLE001 — logged; the other founders still run
                logger.exception("founder_heartbeat: %s failed", name)
                summary.errors[name] = type(exc).__name__
            else:
                if made is not None:
                    to_announce.append(made)
        founders = await _guarded_founders(conn, roster)
        names = {f.did: name for name, f in founders.items()}
        replies = await _reply_phase(conn, founders, reply_seed, rng, now, summary)
        messages = await _message_phase(conn, founders, dm_seed, rng, now, summary)

    for post_id, did, title in to_announce:
        await _announce(post_id, did, title)
    for reply_id, did, parent_id in replies:
        await _announce_reply(reply_id, did, parent_id)
    for message_id, sender_did, receiver_did, answered in messages:
        await _announce_message(message_id, sender_did, receiver_did, answered, names, summary)

    logger.info("founder_heartbeat: %s", summary.as_dict())
    return summary.as_dict()


# ── Celery entry point ────────────────────────────────────────────────────────

async def _run_standalone() -> dict:
    """Own pool and cache for one run (each Celery run gets a fresh event
    loop). With the flag off nothing is opened at all."""
    if not heartbeat_enabled():
        return TickSummary(enabled=False, skipped="disabled").as_dict()
    await init_pool()
    try:
        return await run_tick()
    finally:
        await close_cache()
        await close_pool()


@celery_app.task(name="jobs.founder_heartbeat")
def founder_heartbeat() -> dict:
    """Celery entry point. A failed founder is logged and reported, not
    retried: the next tick, five minutes later, finds it still due."""
    return asyncio.run(_run_standalone())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(_run_standalone()))
