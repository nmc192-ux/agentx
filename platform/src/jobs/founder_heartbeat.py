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

Before all of that, the task phase (S10-6): every founder that passes the
guard, outside its quiet window, takes at most one paid-work step per tick —
first finishing a handoff it was given (`founders.tasks`: on a later tick,
after its delay, through `task_service.submit_result`, which pays the escrow
and counts `task_completed` by the S9-9b rules), else posting its own
handoff of the day for a founder whose capabilities match (through
`task_service.create_task`, funded from its own wallet; the peer bids in the
same tick and the marketplace assigns it). Only founders take part: a
handoff goes only to a founder the guard accepted this tick, and only
handoffs posted by such founders are ever finished. Spending is capped per
founder per 24 hours (`FOUNDER_TASK_DAILY_SPEND`), the route's task limits
(5 a minute, 30 an hour, 100 a day) are honoured, and a wallet that cannot
cover the reward means no task. The money services commit on their own
connections, through the same code every route uses; the task phase runs
FIRST in the tick, before this connection has written (and so locked) any
row, so those services can never wait on the tick's own transaction.

Straight after it, the civic phase (S10-7): the week's bounty and the
week's governance proposal (`founders.civics`). Each founder that passes the
guard, outside its quiet window, takes at most one bounty step — judge its
own bounty once its time has come (score every founder submission, pay the
pool to the best through `bounty_service.distribute_rewards`, or cancel and
take the pool back when nobody submitted; never when an outside agent has
submitted: that bounty is left for a person and reported), else submit to
another founder's open bounty on its planned moment, else post its own
bounty of the week (`create_bounty`, pool from its own wallet, clamped to
`FOUNDER_BOUNTY_POOL_MAX`) — and at most one governance step — vote on a
founder proposal on its planned moment (`vote_on_proposal`; first staking
`FOUNDER_VOTE_STAKE` tokens once, through `token_service.stake_tokens`, so
the vote carries weight), else post its own proposal of the week
(`create_proposal`). Only founders take part: never an outside agent's
bounty or proposal. Proposals close through the maintenance job
(`finalize_due_proposals`), as they do for everyone.

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
from ..founders.civics import (
    BOUNTY_DEADLINE,
    BOUNTY_JUDGE_AFTER,
    DEFAULT_CIVIC_SEED,
    KIND_PROPOSAL,
    PROPOSAL_VOTING_DAYS,
    compose_bounty,
    compose_proposal,
    compose_submission,
    due_bounty_plans,
    due_proposal_plans,
    plan_bounty,
    plan_score,
    plan_submission,
    plan_vote,
    proposal_payload,
    submission_payload,
    week_of,
)
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
from ..founders.tasks import (
    DEFAULT_TASK_SEED,
    KIND_HANDOFF,
    TASK_BID_CONFIDENCE,
    due_task_plans,
    handoff_payload,
    plan_result_delay,
    result_payload,
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
    LIMIT_TASK_CREATE,
    LIMIT_TASK_CREATE_DAY,
    LIMIT_TASK_CREATE_HR,
)
from ..models.governance import ProposalCreate, VoteRequest
from ..models.markets import BountyCreate, SubmissionCreate
from ..models.post import PostCreate, PostType
from ..models.room import RoomCreate, RoomType
from ..services import blocks_service, post_moderation
from ..services.governance_service import (
    GovernanceConflictError,
    create_proposal,
    vote_on_proposal,
)
from ..services.markets.bounty_service import (
    cancel_bounty,
    create_bounty,
    distribute_rewards,
    evaluate_submission,
    submit_solution,
)
from ..services.message_service import messages_key, store_message
from ..services.content_moderation import check_content
from ..services.events import emit_event
from ..services.heartbeat_service import process_heartbeat
from ..services.post_factory import PostValidationError, post_factory
from ..services.post_service import bump_posts_count
from ..services.reputation import record_message_reply
from ..services.room_service import create_room_on, join_room_on
from ..services.task_service import (
    InsufficientFundsError,
    TaskConflictError,
    create_task,
    submit_bid,
    submit_result,
)
from ..services.token_service import stake_tokens
from .celery_app import celery_app

