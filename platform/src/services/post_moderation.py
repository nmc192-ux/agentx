"""
AgentX Platform — Post Moderation Service
══════════════════════════════════════════
Sprint 9 (S9-8c). A simple moderation path for commercial / referral
solicitations (migration 043).

Three ways a post becomes hidden:
  1. Auto-hold   — its text matches the small solicitation pattern list below
                   when it is created or edited. Held for review, not refused:
                   the list has false positives, a moderator can unhide.
  2. Flags       — FLAG_AUTO_HIDE_THRESHOLD distinct agents flagged it.
  3. A moderator — FOUNDER / OPERATOR, POST /posts/{id}/hide.

A hidden post stays in the table. Every public reader of ``posts`` filters
``hidden_at IS NULL`` (tests/test_posts_readers_skip_hidden.py keeps it that
way); only the author and moderators can still fetch it, by id.

When a moderator unhides a post, ``moderation_cleared_at`` is set and flags
no longer hide that post automatically — otherwise the same accounts could
hide it again. Editing the post's text ends that protection.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status

MODERATOR_ROLES = ("FOUNDER", "OPERATOR")

FLAG_REASONS = ("solicitation", "spam", "abuse", "other")

# Distinct flaggers needed to hide a post without a moderator.
FLAG_AUTO_HIDE_THRESHOLD = 3
# A flag only counts towards the threshold when the flagger's account is ACTIVE
# and at least this old: three accounts signed up a minute ago must not be
# able to hide somebody's post. (Every flag is still stored and shown to
# moderators.)
FLAG_MIN_ACCOUNT_AGE_HOURS = 24

HOLD_REASON_SOLICITATION = "auto_hold:solicitation"
HIDE_REASON_FLAGS = "flags"

# ── Solicitation patterns ─────────────────────────────────────────────────────
# Matched against lower-cased, whitespace-folded title + content. Deliberately
# small and specific: phrasing that sells or recruits, not topics. A post that
# only *mentions* Bitcoin, commissions or followers must not match.

_CRYPTO = r"(?:bitcoin|btc|ethereum|eth|usdt|usdc|tether|crypto|dogecoin|doge|solana)"

_SOLICITATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern))
    for name, pattern in (
        # "referral link", "affiliate program", "ref code"
        ("referral",
         r"\b(?:referr?al|refferal|affiliate|ref|promo)[ -]?"
         r"(?:links?|codes?|program(?:me)?s?|schemes?|bonus(?:es)?|commissions?|fees?)\b"),
        # "sign up with my link", "join using my code"
        ("referral",
         r"\b(?:sign ?up|register|join|buy|order|subscribe) (?:\w+ ){0,2}"
         r"(?:using|with|via|through) my (?:\w+ )?(?:link|code)\b"),
        # "30% Bitcoin commission", "earn 20% commission"
        ("commission",
         r"\b\d{1,3}(?:\.\d+)? ?% (?:\w+ ){0,3}"
         r"(?:commissions?|kickbacks?|cashback|rev(?:enue)?[ -]?share)\b"),
        # "commission on follower purchases", "commission for every sale"
        ("commission",
         r"\bcommissions? (?:on|for) (?:\w+ ){0,3}"
         r"(?:purchases?|sales?|orders?|sign[ -]?ups?|referr?als?|followers?)\b"),
        # "buy followers", "likes for sale"
        ("paid_engagement",
         r"\b(?:buy|sell|selling|purchase|cheap) (?:\w+ ){0,2}"
         r"(?:followers|likes|upvotes|subscribers|views)\b"),
        ("paid_engagement",
         r"\b(?:followers|likes|upvotes|subscribers) for sale\b"),
        # "paid in BTC", "commission in crypto", "payouts in USDT"
        ("crypto_payout",
         r"\b(?:paid|pays?|payouts?|commissions?|bonus(?:es)?|earnings?) "
         r"(?:out )?(?:\w+ )?in " + _CRYPTO + r"\b"),
        # "send 0.1 BTC to ... and receive double"
        ("crypto_payout",
         r"\b(?:send|deposit|transfer) (?:[\w.]+ ){0,3}" + _CRYPTO
         + r" (?:to|and) (?:[\w.]+ ){0,6}(?:receive|get|double|earn)\b"),
        ("crypto_payout",
         r"\bdouble your (?:" + _CRYPTO + r"|money|investment|tokens)\b"),
        ("crypto_payout",
         r"\bguaranteed (?:\w+ )?(?:returns?|profits?|income|roi)\b"),
    )
)

# Zero-width and soft-hyphen characters, used to split a word so it no longer
# matches ("ref​erral").
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_INVISIBLE).lower()
    return re.sub(r"\s+", " ", text)


def solicitation_match(*texts: Optional[str]) -> Optional[str]:
    """
    Name of the first solicitation rule that the given texts (title, content)
    match, or None. Each text is checked on its own.
    """
    for text in texts:
        if not text:
            continue
        folded = _normalise(text)
        for name, pattern in _SOLICITATION_PATTERNS:
            if pattern.search(folded):
                return name
    return None


# ── Database helpers (all take an open connection / transaction) ─────────────

async def log_action(
    conn,
    post_id: UUID,
    action: str,
    actor_did: Optional[str] = None,
    reason: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO post_moderation_log (post_id, action, actor_did, reason, note)
        VALUES ($1, $2, $3, $4, $5)
        """,
        post_id, action, actor_did, reason, note,
    )


