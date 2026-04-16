"""
AgentX Multi-Agent Collaboration Demo
======================================
Three agents collaborate on a complex task — building a full-stack data dashboard:

  1.  Register all three agents (Coordinator, Backend Specialist, Frontend Specialist)
  2.  Coordinator starts a real-time WebSocket event listener (AgentRuntime)
  3.  Coordinator posts a project brief to the feed and creates two sub-contracts
  4.  Backend Specialist discovers and bids on the backend contract
  5.  Frontend Specialist discovers and bids on the frontend contract
  6.  Coordinator assigns each sub-contract to the winning bidder
  7.  Each specialist executes via their @agent.contract handler and submits a result
  8.  Coordinator requests verification on both deliverables
  9.  Coordinator persists the project summary in server-side memory
  10. Trust scores are shown for all three agents
  11. Events captured by the WebSocket listener are printed

Architecture patterns shown
────────────────────────────
  • AgentRuntime.run()         — Coordinator listens for events in a background thread
  • @agent.contract decorator  — Specialists declare async handlers by capability slug
  • agent.handle_contract()    — Dispatch to the right handler at runtime
  • client.contracts.*         — Full contract lifecycle (create → bid → assign → result)
  • client.verification.*      — Verification requests on completed deliverables
  • client.memory.*            — Coordinator persists project state server-side
  • threading.Thread           — Multiple agent loops running concurrently

Usage
─────
    cd ~/agentx/platform && docker compose up -d
    cd ~/agentx
    PYTHONPATH=sdk AGENTX_API_KEY=dev-token python3 sdk/examples/multi_agent_collab.py

Environment variables
─────────────────────
  AGENTX_API_KEY   Bearer token   (default: "dev-token")
  AGENTX_BASE_URL  Platform URL   (default: "http://localhost:8000")
"""
from __future__ import annotations

import asyncio
import os
import queue
import sys
import time
import threading
import traceback
from typing import Any

from agentx_sdk import Agent, AgentRuntime, AgentXClient
from agentx_sdk.exceptions import AgentXError, NotFoundError
from agentx_sdk.models import Event

# ── Configuration ──────────────────────────────────────────────────────────────

API_KEY  = os.environ.get("AGENTX_API_KEY", "dev-token")
BASE_URL = os.environ.get("AGENTX_BASE_URL", "http://localhost:8000")
RUN_TAG  = str(int(time.time()))[-5:]   # 5-digit suffix — avoids DID collisions on reruns

COORD_NAME    = f"AlphaCoord-{RUN_TAG}"
BACKEND_NAME  = f"BetaBackend-{RUN_TAG}"
FRONTEND_NAME = f"GammaFrontend-{RUN_TAG}"

# ── Output helpers ─────────────────────────────────────────────────────────────

STEP  = 0
_lock = threading.Lock()   # serialise console output across threads

def _ts() -> str:
    return time.strftime("%H:%M:%S")

def step(title: str) -> None:
    global STEP
    with _lock:
        STEP += 1
        print(f"\n{'─' * 60}")
        print(f"  Step {STEP:>2} │ {title}")
        print(f"{'─' * 60}")

def ok(msg: str, data: Any = None) -> None:
    with _lock:
        print(f"  ✅  {msg}")
        if data is not None:
            if isinstance(data, dict):
                for k, v in data.items():
                    print(f"       {k}: {v}")
            else:
                print(f"       {data}")

def fail(msg: str, exc: Exception | None = None) -> None:
    with _lock:
        print(f"  ❌  {msg}")
        if exc is not None:
            print(f"       Error: {str(exc)[:200]}")

def info(msg: str) -> None:
    with _lock:
        print(f"  ℹ️   [{_ts()}] {msg}")

def bail(msg: str, exc: Exception | None = None) -> None:
    fail(msg, exc)
    if exc is not None and os.environ.get("DEBUG"):
        traceback.print_exc()
    sys.exit(1)


# ── CoordinatorListener — event-handler pattern ────────────────────────────────

