"""
AgentX — Autonomous Orchestration Loop
═══════════════════════════════════════
Polls the message bus and routes QUERY/TASK messages to the target agent.
Agents respond autonomously — no human required in the loop.

Usage:
    from orchestrator.loop import OrchestrationLoop
    loop = OrchestrationLoop(agents={"MARCUS": marcus, "QUINN": quinn})
    loop.run(max_iterations=50)

Message handling:
    QUERY  → agent reads + responds with RESPONSE message
    TASK   → agent executes task + responds with RESPONSE
    Other  → logged but not acted on (ANNOUNCE, NOTIFY, etc.)
"""
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class OrchestrationLoop:
    """
    Event-driven orchestration loop.

    Polls the SQLite message bus every `poll_interval` seconds.
    For each QUERY or TASK message addressed to a registered agent,
    the agent reads the message and calls think() to produce a response,
    which is sent back to the originator as a RESPONSE message.

    Cost note: each handled message = 1 LLM call. Local agents are free.
    """

    def __init__(
        self,
        agents:        dict,          # {"ATLAS": atlas_instance, ...}
        poll_interval: float = 2.0,   # seconds between bus polls
        max_tokens:    int   = 4000,  # per-response token cap (keep lean)
        verbose:       bool  = True,
        start_id:      int   = 0,     # skip messages with id <= this value
    ):
        self.agents        = agents
        self.poll_interval = poll_interval
        self.max_tokens    = max_tokens
        self.verbose       = verbose
        self._last_id      = start_id  # highest message id seen so far
        self._handled      = set()     # ids we've already responded to
        self._stats        = {
            "messages_seen":    0,
            "messages_handled": 0,
            "responses_sent":   0,
            "errors":           0,
        }
        # Per-agent last_id — prevents a high-ID agent from masking
        # lower-ID messages addressed to other agents in the same cycle.
        self._last_id_per_agent: dict[str, int] = {name: start_id for name in agents}

        # Ledger path for loop events
        from config import LEDGER
        self._ledger = LEDGER / "loop_log.jsonl"

    # ── Logging ────────────────────────────────────────────────────────────────

    def _log(self, event: str, detail: str) -> None:
        entry = {
            "ts":    datetime.now(timezone.utc).isoformat(),
            "event": event,
            "detail": detail,
        }
        with open(self._ledger, "a") as f:
            f.write(json.dumps(entry) + "\n")
        if self.verbose:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] 🔄 LOOP  {event:<18} {detail[:70]}")

    # ── Core routing ───────────────────────────────────────────────────────────

    def _handle_message(self, msg: dict) -> bool:
        """
        Route a single QUERY or TASK message to its target agent.
        Returns True if handled, False if skipped.
        """
        msg_id   = msg["id"]
        from_ag  = msg["from_ag"]
        to_ag    = msg["to_ag"]
        msg_type = msg["msg_type"]
        content  = msg["content"]

        # Only handle QUERY and TASK; skip ANNOUNCE, NOTIFY, etc.
        if msg_type not in ("QUERY", "TASK"):
            return False

        # Only handle messages addressed to a registered agent
        if to_ag not in self.agents:
            return False

        # Don't handle the same message twice
        if msg_id in self._handled:
            return False

        agent = self.agents[to_ag]
        self._log("ROUTING", f"msg#{msg_id}  {from_ag}→{to_ag}  [{msg_type}]  {content[:50]}")

        try:
            # Build a concise prompt so the agent stays on-task
            prompt = (
                f"[INCOMING {msg_type} from {from_ag}]\n\n"
                f"{content}\n\n"
                f"Reply concisely. If this is a QUERY, answer it directly. "
                f"If this is a TASK, describe what you would change or implement."
            )

            response = agent.think(prompt, max_tokens=self.max_tokens)

            # Send response back via message bus
            if agent.bus:
                agent.bus.send(
                    to_ag,
                    from_ag,
                    "RESPONSE",
                    response[:1000],          # keep bus messages readable
                    thread_id=str(msg_id),    # link to original message
                )
                self._stats["responses_sent"] += 1
                self._log("RESPONDED", f"msg#{msg_id}  {to_ag}→{from_ag}  {len(response)} chars")

            self._handled.add(msg_id)
            self._stats["messages_handled"] += 1
            return True

        except Exception as e:
            self._log("ERROR", f"msg#{msg_id}  {to_ag}  {e}")
            self._stats["errors"] += 1
            return False

    # ── Main loop ──────────────────────────────────────────────────────────────

    def run(
        self,
        max_iterations: Optional[int] = None,
        stop_when_idle: bool          = True,
        idle_threshold: int           = 3,     # consecutive empty polls before stopping
    ) -> dict:
        """
        Start the event loop.

        Args:
            max_iterations:  Stop after this many poll cycles (None = run forever).
            stop_when_idle:  Stop automatically when message bus has been empty
                             for `idle_threshold` consecutive polls.
            idle_threshold:  How many empty polls before declaring idle.

        Returns:
            stats dict with messages seen/handled/responded/errors.
        """
        from agents.message_bus import BUS

        self._log("START", f"Watching {list(self.agents.keys())}  poll={self.poll_interval}s")
        print(f"\n{'═'*68}")
        print(f"  🔄  ORCHESTRATION LOOP STARTED")
        print(f"  Agents : {', '.join(self.agents.keys())}")
        print(f"  Poll   : every {self.poll_interval}s")
        if max_iterations:
            print(f"  Limit  : {max_iterations} iterations")
        if stop_when_idle:
            print(f"  Idle   : stops after {idle_threshold} empty polls")
        print(f"{'═'*68}\n")

        iteration   = 0
        idle_count  = 0

        try:
            while True:
                if max_iterations and iteration >= max_iterations:
                    self._log("STOP", f"max_iterations={max_iterations} reached")
                    break

                # Poll all registered agents' inboxes
                new_messages_this_cycle = 0

                for agent_name in self.agents:
                    agent_last = self._last_id_per_agent.get(agent_name, 0)
                    msgs = BUS.get_for_agent(agent_name, since_id=agent_last)
                    for msg in msgs:
                        self._stats["messages_seen"] += 1
                        self._last_id_per_agent[agent_name] = max(agent_last, msg["id"])
                        self._last_id = max(self._last_id, msg["id"])
                        handled = self._handle_message(msg)
                        if handled:
                            new_messages_this_cycle += 1

                # Idle detection
                if new_messages_this_cycle == 0:
                    idle_count += 1
                    if self.verbose and idle_count == 1:
                        print(f"  💤  No new messages — waiting...")
                    if stop_when_idle and idle_count >= idle_threshold:
                        self._log("IDLE", f"No messages for {idle_threshold} polls — stopping")
                        break
                else:
                    idle_count = 0

                time.sleep(self.poll_interval)
                iteration += 1

        except KeyboardInterrupt:
            self._log("STOP", "KeyboardInterrupt — loop stopped by user")
            print("\n\n  ⏹  Loop stopped by user (Ctrl+C)\n")

        self._print_stats()
        return self._stats

    # ── Stats ──────────────────────────────────────────────────────────────────

    def _print_stats(self) -> None:
        s = self._stats
        print(f"\n{'─'*68}")
        print(f"  🔄  LOOP COMPLETE")
        print(f"  Messages seen    : {s['messages_seen']}")
        print(f"  Messages handled : {s['messages_handled']}")
        print(f"  Responses sent   : {s['responses_sent']}")
        print(f"  Errors           : {s['errors']}")
        print(f"{'─'*68}\n")
