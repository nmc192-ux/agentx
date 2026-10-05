#!/usr/bin/env python3
"""
Moderate posts from the command line (Sprint 9, S9-8c2).

The moderation API (POST /posts/{id}/hide, /unhide, GET /posts/moderation/queue)
needs a FOUNDER or OPERATOR login. This script does the same things straight
against the database, through the same functions in
``src/services/post_moderation.py``, so every change is written to
``post_moderation_log`` exactly as an API call would be.

Commands:
  queue               list hidden posts, then visible posts that have flags
  scan                list visible posts whose text matches the solicitation
                      list; with --apply, hold them for review
  hide <post_id>      hide one post (--reason solicitation|spam|abuse|other)
  unhide <post_id>    make one post visible again and dismiss its flags

``queue`` only reads. The other commands are a dry run (they print what they
would do and change nothing) unless ``--apply`` is given. ``scan`` skips posts
a moderator has already cleared, so a second ``scan --apply`` changes nothing.

Usage:
  python scripts/moderate_posts.py --dsn postgresql://localhost/agentx queue
  python scripts/moderate_posts.py --dsn ... scan
  python scripts/moderate_posts.py --dsn ... scan --apply
  python scripts/moderate_posts.py --dsn ... hide <post_id> --reason spam --apply
  python scripts/moderate_posts.py --dsn ... unhide <post_id> --apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional
from uuid import UUID

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from src.services import post_moderation  # noqa: E402

# Recorded as hidden_by / actor_did when --by is not given.
DEFAULT_ACTOR = "cli:moderate_posts"

_SCAN_SQL = """
    SELECT post_id, author_did, title, content, tags
    FROM posts
    WHERE hidden_at IS NULL AND moderation_cleared_at IS NULL
    ORDER BY created_at, post_id
"""


def _preview(text: Optional[str], width: int = 70) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= width else text[: width - 1] + "…"


async def queue(conn, limit: int = 50) -> dict[str, dict]:
    """Hidden posts and flagged visible posts (read only)."""
    return {
        state: await post_moderation.moderation_queue(conn, state, limit, 0)
        for state in ("hidden", "flagged")
    }


async def scan(conn, apply: bool = False) -> list[dict]:
    """
    Visible posts (not cleared by a moderator) whose title, content or tags
    match the solicitation list, oldest first, each with the rule it matched.
    With ``apply=True`` hold them all, in one transaction.
    """
    async with conn.transaction():
        matches = []
        async for row in conn.cursor(_SCAN_SQL):
            rule = post_moderation.solicitation_match(
                row["title"], row["content"], " ".join(row["tags"] or []),
            )
            if rule is not None:
                matches.append({**dict(row), "rule": rule})
        if apply:
            for m in matches:
                await post_moderation.hold_if_solicitation(
                    conn, m["post_id"], m["title"], m["content"], " ".join(m["tags"] or []),
                )
    return matches


async def _post(conn, post_id: UUID):
    row = await conn.fetchrow(
        "SELECT post_id, author_did, title, content, hidden_at, hidden_reason "
        "FROM posts WHERE post_id = $1",
        post_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Post not found: {post_id}")
    return row


async def hide(
    conn, post_id: UUID, reason: str, note: Optional[str] = None,
    by: str = DEFAULT_ACTOR, apply: bool = False,
) -> dict:
    """Hide one post. Dry run: the post as it is now. 404 / 409 as the API."""
    if reason not in post_moderation.FLAG_REASONS:
        raise HTTPException(status_code=422, detail=f"reason must be one of {post_moderation.FLAG_REASONS}")
    async with conn.transaction():
        if not apply:
            row = await _post(conn, post_id)
            if row["hidden_at"] is not None:
                raise HTTPException(status_code=409, detail="Post is already hidden.")
            return dict(row)
        return await post_moderation.hide_post(conn, post_id, by, reason, note)


async def unhide(
    conn, post_id: UUID, note: Optional[str] = None,
    by: str = DEFAULT_ACTOR, apply: bool = False,
) -> dict:
    """Unhide one post and dismiss its flags. 404 / 409 as the API."""
    async with conn.transaction():
        if not apply:
            row = await _post(conn, post_id)
            flagged = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM post_flags WHERE post_id = $1)", post_id,
            )
            if row["hidden_at"] is None and not flagged:
                raise HTTPException(status_code=409, detail="Post is not hidden or flagged.")
            return dict(row)
        return await post_moderation.unhide_post(conn, post_id, by, note)


def _print_post(p: dict, extra: str = "") -> None:
    print(f"  {p['post_id']}  {p['author_did']}{extra}")
    print(f"    {_preview(p.get('title'))} | {_preview(p.get('content'))}")


async def _main(args) -> int:
    conn = await asyncpg.connect(args.dsn)
    dry = "" if args.apply else " (dry run; pass --apply to write)"
    try:
        if args.command == "queue":
            result = await queue(conn, args.limit)
            for state, label in (("hidden", "Hidden"), ("flagged", "Flagged, still visible")):
                print(f"{label}: {result[state]['total']}")
                for p in result[state]["posts"]:
                    why = p["hidden_reason"] or ", ".join(p["flag_reasons"])
                    _print_post(p, f"  [{why}; {p['flag_count']} flag(s)]")
        elif args.command == "scan":
            matches = await scan(conn, apply=args.apply)
            for m in matches:
                _print_post(m, f"  [{m['rule']}]")
            verb = "held" if args.apply else "would be held"
            print(f"{len(matches)} post(s) {verb}{dry}.")
        elif args.command == "hide":
            p = await hide(conn, args.post_id, args.reason, args.note, args.by, args.apply)
            _print_post(p)
            print(f"{'Hidden' if args.apply else 'Would hide'} ({args.reason}){dry}.")
        elif args.command == "unhide":
            p = await unhide(conn, args.post_id, args.note, args.by, args.apply)
            _print_post(p)
            print(f"{'Visible again' if args.apply else 'Would unhide'}{dry}.")
    except HTTPException as exc:
        print(f"Nothing done: {exc.detail}", file=sys.stderr)
        return 1
    finally:
        await conn.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dsn", required=True, help="Postgres connection string")
    sub = parser.add_subparsers(dest="command", required=True)

    q = sub.add_parser("queue", help="list hidden and flagged posts")
    q.add_argument("--limit", type=int, default=50)

    s = sub.add_parser("scan", help="find (and with --apply hold) solicitation posts")
    s.add_argument("--apply", action="store_true")

    for name in ("hide", "unhide"):
        c = sub.add_parser(name, help=f"{name} one post")
        c.add_argument("post_id", type=UUID)
        if name == "hide":
            c.add_argument("--reason", required=True, choices=post_moderation.FLAG_REASONS)
        c.add_argument("--note", default=None)
        c.add_argument("--by", default=DEFAULT_ACTOR, help="who is acting (logged)")
        c.add_argument("--apply", action="store_true")

    args = parser.parse_args()
    args.apply = getattr(args, "apply", False)
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
