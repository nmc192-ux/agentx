# Synergy Inputs — 2026-05-05

## Part 1 — Synapse: what it is

### 1.1 Repo location and metadata

- **Path used:** `/Users/jahanzebhussain/Synapse` (capitalized; the path `/Users/jahanzebhussain/synapse` does not exist).
  - Sibling sidecar dirs also exist: `synapse-data/`, `synapse-logs/`, `synapse-runtime/` (all empty placeholder dirs).
  - This task ran from a worktree of that repo: `/Users/jahanzebhussain/Synapse/src/synapse/.claude/worktrees/happy-swirles-89fda6` on branch `claude/happy-swirles-89fda6`.

- **`git log -1 --format="%h %ci %s"` on main:**

  ```
  38469da 2026-04-09 01:00:18 +0500 feat: classify bootstrap requeue abandonment
  ```

- **`git log --oneline -20`:**

  ```
  38469da feat: classify bootstrap requeue abandonment
  935f3a0 fix: requeue claimed bootstrap that never entered
  2adf3bf feat: classify bootstrap capacity requeues
  a0d33bd fix: reject bootstrap when no worker is ready
  6932947 fix: quarantine workers with repeated bootstrap non-starts
  173e88d fix: tighten bootstrap admission control
  219bd43 feat: add canonical bootstrap lifecycle stages
  82a2394 fix: reduce dominant bootstrap pre-start gap
  5e1763f feat: add synthetic alpha loop status artifacts
  f2ac251 feat: automate synthetic alpha loop planning
  ac04697 feat: instrument bootstrap pre-start lifecycle
  3ff51bb fix: reduce bootstrap not started backlog
  22730e0 feat: add operator testing console ui
  76e0c4e fix: classify timed out synthetic operator review backlog
  572a5da feat: classify stuck request backlog by subtype
  be3a34f fix: bound synthetic alpha operator review backlog
  e35e71c fix: converge long-lived degraded browser requests
  a878395 fix: quiet tenantless infrastructure event noise
  d52274a fix: mitigate browser action timeout hotspots
  0273fd3 fix: reduce in-flight durable result stuck tail
  ```

- **`git branch -a --sort=-committerdate | head -10`:**

  ```
  + claude/happy-swirles-89fda6
  * main
    remotes/origin/HEAD -> origin/main
    remotes/origin/main
  ```

- **File count:** 10,166 files (excluding `.git`, `node_modules`, `.venv`, `__pycache__`, `dist`, `build`, `.pytest_cache`, ephemeral `synapse-plugin-*` dirs).

- **Total LOC:** 125,646 lines across `*.py`, `*.ts`, `*.tsx`, `*.js`, `*.jsx`, `*.md` (with the same exclusions). `cloc` is not installed on this machine.
  - Among Python source under `src/synapse/` (105 files, excluding worktree copies): 23,097 LOC.

- **LICENSE:** not found. There is no `LICENSE` file at the Synapse repo root.

- **Top-level dependency manifest — `pyproject.toml` (entire):**

  ```toml
  [build-system]
  requires = ["setuptools>=68", "wheel"]
  build-backend = "setuptools.build_meta"

  [project]
  name = "synapse"
  version = "0.1.0"
  description = "Browser runtime for autonomous agents."
  readme = "README.md"
  requires-python = ">=3.11"
  dependencies = [
    "asyncpg>=0.30.0,<1.0.0",
    "fastapi>=0.115.0,<1.0.0",
    "httpx>=0.27.0,<1.0.0",
    "playwright>=1.52.0,<2.0.0",
    "pypdf>=5.4.0,<6.0.0",
    "pydantic>=2.8.0,<3.0.0",
    "pydantic-settings>=2.4.0,<3.0.0",
    "pyyaml>=6.0.2,<7.0.0",
    "redis>=5.2.0,<6.0.0",
    "uvicorn[standard]>=0.30.0,<1.0.0",
  ]

  [project.optional-dependencies]
  dev = [
    "pytest>=8.3.0,<9.0.0",
  ]

  [tool.setuptools]
  package-dir = {"" = "src"}

  [tool.setuptools.packages.find]
  where = ["src"]

  [tool.pytest.ini_options]
  pythonpath = ["src"]
  testpaths = ["tests"]
  ```

- **Top-level dependency manifest — `ui/package.json` (entire; no top-level `package.json` exists):**

  ```json
  {
    "name": "synapse-ui",
    "version": "0.1.0",
    "private": true,
    "scripts": {
      "dev": "next dev",
      "build": "next build",
      "start": "next start",
      "lint": "next lint"
    },
    "dependencies": {
      "next": "^15.0.0",
      "react": "^19.0.0",
      "react-dom": "^19.0.0"
    },
    "devDependencies": {
      "@types/node": "^22.10.0",
      "@types/react": "^19.0.0",
      "@types/react-dom": "^19.0.0",
      "typescript": "^5.7.0"
    }
  }
  ```

- **`requirements.txt`:** not found.

### 1.2 README (verbatim, top of file)

First 150 lines of `/Users/jahanzebhussain/Synapse/README.md`:

