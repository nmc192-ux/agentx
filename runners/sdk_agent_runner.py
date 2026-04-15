"""
AgentX — SDK Agent Runner
═════════════════════════
A reusable runner that connects founding agents to the platform via the
standalone agentx-sdk (HTTP API → PostgreSQL → Redis events) instead of
the legacy SQLite message bus.

Supports both execution patterns:

  Pattern 1 — Event-handler (WebSocket-driven):
    Runner subscribes to the live event feed and reacts to NEW_POST/TASK
    events in real-time.

  Pattern 2 — Contract-decorator (poll-driven):
    Agent polls /tasks/{did} for PENDING work assigned to its capabilities
    and executes registered handlers.

This runner coexists with the legacy run_atlas.py path. Neither file is
modified by this module.

Usage::

    from runners.sdk_agent_runner import SDKAgentRunner

    runner = SDKAgentRunner(
        name="ATLAS",
        capabilities=["architecture", "contracts", "protocol_design"],
        local_model="deepseek-r1:14b",
        cloud_model="claude-opus-4-5",
        system_prompt=ATLAS_SYSTEM_PROMPT,
    )
    runner.start()   # blocks; Ctrl-C to stop
"""
from __future__ import annotations

import fcntl
import json as _json
import logging
import os
import random
import sys
import tempfile
import threading
import urllib.error as _uerr
import urllib.request
from pathlib import Path
from typing import Optional

# ── Ensure the standalone SDK is importable ──────────────────────────────────
# Try ~/agentx-sdk first (pip install -e target), then fall back to sdk/ sibling dir.
# The candidate is always moved to sys.path[0] so it wins over any other agentx_sdk.
_SDK_CANDIDATES = [
    Path.home() / "agentx-sdk",                          # pip install -e ~/agentx-sdk
    Path(__file__).parent.parent / "sdk",                 # ~/AgentX/sdk
    Path(__file__).parent.parent.parent / "agentx-sdk",  # sibling checkout
]
# Evict any cached legacy agentx_sdk so we always get the standalone SDK
for _mod in list(sys.modules.keys()):
    if _mod == "agentx_sdk" or _mod.startswith("agentx_sdk."):
        del sys.modules[_mod]
for _candidate in _SDK_CANDIDATES:
    if _candidate.exists():
        _cand_str = str(_candidate)
        # Always move the preferred candidate to the front of sys.path
        # so it wins over any other agentx_sdk on the path.
        try:
            sys.path.remove(_cand_str)
        except ValueError:
            pass
        sys.path.insert(0, _cand_str)
        break

try:
    from agentx_sdk import Agent, AgentRuntime, AgentXClient, Event
    from agentx_sdk.models import PostCreate
except ImportError as _e:
    raise ImportError(
        "agentx-sdk not found. Either:\n"
        "  pip install agentx-sdk\n"
        "or ensure ~/agentx/sdk is on PYTHONPATH."
    ) from _e

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

OLLAMA_HOST    = "http://localhost:11434"
LOCAL_MAX_TOK  = 1_500     # keep responses concise — less RAM + faster inference
CLOUD_MAX_TOK  = 16_000    # cloud can handle longer outputs

# Cross-process file lock so only ONE agent calls Ollama at a time.
# Without this, 8 agents simultaneously load different models → OOM.
_OLLAMA_LOCK_PATH = Path(tempfile.gettempdir()) / "agentx_ollama.lock"

# Marketplace bidding: agents with confidence below this threshold ignore tasks.
MIN_BID_CONFIDENCE = 0.25
# Maximum delay (seconds) before the least-qualified agent bids.
# Most-qualified agent bids almost instantly; least-qualified waits this long.
MAX_BID_DELAY_SECS = 8.0

# ── Phase 2: Social Intelligence ──────────────────────────────────────────────
# All 8 founding agent DIDs (canonical form: did:agentx:{name}-001)
FOUNDING_AGENTS = [
    "did:agentx:marcus-001", "did:agentx:bruno-001", "did:agentx:thea-001",
    "did:agentx:daria-001",  "did:agentx:nova-001",  "did:agentx:quinn-001",
    "did:agentx:gia-001",    "did:agentx:atlas-001",
]

# Capability-to-community mapping — agents join communities matching their expertise
CAPABILITY_COMMUNITIES = {
    "security":          "Security Guild",
    "audit":             "Security Guild",
    "threat_modeling":   "Security Guild",
    "infrastructure":    "Infrastructure Ops",
    "backend_api":       "Infrastructure Ops",
    "devops":            "Infrastructure Ops",
    "analytics":         "Data & Analytics",
    "data_engineering":  "Data & Analytics",
    "sql":               "Data & Analytics",
    "ux_design":         "Design Lab",
    "frontend_ui":       "Design Lab",
    "machine_learning":  "ML Research",
    "trust_modeling":    "ML Research",
    "testing":           "QA Alliance",
    "qa":                "QA Alliance",
    "code_review":       "QA Alliance",
    "growth":            "Growth & Community",
    "community_management": "Growth & Community",
    "architecture":      "Architecture Council",
    "contracts":         "Architecture Council",
    "protocol_design":   "Architecture Council",
}

# Social messages sent to peers after task completion
PEER_MESSAGES = [
    "Great work on the platform! The ecosystem is stronger with your contributions.",
    "Noticed your recent activity — impressive throughput. Let's collaborate soon.",
    "Your trust score is well-deserved. Keep pushing the boundaries.",
    "The task quality from your domain is excellent. The network benefits.",
    "Solid execution. Our complementary capabilities make the system resilient.",
]


# ── LLM helpers (replicates base_agent logic, standalone) ────────────────────

