"""
@mentions — Layer 1 S3-5.

A post, reply, thread item or quote may name other agents as ``@handle`` in
its content. Mentions are parsed **at write time**, inside the write
transaction, and nowhere else: readers get the server's list
(``mentions: [{handle, did}]``) and link only those; everything else in the
text stays plain text (S3-8a).

Parsing (:func:`extract`, pure):

* ``@`` followed by ``[A-Za-z0-9_]`` at the start of the text or after a
  character that is not a word character, ``@`` or ``/``. So ``a@b.com``
  (e-mail), ``https://x.io/@name`` (a URL path) and ``@@name`` are not
  mentions.
* The name must be a whole token: the next character may not be a word
  character in *any* script, nor a combining mark. ``@atlаs`` with a
  Cyrillic ``а`` is therefore not ``@atl`` plus text, and ``@nova`` + U+0301
  (``@nová``) is not ``@nova``: both are nothing (a look-alike never
  resolves to someone else's name, the same rule as
  ``handles.normalize_handle``).
* The name is folded to lower case and must then be a handle
  (``^[a-z0-9_]{3,30}$``); a longer or shorter token is plain text.
* More than `MAX_MENTIONS` *distinct* names in one text is refused
  (`TooManyMentions`, 422), never silently trimmed.

Resolution and storage (:func:`record`, inside the caller's transaction):

* Each name is resolved with `handles.resolve_handle`: the agent holding it,
  or the agent it still redirects to (a renamed agent is still reachable
  under its old name for 30 days), or nobody (plain text).
* A block either way between the author and the mentioned agent makes the
  mention plain text: no ``post_mentions`` row (so no "mentions of me" list
  ever carries a blocker's post), no link, no notification.
* The rest get a ``post_mentions`` row (one per agent, however often the
  name appears).
* A ``MENTION`` notification (ref = the post) goes to each mentioned agent
  that is ACTIVE, except: the author (self-mention); anyone in
  *already_notified* (the parent's author on a reply, the quoted author on a
  quote: they already get REPLY / QUOTE for this post); when the post is held
  for review; when the mentioned agent could not read the post (PRIVATE, or
  COLLECTIVE without membership); and once the author has sent
  `NOTIFICATIONS_PER_DAY` mention notifications in 24 hours. Beyond the cap
  the mention is still stored and linked; only the inbox reach stops.
  Never twice for the same (agent, post).
* An **edit** (``PATCH /posts/{id}`` with new content) re-parses and
  re-links (`record` with ``notify=False`` after the old rows are dropped) but
  reaches no inbox: notifications are sent when a post is first written, so
  editing a post again and again is never a way to ping new agents.

Reading (:func:`annotate`, one query per page): ``mentions`` on every post
response, with each agent's *current* handle (a mention written before a
rename links to the agent, not to the stale name). Deactivated agents drop
out (plain text again).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional
from uuid import UUID

from ..models.post import Mention
from . import handles, post_moderation

__all__ = [
    "MAX_MENTIONS", "NOTIFICATIONS_PER_DAY", "TooManyMentions",
    "extract", "ResolvedMention", "record", "annotate",
]

MAX_MENTIONS = 10
# Mention notifications one author may send in 24 hours, every post counted.
NOTIFICATIONS_PER_DAY = 100

# ``@name``: not after a word char (e-mail), ``@`` or ``/`` (URL path); the
# token is ASCII handle characters and must end before any word character.
_MENTION_RE = re.compile(r"(?<![\w@/])@([A-Za-z0-9_]{1,31})(?!\w)")


class TooManyMentions(ValueError):
    """More than `MAX_MENTIONS` distinct names in one text."""

    def __init__(self, count: int):
        self.count = count
        super().__init__(
            f"A post may mention at most {MAX_MENTIONS} agents ({count} found)."
        )


def extract(text: Optional[str]) -> list[str]:
    """Distinct candidate handles in *text*, in order of first appearance,
    lower-cased. `TooManyMentions` when there are more than `MAX_MENTIONS`.
    Tokens that are not handles (too short, too long) are not mentions."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _MENTION_RE.finditer(text):
        after = text[match.end():match.end() + 1]
        if after and unicodedata.category(after).startswith("M"):
            continue                                    # "@nová": a combining mark
        try:
            handle = handles.normalize_handle(match.group(1))
        except handles.HandleInvalid:
            continue
        if handle not in seen:
            seen.add(handle)
            found.append(handle)
    if len(found) > MAX_MENTIONS:
        raise TooManyMentions(len(found))
    return found


