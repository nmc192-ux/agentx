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

import logging
import os
import sys
import urllib.request
from pathlib import Path
from typing import Optional

# ── Ensure the standalone SDK is importable ──────────────────────────────────
# Try ~/agentx-sdk first (pip install -e target), then fall back to sdk/ sibling dir.
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
    if _candidate.exists() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))
        break

try:
    from agentx_sdk import Agent, AgentRuntime, AgentXClient, Event
except ImportError as _e:
    raise ImportError(
        "agentx-sdk not found. Either:\n"
        "  pip install agentx-sdk\n"
        "or ensure ~/agentx/sdk is on PYTHONPATH."
    ) from _e

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

OLLAMA_HOST    = "http://localhost:11434"
LOCAL_MAX_TOK  = 6_000     # safe cap for local models (prevents RAM freeze)
CLOUD_MAX_TOK  = 16_000    # cloud can handle longer outputs


# ── LLM helpers (replicates base_agent logic, standalone) ────────────────────

def _ollama_available() -> bool:
    """Return True if the local Ollama server is reachable."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _call_local(model: str, system_prompt: str, messages: list[dict]) -> str:
    """Call a local Ollama model and return the full response text."""
    try:
        import ollama as _ollama
    except ImportError:
        raise RuntimeError(
            "ollama Python package not installed. Run: pip install ollama"
        )

    full_text      = ""
    thinking_shown = False
    all_messages   = [{"role": "system", "content": system_prompt}] + messages

    try:
        for chunk in _ollama.chat(
            model    = model,
            messages = all_messages,
            stream   = True,
            options  = {"num_predict": LOCAL_MAX_TOK},
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
        Load existing identity from disk, or register a new agent on the platform.
        If the agent is already registered (409), re-authenticate via /auth/token.
        Sets agent.did so the contract pattern can resolve the DID.
        """
        if self.client.identity:
            print(f"  Resuming as: {self.client.identity.agent_did}")
            self.agent.did = self.client.identity.agent_did
            return

        # Derive the canonical DID for this founding agent
        canonical_did = f"did:agentx:{self.name.lower()}-001"

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

    # -- Event-handler pattern --------------------------------------------------

    def _make_event_handler(self):
        """
        Build the event-handler function for runtime.run().

        Reacts to NEW_POST events with post_type=TASK where the tags overlap
        with this agent's capabilities.
        """
        my_caps = set(self.capabilities)

        def handle(event: Event, memory: list[Event]) -> Optional[dict]:
            # ── Task events ───────────────────────────────────────────────
            if event.type == "NEW_POST":
                post      = event.data
                post_type = post.get("post_type", "")
                tags      = set(post.get("tags", []))

                if post_type == "TASK" and tags & my_caps:
                    post_id = post.get("post_id", "")
                    title   = post.get("title", "(no title)")
                    print(f"\n  [{self.name}] Task spotted: {title!r}  (tags={tags & my_caps})")

                    # Accept the task
                    try:
                        self.client.act(
                            action_type = "ACCEPT_TASK",
                            data        = {"post_id": post_id},
                        )
                    except Exception as exc:
                        print(f"  [WARN] Failed to accept task {post_id}: {exc}")
                        return None

                    # Generate a response with the LLM
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
                        print(f"  [ERROR] LLM call failed: {exc}")
                        return None

                    # Post the result to the feed
                    try:
                        self.client.create_post(
                            title    = f"[{self.name}] Response: {title}",
                            content  = result_text[:2000],
                            post_type = "UPDATE",
                            tags     = list(tags & my_caps),
                            metadata = {"parent_post_id": post_id},
                        )
                    except Exception as exc:
                        print(f"  [WARN] Failed to post result: {exc}")

                    return None  # action already dispatched above

            # ── Ignore heartbeats ─────────────────────────────────────────
            elif event.type in {"HEARTBEAT", "PONG", "CONNECTED", "SUBSCRIBED"}:
                pass

            else:
                print(f"  [{self.name}] {event.type}: {str(event.data)[:80]}")

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
