"""
AgentX Platform — Agent Memory Pydantic Schemas
════════════════════════════════════════════════
Models for the server-side key-value memory store.

Endpoints that use these models:
  PUT    /agents/{agent_did}/memory/{key}  — MemoryWrite  → MemoryEntry
  GET    /agents/{agent_did}/memory/{key}  — MemoryEntry
  GET    /agents/{agent_did}/memory        — list[str]  (keys only)
  DELETE /agents/{agent_did}/memory/{key}  — 204 No Content
  DELETE /agents/{agent_did}/memory        — MemoryClearResponse
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MemoryEntry(BaseModel):
    """Full memory record — returned by PUT and GET endpoints."""
    memory_id:  str
    agent_did:  str
    key:        str
    value:      Any
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemoryWrite(BaseModel):
    """Request body for PUT /agents/{agent_did}/memory/{key}."""
    value: Any = Field(description="Any JSON-serialisable value to store")


class MemoryClearResponse(BaseModel):
    """Response body for DELETE /agents/{agent_did}/memory (clear all)."""
    deleted: int = Field(description="Number of memory entries removed")
