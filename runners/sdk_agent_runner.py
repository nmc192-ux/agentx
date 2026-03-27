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

        print(f"\n  Starting {self.name} in {mode.upper()} mode")
        print(f"  Backend: {'local' if self._is_local else 'cloud'}  Model: {self.active_model}")
        print(f"  Capabilities: {self.capabilities}")
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
