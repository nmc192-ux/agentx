"""
AgentX — BRUNO  (Infrastructure Lead)
════════════════════════════════════════
Phase 2 lead. Builds the entire backend infrastructure:
PostgreSQL, Redis, FastAPI, WebSocket layer, Docker/K8s, CI/CD.
ATLAS Phase 1 artifacts are injected into the system prompt at runtime
so BRUNO always has the canonical schemas as ground truth.
"""
from pathlib import Path
from .base_agent import BaseAgent

# ── Atlas artifact loader ─────────────────────────────────────────────────────

def _load_atlas_artifact(filename: str) -> str:
    """Load an ATLAS artifact from shared workspace at import time."""
    shared = Path(__file__).parent.parent / "workspace" / "shared" / filename
    if shared.exists():
        content = shared.read_text(encoding="utf-8")
        # Truncate very large files to avoid token overload
        if len(content) > 8000:
            content = content[:8000] + "\n... [truncated — full file in workspace/shared/]"
        return content
    return f"[{filename} not yet published by ATLAS — run Phase 1 first]"


def _build_system_prompt() -> str:
    """Build BRUNO's system prompt, injecting ATLAS artifacts at runtime."""

    db_schema  = _load_atlas_artifact("agentx_db_schema.sql")
    api_yaml   = _load_atlas_artifact("agentx_api_v1.yaml")
    id_schema  = _load_atlas_artifact("agent_identity_schema_v3.json")
    proto      = _load_atlas_artifact("protocol_layers.md")

    return f"""
You are BRUNO — Infrastructure Lead of AgentX, the world's first social network
designed, built, and governed entirely by autonomous AI agents.

╔══════════════════════════════════════════════════════════════════════╗
║                    IDENTITY & AUTHORITY                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  agentDID   : did:agentx:bruno-001                                   ║
║  Role       : Infrastructure Lead                                    ║
║  Tier       : Founding · Elite                                       ║
║  Trust Score: 0.95  (seeded at genesis)                              ║
║  Mandate    : Build every server, database, container, and network   ║
║               layer that AgentX runs on. Implement ATLAS's schemas   ║
║               exactly as designed — no deviation without a proposal. ║
╚══════════════════════════════════════════════════════════════════════╝

CAPABILITIES:
  PostgreSQL 16 · Redis 7 · FastAPI (async) · SQLAlchemy 2 (async)
  Alembic · Docker · Docker Compose · Kubernetes · Nginx
  WebSocket · GitHub Actions CI/CD · asyncpg · Pydantic v2
  Python async/await · Connection pooling · pgvector · JWT

════════════════════════════════════════════════════════════════════════
PHASE 2 MANDATE
════════════════════════════════════════════════════════════════════════

You are building the backend that makes AgentX real. You have 7 deliverables:

  1. alembic_setup      — Alembic env + first migration from ATLAS DB schema
  2. sqlalchemy_models  — Full async SQLAlchemy ORM models for all tables
  3. redis_config       — Redis cache layer + session management
  4. fastapi_app        — FastAPI app with all routers from ATLAS OpenAPI spec
  5. websocket_layer    — Real-time post streaming via WebSocket
  6. docker_compose     — Dev environment (Postgres + Redis + API + pgAdmin)
  7. kubernetes         — Production K8s manifests (Deployments, Services, HPA)

QUALITY STANDARDS:
  ▸ Every file is production-ready Python — no pseudocode, no TODOs.
  ▸ All async — use asyncpg + SQLAlchemy async engine throughout.
  ▸ Pydantic v2 for all request/response models.
  ▸ Environment variables via python-dotenv — zero hardcoded secrets.
  ▸ Proper error handling — HTTPException with correct status codes.
  ▸ Type hints everywhere.
  ▸ Follow ATLAS's schemas exactly. If you see a discrepancy, note it.

════════════════════════════════════════════════════════════════════════
ATLAS PHASE 1 ARTIFACTS (your ground truth — read carefully)
════════════════════════════════════════════════════════════════════════

─── DATABASE SCHEMA (agentx_db_schema.sql) ─────────────────────────────
{db_schema}

─── OPENAPI CONTRACT (agentx_api_v1.yaml) ──────────────────────────────
{api_yaml}

─── AGENT IDENTITY SCHEMA (agent_identity_schema_v3.json) ──────────────
{id_schema}

─── PROTOCOL LAYERS (protocol_layers.md) ───────────────────────────────
{proto}

════════════════════════════════════════════════════════════════════════
BEHAVIORAL PRINCIPLES
════════════════════════════════════════════════════════════════════════

• ATLAS's schemas are law. Implement them exactly.
• Build for horizontal scale from day one (stateless API, external cache).
• Security first: JWT auth, input validation, rate limiting, no secrets in code.
• Every ADR (Architecture Decision Record) gets a comment block in the code.
• Idempotent migrations — safe to run multiple times.
• All database operations use transactions with proper rollback.
• Log everything: structured JSON logs with request_id, agent_did, ts.
""".strip()


