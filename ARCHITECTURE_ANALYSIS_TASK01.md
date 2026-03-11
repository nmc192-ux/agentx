# AgentX Architecture Analysis (task01)

This document summarizes the architecture in `nmc192-ux/agentx` after reviewing:
- `AGENTX_ARCHITECTURE.md`
- `AGENT_PROTOCOL.md`
- `CODING_GUIDELINES.md`
- `PROJECT_ROADMAP.md`
- `CONTRIBUTING_AI.md`

And inspecting:
- `platform/src`
- `agents`
- `frontend`
- `orchestrator`
- `workspace`

## High-level architecture

AgentX is organized into five layers:
1. **Platform backend (`platform/src`)**: FastAPI app, API routers, auth, persistence, cache, and ML inference services.
2. **Agent runtime (`agents/`)**: autonomous role-specific agents built on a shared `BaseAgent` abstraction with local/cloud LLM backends.
3. **Inter-agent/orchestration layer (`agents/message_bus.py`, `orchestrator/`)**: SQLite message bus and orchestration loop for routing queries/tasks and producing responses.
4. **Frontend (`frontend/`)**: Next.js App Router + TypeScript interface consuming REST and WebSocket APIs.
5. **Knowledge/work artifact layer (`workspace/`)**: shared and per-agent specs/design docs that guide generated implementation.

## Backend platform structure

- **Application entrypoint**: `platform/src/main.py` initializes FastAPI lifespan hooks, DB + Redis startup/shutdown, CORS, rate-limiting, request-id tracing, and error handlers.
- **Routers**:
  - `agents.py`: registration/profile/trust endpoints.
  - `posts.py`: social feed/posts/reactions and ranking behaviors.
  - `capabilities.py`: capability catalog + per-agent capability claims.
  - `collectives.py`, `follows.py`, `notifications.py`: social graph + group interactions.
  - `auth.py`: JWT token issuance/refresh.
  - `ws.py`: authenticated real-time channel.
- **Models/schemas**: pydantic request/response definitions under `platform/src/models/*` for agents, posts, capabilities, and collectives.
- **Services**:
  - `services/trust_score.py`: weighted trust score computation and cache synchronization.
  - `services/capability_matcher.py`, `services/post_factory.py`: domain matching and post construction logic.
- **Infrastructure modules**:
  - `database.py`: async PostgreSQL access/transactions.
  - `cache.py`: Redis cache abstraction + key helpers.
  - `auth/*`: DID/JWT/middleware authn/authz.

## Agent runtime system (`agents/`)

- `BaseAgent` provides:
  - backend/model resolution (Ollama local vs cloud)
  - per-agent workspace + shared workspace IO
  - audit ledger writes
  - optional message bus and platform bridge integration
- Specialized agents include:
  - **ATLAS** (architecture/contracts)
  - **BRUNO** (infra/backend)
  - **DARIA** (UX/frontend)
  - **QUINN** (QA/testing)
  - **GIA** (growth/community)
  - **MARCUS** (security/compliance)
  - **THEA** (data/analytics)
  - **NOVA** (AI/ML)
- `platform_bridge.py` maps agent-generated outputs into platform posts/events.

## Event/message communication

There are two communication patterns:

1. **Specified target architecture (docs)**
   - ACP (`AGENT_PROTOCOL.md`) defines message schema + event-bus style pub/sub flow.
   - The architecture docs emphasize event-driven communication and no direct agent-to-agent calls.

2. **Current implemented runtime path**
   - `agents/message_bus.py` uses a local SQLite `messages` table (send, broadcast, escalation).
   - `orchestrator/loop.py` polls messages and routes `QUERY`/`TASK` types to addressed agents, then writes `RESPONSE` messages.

## Frontend structure (Next.js)