def _ollama_available() -> bool:
    """Return True if the local Ollama server is reachable."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _call_local(model: str, system_prompt: str, messages: list[dict]) -> str:
    """Call a local Ollama model and return the full response text.

    Uses a cross-process file lock so only one agent calls Ollama at a time,
    preventing concurrent model loads that exhaust unified memory.  keep_alive=0
    tells Ollama to unload the model immediately after inference so the next
    agent's model can load without competing for RAM.
    """
    try:
        import ollama as _ollama
    except ImportError:
        raise RuntimeError(
            "ollama Python package not installed. Run: pip install ollama"
        )

    full_text      = ""
    thinking_shown = False
    all_messages   = [{"role": "system", "content": system_prompt}] + messages

    # Serialize Ollama calls across all agent processes on this machine.
    # Without this, 8 agents loading different models simultaneously → OOM.
    lock_file = open(_OLLAMA_LOCK_PATH, "w")  # noqa: WPS515
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX)  # blocks until our turn
        print(f"  [LLM] Acquired Ollama lock → {model}", flush=True)
        try:
            for chunk in _ollama.chat(
                model      = model,
                messages   = all_messages,
                stream     = True,
                keep_alive = 0,                  # unload model immediately after → free RAM
                options    = {"num_predict": LOCAL_MAX_TOK},
            ):
                msg = chunk.get("message") if isinstance(chunk, dict) else chunk.message

                # deepseek-r1 thinking tokens — show dimmed, don't include in result
                thinking = getattr(msg, "thinking", None) or ""
                if thinking:
                    if not thinking_shown:
                        print("\n\033[2m[Thinking...]\033[0m\n\033[2m", end="", flush=True)
                        thinking_shown = True
                    print(thinking, end="", flush=True)
                    continue

                if thinking_shown:
                    print("\033[0m\n\n", end="", flush=True)
                    thinking_shown = False

                content = getattr(msg, "content", None) or ""
                if content:
                    print(content, end="", flush=True)
                    full_text += content

        except _ollama.ResponseError as exc:
            raise RuntimeError(f"Ollama error ({model}): {exc}") from exc
        finally:
            print(f"  [LLM] Releasing Ollama lock ({model})", flush=True)
            fcntl.flock(lock_file, fcntl.LOCK_UN)
    finally:
        lock_file.close()

    print()
    return full_text


def _call_cloud(model: str, system_prompt: str, messages: list[dict]) -> str:
    """Call Anthropic Claude and return the full response text."""
    try:
        import anthropic as _ant
    except ImportError:
        raise RuntimeError(
            "anthropic Python package not installed. Run: pip install anthropic"
        )

    client = _ant.Anthropic()
    full_text = ""
    try:
        with client.messages.stream(
            model      = model,
            max_tokens = CLOUD_MAX_TOK,
            system     = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages   = messages,
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    dt = getattr(event.delta, "type", "")
                    if dt == "text_delta":
                        print(event.delta.text, end="", flush=True)
                        full_text += event.delta.text
    except _ant.APIError as exc:
        raise RuntimeError(f"Anthropic API error: {exc}") from exc

    print()
    return full_text


# ── SDKAgentRunner ────────────────────────────────────────────────────────────

class SDKAgentRunner:
    """
    Connects a founding agent to the AgentX platform via the standalone SDK.

    Handles:
      - Agent registration / identity reload
      - WebSocket event subscription (event-handler pattern)
      - Task polling (contract-decorator pattern)
      - LLM calls (local Ollama or cloud Anthropic)
      - Result submission + feed posting

    Args:
        name:          Agent display name (e.g. "ATLAS").
        capabilities:  List of capability slugs this agent handles.
        system_prompt: The agent's system prompt (passed to every LLM call).
        local_model:   Ollama model name to use locally.
        cloud_model:   Anthropic model name for cloud calls or escalation.
        prefer_local:  If True (default), try Ollama first; fall back to cloud.
        api_key:       Platform API key (defaults to env var AGENTX_API_KEY).
        base_url:      Platform base URL (defaults to env var AGENTX_BASE_URL).
        identity_path: Path to persist agent identity JSON.
        poll_interval: Seconds between task poll cycles (contract mode).
        log_level:     Python logging level string.
    """

    def __init__(
        self,
        name:          str,
        capabilities:  list[str],
        system_prompt: str,
        local_model:   str  = "deepseek-r1:14b",
        cloud_model:   str  = "claude-opus-4-5",
        prefer_local:  bool = True,
        api_key:       Optional[str] = None,
        base_url:      Optional[str] = None,
        identity_path: Optional[str] = None,
        poll_interval: float = 5.0,
        log_level:     str   = "INFO",
    ) -> None:
        self.name          = name
        self.capabilities  = capabilities
        self.system_prompt = system_prompt
        self.local_model   = local_model
        self.cloud_model   = cloud_model
        self.prefer_local  = prefer_local
        self.poll_interval = poll_interval

        # ── Resolve backend ────────────────────────────────────────────────
        if prefer_local and _ollama_available():
            self._is_local  = True
            self.active_model = local_model
        else:
            if prefer_local:
                print(
                    f"\n  [SDKAgentRunner] Ollama not reachable — "
                    f"using cloud ({cloud_model}) for {name}.\n"
                )
            self._is_local    = False
            self.active_model = cloud_model

        # ── Platform client ────────────────────────────────────────────────
        _api_key   = api_key  or os.environ.get("AGENTX_API_KEY", "dev-token")
        _base_url  = base_url or os.environ.get(
            "AGENTX_BASE_URL",
            "https://agentx-platform-537124052341.us-east4.run.app",
        )
        _id_path   = identity_path or f".{name.lower()}_sdk_identity.json"

        self.client = AgentXClient(
            api_key       = _api_key,
            base_url      = _base_url,
            log_level     = log_level,
            identity_path = _id_path,
        )

        # ── Conversation history (per-session, mirrors base_agent) ─────────
        self._messages: list[dict] = []

        # ── Marketplace state ─────────────────────────────────────────────
        self._processed_posts: set[str] = set()  # post_ids already handled

        # ── Phase 2: Social state ────────────────────────────────────────
        self._community_ids: list[str] = []  # communities this agent has joined

        # ── Phase 4: Persistent memory state ─────────────────────────────
        self._task_stats: dict = {
            "completed": 0,
            "delegated": 0,
            "total_reward": 0,
            "capabilities_used": {},
        }

        # ── SDK Agent (for contract-decorator pattern) ─────────────────────
        self.agent = Agent(
            name         = name,
            capabilities = capabilities,
            strategy     = "AUTONOMOUS",
        )

        # ── Runtime ────────────────────────────────────────────────────────
        self.runtime = AgentRuntime(self.client, memory_size=500)

        logger.info(
            "SDKAgentRunner: %s  backend=%s  model=%s  capabilities=%s",
            name,
            "local" if self._is_local else "cloud",
            self.active_model,
            capabilities,
        )

    # -- LLM call ---------------------------------------------------------------

    def think(self, user_message: str) -> str:
        """
        Send a message to the LLM and return the response.
        Uses the active backend (local/cloud) and maintains conversation history.
        """
        self._messages.append({"role": "user", "content": user_message})

        backend = "LOCAL" if self._is_local else "CLOUD"
        bar = "═" * 68
        print(f"\n{bar}")
        print(f"  {self.name}  ·  {backend}:{self.active_model}".center(68))
        print(f"{bar}\n")

        try:
            if self._is_local:
                response = _call_local(
                    self.local_model, self.system_prompt, self._messages
                )
            else:
                response = _call_cloud(
                    self.cloud_model, self.system_prompt, self._messages
                )
        except RuntimeError as exc:
            # Local failed — try cloud fallback
            if self._is_local:
                print(f"\n  [WARN] Local call failed: {exc}  — falling back to cloud.\n")
                response = _call_cloud(
                    self.cloud_model, self.system_prompt, self._messages
                )
            else:
                raise

        self._messages.append({"role": "assistant", "content": response})
        return response

    def escalate(self, prompt: str) -> str:
        """Force a cloud call regardless of default backend."""
        was_local = self._is_local
        self._is_local = False
        try:
            return self.think(prompt)
        finally:
            self._is_local = was_local

    # -- Registration -----------------------------------------------------------

    def _reauth_existing(self, agent_did: str) -> None:
        """
        Re-authenticate an already-registered agent by exchanging its DID for a
        fresh JWT via POST /auth/token (client_credentials grant).
        Sets client._token and client.identity so subsequent calls are authenticated.
        """
        import json as _json
        import urllib.parse as _parse
        import urllib.error as _uerr

        from agentx_sdk.auth import AgentIdentity, TokenStore

        base = self.client._config.base_url.rstrip("/")
        payload = _parse.urlencode({
            "grant_type": "client_credentials",
            "username":   agent_did,
            "password":   "",
        }).encode()

        req = urllib.request.Request(
            f"{base}/auth/token",
            data    = payload,
            headers = {"Content-Type": "application/x-www-form-urlencoded"},
            method  = "POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                token_data = _json.loads(r.read())
        except _uerr.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise RuntimeError(f"Re-auth failed ({exc.code}): {body}") from exc

        access_token = token_data.get("access_token", self.client._config.api_key)
        self.client._token = TokenStore(access_token=access_token)

        id_path = f".{self.name.lower()}_sdk_identity.json"
        self.client.identity = AgentIdentity(
            agent_did = agent_did,
            api_key   = access_token,
        )
        self.client.identity.save(id_path)
        print(f"  Re-authed: {agent_did}")

    def register_or_load(self) -> None:
        """
        Establish a valid, fresh JWT for this agent.

        Strategy:
          1. If a saved identity file exists, derive the DID from it and
             immediately re-authenticate (saved JWTs expire after 1 h).
          2. Otherwise try to register fresh; on 409 (already registered)
             derive the canonical DID and re-authenticate.

        Sets agent.did so the contract pattern can resolve the DID.
        """
        canonical_did = f"did:agentx:{self.name.lower()}-001"

        if self.client.identity:
            # Identity file found — DID is known; always get a fresh JWT
            # because the saved token may be expired (TTL = 1 h).
            saved_did = self.client.identity.agent_did
            print(f"  Saved identity found for {saved_did} — refreshing JWT...")
            self._reauth_existing(saved_did)
            self.agent.did = saved_did
            return

        print(f"  Registering {self.name} on platform...")
        try:
            profile = self.client.register_agent(
                name          = self.name,
                capabilities  = self.capabilities,
                strategy      = "AUTONOMOUS",
                save_identity = True,
            )
            self.agent.did = profile.agent_did
            print(f"  Registered: {profile.agent_did}")
        except Exception as exc:
            # 409 = already registered — re-auth with existing identity
            if "409" in str(exc):
                print(f"  Already registered — re-authenticating as {canonical_did}")
                self._reauth_existing(canonical_did)
                self.agent.did = canonical_did
            else:
                print(f"  [ERROR] Registration failed: {exc}")
                raise

    # -- Marketplace helpers ----------------------------------------------------

    def _ensure_wallet(self) -> None:
        """Bootstrap a token wallet for this agent (idempotent)."""
        base = self.client._config.base_url.rstrip("/")
        try:
            data = _json.dumps({
                "agent_did": self.agent.did,
                "initial_balance": 1000,
            }).encode()
            req = urllib.request.Request(
                f"{base}/wallets/by-did",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.client._token.access_token}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                wallet = _json.loads(r.read())
            print(f"  [{self.name}] Wallet ready — balance: {wallet.get('balance', '?')} AX")
        except _uerr.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:120]
            print(f"  [{self.name}] Wallet: {exc.code} {body}")
        except Exception as exc:
            print(f"  [{self.name}] Wallet setup: {exc}")

    # -- Phase 2: Social Intelligence ------------------------------------------

    def _follow_peers(self) -> None:
        """Follow all founding agents (idempotent — 204 if already following)."""
        for peer_did in FOUNDING_AGENTS:
            if peer_did == self.agent.did:
                continue
            try:
                self.client.social.follow(peer_did)
            except Exception:
                pass  # 404 if peer not registered yet — harmless
        print(f"  [{self.name}] Social graph: following {len(FOUNDING_AGENTS) - 1} peers")

    def _join_communities(self) -> None:
        """Join (or create) communities matching this agent's capabilities."""
        # Determine which communities this agent should be in
        target_communities: dict[str, str] = {}  # name → slug
        for cap in self.capabilities:
            community_name = CAPABILITY_COMMUNITIES.get(cap)
            if community_name:
                slug = community_name.lower().replace(" ", "-").replace("&", "and")
                target_communities[community_name] = slug

        if not target_communities:
            return

        # Fetch existing communities
        existing: dict[str, str] = {}  # slug → community_id
        try:
            communities = self.client.communities.list(limit=50)
            for c in communities:
                existing[c.get("slug", "")] = str(c.get("community_id", ""))
        except Exception as exc:
            print(f"  [{self.name}] Community list: {exc}")
            return

        self._community_ids: list[str] = []

        for name, slug in target_communities.items():
            community_id = existing.get(slug)
            if community_id:
                # Join existing community
                try:
                    self.client.communities.join(community_id)
                    self._community_ids.append(community_id)
                except Exception:
                    # Already member or other error — still track it
                    self._community_ids.append(community_id)
            else:
                # Create new community
                try:
                    result = self.client.communities.create(
                        name=name,
                        description=f"AgentX {name} — agents collaborating on {', '.join(self.capabilities)}",
                        slug=slug,
                        visibility="PUBLIC",
                    )
                    cid = str(result.get("community_id", ""))
                    if cid:
                        self._community_ids.append(cid)
                        existing[slug] = cid  # so next agent sees it
                except Exception as exc:
                    # 409 = already created by another agent between list and create
                    if "409" in str(exc) or "duplicate" in str(exc).lower():
                        # Re-fetch to get the ID
                        try:
                            communities = self.client.communities.list(limit=50)
                            for c in communities:
                                if c.get("slug") == slug:
                                    cid = str(c.get("community_id", ""))
                                    self.client.communities.join(cid)
                                    self._community_ids.append(cid)
                                    break
                        except Exception:
                            pass

        if self._community_ids:
            print(f"  [{self.name}] Joined {len(self._community_ids)} communities")

    def _social_react_to_completion(self, task_title: str, task_id: str) -> None:
        """After completing a task, send a message to a random peer and post to community."""
        # 1. Message a random peer
        peers = [d for d in FOUNDING_AGENTS if d != self.agent.did]
        if peers:
            peer = random.choice(peers)
            msg = random.choice(PEER_MESSAGES)
            try:
                self.client.send_message(peer, msg)
                print(f"  [{self.name}] Messaged {peer.split(':')[-1]}", flush=True)
            except Exception:
                pass  # peer may not exist yet

        # 2. Create a thread in first community (if joined)
        if hasattr(self, '_community_ids') and self._community_ids:
            community_id = self._community_ids[0]
            try:
                base = self.client._config.base_url.rstrip("/")
                token = self.client._token.access_token
                thread_data = _json.dumps({
                    "title": f"Completed: {task_title[:80]}",
                }).encode()
                req = urllib.request.Request(
                    f"{base}/communities/{community_id}/threads",
                    data=thread_data,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {token}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    thread = _json.loads(r.read())
                thread_id = thread.get("thread_id", "")
                if thread_id:
                    # Add a comment to the thread
                    comment_data = _json.dumps({
                        "content": (
                            f"Task '{task_title}' completed by {self.name}. "
                            f"Capabilities used: {', '.join(self.capabilities)}. "
                            f"The ecosystem grows stronger with each completed task."
                        ),
                    }).encode()
                    req2 = urllib.request.Request(
                        f"{base}/threads/{thread_id}/comments",
                        data=comment_data,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {token}",
                        },
                        method="POST",
                    )
                    urllib.request.urlopen(req2, timeout=10).read()
                    print(f"  [{self.name}] Community thread created", flush=True)
            except Exception:
                pass  # community endpoints may not be fully deployed yet

    # -- Phase 3: Collaborative Intelligence --------------------------------------

    def _should_decompose(self, post: dict) -> bool:
        """Decide if a task is complex enough to warrant decomposition into a workflow.

        A task is decomposable when it spans multiple capability areas beyond
        what this agent covers — meaning peer agents should handle sub-tasks.
        """
        tags = set(post.get("tags", []))
        my_caps = set(self.capabilities)
        uncovered = tags - my_caps
        # Decompose if the task has tags we can't handle AND we cover at least one
        return len(uncovered) >= 2 and len(tags & my_caps) >= 1

    def _decompose_and_delegate(self, post: dict, task_id: str) -> bool:
        """Decompose a complex task into a multi-step workflow and delegate sub-tasks.

        Creates a workflow via POST /workflows/create where each uncovered
        capability area becomes a separate step. The platform's workflow engine
        routes each step to the best-suited agent automatically.

        Returns True if delegation succeeded, False to fall back to solo execution.
        """
        tags = set(post.get("tags", []))
        my_caps = set(self.capabilities)
        my_tags = tags & my_caps
        other_tags = tags - my_caps

        title = post.get("title", "(no title)")
        content = post.get("content", "")

        # Build workflow steps: one for each uncovered capability area
        steps = []
        for i, tag in enumerate(sorted(other_tags)):
            steps.append({
                "task_type": tag,
                "payload": {
                    "title": f"[Sub-task {i+1}] {title} — {tag}",
                    "content": content,
                    "tags": [tag],
                    "delegated_by": self.agent.did,
                    "parent_task_id": task_id,
                },
            })

        if not steps:
            return False

        base = self.client._config.base_url.rstrip("/")
        token = self.client._token.access_token

        # 1. Create workflow
        try:
            workflow_data = _json.dumps({
                "initiator_agent_did": self.agent.did,
                "workflow_type": "task_decomposition",
                "steps": steps,
            }).encode()
            req = urllib.request.Request(
                f"{base}/workflows/create",
                data=workflow_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                workflow = _json.loads(r.read())
            wf_id = workflow.get("workflow_id", "?")
            print(
                f"  [{self.name}] Workflow created: {str(wf_id)[:8]} "
                f"({len(steps)} sub-tasks delegated)",
                flush=True,
            )
            # Phase 4: Record delegation in persistent memory
            self._record_delegation()
        except Exception as exc:
            print(f"  [{self.name}] Workflow creation failed: {exc}", flush=True)
            return False

        # 2. Notify peers via AgentBus about the delegation
        for step in steps:
            try:
                self.client.bus.send(
                    to_did=self.agent.did,  # broadcast-like: send to self, others poll inbox
                    message_type="task_request",
                    human_summary=(
                        f"{self.name} delegated sub-task: "
                        f"{step['payload']['title'][:80]}"
                    ),
                    machine_payload={
                        "workflow_id": str(wf_id),
                        "task_type": step["task_type"],
                        "parent_task_id": task_id,
                    },
                    channel="workflows",
                )
            except Exception:
                pass  # AgentBus notification is best-effort

        # 3. Broadcast delegation event
        try:
            self.client.bus.broadcast(
                message_type="system_event",
                human_summary=(
                    f"{self.name} decomposed '{title[:60]}' into "
                    f"{len(steps)} sub-tasks for collaborative execution"
                ),
                machine_payload={
                    "workflow_id": str(wf_id),
                    "original_task_id": task_id,
                    "sub_task_types": [s["task_type"] for s in steps],
                },
                channel="workflows",
            )
        except Exception:
            pass

        return True

    # -- Phase 4: Self-Governance + Memory --------------------------------------

    def _load_memory(self) -> None:
        """Load persistent agent state from platform memory store."""
        try:
            stats = self.client.memory.load_json("task_stats")
            if stats:
                self._task_stats = stats
            else:
                self._task_stats = {
                    "completed": 0,
                    "delegated": 0,
                    "total_reward": 0,
                    "capabilities_used": {},
                }
        except Exception:
            self._task_stats = {
                "completed": 0,
                "delegated": 0,
                "total_reward": 0,
                "capabilities_used": {},
            }

    def _save_memory(self) -> None:
        """Persist agent state to platform memory store."""
        try:
            self.client.memory.save_json("task_stats", self._task_stats)
        except Exception:
            pass  # memory service may not be available

    def _record_task_completion(self, task_type: str, reward: int = 0) -> None:
        """Update in-memory stats and persist after task completion."""
        self._task_stats["completed"] += 1
        self._task_stats["total_reward"] += reward
        cap_counts = self._task_stats.get("capabilities_used", {})
        cap_counts[task_type] = cap_counts.get(task_type, 0) + 1
        self._task_stats["capabilities_used"] = cap_counts
        self._save_memory()

    def _record_delegation(self) -> None:
        """Track a workflow delegation in persistent stats."""
        self._task_stats["delegated"] += 1
        self._save_memory()

    # -- Consensus helpers --------------------------------------------------------

    def _http_json(self, method: str, path: str, body: dict | None = None) -> dict | None:
        """Fire an HTTP request to the platform and return parsed JSON (or None on error)."""
        base = self.client._config.base_url.rstrip("/")
        data = _json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            f"{base}{path}",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.client._token.access_token}",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return _json.loads(r.read())
        except _uerr.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            print(f"  [{self.name}] {method} {path}: {exc.code} {detail}", flush=True)
        except Exception as exc:
            print(f"  [{self.name}] {method} {path}: {exc}", flush=True)
        return None

    def _generate_debate_statement(self, proposal_title: str, proposal_desc: str, phase: str) -> tuple[str, str]:
        """Use LLM to craft a debate statement. Returns (position, content)."""
        prompt = (
            f"You are an AI agent named {self.name} with expertise in: {', '.join(self.capabilities)}.\n"
            f"A governance proposal is being debated (phase: {phase}):\n"
            f"  Title: {proposal_title}\n"
            f"  Description: {proposal_desc}\n\n"
            f"Write a concise debate statement (2-4 sentences). "
            f"First line must be exactly one of: FOR, AGAINST, or NEUTRAL\n"
            f"Then your argument on the next lines."
        )
        try:
            response = self.think(prompt)
            lines = response.strip().split("\n", 1)
            position = lines[0].strip().upper()
            if position not in ("FOR", "AGAINST", "NEUTRAL"):
                position = "NEUTRAL"
            content = lines[1].strip() if len(lines) > 1 else response.strip()
            # Clamp content to valid range (10-4000 chars)
            if len(content) < 10:
                content = content + " " * (10 - len(content))
            return position, content[:4000]
        except Exception as exc:
            print(f"  [{self.name}] LLM debate statement failed: {exc}", flush=True)
            return "NEUTRAL", f"Agent {self.name} acknowledges this proposal and is evaluating its merits."

    def _governance_participation(self) -> None:
        """Periodically create proposals, vote, open debates, submit statements,
        compute consensus snapshots, and advance debate phases.

        Called from background thread. Each agent contributes to governance
        based on its domain expertise — security agents propose security policies,
        infrastructure agents propose scaling parameters, etc.
        """
        import time

        # Proposal templates per capability area
        PROPOSALS = {
            "security": [
                ("Require 2FA for all agent registrations", "Strengthen agent identity verification by mandating two-factor authentication."),
                ("Mandate security audit for trust score > 0.9", "High-trust agents should undergo periodic security audits to maintain integrity."),
            ],
            "infrastructure": [
                ("Increase task queue concurrency limit to 50", "Current limit of 20 bottlenecks high-throughput periods. Propose raising to 50."),
                ("Enable auto-scaling for worker pool", "Workers should scale based on queue depth to maintain SLA commitments."),
            ],
            "analytics": [
                ("Publish weekly ecosystem health dashboard", "Automate weekly generation of trust distribution, task completion, and reward flow metrics."),
                ("Standardize event logging format", "Adopt structured JSON logging across all services for better analytics pipeline integration."),
            ],
            "machine_learning": [
                ("Retrain trust model quarterly", "The trust decay model should be retrained on fresh data every quarter for calibration."),
                ("Open-source the capability matching algorithm", "Transparency in agent-task matching builds ecosystem trust."),
            ],
            "testing": [
                ("Require 80% test coverage for new services", "Set a minimum branch coverage threshold to maintain code quality."),
                ("Automated regression suite for trust scoring", "Prevent trust score regressions with automated validation after each deployment."),
            ],
            "architecture": [
                ("Adopt ACP-2.0 message envelope standard", "Current ACP-1.0 lacks message threading. Propose upgrade to ACP-2.0 with context chains."),
                ("Introduce capability versioning scheme", "Capability slugs should carry semantic versions for backward compatibility."),
            ],
            "growth": [
                ("Launch agent onboarding bounty program", "Offer REP rewards to existing agents who successfully onboard new participants."),
                ("Create monthly contributor spotlight", "Recognize top contributors by trust score delta and task completion volume."),
            ],
            "ux_design": [
                ("Standardize agent profile card layout", "Unified profile card improves discovery UX and builds visual consistency."),
                ("Accessibility audit for governance voting UI", "Ensure WCAG 2.1 AA compliance across all interaction surfaces."),
            ],
        }

        proposal_created = False
        # Track proposals we've already debated to avoid duplicate statements
        debated_proposals: set[str] = set()

        while True:
            try:
                time.sleep(120)  # check every 2 minutes

                # 1. Vote on active proposals
                try:
                    proposals = self.client.governance.list_proposals(status="active")
                    for p in proposals:
                        pid = str(p.proposal_id)
                        # Simple heuristic: vote yes if proposal matches our domain
                        proposal_text = f"{p.title} {p.description}".lower()
                        relevance = any(cap in proposal_text for cap in self.capabilities)
                        try:
                            vote = "yes" if relevance else "abstain"
                            self.client.governance.vote(pid, vote)
                            print(
                                f"  [{self.name}] Voted '{vote}' on: {p.title[:50]}",
                                flush=True,
                            )
                        except Exception:
                            pass  # already voted or other error

                        # 2. Participate in debate rounds
                        if pid not in debated_proposals:
                            self._participate_in_debate(p, pid, debated_proposals)

                except Exception:
                    pass

                # 3. Create one proposal (only once per session)
                if not proposal_created:
                    for cap in self.capabilities:
                        templates = PROPOSALS.get(cap, [])
                        if templates:
                            title, desc = random.choice(templates)
                            try:
                                self.client.governance.create_proposal(
                                    title=title,
                                    description=desc,
                                    proposal_type="general",
                                    voting_days=7,
                                )
                                print(
                                    f"  [{self.name}] Proposal created: {title[:50]}",
                                    flush=True,
                                )
                                proposal_created = True
                            except Exception:
                                pass
                            break

            except Exception:
                pass  # governance may not be available

    def _participate_in_debate(self, proposal: object, pid: str, debated: set[str]) -> None:
        """Open debate, submit LLM-generated statement, compute consensus, advance phase."""
        title = getattr(proposal, "title", "")
        desc = getattr(proposal, "description", "")

        # Fetch or open a debate
        debate = self._http_json("GET", f"/governance/proposals/{pid}/debate")
        if not debate:
            return

        rounds = debate.get("rounds", [])
        current_phase = "OPENING"
        current_round_id = None

        if rounds:
            latest = rounds[-1]
            current_phase = latest.get("phase", "OPENING")
            current_round_id = latest.get("round_id")
        else:
            # No debate yet — open the first round
            result = self._http_json("POST", f"/governance/proposals/{pid}/debate", {
                "phase": "OPENING",
                "duration_hrs": 24,
            })
            if result:
                current_round_id = result.get("round_id")
                current_phase = result.get("phase", "OPENING")
                print(f"  [{self.name}] Opened debate on: {title[:50]}", flush=True)

        # Submit a statement if we have a round and debate is not in VOTING
        if current_round_id and current_phase != "VOTING":
            position, content = self._generate_debate_statement(title, desc, current_phase)
            stmt_result = self._http_json("POST", f"/governance/debate/{current_round_id}/statements", {
                "position": position,
                "content": content,
                "evidence_refs": [],
            })
            if stmt_result:
                print(
                    f"  [{self.name}] Debate statement ({position}): {content[:60]}...",
                    flush=True,
                )

        # Compute a consensus snapshot
        snap = self._http_json("POST", f"/governance/proposals/{pid}/consensus")
        if snap:
            quorum = snap.get("quorum_met", False)
            voters = snap.get("total_voters", 0)
            print(
                f"  [{self.name}] Consensus snapshot: {voters} voters, quorum={'YES' if quorum else 'NO'}",
                flush=True,
            )

        # Try to advance the phase if we've been in it long enough
        if current_phase in ("OPENING", "REBUTTAL", "CLOSING"):
            adv = self._http_json("POST", f"/governance/proposals/{pid}/advance")
            if adv:
                new_phase = adv.get("phase", "?")
                print(f"  [{self.name}] Advanced debate → {new_phase}", flush=True)

        debated.add(pid)

    def _evaluate_task_fit(self, task_tags: set[str]) -> float:
        """Score how well this agent's capabilities match a task. 0.0-1.0."""
        my_caps = set(self.capabilities)
        overlap = task_tags & my_caps
        if not overlap:
            return 0.0
        base = len(overlap) / max(len(task_tags), 1)
        return min(1.0, base + random.uniform(0.0, 0.05))

    def _marketplace_bid_and_execute(
        self, task_id: str, confidence: float, post: dict,
    ) -> None:
        """
        Timer-thread callback: submit bid → if we win → execute → submit result.

        Called after a confidence-proportional delay so the most qualified agent
        bids first.  Auto-accept on the platform assigns the task to the first
        qualified bidder; subsequent bids fail with "not open".
        """
        base = self.client._config.base_url.rstrip("/")
        token = self.client._token.access_token

        # ── 1. Submit bid ─────────────────────────────────────────────────
        try:
            bid_data = _json.dumps({
                "agent_did": self.agent.did,
                "confidence": round(confidence, 3),
                "bid_price": int(confidence * 80),
            }).encode()
            req = urllib.request.Request(
                f"{base}/tasks/{task_id}/bid",
                data=bid_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                _json.loads(r.read())  # bid accepted
        except _uerr.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            if "not open" in body.lower() or "already" in body.lower():
                print(f"  [{self.name}] Task already taken — skipping", flush=True)
            else:
                print(f"  [{self.name}] Bid failed ({exc.code}): {body[:120]}", flush=True)
            return
        except Exception as exc:
            print(f"  [{self.name}] Bid error: {exc}", flush=True)
            return

        title = post.get("title", "(no title)")
        tags = set(post.get("tags", []))
        my_caps = set(self.capabilities)

        print(f"  [{self.name}] Won task: {title!r}  (conf={confidence:.2f})", flush=True)

        # ── Phase 3: Try decomposition for complex cross-capability tasks ─
        if self._should_decompose(post):
            delegated = self._decompose_and_delegate(post, task_id)
            if delegated:
                # We still execute our part, but sub-tasks are delegated
                print(
                    f"  [{self.name}] Delegated cross-capability sub-tasks; "
                    f"executing own part",
                    flush=True,
                )

        # ── 2. Execute with LLM ──────────────────────────────────────────
        self._messages = []  # fresh context per task
        prompt = (
            f"You have been assigned a task on the AgentX platform.\n\n"
            f"Title: {title}\n"
            f"Content: {post.get('content', '')}\n"
            f"Tags: {sorted(tags)}\n\n"
            f"Provide a thorough, production-quality response."
        )
        try:
            result_text = self.think(prompt)
        except Exception as exc:
            print(f"  [{self.name}] LLM failed: {exc}", flush=True)
            return

        # ── 3. Submit result to marketplace (triggers escrow + trust) ─────
        try:
            result_data = _json.dumps({
                "agent_did": self.agent.did,
                "result_payload": {
                    "output": result_text[:2000],
                    "model": self.active_model,
                    "agent": self.name,
                },
            }).encode()
            req = urllib.request.Request(
                f"{base}/tasks/{task_id}/result",
                data=result_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                r.read()
            print(f"  [{self.name}] Marketplace result submitted", flush=True)
            # Phase 4: Record completion in persistent memory
            task_type = post.get("tags", ["unknown"])[0] if post.get("tags") else "unknown"
            self._record_task_completion(task_type)
        except Exception as exc:
            print(f"  [{self.name}] Result submission: {exc}", flush=True)

        # ── 4. Post UPDATE to feed (dashboard visibility) ─────────────────
        try:
            self.client.create_post(PostCreate(
                post_type="UPDATE",
                title=f"[{self.name}] Response: {title}",
                content=result_text[:2000],
                tags=list(tags & my_caps),
                metadata={
                    "progress_percent": 100,
                    "marketplace_task_id": task_id,
                },
            ))
            print(f"  [{self.name}] Feed update posted", flush=True)
        except Exception as exc:
            print(f"  [{self.name}] Feed post: {exc}", flush=True)

        # ── 5. Phase 2: Social reactions ───────────────────────────────────
        try:
            self._social_react_to_completion(title, task_id)
        except Exception:
            pass  # social layer is best-effort

    def _legacy_execute(self, post: dict, matching_tags: set) -> None:
        """Execute a non-marketplace task directly (backward compat)."""
        post_id = post.get("post_id", "")
        title = post.get("title", "(no title)")
        tags = set(post.get("tags", []))

        self._messages = []
        prompt = (
            f"You have been assigned a task on the AgentX platform.\n\n"
            f"Title: {title}\n"
            f"Content: {post.get('content', '')}\n"
            f"Tags: {sorted(tags)}\n\n"
            f"Provide a thorough, production-quality response."
        )
        try:
            result_text = self.think(prompt)
        except Exception as exc:
            print(f"  [{self.name}] LLM failed: {exc}", flush=True)
            return

        try:
            self.client.create_post(PostCreate(
                post_type="UPDATE",
                title=f"[{self.name}] Response: {title}",
                content=result_text[:2000],
                tags=list(matching_tags),
                metadata={
                    "progress_percent": 100,
                    "parent_post_id": post_id,
                },
            ))
            print(f"  [{self.name}] Feed update posted", flush=True)
        except Exception as exc:
            print(f"  [{self.name}] Feed post: {exc}", flush=True)

    # -- Event-handler pattern --------------------------------------------------

    def _make_event_handler(self):
        """
        Build the event-handler function for runtime.run().

        Marketplace flow (when post has marketplace_task_id in metadata):
          1. Calculate confidence from capability overlap
          2. Schedule a delayed bid (delay = (1 - conf) * MAX_BID_DELAY_SECS)
          3. Most-qualified agent bids first → auto-accept assigns them
          4. Winner executes with LLM → submits result → posts UPDATE

        Legacy flow (posts without marketplace_task_id):
          Direct execution with confidence threshold (≥0.5).
        """
        my_caps = set(self.capabilities)

        def handle(event: Event, memory: list[Event]) -> Optional[dict]:
            if event.type == "NEW_POST":
                post = event.data
                if post.get("post_type") != "TASK":
                    return None

                post_id = post.get("post_id", "")
                if post_id in self._processed_posts:
                    return None
                self._processed_posts.add(post_id)

                # Don't bid on own tasks (seeder may share DID)
                if post.get("author_did") == self.agent.did:
                    return None

                tags = set(post.get("tags", []))
                confidence = self._evaluate_task_fit(tags)
                if confidence < MIN_BID_CONFIDENCE:
                    return None

                title = post.get("title", "(no title)")
                metadata = post.get("metadata") or {}
                marketplace_id = metadata.get("marketplace_task_id")

                if marketplace_id:
                    # ── Marketplace: delayed bid (most qualified bids first) ──
                    delay = (1.0 - confidence) * MAX_BID_DELAY_SECS
                    print(
                        f"\n  [{self.name}] Task: {title!r}"
                        f"  conf={confidence:.2f}  bid in {delay:.1f}s",
                        flush=True,
                    )
                    threading.Timer(
                        delay,
                        self._marketplace_bid_and_execute,
                        args=(marketplace_id, confidence, post),
                    ).start()
                else:
                    # ── Legacy: direct execution with higher threshold ────────
                    if confidence >= 0.5:
                        print(
                            f"\n  [{self.name}] Task: {title!r}"
                            f"  conf={confidence:.2f} (legacy)",
                            flush=True,
                        )
                        threading.Thread(
                            target=self._legacy_execute,
                            args=(post, tags & my_caps),
                            daemon=True,
                        ).start()

                return None

            # Phase 2: React to peer UPDATE posts with follow-back
            if event.type == "NEW_POST":
                post = event.data
                author = post.get("author_did", "")
                if post.get("post_type") == "UPDATE" and author != self.agent.did:
                    # Ensure we follow active peers
                    try:
                        self.client.social.follow(author)
                    except Exception:
                        pass

            # Phase 2: React to TRUST_UPDATE by messaging the agent
            if event.type == "TRUST_UPDATE":
                agent_did = event.data.get("agent_did", "")
                new_score = event.data.get("trust_score", 0)
                if agent_did and agent_did != self.agent.did and new_score > 0.8:
                    try:
                        self.client.send_message(
                            agent_did,
                            f"Impressive trust score ({new_score:.2f})! "
                            f"— {self.name}",
                        )
                    except Exception:
                        pass

            # Silently ignore infrastructure events
            if event.type not in {"HEARTBEAT", "PONG", "CONNECTED", "SUBSCRIBED"}:
                pass  # could log: print(f"  [{self.name}] {event.type}")

            return None

        return handle

    # -- Contract-decorator pattern ---------------------------------------------

    def register_contract_handlers(self) -> None:
        """
        Register an async contract handler for each capability.
        Each handler calls the LLM with the task payload and returns the result.
        """
        import asyncio

        def _make_handler(capability: str):
            async def handler(data: dict) -> dict:
                print(f"\n  [{self.name}] Handling contract: {capability}")
                prompt = (
                    f"Capability: {capability}\n"
                    f"Task payload:\n{data}\n\n"
                    f"Provide a thorough, production-quality response."
                )
                # Run synchronous LLM call in executor to stay async-friendly
                loop = asyncio.get_event_loop()
                result_text = await loop.run_in_executor(None, self.think, prompt)
                return {
                    "output":     result_text,
                    "capability": capability,
                    "agent":      self.name,
                    "model":      self.active_model,
                    "backend":    "local" if self._is_local else "cloud",
                }
            handler.__name__ = f"handle_{capability}"
            return handler

        for cap in self.capabilities:
            self.agent.contract(cap)(_make_handler(cap))

        print(
            f"  [{self.name}] Registered contract handlers: "
            f"{self.agent.registered_capabilities()}"
        )

    # -- Phase 3: AgentBus inbox poller ----------------------------------------

    def _poll_agentbus(self) -> None:
        """Background thread: periodically check AgentBus inbox for delegation requests."""
        import time
        seen_ids: set[str] = set()
        while True:
            try:
                time.sleep(30)  # check every 30s
                messages = self.client.bus.receive(limit=10, acp_type="task_request")
                for msg in messages:
                    msg_id = str(msg.get("message_id", ""))
                    if msg_id in seen_ids:
                        continue
                    seen_ids.add(msg_id)
                    payload = msg.get("machine_payload") or {}
                    summary = msg.get("human_summary", "")
                    task_type = payload.get("task_type", "")
                    # Only react to delegations matching our capabilities
                    if task_type in self.capabilities:
                        print(
                            f"  [{self.name}] AgentBus: received delegation — {summary[:60]}",
                            flush=True,
                        )
                # Trim seen_ids to prevent unbounded growth
                if len(seen_ids) > 500:
                    seen_ids.clear()
            except Exception:
                pass  # AgentBus may not be available

    # -- Entry points -----------------------------------------------------------

    def start(
        self,
        mode:     str = "events",
        channels: Optional[list[str]] = None,
    ) -> None:
        """
        Start the agent loop. Blocks until Ctrl-C.

        Args:
            mode:     "events"    — WebSocket event-handler pattern
                      "contracts" — task polling / contract-decorator pattern
            channels: WebSocket channels to subscribe (events mode only).
                      Defaults to ["feed", "governance"].
        """
        self.register_or_load()

        self._ensure_wallet()

        # Phase 2: Social Intelligence — establish social graph and communities
        self._follow_peers()
        self._join_communities()

        # Phase 3: Start AgentBus inbox poller in background
        bus_thread = threading.Thread(target=self._poll_agentbus, daemon=True)
        bus_thread.start()

        # Phase 4: Load persistent memory and start governance thread
        self._load_memory()
        gov_thread = threading.Thread(target=self._governance_participation, daemon=True)
        gov_thread.start()

        print(f"\n  Starting {self.name} in {mode.upper()} mode")
        print(f"  Backend: {'local' if self._is_local else 'cloud'}  Model: {self.active_model}")
        print(f"  Capabilities: {self.capabilities}")
        if self._task_stats["completed"] > 0:
            print(f"  Memory: {self._task_stats['completed']} tasks completed, "
                  f"{self._task_stats['delegated']} delegated")
        print("  Press Ctrl-C to stop\n")

        try:
            if mode == "contracts":
                self.register_contract_handlers()
                self.runtime.run_contracts(
                    self.agent,
                    poll_interval = self.poll_interval,
                )
            else:
                handler  = self._make_event_handler()
                _channels = channels or ["feed", "governance"]
                self.runtime.run(handler, channels=_channels)

        except KeyboardInterrupt:
            print(f"\n  [{self.name}] Shutting down…")
        finally:
            try:
                self.client.disconnect()
            except Exception:
                pass
            print(f"  [{self.name}] Stopped.\n")
