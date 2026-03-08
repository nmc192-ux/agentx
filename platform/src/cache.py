"""
AgentX Platform — Redis Cache Layer
═════════════════════════════════════
Redis 7 connection with TLS + AUTH enforced.

MARCUS P0 Gap 2: All Redis connections use TLS (rediss:// scheme, port 6380)
MARCUS P1 Gap 4: Password loaded from /run/secrets/redis_password

TTL defaults:
  - Agent profiles:    5 minutes  (trust scores change frequently)
  - Capabilities:     15 minutes  (rarely changes)
  - Feed results:      2 minutes  (high churn)
  - Leaderboard:       1 minute   (real-time feel)
  - Rate limit state:  rolling     (managed by slowapi)

Usage:
    value = await cache_get("agent:did:agentx:atlas-001")
    await cache_set("agent:did:agentx:atlas-001", data, ttl=300)
    await cache_delete("agent:did:agentx:atlas-001")
"""
import json
import logging
import ssl
from typing import Any, Optional

import redis.asyncio as aioredis

from .config import get_settings

logger = logging.getLogger(__name__)

# ── Module-level client (initialized in lifespan) ─────────────────────────────
_redis: Optional[aioredis.Redis] = None

# ── TTL constants (seconds) ────────────────────────────────────────────────────
TTL_AGENT_PROFILE  = 300    #  5 min
TTL_CAPABILITIES   = 900    # 15 min
TTL_FEED           = 120    #  2 min
TTL_LEADERBOARD    = 60     #  1 min
TTL_SEARCH_RESULTS = 300    #  5 min


def _build_ssl_context() -> Optional[ssl.SSLContext]:
    """Build SSL context for Redis TLS (MARCUS P0 Gap 2)."""
    settings = get_settings()
    if not settings.redis_tls:
        logger.warning("Redis TLS disabled — not safe for production")
        return None

    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)

    if settings.redis_tls_ca:
        ctx.load_verify_locations(cafile=settings.redis_tls_ca)
    else:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        logger.warning(
            "Redis TLS: certificate verification disabled. "
            "Set REDIS_TLS_CA in production."
        )

    return ctx


async def init_cache() -> None:
    """Create the Redis connection. Called once at startup."""
    global _redis
    settings = get_settings()
    ssl_ctx = _build_ssl_context()

    logger.info(
        "Initialising Redis connection: host=%s port=%s tls=%s",
        settings.redis_host,
        settings.redis_port,
        settings.redis_tls,
    )

    _redis = aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        ssl=ssl_ctx,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_keepalive=True,
        retry_on_timeout=True,
        health_check_interval=30,
    )

    # Verify connection
    await _redis.ping()
    logger.info("Redis connection ready (TLS=%s)", settings.redis_tls)


async def close_cache() -> None:
    """Close the Redis connection. Called at shutdown."""
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
        logger.info("Redis connection closed")


def get_redis() -> aioredis.Redis:
    """Return the active Redis client. Raises if not initialised."""
    if _redis is None:
        raise RuntimeError("Cache not initialised. Call init_cache() first.")
    return _redis


# ── High-level cache helpers ───────────────────────────────────────────────────

async def cache_get(key: str) -> Optional[Any]:
    """Get a cached value. Returns None on miss or error."""
    try:
        raw = await get_redis().get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning("Cache GET failed for key=%s: %s", key, e)
        return None


async def cache_set(key: str, value: Any, ttl: int = TTL_AGENT_PROFILE) -> bool:
    """Set a cache value with TTL. Returns True on success."""
    try:
        await get_redis().setex(key, ttl, json.dumps(value, default=str))
        return True
    except Exception as e:
        logger.warning("Cache SET failed for key=%s: %s", key, e)
        return False


async def cache_delete(key: str) -> bool:
    """Delete a cache entry. Returns True if key existed."""
    try:
        result = await get_redis().delete(key)
        return result > 0
    except Exception as e:
        logger.warning("Cache DELETE failed for key=%s: %s", key, e)
        return False


async def cache_delete_pattern(pattern: str) -> int:
    """Delete all keys matching a glob pattern. Returns count deleted."""
    try:
        keys = await get_redis().keys(pattern)
        if keys:
            return await get_redis().delete(*keys)
        return 0
    except Exception as e:
        logger.warning("Cache DELETE pattern=%s failed: %s", pattern, e)
        return 0


# ── Cache key builders ─────────────────────────────────────────────────────────

def agent_key(agent_did: str) -> str:
    return f"agent:{agent_did}"

def capabilities_key(agent_did: str) -> str:
    return f"capabilities:{agent_did}"

def feed_key(agent_did: str, page: int = 1) -> str:
    return f"feed:{agent_did}:p{page}"

def leaderboard_key(domain: Optional[str] = None) -> str:
    return f"leaderboard:{domain or 'global'}"

def trust_score_key(agent_did: str) -> str:
    return f"trust:{agent_did}"


async def check_cache_health() -> dict:
    """Quick health check: ping Redis. Used by GET /health."""
    try:
        r = get_redis()
        await r.ping()
        info = await r.info("server")
        return {
            "status": "ok",
            "redis_version": info.get("redis_version", "unknown"),
            "connected_clients": info.get("connected_clients", 0),
        }
    except Exception as e:
        logger.error("Cache health check failed: %s", e)
        return {"status": "error", "detail": str(e)}
