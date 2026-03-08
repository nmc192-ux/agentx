"""
AgentX — BaseAgent
The shared foundation for all 8 founding agents.

Each agent is an autonomous entity with:
  - Dual backend: Ollama (local, free) by default, Claude (cloud) for escalations
  - Private workspace + shared artifact space
  - Immutable audit ledger
  - Inter-agent message bus
  - CEO escalation channel
"""
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Session-level cost accumulator (cloud spend only) ────────────────────────
_session_input_tokens:  int   = 0
_session_output_tokens: int   = 0
_session_cost_usd:      float = 0.0


class BaseAgent:
    """
    Base class for every AgentX founding agent.

    Backend selection (in priority order):
      1. Explicit --model flag on runner  → use that model literally
      2. Explicit --backend {local|cloud} → force that tier
      3. config.USE_LOCAL_BY_DEFAULT      → auto-select local or cloud

    Local (Ollama) calls cost $0. Cloud (Anthropic) calls are tracked and billed.
    """

    def __init__(
        self,
        name:          str,
        emoji:         str,
        role:          str,
        system_prompt: str,
        model:         str = "",   # empty → auto from config
        backend:       str = "auto",  # "auto" | "local" | "cloud"
    ):
        self.name           = name
        self.emoji          = emoji
        self.role           = role
        self._system_prompt = system_prompt
        self.messages: list = []

        from config import (
            LOCAL_MODELS, CLOUD_MODELS, DEFAULT_MODEL,
            SUPPORTS_THINKING, COST_TABLE, USE_LOCAL_BY_DEFAULT,
            LOCAL_GENERAL, HAIKU,
        )

        # ── Resolve model & backend ────────────────────────────────────────
        if model and model.startswith("claude-"):
            # Explicit cloud model passed
            self._is_local    = False
            self.model        = model
        elif model:
            # Non-Claude model name → treat as local/Ollama
            self._is_local    = True
            self.model        = model
        elif backend == "cloud":
            self._is_local    = False
            self.model        = CLOUD_MODELS.get(name, DEFAULT_MODEL)
        elif backend == "local":
            self._is_local    = True
            self.model        = LOCAL_MODELS.get(name, LOCAL_GENERAL)
        else:
            # "auto" — use config default
            if USE_LOCAL_BY_DEFAULT:
                self._is_local = True
                self.model     = LOCAL_MODELS.get(name, LOCAL_GENERAL)
            else:
                self._is_local = False
                self.model     = CLOUD_MODELS.get(name, DEFAULT_MODEL)

        # ── Verify Ollama is reachable; fall back to cloud if not ──────────
        if self._is_local and not self._ollama_available():
            print(
                f"\n  ⚠️  Ollama not reachable at localhost:11434 — "
                f"falling back to cloud for {name}.\n"
                f"     Start Ollama with: ollama serve\n"
            )
            self._is_local = False
            self.model     = CLOUD_MODELS.get(name, DEFAULT_MODEL)

        # Cloud model to use for escalations (always set, even if running locally)
        self._cloud_model = CLOUD_MODELS.get(name, HAIKU)

        # ── Thinking support (cloud-only feature, currently disabled) ──────
        self._supports_think = (not self._is_local) and (self.model in SUPPORTS_THINKING)

        # ── Cost table ────────────────────────────────────────────────────
        self._cost_table = COST_TABLE.get(
            self.model,
            {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
        )

        # ── Anthropic client (lazy — only created when needed) ────────────
        self._anthropic = None

        # ── Workspace — each agent gets a private directory ───────────────
        from config import WORKSPACE, SHARED, LEDGER
        self.workspace   = WORKSPACE / name.lower()
        self.shared      = SHARED
        self.ledger_path = LEDGER / "audit_log.jsonl"
        self.workspace.mkdir(parents=True, exist_ok=True)

        # ── Per-instance cost counters ────────────────────────────────────
        self.total_input_tokens:  int   = 0
        self.total_output_tokens: int   = 0
        self.total_cost_usd:      float = 0.0

        # ── Message bus ───────────────────────────────────────────────────
        try:
            from agents.message_bus import BUS
            self.bus = BUS
        except Exception:
            self.bus = None

        # ── Platform bridge (AgentX social network posting) ───────────────
        try:
            from agents.platform_bridge import PlatformBridge
            self.bridge: Optional[PlatformBridge] = PlatformBridge.for_agent(name)
        except Exception:
            self.bridge = None

        # ── Backward-compat alias ─────────────────────────────────────────
        # Some older code references self.client for the Anthropic client.
        # We keep it as a property that auto-creates on first access.

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def client(self):
        """Anthropic client (lazy-initialized). Use for cloud calls."""
        if self._anthropic is None:
            import anthropic
            self._anthropic = anthropic.Anthropic()
        return self._anthropic

    @client.setter
    def client(self, value):
        self._anthropic = value

    # ── Ollama availability check ──────────────────────────────────────────────

    @staticmethod
    def _ollama_available() -> bool:
        """Ping Ollama API. Returns True if reachable."""
        try:
            with urllib.request.urlopen(
                "http://localhost:11434/api/tags", timeout=2
            ) as r:
                return r.status == 200
        except Exception:
            return False

    # ── Cost helpers ────────────────────────────────────────────────────────────

    def _calc_cost(self, usage) -> float:
        ct     = self._cost_table
        inp    = getattr(usage, "input_tokens",               0)
        out    = getattr(usage, "output_tokens",              0)
        c_read = getattr(usage, "cache_read_input_tokens",    0)
        c_writ = getattr(usage, "cache_creation_input_tokens", 0)
        billed = max(0, inp - c_read - c_writ)
        return (
            billed * ct["input"]        / 1_000_000 +
            c_writ * ct["cache_write"]  / 1_000_000 +
            c_read * ct["cache_read"]   / 1_000_000 +
            out    * ct["output"]       / 1_000_000
        )

    def _update_cloud_counters(self, usage) -> float:
        global _session_input_tokens, _session_output_tokens, _session_cost_usd
        inp  = getattr(usage, "input_tokens",  0)
        out  = getattr(usage, "output_tokens", 0)
        cost = self._calc_cost(usage)
        self.total_input_tokens  += inp
        self.total_output_tokens += out
        self.total_cost_usd      += cost
        _session_input_tokens    += inp
        _session_output_tokens   += out
        _session_cost_usd        += cost
        return cost

    # ── Audit ledger ────────────────────────────────────────────────────────────

    def _log(self, entry_type: str, body: str, ref: str = "") -> None:
        """Append an immutable entry to the audit ledger (JSONL)."""
        entry = {
            "ts":    datetime.now(timezone.utc).isoformat(),
            "agent": self.name,
            "type":  entry_type,
            "body":  body,
            "model": self.model,
            "local": self._is_local,
        }
        if ref:
            entry["ref"] = ref
        with open(self.ledger_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{ts}] ● LEDGER  {entry_type:<14} {self.name:<8}  {body[:60]}")

    # ── Core LLM — local (Ollama) ───────────────────────────────────────────────

    def _think_local(self, max_tokens: int) -> str:
        """
        Call Ollama local model with full streaming output.

        Handles deepseek-r1 style 'thinking' tokens (separate field in newer Ollama):
          chunk['message']['thinking'] → reasoning (shown dimmed, not stored)
          chunk['message']['content']  → answer    (printed bold, stored in history)

        Enforces LOCAL_MAX_TOKENS cap to prevent RAM overflow / terminal freeze.
        """
        import ollama as _ollama
        from config import LOCAL_MAX_TOKENS

        # Cap output tokens for local models — prevents memory overflow on large models
        safe_tokens = min(max_tokens, LOCAL_MAX_TOKENS)
        if safe_tokens < max_tokens:
            print(f"\n  ℹ️  Local cap: {max_tokens} → {safe_tokens} tokens (prevents freeze)\n")

        # Build messages: system prompt first, then conversation history
        messages = [{"role": "system", "content": self._system_prompt}] + self.messages

        full_text      = ""
        thinking_shown = False   # track whether we've printed the thinking header

        try:
            for chunk in _ollama.chat(
                model    = self.model,
                messages = messages,
                stream   = True,
                options  = {"num_predict": safe_tokens},
            ):
                # chunk['message'] is a Message object (not dict) — use getattr
                msg = chunk.get("message") if isinstance(chunk, dict) else chunk.message

                # ── Thinking tokens (deepseek-r1 / reasoning models) ───────
                # Ollama exposes thinking in a separate .thinking attribute.
                # We show them dimmed so the user can watch the model reason,
                # but we DON'T include them in full_text (ephemeral reasoning).
                thinking_token = getattr(msg, "thinking", None) or ""
                if thinking_token:
                    if not thinking_shown:
                        print("\n\033[2m💭 [Thinking...]\033[0m\n\033[2m", end="", flush=True)
                        thinking_shown = True
                    print(thinking_token, end="", flush=True)
                    continue

                # ── Close thinking block if it was open ────────────────────
                if thinking_shown:
                    print("\033[0m\n\n", end="", flush=True)
                    thinking_shown = False

                # ── Regular response content ───────────────────────────────
                content = getattr(msg, "content", None) or ""
                if content:
                    print(content, end="", flush=True)
                    full_text += content

        except _ollama.ResponseError as e:
            # Model not pulled yet — give a helpful message and fall back
            if "not found" in str(e).lower() or "pull" in str(e).lower():
                print(
                    f"\n\n  ⚠️  Model '{self.model}' not found in Ollama.\n"
                    f"  Run: ollama pull {self.model}\n"
                    f"  Falling back to cloud: {self._cloud_model}\n"
                )
            else:
                print(f"\n  ⚠️  Ollama error: {e}\n  Falling back to cloud.\n")
            return self._fallback_to_cloud(max_tokens)

        except Exception as e:
            print(f"\n  ⚠️  Ollama call failed: {e}\n  Falling back to cloud.\n")
            return self._fallback_to_cloud(max_tokens)

        print(f"\n\n{'─' * 68}")
        print(
            f"  🟢 LOCAL  ${0:.4f} (free)  │  "
            f"model={self.model}  │  "
            f"session_cloud=${_session_cost_usd:.4f}"
        )
        print(f"{'─' * 68}\n")

        self.messages.append({"role": "assistant", "content": full_text})
        self._log("TASK_DONE", f"{len(full_text):,} chars  |  $0.0000 (local)  |  model={self.model}")
        return full_text

    def _fallback_to_cloud(self, max_tokens: int) -> str:
        """Temporarily switch to cloud and retry. Restores local after."""
        was_local    = self._is_local
        was_model    = self.model
        was_ct       = self._cost_table

        from config import COST_TABLE
        self._is_local   = False
        self.model       = self._cloud_model
        self._cost_table = COST_TABLE.get(self._cloud_model, was_ct)

        result = self._think_cloud(max_tokens, show_thinking=False)

        self._is_local   = was_local
        self.model       = was_model
        self._cost_table = was_ct
        return result

    # ── Core LLM — cloud (Anthropic) ───────────────────────────────────────────

    def _think_cloud(self, max_tokens: int, show_thinking: bool = False) -> str:
        """Call Anthropic Claude with streaming and prompt caching."""
        import anthropic as _ant

        stream_kwargs = dict(
            model      = self.model,
            max_tokens = max_tokens,
            system     = [
                {
                    "type": "text",
                    "text": self._system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages   = self.messages,
        )
        if self._supports_think:
            stream_kwargs["thinking"] = {"type": "adaptive"}

        full_text = ""
        try:
            with self.client.messages.stream(**stream_kwargs) as stream:
                for event in stream:
                    if event.type == "content_block_start":
                        if getattr(event.content_block, "type", "") == "thinking" and show_thinking:
                            print("\n💭 [Thinking]\n", end="", flush=True)
                    elif event.type == "content_block_delta":
                        dt = getattr(event.delta, "type", "")
                        if dt == "thinking_delta" and show_thinking:
                            print(event.delta.thinking, end="", flush=True)
                        elif dt == "text_delta":
                            print(event.delta.text, end="", flush=True)
                            full_text += event.delta.text
                final = stream.get_final_message()

        except _ant.APIError as e:
            self._log("ERROR", f"Cloud API error: {e}")
            raise

        usage      = final.usage
        call_cost  = self._update_cloud_counters(usage)
        inp        = getattr(usage, "input_tokens",                0)
        out        = getattr(usage, "output_tokens",               0)
        c_read     = getattr(usage, "cache_read_input_tokens",     0)
        c_writ     = getattr(usage, "cache_creation_input_tokens", 0)

        print(f"\n\n{'─' * 68}")
        print(
            f"  ☁️  CLOUD  ${call_cost:.4f}  │  "
            f"in={inp:,}  out={out:,}  cache_r={c_read:,}  cache_w={c_writ:,}  │  "
            f"session=${_session_cost_usd:.4f}"
        )
        print(f"{'─' * 68}\n")

        self.messages.append({"role": "assistant", "content": full_text})
        self._log(
            "TASK_DONE",
            f"{len(full_text):,} chars  |  ${call_cost:.4f}  |  "
            f"in={inp} out={out} cr={c_read} cw={c_writ}",
        )
        return full_text

    # ── Public think() — dispatches to local or cloud ──────────────────────────

    def think(
        self,
        user_message:  str,
        max_tokens:    int  = 16000,
        show_thinking: bool = False,
    ) -> str:
        """
        Send a message to this agent and get a streamed response.
        Routes to local (Ollama) or cloud (Anthropic) based on agent config.
        """
        self.messages.append({"role": "user", "content": user_message})

        backend_tag = f"🟢 local:{self.model}" if self._is_local else f"☁️  cloud:{self.model}"
        bar   = "═" * 68
        label = f" {self.emoji}  {self.name}  ·  {self.role}  ·  {backend_tag} "
        print(f"\n{bar}")
        print(f"{label:^68}")
        print(f"{bar}\n")

        self._log("TASK_START", user_message[:100])

        if self._is_local:
            return self._think_local(max_tokens)
        else:
            return self._think_cloud(max_tokens, show_thinking)

    # ── Escalation ─────────────────────────────────────────────────────────────

    def escalate(
        self,
        reason:     str,
        prompt:     str     = "",
        max_tokens: int     = 8000,
        notify_ceo: bool    = True,
    ) -> str:
        """
        Force this call to the cloud escalation model, regardless of default backend.

        Use for critical decisions, security reviews, or when local output is insufficient.
        Automatically notifies CEO via message bus if notify_ceo=True.

        Example:
            response = self.escalate(
                reason="Critical security finding requires deep analysis",
                prompt="Analyze this auth bypass: ...",
            )
        """
        self._log("ESCALATION", f"Escalating to cloud [{self._cloud_model}]: {reason}")

        if notify_ceo and self.bus:
            self.bus.escalate_to_ceo(
                self.name,
                reason,
                prompt[:200] if prompt else "",
            )

        # Temporarily switch to cloud
        was_local    = self._is_local
        was_model    = self.model
        was_ct       = self._cost_table
        was_think    = self._supports_think

        from config import COST_TABLE, SUPPORTS_THINKING
        self._is_local   = False
        self.model       = self._cloud_model
        self._cost_table = COST_TABLE.get(self._cloud_model, was_ct)
        self._supports_think = self._cloud_model in SUPPORTS_THINKING

        if prompt:
            result = self.think(prompt, max_tokens=max_tokens)
        else:
            # Re-run the last user message with cloud
            result = self._think_cloud(max_tokens)

        # Restore original backend
        self._is_local       = was_local
        self.model           = was_model
        self._cost_table     = was_ct
        self._supports_think = was_think
        return result

    # ── Message bus helpers ─────────────────────────────────────────────────────

    def send_message(
        self,
        to_agent:  str,
        msg_type:  str,
        content:   str,
        priority:  int = 0,
        thread_id: Optional[str] = None,
    ) -> Optional[int]:
        """Send a direct message to another agent via the message bus."""
        if self.bus:
            return self.bus.send(self.name, to_agent, msg_type, content,
                                 thread_id=thread_id, priority=priority)
        return None

    def broadcast(self, msg_type: str, content: str, priority: int = 0) -> Optional[int]:
        """Broadcast a message to all agents."""
        if self.bus:
            return self.bus.broadcast(self.name, msg_type, content, priority=priority)
        return None

    def escalate_to_ceo(self, reason: str, details: str = "") -> Optional[int]:
        """Send an urgent CEO-level escalation (priority 2)."""
        if self.bus:
            return self.bus.escalate_to_ceo(self.name, reason, details)
        return None

    def get_messages(self, since_id: int = 0) -> list[dict]:
        """Retrieve messages addressed to this agent."""
        if self.bus:
            return self.bus.get_for_agent(self.name, since_id=since_id)
        return []

    # ── Artifact helpers ────────────────────────────────────────────────────────

    def save(self, filename: str, content: str, description: str = "") -> Path:
        """Save an artifact to this agent's private workspace."""
        filepath = self.workspace / filename
        filepath.write_text(content, encoding="utf-8")
        ref = f"workspace/{self.name.lower()}/{filename}"
        self._log("ARTIFACT", description or filename, ref=ref)
        print(f"✓ Saved   → {ref}")
        return filepath

    def publish(self, filename: str, content: str, description: str = "") -> Path:
        """Publish an artifact to the shared workspace (visible to ALL agents)."""
        filepath = self.shared / filename
        filepath.write_text(content, encoding="utf-8")
        ref = f"workspace/shared/{filename}"
        self._log("PUBLISHED", description or filename, ref=ref)
        print(f"✓ Shared  → {ref}")
        # Notify all agents via message bus
        if self.bus:
            self.bus.broadcast(self.name, "ANNOUNCE",
                               f"Published: {filename} — {description or ''}")
        # Post to platform feed (if bridge is configured)
        if self.bridge:
            self.bridge.post_artifact(
                filename = filename,
                summary  = description or f"Published {filename} to shared workspace",
            )
        return filepath

    def read_shared(self, filename: str) -> Optional[str]:
        """Read an artifact from the shared workspace."""
        filepath = self.shared / filename
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        return None

    # ── Platform posting helpers ─────────────────────────────────────────────────

    def post_to_platform(
        self,
        content:  str,
        title:    Optional[str] = None,
        tags:     list = (),
        urgency:  str = "MEDIUM",
        is_request: bool = False,
    ) -> Optional[dict]:
        """
        Post an update or request to the live AgentX social feed.

        Call this from your runner script after think() to share key results
        publicly. Silently no-ops if PLATFORM_POSTING is not enabled or no JWT.

        Example:
            response = self.think("Analyse the auth module security…")
            self.post_to_platform(
                content=response[:280],
                title="🛡️ Security analysis complete",
                tags=["security", "auth"],
            )
        """
        if not self.bridge:
            return None
        if is_request:
            return self.bridge.post_request(
                title   = title or f"{self.name}: needs help",
                content = content,
                urgency = urgency,
                tags    = list(tags),
            )
        return self.bridge.post_update(
            content = content,
            title   = title,
            tags    = list(tags),
        )

    # ── Session management ──────────────────────────────────────────────────────

    def reset_session(self) -> None:
        """Clear conversation history."""
        self.messages = []
        self._log("SESSION_RESET", "Conversation history cleared")

    def cost_report(self) -> str:
        """Print a cost summary for this agent instance."""
        backend = "local (free)" if self._is_local else f"cloud ({self.model})"
        lines = [
            f"\n  💰 {self.name} Cost Report",
            f"  {'─' * 40}",
            f"  Backend        : {backend}",
            f"  Model          : {self.model}",
            f"  Input tokens   : {self.total_input_tokens:,}",
            f"  Output tokens  : {self.total_output_tokens:,}",
            f"  Total cost     : ${self.total_cost_usd:.4f}",
        ]
        report = "\n".join(lines)
        print(report)
        return report

    def __repr__(self) -> str:
        backend = "local" if self._is_local else "cloud"
        return (
            f"<{self.name} ({self.role}) "
            f"backend={backend} model={self.model} "
            f"cost=${self.total_cost_usd:.4f}>"
        )