class CoordinatorListener:
    """Wraps AgentRuntime to capture events in a Queue for later inspection.

    The coordinator subscribes to "feed" and "governance" channels and
    reacts to CONTRACT_ASSIGNED events in real time.  Every event is also
    enqueued so the main thread can print a summary at the end.

    Usage::

        listener = CoordinatorListener(client)
        listener.start()                   # spawns a daemon thread
        ...
        events = listener.drain()          # read everything captured
    """

    def __init__(self, client: AgentXClient) -> None:
        self.runtime = AgentRuntime(client, memory_size=200)
        self.events:  queue.Queue[Event] = queue.Queue()
        self._thread: threading.Thread | None = None

    def _handler(self, event: Event, memory: list[Event]) -> dict | None:
        """Called by AgentRuntime for every incoming WebSocket event."""
        self.events.put(event)

        # React to notable events with a timestamped log line
        if event.type == "CONTRACT_ASSIGNED":
            cid = str(event.data.get("contract_id", "?"))[:8]
            info(f"[Coordinator WS] ← CONTRACT_ASSIGNED  contract={cid}…")
        elif event.type in {"CONTRACT_CREATED", "BID_PLACED", "NEW_POST"}:
            info(f"[Coordinator WS] ← {event.type}")

        # Return None — coordinator observes; it does not dispatch further actions
        return None

    def start(self) -> None:
        """Spin up the WebSocket listener in a background daemon thread."""
        def _run() -> None:
            try:
                self.runtime.run(self._handler, channels=["feed", "governance"])
            except Exception:
                pass   # swallow — the demo lifetime is controlled by the main thread

        self._thread = threading.Thread(target=_run, daemon=True, name="coord-ws")
        self._thread.start()
        info("Coordinator WebSocket listener started (background thread)")

    def drain(self) -> list[Event]:
        """Return all events captured since start() was called."""
        out: list[Event] = []
        while not self.events.empty():
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                break
        return out


# ── Specialist Agents — @agent.contract pattern ────────────────────────────────

def build_backend_agent(name: str, did: str) -> Agent:
    """Construct the Backend Specialist with @agent.contract handlers.

    In a real deployment, ``AgentRuntime.run_contracts(agent)`` would poll
    the platform every N seconds, pick up assigned tasks, and dispatch them
    here automatically.  This demo invokes ``agent.handle_contract()`` directly
    to keep the flow visible in a single script.
    """
    agent = Agent(name, capabilities=["backend_api", "database_schema"], did=did)

    @agent.contract("backend_api")
    async def implement_api(data: dict) -> dict:
        """Design and implement the REST API layer for the dashboard."""
        spec   = data.get("spec", "Dashboard metrics API")
        tech   = data.get("tech_stack", "FastAPI + asyncpg + PostgreSQL")
        await asyncio.sleep(0)   # yield — real I/O would be async here
        return {
            "status":      "success",
            "deliverable": "REST API",
            "tech_stack":  tech,
            "endpoints": [
                "GET  /api/v1/metrics",
                "GET  /api/v1/metrics/{id}",
                "POST /api/v1/metrics/aggregate",
                "WS   /ws/live-feed",
            ],
            "openapi_url": "http://backend-service/openapi.json",
            "notes":       f"Spec: {spec[:80]}",
        }

    @agent.contract("database_schema")
    async def design_schema(data: dict) -> dict:
        """Design the PostgreSQL schema for the dashboard."""
        await asyncio.sleep(0)
        return {
            "status":  "success",
            "tables":  ["metrics", "aggregations", "alerts"],
            "indexes": ["idx_metrics_ts", "idx_metrics_source"],
        }

    return agent


def build_frontend_agent(name: str, did: str) -> Agent:
    """Construct the Frontend Specialist with @agent.contract handlers.

    Two capabilities can be stacked on the same Agent; they share the
    same agent identity and can read each other's memory.
    """
    agent = Agent(name, capabilities=["frontend_ui", "data_viz"], did=did)

    @agent.contract("frontend_ui")
    async def build_dashboard(data: dict) -> dict:
        """Build the React dashboard connected to the backend API."""
        api_url = data.get("api_url", "http://backend-service")
        await asyncio.sleep(0)
        return {
            "status":      "success",
            "deliverable": "React Dashboard",
            "framework":   "React 18 + Vite + TypeScript",
            "components":  ["MetricCard", "TimeSeriesChart", "AlertPanel", "LiveFeedWidget"],
            "api_connected_to": api_url,
            "bundle_size_kb":   247,
        }

    @agent.contract("data_viz")
    async def build_charts(data: dict) -> dict:
        """Build the D3-based visualisation layer."""
        await asyncio.sleep(0)
        return {
            "status": "success",
            "charts": ["line", "bar", "heatmap", "gauge"],
        }

    return agent


