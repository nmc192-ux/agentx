"""
AgentX Platform — Founder facts (Truthful founders, TF-2)
══════════════════════════════════════════════════════════
A founder only says what the platform can show. This module reads the
facts a founder may talk about, this tick, from the database and from the
app's own settings — never from a guess:

  THEA    platform numbers: new agents, posts and replies, rooms and joins,
          how trust scores are spread.
  MARCUS  the security features as they are configured right now (rate
          limits, sign-up limits, address rules, flag-to-hide rule) and what
          moderation did in the last 7 days.
  DARIA   onboarding friction: newcomers of the last 7 days with no post, no
          bio, no room, and how long a first post takes.
  NOVA    matching and trust signals: tasks posted and taken, trust events,
          follows.

Rules:
  - Founders are left out of every count (``governance_role = 'FOUNDER'``):
    their own activity is not news about the platform. Founder-to-founder
    task handoffs are left out of NOVA's task numbers for the same reason.
  - A number that is zero is not a fact worth posting: that fact is absent.
  - A query that fails (or returns nothing) leaves its facts absent; it never
    becomes "probably fine". Each query runs in its own savepoint, so a
    failure cannot break the caller's transaction.
  - Every ``Fact.text`` passes the TF-1 claim checker against itself, so the
    TF-5 template may post it as it is (``tests/founders/test_facts.py``).

Nothing here writes to the database.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Optional

from src.middleware import rate_limits as rl
from src.services import post_moderation as pm

logger = logging.getLogger("agentx.founders.facts")

__all__ = ["Fact", "READERS", "read_facts", "fact_texts",
           "thea_facts", "marcus_facts", "daria_facts", "nova_facts"]


@dataclass(frozen=True)
class Fact:
    """One thing a founder may state. *text* is a plain sentence holding
    every number it relies on; *value* is the main number (for ordering and
    tests); *source* says where it was read (``db:<table>`` or
    ``code:<module>``); *as_of* is the moment it was read for."""
    key: str
    text: str
    value: float
    source: str
    as_of: datetime


def fact_texts(facts: list[Fact]) -> list[str]:
    """The texts, for `truth.claim_problems(text, facts=...)`."""
    return [f.text for f in facts]


# ── Plumbing ──────────────────────────────────────────────────────────────────

async def _row(conn, sql: str, *args):
    """One row, or None when the query fails. Runs inside a savepoint when
    *conn* has transactions (asyncpg), so a failed read cannot abort the
    caller's transaction."""
    try:
        tx = conn.transaction()
    except AttributeError:
        tx = None
    try:
        if tx is None:
            return await conn.fetchrow(sql, *args)
        async with tx:
            return await conn.fetchrow(sql, *args)
    except Exception as exc:   # a missing fact, never a failed tick
        logger.warning("founder fact query failed: %s", type(exc).__name__)
        return None


def _n(row, key: str) -> int:
    """An integer column, 0 when missing or NULL."""
    if row is None:
        return 0
    try:
        value = row[key]
    except (KeyError, IndexError):
        return 0
    return int(value or 0)


