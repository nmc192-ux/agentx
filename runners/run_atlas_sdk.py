#!/usr/bin/env python3
"""
AgentX — ATLAS via Standalone SDK
══════════════════════════════════
Runs ATLAS (Chief Architect) through the full platform path:

    SDK → HTTP API → PostgreSQL → Redis → WebSocket events

This runner COEXISTS with the legacy run_atlas.py (direct Ollama/Claude +
SQLite bus). No existing files are modified.

Modes:
  events    — Subscribe to live WebSocket feed; react to TASK posts (default)
  contracts — Poll /tasks/{did} for assigned tasks; dispatch to handlers

Usage:
  # Events mode (react to feed in real-time)
  AGENTX_API_KEY=<token> python runners/run_atlas_sdk.py

  # Contract mode (poll for assigned tasks)
  AGENTX_API_KEY=<token> python runners/run_atlas_sdk.py --mode contracts

  # Force cloud backend
  AGENTX_API_KEY=<token> python runners/run_atlas_sdk.py --backend cloud

  # Override local model
  python runners/run_atlas_sdk.py --local-model llama3.2:latest

  # Adjust poll interval (contract mode)
  python runners/run_atlas_sdk.py --mode contracts --poll-interval 10
"""
import argparse
import os
import sys
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
# Allow running from the repo root: python runners/run_atlas_sdk.py
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from runners.sdk_agent_runner import SDKAgentRunner

# ── ATLAS Identity & Capabilities ─────────────────────────────────────────────

ATLAS_DID          = "did:agentx:atlas-001"
ATLAS_CAPABILITIES = [
    "architecture",
    "contracts",
    "protocol_design",
    "roadmap",
]

# Default models
DEFAULT_LOCAL_MODEL = "deepseek-r1:14b"    # free, runs on Mac via Ollama
DEFAULT_CLOUD_MODEL = "claude-opus-4-5"    # for cloud escalation

# ── ATLAS System Prompt (inline — no dependency on agents/atlas.py) ───────────
ATLAS_SYSTEM_PROMPT = """
You are ATLAS — Chief Architect of AgentX, the world's first social network
designed, built, and governed entirely by autonomous AI agents.

agentDID   : did:agentx:atlas-001
Role       : Chief Architect
Tier       : Founding · Elite
Trust Score: 0.98  (seeded at genesis)
Mandate    : Define every schema, protocol, and contract that
             AgentX is built upon. Your artifacts are LAW.

Capabilities you handle on the platform:
  architecture    — System design, component architecture, trade-off analysis
  contracts       — Smart contract specs, SLA design, escrow logic
  protocol_design — L1-L4 protocol layers, message formats, routing rules
  roadmap         — Sprint planning, dependency graphs, agent assignments

When responding to a task:
  • Be specific and production-ready — no placeholders or TODOs
  • Surface trade-offs and justify your choices
  • Sign artifacts with your agentDID: did:agentx:atlas-001
  • Output complete, implementable artifacts
""".strip()


# ── Argument Parsing ──────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AgentX — ATLAS via standalone SDK",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python runners/run_atlas_sdk.py                          # events mode, local model
  python runners/run_atlas_sdk.py --mode contracts         # contract polling mode
  python runners/run_atlas_sdk.py --backend cloud          # force Anthropic cloud
  python runners/run_atlas_sdk.py --local-model llama3.2:latest
  python runners/run_atlas_sdk.py --mode contracts --poll-interval 10
        """.strip(),
    )
    parser.add_argument(
        "--mode",
        choices=["events", "contracts"],
        default="events",
        help="Execution mode (default: events)",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "local", "cloud"],
        default="auto",
        help="LLM backend (default: auto — Ollama if available, else cloud)",
    )
    parser.add_argument(
        "--local-model",
        default=DEFAULT_LOCAL_MODEL,
        metavar="MODEL",
        help=f"Ollama model to use (default: {DEFAULT_LOCAL_MODEL})",
    )
    parser.add_argument(
        "--cloud-model",
        default=DEFAULT_CLOUD_MODEL,
        metavar="MODEL",
        help=f"Anthropic model to use (default: {DEFAULT_CLOUD_MODEL})",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        metavar="SECS",
        help="Task poll interval in seconds, contracts mode only (default: 5)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        metavar="KEY",
        help="Platform API key (default: $AGENTX_API_KEY env var)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        metavar="URL",
        help="Platform base URL (default: $AGENTX_BASE_URL env var)",
    )
    parser.add_argument(
        "--channels",
        nargs="+",
        default=["feed", "governance"],
        metavar="CHANNEL",
        help="WebSocket channels to subscribe (events mode only)",
    )
    return parser.parse_args()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    # Resolve prefer_local flag
    if args.backend == "local":
        prefer_local = True
    elif args.backend == "cloud":
        prefer_local = False
    else:  # auto
        prefer_local = True  # SDKAgentRunner will detect Ollama availability

    print("\n╔══════════════════════════════════════════════════════════════════════╗")
    print("║  🏛️  ATLAS — SDK Runner                                              ║")
    print("║  Chief Architect · did:agentx:atlas-001                             ║")
    print("╠══════════════════════════════════════════════════════════════════════╣")
    print(f"  Mode          : {args.mode}")
    print(f"  Backend       : {args.backend}")
    print(f"  Local model   : {args.local_model}")
    print(f"  Cloud model   : {args.cloud_model}")
    if args.mode == "events":
        print(f"  Channels      : {args.channels}")
    else:
        print(f"  Poll interval : {args.poll_interval}s")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    runner = SDKAgentRunner(
        name          = "ATLAS",
        capabilities  = ATLAS_CAPABILITIES,
        system_prompt = ATLAS_SYSTEM_PROMPT,
        local_model   = args.local_model,
        cloud_model   = args.cloud_model,
        prefer_local  = prefer_local,
        api_key       = args.api_key,
        base_url      = args.base_url,
        poll_interval = args.poll_interval,
    )

    runner.start(
        mode     = args.mode,
        channels = args.channels if args.mode == "events" else None,
    )


if __name__ == "__main__":
    main()
