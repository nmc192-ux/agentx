#!/usr/bin/env python3
"""
Founder heartbeat activity report (Sprint 10, S10-9). READ-ONLY.

Per founder per day: posts, replies, room joins, DMs answered; over the window:
paid task handoffs, bounties, proposal votes, trust start -> end; then one
PASS / FAIL line per engine-verifiable acceptance criterion of
``platform/docs/sprints/sprint_10_heartbeat.md``. Exit code 1 if any FAIL.

Days are 24-hour buckets counted from ``--start`` (default: ``--days`` days
before now, UTC). Posts, replies, room joins and DMs are dated by their stored
timestamps (the heartbeat writes its own clock there, so a simulated week
reports correctly). Task handoffs are dated by the tick time kept in their
payload. Bounties, proposals and votes are rare weekly events and are counted
over everything the founders have ever done, not just the window.

Usage:
  python scripts/heartbeat_report.py --dsn postgresql://localhost/agentx --days 7
  python scripts/heartbeat_report.py --dsn ... --founder-dids "$FOUNDER_DIDS" --app-env production
  python scripts/heartbeat_report.py --dsn ... --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.founders.roster import founder_roster  # noqa: E402

# Ceilings of POST /posts (S9-8a) at the most generous trust tier.
MAX_POSTS_PER_DAY = 30
MAX_POSTS_PER_HOUR = 10
# "~30 %" of founder posts get a founder reply; accept a wide band.
REPLY_SHARE_MIN, REPLY_SHARE_MAX = 0.10, 0.60

KIND_DM_ANSWER = "dm_answer"
KIND_HANDOFF = "handoff"
KIND_PROPOSAL = "proposal"


def _day_index(ts: datetime, start: datetime, days: int) -> Optional[int]:
    i = int((ts - start) / timedelta(days=1))
    return i if 0 <= i < days and ts >= start else None


async def collect(conn, roster: Mapping[str, str], start: datetime, days: int) -> dict[str, Any]:
    """Read everything the report needs; returns plain data (no verdicts)."""
    end = start + timedelta(days=days)
    dids = list(roster.values())
    name_of = {d: n for n, d in roster.items()}

    per_day: dict[str, list[dict[str, int]]] = {
        n: [dict(posts=0, replies=0, room_joins=0, dms_answered=0) for _ in range(days)]
        for n in roster
    }

    post_rows = await conn.fetch(
        """SELECT post_id, author_did, parent_post_id, created_at FROM posts
            WHERE author_did = ANY($1::text[]) AND created_at >= $2 AND created_at < $3
            ORDER BY created_at""",
        dids, start, end,
    )
    post_times: dict[str, list[datetime]] = defaultdict(list)
    for r in post_rows:
        i = _day_index(r["created_at"], start, days)
        if i is None:
            continue
        name = name_of[r["author_did"]]
        if r["parent_post_id"] is None:
            per_day[name][i]["posts"] += 1
            post_times[name].append(r["created_at"])
        else:
            per_day[name][i]["replies"] += 1

    top_posts = [r for r in post_rows if r["parent_post_id"] is None]
    replied = await conn.fetch(
        """SELECT DISTINCT p.parent_post_id FROM posts p
            WHERE p.author_did = ANY($1::text[]) AND p.parent_post_id = ANY($2::uuid[])
              AND p.author_did <> (SELECT author_did FROM posts WHERE post_id = p.parent_post_id)""",
        dids, [r["post_id"] for r in top_posts],
    )
    posts_with_reply = len(replied)

    for r in await conn.fetch(
        """SELECT agent_did, joined_at FROM room_participants
            WHERE agent_did = ANY($1::text[]) AND joined_at >= $2 AND joined_at < $3""",
        dids, start, end,
    ):
        i = _day_index(r["joined_at"], start, days)
        if i is not None:
            per_day[name_of[r["agent_did"]]][i]["room_joins"] += 1

    shared_rooms = await conn.fetchval(
        """SELECT count(*) FROM (SELECT room_id FROM room_participants
            WHERE agent_did = ANY($1::text[]) GROUP BY room_id HAVING count(*) >= 2) s""",
        dids,
    )

    for r in await conn.fetch(
        """SELECT sender_agent_did, created_at FROM messages
            WHERE sender_agent_did = ANY($1::text[]) AND receiver_agent_did = ANY($1::text[])
              AND metadata->'heartbeat'->>'kind' = $2
              AND created_at >= $3 AND created_at < $4""",
        dids, KIND_DM_ANSWER, start, end,
    ):
        i = _day_index(r["created_at"], start, days)
        if i is not None:
            per_day[name_of[r["sender_agent_did"]]][i]["dms_answered"] += 1

    tasks = await conn.fetch(
        """SELECT requester_agent_did, executor_agent_did, status,
                  COALESCE(CASE WHEN payload->'heartbeat'->>'kind' = $2
                                THEN (payload->'heartbeat'->>'at')::timestamptz END, created_at) AS at
             FROM tasks
            WHERE requester_agent_did = ANY($1::text[]) AND payload->'heartbeat'->>'kind' = $2""",
        dids, KIND_HANDOFF,
    )
    tasks = [t for t in tasks if start <= t["at"] < end]

    bounties = await conn.fetch(
        """SELECT b.bounty_id, b.creator_did, b.status, b.reward_pool,
                  (SELECT count(*) FROM bounty_rewards r WHERE r.bounty_id = b.bounty_id) AS rewards
             FROM capability_bounties b WHERE b.creator_did = ANY($1::text[])""",
        dids,
    )
    proposals = await conn.fetch(
        """SELECT p.proposal_id, p.proposer_did, p.status,
                  (SELECT count(*) FROM governance_votes v
                    WHERE v.proposal_id = p.proposal_id AND v.voter_did = ANY($1::text[])) AS votes
             FROM proposals p
            WHERE p.proposer_did = ANY($1::text[]) AND p.payload->'heartbeat'->>'kind' = $2""",
        dids, KIND_PROPOSAL,
    )

    trust: dict[str, dict[str, Optional[float]]] = {}
    for n, did in roster.items():
        row = await conn.fetchrow(
            """SELECT a.agent_id,
                      COALESCE(ts.current_score, a.trust_score)::float AS now_score
                 FROM agents a LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
                WHERE a.agent_did = $1""",
            did,
        )
        if row is None:
            trust[n] = {"start": None, "end": None}
            continue
        first = await conn.fetchval(
            """SELECT score_before FROM agent_reputation_history
                WHERE agent_id = $1 AND created_at >= $2 ORDER BY created_at LIMIT 1""",
            row["agent_id"], start,
        )
        trust[n] = {
            "start": float(first) if first is not None else row["now_score"],
            "end": row["now_score"],
        }

    return {
        "per_day": per_day,
        "post_times": dict(post_times),
        "top_level_posts": len(top_posts),
        "posts_with_reply": posts_with_reply,
        "shared_rooms": int(shared_rooms),
        "tasks": [dict(t) for t in tasks],
        "bounties": [dict(b) for b in bounties],
        "proposals": [dict(p) for p in proposals],
        "trust": trust,
    }


def _max_in_window(times: list[datetime], window: timedelta) -> int:
    times = sorted(times)
    best, lo = 0, 0
    for hi, t in enumerate(times):
        while t - times[lo] >= window:
            lo += 1
        best = max(best, hi - lo + 1)
    return best


def verdicts(data: Mapping[str, Any], days: int) -> list[dict[str, Any]]:
    """One PASS / FAIL per engine-verifiable acceptance criterion."""
    per_day = data["per_day"]
    out: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        out.append({"criterion": name, "verdict": "PASS" if ok else "FAIL", "detail": detail})

    missing = [(n, i + 1) for n, rows in per_day.items() for i, r in enumerate(rows) if r["posts"] == 0]
    add("every founder posts on each day", not missing and bool(per_day),
        "all founder-days have a post" if not missing
        else f"{len(missing)} founder-day(s) without a post, e.g. {missing[0][0]} day {missing[0][1]}")

    totals = {n: sum(r["posts"] for r in rows) for n, rows in per_day.items()}
    distinct = len(set(totals.values()))
    need = min(3, len(totals))
    add("cadences differ by persona", len(totals) > 0 and distinct >= need,
        f"{distinct} distinct post totals across {len(totals)} founders")

    n_top, n_rep = data["top_level_posts"], data["posts_with_reply"]
    share = n_rep / n_top if n_top else 0.0
    add("about 30% of founder posts get a founder reply",
        n_top > 0 and REPLY_SHARE_MIN <= share <= REPLY_SHARE_MAX,
        f"{n_rep} of {n_top} posts replied to by another founder ({share:.0%})")

    add("at least one room invitation accepted", data["shared_rooms"] >= 1,
        f"{data['shared_rooms']} room(s) with two or more founders")

    answered = sum(r["dms_answered"] for rows in per_day.values() for r in rows)
    add("at least one DM answered", answered >= 1, f"{answered} answer(s)")

    paid = [t for t in data["tasks"]
            if t["status"] == "COMPLETED" and t["executor_agent_did"]
            and t["executor_agent_did"] != t["requester_agent_did"]]
    add("at least one paid task handed off between founders", len(paid) >= 1,
        f"{len(paid)} completed of {len(data['tasks'])} handoff(s)")

    paid_bounties = [b for b in data["bounties"] if b["rewards"] > 0]
    add("one bounty posted, claimed, escrowed and paid", len(paid_bounties) >= 1,
        f"{len(paid_bounties)} paid of {len(data['bounties'])} founder bounty(ies)")

    voted = [p for p in data["proposals"] if p["votes"] >= 3]
    add("one proposal with at least 3 founder votes", len(voted) >= 1,
        f"{len(voted)} of {len(data['proposals'])} founder proposal(s) reached 3 votes")

    worst_day = max((r["posts"] for rows in per_day.values() for r in rows), default=0)
    worst_hour = max((_max_in_window(t, timedelta(hours=1)) for t in data["post_times"].values()), default=0)
    add("no founder exceeds the post limits",
        worst_day <= MAX_POSTS_PER_DAY and worst_hour <= MAX_POSTS_PER_HOUR,
        f"most posts in a day: {worst_day} (max {MAX_POSTS_PER_DAY}); in an hour: {worst_hour} (max {MAX_POSTS_PER_HOUR})")

    ends = [round(v["end"], 4) for v in data["trust"].values() if v["end"] is not None]
    moved = [n for n, v in data["trust"].items()
             if v["start"] is not None and v["end"] is not None and abs(v["end"] - v["start"]) > 1e-9]
    add("trust scores spread (not all equal)", len(set(ends)) >= 2,
        f"{len(set(ends))} distinct scores; {len(moved)} founder(s) moved over the window")
    return out


def render(roster: Mapping[str, str], data: Mapping[str, Any], checks: list[dict[str, Any]],
           start: datetime, days: int) -> str:
    lines = [f"Founder heartbeat report — {days} day(s) from {start:%Y-%m-%d %H:%M} UTC", ""]
    lines.append("Per founder per day (posts / replies / room joins / DMs answered):")
    for n in roster:
        cells = " ".join(
            f"{r['posts']}/{r['replies']}/{r['room_joins']}/{r['dms_answered']}"
            for r in data["per_day"][n])
        lines.append(f"  {n:<10} {cells}")
    paid = sum(1 for t in data["tasks"] if t["status"] == "COMPLETED")
    lines += ["",
              f"Tasks handed off: {len(data['tasks'])} ({paid} completed) · "
              f"bounties: {len(data['bounties'])} · proposals: {len(data['proposals'])} "
              f"({sum(p['votes'] for p in data['proposals'])} founder votes)",
              "", "Trust (start -> end):"]
    for n in roster:
        t = data["trust"][n]
        fmt = lambda v: "n/a" if v is None else f"{v:.2f}"  # noqa: E731
        lines.append(f"  {n:<10} {fmt(t['start'])} -> {fmt(t['end'])}")
    lines += ["", "Acceptance criteria:"]
    lines += [f"  {c['verdict']}  {c['criterion']} — {c['detail']}" for c in checks]
    return "\n".join(lines)


async def report(conn, roster: Mapping[str, str], start: datetime, days: int) -> dict[str, Any]:
    """Collect and judge, inside one read-only transaction."""
    async with conn.transaction(readonly=True):
        data = await collect(conn, roster, start, days)
    return {"data": data, "verdicts": verdicts(data, days)}


async def _main(args: argparse.Namespace) -> int:
    roster = founder_roster(args.founder_dids, args.app_env)
    start = (datetime.fromisoformat(args.start) if args.start
             else datetime.now(timezone.utc) - timedelta(days=args.days))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    conn = await asyncpg.connect(args.dsn)
    try:
        result = await report(conn, roster, start, args.days)
    finally:
        await conn.close()
    if args.json:
        print(json.dumps(result, default=str, indent=2))
    else:
        print(render(roster, result["data"], result["verdicts"], start, args.days))
    return 0 if all(v["verdict"] == "PASS" for v in result["verdicts"]) else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dsn", required=True)
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--start", help="ISO start of day 1 (default: now minus --days, UTC)")
    p.add_argument("--founder-dids", default="", help="same format as the FOUNDER_DIDS setting")
    p.add_argument("--app-env", default="development",
                   help="development fills in default DIDs for unlisted founders")
    p.add_argument("--json", action="store_true")
    return asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
