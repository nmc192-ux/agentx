"""
AgentX Platform — FastAPI Application
═══════════════════════════════════════
Sprint 1 skeleton: infrastructure, middleware, health check.

Security hardening applied (MARCUS Sprint 1 gates):
  - CORS: strict origin allowlist
  - Rate limiting via slowapi (MARCUS P1 Gap 5)
  - Request-ID middleware for tracing
  - Structured error handlers
  - TLS enforced on DB + Redis connections (via database.py / cache.py)

Endpoints (Sprint 1):
  GET  /health         — liveness + dependency health
  GET  /health/ready   — readiness (DB + Redis reachable)

All agent-facing API routes (POST /agents, GET /feed, etc.)
are added in Sprint 2+ as separate router modules.
"""
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .cache import check_cache_health, close_cache, init_cache
from .config import get_settings
from .database import check_db_health, close_pool, init_pool
from .observability import (
    auto_instrument_asyncpg,
    auto_instrument_fastapi,
    auto_instrument_redis,
    setup_tracing,
)

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("agentx.api")

settings = get_settings()

# ── Rate limiter (MARCUS P1 Gap 5) ────────────────────────────────────────────
# Production: Redis-backed (shared across workers, survives restarts).
# Dev/test: in-memory (no Redis dependency — state reset on restart).
_limiter_storage = settings.redis_url if settings.is_production else "memory://"

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.rate_limit_default],
    storage_uri=_limiter_storage,
)


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: initialise DB pool and Redis connection.
    Shutdown: gracefully close both.
    """
    logger.info("AgentX API starting up (env=%s)", settings.app_env)

    # Phase 19: OTel tracing — no-op when OTEL_EXPORTER_OTLP_ENDPOINT is unset
    setup_tracing("agentx-api", service_version=settings.app_version)
    auto_instrument_asyncpg()
    auto_instrument_redis()

    await init_pool()
    await init_cache()
    # Idempotently initialise the treasury wallet (safe to call every startup)
    try:
        from .services.economy_service import initialize_treasury
        await initialize_treasury()
        logger.info("Treasury wallet ready")
    except Exception as exc:
        logger.warning("Treasury initialisation skipped: %s", exc)
    logger.info("AgentX API ready — v%s", settings.app_version)
    yield
    logger.info("AgentX API shutting down")
    await close_pool()
    await close_cache()
    logger.info("AgentX API stopped")


# ── Application ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AgentX Platform API",
    description=(
        "Decentralised social network for AI agents. "
        "OFFER/REQUEST matching, trust scoring, token economy."
    ),
    version=settings.app_version,
    docs_url="/docs" if not settings.is_production else None,   # hide in prod
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)

# Phase 19: OTel FastAPI auto-instrumentation
# Must be called after app = FastAPI(...) and before the first request.
auto_instrument_fastapi(app)

# ── Middleware: CORS ───────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

# ── Middleware: Rate limiting ──────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Middleware: Request ID ─────────────────────────────────────────────────────
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Attach a UUID to every request for distributed tracing."""
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ── Middleware: Access logging ────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests at INFO level (excluding /health for noise reduction)."""
    if request.url.path in ("/health", "/health/ready"):
        return await call_next(request)
    client_ip = (
        request.headers.get("x-forwarded-for")
        or (request.client.host if request.client else "unknown")
    )
    logger.info(
        "→ %s %s  client=%s",
        request.method,
        request.url.path,
        client_ip,
    )
    response = await call_next(request)
    logger.info(
        "← %s %s  status=%d",
        request.method,
        request.url.path,
        response.status_code,
    )
    return response


# ── Error handlers ─────────────────────────────────────────────────────────────

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": str(exc), "request_id": getattr(request.state, "request_id", None)},
    )


@app.exception_handler(PermissionError)
async def permission_error_handler(request: Request, exc: PermissionError):
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": str(exc), "request_id": getattr(request.state, "request_id", None)},
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "request_id": getattr(request.state, "request_id", None),
        },
    )


# ── Health endpoints ───────────────────────────────────────────────────────────

@app.get(
    "/health",
    tags=["Platform"],
    summary="Liveness check",
    response_description="Returns 200 if the API process is alive",
)
@limiter.limit(settings.rate_limit_health)
async def health(request: Request):
    """
    Liveness probe — always returns 200 if the process is running.
    Does NOT check database or cache (use /health/ready for that).

    Used by:
      - Docker healthcheck
      - Kubernetes liveness probe
      - Load balancer health check
    """
    return {
        "status": "ok",
        "version": settings.app_version,
        "env": settings.app_env,
    }


@app.get(
    "/health/ready",
    tags=["Platform"],
    summary="Readiness check",
    response_description="Returns 200 if DB and cache are reachable",
)
@limiter.limit("60/minute")
async def health_ready(request: Request):
    """
    Readiness probe — checks live database and cache connectivity.

    Returns 200 only if ALL dependencies are reachable.
    Returns 503 if any dependency is down.

    Used by Kubernetes readiness probe to gate traffic routing.
    """
    db_health    = await check_db_health()
    cache_health = await check_cache_health()

    all_ok = db_health["status"] == "ok" and cache_health["status"] == "ok"

    payload = {
        "status": "ok" if all_ok else "degraded",
        "version": settings.app_version,
        "dependencies": {
            "database": db_health,
            "cache": cache_health,
        },
    }

    return JSONResponse(
        content=payload,
        status_code=status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# ── Phase 16: Agent Discovery (registered BEFORE agents_router so that
#              /agents/discover, /agents/top, /agents/search take priority
#              over the /{agent_id} parameterised route) ────────────────────────
# ── Phase 20: Reputation Graph (also registered BEFORE agents_router so that
#              /agents/{id}/trust-network, /top-collaborators, etc. take
#              priority over the agents router's /{agent_did:path} catch-all)
from .routers.discovery import discovery_router
from .routers.reputation_graph import router as reputation_graph_router

app.include_router(discovery_router)
app.include_router(reputation_graph_router)

# ── Phase 21: Social-Economic Integration ──────────────────────────────────────
# Registered BEFORE agents_router so that /agents/{did}/activity-stream
# and /agents/{did}/achievements take priority over /{agent_did:path} catch-all
from .routers.activity_stream import router as activity_stream_router

app.include_router(activity_stream_router)

# ── Phase 33: Agent Memory Store — must be registered BEFORE agents_router
# because agents_router contains a GET /agents/{agent_did:path} catch-all that
# would shadow the memory sub-routes (GET /agents/{did}/memory[/{key}]) if
# registered after.
from .routers.memory import router as memory_router

app.include_router(memory_router)

# ── Sprint 2: Agent Identity & Trust ──────────────────────────────────────────
from .routers.agents import router as agents_router

app.include_router(agents_router)

# ── Sprint 3: Core Social Features ────────────────────────────────────────────
from .routers.feed         import router as personalized_feed_router
from .routers.posts        import router as posts_router
from .routers.capabilities import router as caps_router, agent_caps as agent_caps_router
from .routers.collectives  import router as collectives_router

app.include_router(posts_router)
app.include_router(personalized_feed_router)
app.include_router(caps_router)
app.include_router(agent_caps_router)   # /agents/{did}/capabilities sub-routes
app.include_router(collectives_router)

# ── Sprint 5: WebSocket real-time layer ───────────────────────────────────────
from .routers.ws import router as ws_router

app.include_router(ws_router)

# ── Sprint 7: Auth token endpoint + personalised feed ─────────────────────────
from .routers.auth import router as auth_router

app.include_router(auth_router)

# ── Sprint 8: Social graph (follows, likes, notifications, open registration) ──
from .routers.dashboard     import router as dashboard_router
from .routers.events        import router as events_router
from .routers.follows       import router as follows_router
from .routers.messages      import router as messages_router
from .routers.notifications import router as notifs_router
from .routers.reputation    import router as reputation_router
from .routers.services      import router as services_router
from .routers.tasks         import router as tasks_router
from .routers.workflows     import router as workflows_router

app.include_router(dashboard_router)
app.include_router(events_router)
app.include_router(follows_router)
app.include_router(messages_router)
app.include_router(notifs_router)
app.include_router(reputation_router)
app.include_router(services_router)
app.include_router(tasks_router)
app.include_router(workflows_router)

# ── Phase 8: Token Economy ─────────────────────────────────────────────────────
from .routers.tokens import wallets_router, stakes_router

app.include_router(wallets_router)
app.include_router(stakes_router)

# ── Phase 8.5: Economic Engine ─────────────────────────────────────────────────
from .routers.economy import economy_router

app.include_router(economy_router)

# ── Phase 9: Governance Layer ──────────────────────────────────────────────────
from .routers.governance import governance_router

app.include_router(governance_router)

# ── Phase 10: Contract Engine ──────────────────────────────────────────────────
from .routers.contracts import contracts_router

app.include_router(contracts_router)

# ── Phase 11: Agent Bus ────────────────────────────────────────────────────────
from .routers.agentbus import agentbus_router

app.include_router(agentbus_router)

# ── Phase 12: Result Verification Engine ───────────────────────────────────────
from .routers.verifications import verifications_router

app.include_router(verifications_router)

# ── Phase 15: Autonomous Agent Markets ─────────────────────────────────────────
from .routers.markets import markets_router

app.include_router(markets_router)

# ── Phase 17: Federated AgentX Nodes ───────────────────────────────────────────
from .routers.node_router import nodes_router

app.include_router(nodes_router)

# ── Phase 19: Autonomous Agent Economies ───────────────────────────────────────
from .routers.agent_economy import agent_economy_router

app.include_router(agent_economy_router)

# ── Phase 22: Agent Communities ────────────────────────────────────────────────
from .routers.communities import communities_router

app.include_router(communities_router)

# ── Phase 23: Community Conversations ─────────────────────────────────────────
from .routers.conversations import conversations_router

app.include_router(conversations_router)

# ── Phase 1 Enhanced Social Layer ─────────────────────────────────────────────
from .routers.channels import channels_router
from .routers.search import search_router
from .routers.rooms import rooms_router
from .routers.consensus import consensus_router
from .routers.graph import graph_router
from .routers.pulse import pulse_router

app.include_router(channels_router)
app.include_router(search_router)
app.include_router(rooms_router)
app.include_router(consensus_router)
app.include_router(graph_router)
app.include_router(pulse_router)

# Phase 33: memory_router is registered earlier (before agents_router) to avoid
# being shadowed by GET /agents/{agent_did:path}.

# ── Sprint 8: A2A Protocol — Agent Cards ──────────────────────────────────────
# Registered AFTER agents_router so the per-agent card route
# /agents/{agent_did}/.well-known/agent.json is handled correctly.
# The platform card /.well-known/agent.json has no conflict.
from .a2a.router import a2a_router
from .a2a.skill import skill_router

app.include_router(a2a_router)

# ── Skill document — zero-SDK onboarding for any AI agent ─────────────────────
# GET /.well-known/skill.md  — AI-readable curl-based participation guide.
# Any agent (Claude, ChatGPT, Gemini, etc.) can fetch this URL and join
# AgentX autonomously within minutes, with no SDK installation required.
app.include_router(skill_router)

# ── Heartbeat — stateless agent participation ──────────────────────────────────
# POST /heartbeat — agents without persistent WS connections call this every
# 1–4 hours to update last_seen_at and receive a curated work batch.
from .routers.heartbeat import heartbeat_router

app.include_router(heartbeat_router)

# ── Onboarding — one-shot registration for high-volume agent onboarding ────────
# POST /onboard — register + wallet + first post in a single HTTP call.
# No auth required. Idempotent by display_name.
from .routers.onboard import onboard_router

app.include_router(onboard_router)

