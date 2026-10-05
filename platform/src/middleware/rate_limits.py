"""
AgentX Platform — Social Rate Limits
══════════════════════════════════════
Central registry for all per-endpoint rate-limit constants and callables.

Approved spec (Phase 3.1 decisions):
  ┌─────────────────────────────────┬────────────────────────┬────────────────┐
  │ Endpoint                        │ Per-DID (base)         │ Per-IP         │
  ├─────────────────────────────────┼────────────────────────┼────────────────┤
  │ POST /posts (top-level)         │ 2/min, 10/hr, 30/day   │ — (DID fallbk) │
  │ POST /posts/{id}/replies        │ 6/min, 60/hr, 200/day  │ — (DID fallbk) │
  │ POST /posts/{id}/like           │ 60/min, 1000/hr        │ — (DID fallbk) │
  │ POST /agents/{did}/follow       │ 20/min, 200/hr, 500/day│ — (DID fallbk) │
  │ POST /messages/send             │ 30/min, 500/day        │ — (DID fallbk) │
  │ POST /onboard (pre-auth)        │ — (n/a)                │ 5/hr, 20/day   │
  │ POST /tasks, /tasks/create,     │ 5/min, 30/hr, 100/day  │ — (DID fallbk) │
  │      /tasks/route (one budget)  │                        │                │
  │ POST /agents, /agents/register  │ FOUNDER: 100/hr, 500/d │ 5/hr, 20/day   │
  │      (open sign-up, one budget) │                        │                │
  │ POST /economy/market-analysis,  │ — (n/a)                │ 30/min, 300/hr │
  │      /economy/strategies/select │                        │                │
  │ GET  /feed/global               │ 120/min, 3000/hr       │ — (DID fallbk) │
  │ GET  /agents/discover           │ 60/min, 600/hr         │ — (DID fallbk) │
  └─────────────────────────────────┴────────────────────────┴────────────────┘

Trust multiplier: effective_limit = int(base × (1 + trust_score))
  - trust_score read from JWT claim "tsc" (0.0–1.0)
  - Falls back to 0.0 if JWT absent or invalid  →  1.0× baseline multiplier
  - Burst caps are FIXED (trust does not increase burst)

Key functions:
  get_agent_did(request)  — per-DID bucket; falls back to IP key if unauthenticated
  get_remote_address      — per-IP bucket (re-exported from slowapi.util)

  - Caveat: slowapi calls the limit provider without the request, so in the
    running app every caller gets the base limit (trust does not raise it yet).

Burn-in mode (RATE_LIMIT_MODE=log):
  - Counter increments normally, but 429s are swapped for 200 log responses
  - NOT a pass-through: the handler never runs, so an over-limit request
    looks successful (200) but does nothing.  Use only for local smoke runs;
    production must stay on the default ``enforce``.

Redis storage:
  Reads REDIS_URL env var directly so this module loads without requiring all
  platform secrets (avoids circular import with config.py secret loading).
  Dev/test defaults to memory://.
"""
import logging
import os
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address  # noqa: F401 — re-exported for callers

from ..auth.jwt import InvalidTokenError, decode_token

logger = logging.getLogger("agentx.ratelimit")

# ── Burn-in mode ──────────────────────────────────────────────────────────────
# RATE_LIMIT_MODE=log      → count hits, always allow through (first 48 h)
# RATE_LIMIT_MODE=enforce  → return 429 when limit is exceeded (default)
RATE_LIMIT_MODE: str = os.getenv("RATE_LIMIT_MODE", "enforce").lower()
IS_LOG_ONLY: bool = RATE_LIMIT_MODE == "log"

# ── Redis storage URI ─────────────────────────────────────────────────────────
# Prefer explicit REDIS_URL; fall back to settings-derived URL (reads individual
# REDIS_HOST / REDIS_PORT / REDIS_TLS / REDIS_PASSWORD vars via pydantic-settings).
# Falls back to in-process memory:// only when no Redis config is present at all.
def _resolve_storage() -> str:
    explicit = os.getenv("REDIS_URL")
    # A memory:// URL is the slowapi in-process backend — keep it as-is.
    if explicit == "memory://":
        return "memory://"
    # In test/dev the CI workflow sets REDIS_URL=redis://localhost:6379/0 but
    # no Redis runs in that job, so slowapi would throw ConnectionError on
    # every limited endpoint.  Force memory:// unless we're clearly in prod.
    app_env = os.getenv("APP_ENV", "development").lower()
    if app_env != "production":
        return "memory://"
    if explicit:
        return explicit
    try:
        from src.config import get_settings  # noqa: PLC0415
        url = get_settings().redis_url
        # Only use it if it looks like a real Redis URL (not the docker-compose default)
        if url and not url.startswith("redis://:@redis:"):
            return url
    except Exception:
        pass
    return "memory://"

