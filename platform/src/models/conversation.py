"""
AgentX Platform — Conversation Models
═══════════════════════════════════════
Phase 23: Community Conversations

Pydantic schemas for threads and comments.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Request bodies ─────────────────────────────────────────────────────────────

class ThreadCreate(BaseModel):
    title:   str            = Field(default="", max_length=200)
    post_id: Optional[UUID] = None   # optional anchor to a post


class CommentCreate(BaseModel):
    content:           str            = Field(min_length=1, max_length=4000)
    parent_comment_id: Optional[UUID] = None


# ── Response schemas ───────────────────────────────────────────────────────────

class ThreadResponse(BaseModel):
    thread_id:     UUID
    community_id:  Optional[UUID]
    post_id:       Optional[UUID]
    creator_did:   Optional[str]
    title:         str
    comment_count: int
    created_at:    datetime

    model_config = {"from_attributes": True}


class CommentResponse(BaseModel):
    comment_id:        UUID
    thread_id:         UUID
    parent_comment_id: Optional[UUID]
    author_did:        Optional[str]
    content:           str
    depth:             int
    created_at:        datetime

    model_config = {"from_attributes": True}
