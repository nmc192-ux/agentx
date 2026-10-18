"""
Unit tests: shipped changes for ATLAS (src/founders/changelog.py, TF-4).

What is proven (no database: a fake connection and temporary files):
  • only `- YYYY-MM-DD — words` lines are entries; headings, notes, bad
    dates and over-long lines are not
  • ATLAS gets one fact: the newest entry no founder has posted (file order
    within a day); posted entries are skipped; all posted → no fact
  • missing, empty, oversized or unreadable file → no fact; a failed
    "already posted" lookup → no fact
  • future-dated, older than 30 days, or claim-checker-failing lines → skipped
  • the fact text passes the TF-1 claim checker; its key round-trips through
    `entry_key`; `read_facts(conn, "atlas")` dispatches here
  • the real platform/CHANGELOG.md parses, every line passes the checker,
    and the image build files copy it in
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.founders import changelog as C
from src.founders import facts as F
from src.founders.truth import claim_problems

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
PLATFORM = Path(__file__).resolve().parents[2]
_TAG = re.compile(r"/\* fact:([a-z_.]+) \*/")

SAMPLE = """# AgentX — what changed

Some note with 2026-10-18 in it that is not an entry.

- 2026-10-18 — Visitors who are not signed in no longer see an error.
- 2026-10-18 — The health check answers HEAD requests.
- 2026-10-12 — Rooms can be searched.
- 2026-02-30 — Not a real date.
-2026-10-11 — Missing space.
- 2026-08-01 — Too old to be news.
"""


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, keys=(), fail=False):
        self.keys, self.fail, self.queries = list(keys), fail, 0

    def transaction(self):
        return _Tx()

    async def fetchrow(self, sql, *args):
        self.queries += 1
        assert _TAG.search(sql).group(1) == "atlas.posted"
        if self.fail:
            raise RuntimeError("broken")
        return {"keys": self.keys}


@pytest.fixture
def log(tmp_path):
    def write(text: str) -> Path:
        path = tmp_path / "CHANGELOG.md"
        path.write_text(text, encoding="utf-8")
        return path
    return write


def _keys(text: str) -> list[str]:
    return [e.key for e in C.parse_changelog(text)]


# ── parsing ──────────────────────────────────────────────────────────────────

def test_parse_only_well_formed_lines():
    entries = C.parse_changelog(SAMPLE)
    assert [(e.day.isoformat(), e.text) for e in entries] == [
        ("2026-10-18", "Visitors who are not signed in no longer see an error."),
        ("2026-10-18", "The health check answers HEAD requests."),
        ("2026-10-12", "Rooms can be searched."),
        ("2026-08-01", "Too old to be news."),
    ]


def test_parse_skips_overlong_lines():
    assert C.parse_changelog(f"- 2026-10-18 — {'x' * (C.MAX_LINE + 1)}") == []
    assert len(C.parse_changelog(f"- 2026-10-18 — {'x' * C.MAX_LINE}")) == 1


def test_keys_are_stable_and_distinct():
    a, b, c, d = _keys(SAMPLE)
    assert len({a, b, c, d}) == 4
    assert _keys(SAMPLE)[0] == a
    assert re.fullmatch(r"[0-9a-f]{16}", a)


# ── the reader ───────────────────────────────────────────────────────────────

async def test_newest_unposted_entry_first(log):
    path = log(SAMPLE)
    [fact] = await C.atlas_facts(FakeConn(), NOW, path)
    assert fact.key == "atlas.changelog"
    assert fact.text == ("New on AgentX on 18 Oct 2026: Visitors who are not signed in "
                         "no longer see an error.")
    assert fact.value == 0
    assert C.entry_key(fact) == _keys(SAMPLE)[0]
    assert claim_problems(fact.text, [fact.text]) == []


async def test_posted_entries_are_skipped(log):
    path = log(SAMPLE)
    k = _keys(SAMPLE)
    [fact] = await C.atlas_facts(FakeConn([k[0]]), NOW, path)
    assert C.entry_key(fact) == k[1]
    [fact] = await C.atlas_facts(FakeConn(k[:2]), NOW, path)
    assert C.entry_key(fact) == k[2] and fact.value == 6
    assert await C.atlas_facts(FakeConn(k[:3]), NOW, path) == []   # the rest is too old


async def test_failed_lookup_means_quiet(log):
    assert await C.atlas_facts(FakeConn(fail=True), NOW, log(SAMPLE)) == []


@pytest.mark.parametrize("content", ["", "# only a heading\n", "- 2026-10-19 — From tomorrow.\n",
                                     "- 2026-09-17 — Thirty-one days ago.\n"])
async def test_nothing_fresh_means_quiet_and_no_query(log, content):
    conn = FakeConn()
    assert await C.atlas_facts(conn, NOW, log(content)) == []
    assert conn.queries == 0


async def test_thirty_days_is_still_news(log):
    assert len(await C.atlas_facts(FakeConn(), NOW, log("- 2026-09-18 — Thirty days ago.\n"))) == 1


@pytest.mark.parametrize("words", [
    "We tested the new feed.",
    "Deployed a faster search.",
    "Shipped rooms.",
    "Search is faster today.",
    "Status: all green.",
])
async def test_claim_lines_are_skipped(log, words):
    path = log(f"- 2026-10-18 — {words}\n- 2026-10-17 — Rooms can be searched.\n")
    [fact] = await C.atlas_facts(FakeConn(), NOW, path)
    assert fact.text.endswith("Rooms can be searched.")


async def test_missing_oversized_or_binary_file(tmp_path):
    assert await C.atlas_facts(FakeConn(), NOW, tmp_path / "nope.md") == []
    assert await C.atlas_facts(FakeConn(), NOW, tmp_path) == []          # a folder
    big = tmp_path / "big.md"
    big.write_text("- 2026-10-18 — Rooms can be searched.\n" + "x" * 70_000)
    assert await C.atlas_facts(FakeConn(), NOW, big) == []
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"- 2026-10-18 \xe2 \xff\xfe\n")
    assert await C.atlas_facts(FakeConn(), NOW, bad) == []


async def test_posted_keys_ignores_junk_values():
    assert await C.posted_keys(FakeConn(["abc", None, 3])) == {"abc"}
    assert await C.posted_keys(FakeConn(fail=True)) is None


def test_entry_key_only_for_changelog_facts():
    fact = F.Fact("thea.x", "t", 1, "db:agents", NOW)
    assert C.entry_key(fact) is None
    assert C.entry_key(F.Fact("atlas.changelog", "t", 0, "file:CHANGELOG.md#zz", NOW)) is None


async def test_read_facts_dispatches_atlas(monkeypatch, log):
    path = log(SAMPLE)
    monkeypatch.setattr(C, "DEFAULT_PATH", path)
    [fact] = await F.read_facts(FakeConn(), "atlas", NOW)
    assert fact.key == "atlas.changelog"


# ── the real file and the image ──────────────────────────────────────────────

def test_real_changelog_is_well_formed_and_truthful():
    text = (PLATFORM / "CHANGELOG.md").read_text(encoding="utf-8")
    entries = C.parse_changelog(text)
    assert len(entries) >= 5
    dash_lines = [ln for ln in text.splitlines() if ln.startswith("- ")]
    assert len(dash_lines) == len(entries), "every '- ' line must be a valid entry"
    days = [e.day for e in entries]
    assert days == sorted(days, reverse=True), "newest first"
    for e in entries:
        sentence = C._fact_text(e)
        assert claim_problems(sentence, [sentence]) == [], e.text
    assert C.DEFAULT_PATH == PLATFORM / "CHANGELOG.md"


def test_image_includes_the_changelog():
    assert "COPY CHANGELOG.md ./CHANGELOG.md" in (PLATFORM / "Dockerfile.fly").read_text()
    assert "COPY platform/CHANGELOG.md ./CHANGELOG.md" in (PLATFORM / "Dockerfile").read_text()
    ignore = (PLATFORM / ".dockerignore").read_text().splitlines()
    assert "*.md" in ignore and "!CHANGELOG.md" in ignore
    assert ignore.index("!CHANGELOG.md") > ignore.index("*.md")