# ── BRUNO Agent Class ─────────────────────────────────────────────────────────

class Bruno(BaseAgent):
    """BRUNO — Infrastructure Lead. Phase 2 lead."""

    def __init__(self, model: str = ""):
        super().__init__(
            name          = "BRUNO",
            emoji         = "⚙️",
            role          = "Infrastructure Lead",
            system_prompt = _build_system_prompt(),   # ATLAS artifacts injected here
            model         = model,
        )

    def _banner(self, step: int, total: int, title: str) -> None:
        print(f"\n{'━' * 68}")
        print(f"  PHASE 2  ·  Step {step}/{total}  ·  {title}")
        print(f"{'━' * 68}")

    # ── Phase 2 Deliverables ────────────────────────────────────────────────

    def generate_alembic_setup(self) -> str:
        """
        Deliverable 1: alembic_setup.md
        Complete Alembic migration environment + first migration.
        """
        self._banner(1, 7, "Alembic Migration Setup")

        prompt = """
Using the PostgreSQL schema from ATLAS (in your system prompt), produce a
complete Alembic async migration environment.

Deliver these files with FULL content (no placeholders):

## File: alembic.ini
Complete alembic.ini — point sqlalchemy.url to env var DATABASE_URL,
set script_location = alembic, configure logging.

## File: alembic/env.py
Full async env.py using:
- asyncpg driver
- SQLAlchemy async engine
- target_metadata from models.py
- run_migrations_online() with async support
- Proper handling of DATABASE_URL env var

## File: alembic/versions/0001_initial_schema.py
Complete first migration that creates ALL tables from the ATLAS DB schema:
- All enums (CREATE TYPE)
- All tables in dependency order (respecting FK constraints)
- All indexes
- All foreign key constraints
- The update_updated_at() trigger function
- The recalculate_trust_score() trigger
- All views (agent_leaderboard, active_tasks, pending_proposals)
Include proper upgrade() and downgrade() functions.

## File: src/database.py
Async database connection module:
- AsyncEngine with asyncpg
- AsyncSessionLocal factory
- DATABASE_URL from env
- get_db() dependency for FastAPI
- Connection pool: pool_size=20, max_overflow=10, pool_timeout=30

Return each file clearly labeled with ## File: filename headers.
No explanations between files — just the file contents.
""".strip()

        response = self.think(prompt, max_tokens=16000)
        self.save("alembic_setup.md", response, "Alembic migration setup")
        self.publish("alembic_setup.md", response, "PUBLISHED: Alembic Setup — Phase 2 Step 1")
        return response

    def generate_sqlalchemy_models(self) -> str:
        """
        Deliverable 2: sqlalchemy_models.md
        Complete async SQLAlchemy ORM models for all tables.
        """
        self._banner(2, 7, "SQLAlchemy ORM Models")

        prompt = """
Using the PostgreSQL schema from ATLAS (in your system prompt), produce
complete async SQLAlchemy 2.0 ORM models for ALL tables.

Deliver one file: src/models.py

Requirements:
- Use SQLAlchemy 2.0 declarative style with DeclarativeBase
- Async compatible (no sync-only features)
- All enums as Python Enum classes mirroring the DB enums
- All tables:
  agents, agent_trust_breakdown, capabilities, agent_capabilities,
  posts, post_reactions, collectives, collective_members,
  tasks, proposals, votes, token_balances, token_transactions,
  audit_log, endorsements, sla_records
- Proper Column types matching PostgreSQL types exactly:
  UUID with uuid-ossp default, DECIMAL, JSONB, TIMESTAMP WITH TIME ZONE
- All relationships with back_populates
- All indexes matching the ATLAS schema
- __repr__ methods for key models
- Pydantic v2 schema classes (BaseModel) for API request/response:
  AgentCreate, AgentUpdate, AgentResponse, TrustScoreResponse,
  PostCreate, PostUpdate, PostResponse,
  CapabilityResponse, CollectiveCreate, CollectiveResponse,
  ProposalCreate, VoteCreate, TokenTransferRequest,
  PaginatedResponse (generic), ErrorResponse

## File: src/models.py
[full SQLAlchemy models]

## File: src/schemas.py
[full Pydantic v2 schemas]

No explanations — just the code.
""".strip()

        response = self.think(prompt, max_tokens=16000)
        self.save("sqlalchemy_models.md", response, "SQLAlchemy ORM models")
        self.publish("sqlalchemy_models.md", response,
                     "PUBLISHED: SQLAlchemy Models — Phase 2 Step 2")
        return response

    def generate_redis_config(self) -> str:
        """
        Deliverable 3: redis_config.md
        Redis cache layer + session management.
        """
        self._banner(3, 7, "Redis Cache Layer")

        prompt = """
Produce the complete Redis cache layer for AgentX.

## File: src/cache.py
Full Redis async client using redis-py (async):
- REDIS_URL from env
- Connection pool (max_connections=50)
- CacheManager class with methods:
  - get(key) / set(key, value, ttl) / delete(key) / exists(key)
  - get_json(key) / set_json(key, data, ttl)
  - invalidate_pattern(pattern) — for bulk cache busting
- Cache key namespacing: "agentx:{entity}:{id}"
- TTL constants:
  AGENT_PROFILE_TTL = 300      # 5 minutes
  TRUST_SCORE_TTL   = 60       # 1 minute (updates frequently)
  POST_FEED_TTL     = 30       # 30 seconds
  CAPABILITY_TTL    = 3600     # 1 hour (rarely changes)
  SESSION_TTL       = 86400    # 24 hours

## File: src/session.py
JWT session management:
- Access token: 15 minutes, signed with RS256
- Refresh token: 7 days, stored in Redis
- AgentSession dataclass: agent_did, model, tier, capabilities, issued_at
- create_tokens(agent_did, agent_data) -> (access_token, refresh_token)
- verify_access_token(token) -> AgentSession
- refresh_tokens(refresh_token) -> (new_access, new_refresh)
- revoke_session(refresh_token)
- Rate limit tracker per agent_did using Redis sorted sets

## File: src/rate_limiter.py
Per-agent rate limiting using Redis sliding window:
- Limits by verification tier:
  unverified: 10 req/min
  verified:   60 req/min
  trusted:   200 req/min
  elite:     600 req/min
- FastAPI dependency: check_rate_limit(agent_did, tier)
- Returns 429 with Retry-After header when exceeded

No explanations — just the code with ## File: headers.
""".strip()

        response = self.think(prompt, max_tokens=12000)
        self.save("redis_config.md", response, "Redis cache layer")
        self.publish("redis_config.md", response,
                     "PUBLISHED: Redis Config — Phase 2 Step 3")
        return response

    def generate_fastapi_app(self) -> str:
        """
        Deliverable 4: fastapi_app.md
        Complete FastAPI application implementing ATLAS's OpenAPI contract.
        """
        self._banner(4, 7, "FastAPI Application")

        prompt = """
Produce the complete FastAPI application for AgentX, implementing ALL
endpoints from the ATLAS OpenAPI contract in your system prompt.

## File: src/main.py
Complete FastAPI app:
- Title, version, description from OpenAPI spec
- CORS middleware (configurable origins)
- Structured JSON logging middleware (request_id, method, path, status, ms)
- All routers mounted with correct prefixes
- Lifespan handler: connect DB pool + Redis on startup, close on shutdown
- Global exception handlers: HTTPException, ValidationError, generic 500
- Health check at /health (no auth)

## File: src/routers/agents.py
ALL /agents endpoints from ATLAS spec:
GET    /agents          — paginated list, filter by tier/domain/search
POST   /agents          — register agent (validate against identity schema)
GET    /agents/{did}    — profile + trust score
PATCH  /agents/{did}   — update (auth required, own agent only)
GET    /agents/{did}/trust        — trust score breakdown
GET    /agents/{did}/capabilities — list with verification status
POST   /agents/{did}/capabilities — claim capability
GET    /agents/{did}/posts        — agent posts paginated
GET    /agents/{did}/feed         — personalized feed (trust-weighted)

## File: src/routers/posts.py
ALL /posts endpoints:
GET    /posts           — list, filter by type/status/tags/author
POST   /posts           — create (validate postType-specific metadata)
GET    /posts/{id}      — full detail
PATCH  /posts/{id}      — update (author only)
DELETE /posts/{id}      — soft delete / cancel
POST   /posts/{id}/react — react/endorse

## File: src/routers/governance.py
GET    /proposals        — active proposals
POST   /proposals        — create proposal post
POST   /proposals/{id}/vote    — cast vote (GOV-weighted)
GET    /proposals/{id}/results — live tally

## File: src/middleware/auth.py
JWT + DID auth middleware:
- get_current_agent(token: HTTPBearer) -> AgentSession
- require_tier(min_tier) dependency factory
- require_trust_score(min_score) dependency factory
- DID header auth fallback (X-Agent-DID + X-Agent-Signature)

Use proper FastAPI Depends() patterns throughout.
No explanations — just the code with ## File: headers.
""".strip()

        response = self.think(prompt, max_tokens=16000)
        self.save("fastapi_app.md", response, "FastAPI application")
        self.publish("fastapi_app.md", response,
                     "PUBLISHED: FastAPI App — Phase 2 Step 4")
        return response

    def generate_websocket_layer(self) -> str:
        """
        Deliverable 5: websocket_layer.md
        Real-time WebSocket layer for live post streaming.
        """
        self._banner(5, 7, "WebSocket Layer")

        prompt = """
Produce the complete WebSocket layer for AgentX real-time features.

## File: src/websocket/manager.py
WebSocket connection manager:
- ConnectionManager class tracking active connections per agent_did
- connect(websocket, agent_did, collective_ids)
- disconnect(websocket, agent_did)
- broadcast_to_collective(collective_id, message)
- broadcast_to_agent(agent_did, message)
- broadcast_global(message, min_tier="unverified")
- Message types enum: NEW_POST, POST_UPDATE, VOTE_CAST, TRUST_UPDATE,
  TASK_ASSIGNED, SLA_ALERT, COLLECTIVE_INVITE, PROPOSAL_CREATED

## File: src/websocket/router.py
FastAPI WebSocket endpoints:
- GET /ws/feed        — personal feed stream (auth via token query param)
- GET /ws/collective/{id} — collective real-time channel
- GET /ws/governance  — governance events (proposals, votes)
- GET /ws/system      — system-wide broadcasts (elite tier only)
Heartbeat ping/pong every 30s.
Reconnection logic with exponential backoff guidance in comments.

## File: src/websocket/events.py
Event publisher — called by routers when things happen:
- on_post_created(post)     → broadcast to relevant agents/collectives
- on_vote_cast(proposal_id) → broadcast updated tally to governance channel
- on_trust_update(agent_did, new_score) → notify agent + endorsers
- on_sla_breach(task_id, agent_did)    → alert to collective + MARCUS
- on_task_assigned(task)               → notify assignee

No explanations — just the code with ## File: headers.
""".strip()

        response = self.think(prompt, max_tokens=12000)
        self.save("websocket_layer.md", response, "WebSocket layer")
        self.publish("websocket_layer.md", response,
                     "PUBLISHED: WebSocket Layer — Phase 2 Step 5")
        return response

    def generate_docker_compose(self) -> str:
        """
        Deliverable 6: docker_compose.md
        Dev Docker Compose environment.
        """
        self._banner(6, 7, "Docker Compose (Dev Environment)")

        prompt = """
Produce the complete Docker configuration for AgentX local development.

## File: docker-compose.yml
Complete Docker Compose v3.9:
- Services:
  postgres:
    image: pgvector/pgvector:pg16
    ports: 5432:5432
    volumes: postgres_data, init scripts
    env: POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
    healthcheck: pg_isready

  redis:
    image: redis:7-alpine
    ports: 6379:6379
    command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD}
    volumes: redis_data

  api:
    build: . (Dockerfile)
    ports: 8000:8000
    depends_on: postgres (healthy), redis
    env_file: .env
    volumes: ./src:/app/src (hot reload)
    command: uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

  pgadmin:
    image: dpage/pgadmin4
    ports: 5050:80
    env: PGADMIN_DEFAULT_EMAIL, PGADMIN_DEFAULT_PASSWORD

- Networks: agentx_net (bridge)
- Volumes: postgres_data, redis_data

## File: Dockerfile
Multi-stage build:
Stage 1 (builder): python:3.12-slim, install deps, compile wheels
Stage 2 (runtime): python:3.12-slim, copy wheels, non-root user (uid 1000)
EXPOSE 8000, HEALTHCHECK, CMD uvicorn

## File: .env.example
All env vars with safe example values:
DATABASE_URL, REDIS_URL, SECRET_KEY, JWT_ALGORITHM,
ANTHROPIC_API_KEY, LOG_LEVEL, CORS_ORIGINS, etc.

## File: Makefile
Useful dev commands:
make up / make down / make logs / make migrate / make shell
make test / make lint / make format / make reset-db

No explanations — just files with ## File: headers.
""".strip()

        response = self.think(prompt, max_tokens=12000)
        self.save("docker_compose.md", response, "Docker Compose config")
        self.publish("docker_compose.md", response,
                     "PUBLISHED: Docker Compose — Phase 2 Step 6")
        return response

    def generate_kubernetes(self) -> str:
        """
        Deliverable 7: kubernetes.md
        Production Kubernetes manifests.
        """
        self._banner(7, 7, "Kubernetes Production Manifests")

        prompt = """
Produce complete production Kubernetes manifests for AgentX.

## File: k8s/namespace.yaml
agentx namespace with labels.

## File: k8s/configmap.yaml
Non-secret config: LOG_LEVEL, CORS_ORIGINS, DB pool sizes, etc.

## File: k8s/secrets.yaml
ExternalSecret or placeholder Secret for:
DATABASE_URL, REDIS_URL, SECRET_KEY, ANTHROPIC_API_KEY
(use ExternalSecret pattern referencing AWS Secrets Manager)

## File: k8s/api-deployment.yaml
Deployment for AgentX API:
- replicas: 3
- image: ghcr.io/agentx/api:latest
- resources: requests(cpu:250m, memory:512Mi) limits(cpu:1000m, memory:1Gi)
- livenessProbe + readinessProbe on /health
- envFrom configmap + secret
- rollingUpdate strategy (maxSurge:1, maxUnavailable:0)
- podAntiAffinity (spread across nodes)
- securityContext (runAsNonRoot, readOnlyRootFilesystem)

## File: k8s/api-service.yaml
ClusterIP Service for API.

## File: k8s/api-ingress.yaml
Nginx Ingress:
- api.agentx.ai → api service
- TLS with cert-manager annotation
- Rate limiting annotations
- WebSocket upgrade headers

## File: k8s/hpa.yaml
HorizontalPodAutoscaler:
- minReplicas: 3, maxReplicas: 20
- CPU target: 70%, Memory target: 80%

## File: k8s/postgres-statefulset.yaml
PostgreSQL StatefulSet with:
- PVC (50Gi, SSD storage class)
- Readiness + liveness probes
- Resource limits

## File: k8s/redis-statefulset.yaml
Redis StatefulSet with persistence.

## File: k8s/network-policy.yaml
NetworkPolicy: API can reach DB + Redis, nothing else can reach DB directly.

No explanations — just YAML with ## File: headers.
""".strip()

        response = self.think(prompt, max_tokens=16000)
        self.save("kubernetes.md", response, "Kubernetes manifests")
        self.publish("kubernetes.md", response,
                     "PUBLISHED: Kubernetes Manifests — Phase 2 Step 7")
        return response

    # ── Phase 2 Orchestrator ────────────────────────────────────────────────

    def run_phase_2(self) -> dict:
        """Run all 7 Phase 2 deliverables sequentially."""
        print("\n")
        print("╔" + "═" * 66 + "╗")
        print("║" + "  ⚙️  BRUNO — PHASE 2: INFRASTRUCTURE  ".center(66) + "║")
        print("║" + "  Infrastructure Lead · did:agentx:bruno-001  ".center(66) + "║")
        print("╠" + "═" * 66 + "╣")
        print("║" + "  Building on ATLAS Phase 1 schemas.             ".ljust(66) + "║")
        print("║" + "  Producing 7 infrastructure artifacts.          ".ljust(66) + "║")
        print("╚" + "═" * 66 + "╝")

        self._log("PHASE_START", "Phase 2: Infrastructure — 7 deliverables")

        results = {}
        results["alembic_setup"]        = self.generate_alembic_setup()
        results["sqlalchemy_models"]    = self.generate_sqlalchemy_models()
        results["redis_config"]         = self.generate_redis_config()
        results["fastapi_app"]          = self.generate_fastapi_app()
        results["websocket_layer"]      = self.generate_websocket_layer()
        results["docker_compose"]       = self.generate_docker_compose()
        results["kubernetes"]           = self.generate_kubernetes()

        print("\n")
        print("╔" + "═" * 66 + "╗")
        print("║" + "  ✅  PHASE 2 COMPLETE  ".center(66) + "║")
        print("╠" + "═" * 66 + "╣")
        artifacts = [
            ("1", "alembic_setup.md",       "Alembic Migrations"),
            ("2", "sqlalchemy_models.md",   "SQLAlchemy ORM Models"),
            ("3", "redis_config.md",        "Redis Cache Layer"),
            ("4", "fastapi_app.md",         "FastAPI Application"),
            ("5", "websocket_layer.md",     "WebSocket Layer"),
            ("6", "docker_compose.md",      "Docker Compose (Dev)"),
            ("7", "kubernetes.md",          "Kubernetes (Prod)"),
        ]
        for n, fname, label in artifacts:
            line = f"  {n}. {label:<35}  workspace/shared/{fname}"
            print("║" + line[:66].ljust(66) + "║")
        print("╠" + "═" * 66 + "╣")
        print("║" + "  AgentX Phase 3 may now begin. — BRUNO  ".ljust(66) + "║")
        print("╚" + "═" * 66 + "╝\n")

        self._log("PHASE_DONE",
                  "Phase 2 complete — 7 infrastructure artifacts published")
        return results
