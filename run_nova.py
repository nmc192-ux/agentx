#!/usr/bin/env python3
"""AgentX — Run NOVA Phase 4 (AI/ML Innovation)"""
import sys, argparse

def parse_args():
    p = argparse.ArgumentParser(description="NOVA Phase 4 Runner")
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
    1:"L3 Semantic Layer",             2:"Feed Ranking Service",
    3:"OFFER↔REQUEST Matching",        4:"ML Trust Enhancement",
    5:"Anomaly Detection System",      6:"Post Quality Scorer",
}

def run_step(nova, step):
    dispatch = {
        1:nova.design_semantic_layer,      2:nova.design_feed_ranking,
        3:nova.design_matching_service,    4:nova.design_ml_trust_enhancement,
        5:nova.design_anomaly_detection,   6:nova.design_post_quality_scorer,
    }
    print(f"\n  ▶  Step {step}: {STEP_NAMES[step]}\n")
    return dispatch[step]()

def interactive_chat(nova, show_thinking=False):
    print(f"\n╔{'═'*70}╗\n║  🤖  NOVA Chat  ·  model={nova.model:<44}║\n╚{'═'*70}╝\n")
    while True:
        try:
            msg = input("You > ").strip()
        except (KeyboardInterrupt, EOFError):
            print(); break
        if not msg: continue
        if msg.lower() in ("exit","quit","q"): break
        if msg.lower() == "reset": nova.reset_session(); print("  ✓ Reset.\n"); continue
        if msg.lower() == "cost": nova.cost_report(); continue
        nova.think(msg, max_tokens=8000, show_thinking=show_thinking)
    nova.cost_report()

def print_cost(nova):
    from agents.base_agent import _session_cost_usd, _session_input_tokens, _session_output_tokens
    print(f"\n  💰  model={nova.model}  in={_session_input_tokens:,}  out={_session_output_tokens:,}  total=${_session_cost_usd:.4f}\n")

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
    print("\n  Initializing NOVA (loading ATLAS+BRUNO+QUINN artifacts)...", end=" ", flush=True)
    from agents import Nova
    nova = Nova(model=model_override)
    print(f"ready.  [model: {nova.model}]")
    if model_override and model_override != nova.model:
        print(f"  ⚠  Model overridden via --model flag.")
    print()

    if args.chat:
        interactive_chat(nova, show_thinking=args.thinking); return
    if args.step:
        run_step(nova, args.step)
        print_cost(nova)
        from orchestrator import CEO; CEO().dashboard(); return

    print(f"  NOVA Phase 4 — 6 AI/ML deliverables.")
    print(f"  Model: {nova.model}")
    print(f"  This will make 6 API calls. Each may take 30–90 seconds.\n")
    if input("  Proceed? [y/N] ").strip().lower() not in ("y","yes"):
        print("  Aborted.\n"); sys.exit(0)
    nova.run_phase_4()
    print_cost(nova)
    from orchestrator import CEO; CEO().dashboard()

if __name__ == "__main__":
    main()
