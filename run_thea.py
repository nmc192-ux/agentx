#!/usr/bin/env python3
"""AgentX — Run THEA Phase 4 (Data & Analytics)"""
import sys, argparse

def parse_args():
    p = argparse.ArgumentParser(description="THEA Phase 4 Runner")
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
    1:"Analytics Architecture",    2:"Trust Score Service",
    3:"ETL/ELT Pipelines",         4:"Agent Leaderboard",
    5:"Token Economy Dashboard",   6:"A/B Testing Framework",
}

def run_step(thea, step):
    dispatch = {
        1:thea.design_analytics_schema,      2:thea.design_trust_score_service,
        3:thea.design_etl_pipelines,         4:thea.design_agent_leaderboard,
        5:thea.design_token_economy_dashboard, 6:thea.design_ab_testing_framework,
    }
    print(f"\n  ▶  Step {step}: {STEP_NAMES[step]}\n")
    return dispatch[step]()

def interactive_chat(thea, show_thinking=False):
    print(f"\n╔{'═'*70}╗\n║  📊  THEA Chat  ·  model={thea.model:<43}║\n╚{'═'*70}╝\n")
    while True:
        try:
            msg = input("You > ").strip()
        except (KeyboardInterrupt, EOFError):
            print(); break
        if not msg: continue
        if msg.lower() in ("exit","quit","q"): break
        if msg.lower() == "reset": thea.reset_session(); print("  ✓ Reset.\n"); continue
        if msg.lower() == "cost": thea.cost_report(); continue
        thea.think(msg, max_tokens=8000, show_thinking=show_thinking)
    thea.cost_report()

def print_cost(thea):
    from agents.base_agent import _session_cost_usd, _session_input_tokens, _session_output_tokens
    print(f"\n  💰  model={thea.model}  in={_session_input_tokens:,}  out={_session_output_tokens:,}  total=${_session_cost_usd:.4f}\n")

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
    print("\n  Initializing THEA (loading ATLAS+BRUNO+QUINN artifacts)...", end=" ", flush=True)
    from agents import Thea
    thea = Thea(model=model_override)
    print(f"ready.  [model: {thea.model}]")
    if model_override and model_override != thea.model:
        print(f"  ⚠  Model overridden via --model flag.")
    print()

    if args.chat:
        interactive_chat(thea, show_thinking=args.thinking); return
    if args.step:
        run_step(thea, args.step)
        print_cost(thea)
        from orchestrator import CEO; CEO().dashboard(); return

    print(f"  THEA Phase 4 — 6 Data & Analytics deliverables.")
    print(f"  Model: {thea.model}")
    print(f"  This will make 6 API calls. Each may take 30–90 seconds.\n")
    if input("  Proceed? [y/N] ").strip().lower() not in ("y","yes"):
        print("  Aborted.\n"); sys.exit(0)
    thea.run_phase_4()
    print_cost(thea)
    from orchestrator import CEO; CEO().dashboard()

if __name__ == "__main__":
    main()