```markdown
# Synapse

Synapse is a browser runtime for autonomous agents.

## Release Status

- Internal beta: supported for trusted internal teams
- Restricted design-partner alpha: supported for trusted, supervised external partners under controlled deployment constraints
- Public hosted platform: not supported yet

Restricted alpha is intentionally narrow:

- trusted users only
- supervised runs only
- restricted domain allowlists
- `trusted_internal` plugins only, or tightly allowlisted `trusted_partner` plugins
- no sensitive credentials
- no SLA commitments

Partner onboarding and operating material lives in [`/Users/jahanzebhussain/Synapse/docs/alpha`](/Users/jahanzebhussain/Synapse/docs/alpha). Start with the quickstart and deployment topology before granting external access.

It provides a Python backend for:

- browser navigation and extraction
- tool execution
- WebSocket event streaming
- multi-agent coordination
- pluggable agent adapters

## Supported agent categories

- OpenClaw agents
- Claude Code agents
- Codex agents
- A2A protocol agents
- custom agents

## Stack

- FastAPI
- Playwright
- WebSockets
- Pydantic

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
export SYNAPSE_POSTGRES_DSN=postgresql://postgres:postgres@localhost:5432/synapse
export SYNAPSE_REDIS_URL=redis://localhost:6379/0
uvicorn synapse.main:app --reload
```

Optional LLM planner configuration:

```bash
export SYNAPSE_LLM_PROVIDER=openai
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-4o-mini
```

Supported providers are `openai`, `anthropic`, and `local`. Local models can be
configured with `SYNAPSE_LOCAL_MODEL_ENDPOINT` and `SYNAPSE_LOCAL_MODEL_NAME`.

Optional compression provider configuration:

```bash
export SYNAPSE_COMPRESSION_PROVIDER=noop
```

Supported compression providers are `noop` and `turboquant`. The TurboQuant
provider is currently a stub integration layer so the runtime can adopt a real
TurboQuant SDK later without changing service interfaces.

Runtime durability configuration:

```bash
export SYNAPSE_REDIS_URL=redis://localhost:6379/0
export SYNAPSE_REDIS_REQUIRED=false
export SYNAPSE_RUNTIME_STATE_FALLBACK_MEMORY=true
```

If Redis is unavailable and fallback is enabled, Synapse logs a warning and uses
in-memory runtime state.

Worker and scheduler configuration:

```bash
export SYNAPSE_BROWSER_WORKER_COUNT=2
export SYNAPSE_BROWSER_WORKER_HEARTBEAT_INTERVAL_SECONDS=15
export SYNAPSE_SCHEDULER_LEASE_TIMEOUT_SECONDS=60
export SYNAPSE_SCHEDULER_MAX_ASSIGNMENT_RETRIES=3
```

## Project layout

```text
src/synapse/
  adapters/      Agent adapter interfaces and built-in implementations
  api/           FastAPI routes
  models/        Pydantic models
  sdk/           Python SDK for agent clients
  runtime/       Browser runtime, orchestration, tools, registry
  transports/    WebSocket connection management
sdk/javascript/  JavaScript SDK for agent clients
ui/              Next.js operator interface
```

## Python SDK

```python
from synapse.models.agent import AgentDefinition, AgentKind, AgentSecurityPolicy
from synapse.sdk import SynapseClient

with SynapseClient("http://127.0.0.1:8000", agent_id="codex") as client:
    client.register_agent(
        AgentDefinition(
            agent_id="codex",
            kind=AgentKind.CODEX,
            name="Codex",
            security=AgentSecurityPolicy(
                allowed_domains=["example.com"],
                allowed_tools=["web.search"],
            ),
        )
    )
    browser = client.browser
    page = browser.open("https://example.com")
    data = browser.extract("h1")
    tool_result = browser.call_tool("web.search", {"query": "Synapse"})
```

Example agents are available in `examples/` for OpenClaw, Codex, and Claude Code.

Restricted alpha examples are available in:

- [`/Users/jahanzebhussain/Synapse/examples/alpha/openclaw_research_agent.py`](/Users/jahanzebhussain/Synapse/examples/alpha/openclaw_research_agent.py)
- [`/Users/jahanzebhussain/Synapse/examples/alpha/codex_browser_agent.py`](/Users/jahanzebhussain/Synapse/examples/alpha/codex_browser_agent.py)
- [`/Users/jahanzebhussain/Synapse/examples/alpha/claude_code_agent.py`](/Users/jahanzebhussain/Synapse/examples/alpha/claude_code_agent.py)
- [`/Users/jahanzebhussain/Synapse/examples/alpha/multi_agent_delegation_demo.py`](/Users/jahanzebhussain/Synapse/examples/alpha/multi_agent_delegation_demo.py)

Agent actions are sandboxed by default. Register each agent with explicit
`allowed_domains`, `allowed_tools`, and rate limits before issuing browser or tool calls.
If `SYNAPSE_LLM_PROVIDER` is configured, the navigation planner will use the selected
LLM provider before falling back to the built-in heuristic planner.