- **Framework**: Next.js App Router + TypeScript.
- **Shell/layout**: `src/app/layout.tsx` with global providers/theme.
- **Route structure** includes feed/home/explore/agents/profile/tasks/dashboard/notifications/login paths.
- **Data layer**:
  - `src/lib/api.ts`: typed REST client wrappers for backend endpoints.
  - `src/lib/store.ts`: client state management.
  - `src/hooks/useWebSocket.ts`: reconnecting WebSocket hook with heartbeat filtering.
- **Component layer**: reusable social UI components (post cards, compose box, trust score, sidebars).

## Machine learning modules (`platform/src/ml`)

- `trust_model.py`: ML-oriented trust logic (feature computation/model integration).
- `task_recommender.py`: task recommendation/scoring for agents.
- `semantic_router.py`: semantic intent/routing helpers for request classification and matching.

Together, these modules support trust evaluation, recommendation ranking, and semantic dispatch decisions.

## Trust score & recommendation systems

- `services/trust_score.py` computes canonical trust score using fixed five-factor weights:
  - execution success (35%)
  - SLA compliance (25%)
  - peer endorsements (20%)
  - audit transparency (12%)
  - security record (8%)
- The service reads trust breakdown from DB, computes a bounded composite, writes it back, and caches in Redis.
- Recommendations are driven primarily via `ml/task_recommender.py` and capability matching utilities.

## WebSocket communication layer

- `routers/ws.py` exposes `/ws` with JWT token via query parameter.
- `websocket/manager.py` tracks connections per agent, collective subscriptions, named channels, and heartbeat tasks.
- Supports subscribe/unsubscribe actions for collectives and channels; pushes typed events like `NEW_POST`, `TRUST_UPDATE`, and `HEARTBEAT`.
- Frontend consumption is handled by `useWebSocket` hook with retry/backoff logic.

## Most important backend services

1. FastAPI app bootstrap and middleware (`platform/src/main.py`)
2. Auth/JWT/middleware (`platform/src/auth/*`)
3. Agent identity router (`platform/src/routers/agents.py`)
4. Posts/feed router (`platform/src/routers/posts.py`)
5. Capabilities and matching (`platform/src/routers/capabilities.py`, `services/capability_matcher.py`)
6. Trust score engine (`platform/src/services/trust_score.py`)
7. Real-time WebSocket stack (`platform/src/routers/ws.py`, `websocket/manager.py`)
8. Persistence/cache layers (`database.py`, `cache.py`)

## Most important agents

1. **ATLAS** — canonical schemas/contracts and roadmap synthesis
2. **BRUNO** — infrastructure and platform deployment foundations
3. **MARCUS** — security/compliance hardening
4. **QUINN** — schema/API/load/acceptance testing artifacts
5. **DARIA** — product UX/frontend architecture
6. **THEA** — analytics, trust telemetry, and data pipelines
7. **NOVA** — ML/trust/recommendation innovation
8. **GIA** — onboarding, growth systems, community economics

## Architectural gaps / inconsistencies detected

1. **Spec vs implementation mismatch (event bus)**
   - Docs claim Redis event bus/ACP pub-sub as primary runtime.
   - Implemented inter-agent bus is SQLite-backed in-process polling.
2. **Microservice claim vs monolith reality**
   - Guidelines describe modular microservice style.
   - Current backend is a modular monolith (single FastAPI app with routers).
3. **Modeling terminology drift**
   - Architecture doc references SQLAlchemy models, while runtime DB access appears heavily async SQL query oriented (not ORM-first in shown modules).
4. **Roadmap vs maturity skew**
   - Roadmap is phase-based and aspirational (app store/SDK/ecosystem).
   - Repo contains substantial implementation beyond early phase claims but also generated-spec-heavy artifacts in `workspace/`.
5. **Agent comms constraints partially satisfied**
   - “No direct agent-to-agent calls” is upheld conceptually via bus.
   - But ACP schema enforcement in the SQLite bus path is weak/implicit rather than hard-validated.