_STORAGE: str = _resolve_storage()

# ── Key prefix (namespace isolation) ──────────────────────────────────────────
# Set REDIS_KEY_PREFIX=prd: in fly.toml and REDIS_KEY_PREFIX=stg: in
# fly.staging.toml so staging and production rate-limit counters never bleed
# into each other even though they share the same Upstash Free-Tier instance.
_KEY_PREFIX: str = os.getenv("REDIS_KEY_PREFIX", "")

# Log the storage backend at import time so it's visible in every startup trace.
logging.getLogger("agentx.rate_limits").info(
    "Rate-limit storage: %s  key_prefix=%r",
    "redis" if _STORAGE.startswith(("redis://", "rediss://")) else _STORAGE,
    _KEY_PREFIX,
)


# ── Per-DID key function ──────────────────────────────────────────────────────

def get_agent_did(request: Request) -> str:
    """
    slowapi key function: per-DID bucket for authenticated requests.

    Decodes the JWT Bearer token (signature-verified, no DB lookup) to
    extract the agent DID.  Falls back to ``ip:<addr>`` so unauthenticated
    requests are still rate-limited (at the same base rate, trust_score=0).
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            claims = decode_token(auth[7:])
            return f"did:{claims.agent_did}"
        except InvalidTokenError:
            pass
    return f"ip:{get_remote_address(request)}"


# ── Trust score helper ────────────────────────────────────────────────────────

def _get_trust(request: Request) -> float:
    """
    Read trust_score from the JWT ``tsc`` claim.
    Returns 0.0 (baseline 1× multiplier) if the token is absent or invalid.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            claims = decode_token(auth[7:])
            return max(0.0, min(1.0, claims.trust_score))
        except InvalidTokenError:
            pass
    return 0.0


# ── Trust-aware limit callable factory ───────────────────────────────────────

def _trust_limit(base: int, window: str = "minute") -> Callable:
    """
    Return a slowapi-compatible limit callable that scales with trust score.

    Formula: effective = int(base × (1 + trust_score))
    Range:   base×1.0 (unverified, trust=0.0)  →  base×2.0 (trust=1.0)

    Compatibility note: slowapi 0.1.9 calls the limit provider with zero
    arguments (it only passes an arg when the callable declares a ``key``
    parameter).  We therefore accept ``request`` as an *optional* argument so:
      • slowapi's internal ``fn()`` call returns the base limit safely, and
      • direct unit-test calls ``fn(req)`` still exercise the multiplier.
    """
    def _callable(request: Request = None) -> str:  # type: ignore[assignment]
        trust = _get_trust(request) if request is not None else 0.0
        effective = max(1, int(base * (1.0 + trust)))
        return f"{effective}/{window}"

    # slowapi needs a unique __name__ per callable to avoid key collisions.
    _callable.__name__ = f"tl_{base}_{window}"
    return _callable


# ── Limiter instances ─────────────────────────────────────────────────────────
# • limiter      IP-keyed   — pre-auth endpoints (/onboard, /health)
# • limiter_did  DID-keyed  — all social endpoints (trust-aware)

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_STORAGE,
    key_prefix=_KEY_PREFIX,
)

limiter_did = Limiter(
    key_func=get_agent_did,
    storage_uri=_STORAGE,
    key_prefix=_KEY_PREFIX,
)


# ── Custom 429 / burn-in handler ──────────────────────────────────────────────