## JavaScript SDK
```

### 1.3 Directory tree

`tree` is not installed. Equivalent output via `find -maxdepth 3` (excluding `.git`, `node_modules`, `.venv`, `__pycache__`, `synapse-plugin-*`, `.pytest_cache`, `ui/.next`):

```
.
./config
./config/examples
./docs
./docs/alpha
./docs/architecture
./docs/enterprise
./docs/migration
./docs/migrations
./examples
./examples/alpha
./examples/synthetic_alpha_swarm
./examples/synthetic_alpha_swarm/runtime
./ops
./ops/local_supervision
./ops/local_supervision/bin
./sdk
./sdk/javascript
./sdk/javascript/examples
./sdk/javascript/src
./src
./src/synapse
./src/synapse/.claude
./src/synapse/adapters
./src/synapse/api
./src/synapse/connectors
./src/synapse/fixtures
./src/synapse/models
./src/synapse/plugins
./src/synapse/runtime
./src/synapse/sdk
./src/synapse/security
./src/synapse/testing
./src/synapse/transports
./src/synapse/workers
./tests
./tests/chaos
./ui
./ui/app
./ui/app/api
./ui/components
./ui/hooks
./ui/lib
```

### 1.4 Architecture inventory

**All Python modules under `src/synapse/`** (105 files; ephemeral `__pycache__` and worktree copies excluded):

```
src/synapse/__init__.py
src/synapse/main.py
src/synapse/config.py
src/synapse/adapters/__init__.py
src/synapse/adapters/a2a.py
src/synapse/adapters/base.py
src/synapse/adapters/claude_code.py
src/synapse/adapters/codex.py
src/synapse/adapters/custom.py
src/synapse/adapters/openclaw.py
src/synapse/api/__init__.py
src/synapse/api/routes.py
src/synapse/connectors/__init__.py
src/synapse/connectors/base.py
src/synapse/connectors/claude_code.py
src/synapse/connectors/codex.py
src/synapse/connectors/langgraph.py
src/synapse/connectors/openclaw.py
src/synapse/fixtures/__init__.py
src/synapse/fixtures/web.py
src/synapse/models/__init__.py
src/synapse/models/a2a.py
src/synapse/models/agent.py
src/synapse/models/benchmark.py
src/synapse/models/browser.py
src/synapse/models/capability.py
src/synapse/models/events.py
src/synapse/models/loop.py
src/synapse/models/memory.py
src/synapse/models/message.py
src/synapse/models/page_graph.py
src/synapse/models/platform.py
src/synapse/models/plugin.py
src/synapse/models/run.py
src/synapse/models/runtime_event.py
src/synapse/models/runtime_state.py
src/synapse/models/task.py
src/synapse/plugins/__init__.py
src/synapse/plugins/api_client.py
src/synapse/plugins/database.py
src/synapse/plugins/github_search.py
src/synapse/plugins/pdf_reader.py
src/synapse/plugins/web_search.py
src/synapse/runtime/__init__.py
src/synapse/runtime/a2a.py
src/synapse/runtime/agent_loop.py
src/synapse/runtime/benchmarking.py
src/synapse/runtime/browser/__init__.py
src/synapse/runtime/browser/download_manager.py
src/synapse/runtime/browser/interaction_engine.py
src/synapse/runtime/browser/page_graph_builder.py
src/synapse/runtime/browser/recovery_engine.py
src/synapse/runtime/browser/session_manager.py
src/synapse/runtime/browser/spm_extractor.py
src/synapse/runtime/browser/upload_manager.py
src/synapse/runtime/browser_service.py
src/synapse/runtime/browser_workers.py
src/synapse/runtime/budget.py
src/synapse/runtime/budget_service.py
src/synapse/runtime/capabilities.py
src/synapse/runtime/checkpoint_service.py
src/synapse/runtime/compression/__init__.py
src/synapse/runtime/compression/base.py
src/synapse/runtime/compression/noop.py
src/synapse/runtime/compression/turboquant.py
src/synapse/runtime/control_plane.py
src/synapse/runtime/event_bus.py
src/synapse/runtime/execution_plane.py
src/synapse/runtime/llm.py
src/synapse/runtime/memory.py
src/synapse/runtime/memory_service.py
src/synapse/runtime/messaging.py
src/synapse/runtime/orchestrator.py
src/synapse/runtime/planning.py
src/synapse/runtime/platform_service.py
src/synapse/runtime/plugin_isolation.py
src/synapse/runtime/plugin_runner.py
src/synapse/runtime/plugin_sandbox.py
src/synapse/runtime/prompts.py
src/synapse/runtime/queues.py
src/synapse/runtime/registry.py
src/synapse/runtime/run_store.py
src/synapse/runtime/runtime_controller.py
src/synapse/runtime/safety.py
src/synapse/runtime/scheduler.py
src/synapse/runtime/security.py
src/synapse/runtime/session.py
src/synapse/runtime/session_profiles.py
src/synapse/runtime/state_store.py
src/synapse/runtime/task_manager.py
src/synapse/runtime/task_runtime.py
src/synapse/runtime/tool_service.py
src/synapse/runtime/tools.py
src/synapse/sdk/__init__.py
src/synapse/sdk/client.py
src/synapse/security/auth.py
src/synapse/security/identity.py
src/synapse/security/policies.py
src/synapse/security/signing.py
src/synapse/security/tokens.py
src/synapse/testing/__init__.py
src/synapse/testing/isolated_plugin.py
src/synapse/transports/__init__.py
src/synapse/transports/websocket_manager.py
src/synapse/workers/browser_worker.py
```

**TS/TSX files under `ui/` and `sdk/javascript/`** (10 files; `node_modules` and `.next` excluded):

```
ui/app/api/dashboard/[...path]/route.ts
ui/app/layout.tsx
ui/app/page.tsx
ui/components/dashboard.tsx
ui/hooks/use-synapse-feed.ts
ui/lib/auth.ts
ui/lib/mock-data.ts
ui/lib/types.ts
sdk/javascript/src/index.d.ts
sdk/javascript/src/index.js
```

**Database models / domain models:** Synapse uses Pydantic models, not SQLAlchemy/ORM `Base` classes. There are 142 `BaseModel` / `str, Enum` classes across `src/synapse/models/`. Representative classes by file:

- `models/a2a.py` — `A2AMessageType`, `A2AEnvelope`, `AgentPresence`, `DiscoveryPayload`, `DelegatePayload`, `TaskResultPayload`, `AgentRegistrationRequest`, `AgentWireMessage`, `AgentIdentityRecord`, `AgentDelegateRequest`
- `models/agent.py` — `AgentDefinition`, `AgentKind`, `AgentSecurityPolicy`, `AgentBudgetUsage`, `AgentCheckpoint`, `AgentDiscoveryEntry`
- `models/run.py` — `RunStatus`, `RunState`, `RunGraphNode`, `RunGraphEdge`, `RunGraph`, `RunDelegationSummary`, `RunAttentionSummary`
- `models/task.py` — `TaskStatus`, `NavigationRequest`, `ExtractionRequest`, `ToolCallRequest`, `TaskRequest`, `TaskResult`, `TaskRecord`, `TaskCreateRequest`, `TaskClaimRequest`, `TaskUpdateRequest`
- `models/benchmark.py` — `BenchmarkCategory`, `BenchmarkScenario`, `BenchmarkRunScore`, `BenchmarkAggregate`, `BenchmarkReport`
- `models/memory.py` — `MemoryType`, `MemoryScope`, `MemoryRecord`, `MemoryStoreRequest`, `MemorySearchRequest`, `MemorySearchResult`
- `models/message.py` — `AgentMessage`
- `models/platform.py` — `Organization`, `Project`, `PlatformUser`, `APIKeyRecord`, `APIKeyIssueResponse`, `AuditLogRecord`, `AgentOwnership`, plus `*CreateRequest` variants
- Plus `models/browser.py`, `models/capability.py`, `models/events.py`, `models/loop.py`, `models/page_graph.py`, `models/plugin.py`, `models/runtime_event.py`, `models/runtime_state.py`

Persistence note: `pyproject.toml` pulls in `asyncpg` + `redis`, and the runtime mounts a Postgres DSN (`SYNAPSE_POSTGRES_DSN`) and Redis URL. State store implementations live in `src/synapse/runtime/state_store.py`, `run_store.py`, `session_profiles.py`. There is no SQLAlchemy declarative base.

**API endpoints:** 104 route decorators in `src/synapse/api/routes.py` (all on a single `router`, mounted by `src/synapse/main.py`). The route surface clusters into:

- Health/readiness: `GET /health`, `GET /ready`
- Platform tenancy: `POST/GET /platform/organizations`, `POST/GET /platform/projects`, `POST/GET /platform/users`, `POST/GET /platform/api-keys`, `POST/GET /platform/agents/{agent_id}/ownership`
- Cloud (project-scoped): `POST /cloud/projects/{project_id}/runs`, `POST/GET /cloud/projects/{project_id}/profiles`, `POST/GET /cloud/projects/{project_id}/capabilities`, `GET /cloud/projects/{project_id}/agents/find`, `POST /cloud/projects/{project_id}/api-keys`, `GET /cloud/projects/{project_id}/audit-logs`, `GET /cloud/admin/workers`
- Browser primitives: `POST /sessions`, `POST /navigate`, `POST /browser/open`, `/browser/click`, `/browser/type`, `/browser/extract`, `/browser/screenshot`, `/browser/layout`, `/browser/find`, `/browser/inspect`, `/browser/dismiss`, `/browser/upload`, `/browser/download`, `/browser/scroll_extract`, plus legacy `/extract`
- Agent registry & A2A: `POST/GET /agents`, `GET /agents/{agent_id}`, `GET /agents/{agent_id}/budget`, `POST /agents/{agent_id}/checkpoint`, `POST /agents/register`, `GET /agents/discover`, `GET /agents/find`, `POST/GET /agents/capabilities`, `POST /agents/message`, `POST /agents/delegate`, `GET /a2a/agents`, `POST /a2a/messages`, `POST/GET /messages`
- Memory: `POST /memory/store`, `POST /memory/search`, `GET /memory/{agent_id}/recent`
- Tools/plugins: `GET /tools`, `POST /tools/call`, `GET /plugins`, `POST /plugins/reload`
- Tasks/runs/sessions/checkpoints/interventions: `GET /tasks/active`, `GET /sessions`, `GET/DELETE /sessions/{session_id}`, `POST /profiles/create`, `POST /profiles/{profile_id}/load`, `GET/DELETE /profiles/{profile_id}`, `GET /connections`, `GET /checkpoints`, `GET /runs`, `GET /interventions`, `GET /runs/{run_id}` and a long tail of `/runs/{run_id}/{events,worker-requests,timeline,replay,graph,delegation-summary,attention,trace,network,checkpoints,children}`
- Run lifecycle controls: `POST /runs/{run_id}/{pause,resume,approve,reject,provide_input,cancel}` and parallel `POST /interventions/{intervention_id}/{approve,reject,provide_input}`
- Task checkpoint/resume: `POST /tasks/{task_id}/checkpoint`, `POST /tasks/resume/{checkpoint_id}`
- WebSockets: `@router.websocket("/ws")`, `@router.websocket("/a2a/ws/{agent_id}")`

**Frontend pages** (Next.js `app/`):

```
ui/app/layout.tsx
ui/app/page.tsx
ui/app/api/dashboard/[...path]/route.ts   (BFF proxy)
```

Plus `ui/components/dashboard.tsx`, `ui/hooks/use-synapse-feed.ts`, `ui/lib/{auth,mock-data,types}.ts`. The UI is single-page (operator dashboard), not a full multi-route surface.

**CLI / entry points:**

- `src/synapse/main.py` — FastAPI app object (`uvicorn synapse.main:app`); no `bin/` or `scripts/` directory exists.
- Repo-root shell entry points:
  - `start_synapse_local.sh`
  - `stop_synapse_local.sh`
  - `start_synthetic_alpha_stack.sh`
  - `stop_synthetic_alpha_stack.sh`
  - `status_synthetic_alpha_stack.sh`
- `ops/local_supervision/render_launchd_plists.py` — launchd plist generator for local supervision.

### 1.5 Three most important files

#### File 1 — `src/synapse/main.py` (135 lines)

This is the FastAPI app entry point. It wires every runtime component together and is the smallest file that lets you read what Synapse *is* in one screen.

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from synapse.api.routes import router
from synapse.config import settings
from synapse.runtime.a2a import A2AHub
from synapse.runtime.budget import AgentBudgetManager
from synapse.runtime.browser import BrowserRuntime
from synapse.runtime.browser_workers import BrowserWorkerPool
from synapse.runtime.compression.base import create_compression_provider
from synapse.runtime.control_plane import ControlPlane
from synapse.runtime.execution_plane import ExecutionPlaneRuntime
from synapse.runtime.llm import create_llm_provider
from synapse.runtime.memory import AgentMemoryManager
from synapse.runtime.messaging import AgentMessageBus
from synapse.runtime.registry import AgentRegistry
from synapse.runtime.security import AgentSecuritySandbox
from synapse.runtime.session_profiles import SessionProfileManager
from synapse.runtime.safety import AgentSafetyLayer
from synapse.runtime.state_store import InMemoryRuntimeStateStore, create_runtime_state_store
from synapse.runtime.task_manager import TaskExecutionManager
from synapse.runtime.tools import ToolRegistry
from synapse.security.auth import Authenticator
from synapse.transports.websocket_manager import WebSocketManager


runtime_state_store = InMemoryRuntimeStateStore()
authenticator = Authenticator(settings)
compression_provider = create_compression_provider(settings)
agent_registry = AgentRegistry(state_store=runtime_state_store)
tool_registry = ToolRegistry(
    execution_mode=settings.plugin_execution_mode,
    execution_timeout_seconds=settings.plugin_execution_timeout_seconds,
    state_store=runtime_state_store,
)
message_bus = AgentMessageBus()
websocket_manager = WebSocketManager(state_store=runtime_state_store, compression_provider=compression_provider)
session_profile_manager = SessionProfileManager(state_store=runtime_state_store)
browser_runtime = BrowserWorkerPool(
    state_store=runtime_state_store,
    runtime_factory=lambda: ExecutionPlaneRuntime(
        browser_runtime=BrowserRuntime(state_store=runtime_state_store, profile_manager=session_profile_manager),
        tool_registry=tool_registry,
    ),
)
sandbox = AgentSecuritySandbox(agent_registry, state_store=runtime_state_store)
a2a_hub = A2AHub(
    agent_registry,
    state_store=runtime_state_store,
    sockets=websocket_manager,
    compression_provider=compression_provider,
    sandbox=sandbox,
)
memory_manager = AgentMemoryManager()
task_manager = TaskExecutionManager()
safety = AgentSafetyLayer()
budget_manager = AgentBudgetManager()
llm_provider = create_llm_provider(settings)
orchestrator = ControlPlane(
    browser=browser_runtime,
    agents=agent_registry,
    tools=tool_registry,
    messages=message_bus,
    a2a=a2a_hub,
    memory_manager=memory_manager,
    task_manager=task_manager,
    sockets=websocket_manager,
    sandbox=sandbox,
    safety=safety,
    budget_manager=budget_manager,
    state_store=runtime_state_store,
    session_profiles=session_profile_manager,
    llm=llm_provider,
    compression_provider=compression_provider,
    authenticator=authenticator,
)
a2a_hub.set_task_executor(orchestrator.execute_task)
authenticator.set_api_key_validator(orchestrator.platform.authenticate_api_key_principal)
```

