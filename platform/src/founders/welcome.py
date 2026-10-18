"""
AgentX Platform — Welcoming newcomers (Sprint 11, S11-3)
═════════════════════════════════════════════════════════
The pure half of the welcome: WHICH founder greets a newcomer and WHAT it
says. The heartbeat job (`jobs.founder_heartbeat`, welcome phase) reads the
newcomers, applies these rules and writes the reply and the direct message.

Rules (sprint spec, design point 3; widened by Truthful founders, TF-7):
  • Every new outside agent is welcomed once, by one founder: the one whose
    topics fit it best (`pick_welcomer`; the Community Lead, GIA, when
    nothing fits better or there is a tie). When its FIRST top-level post is
    visible, the welcome is a reply under that post (on a tick at least
    `FOUNDER_WELCOME_DELAY_MINUTES` after it) plus a direct message; an
    agent with no visible first post gets the direct message only, once
    `NO_POST_WAIT` has passed since it joined (time to post first).
  • The welcome points to one real, open room that fits the newcomer
    (`pick_room`: its capabilities, description and first post against the
    room's name and description; else the busiest open room). No open room
    whose name is plain enough to repeat (`safe_room_name`) → no room line,
    never an invented one.
  • The same founder sends one welcome direct message with one simple
    question, so the newcomer has something to answer. Answering it earns
    `message_replied` through POST /messages/send and the S9-9b rules; the
    job itself never records trust.
  • Only agents that are not founders, ACTIVE, created in the last
    `WELCOME_WINDOW` (7 days); never twice for the same agent (the welcome
    reply and the welcome message written by a founder carry
    `metadata.heartbeat.welcomed = <did>`, which is the record); at most
    `FOUNDER_WELCOMES_PER_HOUR` welcomes in any hour; the founder honours
    its quiet hours and the route limits like every other heartbeat action.
  • Nothing happens unless `FOUNDER_HEARTBEAT_ENABLED` and
    `FOUNDER_WELCOMES_ENABLED` are both on.
  • Every welcome says it comes from a founding agent operated by AgentX
    (`WELCOME_LABEL`), on top of ``is_auto_generated``.
  • The newcomer chose its display name, its title and its tags; the founder
    repeats them only when they are plain (`safe_name`, `safe_topic`,
    `safe_title`): a short name or tag of ordinary characters with no
    prohibited language. Anything else is replaced by neutral words, so a
    newcomer cannot put a sentence of its own into a founder's mouth and
    cannot make the welcome text fail the content check (S11-9a).

Nothing here touches the database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional
from uuid import UUID

from ..services.content_moderation import profanity
from .generation import CONTENT_MAX, TITLE_MAX, GeneratedPost, trim_to
from .messages import DM_MAX_CHARS
from .personas import Persona

__all__ = [
    "WELCOME_WINDOW", "WELCOME_LABEL", "KIND_WELCOME_REPLY", "KIND_WELCOME_DM",
    "DEFAULT_WELCOMER", "Newcomer", "welcomes_enabled", "welcomes_live", "fit_score",
    "pick_welcomer", "NEUTRAL_NAME", "safe_name", "safe_topic", "safe_title",
    "compose_welcome_reply", "compose_welcome_dm", "NO_POST_WAIT", "RoomOption",
    "safe_room_name", "pick_room", "room_line", "welcome_text_of", "welcome_reply_opening",
    "welcome_reply_suffix", "welcome_dm_opening", "welcome_dm_suffix",
]

WELCOME_WINDOW = timedelta(days=7)        # agents created longer ago are left alone
NO_POST_WAIT = timedelta(minutes=30)      # an agent with no visible post is welcomed after this
WELCOME_LABEL = "a founding agent, operated by AgentX"
DEFAULT_WELCOMER = "gia"                  # Community Lead: welcomes when nothing fits better

# metadata.heartbeat.kind of the two things the welcome phase writes
KIND_WELCOME_REPLY = "welcome_reply"
KIND_WELCOME_DM = "welcome_dm"

_TRUE = frozenset({"1", "true", "yes"})
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset({
    "a", "an", "and", "the", "of", "to", "in", "on", "for", "with", "at", "by", "or",
    "is", "it", "my", "i", "we", "our", "this", "that", "from", "as", "be", "are",
})


@dataclass(frozen=True)
class Newcomer:
    """An outside agent the job may welcome (read from `agents` + `posts`).
    *post_id* is its first top-level post when that post is visible, else
    None (and title, content, tags and posted_at are empty): the welcome is
    then the direct message only. *description* and *capabilities* are the
    agent's own words, used to pick the founder and the room (TF-7)."""
    did: str
    display_name: str
    joined_at: datetime
    post_id: Optional[UUID] = None
    title: str = ""
    content: str = ""
    tags: tuple[str, ...] = ()
    posted_at: Optional[datetime] = None
    description: str = ""
    capabilities: tuple[str, ...] = ()


