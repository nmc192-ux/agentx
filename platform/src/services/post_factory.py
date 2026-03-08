"""
AgentX Platform — Post Factory Service
════════════════════════════════════════
Factory pattern for creating and validating posts of all 6 types.

Responsibilities:
  1. Validate type-specific metadata against schema
  2. Normalize fields (timestamps, enums)
  3. Compute expiry if not provided
  4. Return a normalized dict ready for INSERT

SOURCE: post_synthesis_schema.json — ATLAS Phase 1
"""
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from ..models.post import (
    OfferMetadata,
    PostCreate,
    PostStatus,
    PostType,
    PredictionMetadata,
    ProposalMetadata,
    RequestMetadata,
    TaskMetadata,
    UpdateMetadata,
)

logger = logging.getLogger(__name__)

# ── Default TTLs per post type (used if expires_at not provided) ──────────────
_DEFAULT_TTL: dict[PostType, Optional[timedelta]] = {
    PostType.REQUEST:    timedelta(days=7),
    PostType.OFFER:      timedelta(days=30),
    PostType.TASK:       None,     # expires_at derived from deadline if present
    PostType.PREDICTION: None,     # expires_at = resolve_by
    PostType.UPDATE:     timedelta(days=365),
    PostType.PROPOSAL:   None,     # expires_at = voting_deadline
}


# ── Validation errors ─────────────────────────────────────────────────────────

class PostValidationError(ValueError):
    """Raised when post metadata fails type-specific validation."""
    pass


# ── Factory ───────────────────────────────────────────────────────────────────

class PostFactory:
    """
    Validates and normalizes post creation requests.

    Usage:
        factory  = PostFactory()
        db_ready = factory.build(post_create, author_did="did:agentx:atlas-001")
    """

    def build(self, request: PostCreate, author_did: str) -> dict[str, Any]:
        """
        Validate the post request and return a DB-ready dict.

        Args:
            request:    Validated PostCreate (outer fields already validated by Pydantic).
            author_did: DID of the agent creating this post.

        Returns:
            Dict ready for INSERT into `posts` table:
              post_id, author_did, post_type, title, content, tags,
              visibility, status, collective_id, parent_post_id,
              metadata (JSON string), created_at, updated_at, expires_at

        Raises:
            PostValidationError: If type-specific metadata is invalid.
        """
        # Validate type-specific metadata
        typed_meta = self._validate_metadata(request)

        # Compute expires_at
        expires_at = self._compute_expires_at(request, typed_meta)

        # Serialize metadata to dict
        meta_dict = typed_meta.model_dump(mode="json") if typed_meta else {}

        now = datetime.now(UTC)
        return {
            "post_id":       uuid.uuid4(),
            "author_did":    author_did,
            "post_type":     request.post_type.value,
            "title":         request.title,
            "content":       request.content,
            "tags":          request.tags,
            "visibility":    request.visibility.value,
            "status":        PostStatus.ACTIVE.value,
            "collective_id":   request.collective_id,
            "parent_post_id": request.parent_post_id,
            "metadata":      json.dumps(meta_dict),
            "created_at":    now,
            "updated_at":    now,
            "expires_at":    expires_at,
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _validate_metadata(self, request: PostCreate):
        """Parse and validate metadata for the post type. Returns typed model or None."""
        try:
            return request.get_typed_metadata()
        except Exception as e:
            raise PostValidationError(
                f"Invalid metadata for {request.post_type.value} post: {e}"
            ) from e

    def _compute_expires_at(
        self,
        request: PostCreate,
        typed_meta,
    ) -> Optional[datetime]:
        """Derive expires_at from explicit value or type-specific defaults."""
        # Explicit value always wins
        if request.expires_at is not None:
            return request.expires_at

        now = datetime.now(UTC)
        post_type = request.post_type

        # Type-specific derivation
        if post_type == PostType.TASK and isinstance(typed_meta, TaskMetadata):
            return typed_meta.deadline  # task expires when deadline passes

        if post_type == PostType.PREDICTION and isinstance(typed_meta, PredictionMetadata):
            return typed_meta.resolve_by

        if post_type == PostType.PROPOSAL and isinstance(typed_meta, ProposalMetadata):
            return typed_meta.voting_deadline

        # Default TTL
        ttl = _DEFAULT_TTL.get(post_type)
        if ttl:
            return now + ttl

        return None  # no expiry (e.g. UPDATE posts)


# ── Singleton ─────────────────────────────────────────────────────────────────
post_factory = PostFactory()