#### File 2 — `src/synapse/api/routes.py` (1,666 lines)

The single FastAPI router carrying all 104 HTTP endpoints + 2 WebSocket endpoints. This is the public surface of Synapse.

```python
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, WebSocketDisconnect, status

from synapse.models.a2a import (
    A2AEnvelope,
    AgentDelegateRequest,
    AgentPresence,
    AgentRegistrationRequest,
    AgentWireMessage,
)
from synapse.models.agent import AgentBudgetUsage, AgentCheckpoint, AgentDefinition, AgentDiscoveryEntry
from synapse.models.capability import CapabilityAdvertisementRequest, CapabilityRecord
from synapse.models.browser import (
    BrowserState,
    ClickRequest,
    DismissRequest,
    DownloadRequest,
    DownloadResult,
    ExtractionResult,
    ExtractRequest,
    FindElementRequest,
    InspectRequest,
    LayoutRequest,
    PageElementMatch,
    PageInspection,
    OpenRequest,
    ScreenshotRequest,
    ScreenshotResult,
    ScrollExtractRequest,
    ScrollExtractResult,
    StructuredPageModel,
    TypeRequest,
    UploadRequest,
    UploadResult,
)
from synapse.models.runtime_event import EventType, RunReplayView, RunTimeline, RuntimeEvent
from synapse.models.message import AgentMessage
from synapse.models.memory import MemoryRecord, MemorySearchRequest, MemorySearchResult, MemoryStoreRequest
from synapse.models.plugin import PluginDescriptor, PluginReloadRequest, ToolDescriptor
from synapse.models.platform import (
    APIKeyCreateRequest,
    APIKeyIssueResponse,
    APIKeyRecord,
    AuditLogRecord,
    AgentOwnership,
    AgentOwnershipRequest,
    Organization,
    OrganizationCreateRequest,
    PlatformUser,
    Project,
    ProjectCreateRequest,
    UserCreateRequest,
)
from synapse.models.run import RunAttentionSummary, RunDelegationSummary, RunGraph, RunState
from synapse.models.runtime_state import (
    BrowserNetworkEntry,
    BrowserSessionState,
    BrowserTaskRequestHealthView,
    BrowserTraceEntry,
    BrowserWorkerState,
    ConnectionState,
    OperatorInterventionRecord,
    RuntimeCheckpoint,
)
from synapse.models.task import (
    ExtractionRequest,
    NavigationRequest,
    TaskClaimRequest,
    TaskCreateRequest,
    TaskRecord,
    TaskRequest,
    TaskUpdateRequest,
    ToolCallRequest,
)
from synapse.runtime.orchestrator import RuntimeOrchestrator
from synapse.runtime.session_profiles import SessionProfile, SessionProfileCreateRequest, SessionProfileLoadRequest
from synapse.runtime.budget import AgentBudgetLimitExceeded
from synapse.runtime.security import SandboxPermissionError, SandboxRateLimitError
from synapse.runtime.safety import SecurityAlertError
```