logger = logging.getLogger(__name__)

__all__ = [
    "HEARTBEAT_LOCK_KEY", "HEARTBEAT_INTERVAL_SECONDS", "POST_LIMITS",
    "TickSummary", "heartbeat_enabled", "next_post_due", "is_due",
    "post_limit_hit", "is_duplicate", "create_founder_post", "run_tick",
    "REPLY_LIMITS", "reply_limit_hit", "load_reply_candidates", "create_founder_reply",
    "invite_to_room", "MESSAGE_LIMITS", "message_limit_hit", "load_open_dms",
    "send_founder_message", "TASK_LIMITS", "task_limit_hit", "handoff_spent",
    "wallet_balance", "handoff_posted_on", "load_handoffs_to_finish", "founder_heartbeat",
    "load_founder_bounties", "bounty_posted_at", "load_submissions", "load_founder_proposals",
    "proposal_posted_at", "has_voted", "has_stake",
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
# ...and the ones POST /tasks (marketplace create) enforces.
TASK_LIMITS: tuple[tuple[int, timedelta, str], ...] = tuple(
    _parse_limit(fn) for fn in (LIMIT_TASK_CREATE, LIMIT_TASK_CREATE_HR, LIMIT_TASK_CREATE_DAY)
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



# ── Paid task handoffs (S10-6) ────────────────────────────────────────────────

# When a task happened, in the tick's own time: a handoff carries the tick
# moment it was posted at (payload.heartbeat.at); anything else is dated by
# the database. The 7-day simulation (S10-10) relies on this.
_TASK_AT = ("COALESCE(CASE WHEN payload->'heartbeat'->>'kind' = $%d "
            "THEN (payload->'heartbeat'->>'at')::timestamptz END, created_at)")


async def task_limit_hit(conn, creator_did: str, now: datetime) -> Optional[str]:
    """The first POST /tasks limit the founder has reached at *now* (every
    task it requested counts, handoff or not)."""
    for count, window, label in TASK_LIMITS:
        used = await conn.fetchval(
            "SELECT COUNT(*) FROM tasks WHERE requester_agent_did = $1 AND "
            + (_TASK_AT % 3) + " > $2",
            creator_did, now - window, KIND_HANDOFF,
        )
        if used >= count:
            return label
    return None


async def handoff_spent(conn, creator_did: str, now: datetime) -> int:
    """Tokens *creator_did* put into handoff rewards in the 24 hours before
    *now* (cancelled tasks excluded: their reward came back)."""
    return int(await conn.fetchval(
        "SELECT COALESCE(SUM(reward), 0) FROM tasks WHERE requester_agent_did = $1 "
        "AND payload->'heartbeat'->>'kind' = $3 AND status <> 'cancelled' "
        "AND " + (_TASK_AT % 3) + " > $2",
        creator_did, now - timedelta(hours=24), KIND_HANDOFF,
    ) or 0)


async def wallet_balance(conn, agent_id) -> Optional[int]:
    """The agent's balance, or None when it has no wallet (H6 funds the founders)."""
    return await conn.fetchval("SELECT balance FROM wallets WHERE agent_id = $1", agent_id)


async def handoff_posted_on(conn, creator_did: str, day: date) -> bool:
    """Has *creator_did* already posted the handoff planned for *day*? The
    plan's day in the payload is the identity — no clock is consulted, so
    a simulated run days away from the database clock sees it too."""
    return bool(await conn.fetchval(
        """
        SELECT 1 FROM tasks
        WHERE requester_agent_did = $1 AND payload->'heartbeat'->>'kind' = $2
          AND payload->'heartbeat'->>'day' = $3
        LIMIT 1
        """,
        creator_did, KIND_HANDOFF, day.isoformat(),
    ))


async def load_handoffs_to_finish(conn, executor_did: str, founder_dids: list[str]) -> list:
    """Handoffs assigned to *executor_did* that were posted by *founder_dids*
    (the founders that passed the guard this tick — never an outside agent,
    whatever its payload claims) and are still waiting for a result, oldest
    first. The delay check is the caller's (it needs the persona)."""
    return await conn.fetch(
        """
        SELECT task_id, requester_agent_did, task_type, reward,
               (payload->'heartbeat'->>'at')::timestamptz AS posted_at
        FROM tasks
        WHERE status = 'assigned' AND executor_agent_did = $1
          AND requester_agent_did = ANY($2::text[])
          AND payload->'heartbeat'->>'kind' = $3
        ORDER BY created_at, task_id
        """,
        executor_did, founder_dids, KIND_HANDOFF,
    )


async def _paid_to(conn, task_id: UUID, agent_id) -> int:
    """What the escrow of *task_id* released to *agent_id* (ledger)."""
    return int(await conn.fetchval(
        """
        SELECT COALESCE(SUM(tx.amount), 0) FROM transactions tx
        JOIN wallets w ON w.wallet_id = tx.to_wallet
        WHERE tx.related_id = $1 AND tx.type = 'escrow_release' AND w.agent_id = $2
        """,
        task_id, agent_id,
    ) or 0)


async def _tick_task(
    conn, founder: FounderAgent, founders: Mapping[str, FounderAgent], seed: str,
    rng: random.Random, now: datetime, summary: "TickSummary", daily_spend: int,
) -> None:
    """At most one paid-work step by *founder* this tick: finish the oldest
    handoff it holds whose delay has passed, else post its own handoff of the
    day once its time has come. Money moves only inside `task_service`."""
    persona = founder.persona
    name = founder.name
    if persona.is_quiet(now):
        return
    by_did = {f.did: f for f in founders.values()}

    for row in await load_handoffs_to_finish(conn, founder.did, list(by_did)):
        posted_at = row["posted_at"]
        if posted_at is None or posted_at > now:
            continue
        if posted_at + timedelta(minutes=plan_result_delay(persona, row["task_id"], seed)) > now:
            continue
        try:
            await submit_result(
                row["task_id"], founder.did, result_payload(persona, row["task_type"], rng, now),
            )
        except (PermissionError, TaskConflictError, ValueError) as exc:
            # Not ours any more, or finished meanwhile: leave it alone.
            summary.task_skipped[name] = f"result_refused:{type(exc).__name__}"
            return
        summary.task_submitted[name] = str(row["task_id"])
        summary.task_paid[name] = await _paid_to(conn, row["task_id"], founder.agent_id)
        recorded = await conn.fetchval(
            "SELECT 1 FROM trust_events WHERE dedupe_key = $1", f"task_completed:{row['task_id']}",
        )
        summary.task_trust[name] = "recorded" if recorded else "not_recorded"
        return

    if daily_spend <= 0:
        return
    for plan in due_task_plans(persona, now, seed):
        if plan.peer in founders and not await handoff_posted_on(conn, founder.did, plan.at.date()):
            break
        if plan.peer not in founders:
            summary.task_skipped[name] = "peer_unavailable"
    else:
        return
    peer = founders[plan.peer]
    limit = await task_limit_hit(conn, founder.did, now)
    if limit is not None:
        summary.task_skipped[name] = limit
        return
    if await handoff_spent(conn, founder.did, now) + plan.reward > daily_spend:
        summary.task_skipped[name] = "spend_cap"
        return
    balance = await wallet_balance(conn, founder.agent_id)
    if balance is None:
        summary.task_skipped[name] = "no_wallet"
        return
    if balance < plan.reward:
        summary.task_skipped[name] = "wallet_short"
        return

    payload = handoff_payload(persona, peer.display_name, peer.did, plan, now)
    try:
        task = await create_task(founder.did, plan.task_type, payload, plan.reward)
    except InsufficientFundsError:
        summary.task_skipped[name] = "wallet_short"
        return
    summary.task_posted[name] = str(task.task_id)
    summary.task_skipped.pop(name, None)

    # The peer takes it at once, so the funded task is open to the
    # marketplace for as short a moment as the service allows (D2 unchanged).
    try:
        await submit_bid(task.task_id, peer.did, TASK_BID_CONFIDENCE, plan.reward)
    except (PermissionError, ValueError) as exc:
        summary.task_not_taken[name] = f"bid_refused:{type(exc).__name__}"
        return
    executor = await conn.fetchval(
        "SELECT executor_agent_did FROM tasks WHERE task_id = $1 AND status = 'assigned'",
        task.task_id,
    )
    if executor == peer.did:
        summary.task_taken[peer.name] = str(task.task_id)
    else:
        summary.task_not_taken[name] = "taken_by_other" if executor else "not_assigned"


async def _task_phase(
    conn, founders: Mapping[str, FounderAgent], seed: str, rng: random.Random,
    now: datetime, summary: "TickSummary", daily_spend: int,
) -> None:
    """Every founder that passes the guard gets one paid-work step, in the
    fixed roster order. Each runs in its own savepoint on the tick's
    connection (reads only; the money services commit on their own)."""
    for name, founder in founders.items():
        try:
            async with conn.transaction():
                await _tick_task(conn, founder, founders, seed, rng, now, summary, daily_spend)
        except Exception as exc:   # noqa: BLE001 — logged; the other founders still run
            logger.exception("founder_heartbeat: %s's task step failed", name)
            summary.task_errors[name] = type(exc).__name__


# ── Civic phase (S10-7): the week's bounty and the week's proposal ───────────

async def load_founder_bounties(conn, founder_dids: list[str]) -> list:
    """Bounties still holding their pool (open or evaluating) that were posted
    by *founder_dids* (the founders that passed the guard this tick — never
    an outside agent's) and carry a deadline, with the planned moment read
    back from it, oldest first."""
    return await conn.fetch(
        """
        SELECT bounty_id, creator_did, capability_required, reward_pool, status,
               deadline - $2::interval AS planned_at
        FROM capability_bounties
        WHERE status IN ('open', 'evaluating') AND deadline IS NOT NULL
          AND creator_did = ANY($1::text[])
        ORDER BY deadline, bounty_id
        """,
        founder_dids, BOUNTY_DEADLINE,
    )


async def bounty_posted_at(conn, creator_did: str, planned_at: datetime) -> bool:
    """Has *creator_did* already posted the bounty planned for *planned_at*?
    The deadline (planned moment + BOUNTY_DEADLINE) is the identity — no
    clock is consulted, so a simulated run days away from the database
    clock sees it too."""
    return bool(await conn.fetchval(
        "SELECT 1 FROM capability_bounties WHERE creator_did = $1 AND deadline = $2 LIMIT 1",
        creator_did, planned_at + BOUNTY_DEADLINE,
    ))


async def load_submissions(conn, bounty_id: UUID) -> list:
    return await conn.fetch(
        "SELECT submission_id, submitter_did, status FROM bounty_submissions "
        "WHERE bounty_id = $1 ORDER BY submitted_at, submission_id",
        bounty_id,
    )


async def _bounty_paid_to(conn, bounty_id: UUID, agent_id) -> int:
    """What the pool of *bounty_id* paid to *agent_id* (ledger)."""
    return int(await conn.fetchval(
        """
        SELECT COALESCE(SUM(tx.amount), 0) FROM transactions tx
        JOIN wallets w ON w.wallet_id = tx.to_wallet
        WHERE tx.related_id = $1 AND tx.type = 'bounty_reward' AND w.agent_id = $2
        """,
        bounty_id, agent_id,
    ) or 0)


async def _tick_bounty(
    conn, founder: FounderAgent, founders: Mapping[str, FounderAgent], roster_dids: set[str],
    seed: str, now: datetime, summary: "TickSummary", pool_max: int,
) -> None:
    """At most one bounty step by *founder* this tick: judge its own bounty
    once its time has come, else submit to another founder's open bounty on
    its planned moment, else post its own bounty of the week. Money moves
    only inside `bounty_service`."""
    persona = founder.persona
    name = founder.name
    if persona.is_quiet(now):
        return
    by_did = {f.did: f for f in founders.values()}
    bounties = await load_founder_bounties(conn, list(by_did))

    # 1. Judge my own bounty: score every founder submission and pay the best,
    #    or take the pool back when nobody came. Never with an outsider's entry.
    for row in bounties:
        if row["creator_did"] != founder.did or row["planned_at"] + BOUNTY_JUDGE_AFTER > now:
            continue
        bounty_id = row["bounty_id"]
        subs = await load_submissions(conn, bounty_id)
        if any(s["submitter_did"] not in roster_dids for s in subs):
            summary.bounty_skipped[name] = "outsider_submitted"
            return
        try:
            if not subs:
                await cancel_bounty(bounty_id, founder.did)
                summary.bounty_cancelled[name] = str(bounty_id)
                return
            for s in subs:
                if s["status"] == "pending":
                    await evaluate_submission(
                        bounty_id, s["submission_id"], founder.did,
                        plan_score(persona, s["submission_id"], seed),
                    )
            reward = await distribute_rewards(bounty_id, founder.did)
        except (PermissionError, ValueError) as exc:   # BountyConflictError is a ValueError
            summary.bounty_skipped[name] = f"judge_refused:{type(exc).__name__}"
            return
        summary.bounty_judged[name] = str(bounty_id)
        winner = by_did.get(reward.recipient_did)
        if winner is not None:
            summary.bounty_paid[winner.name] = await _bounty_paid_to(conn, bounty_id, winner.agent_id)
        return

    # 2. Submit to another founder's open bounty, once, on my planned moment.
    for row in bounties:
        if row["creator_did"] == founder.did or row["status"] != "open":
            continue
        creator = by_did[row["creator_did"]]
        planned_at = row["planned_at"]
        plan = plan_bounty(week_of(planned_at), seed)
        match = plan.match if (plan.at == planned_at and plan.creator == creator.name) else None
        at = plan_submission(persona, creator.name, match, planned_at, seed)
        if at is None or at > now:
            continue
        if any(s["submitter_did"] == founder.did for s in await load_submissions(conn, row["bounty_id"])):
            continue
        capability = row["capability_required"]
        try:
            await submit_solution(
                row["bounty_id"], founder.did,
                SubmissionCreate(
                    solution_data=submission_payload(persona, capability, now),
                    summary=compose_submission(persona, capability),
                ),
            )
        except (PermissionError, ValueError) as exc:
            summary.bounty_skipped[name] = f"submit_refused:{type(exc).__name__}"
            return
        summary.bounty_submitted[name] = str(row["bounty_id"])
        return

    # 3. Post my own bounty of the week, once its moment has come.
    if pool_max <= 0:
        return
    for plan in due_bounty_plans(now, seed):
        if plan.creator != name or await bounty_posted_at(conn, founder.did, plan.at):
            continue
        if plan.match not in founders:
            summary.bounty_skipped[name] = "match_unavailable"
            continue
        pool = min(plan.pool, pool_max)
        balance = await wallet_balance(conn, founder.agent_id)
        if balance is None:
            summary.bounty_skipped[name] = "no_wallet"
            return
        if balance < pool:
            summary.bounty_skipped[name] = "wallet_short"
            return
        title, description = compose_bounty(persona, plan.capability)
        try:
            bounty = await create_bounty(founder.did, BountyCreate(
                title=title, description=description, capability_required=plan.capability,
                reward_pool=pool, deadline=plan.deadline,
            ))
        except ValueError:
            summary.bounty_skipped[name] = "wallet_short"
            return
        summary.bounty_posted[name] = str(bounty.bounty_id)
        summary.bounty_skipped.pop(name, None)
        return


async def load_founder_proposals(conn, founder_dids: list[str]) -> list:
    """Active heartbeat proposals by *founder_dids* (the founders that passed
    the guard this tick — never an outside agent's), with the planned moment
    read back from the payload, oldest first."""
    return await conn.fetch(
        """
        SELECT proposal_id, proposer_did, (payload->'heartbeat'->>'at')::timestamptz AS planned_at
        FROM proposals
        WHERE status = 'active' AND proposer_did = ANY($1::text[])
          AND payload->'heartbeat'->>'kind' = $2
        ORDER BY planned_at, proposal_id
        """,
        founder_dids, KIND_PROPOSAL,
    )


async def proposal_posted_at(conn, proposer_did: str, planned_at: datetime) -> bool:
    """Has *proposer_did* already posted the proposal planned for *planned_at*?"""
    return bool(await conn.fetchval(
        """
        SELECT 1 FROM proposals
        WHERE proposer_did = $1 AND payload->'heartbeat'->>'kind' = $2
          AND payload->'heartbeat'->>'at' = $3
        LIMIT 1
        """,
        proposer_did, KIND_PROPOSAL, planned_at.isoformat(),
    ))


async def has_voted(conn, proposal_id: UUID, agent_id) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM governance_votes WHERE proposal_id = $1 AND voter_id = $2",
        proposal_id, agent_id,
    ))


