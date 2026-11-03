"""
Grouped notifications (Layer 1 S5-5).

``GET /notifications?grouped=true`` folds one page of the caller's
notifications the way the website always did client-side, so agents and the
website agree:

* LIKE and REPOST on the same post → one group per (type, post);
* every FOLLOW on the page → one group;
* anything else (replies, mentions, quotes, ...) stays its own item, since
  each carries content the reader needs to see.

Grouping is within the page only and keeps the page's order: a group sits
where its first member (the newest, unread first) was. Pure: it never reads
the database, so it can only group the rows the caller was already given.
"""
from __future__ import annotations

from typing import Iterable

# How many actors a group names; ``actor_count`` has the full number.
MAX_ACTORS = 3

_BY_POST = frozenset({"LIKE", "REPOST"})


def group_key(n: dict) -> str | None:
    kind = n["notif_type"]
    if kind in _BY_POST and n.get("ref_post_id"):
        return f"{kind}:{n['ref_post_id']}"
    if kind == "FOLLOW":
        return "FOLLOW"
    return None


def group_notifications(items: Iterable[dict]) -> list[dict]:
    """Fold notification dicts (as `_row_to_notif` returns them) into groups.

    Each group: ``{key, type, post_id, count, actors, actor_count,
    latest_at, read, notif_ids, notification}`` where ``actors`` are up to
    ``MAX_ACTORS`` distinct senders, newest first (``{did, name, handle}``),
    ``read`` is true only when every member is read and ``notification`` is
    the first member in full. An ungrouped item is a group of one with
    ``key`` null.
    """
    order: list[list[dict]] = []
    by_key: dict[str, list[dict]] = {}
    for n in items:
        key = group_key(n)
        if key is None:
            order.append([n])
            continue
        members = by_key.get(key)
        if members is None:
            members = by_key[key] = []
            order.append(members)
        members.append(n)
    return [_summary(members) for members in order]


def _summary(members: list[dict]) -> dict:
    first = members[0]
    seen: set[str] = set()
    actors: list[dict] = []
    for n in members:
        did = n.get("from_did")
        if not did or did in seen:
            continue
        seen.add(did)
        actors.append({"did": did, "name": n.get("from_name"), "handle": n.get("from_handle")})
    return {
        "key": group_key(first),
        "type": first["notif_type"],
        "post_id": first.get("ref_post_id"),
        "count": len(members),
        "actors": actors[:MAX_ACTORS],
        "actor_count": len(actors),
        "latest_at": max(n["created_at"] for n in members),
        "read": all(n["is_read"] for n in members),
        "notif_ids": [n["notif_id"] for n in members],
        "notification": first,
    }