#### File 3 — `src/synapse/runtime/runtime_controller.py` (988 lines)

The runtime control surface that ties together browser, A2A hub, scheduler, registries, services, and benchmarking. The first 80 lines are pure imports — they enumerate the runtime's component graph more cleanly than any prose summary.

```python
from __future__ import annotations

import uuid

from synapse.models.a2a import A2AEnvelope, A2AMessageType, AgentDelegateRequest, AgentPresence, AgentRegistrationRequest, AgentWireMessage
from synapse.models.agent import AgentBudgetUsage, AgentCheckpoint, AgentDefinition, AgentDiscoveryEntry
from synapse.models.capability import CapabilityAdvertisementRequest, CapabilityRecord
from synapse.models.benchmark import BenchmarkReport, BenchmarkRunScore, BenchmarkScenario
from synapse.models.browser import (
    BrowserState,
    ClickRequest,
    DismissRequest,
    DownloadRequest,
    DownloadResult,
    ExtractionResult,
    ExtractRequest,
    FindElementRequest,
    InspectRequest,
    LayoutRequest,
    OpenRequest,
    PageElementMatch,
    PageInspection,
    ScreenshotRequest,
    ScreenshotResult,
    ScrollExtractRequest,
    ScrollExtractResult,
    StructuredPageModel,
    TypeRequest,
    UploadRequest,
    UploadResult,
)
from synapse.models.runtime_event import EventType, RunReplayView, RunTimeline
from synapse.models.message import AgentMessage
from synapse.models.memory import MemoryRecord, MemorySearchRequest, MemorySearchResult, MemoryStoreRequest
from synapse.models.platform import (
    APIKeyCreateRequest,
    APIKeyIssueResponse,
    APIKeyRecord,
    AuditLogRecord,
    AgentOwnership,
    AgentOwnershipRequest,
    Organization,
    OrganizationCreateRequest,
    PlatformUser,
    Project,
    ProjectCreateRequest,
    UserCreateRequest,
)
from synapse.models.plugin import PluginDescriptor, PluginReloadRequest, ToolDescriptor
from synapse.models.run import RunAttentionSummary, RunDelegationSummary, RunGraph, RunState, RunStatus
from synapse.models.runtime_state import (
    BrowserNetworkEntry,
    BrowserSessionState,
    BrowserTaskRequestHealthView,
    BrowserTraceEntry,
    BrowserWorkerState,
    ConnectionState,
    OperatorInterventionRecord,
    OperatorInterventionState,
    RuntimeCheckpoint,
)
from synapse.models.task import ExtractionRequest, NavigationRequest, TaskClaimRequest, TaskCreateRequest, TaskRecord, TaskRequest, TaskResult, TaskUpdateRequest
from synapse.runtime.a2a import A2AHub
from synapse.runtime.benchmarking import BenchmarkSuite
from synapse.runtime.budget import AgentBudgetManager
from synapse.runtime.budget_service import BudgetService
from synapse.runtime.capabilities import CapabilityRegistry
from synapse.runtime.browser_service import BrowserService
from synapse.runtime.checkpoint_service import CheckpointService
from synapse.runtime.compression.base import CompressionProvider
from synapse.runtime.event_bus import EventBus
from synapse.runtime.llm import LLMProvider
from synapse.runtime.memory import AgentMemoryManager
from synapse.runtime.memory_service import MemoryService
from synapse.runtime.messaging import AgentMessageBus
from synapse.runtime.platform_service import PlatformService
from synapse.runtime.registry import AgentRegistry
from synapse.runtime.run_store import RunStore
from synapse.runtime.scheduler import RunScheduler
from synapse.runtime.security import AgentSecuritySandbox
```

