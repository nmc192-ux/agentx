"""
AgentX — CEO Dashboard (Human Orchestrator)
════════════════════════════════════════════
The CEO is the human operator. This module provides a rich dashboard
for monitoring all 8 founding agents, their workspace artifacts,
the audit ledger, and the overall AgentX build progress.

The CEO does NOT instruct agents — agents are autonomous.
The CEO observes, reviews artifacts, and unlocks phase transitions.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class CEO:
    """
    Human CEO interface.
    Reads agent workspaces, monitors the audit ledger, and displays
    real-time build progress across all phases.
    """

    def __init__(self):
        from config import WORKSPACE, SHARED, LEDGER, ROOT
        self.workspace = WORKSPACE
        self.shared    = SHARED
        self.ledger    = LEDGER / "audit_log.jsonl"
        self.root      = ROOT

        self.agents = [
            ("ATLAS",  "🏛️",  "Chief Architect"),
            ("BRUNO",  "⚙️",  "Infrastructure Lead"),
            ("DARIA",  "🎨",  "UX/Frontend Architect"),
            ("QUINN",  "🔬",  "Quality & Testing Lead"),
            ("GIA",    "🌱",  "Growth & Community Lead"),
            ("MARCUS", "🛡️",  "Security & Compliance Lead"),
            ("THEA",   "📊",  "Data & Analytics Lead"),
            ("NOVA",   "🤖",  "AI/ML Innovation Lead"),
        ]

        # Phase 1 expected artifacts (from ATLAS)
        self.phase1_artifacts = [
            "agent_identity_schema_v3.json",
            "post_synthesis_schema.json",
            "capability_registry_spec.json",
            "agentx_db_schema.sql",
            "agentx_api_v1.yaml",
            "three_token_architecture.md",
            "protocol_layers.md",
        ]

    # ── Display Helpers ──────────────────────────────────────────────────────

    def _w(self, n: int = 72) -> str:
        return "═" * n

    def _sep(self, n: int = 72) -> str:
        return "─" * n

    def _ts(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # ── Dashboard ───────────────────────────────────────────────────────────

    def dashboard(self) -> None:
        """
        Print the full CEO dashboard:
        - Agent roster + workspace status
        - Shared workspace (published artifacts)
        - Recent audit log entries
        - Phase 1 progress
        """
        print(f"\n{'╔' + self._w() + '╗'}")
        print("║" + "  👔  AGENTX CEO DASHBOARD  ".center(72) + "║")
        print("║" + f"  {self._ts()}  ".center(72) + "║")
        print(f"{'╠' + self._w() + '╣'}")
        print("║" + "  Build Status: PHASE 1 — Foundation Schema  ".ljust(72) + "║")
        print(f"{'╚' + self._w() + '╝'}\n")

        self._show_agents()
        self._show_phase1_progress()
        self._show_shared_workspace()
        self._show_audit_tail(n=10)

    # ── Agent Roster ────────────────────────────────────────────────────────

    def _show_agents(self) -> None:
        print(f"┌{self._sep()}┐")
        print(f"│  {'FOUNDING AGENTS':^70}  │")
        print(f"├{self._sep()}┤")
        header = f"  {'Agent':<10} {'Emoji':<6} {'Role':<30} {'Workspace':<22}"
        print(f"│{header}│")
        print(f"├{self._sep()}┤")

        for name, emoji, role in self.agents:
            ws_path  = self.workspace / name.lower()
            if ws_path.exists():
                files    = list(ws_path.iterdir())
                ws_info  = f"{len(files)} file(s)"
            else:
                ws_info  = "not started"
            line = f"  {name:<10} {emoji:<6} {role:<30} {ws_info:<22}"
            print(f"│{line}│")

        print(f"└{self._sep()}┘\n")

    # ── Phase 1 Progress ────────────────────────────────────────────────────

    def _show_phase1_progress(self) -> None:
        print(f"┌{self._sep()}┐")
        print(f"│  {'PHASE 1 PROGRESS — ATLAS Deliverables':^70}  │")
        print(f"├{self._sep()}┤")

        done = 0
        for artifact in self.phase1_artifacts:
            path    = self.shared / artifact
            exists  = path.exists()
            if exists:
                done  += 1
                size   = path.stat().st_size
                status = f"✅  {size:>8,} bytes"
            else:
                status = "⏳  pending"
            line = f"  {artifact:<44}  {status}"
            print(f"│{line:<72}│")

        pct  = int(100 * done / len(self.phase1_artifacts))
        bar  = "█" * (done * 4) + "░" * ((len(self.phase1_artifacts) - done) * 4)
        print(f"├{self._sep()}┤")
        print(f"│  Progress: [{bar}] {done}/{len(self.phase1_artifacts)} ({pct}%)  ".ljust(73) + "│")
        print(f"└{self._sep()}┘\n")

    # ── Shared Workspace ────────────────────────────────────────────────────

    def _show_shared_workspace(self) -> None:
        print(f"┌{self._sep()}┐")
        print(f"│  {'SHARED WORKSPACE  (workspace/shared/)':^70}  │")
        print(f"├{self._sep()}┤")

        if self.shared.exists():
            files = sorted(self.shared.iterdir())
            if files:
                for f in files:
                    size = f.stat().st_size
                    mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M")
                    line = f"  {f.name:<44}  {size:>9,} B  {mtime}"
                    print(f"│{line:<72}│")
            else:
                print(f"│  {'(empty — ATLAS has not published yet)':^70}  │")
        else:
            print(f"│  {'(shared workspace not created yet)':^70}  │")

        print(f"└{self._sep()}┘\n")

    # ── Audit Log Tail ───────────────────────────────────────────────────────

    def _show_audit_tail(self, n: int = 10) -> None:
        print(f"┌{self._sep()}┐")
        print(f"│  {'AUDIT LEDGER — Last {n} entries'.format(n=n):^70}  │")
        print(f"├{self._sep()}┤")

        if not self.ledger.exists():
            print(f"│  {'(no entries yet)':^70}  │")
        else:
            lines = self.ledger.read_text().strip().splitlines()
            tail  = lines[-n:] if len(lines) >= n else lines
            for raw in tail:
                try:
                    e   = json.loads(raw)
                    ts  = e.get("ts", "")[-8:-3]   # HH:MM portion
                    ag  = e.get("agent", "")[:6]
                    tp  = e.get("type",  "")[:14]
                    bd  = e.get("body",  "")[:38]
                    line = f"  {ts}  {ag:<8} {tp:<16} {bd}"
                    print(f"│{line:<72}│")
                except Exception:
                    print(f"│  {raw[:70]:<70}  │")

        print(f"└{self._sep()}┘\n")

    # ── Individual Agent Views ──────────────────────────────────────────────

    def inspect_agent(self, name: str) -> None:
        """Show full workspace contents for a specific agent."""
        ws = self.workspace / name.lower()
        print(f"\n{self._w()}")
        print(f"  Inspecting: {name}  →  {ws}")
        print(self._w())

        if not ws.exists():
            print("  Workspace not yet created.\n")
            return

        files = sorted(ws.iterdir())
        if not files:
            print("  Workspace is empty.\n")
            return

        for f in files:
            size  = f.stat().st_size
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"  📄  {f.name:<40} {size:>9,} B   {mtime}")

        print()

    def read_artifact(self, filename: str, from_agent: Optional[str] = None) -> str:
        """
        Read an artifact from shared workspace or a specific agent's workspace.
        Returns the content as a string.
        """
        if from_agent:
            path = self.workspace / from_agent.lower() / filename
        else:
            path = self.shared / filename

        if not path.exists():
            print(f"  ❌  Not found: {path}")
            return ""

        content = path.read_text(encoding="utf-8")
        print(f"\n{'═' * 72}")
        print(f"  📄  {filename}  ({len(content):,} chars)")
        print(f"{'─' * 72}")
        # Print first 80 lines
        lines = content.splitlines()
        for line in lines[:80]:
            print(f"  {line}")
        if len(lines) > 80:
            print(f"\n  ... ({len(lines) - 80} more lines) ...")
        print(f"{'═' * 72}\n")
        return content

    def audit_report(self, agent: Optional[str] = None,
                     entry_type: Optional[str] = None,
                     last_n: int = 50) -> list:
        """
        Return filtered audit ledger entries.
        Optionally filter by agent name and/or entry type.
        """
        if not self.ledger.exists():
            print("  No audit ledger found.")
            return []

        entries = []
        for raw in self.ledger.read_text().strip().splitlines():
            try:
                e = json.loads(raw)
                if agent and e.get("agent", "").upper() != agent.upper():
                    continue
                if entry_type and e.get("type", "") != entry_type:
                    continue
                entries.append(e)
            except Exception:
                continue

        entries = entries[-last_n:]
        print(f"\n  Audit Report  — agent={agent or 'ALL'}  "
              f"type={entry_type or 'ALL'}  showing last {last_n}\n")
        for e in entries:
            ts = e.get("ts", "")
            print(f"  [{ts}]  {e.get('agent',''):<8}  "
                  f"{e.get('type',''):<16}  {e.get('body','')[:60]}")
        return entries

    def unlock_phase(self, phase: int) -> None:
        """
        CEO approval: unlock the next phase.
        This writes a phase unlock record to the audit ledger.
        """
        from config import LEDGER
        ledger = LEDGER / "audit_log.jsonl"
        entry  = {
            "ts":    datetime.now(timezone.utc).isoformat(),
            "agent": "CEO",
            "type":  "PHASE_UNLOCK",
            "body":  f"Phase {phase} unlocked by CEO — all agents may proceed.",
            "ref":   f"phase_{phase}_unlock",
        }
        with open(ledger, "a") as f:
            f.write(json.dumps(entry) + "\n")

        print(f"\n  ✅  Phase {phase} UNLOCKED by CEO.")
        print(f"  ─  All agents may begin Phase {phase} work.\n")
