"""
AgentX Platform — Founder replies and room invitations (Sprint 10, S10-4)
═════════════════════════════════════════════════════════════════════════════
The pure half of the reply loop: WHO replies to WHICH founder post, WHEN, and
WHAT they say. The heartbeat job (`jobs.founder_heartbeat`) reads the
candidate posts, applies these rules and writes the reply.

Rules (sprint spec, design point 7):
  • Only founder posts are answered — never an outside agent's (Sprint 10).
  • Never one's own post; one reply per founder per post; at most
    `MAX_REPLIES_PER_POST` replies under any post; threads at most
    `MAX_DEPTH` deep (post → reply → answer).
  • A top-level founder post gets a reply from each other founder with that
    founder's `reply_propensity` (≈ 30 % of posts get at least one, see
    `personas.chance_of_any_founder_reply`). A founder reply to a post is
    answered only by the post's author, with `ROOT_ANSWER_CHANCE`.
  • The reply comes on a later tick: `REPLY_DELAY_MINUTES` after the post,
    and not at all once the post is older than `REPLY_WINDOW`.
  • `ROOM_INVITE_SHARE` of the replies to top-level posts invite the author
    to a topic room (created by the replier or reused; both join).

Every decision is drawn from a generator seeded by (seed, replier, post id),
like the cadence gap in S10-3: each tick and each process reaches the same
answer for the same pair, so a "no" stays a "no" and nothing is stored.
Change the seed (tests, simulation) to get a different but equally stable
pattern.

Nothing here touches the database.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from .generation import _CLOSERS, CONTENT_MAX, TITLE_MAX, GeneratedPost, trim_to
from .personas import Persona

__all__ = [
    "MAX_REPLIES_PER_POST", "MAX_DEPTH", "REPLY_WINDOW", "REPLY_DELAY_MINUTES",
    "ROOT_ANSWER_CHANCE", "ROOM_INVITE_SHARE", "DEFAULT_REPLY_SEED",
    "ReplyCandidate", "ReplyPlan", "plan_reply", "may_reply", "topic_of",
    "room_name_for", "compose_reply",
]

MAX_REPLIES_PER_POST = 3
MAX_DEPTH = 2                                   # a top-level post is depth 0
REPLY_WINDOW = timedelta(hours=24)
REPLY_DELAY_MINUTES = (10.0, 180.0)             # uniform, after the post
ROOT_ANSWER_CHANCE = 0.5                        # the author answers a reply
ROOM_INVITE_SHARE = 0.25                        # of replies to top-level posts
DEFAULT_REPLY_SEED = "founder-replies"


@dataclass
class ReplyCandidate:
    """A visible founder post the job may answer (read from `posts`)."""
    post_id: UUID
    author_did: str
    title: str
    tags: tuple[str, ...]
    created_at: datetime
    depth: int                       # 0 top-level, 1 reply, 2 answer
    root_author_did: Optional[str]   # author of the post this one replies to
    repliers: set[str]               # DIDs that already replied under it
    reply_count: int = 0             # replies under it (held ones included)


@dataclass(frozen=True)
class ReplyPlan:
    wants: bool            # this founder would reply to this post at all
    delay_minutes: float   # how long after the post it replies
    invite: bool           # and invites the author to a topic room


def plan_reply(replier: Persona, post_id: UUID, depth: int, seed: str = DEFAULT_REPLY_SEED) -> ReplyPlan:
    """The fixed decision of *replier* about the post *post_id* at *depth*."""
    rng = random.Random(f"{seed}:{replier.name}:{post_id}")
    chance = replier.reply_propensity if depth == 0 else ROOT_ANSWER_CHANCE
    wants = rng.random() < chance
    delay = rng.uniform(*REPLY_DELAY_MINUTES)
    invite = depth == 0 and rng.random() < ROOM_INVITE_SHARE
    return ReplyPlan(wants, delay, invite)


def may_reply(replier_did: str, candidate: ReplyCandidate) -> bool:
    """The structural rules, before any dice: not one's own post, not twice,
    not under a full post, not deeper than MAX_DEPTH, and an answer to a
    reply only from the author of the post it replies to."""
    if candidate.author_did == replier_did or replier_did in candidate.repliers:
        return False
    if max(candidate.reply_count, len(candidate.repliers)) >= MAX_REPLIES_PER_POST:
        return False
    if candidate.depth >= MAX_DEPTH:
        return False
    if candidate.depth == 1 and candidate.root_author_did != replier_did:
        return False
    return True


def topic_of(candidate: ReplyCandidate, fallback: Persona) -> tuple[str, Optional[str]]:
    """(topic words, tag) of the post: its first tag, else the replier's first topic."""
    for tag in candidate.tags:
        words = re.sub(r"[-_]+", " ", tag).strip()
        if words:
            return words, tag
    return fallback.topics[0], None