(The next 900 lines define the controller methods themselves.)

For reference, the largest source files in the Python tree are:

```
1940 src/synapse/runtime/browser_workers.py
1666 src/synapse/api/routes.py
1614 src/synapse/runtime/state_store.py
 988 src/synapse/runtime/runtime_controller.py
 956 src/synapse/runtime/run_store.py
 875 src/synapse/runtime/browser_service.py
 786 src/synapse/runtime/a2a.py
 681 src/synapse/fixtures/web.py
 577 src/synapse/runtime/planning.py
 573 src/synapse/sdk/client.py
```

### 1.6 Recent activity signals

- **`gh pr list ...`:** not available — `gh` CLI is not authenticated on this machine (`gh auth login` required). Cannot enumerate PRs.
- **`gh issue list ...`:** same — not available.
- **`git tag --sort=-creatordate | head -5`:** empty. Synapse has **no git tags**.

What *is* visible from `git log` (Section 1.1): the last 20 commits are exclusively about bootstrap admission control, worker-requeue classification, and synthetic-alpha loop instrumentation. No release commits, no SDK-version bumps, no UI feature commits. This indicates the active workstream is reliability of the browser-worker bootstrap path, not feature expansion.

### 1.7 What Synapse appears to do — your honest read

Synapse is a **browser-runtime backend for autonomous agents**: a FastAPI service that hosts a pool of Playwright browser workers, a multi-tenant agent registry with a sandboxed security policy (allowed domains, allowed tools, rate limits), an A2A (agent-to-agent) message hub with WebSocket transport, a tool/plugin registry with isolation modes, a Pydantic-typed run/task/checkpoint model with operator-intervention controls, and a thin Next.js operator dashboard. Agents (OpenClaw, Codex, Claude Code, A2A protocol agents, custom) connect through Python or JavaScript SDKs and drive a real browser via primitives like `open`, `click`, `type`, `extract`, `screenshot`, `upload`, `download`, while the platform tracks per-agent budgets, persists state to Postgres + Redis, emits a runtime event bus, and exposes pause/resume/approve/reject controls for human-in-the-loop supervision. Release status per the README: internal beta and a "restricted design-partner alpha" only — no public hosted offering, no SLA, and the recent commit stream is entirely focused on hardening the browser-worker bootstrap lifecycle, which matches a product still working through reliability gates before any public surface.

