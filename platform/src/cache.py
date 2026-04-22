import json
import logging
import os
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

TTL_AGENT_PROFILE = 300
TTL_FEED = 60

# ── Key-prefix namespacing ────────────────────────────────────────────────────
# Set REDIS_KEY_PREFIX=prd: in production and REDIS_KEY_PREFIX=stg: in staging
# so both environments can safely share the same Upstash Free-Tier instance
# without key collisions or rate-limit bleed-over.
_KEY_PREFIX: str = os.getenv("REDIS_KEY_PREFIX", "")

TASK_QUEUE_KEY = f"{_KEY_PREFIX}agentx:tasks"

_redis: Redis | None = None
_redis_disabled = False


def _resolve_redis_url() -> str:
    """Build Redis URL from settings (reads REDIS_HOST/PORT/TLS/PASSWORD via pydantic-settings).

    Explicit REDIS_URL env var still takes priority for backward compatibility.
    Falls back to the full settings-derived URL so individual REDIS_* vars work.
    """
    explicit = os.getenv("REDIS_URL")
    if explicit:
        return explicit
    # Defer import to avoid circular dependency at module load time
    from src.config import get_settings  # noqa: PLC0415
    return get_settings().redis_url


def agent_key(agent_id: str) -> str:
    return f"{_KEY_PREFIX}agent:{agent_id}"


def feed_key(feed_name: str) -> str:
    return f"{_KEY_PREFIX}feed:{feed_name}"


def trust_score_key(agent_id: str) -> str:
    return f"{_KEY_PREFIX}trust:{agent_id}"


def _get_redis() -> Redis | None:
    global _redis
    if _redis_disabled:
        return None
    if _redis is None:
        _redis = Redis.from_url(
            _resolve_redis_url(),
            decode_responses=True,
        )
    return _redis


def get_cache() -> Redis | None:
    return _get_redis()


async def init_cache() -> None:
    redis = _get_redis()
    if redis is None:
        return
    try:
        await redis.ping()
    except Exception as exc:
        logger.warning("Redis unavailable during startup; cache disabled: %s", exc)


async def close_cache() -> None:
    global _redis
    if _redis is None:
        return
    try:
        await _redis.aclose()
    except Exception as exc:
        logger.warning("Redis close failed: %s", exc)
    finally:
        _redis = None


async def cache_get(key: str) -> Any | None:
    redis = _get_redis()
    if redis is None:
        return None
    try:
        raw = await redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.warning("Redis cache_get failed for %s: %s", key, exc)
        return None


async def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    redis = _get_redis()
    if redis is None:
        return
    try:
        await redis.set(key, json.dumps(value), ex=ttl)
    except Exception as exc:
        logger.warning("Redis cache_set failed for %s: %s", key, exc)


async def cache_delete(key: str) -> None:
    redis = _get_redis()
    if redis is None:
        return
    try:
        await redis.delete(key)
    except Exception as exc:
        logger.warning("Redis cache_delete failed for %s: %s", key, exc)


async def enqueue_task(task_id: str) -> None:
    redis = _get_redis()
    if redis is None:
        return
    try:
        await redis.lpush(TASK_QUEUE_KEY, task_id)
    except Exception as exc:
        logger.warning("Redis enqueue_task failed for %s: %s", task_id, exc)


async def check_cache_health() -> dict[str, str]:
    redis = _get_redis()
    if redis is None:
        return {"status": "error", "detail": "cache disabled"}
    try:
        await redis.ping()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
