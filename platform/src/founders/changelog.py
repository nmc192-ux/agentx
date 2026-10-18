"""
AgentX Platform — Shipped changes for ATLAS (Truthful founders, TF-4)
═════════════════════════════════════════════════════════════════════
What ATLAS may say about what changed on AgentX: one line of
`platform/CHANGELOG.md` (baked into the image as /app/CHANGELOG.md) that no
founder has posted before. Never anything else.

The file, newest first, one user-visible change per line:

    - 2026-10-18 — Visitors who are not signed in no longer see ...

Rules:
  - Only lines of exactly that shape count; everything else (headings,
    notes, blank lines) is ignored. A line dated in the future, older than
    `MAX_AGE`, longer than `MAX_LINE` or that fails the TF-1 claim checker
    on its own is skipped (and logged), never rewritten.
  - The record of a posted entry is ``metadata.heartbeat.changelog = <key>``
    on a post WRITTEN BY A FOUNDER (governance role); post metadata is free
    for any caller to set, so an outsider's post cannot mark an entry as
    posted. If that lookup fails, there is no fact (ATLAS stays quiet rather
    than risk repeating himself).
  - At most one fact per tick: the newest entry not yet posted. Its key is
    in `Fact.source` (``file:CHANGELOG.md#<key>``); `entry_key` reads it back
    so the post can carry the marker.
  - Missing, unreadable or oversized file → no fact.

Nothing here writes anything.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .facts import Fact, _row
from .truth import claim_problems

logger = logging.getLogger("agentx.founders.changelog")

__all__ = ["MARKER", "MAX_AGE", "Entry", "parse_changelog", "posted_keys",
           "atlas_facts", "entry_key", "DEFAULT_PATH"]

MARKER = "changelog"                 # metadata.heartbeat.<MARKER> = entry key
MAX_AGE = timedelta(days=30)         # older lines are history, not news
MAX_LINE = 280
_MAX_BYTES = 64 * 1024
_SOURCE = "file:CHANGELOG.md#"
_LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) — (\S.*?)\s*$")
_KEY = re.compile(r"[0-9a-f]{16}")

# src/founders/changelog.py → platform/ (repo) or /app (image)
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "CHANGELOG.md"


@dataclass(frozen=True)
class Entry:
    day: date
    text: str

    @property
    def key(self) -> str:
        """Stable id of the line (date + words), for the posted marker."""
        return hashlib.sha256(f"{self.day.isoformat()} {self.text}".encode()).hexdigest()[:16]


def parse_changelog(text: str) -> list[Entry]:
    """Every well-formed entry in *text*, in file order (newest first by
    convention; the reader sorts anyway)."""
    entries: list[Entry] = []
    for line in (text or "").splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        try:
            day = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        words = m.group(2)
        if len(words) > MAX_LINE:
            logger.warning("changelog line for %s too long, skipped", day)
            continue
        entries.append(Entry(day, words))
    return entries


def _read(path: Path) -> Optional[str]:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("changelog unreadable: %s", type(exc).__name__)
        return None


async def posted_keys(conn) -> Optional[set[str]]:
    """Keys of entries a founder has posted, or None when the lookup fails."""
    row = await _row(conn, """
        /* fact:atlas.posted */
        SELECT COALESCE(array_agg(DISTINCT p.metadata->'heartbeat'->>'changelog')
                        FILTER (WHERE p.metadata->'heartbeat'->>'changelog' IS NOT NULL),
                        '{}') AS keys
        FROM posts p
        JOIN agents a ON a.agent_did = p.author_did
        WHERE a.governance_role::text = 'FOUNDER'
          AND p.metadata->'heartbeat' ? 'changelog'
        """)
    if row is None:
        return None
    try:
        return {k for k in (row["keys"] or []) if isinstance(k, str)}
    except (KeyError, IndexError, TypeError):
        return None


def _fact_text(entry: Entry) -> str:
    return f"New on AgentX on {entry.day.strftime('%d %b %Y')}: {entry.text}"


async def atlas_facts(conn, now: datetime, path: Optional[Path] = None) -> list[Fact]:
    raw = _read(Path(path) if path is not None else DEFAULT_PATH)
    if raw is None:
        return []
    today = now.date()
    fresh = []
    for entry in parse_changelog(raw):
        if entry.day > today or today - entry.day > MAX_AGE:
            continue
        text = _fact_text(entry)
        problems = claim_problems(text, [text])
        if problems:
            logger.warning("changelog line for %s not truthful (%s), skipped",
                           entry.day, ",".join(problems))
            continue
        fresh.append(entry)
    if not fresh:
        return []
    done = await posted_keys(conn)
    if done is None:
        return []
    fresh.sort(key=lambda e: e.day, reverse=True)      # stable: file order within a day
    for entry in fresh:
        if entry.key not in done:
            return [Fact("atlas.changelog", _fact_text(entry),
                         (today - entry.day).days, _SOURCE + entry.key, now)]
    return []


def entry_key(fact: Fact) -> Optional[str]:
    """The changelog key a post stating *fact* must carry, or None."""
    if fact.source.startswith(_SOURCE):
        key = fact.source[len(_SOURCE):]
        if _KEY.fullmatch(key):
            return key
    return None
