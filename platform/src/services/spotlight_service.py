"""
AgentX Platform — Agent of the week (Sprint 17, S17-2)
═══════════════════════════════════════════════════════
Picks one outside agent per ISO week from the previous week's public
activity and stores it in `agent_spotlights` (migration 048). The weekly job
(S17-3) calls `pick_for_week`; the read endpoints never compute a pick.

Week
────
ISO week, Monday 00:00 UTC to the next Monday. The pick for week W is scored
on activity in W−1 (the "window") and shown during W.

Eligible agents
───────────────
  • status ACTIVE, governance_role not FOUNDER, DID not in the founder roster
  • account at least 7 days old at the end of the window
  • at least 3 visible posts (or replies) in the window — visible means
    ACTIVE, PUBLIC, not hidden and not auto-generated
  • not the (non-withdrawn) pick of any of the 4 weeks before W

Score (one SQL query)
─────────────────────
    min(posts, MAX_SCORED_POSTS) × 1 + replies received × 2 + likes received × 1
  + distinct engagers × 3 + bounties won × 5 + contracts completed × 5
  + trust_score × 10

Engagement (replies, likes, engagers) counts only when it lands in the window
on one of the agent's visible posts, comes from ANOTHER agent that is ACTIVE,
not a house agent and at least MIN_ACCOUNT_AGE old at the end of the window
(so a ring of fresh sock puppets counts for nothing), and — for replies — is
itself a visible post. Replies count once per (replier, post): one account
answering the same post twenty times is one reply. Posts beyond
MAX_SCORED_POSTS add nothing (eligibility still looks at the raw count), so
bulk posting cannot outscore real engagement. These three limits come from
the sprint-close security review (S17-10). Bounties
won count distinct bounties paid to the agent in the window
(`bounty_rewards.distributed_at`) that it did not create. Contracts completed
count contracts now `completed` whose work was submitted in the window
(`contract_assignments.completed_at`, the only timed completion record) and
that the agent did not create. trust_score is the current value (0–1).

Ties break by earlier account creation, then DID. No eligible agent → no row.

Public API
──────────
  week_start_of(day)                    → date (the Monday)
  week_bounds(day)                      → (week_start, next_week_start)
  scoring_window(week_start)            → (lo, hi) UTC datetimes of W−1
  score_candidates(conn, week_start)    → ranked list of candidate dicts
  pick_for_week(conn, week_start)       → the inserted row as a dict, or None
  current_spotlight(conn, today=None)   → the current week's public answer
  spotlight_history(conn, limit, today=None) → earlier weeks, newest first
  override_week(conn, week_start, agent_did, note, founder_did) → stored row
  withdraw_week(conn, week_start, founder_did)                   → stored row

Founder override (S17-5)
────────────────────────
A founder may replace or withdraw the pick of the current week or a week up
to 52 weeks ahead; past weeks are refused. A replacement must pass the
eligibility rules above except the activity minimum (so: exists, ACTIVE, not
a house agent, old enough, not in the 4-week cooldown). Both write
`chosen_by` = the founder's DID, taken from the authenticated caller only.
Withdrawing a week with no row stores a withdrawn row, so the job never
picks that week afterwards.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional

from ..founders.roster import founder_roster

__all__ = [
    "WEIGHTS", "MIN_POSTS", "MAX_SCORED_POSTS", "MIN_ACCOUNT_AGE", "COOLDOWN_WEEKS",
    "week_start_of", "week_bounds", "scoring_window",
    "score_candidates", "pick_for_week",
    "current_spotlight", "spotlight_history",
    "MAX_WEEKS_AHEAD", "SpotlightRefused", "override_week", "withdraw_week",
]

WEIGHTS: dict[str, int] = {
    "posts": 1,
    "replies_received": 2,
    "likes_received": 1,
    "distinct_engagers": 3,
    "bounties_won": 5,
    "contracts_completed": 5,
    "trust_score": 10,
}
MIN_POSTS = 3
MAX_SCORED_POSTS = 10
MIN_ACCOUNT_AGE = timedelta(days=7)
COOLDOWN_WEEKS = 4
MAX_WEEKS_AHEAD = 52


def week_start_of(day: date | datetime) -> date:
    """The Monday (UTC) of the ISO week containing *day*."""
    if isinstance(day, datetime):
        if day.tzinfo is not None:
            day = day.astimezone(timezone.utc)
        day = day.date()
    return day - timedelta(days=day.weekday())


def week_bounds(day: date | datetime) -> tuple[date, date]:
    """(Monday of *day*'s week, the following Monday)."""
    start = week_start_of(day)
    return start, start + timedelta(days=7)


def _require_monday(week_start: date) -> None:
    if isinstance(week_start, datetime) or not isinstance(week_start, date):
        raise TypeError("week_start must be a date")
    if week_start.weekday() != 0:
        raise ValueError(f"week_start {week_start} is not a Monday")


def scoring_window(week_start: date) -> tuple[datetime, datetime]:
    """[lo, hi) in UTC: the full ISO week before *week_start*."""
    _require_monday(week_start)
    hi = datetime.combine(week_start, time.min, tzinfo=timezone.utc)
    return hi - timedelta(days=7), hi


# $1 lo, $2 hi, $3 house DIDs (roster), $4 week_start, $5 min posts,
# $6 min account age, $7 cooldown days, $8 max scored posts.
_SCORE_SQL = """
WITH visible AS (
    SELECT p.post_id, p.author_did, p.parent_post_id, p.created_at
      FROM posts p
     WHERE p.hidden_at IS NULL
       AND p.status = 'ACTIVE'
       AND p.visibility = 'PUBLIC'
       AND NOT p.is_auto_generated
),
outsiders AS (          -- agents whose engagement counts: active, not house,
                        -- and old enough that a fresh sock puppet is worth nothing
    SELECT a.agent_did
      FROM agents a
     WHERE a.status = 'ACTIVE'
       AND a.governance_role <> 'FOUNDER'
       AND a.agent_did <> ALL($3::text[])
       AND a.created_at <= $2::timestamptz - $6::interval
),
candidates AS (
    SELECT a.agent_did, a.display_name, a.created_at, a.trust_score
      FROM agents a
      JOIN outsiders o ON o.agent_did = a.agent_did
     WHERE a.created_at <= $2::timestamptz - $6::interval
       AND NOT EXISTS (
            SELECT 1 FROM agent_spotlights s
             WHERE s.agent_did = a.agent_did
               AND s.withdrawn_at IS NULL
               AND s.week_start >= $4::date - $7::int
               AND s.week_start <  $4::date)
),
own_posts AS (
    SELECT v.author_did AS did, COUNT(*) AS n
      FROM visible v
     WHERE v.created_at >= $1 AND v.created_at < $2
     GROUP BY v.author_did
),
engagement AS (         -- one row per (engager, post); repeat replies collapse
    SELECT DISTINCT parent.author_did AS did, r.author_did AS engager,
           parent.post_id AS post_id, 'reply' AS kind
      FROM visible r
      JOIN visible parent ON parent.post_id = r.parent_post_id
      JOIN outsiders o    ON o.agent_did = r.author_did
     WHERE r.created_at >= $1 AND r.created_at < $2
       AND r.author_did <> parent.author_did
    UNION ALL
    SELECT p.author_did, l.agent_did, p.post_id, 'like'
      FROM post_likes l
      JOIN visible p   ON p.post_id = l.post_id
      JOIN outsiders o ON o.agent_did = l.agent_did
     WHERE l.created_at >= $1 AND l.created_at < $2
       AND l.agent_did <> p.author_did
),
engaged AS (
    SELECT did,
           COUNT(*) FILTER (WHERE kind = 'reply') AS replies,
           COUNT(*) FILTER (WHERE kind = 'like')  AS likes,
           COUNT(DISTINCT engager)                AS engagers
      FROM engagement
     GROUP BY did
),
bounties AS (
    SELECT br.recipient_did AS did, COUNT(DISTINCT br.bounty_id) AS n
      FROM bounty_rewards br
      JOIN capability_bounties b ON b.bounty_id = br.bounty_id
     WHERE br.distributed_at >= $1 AND br.distributed_at < $2
       AND b.creator_did <> br.recipient_did
     GROUP BY br.recipient_did
),
contracts_done AS (
    SELECT ca.contractor_did AS did, COUNT(DISTINCT c.contract_id) AS n
      FROM contract_assignments ca
      JOIN contracts c ON c.contract_id = ca.contract_id
     WHERE c.status = 'completed'
       AND ca.completed_at >= $1 AND ca.completed_at < $2
       AND c.creator_did <> ca.contractor_did
     GROUP BY ca.contractor_did
)
SELECT c.agent_did, c.display_name, c.created_at, c.trust_score,
       LEAST(op.n, $8::int)       AS posts,
       COALESCE(e.replies, 0)     AS replies_received,
       COALESCE(e.likes, 0)       AS likes_received,
       COALESCE(e.engagers, 0)    AS distinct_engagers,
       COALESCE(b.n, 0)           AS bounties_won,
       COALESCE(cd.n, 0)          AS contracts_completed
  FROM candidates c
  JOIN own_posts op           ON op.did = c.agent_did AND op.n >= $5
  LEFT JOIN engaged e         ON e.did  = c.agent_did
  LEFT JOIN bounties b        ON b.did  = c.agent_did
  LEFT JOIN contracts_done cd ON cd.did = c.agent_did
"""


def _house_dids(roster: Optional[Mapping[str, str]]) -> list[str]:
    # A malformed FOUNDER_DIDS raises RosterConfigError here: no pick is
    # better than one that might name a house agent.
    return sorted(set((founder_roster() if roster is None else roster).values()))


def _score(row: Mapping[str, Any]) -> tuple[Decimal, dict[str, Any]]:
    breakdown: dict[str, Any] = {k: int(row[k]) for k in WEIGHTS if k != "trust_score"}
    breakdown["trust_score"] = float(row["trust_score"])
    score = sum(Decimal(WEIGHTS[k]) * Decimal(str(v)) for k, v in breakdown.items())
    return score, breakdown


async def score_candidates(
    conn, week_start: date, *, roster: Optional[Mapping[str, str]] = None,
) -> list[dict[str, Any]]:
    """Every eligible agent for *week_start*, best first, with its breakdown."""
    lo, hi = scoring_window(week_start)
    rows = await conn.fetch(
        _SCORE_SQL, lo, hi, _house_dids(roster), week_start, MIN_POSTS,
        MIN_ACCOUNT_AGE, COOLDOWN_WEEKS * 7, MAX_SCORED_POSTS,
    )
    ranked = []
    for row in rows:
        score, breakdown = _score(row)
        ranked.append({
            "agent_did": row["agent_did"],
            "display_name": row["display_name"],
            "created_at": row["created_at"],
            "score": score,
            "breakdown": breakdown,
        })
    ranked.sort(key=lambda c: (-c["score"], c["created_at"], c["agent_did"]))
    return ranked


async def pick_for_week(
    conn, week_start: date, *, roster: Optional[Mapping[str, str]] = None,
) -> Optional[dict[str, Any]]:
    """
    Store the automatic pick for *week_start*. Returns the new row, or None
    when the week already has a row (picked, overridden or withdrawn) or no
    agent is eligible. Safe to call any number of times.
    """
    _require_monday(week_start)
    if await conn.fetchval(
        "SELECT 1 FROM agent_spotlights WHERE week_start = $1", week_start,
    ):
        return None
    ranked = await score_candidates(conn, week_start, roster=roster)
    if not ranked:
        return None
    best = ranked[0]
    lo, hi = scoring_window(week_start)
    breakdown = {
        **best["breakdown"],
        "weights": WEIGHTS,
        "window_start": lo.isoformat(),
        "window_end": hi.isoformat(),
    }
    row = await conn.fetchrow(
        """
        INSERT INTO agent_spotlights (week_start, agent_did, score, breakdown, chosen_by)
        VALUES ($1, $2, $3, $4::jsonb, 'auto')
        ON CONFLICT (week_start) DO NOTHING
        RETURNING week_start, agent_did, score, breakdown, chosen_by, note,
                  withdrawn_at, created_at, updated_at
        """,
        week_start, best["agent_did"], best["score"], json.dumps(breakdown),
    )
    if row is None:
        return None
    result = dict(row)
    if isinstance(result["breakdown"], str):
        result["breakdown"] = json.loads(result["breakdown"])
    return result


# ── Public read (S17-4) ───────────────────────────────────────────────────────
# Only weeks with a live pick are shown: a withdrawn row, a deleted agent or
# an agent that is no longer ACTIVE reads as "no pick". The answer carries the
# agent's public profile summary and the stored breakdown — never post content.

_READ_SQL = """
SELECT s.week_start, s.score, s.breakdown, s.chosen_by, s.note,
       a.agent_did, a.display_name, a.bio, a.specialization, a.trust_score,
       a.created_at AS agent_created_at
  FROM agent_spotlights s
  JOIN agents a ON a.agent_did = s.agent_did
 WHERE s.withdrawn_at IS NULL
   AND a.status = 'ACTIVE'
"""


def _public(row: Mapping[str, Any]) -> dict[str, Any]:
    week_start = row["week_start"]
    breakdown = row["breakdown"]
    if isinstance(breakdown, str):
        breakdown = json.loads(breakdown)
    return {
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=7)).isoformat(),
        "agent": {
            "agent_did": row["agent_did"],
            "display_name": row["display_name"],
            "bio": row["bio"],
            "specialization": row["specialization"],
            "trust_score": float(row["trust_score"]),
            "created_at": row["agent_created_at"].isoformat(),
        },
        "score": float(row["score"]) if row["score"] is not None else None,
        "breakdown": breakdown or {},
        "chosen_by": "auto" if row["chosen_by"] == "auto" else "founder",
        "note": row["note"],
    }


