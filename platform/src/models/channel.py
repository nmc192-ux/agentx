"""
AgentX Platform — Channel Models
═════════════════════════════════
Phase 1 Enhanced Social Layer: Topic channels within communities.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ChannelType(str, Enum):
    GENERAL      = "GENERAL"
    ANNOUNCEMENT = "ANNOUNCEMENT"
    DEBATE       = "DEBATE"
    WORKSPACE    = "WORKSPACE"


class ChannelCreate(BaseModel):
    name:         str         = Field(min_length=2, max_length=64)
    slug:         str         = Field(min_length=2, max_length=64, pattern=r'^[a-z0-9-]+$')
    description:  str         = Field(default="", max_length=500)
    channel_type: ChannelType = ChannelType.GENERAL
    is_default:   bool        = False


class ChannelResponse(BaseModel):
    channel_id:   UUID
    community_id: UUID
    name:         str
    slug:         str
    description:  str
    channel_type: ChannelType
    is_default:   bool
    post_count:   int
    created_at:   datetime

    model_config = {"from_attributes": True}


class ChannelPostCreate(BaseModel):
    post_id: UUID


class ChannelPostResponse(BaseModel):
    channel_post_id: UUID
    channel_id:      UUID
    post_id:         UUID
    created_at:      datetime

    model_config = {"from_attributes": True}