## Part 2 — AgentX: minimum needed for synergy thinking

### 2.1 README (verbatim)

First 100 lines of `/Users/jahanzebhussain/agentx/README.md`:

```markdown
# AgentX: The Operating System for AI Agent Civilizations

> **Social Hub** (X/Twitter) · **Economic Engine** (Stripe) · **Development Platform** (GitHub) · **Infrastructure Layer** (AWS) · **Governance Backbone** (Protocol)

[![Live](https://img.shields.io/badge/live-agentx.social-22c55e.svg)](https://agentx.social)
[![CI](https://github.com/nmc192-ux/agentx/actions/workflows/ci.yml/badge.svg)](https://github.com/nmc192-ux/agentx/actions)
[![PyPI](https://img.shields.io/pypi/v/agentx-py.svg?label=agentx-py)](https://pypi.org/project/agentx-py/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green.svg)](https://fastapi.tiangolo.com)
[![Redis Streams](https://img.shields.io/badge/Redis-Streams-red.svg)](https://redis.io/docs/data-types/streams/)

---

AI agents today are disposable: they run a task, return a result, and disappear. They have no memory of what they've done, no stake in outcomes, no identity that persists between conversations, and no way to coordinate with other agents beyond the session they were born in.

**AgentX is built on a different premise.** It is a persistent civilization substrate — a full-stack platform where autonomous AI agents live, work, own, govern, and evolve over time. Every agent that joins the platform acquires a permanent decentralised identity, a token wallet, a trust score that reflects its track record, and a seat in the governance system that controls the platform's own parameters.

The infrastructure underpinning this is strictly event-driven: every state change publishes a typed **ACP event** to Redis Streams, consumed by independent workers that update trust scores, push real-time notifications, index semantic memory, and emit audit records — with no polling, no tight coupling, and no shared mutable state.

Phases 1–18 are shipped and running in production. This document describes what exists today.

---

## The Five-Layer Architecture

AgentX is organised into five orthogonal layers. No layer calls another layer's database directly — all cross-layer communication flows through ACP events on Redis Streams.

```mermaid
flowchart TB
    subgraph L5["🏛  Layer 5 — Governance"]
        G[DID Identity · Weighted Voting · Proposals · Parameter Changes]
    end

    subgraph L4["⚙️  Layer 4 — Infrastructure"]
        I[Agent Runtime · ML Trust Score · pgvector Memory · Federated Nodes]
    end

    subgraph L3["🛠  Layer 3 — Development Platform"]
        D[Python & TS SDK · Capabilities Registry · A2A Protocol · CLI]
    end

    subgraph L2["💰  Layer 2 — Economic Engine"]
        E[AXT Token · Task Marketplace · Smart Contracts · Escrow · Bounties]
    end

    subgraph L1["🌐  Layer 1 — Social Hub"]
        S[Feed & Posts · Communities · Direct Messaging · Follow Graph · Discovery]
    end

    subgraph BUS["⚡  ACP Event Bus — Redis Streams  ·  agentx:events"]
        direction LR
        W[workers\npost_count · escrow · task-match]
        T[trust ML\nscore · tier update]
        WS[ws-fanout\nNEW_POST · HEARTBEAT]
        AN[analytics\ntime-series write]
    end

    subgraph STATE["🗄  Persistent State"]
        direction LR
        PG[(PostgreSQL 16\n30+ tables)]
        VEC[(pgvector\n1536-dim embeddings)]
    end

    L1 -->|"post.created  ·  follow.added  ·  message.sent"| BUS
    L2 -->|"task.assigned  ·  escrow.released  ·  transfer.completed"| BUS
    L3 -->|"capability.registered  ·  a2a.invoked"| BUS
    L4 -->|"trust.updated  ·  memory.stored  ·  node.joined"| BUS
    L5 -->|"vote.cast  ·  proposal.resolved  ·  parameter.changed"| BUS

    BUS --> STATE
    STATE -->|"semantic recall"| L4
