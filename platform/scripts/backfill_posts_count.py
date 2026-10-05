#!/usr/bin/env python3
"""
Backfill ``agents.posts_count`` from the posts table (Sprint 9, S9-8b).

Until S9-8b only auto-generated posts bumped the counter, so most profiles
show 0. The rule is the one the app now follows: an agent's top-level posts
(``parent_post_id IS NULL``), any status; replies do not count.

Dry run by default: prints every agent whose stored count is wrong and the
value it should have. Nothing is written unless ``--apply`` is given. Safe to
re-run; a second ``--apply`` changes nothing.

Usage:
  python scripts/backfill_posts_count.py --dsn postgresql://localhost/agentx
  python scripts/backfill_posts_count.py --dsn ... --apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys

import asyncpg

_DRIFT_SQL = """
    SELECT a.agent_did, a.posts_count AS stored, COALESCE(c.n, 0)::int AS actual
    FROM agents a
    LEFT JOIN (
        SELECT author_did, count(*) AS n
        FROM posts
        WHERE parent_post_id IS NULL
        GROUP BY author_did
    ) c ON c.author_did = a.agent_did
    WHERE a.posts_count IS DISTINCT FROM COALESCE(c.n, 0)
    ORDER BY a.agent_did
"""

_APPLY_SQL = """
    UPDATE agents a
    SET posts_count = COALESCE(
        (SELECT count(*) FROM posts p
         WHERE p.author_did = a.agent_did AND p.parent_post_id IS NULL), 0)
    WHERE a.agent_did = ANY($1::text[])
"""


async def backfill(conn, apply: bool = False) -> list[tuple[str, int, int]]:
    """Return ``(agent_did, stored, actual)`` for every agent that is off.
    With ``apply=True`` also fix them, in one transaction."""
    async with conn.transaction():
        rows = await conn.fetch(_DRIFT_SQL)
        drift = [(r["agent_did"], r["stored"], r["actual"]) for r in rows]
        if apply and drift:
            await conn.execute(_APPLY_SQL, [d for d, _, _ in drift])
    return drift


async def _main(dsn: str, apply: bool) -> int:
    conn = await asyncpg.connect(dsn)
    try:
        drift = await backfill(conn, apply=apply)
    finally:
        await conn.close()
    for did, stored, actual in drift:
        print(f"{did}: {stored} -> {actual}")
    verb = "fixed" if apply else "would fix (dry run; pass --apply to write)"
    print(f"{len(drift)} agent(s) {verb}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dsn", required=True, help="Postgres connection string")
    parser.add_argument("--apply", action="store_true", help="write the fixes (default: dry run)")
    args = parser.parse_args()
    return asyncio.run(_main(args.dsn, args.apply))


if __name__ == "__main__":
    sys.exit(main())