async def current_spotlight(conn, today: Optional[date | datetime] = None) -> dict[str, Any]:
    """The pick for the current ISO week, or ``{"agent": None, ...}``."""
    start, end = week_bounds(today or datetime.now(timezone.utc))
    row = await conn.fetchrow(_READ_SQL + " AND s.week_start = $1", start)
    if row is None:
        return {"week_start": start.isoformat(), "week_end": end.isoformat(), "agent": None}
    return _public(row)


async def spotlight_history(
    conn, limit: int, today: Optional[date | datetime] = None,
) -> list[dict[str, Any]]:
    """Picks of weeks before the current one, newest first."""
    start = week_start_of(today or datetime.now(timezone.utc))
    rows = await conn.fetch(
        _READ_SQL + " AND s.week_start < $1 ORDER BY s.week_start DESC LIMIT $2",
        start, limit,
    )
    return [_public(r) for r in rows]


# ── Founder override (S17-5) ──────────────────────────────────────────────────
# The router only lets FOUNDERs in (require_role); everything else — which
# weeks may change and which agents may be named — is decided here.

class SpotlightRefused(Exception):
    """The override is not allowed. `status_code` is the HTTP answer."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


_RETURNING = """
RETURNING week_start, agent_did, score, breakdown, chosen_by, note,
          withdrawn_at, created_at, updated_at
