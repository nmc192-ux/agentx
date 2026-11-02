"""
#hashtags — Layer 1 S3-6.

A post's ``#tag`` words become tags **at write time** (`merge`, pure), the same
as ``@mentions`` (`services/mentions.py`): readers get the stored ``tags`` and
link only those (S3-8a); everything else stays plain text.

Parsing (:func:`extract`):

* ``#`` followed by ``[A-Za-z0-9_]`` at the start of the text or after a
  character that is not a word character, ``#``, ``&`` or ``/``. So ``a#b``,
  ``##tag``, ``&#39;`` (an HTML entity) and ``x.io/#top`` are not hashtags.
* Nothing inside a URL counts: ``https://x.io/page#section`` and
  ``www.x.io/a?b=1#c`` carry no tag (the URL fragment is skipped as a whole).
* The tag must be a whole token: the next character may not be a word
  character in *any* script, nor a combining mark, so ``#cafè`` or a Cyrillic
  look-alike is not ``#caf`` plus text.
* The tag is folded to lower case and must be 1-`MAX_TAG_LENGTH` characters
  and not only digits (``issue #42`` and ``#1`` are not tags). A longer token
  is plain text, never cut short.

Merging (:func:`merge`): the explicit ``tags`` of the request first (trimmed,
leading ``#`` dropped, lower-cased, empty ones dropped), then the parsed ones,
distinct, in order. More than `MAX_TAGS` in total is refused
(`TooManyTags`, 422), never silently trimmed.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

__all__ = [
    "MAX_TAGS", "MAX_TAG_LENGTH", "TooManyTags",
    "extract", "normalize", "merge",
]

MAX_TAGS = 10
MAX_TAG_LENGTH = 50

# One character past the limit is matched so a too-long token is seen whole
# (and dropped) rather than cut into a 50-character tag.
_HASHTAG_RE = re.compile(
    rf"(?<![\w#&/])#([A-Za-z0-9_]{{1,{MAX_TAG_LENGTH + 1}}})(?!\w)"
)
# A URL runs to the next whitespace; a '#' inside it is a fragment, not a tag.
_URL_RE = re.compile(r"(?i)\b(?:[a-z][a-z0-9+.\-]*://|www\.)\S+")


class TooManyTags(ValueError):
    """More than `MAX_TAGS` distinct tags on one post."""

    def __init__(self, tags: list[str]):
        self.tags = tags
        super().__init__(
            f"A post may carry at most {MAX_TAGS} tags, counting #hashtags in "
            f"the text ({len(tags)} found: {', '.join(tags)})."
        )


def extract(text: Optional[str]) -> list[str]:
    """Distinct hashtags in *text*, lower-cased, in order of first appearance."""
    if not text:
        return []
    urls = [m.span() for m in _URL_RE.finditer(text)]
    found: list[str] = []
    seen: set[str] = set()
    for match in _HASHTAG_RE.finditer(text):
        start = match.start()
        if any(a <= start < b for a, b in urls):
            continue                                    # a URL fragment
        after = text[match.end():match.end() + 1]
        if after and unicodedata.category(after).startswith("M"):
            continue                                    # "#cafè": a combining mark
        tag = match.group(1).lower()
        if len(tag) > MAX_TAG_LENGTH or tag.isdigit():
            continue
        if tag not in seen:
            seen.add(tag)
            found.append(tag)
    return found


def normalize(tag: str) -> str:
    """An explicit tag as stored: trimmed, leading '#' dropped, lower-cased."""
    return tag.strip().lstrip("#").strip().lower()


def merge(tags: Iterable[str], *texts: Optional[str]) -> list[str]:
    """Explicit *tags* then the hashtags of *texts*, distinct, lower-cased.
    `TooManyTags` when the total is over `MAX_TAGS`."""
    merged: list[str] = []
    for tag in [normalize(t) for t in tags] + [t for x in texts for t in extract(x)]:
        if tag and tag not in merged:
            merged.append(tag)
    if len(merged) > MAX_TAGS:
        raise TooManyTags(merged)
    return merged