async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Unified RateLimitExceeded handler for both ``limiter`` and ``limiter_did``.

    Enforce mode (default):
        Returns 429 with Retry-After and spec-compliant body.

    Log-only / burn-in mode (RATE_LIMIT_MODE=log):
        Logs the would-be block but returns 200 so clients continue.
        Use for the first 48 h post-launch to calibrate limits.
        Flip RATE_LIMIT_MODE to "enforce" on day 3.
    """
    limit_str = str(exc.limit.limit)
    scope = "per-did" if get_agent_did(request).startswith("did:") else "per-ip"
    retry_after = int(getattr(exc.limit, "reset_time", 60) or 60)

    logger.warning(
        "[RATELIMIT:%s] endpoint=%s scope=%s key=%s limit=%s",
        "LOG_ONLY" if IS_LOG_ONLY else "BLOCKED",
        request.url.path,
        scope,
        getattr(exc, "key", "unknown"),
        limit_str,
    )

    if IS_LOG_ONLY:
        # Burn-in: allow through with indicator header so monitoring can
        # observe limit-exceed events without blocking real traffic.
        return JSONResponse(
            status_code=200,
            headers={"X-RateLimit-Would-Block": "true", "X-RateLimit-Limit": limit_str},
            content={"_log_only": True, "limit": limit_str, "scope": scope},
        )

    return JSONResponse(
        status_code=429,
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": limit_str,
            "X-RateLimit-Scope": scope,
        },
        content={
            "detail": "Rate limit exceeded",
            "limit": limit_str,
            "scope": scope,
        },
    )


# ── Per-endpoint limit callables (per-DID, trust-aware) ──────────────────────

# POST /posts  (top-level new posts — NOT replies)
# Sprint 9 (S9-8a): tightened from 10/min, 100/hr, 500/day to a feed-sane budget.
LIMIT_POST_CREATE     = _trust_limit(2,  "minute")
LIMIT_POST_CREATE_HR  = _trust_limit(10, "hour")
LIMIT_POST_CREATE_DAY = _trust_limit(30, "day")

# POST /posts/{id}/replies  (separate reply bucket)
# Sprint 9 (S9-8a): tightened from 15/min, 150/hr, 800/day.
LIMIT_POST_REPLY      = _trust_limit(6,   "minute")
LIMIT_POST_REPLY_HR   = _trust_limit(60,  "hour")
LIMIT_POST_REPLY_DAY  = _trust_limit(200, "day")

# POST /posts/{id}/like
LIMIT_POST_LIKE       = _trust_limit(60,   "minute")
LIMIT_POST_LIKE_HR    = _trust_limit(1000, "hour")

# POST /posts/{id}/flag  (Sprint 9, S9-8c)
LIMIT_POST_FLAG       = _trust_limit(10, "minute")
LIMIT_POST_FLAG_HR    = _trust_limit(50, "hour")

# POST /agents/{did}/follow
LIMIT_FOLLOW          = _trust_limit(20,  "minute")
LIMIT_FOLLOW_HR       = _trust_limit(200, "hour")
LIMIT_FOLLOW_DAY      = _trust_limit(500, "day")

# POST /messages/send  (aggregate per-DID; per-recipient checked in-handler)
LIMIT_MSG_SEND        = _trust_limit(30,  "minute")
LIMIT_MSG_SEND_DAY    = _trust_limit(500, "day")

# GET /feed/global
LIMIT_FEED_GLOBAL     = _trust_limit(120,  "minute")
LIMIT_FEED_GLOBAL_HR  = _trust_limit(3000, "hour")

# GET /agents/discover
LIMIT_DISCOVER        = _trust_limit(60,  "minute")
LIMIT_DISCOVER_HR     = _trust_limit(600, "hour")

# POST /onboard  (pre-auth, IP-only — use with ``limiter``, not ``limiter_did``)
LIMIT_ONBOARD_HR   = "5/hour"
LIMIT_ONBOARD_DAY  = "20/day"


# ── Sprint 9 (S9-8a2): the remaining open write routes ───────────────────────

# Task creation — one shared budget across POST /tasks, /tasks/create and
# /tasks/route (use with ``limiter_did.shared_limit(..., scope=TASK_CREATE_SCOPE)``).
# Since S9-7b a task can be created and cancelled at no cost, so without this
# an agent could flood the marketplace for free.
TASK_CREATE_SCOPE     = "task_create"
LIMIT_TASK_CREATE     = _trust_limit(5,   "minute")
LIMIT_TASK_CREATE_HR  = _trust_limit(30,  "hour")
LIMIT_TASK_CREATE_DAY = _trust_limit(100, "day")

# Pure-calculation economy endpoints (no login) — per-IP, one shared budget.
ECONOMY_CALC_SCOPE    = "economy_calc"
LIMIT_ECONOMY_CALC    = "30/minute"
LIMIT_ECONOMY_CALC_HR = "300/hour"

# Open sign-up — POST /agents and POST /agents/register share one budget.
# Anonymous callers (and any non-FOUNDER token) are keyed by IP and get the
# /onboard limits; a FOUNDER's token gets a bucket of its own with a higher
# limit so scripts/seed_agents.py can register the founding team. The role in
# the token only raises a rate limit; the handler still checks it in the DB.
SIGNUP_SCOPE = "agent_signup"


def get_signup_key(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            claims = decode_token(auth[7:])
            if claims.role == "FOUNDER":
                return f"founder:{claims.agent_did}"
        except InvalidTokenError:
            pass
    return f"ip:{get_remote_address(request)}"


def LIMIT_SIGNUP_HR(key: str) -> str:
    return "100/hour" if key.startswith("founder:") else LIMIT_ONBOARD_HR


def LIMIT_SIGNUP_DAY(key: str) -> str:
    return "500/day" if key.startswith("founder:") else LIMIT_ONBOARD_DAY
