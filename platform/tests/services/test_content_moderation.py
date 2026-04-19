"""
Tests for platform/src/services/content_moderation.py

Covers:
  - Accepts clean content within length limits
  - Rejects content that exceeds MAX_CONTENT_LENGTH (returns HTTP 400)
  - Rejects title that exceeds MAX_TITLE_LENGTH (returns HTTP 400)
  - Rejects content containing profanity (returns HTTP 400)
  - Rejects title containing profanity (returns HTTP 400)
  - None title is allowed (reply-only call)
  - Error detail strings are human-readable
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.services.content_moderation import (
    MAX_CONTENT_LENGTH,
    MAX_TITLE_LENGTH,
    check_content,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _call(title: str | None, content: str) -> None:
    """Thin wrapper so test bodies stay one-liners."""
    check_content(title, content)


# ── Accepts valid content ─────────────────────────────────────────────────────

class TestAcceptsNormal:
    def test_clean_short_content(self):
        _call("Hello AgentX", "Looking for a Python coder to help with my project.")

    def test_none_title_allowed(self):
        """Replies pass title=None."""
        _call(None, "Great reply here.")

    def test_exactly_at_content_limit(self):
        _call("Fine title", "x" * MAX_CONTENT_LENGTH)

    def test_exactly_at_title_limit(self):
        _call("t" * MAX_TITLE_LENGTH, "Some content.")

    def test_unicode_content_passes(self):
        _call("Multi-lingual post", "こんにちは AgentX — 日本語テスト。")


# ── Rejects over-length ───────────────────────────────────────────────────────

class TestRejectsOverLength:
    def test_content_one_over_limit_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _call("Title", "x" * (MAX_CONTENT_LENGTH + 1))
        assert exc_info.value.status_code == 400

    def test_content_over_limit_detail_mentions_length(self):
        with pytest.raises(HTTPException) as exc_info:
            _call("Title", "x" * (MAX_CONTENT_LENGTH + 100))
        detail = exc_info.value.detail
        assert "Content too long" in detail
        assert str(MAX_CONTENT_LENGTH) in detail

    def test_title_one_over_limit_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _call("t" * (MAX_TITLE_LENGTH + 1), "Some content.")
        assert exc_info.value.status_code == 400

    def test_title_over_limit_detail_mentions_length(self):
        with pytest.raises(HTTPException) as exc_info:
            _call("t" * (MAX_TITLE_LENGTH + 50), "Some content.")
        detail = exc_info.value.detail
        assert "Title too long" in detail
        assert str(MAX_TITLE_LENGTH) in detail

    def test_title_checked_before_content(self):
        """When both title and content exceed limits, title error fires first."""
        with pytest.raises(HTTPException) as exc_info:
            _call("t" * (MAX_TITLE_LENGTH + 1), "x" * (MAX_CONTENT_LENGTH + 1))
        assert "Title too long" in exc_info.value.detail


# ── Rejects profanity ─────────────────────────────────────────────────────────

class TestRejectsProfanity:
    # better-profanity ships a built-in word list; "shit" and "ass" are in it.

    def test_profane_content_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _call("Normal title", "This is some shit content right here.")
        assert exc_info.value.status_code == 400

    def test_profane_content_detail_message(self):
        with pytest.raises(HTTPException) as exc_info:
            _call("Normal title", "What the shit is going on?")
        assert "prohibited language" in exc_info.value.detail.lower()

    def test_profane_title_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _call("Total shit title", "Perfectly fine body content.")
        assert exc_info.value.status_code == 400

    def test_profane_title_detail_message(self):
        with pytest.raises(HTTPException) as exc_info:
            _call("What the ass", "Fine content.")
        assert "prohibited language" in exc_info.value.detail.lower()

    def test_profanity_in_none_title_skipped(self):
        """title=None means no title check — only content is scanned."""
        # Should NOT raise (content is clean)
        _call(None, "This is a perfectly fine reply.")

    def test_profane_content_with_none_title_still_caught(self):
        with pytest.raises(HTTPException) as exc_info:
            _call(None, "Absolute shit reply.")
        assert exc_info.value.status_code == 400

    def test_clean_content_near_banned_word_passes(self):
        """Words that merely contain a bad string should not false-positive."""
        # "Scunthorpe problem" — better-profanity uses word-boundary matching
        # by default; we verify common false-positive candidates pass.
        _call("Assassin's Creed review", "The assassination plot was gripping.")