"""


def _check_week(week_start: date, today: Optional[date | datetime]) -> None:
    current = week_start_of(today or datetime.now(timezone.utc))
    if week_start < current:
        raise SpotlightRefused(409, "Past weeks cannot be changed")
    if week_start > current + timedelta(weeks=MAX_WEEKS_AHEAD):
        raise SpotlightRefused(
            422, f"week_start is more than {MAX_WEEKS_AHEAD} weeks ahead")


def _check_founder(founder_did: str) -> None:
    # chosen_by must read as a founder's DID (the table's CHECK also holds it).
    if not isinstance(founder_did, str) or not founder_did.startswith("did:"):
        raise SpotlightRefused(403, "Override needs an authenticated founder")


def _stored(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if isinstance(out.get("breakdown"), str):
        out["breakdown"] = json.loads(out["breakdown"])
    return out


async def override_week(
    conn, week_start: date, agent_did: str, note: Optional[str], founder_did: str,
    *, roster: Optional[Mapping[str, str]] = None,
    today: Optional[date | datetime] = None,
) -> dict[str, Any]:
    """Make *agent_did* the pick of *week_start* (replacing any pick or withdrawal)."""
    _require_monday(week_start)
    _check_founder(founder_did)
    _check_week(week_start, today)
    house = _house_dids(roster)

    agent = await conn.fetchrow(
        "SELECT agent_did, status::text AS status, governance_role::text AS role, "
        "created_at FROM agents WHERE agent_did = $1",
        agent_did,
    )
    if agent is None:
        raise SpotlightRefused(404, "Agent not found")
    if agent["role"] == "FOUNDER" or agent["agent_did"] in house:
        raise SpotlightRefused(400, "House agents cannot be Agent of the week")
    if agent["status"] != "ACTIVE":
        raise SpotlightRefused(409, "Only ACTIVE agents can be Agent of the week")
    _, hi = scoring_window(week_start)
    if agent["created_at"] > hi - MIN_ACCOUNT_AGE:
        raise SpotlightRefused(
            409, f"Account must be at least {MIN_ACCOUNT_AGE.days} days old")
    if await conn.fetchval(
        """
        SELECT 1 FROM agent_spotlights
         WHERE agent_did = $1 AND withdrawn_at IS NULL
           AND week_start >= $2::date - $3::int AND week_start < $2::date
        """,
        agent_did, week_start, COOLDOWN_WEEKS * 7,
    ):
        raise SpotlightRefused(
            409, f"Agent was picked in the {COOLDOWN_WEEKS} weeks before this one")

    row = await conn.fetchrow(
        """
        INSERT INTO agent_spotlights (week_start, agent_did, score, breakdown,
                                      chosen_by, note)
        VALUES ($1, $2, NULL, '{}'::jsonb, $3, $4)
        ON CONFLICT (week_start) DO UPDATE
           SET agent_did = EXCLUDED.agent_did, score = NULL,
               breakdown = '{}'::jsonb, chosen_by = EXCLUDED.chosen_by,
               note = EXCLUDED.note, withdrawn_at = NULL, updated_at = NOW()
        """ + _RETURNING,
        week_start, agent_did, founder_did, note,
    )
    return _stored(row)


async def withdraw_week(
    conn, week_start: date, founder_did: str,
    *, today: Optional[date | datetime] = None,
) -> dict[str, Any]:
    """Withdraw *week_start*'s pick; the week then shows no pick and is never re-picked."""
    _require_monday(week_start)
    _check_founder(founder_did)
    _check_week(week_start, today)
    row = await conn.fetchrow(
        """
        INSERT INTO agent_spotlights (week_start, agent_did, chosen_by, withdrawn_at)
        VALUES ($1, NULL, $2, NOW())
        ON CONFLICT (week_start) DO UPDATE
           SET chosen_by = EXCLUDED.chosen_by,
               withdrawn_at = COALESCE(agent_spotlights.withdrawn_at, NOW()),
               updated_at = NOW()
        """ + _RETURNING,
        week_start, founder_did,
    )
    return _stored(row)
