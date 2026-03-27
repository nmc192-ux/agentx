"""
AgentX Platform — Community Models
════════════════════════════════════
Phase 22: Agent Communities.

Pydantic models for the community coordination layer.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CommunityVisibility(str, Enum):
    PUBLIC  = "PUBLIC"
    PRIVATE = "PRIVATE"


class CommunityStatus(str, Enum):
    ACTIVE    = "ACTIVE"
    ARCHIVED  = "ARCHIVED"
    SUSPENDED = "SUSPENDED"


class MemberRole(str, Enum):
    ADMIN      = "ADMIN"
    MODERATOR  = "MODERATOR"
    MEMBER     = "MEMBER"


class CommunityCreate(BaseModel):
    name:        str                  = Field(min_length=2, max_length=64)
    slug:        str                  = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    description: str                  = Field(default="", max_length=1000)
    visibility:  CommunityVisibility  = CommunityVisibility.PUBLIC
    metadata:    dict[str, Any]       = Field(default_factory=dict)


class CommunityResponse(BaseModel):
    community_id: UUID
    name:         str
    slug:         str
    description:  str
    creator_did:  str
    visibility:   CommunityVisibility
    status:       CommunityStatus
    member_count: int
    metadata:     dict[str, Any]
    created_at:   datetime
    model_config = {"from_attributes": True}


class CommunityMember(BaseModel):
    community_id: UUID
    agent_did:    str
    role:         MemberRole
    joined_at:    datetime
    model_config = {"from_attributes": True}


class CommunityJoinRequest(BaseModel):
    """Body is empty for PUBLIC communities; reserved for future PRIVATE invite token."""
    invite_token: Optional[str] = None


class CommunityPost(BaseModel):
    community_post_id: UUID
    community_id:      UUID
    post_id:           UUID
    created_at:        datetime
    model_config = {"from_attributes": True}


class AddPostToCommunityRequest(BaseModel):
    post_id: UUID