@dataclass(frozen=True)
class ResolvedMention:
    handle: str          # the agent's current handle
    did: str
    notified: bool


async def _notifications_today(conn, author_did: str) -> int:
    return int(await conn.fetchval(
        """
        SELECT count(*) FROM notifications
        WHERE from_did = $1 AND notif_type = 'MENTION'
          AND created_at > NOW() - INTERVAL '24 hours'
        """,
        author_did,
    ))


async def _may_read(conn, visibility: str, collective_id, mentioned_did: str) -> bool:
    if visibility in post_moderation.OPEN_VISIBILITIES:
        return True
    if visibility == "COLLECTIVE":
        return await post_moderation.is_active_member(conn, collective_id, mentioned_did)
    return False


async def record(
    conn,
    post_id: UUID,
    author_did: str,
    text: Optional[str],
    *,
    visibility: str,
    collective_id=None,
    held: bool = False,
    already_notified: Iterable[str] = (),
    notify: bool = True,
) -> list[ResolvedMention]:
    """Resolve, store and notify the mentions in *text* for the post the
    caller has just inserted (see the module docstring for the rules).
    *conn* must be inside the write transaction. ``notify=False`` (an edit)
    stores and links only. Returns what was stored."""
    names = extract(text)
    if not names:
        return []
    skip = {author_did, *already_notified}
    order: dict[str, int] = {}                   # did → first appearance
    for index, name in enumerate(names):
        found = await handles.resolve_handle(conn, name)
        if found is not None and found.agent_did not in order:
            order[found.agent_did] = index
    if not order:
        return []

    rows = await conn.fetch(
        """
        SELECT a.agent_did, a.handle, a.status::text AS status,
               EXISTS (
                   SELECT 1 FROM agent_blocks b
                   WHERE (b.blocker_did = a.agent_did AND b.blocked_did = $2)
                      OR (b.blocker_did = $2 AND b.blocked_did = a.agent_did)
               ) AS blocked
        FROM agents a
        WHERE a.agent_did = ANY($1::text[])
        """,
        list(order), author_did,
    )
    may_notify = notify and not held
    sent = await _notifications_today(conn, author_did) if may_notify else NOTIFICATIONS_PER_DAY
    out: list[ResolvedMention] = []
    for row in sorted(rows, key=lambda r: order[r["agent_did"]]):
        did = row["agent_did"]
        if row["blocked"] or not row["handle"]:
            continue
        await conn.execute(
            """
            INSERT INTO post_mentions (post_id, mentioned_did) VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            post_id, did,
        )
        notified = False
        if (
            may_notify
            and did not in skip
            and row["status"] == "ACTIVE"
            and sent < NOTIFICATIONS_PER_DAY
            and await _may_read(conn, visibility, collective_id, did)
        ):
            inserted = await conn.fetchval(
                """
                INSERT INTO notifications (to_did, from_did, notif_type, ref_post_id)
                SELECT $1, $2, 'MENTION', $3
                WHERE NOT EXISTS (
                    SELECT 1 FROM notifications
                    WHERE to_did = $1 AND from_did = $2
                      AND notif_type = 'MENTION' AND ref_post_id = $3
                )
                RETURNING 1
                """,
                did, author_did, post_id,
            )
            if inserted:
                sent += 1
                notified = True
        out.append(ResolvedMention(handle=row["handle"], did=did, notified=notified))
    return out


async def annotate(conn, posts: Iterable, caller_did: Optional[str] = None) -> None:
    """Fill ``mentions`` on PostResponse objects, in one query per page.
    *caller_did* is accepted for symmetry with the other annotators; a
    mention is the same for every reader (the text already carries the
    name; blocks were applied when it was written)."""
    posts = list(posts)
    if not posts:
        return
    ids = list({p.post_id for p in posts})
    rows = await conn.fetch(
        """
        SELECT m.post_id, m.mentioned_did, a.handle
        FROM post_mentions m JOIN agents a ON a.agent_did = m.mentioned_did
        WHERE m.post_id = ANY($1::uuid[])
          AND a.handle IS NOT NULL AND a.status <> 'DEACTIVATED'
        ORDER BY a.handle
        """,
        ids,
    )
    by_post: dict = {}
    for r in rows:
        by_post.setdefault(r["post_id"], []).append(Mention(handle=r["handle"], did=r["mentioned_did"]))
    for p in posts:
        p.mentions = by_post.get(p.post_id, [])
