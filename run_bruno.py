#!/usr/bin/env python3
"""
AgentX — Run BRUNO Phase 2
═══════════════════════════
Entry point for BRUNO (Infrastructure Lead) — Phase 2.
BRUNO reads all ATLAS Phase 1 artifacts and builds the
complete backend infrastructure.

Usage:
  python3 run_bruno.py              # Run all 7 deliverables
  python3 run_bruno.py --step 1    # Alembic setup only
  python3 run_bruno.py --step 4    # FastAPI app only
  python3 run_bruno.py --dashboard # CEO dashboard (no API calls)
  python3 run_bruno.py --chat      # Interactive chat with BRUNO
"""
import sys
import argparse


def parse_args():
    parser = argparse.ArgumentParser(
        description="AgentX — BRUNO Phase 2 Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 run_bruno.py                  # Full Phase 2 (all 7 deliverables)
  python3 run_bruno.py --step 1         # Alembic setup only
  python3 run_bruno.py --step 4         # FastAPI app only
  python3 run_bruno.py --model opus     # Use Opus for deeper reasoning
  python3 run_bruno.py --dashboard      # CEO dashboard
  python3 run_bruno.py --chat           # Interactive BRUNO session
        """.strip()
    )
    parser.add_argument(
        "--step", type=int, choices=range(1, 8), metavar="N",
        help="Run only step N (1-7)"
    )
    parser.add_argument(
        "--model", type=str, metavar="MODEL",
        help="Override model: 'opus', 'sonnet', 'haiku' or full model ID"
    )
    parser.add_argument(
        "--dashboard", action="store_true",
        help="Show CEO dashboard (no API calls)"
    )
    parser.add_argument(
        "--chat", action="store_true",
        help="Interactive chat with BRUNO"
    )
    parser.add_argument(
        "--thinking", action="store_true",
        help="Show extended thinking (Opus only)"
    )
    parser.add_argument(
        "--inspect", type=str, metavar="AGENT",
        help="Inspect an agent's workspace"
    )
    parser.add_argument(
        "--audit", type=str, nargs="?", const="ALL", metavar="AGENT",
        help="Show audit log"
    )
    parser.add_argument(
        "--read", type=str, metavar="FILENAME",
        help="Read a shared workspace artifact"
    )
    return parser.parse_args()


def resolve_model(shortcut: str) -> str:
    from config import OPUS, SONNET, HAIKU
    return {"opus": OPUS, "sonnet": SONNET, "haiku": HAIKU}.get(
        shortcut.lower(), shortcut
    )


STEP_NAMES = {
    1: "Alembic Migration Setup",
    2: "SQLAlchemy ORM Models",
    3: "Redis Cache Layer",
    4: "FastAPI Application",
    5: "WebSocket Layer",
    6: "Docker Compose (Dev)",
    7: "Kubernetes (Prod)",
}


def run_step(bruno, step: int) -> str:
    dispatch = {
        1: bruno.generate_alembic_setup,
        2: bruno.generate_sqlalchemy_models,
        3: bruno.generate_redis_config,
        4: bruno.generate_fastapi_app,
        5: bruno.generate_websocket_layer,
        6: bruno.generate_docker_compose,
        7: bruno.generate_kubernetes,
    }
    print(f"\n  ▶  Running Step {step}: {STEP_NAMES[step]}\n")
    return dispatch[step]()


def interactive_chat(bruno, show_thinking: bool = False) -> None:
    print("\n")
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print(f"║  ⚙️  BRUNO Chat  ·  model={bruno.model:<39}║")
    print("║  BRUNO has ATLAS Phase 1 schemas loaded. Ask about infrastructure.  ║")
    print("║  Type 'exit' to quit · 'cost' for spend · 'reset' to clear history  ║")
    print("╚══════════════════════════════════════════════════════════════════════╝\n")

    while True:
        try:
            user_input = input("You > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            break
        if user_input.lower() == "reset":
            bruno.reset_session()
            print("  ✓ Session reset.\n")
            continue
        if user_input.lower() == "cost":
            bruno.cost_report()
            continue
        bruno.think(user_input, max_tokens=8000, show_thinking=show_thinking)

    bruno.cost_report()
    print("  Session ended.\n")


def print_cost_summary(bruno) -> None:
    from agents.base_agent import _session_cost_usd, _session_input_tokens, _session_output_tokens
    print("\n╔══════════════════════════════════════════════════════════════════════╗")
    print("║  💰 Session Cost Summary                                             ║")
    print("╠══════════════════════════════════════════════════════════════════════╣")
    print(f"  Model           : {bruno.model}")
    print(f"  Input tokens    : {_session_input_tokens:,}")
    print(f"  Output tokens   : {_session_output_tokens:,}")
    print(f"  Total cost      : ${_session_cost_usd:.4f}")
    print("╚══════════════════════════════════════════════════════════════════════╝\n")


def check_phase1_complete() -> bool:
    """Warn if ATLAS Phase 1 artifacts are missing."""
    from pathlib import Path
    shared = Path("workspace/shared")
    required = [
        "agent_identity_schema_v3.json",
        "post_synthesis_schema.json",
        "agentx_db_schema.sql",
        "agentx_api_v1.yaml",
    ]
    missing = [f for f in required if not (shared / f).exists()]
    if missing:
        print("\n  ⚠️  WARNING: ATLAS Phase 1 artifacts not found:")
        for f in missing:
            print(f"     ✗  workspace/shared/{f}")
        print("\n  Run Phase 1 first: python3 run_atlas.py")
        print("  BRUNO will proceed but schema context will be limited.\n")
        return False
    return True


def main():
    args = parse_args()

    # ── No-API commands ───────────────────────────────────────────────────────
    if args.dashboard:
        from orchestrator import CEO
        CEO().dashboard()
        return

    if args.inspect:
        from orchestrator import CEO
        CEO().inspect_agent(args.inspect.upper())
        return

    if args.audit:
        from orchestrator import CEO
        CEO().audit_report(agent=None if args.audit == "ALL" else args.audit,
                           last_n=30)
        return

    if args.read:
        from orchestrator import CEO
        CEO().read_artifact(args.read)
        return

    # ── Phase 1 check ─────────────────────────────────────────────────────────
    check_phase1_complete()

    # ── Unlock Phase 2 in audit log ──────────────────────────────────────────
    from orchestrator import CEO
    CEO().unlock_phase(2)

    # ── Model override ────────────────────────────────────────────────────────
    model_override = resolve_model(args.model) if args.model else ""

    # ── Init BRUNO ────────────────────────────────────────────────────────────
    print("\n  Initializing BRUNO (loading ATLAS schemas)...", end=" ", flush=True)
    from agents import Bruno
    bruno = Bruno(model=model_override)
    print(f"ready.  [model: {bruno.model}]\n")

    # ── Interactive chat ──────────────────────────────────────────────────────
    if args.chat:
        interactive_chat(bruno, show_thinking=args.thinking)
        return

    # ── Single step ───────────────────────────────────────────────────────────
    if args.step:
        run_step(bruno, args.step)
        print_cost_summary(bruno)
        CEO().dashboard()
        return

    # ── Full Phase 2 ─────────────────────────────────────────────────────────
    print("  Starting AgentX Phase 2 — all 7 BRUNO deliverables.")
    print(f"  Model: {bruno.model}")
    print("  ATLAS Phase 1 schemas loaded into BRUNO's context.")
    print("  Each step may take 30–90 seconds.\n")
    confirm = input("  Proceed? [y/N] ").strip().lower()
    if confirm not in ("y", "yes"):
        print("  Aborted.\n")
        sys.exit(0)

    bruno.run_phase_2()

    print_cost_summary(bruno)
    CEO().dashboard()
    print("  Phase 2 complete. Next: MARCUS security review, then Phase 3.\n")


if __name__ == "__main__":
    main()