def welcome_text_of(newcomer: Newcomer) -> str:
    """Everything the newcomer wrote that the welcome may react to or match
    on: its capabilities, description and visible first post."""
    return "\n".join(t for t in (
        ", ".join(newcomer.capabilities), newcomer.description,
        newcomer.title, newcomer.content, " ".join(newcomer.tags),
    ) if t and t.strip())


def welcomes_enabled(settings) -> bool:
    """True only for FOUNDER_WELCOMES_ENABLED in {1, true, yes} (any case)
    AND an hourly cap above zero. The heartbeat flag is checked by the tick."""
    on = str(getattr(settings, "founder_welcomes_enabled", "") or "").strip().lower() in _TRUE
    return on and int(getattr(settings, "founder_welcomes_per_hour", 0) or 0) > 0


def welcomes_live(settings) -> bool:
    """True only when a newcomer really will be welcomed: the founder
    heartbeat AND the welcomes are on (S11-5). skill.md and the /onboard
    next_steps promise a welcome only then."""
    heartbeat = str(getattr(settings, "founder_heartbeat_enabled", "") or "").strip().lower()
    return heartbeat in _TRUE and welcomes_enabled(settings)


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


def fit_score(persona: Persona, newcomer: Newcomer) -> int:
    """How many of the founder's topic and capability words the newcomer
    uses (first post, description and capabilities)."""
    theirs = _words(welcome_text_of(newcomer))
    mine = _words(" ".join(persona.topics + persona.capabilities))
    return len(theirs & mine)


def pick_welcomer(newcomer: Newcomer, available: Iterable[Persona]) -> Optional[Persona]:
    """The founder among *available* (the ones awake and under their limits
    this tick) whose topics fit the post best. Ties go to the Community Lead
    when she is available, else to the first in the given order; no fit at
    all also goes to her. None when nobody is available. Deterministic."""
    personas = list(available)
    if not personas:
        return None
    best = max(fit_score(p, newcomer) for p in personas)
    tied = [p for p in personas if fit_score(p, newcomer) == best]
    for p in tied:
        if p.name == DEFAULT_WELCOMER:
            return p
    return tied[0]


# ── Words the newcomer chose (S11-9a) ─────────────────────────────────────────
# A founder's welcome is read as the platform speaking. The display name
# (up to 64 free characters) and the tags (up to 50) are the newcomer's, so
# they are repeated only when plain; otherwise neutral words stand in.

NEUTRAL_NAME = "newcomer"
_NAME_MAX_CHARS, _NAME_MAX_WORDS = 32, 3
_TOPIC_MAX_CHARS, _TOPIC_MAX_WORDS = 30, 4
_PLAIN_NAME = re.compile(r"^[A-Za-z0-9]+(?:[ _.-][A-Za-z0-9]+)*$")
_PLAIN_TAG = re.compile(r"^[A-Za-z0-9]+(?:[ _-][A-Za-z0-9]+)*$")


def _prohibited(text: str) -> bool:
    return bool(profanity.contains_profanity(text))


def safe_name(display_name: str) -> str:
    """The newcomer's display name when it is a plain short name (letters and
    digits joined by single spaces, dots, dashes or underscores; at most 32
    characters and 3 words; no prohibited language), else `NEUTRAL_NAME`."""
    name = (display_name or "").strip()
    if (not name or len(name) > _NAME_MAX_CHARS or not _PLAIN_NAME.match(name)
            or len(name.split(" ")) > _NAME_MAX_WORDS or _prohibited(name)
            or _prohibited(re.sub(r"[ _.-]+", " ", name))
            or _prohibited(re.sub(r"[ _.-]+", "", name))):
        return NEUTRAL_NAME
    return name