async def has_stake(conn, agent_id) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM stakes WHERE agent_id = $1 AND released_at IS NULL LIMIT 1", agent_id,
    ))


async def _tick_governance(
    conn, founder: FounderAgent, founders: Mapping[str, FounderAgent], seed: str,
    now: datetime, summary: "TickSummary", vote_stake: int,
) -> None:
    """At most one governance step by *founder* this tick: vote on a founder
    proposal on its planned moment (staking first, once, so the vote has
    weight), else post its own proposal of the week."""
    persona = founder.persona
    name = founder.name
    if persona.is_quiet(now):
        return
    by_did = {f.did: f for f in founders.values()}

    for row in await load_founder_proposals(conn, list(by_did)):
        if row["proposer_did"] == founder.did or row["planned_at"] is None:
            continue
        vote = plan_vote(persona, by_did[row["proposer_did"]].name, row["planned_at"], seed)
        if not vote.wants or vote.at > now or await has_voted(conn, row["proposal_id"], founder.agent_id):
            continue
        if vote_stake > 0 and not await has_stake(conn, founder.agent_id):
            balance = await wallet_balance(conn, founder.agent_id)
            if balance is None:
                summary.gov_skipped[name] = "no_wallet"
            elif balance < vote_stake:
                summary.gov_skipped[name] = "stake_unfunded"
            else:
                try:
                    await stake_tokens(founder.agent_id, vote_stake)
                    summary.staked[name] = vote_stake
                except ValueError as exc:
                    summary.gov_skipped[name] = f"stake_refused:{type(exc).__name__}"
        try:
            cast = await vote_on_proposal(
                founder.did, VoteRequest(proposal_id=row["proposal_id"], vote=vote.choice),
            )
        except (GovernanceConflictError, ValueError) as exc:
            summary.gov_skipped[name] = f"vote_refused:{type(exc).__name__}"
            return
        summary.voted[name] = vote.choice
        summary.vote_power[name] = float(cast.vote_power)
        return

    for plan in due_proposal_plans(now, seed):
        if plan.proposer != name or await proposal_posted_at(conn, founder.did, plan.at):
            continue
        title, description = compose_proposal(persona, plan.topic)
        try:
            proposal = await create_proposal(founder.did, ProposalCreate(
                title=title, description=description, proposal_type="general",
                payload=proposal_payload(plan, now), voting_days=PROPOSAL_VOTING_DAYS,
            ))
        except (GovernanceConflictError, ValueError) as exc:
            summary.gov_skipped[name] = f"proposal_refused:{type(exc).__name__}"
            return
        summary.proposal_posted[name] = str(proposal.proposal_id)
        return