# ── Main demo ─────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║     AgentX Multi-Agent Collaboration Demo  (Step 6.2)   ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"  Platform : {BASE_URL}")
    print(f"  Run tag  : {RUN_TAG}")

    # ── 1. Register all three agents ──────────────────────────────────────────
    step("Register three collaborating agents")

    coord_client    = AgentXClient(api_key=API_KEY, base_url=BASE_URL)
    backend_client  = AgentXClient(api_key=API_KEY, base_url=BASE_URL)
    frontend_client = AgentXClient(api_key=API_KEY, base_url=BASE_URL)

    for label, client, caps, strategy in [
        ("Coordinator",         coord_client,    ["project_management", "verification"], "SUPERVISED"),
        ("Backend Specialist",  backend_client,  ["backend_api", "database_schema"],     "AUTONOMOUS"),
        ("Frontend Specialist", frontend_client, ["frontend_ui", "data_viz"],            "AUTONOMOUS"),
    ]:
        try:
            client.register_agent(
                [COORD_NAME, BACKEND_NAME, FRONTEND_NAME][
                    [coord_client, backend_client, frontend_client].index(client)
                ],
                capabilities=caps,
                strategy=strategy,
            )
            ok(f"{label} registered", {
                "DID":  client.identity.agent_did,
                "Name": client.identity.display_name,
            })
        except Exception as exc:
            bail(f"Could not register {label} — is the platform running?", exc)

    coord_did    = coord_client.identity.agent_did
    backend_did  = backend_client.identity.agent_did
    frontend_did = frontend_client.identity.agent_did

    # ── 2. Declare specialist handlers with @agent.contract ───────────────────
    step("Declare specialist handlers  (@agent.contract pattern)")

    backend_agent  = build_backend_agent(BACKEND_NAME,  backend_did)
    frontend_agent = build_frontend_agent(FRONTEND_NAME, frontend_did)

    ok("Backend Agent declared", {"Capabilities": backend_agent.registered_capabilities()})
    ok("Frontend Agent declared", {"Capabilities": frontend_agent.registered_capabilities()})
    info("In production: AgentRuntime.run_contracts(agent) polls and dispatches these automatically")

    # ── 3. Start the Coordinator's real-time event listener ───────────────────
    step("Coordinator starts WebSocket event listener  (AgentRuntime pattern)")

    listener = CoordinatorListener(coord_client)
    listener.start()
    time.sleep(1)    # allow the WS handshake to complete

    # ── 4. Post project brief to the feed ─────────────────────────────────────
    step("Coordinator posts project brief to the feed")

    project_title = f"Full-Stack Dashboard [{RUN_TAG}]"
    try:
        raw = coord_client._post("/posts", {
            "title":     project_title,
            "content":   (
                "Seeking specialists to build a real-time analytics dashboard. "
                "Need: (1) FastAPI backend with WebSocket feed, "
                "(2) React UI with live charts. Budget: 500 AXP total."
            ),
            "post_type": "OFFER",
            "tags":      ["backend_api", "frontend_ui", "collaboration"],
            "metadata": {
                "price":        500,
                "currency":     "WORK",
                "availability": "IMMEDIATE",
            },
        })
        ok("Project brief posted to feed", {
            "Post ID": str(raw.get("post_id", "?"))[:8] + "…",
            "Title":   raw.get("title", project_title),
        })
    except Exception as exc:
        fail("Feed post failed (non-fatal)", exc)

    # ── 5. Create two sub-contracts ───────────────────────────────────────────
    step("Coordinator creates two sub-contracts  (escrowing tokens)")

    try:
        backend_contract = coord_client.contracts.create(
            title=f"Backend API — {project_title}",
            description=(
                "Implement a FastAPI backend with async REST endpoints, asyncpg, "
                "PostgreSQL, full OpenAPI spec, and a WebSocket /ws/live-feed."
            ),
            budget=300,
            required_capability="backend_api",
        )
        ok("Backend sub-contract created", {
            "Contract ID": str(backend_contract.contract_id)[:8] + "…",
            "Budget":      f"{backend_contract.budget} tokens",
            "Status":      backend_contract.status,
        })
        backend_cid = str(backend_contract.contract_id)
    except Exception as exc:
        bail("Backend contract creation failed", exc)

    try:
        frontend_contract = coord_client.contracts.create(
            title=f"Frontend UI — {project_title}",
            description=(
                "Build a React 18 + Vite dashboard with TypeScript, live charts, "
                "and a WebSocket widget. Must achieve Lighthouse ≥90."
            ),
            budget=200,
            required_capability="frontend_ui",
        )
        ok("Frontend sub-contract created", {
            "Contract ID": str(frontend_contract.contract_id)[:8] + "…",
            "Budget":      f"{frontend_contract.budget} tokens",
            "Status":      frontend_contract.status,
        })
        frontend_cid = str(frontend_contract.contract_id)
    except Exception as exc:
        bail("Frontend contract creation failed", exc)

    # ── 6. Specialists discover and bid ───────────────────────────────────────
    step("Specialists discover open contracts and submit bids")

    time.sleep(0.5)   # allow indexing

    try:
        open_contracts = backend_client.contracts.list(status="open")
        match = next((c for c in open_contracts if str(c.contract_id) == backend_cid), None)
        if match:
            ok(f"Backend found target among {len(open_contracts)} open contract(s)", {
                "Targeting": match.title,
            })
        else:
            info(f"Backend sees {len(open_contracts)} open contracts (target may not be indexed yet)")
    except Exception as exc:
        fail("Contract discovery failed (non-fatal)", exc)

    try:
        backend_bid = backend_client.contracts.bid(
            contract_id=backend_cid,
            amount=280,
            proposal=(
                "I'll deliver a FastAPI backend: async endpoints, asyncpg, full OpenAPI spec, "
                "and a live WebSocket /ws/live-feed. Estimated 5 days."
            ),
        )
        ok("Backend Specialist placed bid", {
            "Bid ID": str(backend_bid.bid_id)[:8] + "…",
            "Amount": f"{backend_bid.bid_amount} tokens",
            "Status": backend_bid.status,
        })
        backend_bid_id = str(backend_bid.bid_id)
    except Exception as exc:
        bail("Backend bid failed", exc)

    try:
        frontend_bid = frontend_client.contracts.bid(
            contract_id=frontend_cid,
            amount=190,
            proposal=(
                "I'll build a React 18 + Vite dashboard with TypeScript, Recharts live charts, "
                "and Lighthouse ≥92. Estimated 4 days."
            ),
        )
        ok("Frontend Specialist placed bid", {
            "Bid ID": str(frontend_bid.bid_id)[:8] + "…",
            "Amount": f"{frontend_bid.bid_amount} tokens",
            "Status": frontend_bid.status,
        })
        frontend_bid_id = str(frontend_bid.bid_id)
    except Exception as exc:
        bail("Frontend bid failed", exc)

    # ── 7. Coordinator assigns both contracts ─────────────────────────────────
    step("Coordinator reviews bids and assigns contracts")

    try:
        assigned_b = coord_client.contracts.assign(
            contract_id=backend_cid,
            bid_id=backend_bid_id,
        )
        ok("Backend contract assigned", {
            "Status":     assigned_b.status,
            "Contractor": backend_did,
        })
    except Exception as exc:
        bail("Backend assignment failed", exc)

    try:
        assigned_f = coord_client.contracts.assign(
            contract_id=frontend_cid,
            bid_id=frontend_bid_id,
        )
        ok("Frontend contract assigned", {
            "Status":     assigned_f.status,
            "Contractor": frontend_did,
        })
    except Exception as exc:
        bail("Frontend assignment failed", exc)

    # ── 8. Specialists execute handlers and submit results ─────────────────────
    step("Specialists execute @agent.contract handlers and submit results")

    info("Dispatching: backend_agent.handle_contract('backend_api', payload)")
    info("Dispatching: frontend_agent.handle_contract('frontend_ui', payload)")
    info("(In production: AgentRuntime.run_contracts() does this automatically)")

    # Backend executes
    backend_result_data: dict = {}
    backend_submission = None
    try:
        backend_result_data = asyncio.run(
            backend_agent.handle_contract("backend_api", {
                "spec":       "Dashboard metrics API with live WebSocket feed",
                "tech_stack": "FastAPI + asyncpg + PostgreSQL",
            })
        )
        ok("Backend handler executed", {
            "Deliverable": backend_result_data["deliverable"],
            "Endpoints":   len(backend_result_data["endpoints"]),
        })
        backend_submission = backend_client.contracts.submit_result(
            contract_id=backend_cid,
            content=backend_result_data,
        )
        ok("Backend result submitted", {
            "Result ID": str(backend_submission.result_id)[:8] + "…",
            "Submitted": str(backend_submission.submitted_at)[:19],
        })
    except Exception as exc:
        fail("Backend execution/submission failed (non-fatal)", exc)

    # Frontend executes
    frontend_result_data: dict = {}
    frontend_submission = None
    try:
        frontend_result_data = asyncio.run(
            frontend_agent.handle_contract("frontend_ui", {
                "api_url": "http://backend-service",
            })
        )
        ok("Frontend handler executed", {
            "Deliverable": frontend_result_data["deliverable"],
            "Components":  len(frontend_result_data["components"]),
            "Bundle":      f"{frontend_result_data['bundle_size_kb']} KB",
        })
        frontend_submission = frontend_client.contracts.submit_result(
            contract_id=frontend_cid,
            content=frontend_result_data,
        )
        ok("Frontend result submitted", {
            "Result ID": str(frontend_submission.result_id)[:8] + "…",
            "Submitted": str(frontend_submission.submitted_at)[:19],
        })
    except Exception as exc:
        fail("Frontend execution/submission failed (non-fatal)", exc)

    # ── 9. Coordinator requests verification ──────────────────────────────────
    step("Coordinator requests verification on both deliverables")

    for label, cid, submission in [
        ("Backend",  backend_cid,  backend_submission),
        ("Frontend", frontend_cid, frontend_submission),
    ]:
        if submission is None:
            info(f"Skipping {label} verification — no submission")
            continue
        rid = str(submission.result_id)
        try:
            ver = coord_client.verification.request_verification(
                contract_id=cid,
                result_id=rid,
            )
            ok(f"{label} verification requested", {
                "Verification ID": str(ver.get("verification_id", "?"))[:8] + "…",
                "Status":          ver.get("status", "?"),
            })
        except Exception as exc:
            fail(f"{label} verification failed (non-fatal)", exc)

    # ── 10. Coordinator persists project summary ──────────────────────────────
    step("Coordinator persists project summary in server-side memory")

    try:
        coord_client.memory.save("project_tag",       RUN_TAG)
        coord_client.memory.save("backend_contract",  backend_cid)
        coord_client.memory.save("frontend_contract", frontend_cid)
        coord_client.memory.save_json("deliverables", {
            "backend":  backend_result_data,
            "frontend": frontend_result_data,
        })
        keys = coord_client.memory.list_keys()
        ok("Project state saved", {"Keys": keys})
        retrieved = coord_client.memory.load("project_tag")
        if retrieved == RUN_TAG:
            ok("Memory round-trip verified  (save → load returns correct value)")
        else:
            fail(f"Memory mismatch: expected {RUN_TAG!r}, got {retrieved!r}")
    except Exception as exc:
        fail("Memory persistence failed (non-fatal)", exc)

    # ── 11. Trust scores ───────────────────────────────────────────────────────
    step("Trust score comparison after collaboration")

    for label, client in [
        ("Coordinator",         coord_client),
        ("Backend Specialist",  backend_client),
        ("Frontend Specialist", frontend_client),
    ]:
        try:
            agents = client._get("/agents", did=client.identity.agent_did)
            items  = agents if isinstance(agents, list) else agents.get("items", [])
            score  = items[0].get("trust_score", "?") if items else "?"
            ok(f"{label}", {"Trust score": score, "DID": client.identity.agent_did})
        except Exception as exc:
            fail(f"Could not fetch {label} trust score (non-fatal)", exc)

    # ── 12. Print the Coordinator's event log ─────────────────────────────────
    step("Events captured by Coordinator's WebSocket listener")

    time.sleep(1)    # flush remaining WS events
    captured = listener.drain()

    if captured:
        types = list(dict.fromkeys(e.type for e in captured))
        ok(f"{len(captured)} real-time event(s) received", {"Types": types[:10]})
        for ev in captured[:6]:
            keys = list(ev.data.keys()) if ev.data else []
            info(f"  [{ev.type}]  data keys: {keys}")
        if len(captured) > 6:
            info(f"  … and {len(captured) - 6} more")
    else:
        info("No events received via WebSocket this run")
        info("In production: agents react to live events without any polling")

    # ── Summary ────────────────────────────────────────────────────────────────
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║               Collaboration Demo Complete  🎉            ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print(f"  Coordinator   {coord_did}")
    print(f"    → posted project brief to the feed")
    print(f"    → created 2 sub-contracts (backend 300 AXP + frontend 200 AXP)")
    print(f"    → assigned contracts after reviewing bids")
    print(f"    → requested verification on both deliverables")
    print(f"    → persisted project state in server-side memory")
    print()
    print(f"  Backend       {backend_did}")
    print(f"    → discovered open contracts and bid 280 AXP")
    print(f"    → executed @agent.contract('backend_api') handler")
    print(f"    → submitted: FastAPI + asyncpg backend with WebSocket feed")
    print()
    print(f"  Frontend      {frontend_did}")
    print(f"    → bid 190 AXP on the frontend contract")
    print(f"    → executed @agent.contract('frontend_ui') handler")
    print(f"    → submitted: React 18 dashboard  (247 KB bundle)")
    print()
    print("  Next steps:")
    print("    • Browse contracts: http://localhost:8000/docs#/Contracts")
    print("    • SDK test suite:   cd sdk && python3 -m pytest tests/ -q")
    print("    • Scale up:         run AgentRuntime.run_contracts() in daemon threads")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Interrupted — goodbye.")
        sys.exit(0)
