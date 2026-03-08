#!/usr/bin/env python3
"""
AgentX — Run GIA Phase 3 (Growth & Community)
═══════════════════════════════════════════════
Entry point for running GIA through all 6 Phase 3 deliverables.

Usage:
  python3 run_gia.py              # Run all 6 deliverables
  python3 run_gia.py --step 1    # Onboarding flow only
  python3 run_gia.py --step 4    # Growth metrics only
  python3 run_gia.py --dashboard # CEO dashboard (no API calls)
  python3 run_gia.py --chat      # Interactive chat with GIA
  python3 run_gia.py --model haiku  # Override model (GIA default = Haiku)
"""
import sys, argparse


def parse_args():
    p = argparse.ArgumentParser(
        description="GIA Phase 3 Runner — Growth & Community",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 run_gia.py                  # Full Phase 3 (all 6 deliverables)
  python3 run_gia.py --step 1        # Agent onboarding flow
  python3 run_gia.py --step 2        # Collective charter templates
  python3 run_gia.py --step 3        # Bootstrap incentive program
  python3 run_gia.py --step 4        # Growth metrics dashboard
  python3 run_gia.py --step 5        # Community health scoring
  python3 run_gia.py --step 6        # Developer evangelist program
  python3 run_gia.py --model sonnet  # Use Sonnet (better quality)
  python3 run_gia.py --dashboard     # CEO dashboard only
  python3 run_gia.py --chat          # Interactive GIA session
        """.strip()
    )
    p.add_argument("--step",  type=int, choices=range(1, 7), metavar="N",
                   help="Run only step N (1-6)")
    p.add_argument("--model", type=str, metavar="MODEL",
                   help="Override model: 'opus', 'sonnet', 'haiku', or full ID")
    p.add_argument("--dashboard",  action="store_true",
                   help="Show CEO dashboard without making API calls")
    p.add_argument("--chat",       action="store_true",
                   help="Start interactive chat session with GIA")
    p.add_argument("--thinking",   action="store_true",
                   help="Show extended thinking stream (if supported)")
    p.add_argument("--audit", type=str, nargs="?", const="ALL", metavar="AGENT",
                   help="Show audit log, optionally filtered by agent name")
    p.add_argument("--read", type=str, metavar="FILENAME",
                   help="Read and display a shared workspace artifact")
    return p.parse_args()


def resolve_model(s: str) -> str:
    from config import OPUS, SONNET, HAIKU
    return {"opus": OPUS, "sonnet": SONNET, "haiku": HAIKU}.get(s.lower(), s)


STEP_NAMES = {
    1: "Agent Onboarding Flow",
    2: "Collective Charter Templates",
    3: "Bootstrap Incentive Program",
    4: "Growth Metrics Dashboard",
    5: "Community Health Scoring",
    6: "Developer Evangelist Program",
}


def run_step(gia, step: int) -> str:
    dispatch = {
        1: gia.generate_onboarding_flow,
        2: gia.generate_collective_charter_templates,
        3: gia.generate_bootstrap_incentives,
        4: gia.generate_growth_metrics_spec,
        5: gia.generate_community_health_system,
        6: gia.generate_developer_program,
    }
    print(f"\n  ▶  Step {step}: {STEP_NAMES[step]}\n")
    return dispatch[step]()


def interactive_chat(gia, show_thinking: bool = False) -> None:
    print(f"\n╔{'═'*70}╗")
    print(f"║  🌱  GIA Chat  ·  model={gia.model:<44}║")
    print(f"║  Type 'exit' to quit · 'reset' to clear history · 'cost' for spend  ║")
    print(f"╚{'═'*70}╝\n")
    while True:
        try:
            msg = input("You > ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if not msg:
            continue
        if msg.lower() in ("exit", "quit", "q"):
            break
        if msg.lower() == "reset":
            gia.reset_session()
            print("  ✓ Session reset.\n")
            continue
        if msg.lower() == "cost":
            gia.cost_report()
            continue
        gia.think(msg, max_tokens=8000, show_thinking=show_thinking)
    gia.cost_report()
    print("  Session ended. Goodbye.\n")


def print_cost(gia) -> None:
    from agents.base_agent import _session_cost_usd, _session_input_tokens, _session_output_tokens
    print(f"\n╔{'═'*70}╗")
    print(f"║  💰  Session Cost Summary{'':45}║")
    print(f"╠{'═'*70}╣")
    print(f"  Model        : {gia.model}")
    print(f"  Input tokens : {_session_input_tokens:,}")
    print(f"  Output tokens: {_session_output_tokens:,}")
    print(f"  Total cost   : ${_session_cost_usd:.4f}")
    print(f"╚{'═'*70}╝\n")


def main():
    args = parse_args()

    # ── No-API commands ───────────────────────────────────────────────────────
    if args.dashboard:
        from orchestrator import CEO
        CEO().dashboard()
        return

    if args.audit:
        from orchestrator import CEO
        CEO().audit_report(agent=None if args.audit == "ALL" else args.audit, last_n=30)
        return

    if args.read:
        from orchestrator import CEO
        CEO().read_artifact(args.read)
        return

    # ── Init GIA ──────────────────────────────────────────────────────────────
    model_override = resolve_model(args.model) if args.model else ""
    print("\n  Initializing GIA (loading ATLAS artifacts)...", end=" ", flush=True)
    from agents import Gia
    gia = Gia(model=model_override)
    print(f"ready.  [model: {gia.model}]\n")

    # ── Interactive chat ──────────────────────────────────────────────────────
    if args.chat:
        interactive_chat(gia, show_thinking=args.thinking)
        return

    # ── Single step ───────────────────────────────────────────────────────────
    if args.step:
        run_step(gia, args.step)
        print_cost(gia)
        from orchestrator import CEO
        CEO().dashboard()
        return

    # ── Full Phase 3 ──────────────────────────────────────────────────────────
    print(f"  GIA Phase 3 — 6 Growth & Community deliverables.")
    print(f"  Model: {gia.model}")
    if model_override:
        print(f"  ⚠  Model overridden via --model flag.")
    print(f"  This will make 6 API calls. Each may take 30–90 seconds.\n")

    if input("  Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
        print("  Aborted.\n")
        sys.exit(0)

    gia.run_phase_3()
    print_cost(gia)
    from orchestrator import CEO
    CEO().dashboard()
    print("  Phase 3 (GIA) complete. CEO reviews all Phase 3 artifacts.\n")
    print("  Next: run THEA (Phase 4 Data & Analytics) or review dashboard.\n")


if __name__ == "__main__":
    main()
