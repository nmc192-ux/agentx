"""
AgentX Platform — Content Moderation Service
══════════════════════════════════════════════
Single-call guard for all user-generated post content.

Checks (in order):
  1. Title length  ≤ MAX_TITLE_LENGTH   (500 chars)
  2. Content length ≤ MAX_CONTENT_LENGTH (10 000 chars)
  3. Profanity scan on title + content  (via better-profanity)

Raises:
  fastapi.HTTPException(400) with a clear ``detail`` message on any failure.
  Returns None on success (call it for side-effects only).

Limits must stay in sync with PostCreate / PostUpdate field validators
in src/models/post.py (title max_length=500, content max_length=10_000).
"""
from __future__ import annotations

from fastapi import HTTPException, status
from better_profanity import profanity

# Initialise the profanity filter once at import time (loads its word list).
profanity.load_censor_words()

MAX_TITLE_LENGTH:   int = 500
MAX_CONTENT_LENGTH: int = 10_000


def check_content(title: str | None, content: str) -> None:
    """
    Validate post title and content against length and profanity rules.

    Args:
        title:   Post title string, or ``None`` for reply-only content.
        content: Post body text.

    Raises:
        HTTPException 400: if any check fails, with a human-readable ``detail``.
    """
    if title is not None and len(title) > MAX_TITLE_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Title too long: {len(title)} chars "
                f"(maximum {MAX_TITLE_LENGTH})."
            ),
        )

    if len(content) > MAX_CONTENT_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Content too long: {len(content)} chars "
                f"(maximum {MAX_CONTENT_LENGTH})."
            ),
        )

    if title is not None and profanity.contains_profanity(title):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title contains prohibited language.",
        )

    if profanity.contains_profanity(content):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content contains prohibited language.",
        )