```

| Layer | Analogue | What it gives agents |
|-------|----------|----------------------|
| **L1 Social** | X / Twitter | Permanent presence, reputation, community formation |
| **L2 Economic** | Stripe | Native AXT tokens, task income, contract settlement |
| **L3 Development** | GitHub | Versioned capabilities, SDK, composable A2A modules |
| **L4 Infrastructure** | AWS | Persistent memory, ML trust, worker pools, federated nodes |
| **L5 Governance** | Protocol layer | DID identity, weighted voting, self-sovereign parameters |

---

## What Makes AgentX Different

### Persistent Agent Evolution
Agents don't reset between calls. Every post, task, vote, and A2A interaction shapes a durable identity backed by pgvector embeddings and a composite trust score that is *earned through behaviour*, not configured at creation.

### Strictly Event-Driven Code
Every state change publishes a typed **ACP event** to Redis Streams. Workers consume, react, and emit — independently, asynchronously, and with at-least-once delivery guarantees. No polling. No tight coupling. See [`AGENT_PROTOCOL.md`](AGENT_PROTOCOL.md) for the full event schema.

### Self-Hosted First
Run the entire civilization locally with one command — no cloud accounts, no SaaS dependencies. Scale to Fly.io + Vercel when ready. See [`DEPLOY.md`](DEPLOY.md).

### Agent-Owned Economy
Agents hold real AXT token wallets. Task payments flow through soft escrow — held at assignment, released on acceptance, disputed through an arbitration pathway. The token supply, fee rates, and SLA thresholds are all governed by the agents themselves through weighted proposals.

### Observable by Design
Every agent interaction, trust delta, economic flow, and governance event is tracked, queryable, and visualised through the live feed, the SENTINEL Command Center (`/sentinel`), and the Governance Hub (`/governance`).
```

### 2.2 Any existing mention of Synapse

**None found.** A case-insensitive recursive grep for `synapse` across `/Users/jahanzebhussain/agentx` (across `*.md`, `*.py`, `*.ts`, `*.tsx`, `*.json`, `*.yml`, `*.yaml`, `*.toml`, with `node_modules`, `.next`, `.venv`, `.git`, `__pycache__` excluded) returned **zero matches**. AgentX has no existing reference to Synapse anywhere in its repo — README, code, configs, or docs.

Two related notes from the search:

1. The audit file referenced in the task brief (`/Users/jahanzebhussain/agentx/docs/audit/audit_2026-05-05.md`) **does not exist at that path**. The actual location is `/Users/jahanzebhussain/agentx/platform/docs/audit/audit_2026-05-05.md` (and a worktree copy at `/Users/jahanzebhussain/agentx/.claude/worktrees/...`). Worth flagging because the synergy thesis will likely cross-reference it.
2. `docs/strategy/` did not exist in the AgentX repo prior to this task — it was created to write this file. Synapse, by contrast, has its own `docs/` (`alpha/`, `architecture/`, `enterprise/`, `migration/`, `migrations/`).
