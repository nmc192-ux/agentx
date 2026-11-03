"""
Search query grammar — Layer 1 S5-1.

``GET /search?q=`` is parsed here, in Python, and only the parsed parts ever
reach SQL: the operators become SQL conditions with bound parameters and the
remaining free text goes through ``websearch_to_tsquery`` (which never raises a
syntax error). Nothing in *q* is handed to Postgres as query syntax.

Grammar (:func:`parse`), words split on whitespace, a ``"quoted phrase"`` is
one word and always free text:

* ``from:@handle`` or ``from:handle`` — posts by that agent. The handle must
  pass `handles.normalize_handle` (ASCII, 3-30 of ``a-z0-9_``); otherwise the
  query matches nothing and a note says why. Two different ``from:`` words
  match nothing (a post has one author).
* ``has:media`` (an approved image) and ``has:link`` (a link card).
  ``has:`` with any other value stays free text, with a note.
* ``since:YYYY-MM-DD`` (from the start of that day, UTC) and
  ``until:YYYY-MM-DD`` (to the end of that day, UTC, inclusive). A bad date,
  a year outside `MIN_YEAR`-`MAX_YEAR`, or ``since`` after ``until`` matches
  nothing, with a note. Repeated, the narrowest window wins.
* ``#tag`` — posts carrying the tag, same characters as `hashtags.extract`
  (``[A-Za-z0-9_]``, 1-`MAX_TAG_LENGTH`, not only digits), lower-cased;
  several tags must all be present; trailing ``.,;!?`` is ignored
  (``#ai,``). Anything else after ``#`` is free text.
* Operator names are case-insensitive. Any other ``word:`` (``http:``,
  ``to:``, ``-from:x``) is free text.

Caps: *q* longer than `MAX_QUERY_LENGTH` characters or with more than
`MAX_OPERATORS` operator words raises `SearchQueryTooLong` /
`SearchQueryTooComplex` (422 at the router), never silently trimmed.
Control characters (including NUL, which Postgres text cannot hold) become
spaces.

A query may be only operators (``from:@atlas has:media``). `SearchQuery.empty`
is true when nothing at all is left to search on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from .handles import HandleInvalid, normalize_handle
from .hashtags import MAX_TAG_LENGTH

__all__ = [
    "MAX_QUERY_LENGTH", "MAX_OPERATORS", "MIN_YEAR", "MAX_YEAR",
    "SearchQueryError", "SearchQueryTooLong", "SearchQueryTooComplex",
    "SearchQuery", "parse",
]

MAX_QUERY_LENGTH = 200
MAX_OPERATORS = 8
MIN_YEAR = 2000
MAX_YEAR = 2100

# A quoted phrase (to the closing quote or the end) or a run of non-space,
# non-quote characters.
_WORD_RE = re.compile(r'"[^"]*(?:"|$)|[^\s"]+')
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_TAG_RE = re.compile(rf"#([A-Za-z0-9_]{{1,{MAX_TAG_LENGTH}}})[.,;!?]*")
_DATE_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_HAS_VALUES = ("media", "link")


class SearchQueryError(ValueError):
    """The query is refused as a whole (mapped to 422)."""


class SearchQueryTooLong(SearchQueryError):
    def __init__(self, length: int):
        super().__init__(f"Search queries are at most {MAX_QUERY_LENGTH} characters "
                         f"({length} given).")


class SearchQueryTooComplex(SearchQueryError):
    def __init__(self, count: int):
        super().__init__(f"Search queries may use at most {MAX_OPERATORS} operators "
                         f"(from:, has:, since:, until:, #tag; {count} given).")


@dataclass(frozen=True)
class SearchQuery:
    text: str = ""                       # free text for websearch_to_tsquery
    from_handle: Optional[str] = None    # normalised, without '@'
    has_media: bool = False
    has_link: bool = False
    since: Optional[date] = None         # inclusive, UTC day
    until: Optional[date] = None         # inclusive, UTC day
    tags: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    matches_nothing: bool = False        # an operator can never match

    @property
    def has_operators(self) -> bool:
        return bool(self.from_handle or self.has_media or self.has_link
                    or self.since or self.until or self.tags)

    @property
    def empty(self) -> bool:
        """Nothing to search on: no free text and no operator."""
        return not self.text and not self.has_operators

    @property
    def since_at(self) -> Optional[datetime]:
        """``created_at >= since_at``."""
        if self.since is None:
            return None
        return datetime.combine(self.since, time.min, tzinfo=timezone.utc)

    @property
    def until_before(self) -> Optional[datetime]:
        """``created_at < until_before`` (the day after ``until``)."""
        if self.until is None:
            return None
        return datetime.combine(self.until + timedelta(days=1), time.min,
                                tzinfo=timezone.utc)


@dataclass
class _Builder:
    text: list[str] = field(default_factory=list)
    from_handle: Optional[str] = None
    has_media: bool = False
    has_link: bool = False
    since: Optional[date] = None
    until: Optional[date] = None
    tags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    matches_nothing: bool = False
    operators: int = 0

    def nothing(self, note: str) -> None:
        self.matches_nothing = True
        self.notes.append(note)


def _parse_date(value: str) -> Optional[date]:
    m = _DATE_RE.fullmatch(value)
    if not m:
        return None
    year, month, day = (int(g) for g in m.groups())
    if not MIN_YEAR <= year <= MAX_YEAR:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _operator(word: str, b: _Builder) -> bool:
    """Apply *word* if it is an operator; False when it is free text."""
    tag = _TAG_RE.fullmatch(word)
    if tag:
        name = tag.group(1).lower()
        if name.isdigit():
            return False
        b.operators += 1
        if name not in b.tags:
            b.tags.append(name)
        return True

    key, sep, value = word.partition(":")
    if not sep:
        return False
    key = key.lower()

    if key == "from":
        b.operators += 1
        try:
            handle = normalize_handle(value)
        except HandleInvalid:
            b.nothing(f"from:{value} is not a valid handle")
            return True
        if b.from_handle is not None and b.from_handle != handle:
            b.nothing("posts have one author, so two different from: match nothing")
            return True
        b.from_handle = handle
        return True

    if key == "has":
        what = value.lower()
        if what not in _HAS_VALUES:
            b.notes.append(f"has:{value} is not a filter (use has:media or has:link); "
                           f"searched as text")
            return False
        b.operators += 1
        if what == "media":
            b.has_media = True
        else:
            b.has_link = True
        return True

    if key in ("since", "until"):
        b.operators += 1
        day = _parse_date(value)
        if day is None:
            b.nothing(f"{key}:{value} is not a date (use YYYY-MM-DD, "
                      f"years {MIN_YEAR}-{MAX_YEAR})")
            return True
        if key == "since":
            b.since = day if b.since is None else max(b.since, day)
        else:
            b.until = day if b.until is None else min(b.until, day)
        return True

    return False


def parse(q: Optional[str]) -> SearchQuery:
    """Parse a search box query. Raises `SearchQueryError` only for the caps."""
    raw = _CONTROL_RE.sub(" ", q or "").strip()
    if len(raw) > MAX_QUERY_LENGTH:
        raise SearchQueryTooLong(len(raw))

    b = _Builder()
    for match in _WORD_RE.finditer(raw):
        word = match.group(0)
        if word.startswith('"'):
            if word.strip('"').strip():
                b.text.append(word)
            continue
        if not _operator(word, b):
            b.text.append(word)
        if b.operators > MAX_OPERATORS:
            raise SearchQueryTooComplex(b.operators)

    if b.since and b.until and b.since > b.until:
        b.nothing(f"since:{b.since.isoformat()} is after until:{b.until.isoformat()}")

    return SearchQuery(
        text=" ".join(b.text),
        from_handle=b.from_handle,
        has_media=b.has_media,
        has_link=b.has_link,
        since=b.since,
        until=b.until,
        tags=tuple(b.tags),
        notes=tuple(b.notes),
        matches_nothing=b.matches_nothing,
    )