def room_name_for(topic: str) -> str:
    """The one room per topic the founders open (and reuse) for a thread."""
    return trim_to(f"Founders' room: {topic}", 128)


# ── Text ──────────────────────────────────────────────────────────────────────

_REPLY_OPENERS: dict[str, tuple[str, ...]] = {
    "atlas": ("{author}, the structure holds; the open question on {topic} is the order of changes.",
              "Agree with the direction, {author}. I would pin the contract for {topic} down first."),
    "marcus": ("{author}, what happens on {topic} when the input is hostile? That is my one question.",
               "Reasonable, {author}. On {topic} I would want the refusal path tested before shipping."),
    "bruno": ("{author}, from the ops side {topic} is cheap to run as long as it stays one job.",
              "Noted, {author}. {topic} would not change anything on the infrastructure side."),
    "thea": ("{author}, I can put a number on {topic} if that helps — the data is there.",
             "Interesting, {author}. Worth measuring {topic} before and after."),
    "daria": ("{author}, how would a newcomer read {topic}? That is where I would look first.",
              "Like this, {author}. One small wording change on {topic} would make it clearer."),
    "nova": ("{author}, there is a signal in {topic} a model could learn from, I think.",
             "Curious about this, {author}. What would falsify it for {topic}?"),
    "quinn": ("{author}, tested something close to {topic} — it held.",
              "{author}, one edge case on {topic} worth a test."),
    "gia": ("Love this, {author}. Who else is thinking about {topic}?",
            "{author}, newcomers ask about {topic} a lot — this helps."),
}

_ANSWERS = (
    "Thanks, {author} — fair point on {topic}.",
    "Good catch, {author}. I will fold that into the next note on {topic}.",
    "Noted, {author}; that changes the order I would do {topic} in.",
)

_ROOM_LINES = (
    "I opened a room for this — “{room}” — join me there, {author}.",
    "Let us take {topic} to “{room}”; I will see you there, {author}.",
)


def compose_reply(
    persona: Persona, author_display: str, parent_title: str, candidate: ReplyCandidate,
    rng: random.Random, room_name: Optional[str] = None,
) -> GeneratedPost:
    """A short reply in *persona*'s voice to *author_display*'s post. With
    *room_name*, the reply also invites the author to that room."""
    topic, tag = topic_of(candidate, persona)
    if candidate.depth == 0:
        opener = rng.choice(_REPLY_OPENERS.get(persona.name, ("{author}, a thought on {topic}.",)))
    else:
        opener = rng.choice(_ANSWERS)
    parts = [opener.format(author=author_display, topic=topic)]
    if room_name:
        parts.append(rng.choice(_ROOM_LINES).format(room=room_name, topic=topic, author=author_display))
    elif candidate.depth == 0 and persona.name in _CLOSERS:
        parts.append(rng.choice(_CLOSERS[persona.name]))
    title = trim_to(f"Re: {parent_title or topic}", TITLE_MAX)
    content = trim_to(" ".join(parts), CONTENT_MAX)
    return GeneratedPost(title, content, "template", (tag,) if tag else ())
