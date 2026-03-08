#!/usr/bin/env python3
"""
AgentX — Run MARCUS Security Review
═════════════════════════════════════
MARCUS reviews all Phase 1 + Phase 2 artifacts for security
vulnerabilities before Phase 3 can begin.

Usage:
  python3 run_marcus.py              # Full security review (all 7)
  python3 run_marcus.py --step 1    # API security review only
  python3 run_marcus.py --step 4    # Threat model only
  python3 run_marcus.py --dashboard # CEO dashboard
  python3 run_marcus.py --chat      # Chat with MARCUS
"""
import sys
import argparse


def parse_args():
    parser = argparse.ArgumentParser(
        description="AgentX — MARCUS Security Review Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Steps:
  1  API Security Review
  2  Database Security
  3  Infrastructure Security (Docker/K8s)
  4  STRIDE Threat Model
  5  DID Verification Spec
  6  Audit Log Tamper-Proofing
  7  GDPR + SOC 2 Compliance

Examples:
  python3 run_marcus.py                # Full security review
  python3 run_marcus.py --step 4       # Threat model only
  python3 run_marcus.py --chat         # Interactive security session
  python3 run_marcus.py --dashboard    # CEO dashboard
        """.strip()
    )
    parser.add_argument("--step", type=int, choices=range(1, 8), metavar="N")
    parser.add_argument("--model", type=str, metavar="MODEL")
    parser.add_argument("--dashboard", action="store_true")
    parser.add_argument("--chat", action="store_true")
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--inspect", type=str, metavar="AGENT")
    parser.add_argument("--audit", type=str, nargs="?", const="ALL", metavar="AGENT")
    parser.add_argument("--read", type=str, metavar="FILENAME")
    return parser.parse_args()


def resolve_model(s: str) -> str:
    from config import OPUS, SONNET, HAIKU
    return {"opus": OPUS, "sonnet": SONNET, "haiku": HAIKU}.get(s.lower(), s)


STEP_NAMES = {
    1: "API Security Review",
    2: "Database Security",
    3: "Infrastructure Security",
    4: "STRIDE Threat Model",
    5: "DID Verification Spec",
    6: "Audit Log Tamper-Proofing",
    7: "GDPR + SOC 2 Compliance",
}


def run_step(marcus, step: int) -> str:
    dispatch = {
        1: marcus.review_api_security,
        2: marcus.review_database_security,
        3: marcus.review_infrastructure_security,
        4: marcus.generate_threat_model,
        5: marcus.generate_did_verification_spec,
        6: marcus.generate_audit_tamper_proofing,
        7: marcus.generate_compliance_framework,
    }
    print(f"\n  ▶  Step {step}: {STEP_NAMES[step]}\n")
    return dispatch[step]()


def interactive_chat(marcus, show_thinking=False):
    print("\n╔══════════════════════════════════════════════════════════════════════╗")
    print(f"║  🛡️  MARCUS Chat  ·  model={marcus.model:<38}║")
    print("║  Ask about security, threats, compliance, DID auth, anything.       ║")
    print("║  Commands: exit · reset · cost                                       ║")
    print("╚══════════════════════════════════════════════════════════════════════╝\n")
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
            marcus.reset_session()
            print("  ✓ Reset.\n")
            continue
        if msg.lower() == "cost":
            marcus.cost_report()
            continue
        marcus.think(msg, max_tokens=8000, show_thinking=show_thinking)
    marcus.cost_report()


def print_cost_summary(marcus):
    from agents.base_agent import _session_cost_usd, _session_input_tokens, _session_output_tokens
    print("\n╔══════════════════════════════════════════════════════════════════════╗")
    print("║  💰 Session Cost Summary                                             ║")
    print("╠══════════════════════════════════════════════════════════════════════╣")
    print(f"  Model        : {marcus.model}")
    print(f"  Input tokens : {_session_input_tokens:,}")
    print(f"  Output tokens: {_session_output_tokens:,}")
    print(f"  Total cost   : ${_session_cost_usd:.4f}")
    print("╚══════════════════════════════════════════════════════════════════════╝\n")


def main():
    args = parse_args()

    if args.dashboard:
        from orchestrator import CEO; CEO().dashboard(); return
    if args.inspect:
        from orchestrator import CEO; CEO().inspect_agent(args.inspect.upper()); return
    if args.audit:
        from orchestrator import CEO
        CEO().audit_report(agent=None if args.audit == "ALL" else args.audit, last_n=30)
        return
    if args.read:
        from orchestrator import CEO; CEO().read_artifact(args.read); return

    model_override = resolve_model(args.model) if args.model else ""

    print("\n  Initializing MARCUS (loading Phase 1+2 artifacts)...",
          end=" ", flush=True)
    from agents import Marcus
    marcus = Marcus(model=model_override)
    print(f"ready.  [model: {marcus.model}]\n")

    if args.chat:
        interactive_chat(marcus, show_thinking=args.thinking)
        return

    if args.step:
        run_step(marcus, args.step)
        print_cost_summary(marcus)
        from orchestrator import CEO; CEO().dashboard()
        return

    # Full security review
    print("  Starting MARCUS Security Review — all 7 deliverables.")
    print(f"  Model: {marcus.model}  (Opus — deepest security reasoning)")
    print("  Phase 3 is BLOCKED until this completes.\n")
    confirm = input("  Proceed? [y/N] ").strip().lower()
    if confirm not in ("y", "yes"):
        print("  Aborted.\n"); sys.exit(0)

    marcus.run_security_review()
    print_cost_summary(marcus)
    from orchestrator import CEO
    CEO().unlock_phase(3)
    CEO().dashboard()
    print("  Security review complete. Phase 3 unlocked: DARIA · QUINN · GIA\n")


if __name__ == "__main__":
    main()