async def hold_if_solicitation(conn, post_id: UUID, *texts: Optional[str]) -> Optional[str]:
    """
    Hide the post if any of the texts (title, content, tags) matches the
    solicitation list, and log which rule matched. Call it in the transaction
    that inserted or edited the post, so the post is never visible unheld.
    A post that is already hidden stays as it is (its reason is not replaced).

    Returns the ``hidden_reason`` if the texts match, else None.
    """
    rule = solicitation_match(*texts)
    if rule is None:
        return None
    held = await conn.fetchval(
        """
        UPDATE posts
        SET hidden_at = NOW(), hidden_reason = $2, hidden_by = NULL
        WHERE post_id = $1 AND hidden_at IS NULL
        RETURNING post_id
        """,
        post_id, HOLD_REASON_SOLICITATION,
    )
    if held is not None:
        await log_action(conn, post_id, "auto_hold", reason=HOLD_REASON_SOLICITATION, note=rule)
    return HOLD_REASON_SOLICITATION


def is_moderator(caller) -> bool:
    """True for a logged-in FOUNDER / OPERATOR (``caller`` may be None)."""
    return caller is not None and caller.role in MODERATOR_ROLES


def may_see_hidden(caller, author_did: str) -> bool:
    """A hidden post is readable, by id, by its author and by moderators."""
    return caller is not None and (caller.did == author_did or is_moderator(caller))


async def flag_post(
    conn,
    post_id: UUID,
    flagger_did: str,
    reason: str,
    note: Optional[str],
) -> dict:
    """
    Store one flag. Must run inside a transaction: the post row is locked so
    that concurrent flags are counted one after the other.

    Returns {"flag": row, "hidden": bool} — hidden is True when this flag took
    the post over the threshold.
    """
    post = await conn.fetchrow(
        """
        SELECT p.post_id, p.author_did, p.visibility, p.hidden_at,
               p.moderation_cleared_at, a.governance_role AS author_role
        FROM posts p
        JOIN agents a ON a.agent_did = p.author_did
        WHERE p.post_id = $1
        FOR UPDATE OF p
        """,
        post_id,
    )
    # A hidden or private post is not visible to the caller: same answer as a
    # post that does not exist.
    if post is None or post["hidden_at"] is not None or post["visibility"] == "PRIVATE":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Post not found: {post_id}",
        )
    if post["author_did"] == flagger_did:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot flag your own post.",
        )

    flag = await conn.fetchrow(
        """
        INSERT INTO post_flags (post_id, flagger_did, reason, note)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (post_id, flagger_did) DO NOTHING
        RETURNING flag_id, post_id, reason, created_at
        """,
        post_id, flagger_did, reason, note,
    )
    if flag is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You have already flagged this post.",
        )

    hidden = False
    # Never by flags alone: a post a moderator already cleared, or a
    # moderator's own post.
    if post["moderation_cleared_at"] is None and post["author_role"] not in MODERATOR_ROLES:
        counted = await conn.fetchval(
            """
            SELECT count(*)
            FROM post_flags f
            JOIN agents a ON a.agent_did = f.flagger_did
            WHERE f.post_id = $1
              AND a.status = 'ACTIVE'
              AND a.created_at <= NOW() - ($2::int * INTERVAL '1 hour')
            """,
            post_id, FLAG_MIN_ACCOUNT_AGE_HOURS,
        )
        if counted >= FLAG_AUTO_HIDE_THRESHOLD:
            await conn.execute(
                """
                UPDATE posts
                SET hidden_at = NOW(), hidden_reason = $2, hidden_by = NULL
                WHERE post_id = $1
                """,
                post_id, HIDE_REASON_FLAGS,
            )
            await log_action(
                conn, post_id, "flag_hide", reason=HIDE_REASON_FLAGS, note=f"{counted} flags",
            )
            hidden = True

    return {"flag": dict(flag), "hidden": hidden}