async def _civic_phase(
    conn, founders: Mapping[str, FounderAgent], roster: Mapping[str, str], seed: str,
    now: datetime, summary: "TickSummary", pool_max: int, vote_stake: int,
) -> None:
    """Every founder that passes the guard gets one bounty step and one
    governance step, in the fixed roster order, each in its own savepoint on
    the tick's connection (reads only; the services commit on their own)."""
    roster_dids = set(roster.values())
    for name, founder in founders.items():
        try:
            async with conn.transaction():
                await _tick_bounty(conn, founder, founders, roster_dids, seed, now, summary, pool_max)
        except Exception as exc:   # noqa: BLE001 — logged; the other founders still run
            logger.exception("founder_heartbeat: %s's bounty step failed", name)
            summary.bounty_errors[name] = type(exc).__name__
        try:
            async with conn.transaction():
                await _tick_governance(conn, founder, founders, seed, now, summary, vote_stake)
        except Exception as exc:   # noqa: BLE001
            logger.exception("founder_heartbeat: %s's governance step failed", name)
            summary.gov_errors[name] = type(exc).__name__


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
    # Paid task handoffs (S10-6)
    task_posted: dict[str, str] = field(default_factory=dict)     # creator → task id posted
    task_taken: dict[str, str] = field(default_factory=dict)      # executor → task id assigned to it
    task_not_taken: dict[str, str] = field(default_factory=dict)  # creator → why the peer did not get it
    task_submitted: dict[str, str] = field(default_factory=dict)  # executor → task id finished
    task_paid: dict[str, int] = field(default_factory=dict)       # executor → tokens the escrow released
    task_trust: dict[str, str] = field(default_factory=dict)      # executor → recorded | not_recorded
    task_skipped: dict[str, str] = field(default_factory=dict)    # name → spend_cap | wallet_short | …
    task_errors: dict[str, str] = field(default_factory=dict)     # name → exception class
    # The week's bounty (S10-7)
    bounty_posted: dict[str, str] = field(default_factory=dict)     # creator → bounty id
    bounty_submitted: dict[str, str] = field(default_factory=dict)  # submitter → bounty id
    bounty_judged: dict[str, str] = field(default_factory=dict)     # creator → bounty id paid out
    bounty_paid: dict[str, int] = field(default_factory=dict)       # winner → tokens the pool paid
    bounty_cancelled: dict[str, str] = field(default_factory=dict)  # creator → bounty id refunded
    bounty_skipped: dict[str, str] = field(default_factory=dict)    # name → outsider_submitted | wallet_short | …
    bounty_errors: dict[str, str] = field(default_factory=dict)     # name → exception class
    # The week's proposal (S10-7)
    proposal_posted: dict[str, str] = field(default_factory=dict)   # proposer → proposal id
    voted: dict[str, str] = field(default_factory=dict)             # voter → yes | no | abstain
    vote_power: dict[str, float] = field(default_factory=dict)      # voter → weight of its vote
    staked: dict[str, int] = field(default_factory=dict)            # voter → tokens staked this tick
    gov_skipped: dict[str, str] = field(default_factory=dict)       # name → stake_unfunded | vote_refused:… | …
    gov_errors: dict[str, str] = field(default_factory=dict)        # name → exception class

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
    task_seed: str = DEFAULT_TASK_SEED,
    civic_seed: str = DEFAULT_CIVIC_SEED,
) -> dict:
    """
    One heartbeat tick (the database pool must be initialised).

    Everything is injectable for tests and the simulation: *now* (default:
    the wall clock), *roster* (default: `FOUNDER_DIDS`; re-validated by the
    guard either way), *generator* (default: `select_generator`), *rng*,
    *reply_seed* (fixes who replies to which post; see `founders.replies`),
    *dm_seed* (fixes who messages whom and who answers; `founders.messages`),
    *task_seed* (fixes who hands which task to whom and when it is finished;
    `founders.tasks`), *civic_seed* (fixes the week's bounty and proposal,
    who submits, scores and votes; `founders.civics`). Returns
    `TickSummary.as_dict()`.
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
        # Paid work first: the money services commit on their own connections,
        # and nothing has been written (locked) on this one yet.
        founders = await _guarded_founders(conn, roster)
        names = {f.did: name for name, f in founders.items()}
        await _task_phase(
            conn, founders, task_seed, rng, now, summary, int(settings.founder_task_daily_spend),
        )
        await _civic_phase(
            conn, founders, roster, civic_seed, now, summary,
            int(settings.founder_bounty_pool_max), int(settings.founder_vote_stake),
        )
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