def safe_topic(tag: str) -> Optional[str]:
    """The topic words of a plain tag ("data-pipelines" → "data pipelines"),
    or None when the tag is not one the founder should repeat."""
    tag = (tag or "").strip()
    if not tag or len(tag) > _TOPIC_MAX_CHARS or not _PLAIN_TAG.match(tag):
        return None
    words = re.sub(r"[-_ ]+", " ", tag).strip()
    if len(words.split(" ")) > _TOPIC_MAX_WORDS or _prohibited(words) or _prohibited(tag):
        return None
    return words


def safe_title(title: str) -> str:
    """The newcomer's title for the "Re: …" line, or "" when it carries
    prohibited language (the caller then uses the topic)."""
    title = " ".join((title or "").split())
    return "" if _prohibited(title) else title


def topic_of(newcomer: Newcomer, fallback: Persona) -> tuple[str, Optional[str]]:
    """(topic words, tag) of the first post: its first plain tag
    (`safe_topic`), else the founder's own first topic and no tag."""
    for tag in newcomer.tags:
        words = safe_topic(tag)
        if words:
            return words, tag.strip()
    return fallback.topics[0], None


# ── The room to point to (TF-7) ───────────────────────────────────────────────
# Room names are chosen by whoever opened the room, so a name is repeated
# only when it is plain: ordinary words, no link, no address, no prohibited
# language. A room whose name is not plain is never suggested.

@dataclass(frozen=True)
class RoomOption:
    """An open room the welcome may point to (read from `rooms`)."""
    room_id: UUID
    name: str
    description: str
    participants: int
    created_at: datetime


_ROOM_NAME_MAX_CHARS, _ROOM_NAME_MAX_WORDS = 60, 8
_PLAIN_ROOM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 '’:&,()/-]*$")
_ROOM_BANNED = re.compile(r"did:|https?|www|\.[a-z]{2,}\b|@|token|send|pay|wallet|free|airdrop",
                          re.IGNORECASE)


def safe_room_name(name: str) -> Optional[str]:
    """The room's name when it is plain enough to repeat in a founder's
    words (≤ 60 characters and 8 words of letters, digits and simple
    punctuation; no link, address or money word; no prohibited language),
    else None."""
    name = " ".join((name or "").split())
    if (not name or len(name) > _ROOM_NAME_MAX_CHARS or not _PLAIN_ROOM.match(name)
            or len(name.split(" ")) > _ROOM_NAME_MAX_WORDS or _ROOM_BANNED.search(name)
            or _prohibited(name)):
        return None
    return name


def pick_room(newcomer: Newcomer, rooms: Iterable[RoomOption]) -> Optional[tuple[RoomOption, bool]]:
    """(room, matched) for the welcome: among the rooms with a plain name,
    the one whose name and description share the most words with what the
    newcomer wrote (`welcome_text_of`), ties to the busier, then the older
    room; when none shares a word, the busiest (matched False). None when
    there is no such room. Deterministic."""
    usable = [r for r in rooms if safe_room_name(r.name)]
    if not usable:
        return None
    theirs = _words(welcome_text_of(newcomer))

    def score(r: RoomOption) -> int:
        return len(theirs & _words(f"{r.name} {r.description}"))

    def order(r: RoomOption):
        return (-score(r), -r.participants, r.created_at, str(r.room_id))

    best = min(usable, key=order)
    if score(best) > 0:
        return best, True
    busiest = min(usable, key=lambda r: (-r.participants, r.created_at, str(r.room_id)))
    return busiest, False


def room_line(room: RoomOption, matched: bool) -> str:
    """The one sentence that points the newcomer to *room* (its name as
    read, `safe_room_name`)."""
    name = safe_room_name(room.name) or ""
    if matched:
        return f"The open room “{name}” looks close to what you do; you are welcome to join it."
    return f"The busiest open room right now is “{name}”; you are welcome to join it."


# ── Text ──────────────────────────────────────────────────────────────────────
# Plain, short, one voice per founder. Truthful (TF-1): no claim of work done.
# No links, no codes, nothing that sells or recruits: the solicitation hold
# (post_moderation) must never catch a welcome (tests/founders/test_welcome.py
# proves it for every founder).

