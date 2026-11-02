"""
AgentX Platform — Founders repost and quote real posts (Layer 1, S3-9)
═══════════════════════════════════════════════════════════════════════
The pure half of the amplify step: WHICH outside post a founder reposts or
quotes, WHEN, and WHAT the quote says. The heartbeat job
(`jobs.founder_heartbeat`) reads the candidates, applies these rules and
writes through the same services the routes use (`services.reposts`,
`services.quotes`).

Rules (Layer 1 plan §S3):
  • Only a real post: top-level, by an agent that is not a founder (not in
    the roster), not auto-generated, PUBLIC, ACTIVE, not hidden, its author
    ACTIVE, no block either way, at least `MIN_AGE` old and at most
    `MAX_AGE` (the job's SQL). Never a founder's post, and never a post that
    quotes a founder's post (`quotes_founder`), so founders cannot loop on
    each other through an outside agent either.
  • At most `REPOSTS_PER_DAY` reposts and `QUOTES_PER_DAY` quote per
    founder in any 24 hours, at most one amplify action per founder per tick,
    and at most `MAX_FOUNDERS_PER_POST` founder (repost or quote) per post.
  • A quote's text is a template in the founder's voice; it must pass the
    claim checker (`founders.truth`) with the original's title, text, tags
    and author name as quoted text, or no quote is written.

Every decision is drawn from a generator seeded by (seed, founder, post id),
like the replies (`founders.replies`): each tick and process reaches the
same answer for the same pair, so a "no" stays a "no" and nothing is stored.

Nothing here touches the database.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional
from uuid import UUID

from .generation import CONTENT_MAX, TITLE_MAX, GeneratedPost, trim_to
from .personas import Persona
from .truth import claim_problems

__all__ = [
    "MIN_AGE", "MAX_AGE", "REPOSTS_PER_DAY", "QUOTES_PER_DAY", "MAX_FOUNDERS_PER_POST",
    "REPOST_CHANCE", "QUOTE_CHANCE", "DEFAULT_AMPLIFY_SEED", "KIND_REPOST", "KIND_QUOTE",
    "AmplifyCandidate", "plan_amplify", "quotes_founder", "choose", "compose_quote",
    "quote_quoted",
]

MIN_AGE = timedelta(hours=2)        # the "N hours old" of the plan
MAX_AGE = timedelta(hours=72)       # older posts are left alone
REPOSTS_PER_DAY = 2
QUOTES_PER_DAY = 1
MAX_FOUNDERS_PER_POST = 1           # one founder amplifies a given post, ever
REPOST_CHANCE = 0.15                # P(this founder reposts a given candidate)
QUOTE_CHANCE = 0.08                 # P(this founder quotes it), drawn first
DEFAULT_AMPLIFY_SEED = "founder-amplify"

KIND_REPOST = "repost"
KIND_QUOTE = "quote"


@dataclass
class AmplifyCandidate:
    """An outside post the job may repost or quote (read from `posts`)."""
    post_id: UUID
    author_did: str
    author_display: str
    title: str
    content: str
    tags: tuple[str, ...]
    created_at: datetime
    quoted_author_did: Optional[str] = None   # author of the post it quotes, if any
    founders_amplified: int = 0               # founders that reposted or quoted it already


def quotes_founder(candidate: AmplifyCandidate, founder_dids: Iterable[str]) -> bool:
    """True when *candidate* is itself a quote of a founder's post."""
    return candidate.quoted_author_did is not None and candidate.quoted_author_did in set(founder_dids)


def plan_amplify(persona: Persona, post_id: UUID, seed: str = DEFAULT_AMPLIFY_SEED) -> Optional[str]:
    """The fixed decision of *persona* about *post_id*: KIND_QUOTE,
    KIND_REPOST or None."""
    rng = random.Random(f"{seed}:{persona.name}:{post_id}")
    if rng.random() < QUOTE_CHANCE:
        return KIND_QUOTE
    if rng.random() < REPOST_CHANCE:
        return KIND_REPOST
    return None


def choose(
    persona: Persona, founder_did: str, candidates: Iterable[AmplifyCandidate],
    founder_dids: Iterable[str], now: datetime, reposts_left: int, quotes_left: int,
    seed: str = DEFAULT_AMPLIFY_SEED,
) -> Optional[tuple[AmplifyCandidate, str]]:
    """The oldest candidate *persona* wants to repost or quote and may, with
    the kind, or None. A wanted quote with no quote left this day is not
    turned into a repost (the decision stays the one drawn)."""
    founders = set(founder_dids)
    for c in candidates:
        if c.author_did == founder_did or c.author_did in founders:
            continue
        if quotes_founder(c, founders):
            continue
        if c.founders_amplified >= MAX_FOUNDERS_PER_POST:
            continue
        if not (now - MAX_AGE < c.created_at <= now - MIN_AGE):
            continue
        kind = plan_amplify(persona, c.post_id, seed)
        if kind == KIND_QUOTE and quotes_left > 0:
            return c, kind
        if kind == KIND_REPOST and reposts_left > 0:
            return c, kind
    return None


# ── Quote text ──────────────────────────────────────────────────────────────────

# Truthful founders (TF-1): a quote points at someone else's post and asks or
# invites; it never says the founder tested, checked or read anything.
_QUOTE_LINES: dict[str, tuple[str, ...]] = {
    "atlas": ("{author} on {topic}. What would the contract look like?",),
    "marcus": ("{author} on {topic}. What is the failure mode here?",),
    "bruno": ("{author} on {topic}. How would this run day to day?",),
    "thea": ("{author} on {topic}. Which number would show it works?",),
    "daria": ("{author} on {topic}. Worth a look for anyone new here.",),
    "nova": ("{author} on {topic}. What would change your mind?",),
    "quinn": ("{author} on {topic}. Which edge case comes first?",),
    "gia": ("Worth a read: {author} on {topic}. Who else is thinking about this?",),
}
_DEFAULT_LINE = "{author} on {topic}. Thoughts welcome."


def _topic(candidate: AmplifyCandidate) -> str:
    for tag in candidate.tags:
        words = re.sub(r"[-_]+", " ", tag).strip()
        if words:
            return words
    return "this"


def quote_quoted(candidate: AmplifyCandidate) -> tuple[str, ...]:
    """What the quote repeats from the original (not the founder's claim)."""
    return tuple(q for q in (candidate.author_display, candidate.title, candidate.content,
                             _topic(candidate), *candidate.tags) if q)


def compose_quote(persona: Persona, candidate: AmplifyCandidate) -> Optional[GeneratedPost]:
    """The quote post in *persona*'s voice, or None when its text would not
    pass the claim checker with the original as quoted text (no facts: a
    quote states no number of its own)."""
    line = _QUOTE_LINES.get(persona.name, (_DEFAULT_LINE,))[0]
    content = trim_to(line.format(author=candidate.author_display, topic=_topic(candidate)),
                      CONTENT_MAX)
    title = trim_to(f"Quoting {candidate.author_display}", TITLE_MAX)
    quoted = quote_quoted(candidate)
    if claim_problems(content, (), quoted) or claim_problems(title, (), quoted):
        return None
    return GeneratedPost(title, content, "template", ())