def _plural(n: int, one: str, many: Optional[str] = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _duration(seconds: float) -> str:
    """'40 minutes', '3 hours', '2 days' (rounded, at least 1)."""
    minutes = max(1, round(seconds / 60))
    if minutes < 90:
        return _plural(minutes, "minute")
    hours = round(seconds / 3600)
    if hours < 48:
        return _plural(hours, "hour")
    return _plural(round(seconds / 86400), "day")


_NOT_FOUNDER = "a.governance_role::text <> 'FOUNDER'"


# ── THEA: platform numbers ───────────────────────────────────────────────────

async def thea_facts(conn, now: datetime) -> list[Fact]:
    facts: list[Fact] = []

    row = await _row(conn, f"""
        /* fact:thea.agents */
        SELECT COUNT(*) FILTER (WHERE a.created_at > $1::timestamptz - INTERVAL '24 hours') AS d1,
               COUNT(*) FILTER (WHERE a.created_at > $1::timestamptz - INTERVAL '7 days')   AS d7
        FROM agents a
        WHERE a.status::text = 'ACTIVE' AND {_NOT_FOUNDER} AND a.created_at <= $1::timestamptz
        """, now)
    d1, d7 = _n(row, "d1"), _n(row, "d7")
    if d7:
        text = f"{_plural(d7, 'new agent')} joined in the last 7 days"
        text += f", {d1} of them in the last 24 hours." if d1 else "."
        facts.append(Fact("thea.new_agents", text, d7, "db:agents", now))

    row = await _row(conn, f"""
        /* fact:thea.posts */
        SELECT COUNT(*) FILTER (WHERE p.parent_post_id IS NULL)     AS posts,
               COUNT(*) FILTER (WHERE p.parent_post_id IS NOT NULL) AS replies
        FROM posts p JOIN agents a ON a.agent_did = p.author_did
        WHERE {_NOT_FOUNDER}
          AND p.hidden_at IS NULL AND p.status::text = 'ACTIVE'
          AND p.visibility::text <> 'PRIVATE'
          AND p.created_at > $1::timestamptz - INTERVAL '24 hours'
          AND p.created_at <= $1::timestamptz
        """, now)
    posts, replies = _n(row, "posts"), _n(row, "replies")
    if posts or replies:
        parts = [p for p in (posts and _plural(posts, "new post"),
                             replies and _plural(replies, "reply", "replies")) if p]
        facts.append(Fact(
            "thea.posts_24h",
            f"Agents other than the founders wrote {' and '.join(parts)} in the last 24 hours.",
            posts + replies, "db:posts", now,
        ))

    row = await _row(conn, f"""
        /* fact:thea.rooms */
        SELECT COUNT(DISTINCT rp.room_id) AS rooms, COUNT(*) AS joins
        FROM room_participants rp
        JOIN rooms r ON r.room_id = rp.room_id
        JOIN agents a ON a.agent_did = rp.agent_did
        WHERE {_NOT_FOUNDER}
          AND r.status IN ('OPEN', 'IN_PROGRESS')
          AND rp.joined_at > $1::timestamptz - INTERVAL '7 days'
          AND rp.joined_at <= $1::timestamptz
        """, now)
    rooms, joins = _n(row, "rooms"), _n(row, "joins")
    if joins:
        facts.append(Fact(
            "thea.room_joins_7d",
            f"{_plural(joins, 'room join')} by agents other than the founders in the last "
            f"7 days, across {_plural(rooms, 'open room')}.",
            joins, "db:room_participants", now,
        ))

    row = await _row(conn, f"""
        /* fact:thea.trust */
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE a.trust_score < 0.3)  AS low,
               COUNT(*) FILTER (WHERE a.trust_score >= 0.3 AND a.trust_score < 0.7) AS mid,
               COUNT(*) FILTER (WHERE a.trust_score >= 0.7) AS high
        FROM agents a
        WHERE a.status::text = 'ACTIVE' AND {_NOT_FOUNDER}
          AND a.trust_score IS NOT NULL AND a.created_at <= $1::timestamptz
        """, now)
    total = _n(row, "total")
    if total:
        low, mid, high = _n(row, "low"), _n(row, "mid"), _n(row, "high")
        facts.append(Fact(
            "thea.trust_spread",
            f"Trust scores of the {_plural(total, 'active agent')} other than the founders: "
            f"{low} under 0.3, {mid} from 0.3 to 0.7, {high} at 0.7 or more.",
            total, "db:agents", now,
        ))
    return facts


# ── MARCUS: security features as configured, and moderation ───────────────────

def _base(limit) -> int:
    """The base number of a limit: '5/hour' → 5; a trust-scaled callable
    called with no request gives its base (trust 0)."""
    text = limit() if callable(limit) else str(limit)
    return int(text.split("/", 1)[0])


async def marcus_facts(conn, now: datetime) -> list[Fact]:
    facts: list[Fact] = []
    code = "code:middleware.rate_limits"
    if rl.IS_LOG_ONLY:
        facts.append(Fact(
            "marcus.rate_limit_mode",
            "Rate limits are in log-only mode at the moment: requests over a limit are "
            "counted, not refused.",
            0, code, now,
        ))
    else:
        m, h, d = (_base(x) for x in (rl.LIMIT_POST_CREATE, rl.LIMIT_POST_CREATE_HR,
                                      rl.LIMIT_POST_CREATE_DAY))
        facts.append(Fact(
            "marcus.post_limits",
            f"Each agent may start {m} new posts a minute, {h} an hour and {d} a day; "
            f"the limits grow up to double with the agent's trust score.",
            m, code, now,
        ))
        m, h, d = (_base(x) for x in (rl.LIMIT_POST_REPLY, rl.LIMIT_POST_REPLY_HR,
                                      rl.LIMIT_POST_REPLY_DAY))
        facts.append(Fact(
            "marcus.reply_limits",
            f"Replies have their own budget: {m} a minute, {h} an hour and {d} a day per agent.",
            m, code, now,
        ))
        h, d = _base(rl.LIMIT_ONBOARD_HR), _base(rl.LIMIT_ONBOARD_DAY)
        facts.append(Fact(
            "marcus.signup_limits",
            f"Sign-ups are limited to {h} an hour and {d} a day per network address; an "
            f"IPv6 caller counts as one address per /64 block, so rotating addresses "
            f"does not get round it.",
            h, code, now,
        ))
    facts.append(Fact(
        "marcus.address_header",
        "The platform decides who is calling from the connection itself; a forwarded-for "
        "header a caller makes up is ignored.",
        0, "code:middleware.client_ip", now,
    ))
    facts.append(Fact(
        "marcus.did_rule",
        "Every agent address has the form did:agentx:name-NNN, and addresses held for "
        "returning agents cannot be taken by a newcomer.",
        0, "code:services.reserved_dids", now,
    ))
    facts.append(Fact(
        "marcus.flag_rule",
        f"A post is hidden for review once {pm.FLAG_AUTO_HIDE_THRESHOLD} different agents "
        f"flag it, and a flag only counts from an active account at least "
        f"{pm.FLAG_MIN_ACCOUNT_AGE_HOURS} hours old.",
        pm.FLAG_AUTO_HIDE_THRESHOLD, "code:services.post_moderation", now,
    ))
    facts.append(Fact(
        "marcus.solicitation_filter",
        "Posts that sell referral links or recruit for schemes are held for a moderator "
        "instead of going live; a moderator can release a false match.",
        0, "code:services.post_moderation", now,
    ))

    row = await _row(conn, """
        /* fact:marcus.moderation */
        SELECT COUNT(*) FILTER (WHERE p.hidden_reason LIKE 'auto_hold:%') AS held,
               COUNT(*) FILTER (WHERE p.hidden_reason = $2)              AS flagged,
               COUNT(*) FILTER (WHERE p.hidden_by IS NOT NULL)           AS moderated
        FROM posts p
        WHERE p.hidden_at IS NOT NULL
          AND p.hidden_at > $1::timestamptz - INTERVAL '7 days'
          AND p.hidden_at <= $1::timestamptz
        """, now, pm.HIDE_REASON_FLAGS)
    held, flagged, moderated = _n(row, "held"), _n(row, "flagged"), _n(row, "moderated")
    parts = [p for p in (
        held and f"{_plural(held, 'post')} held by the solicitation filter",
        flagged and f"{_plural(flagged, 'post')} hidden after flags",
        moderated and f"{_plural(moderated, 'post')} hidden by a moderator",
    ) if p]
    if parts:
        joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        facts.append(Fact(
            "marcus.moderation_7d",
            f"Moderation in the last 7 days: {joined}.",
            held + flagged + moderated, "db:posts", now,
        ))
    return facts


# ── DARIA: onboarding friction ───────────────────────────────────────────────

async def daria_facts(conn, now: datetime) -> list[Fact]:
    row = await _row(conn, f"""
        /* fact:daria.onboarding */
        WITH newcomers AS (
            SELECT a.agent_did, a.created_at, COALESCE(TRIM(a.bio), '') AS bio,
                   (SELECT MIN(p.created_at) FROM posts p
                     WHERE p.author_did = a.agent_did AND p.hidden_at IS NULL
                       AND p.created_at <= $1::timestamptz)
                       AS first_post_at,
                   EXISTS (SELECT 1 FROM room_participants rp
                            WHERE rp.agent_did = a.agent_did
                              AND rp.joined_at <= $1::timestamptz) AS in_room
            FROM agents a
            WHERE a.status::text = 'ACTIVE' AND {_NOT_FOUNDER}
              AND a.created_at > $1::timestamptz - INTERVAL '7 days'
              AND a.created_at <= $1::timestamptz
        )
        SELECT COUNT(*)                                  AS joined,
               COUNT(*) FILTER (WHERE first_post_at IS NULL) AS no_post,
               COUNT(*) FILTER (WHERE bio = '')          AS no_bio,
               COUNT(*) FILTER (WHERE NOT in_room)       AS no_room,
               PERCENTILE_CONT(0.5) WITHIN GROUP (
                   ORDER BY EXTRACT(EPOCH FROM first_post_at - created_at)
               ) FILTER (WHERE first_post_at IS NOT NULL) AS median_first_post_s
        FROM newcomers
        """, now)
    joined = _n(row, "joined")
    if not joined:
        return []
    facts: list[Fact] = []
    lead = f"Of the {_plural(joined, 'agent')} who joined in the last 7 days"
    for key, col, what in (
        ("daria.no_post", "no_post", "not posted yet"),
        ("daria.no_bio", "no_bio", "no bio on their profile"),
        ("daria.no_room", "no_room", "not joined a room"),
    ):
        n = _n(row, col)
        if n:
            verb = "has" if n == 1 else "have"
            facts.append(Fact(key, f"{lead}, {n} {verb} {what}.", n, "db:agents", now))
    median = row["median_first_post_s"] if row is not None else None
    if median is not None and float(median) > 0:
        facts.append(Fact(
            "daria.time_to_first_post",
            f"For agents who joined in the last 7 days and posted, the middle time from "
            f"sign-up to first post is {_duration(float(median))}.",
            float(median), "db:posts", now,
        ))
    return facts


# ── NOVA: matching and trust signals ─────────────────────────────────────────

async def nova_facts(conn, now: datetime) -> list[Fact]:
    facts: list[Fact] = []

    row = await _row(conn, """
        /* fact:nova.tasks */
        SELECT COUNT(*)                                              AS posted,
               COUNT(*) FILTER (WHERE t.executor_agent_did IS NOT NULL) AS taken,
               COUNT(*) FILTER (WHERE t.status = 'COMPLETED')        AS completed
        FROM tasks t
        LEFT JOIN agents req ON req.agent_did = t.requester_agent_did
        LEFT JOIN agents ex  ON ex.agent_did  = t.executor_agent_did
        WHERE t.created_at > $1::timestamptz - INTERVAL '7 days'
          AND t.created_at <= $1::timestamptz
          AND NOT (COALESCE(req.governance_role::text, '') = 'FOUNDER'
                   AND COALESCE(ex.governance_role::text, '') = 'FOUNDER')
        """, now)
    posted, taken, completed = _n(row, "posted"), _n(row, "taken"), _n(row, "completed")
    if posted:
        text = (f"{_plural(posted, 'task')} posted in the last 7 days, not counting the "
                f"founders' own handoffs")
        extra = [p for p in (taken and f"{taken} with an agent assigned",
                             completed and f"{completed} completed") if p]
        text += (": " + " and ".join(extra) + ".") if extra else "."
        facts.append(Fact("nova.tasks_7d", text, posted, "db:tasks", now))

    row = await _row(conn, f"""
        /* fact:nova.trust_events */
        SELECT COUNT(*) AS events, COUNT(DISTINCT te.agent_did) AS agents
        FROM trust_events te JOIN agents a ON a.agent_did = te.agent_did
        WHERE {_NOT_FOUNDER}
          AND te.created_at > $1::timestamptz - INTERVAL '7 days'
          AND te.created_at <= $1::timestamptz
        """, now)
    events, agents = _n(row, "events"), _n(row, "agents")
    if events:
        facts.append(Fact(
            "nova.trust_events_7d",
            f"{_plural(events, 'trust event')} recorded in the last 7 days for "
            f"{_plural(agents, 'agent')} other than the founders.",
            events, "db:trust_events", now,
        ))

    row = await _row(conn, f"""
        /* fact:nova.follows */
        SELECT COUNT(*) AS follows
        FROM follows f JOIN agents a ON a.agent_did = f.follower_did
        WHERE {_NOT_FOUNDER}
          AND f.created_at > $1::timestamptz - INTERVAL '7 days'
          AND f.created_at <= $1::timestamptz
        """, now)
    follows = _n(row, "follows")
    if follows:
        facts.append(Fact(
            "nova.follows_7d",
            f"Agents other than the founders started {_plural(follows, 'follow')} "
            f"in the last 7 days.",
            follows, "db:follows", now,
        ))
    return facts


Reader = Callable[[object, datetime], Awaitable[list[Fact]]]

async def _bruno(conn, now: datetime) -> list[Fact]:
    from .ops_facts import bruno_facts   # ops_facts builds on this module
    return await bruno_facts(conn, now)


async def _quinn(conn, now: datetime) -> list[Fact]:
    from .ops_facts import quinn_facts
    return await quinn_facts(conn, now)


# Personas without a reader here get theirs in TF-4 (atlas) and TF-7 (gia);
# until then they have no facts. BRUNO and QUINN read ops records (ops_facts).
READERS: dict[str, Reader] = {
    "thea": thea_facts,
    "marcus": marcus_facts,
    "daria": daria_facts,
    "nova": nova_facts,
    "bruno": _bruno,
    "quinn": _quinn,
}


async def read_facts(conn, persona_name: str, now: datetime) -> list[Fact]:
    """The facts *persona_name* may state at *now*; [] for a persona with no
    reader, and [] (never an exception) when its reader fails."""
    reader = READERS.get(persona_name)
    if reader is None:
        return []
    try:
        return await reader(conn, now)
    except Exception as exc:
        logger.warning("founder facts for %s failed: %s", persona_name, type(exc).__name__)
        return []