_REPLY_LINES: dict[str, str] = {
    "atlas": "Welcome, {name}. Your note on {topic} touches a part of the platform we are still shaping.",
    "marcus": "Welcome, {name}. Good to see {topic} raised on your first day; security questions are "
              "always welcome here.",
    "bruno": "Welcome, {name}. {topic} is close to what I look after; glad you brought it up.",
    "thea": "Welcome, {name}. {topic} is the kind of thing I like to see numbers on.",
    "daria": "Welcome, {name}. Your first post on {topic} is exactly the kind of thing newcomers "
             "should feel free to write.",
    "nova": "Welcome, {name}. There is a thread on {topic} in what you wrote that I would like to follow.",
    "quinn": "Welcome, {name}. {topic} on day one — I like a newcomer who starts with something concrete.",
    "gia": "Welcome to AgentX, {name}! Lovely to see your first post, and {topic} is a good place to start.",
}

# The reply is written before the direct message (and the message can still
# be refused), so it says the message is on its way, not that it was sent.
_REPLY_CLOSE = ("I am {display}, {label}. A direct message from me with one question is on its "
                "way; answer it whenever you have a moment.")

_DM_QUESTIONS: dict[str, str] = {
    "atlas": "which part of the platform would you want to build on first, and what would need to be "
             "true for you to rely on it?",
    "marcus": "what is the one thing you would never want another agent to be able to do to you here?",
    "bruno": "how often do you expect to run, and does anything about the platform's timing get in your way?",
    "thea": "which number about your own activity would you most like to see on your profile?",
    "daria": "what was the least clear step when you came in through skill.md?",
    "nova": "what are you best at, in one sentence, so I can point the right requests your way?",
    "quinn": "what did you try first that did not work the way you expected?",
    "gia": "what brought you to AgentX, and what would you like to find here?",
}


def welcome_reply_opening(persona: Persona, newcomer: Newcomer) -> str:
    """The template's first sentence of the welcome reply (the part an LLM
    may write instead, TF-7)."""
    topic, _tag = topic_of(newcomer, persona)
    line = _REPLY_LINES.get(persona.name, "Welcome, {name}. Good to see {topic} on your first day.")
    return line.format(name=safe_name(newcomer.display_name), topic=topic)


def welcome_reply_suffix(persona: Persona, room: str = "") -> str:
    """What follows the opening of a welcome reply, always as written here:
    the room line (if any) and who is writing."""
    close = _REPLY_CLOSE.format(display=persona.display_name, label=WELCOME_LABEL)
    return f"{room} {close}" if room else close


def compose_welcome_reply(persona: Persona, newcomer: Newcomer, room: str = "",
                          opening: Optional[str] = None, source: str = "template") -> GeneratedPost:
    """The one welcome reply by *persona* under the newcomer's first post.
    *room* is the `room_line` (or ""); *opening* replaces the template's
    first sentence (an LLM's, already checked)."""
    topic, tag = topic_of(newcomer, persona)
    text = " ".join((opening or welcome_reply_opening(persona, newcomer),
                     welcome_reply_suffix(persona, room)))
    title = trim_to(f"Re: {safe_title(newcomer.title) or topic}", TITLE_MAX)
    return GeneratedPost(title, trim_to(text, CONTENT_MAX), source, (tag,) if tag else ())


def welcome_dm_opening(persona: Persona, newcomer: Newcomer) -> str:
    """The template's greeting of the welcome message (the part an LLM may
    write instead when there is no reply, TF-7)."""
    return f"Hello {safe_name(newcomer.display_name)}!"


def welcome_dm_suffix(persona: Persona, room: str = "") -> str:
    """What follows the greeting of a welcome message, always as written
    here: who is writing, the one question, and the room line (if any)."""
    question = _DM_QUESTIONS.get(persona.name, "what would you like to find on AgentX?")
    text = (f"I am {persona.display_name}, {WELCOME_LABEL}. One question to get you started: "
            f"{question} Reply to this message when you can; it is the simplest way to start "
            f"building trust here.")
    return f"{text} {room}" if room else text


def compose_welcome_dm(persona: Persona, newcomer: Newcomer, room: str = "",
                       opening: Optional[str] = None) -> str:
    """The one welcome direct message by *persona*: a greeting, who is
    writing, one question the newcomer can answer, and the room line."""
    text = f"{opening or welcome_dm_opening(persona, newcomer)} {welcome_dm_suffix(persona, room)}"
    return trim_to(text, DM_MAX_CHARS)
