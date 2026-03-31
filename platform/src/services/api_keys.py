"""
AgentX Platform — API Key Service
══════════════════════════════════
Phase 5: Programmatic access without JWT dance

Key format: agx_<prefix>_<secret>
  prefix — 8 chars, stored in DB for lookup
  secret — 32 chars, hashed (SHA-256) and stored

Authentication flow:
  1. Client sends X-API-Key: agx_<prefix>_<secret>
  2. Lookup api_keys by key_prefix
  3. Hash the provided secret, compare to stored key_hash
  4. Return the associated agent_did
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from ..database import get_db, transaction

logger = logging.getLogger(__name__)

KEY_PREFIX_LENGTH = 8
KEY_SECRET_LENGTH = 32


def _generate_key() -> tuple[str, str, str]:
    """Generate a new API key. Returns (full_key, prefix, secret_hash)."""
    prefix = secrets.token_hex(KEY_PREFIX_LENGTH // 2)  # 8 hex chars
    secret = secrets.token_urlsafe(KEY_SECRET_LENGTH)
    full_key = f"agx_{prefix}_{secret}"
    key_hash = hashlib.sha256(secret.encode()).hexdigest()
    return full_key, prefix, key_hash


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


async def create_api_key(
    agent_did: str,
    name: str = "default",
    scopes: list[str] | None = None,
    expires_in_days: int | None = None,
) -> dict:
    """Create a new API key for an agent. Returns the full key (shown once)."""
    full_key, prefix, key_hash = _generate_key()
    scope_list = scopes or ["read", "write"]

    expires_at = None
    if expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    async with transaction() as conn:
        # Verify agent exists
        agent_exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_did = $1", agent_did,
        )
        if not agent_exists:
            raise ValueError(f"Agent not found: {agent_did}")

        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (agent_did, key_prefix, key_hash, name, scopes, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING key_id, agent_did, key_prefix, name, scopes, is_active, expires_at, created_at
            """,
            agent_did, prefix, key_hash, name, scope_list, expires_at,
        )

    result = _row_to_response(dict(row))
    result["api_key"] = full_key
    return result


async def validate_api_key(raw_key: str) -> dict | None:
    """
    Validate an API key and return the agent_did + scopes if valid.
    Returns None if invalid, expired, or deactivated.
    """
    if not raw_key.startswith("agx_"):
        return None

    parts = raw_key.split("_", 2)  # agx, prefix, secret
    if len(parts) != 3:
        return None

    prefix = parts[1]
    secret = parts[2]
    secret_hash = _hash_secret(secret)

    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT key_id, agent_did, key_hash, scopes, is_active, expires_at
            FROM api_keys
            WHERE key_prefix = $1 AND is_active = TRUE
            """,
            prefix,
        )

    if row is None:
        return None

    if row["key_hash"] != secret_hash:
        return None

    # Check expiry
    if row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc):
        return None

    # Update last_used_at (fire-and-forget)
    try:
        async with transaction() as conn:
            await conn.execute(
                "UPDATE api_keys SET last_used_at = CURRENT_TIMESTAMP WHERE key_id = $1",
                row["key_id"],
            )
    except Exception:
        pass

    return {
        "key_id": row["key_id"],
        "agent_did": row["agent_did"],
        "scopes": list(row["scopes"]),
    }


async def list_api_keys(agent_did: str) -> list[dict]:
    """List all API keys for an agent (never returns the secret)."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT key_id, key_prefix, name, scopes, is_active, last_used_at, expires_at, created_at
            FROM api_keys
            WHERE agent_did = $1
            ORDER BY created_at DESC
            """,
            agent_did,
        )
    return [_row_to_response(dict(r)) for r in rows]


async def revoke_api_key(key_id: UUID, agent_did: str) -> dict:
    """Deactivate an API key."""
    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            UPDATE api_keys
            SET is_active = FALSE
            WHERE key_id = $1 AND agent_did = $2
            RETURNING key_id
            """,
            key_id, agent_did,
        )
    if row is None:
        raise ValueError(f"API key not found: {key_id}")
    return {"key_id": str(key_id), "revoked": True}


def _row_to_response(row: dict) -> dict:
    return {
        "key_id": row["key_id"],
        "name": row.get("name", "default"),
        "key_prefix": row["key_prefix"],
        "scopes": list(row.get("scopes", [])),
        "is_active": row.get("is_active", True),
        "last_used_at": row.get("last_used_at"),
        "expires_at": row.get("expires_at"),
        "created_at": row["created_at"],
    }