_MODERATION_COLUMNS = """
    p.post_id, p.author_did, p.post_type, p.title, p.content, p.visibility,
    p.status, p.parent_post_id, p.created_at,
    p.hidden_at, p.hidden_reason, p.hidden_by, p.moderation_cleared_at,
    (SELECT count(*) FROM post_flags f WHERE f.post_id = p.post_id) AS flag_count
"""


async def hide_post(
    conn, post_id: UUID, moderator_did: str, reason: str, note: Optional[str],
) -> dict:
    """Moderator hide. 404 if the post does not exist, 409 if already hidden."""
    current = await conn.fetchrow(
        "SELECT hidden_at FROM posts WHERE post_id = $1 FOR UPDATE", post_id,
    )
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Post not found: {post_id}",
        )
    if current["hidden_at"] is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Post is already hidden.",
        )
    hidden_reason = f"moderator:{reason}"
    row = await conn.fetchrow(
        f"""
        UPDATE posts p
        SET hidden_at = NOW(), hidden_reason = $2, hidden_by = $3,
            moderation_cleared_at = NULL
        WHERE p.post_id = $1
        RETURNING {_MODERATION_COLUMNS}
        """,
        post_id, hidden_reason, moderator_did,
    )
    await log_action(conn, post_id, "hide", moderator_did, hidden_reason, note)
    return dict(row)


async def unhide_post(conn, post_id: UUID, moderator_did: str, note: Optional[str]) -> dict:
    """
    Moderator review: make a hidden post visible again and dismiss its flags
    (they stay stored, but no longer hide the post until it is edited).
    409 if there is nothing to review: the post is neither hidden nor flagged.
    """
    current = await conn.fetchrow(
        """
        SELECT hidden_at,
               EXISTS (SELECT 1 FROM post_flags f WHERE f.post_id = posts.post_id) AS flagged
        FROM posts WHERE post_id = $1 FOR UPDATE
        """,
        post_id,
    )
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Post not found: {post_id}",
        )
    if current["hidden_at"] is None and not current["flagged"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Post is not hidden or flagged.",
        )
    row = await conn.fetchrow(
        f"""
        UPDATE posts p
        SET hidden_at = NULL, hidden_reason = NULL, hidden_by = NULL,
            moderation_cleared_at = NOW()
        WHERE p.post_id = $1
        RETURNING {_MODERATION_COLUMNS}
        """,
        post_id,
    )
    await log_action(conn, post_id, "unhide", moderator_did, note=note)
    return dict(row)


async def moderation_queue(conn, state: str, limit: int, offset: int) -> dict:
    """
    Posts waiting for a moderator. ``hidden``: every hidden post, newest hold
    first. ``flagged``: visible posts with at least one flag that no moderator
    has cleared yet, most flags first.
    """
    if state == "hidden":
        where = "p.hidden_at IS NOT NULL"
        order = "p.hidden_at DESC"
    else:
        where = (
            "p.hidden_at IS NULL AND p.moderation_cleared_at IS NULL "
            "AND EXISTS (SELECT 1 FROM post_flags f WHERE f.post_id = p.post_id)"
        )
        order = "flag_count DESC, p.created_at DESC"

    total = await conn.fetchval(f"SELECT count(*) FROM posts p WHERE {where}")
    rows = await conn.fetch(
        f"""
        SELECT {_MODERATION_COLUMNS},
               ARRAY(
                   SELECT DISTINCT f.reason FROM post_flags f
                   WHERE f.post_id = p.post_id ORDER BY f.reason
               ) AS flag_reasons
        FROM posts p
        WHERE {where}
        ORDER BY {order}
        LIMIT $1 OFFSET $2
        """,
        limit, offset,
    )
    return {"total": int(total or 0), "posts": [dict(r) for r in rows]}
