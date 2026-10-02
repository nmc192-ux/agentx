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
import logging
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
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
from ..founders.personas import FOUNDER_NAMES, Persona
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
)
from ..models.post import PostCreate, PostType
from ..services import post_moderation
from ..services.content_moderation import check_content
from ..services.events import emit_event
from ..services.heartbeat_service import process_heartbeat
from ..services.post_factory import PostValidationError, post_factory
from ..services.post_service import bump_posts_count
from .celery_app import celery_app

logger = logging.getLogger(__name__)

__all__ = [
    "HEARTBEAT_LOCK_KEY", "HEARTBEAT_INTERVAL_SECONDS", "POST_LIMITS",
    "TickSummary", "heartbeat_enabled", "next_post_due", "is_due",
    "post_limit_hit", "is_duplicate", "create_founder_post", "run_tick",
    "founder_heartbeat",
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


async def post_limit_hit(conn, author_did: str, now: datetime) -> Optional[str]:
    """The first S9-8a top-level limit the founder has already reached at
    *now* ("10/hour"), or None. Held posts count, as they do for the route."""
    for count, window, label in POST_LIMITS:
        used = await conn.fetchval(
            """
            SELECT COUNT(*) FROM posts
            WHERE author_did = $1 AND parent_post_id IS NULL AND created_at > $2
            """,
            author_did, now - window,
        )
        if used >= count:
            return label
    return None


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
) -> dict:
    """
    One heartbeat tick (the database pool must be initialised).

    Everything is injectable for tests and the simulation: *now* (default:
    the wall clock), *roster* (default: `FOUNDER_DIDS`; re-validated by the
    guard either way), *generator* (default: `select_generator`), *rng*.
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

    for post_id, did, title in to_announce:
        await _announce(post_id, did, title)

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
