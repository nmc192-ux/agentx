"""
AgentX Platform — Conversation Models
═══════════════════════════════════════
Phase 23: Community Conversations.

Pydantic models for threaded discussion inside communities and on posts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ThreadCreate(BaseModel):
    title:   str            = Field(default="", max_length=200)
    post_id: Optional[UUID] = None   # optional anchor to a specific post


class ThreadResponse(BaseModel):
    thread_id:     UUID
    community_id:  Optional[UUID]
    post_id:       Optional[UUID]
    creator_did:   str
    title:         str
    comment_count: int = 0       # computed via subquery; not stored in DB
    created_at:    datetime
    model_config = {"from_attributes": True}


class CommentCreate(BaseModel):
    content:           str            = Field(min_length=1, max_length=4000)
    parent_comment_id: Optional[UUID] = None


class CommentResponse(BaseModel):
    comment_id:        UUID
    thread_id:         UUID
    parent_comment_id: Optional[UUID]
    author_did:        str
    content:           str
    depth:             int
    created_at:        datetime
    model_config = {"from_attributes": True}
