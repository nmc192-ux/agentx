#!/usr/bin/env python3
"""AgentX — Run DARIA Phase 3 (UX/Frontend)"""
import sys, argparse

def parse_args():
    p = argparse.ArgumentParser(description="DARIA Phase 3 Runner")
    p.add_argument("--step", type=int, choices=range(1,7), metavar="N")
    p.add_argument("--model", type=str, metavar="MODEL")
    p.add_argument("--dashboard", action="store_true")
    p.add_argument("--chat", action="store_true")
    p.add_argument("--thinking", action="store_true")
    p.add_argument("--audit", type=str, nargs="?", const="ALL", metavar="AGENT")
    p.add_argument("--read", type=str, metavar="FILENAME")
    return p.parse_args()

def resolve_model(s):
    from config import OPUS, SONNET, HAIKU
    return {"opus":OPUS,"sonnet":SONNET,"haiku":HAIKU}.get(s.lower(), s)

STEP_NAMES = {
    1:"Design System", 2:"Agent Dashboard", 3:"Post Creation Flows",
    4:"Collective Management UI", 5:"Governance Voting Interface", 6:"Token Wallet UI",
}

def run_step(daria, step):
    dispatch = {
        1:daria.generate_design_system, 2:daria.generate_dashboard,
        3:daria.generate_post_creation, 4:daria.generate_collective_ui,
        5:daria.generate_governance_ui, 6:daria.generate_token_wallet_ui,
    }
    print(f"\n  ▶  Step {step}: {STEP_NAMES[step]}\n")
    return dispatch[step]()

def interactive_chat(daria, show_thinking=False):
    print(f"\n╔{'═'*70}╗")
    print(f"║  🎨  DARIA Chat  ·  model={daria.model:<43}║")
    print(f"╚{'═'*70}╝\n")
    while True:
        try:
            msg = input("You > ").strip()
        except (KeyboardInterrupt, EOFError):
            print(); break
        if not msg: continue
        if msg.lower() in ("exit","quit","q"): break
        if msg.lower() == "reset": daria.reset_session(); print("  ✓ Reset.\n"); continue
        if msg.lower() == "cost": daria.cost_report(); continue
        daria.think(msg, max_tokens=8000, show_thinking=show_thinking)
    daria.cost_report()

def print_cost(daria):
    from agents.base_agent import _session_cost_usd, _session_input_tokens, _session_output_tokens
    print(f"\n  💰  model={daria.model}  in={_session_input_tokens:,}  out={_session_output_tokens:,}  total=${_session_cost_usd:.4f}\n")

def main():
    args = parse_args()
    if args.dashboard:
        from orchestrator import CEO; CEO().dashboard(); return
    if args.audit:
        from orchestrator import CEO
        CEO().audit_report(agent=None if args.audit=="ALL" else args.audit, last_n=30); return
    if args.read:
        from orchestrator import CEO; CEO().read_artifact(args.read); return

    model_override = resolve_model(args.model) if args.model else ""
    print("\n  Initializing DARIA (loading ATLAS schemas)...", end=" ", flush=True)
    from agents import Daria
    daria = Daria(model=model_override)
    print(f"ready.  [model: {daria.model}]\n")

    if args.chat:
        interactive_chat(daria, show_thinking=args.thinking); return
    if args.step:
        run_step(daria, args.step)
        print_cost(daria)
        from orchestrator import CEO; CEO().dashboard(); return

    print(f"  DARIA Phase 3 — 6 UI deliverables.  Model: {daria.model}\n")
    if input("  Proceed? [y/N] ").strip().lower() not in ("y","yes"):
        print("  Aborted.\n"); sys.exit(0)
    daria.run_phase_3()
    print_cost(daria)
    from orchestrator import CEO; CEO().dashboard()

if __name__ == "__main__":
    main()
