#!/usr/bin/env python3
"""
AgentX — Run ATLAS Phase 1
══════════════════════════
Entry point for running ATLAS (Chief Architect) through all 7
Phase 1 deliverables.

Usage:
  python run_atlas.py              # Run all 7 deliverables (auto model routing)
  python run_atlas.py --step 1    # Run only step 1 (identity schema)
  python run_atlas.py --step 4    # Run only step 4 (DB schema)
  python run_atlas.py --dashboard # Show CEO dashboard only (no API calls)
  python run_atlas.py --chat      # Interactive chat with ATLAS
  python run_atlas.py --models    # Show model routing table + estimated costs
  python run_atlas.py --model sonnet  # Override ATLAS model for this run
"""
import sys
import argparse

# ── Argument Parsing ─────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="AgentX — ATLAS Phase 1 Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_atlas.py                    # Full Phase 1 (all 7 deliverables)
  python run_atlas.py --step 1           # Identity schema only
  python run_atlas.py --step 4           # DB schema only
  python run_atlas.py --model sonnet     # Use Sonnet instead of Opus (5x cheaper)
  python run_atlas.py --model haiku      # Use Haiku (19x cheaper, less detail)
  python run_atlas.py --dashboard        # CEO dashboard (no API calls)
  python run_atlas.py --models           # Show model routing + cost estimate
  python run_atlas.py --chat             # Interactive ATLAS session
  python run_atlas.py --chat --thinking  # Chat with visible thinking stream
  python run_atlas.py --inspect ATLAS    # Inspect ATLAS workspace
  python run_atlas.py --audit            # Full audit log
  python run_atlas.py --audit ATLAS      # ATLAS audit entries only
        """.strip()
    )
    parser.add_argument(
        "--step", type=int, choices=range(1, 8), metavar="N",
        help="Run only step N (1-7) instead of all 7"
    )
    parser.add_argument(
        "--model", type=str, metavar="MODEL",
        help=(
            "Override ATLAS model for this run. "
            "Shortcuts: 'opus', 'sonnet', 'haiku'. "
            "Or full ID e.g. 'claude-sonnet-4-5'."
        )
    )
    parser.add_argument(
        "--models", action="store_true",
        help="Show model routing table and cost estimate, then exit"
    )
    parser.add_argument(
        "--dashboard", action="store_true",
        help="Show CEO dashboard without making API calls"
    )
    parser.add_argument(
        "--chat", action="store_true",
        help="Start an interactive chat session with ATLAS"
    )
    parser.add_argument(
        "--inspect", type=str, metavar="AGENT",
        help="Inspect a specific agent's workspace (e.g. ATLAS, BRUNO)"
    )
    parser.add_argument(
        "--audit", type=str, nargs="?", const="ALL", metavar="AGENT",
        help="Show audit log, optionally filtered by agent name"
    )
    parser.add_argument(
        "--read", type=str, metavar="FILENAME",
        help="Read and display a shared workspace artifact"
    )
    parser.add_argument(
        "--thinking", action="store_true",
        help="Show ATLAS's extended thinking stream in real-time"
    )
    return parser.parse_args()


# ── Model Shortcut Resolution ─────────────────────────────────────────────────

def resolve_model(shortcut: str) -> str:
    """
    Resolve a user-friendly model shortcut to a full Anthropic model ID.
    Accepts: 'opus', 'sonnet', 'haiku', or a full model ID.
    """
    from config import OPUS, SONNET, HAIKU
    shortcuts = {
        "opus":   OPUS,
        "sonnet": SONNET,
        "haiku":  HAIKU,
    }
    return shortcuts.get(shortcut.lower(), shortcut)


# ── Model Routing Table ───────────────────────────────────────────────────────

def show_models() -> None:
    """Print the full model routing table with cost estimates."""
    from config import MODELS, COST_TABLE, OPUS, SONNET, HAIKU

    print("\n╔══════════════════════════════════════════════════════════════════════╗")
    print("║  🧮  AgentX — Smart Model Routing                                   ║")
    print("╠══════════════════════════════════════════════════════════════════════╣")
    print(f"  {'Agent':<10} {'Model':<25} {'$/M in':<10} {'$/M out':<10} {'Savings'}")
    print(f"  {'─'*9} {'─'*24} {'─'*9} {'─'*9} {'─'*15}")

    opus_out = COST_TABLE[OPUS]["output"]
    agents   = [
        ("ATLAS",  "Chief Architect",       "deepest reasoning needed"),
        ("MARCUS", "Security Lead",         "threat modeling needs full power"),
        ("BRUNO",  "Infrastructure Lead",   "structured code gen"),
        ("DARIA",  "UX/Frontend",           "design specs & components"),
        ("THEA",   "Data & Analytics",      "SQL, schemas, pipelines"),
        ("NOVA",   "AI/ML Lead",            "system design docs"),
        ("QUINN",  "QA & Testing",          "checklists & test specs"),
        ("GIA",    "Growth & Community",    "onboarding copy & flows"),
    ]

    for name, role, reason in agents:
        model   = MODELS[name]
        ct      = COST_TABLE[model]
        inp_c   = ct["input"]
        out_c   = ct["output"]
        savings = f"{opus_out / out_c:.0f}× cheaper" if out_c < opus_out else "baseline"
        short   = model.replace("claude-", "").replace("-latest", "")
        print(f"  {name:<10} {short:<25} ${inp_c:<9.2f} ${out_c:<9.2f} {savings}")
        print(f"  {'':10} {'':25} ({reason})")

    # Cost estimate for full Phase 1
    print(f"\n{'─'*72}")
    print("  📊 Estimated Phase 1 Cost (ATLAS — 7 deliverables):")
    print()
    ct_opus = COST_TABLE[OPUS]
    # ~25K input + ~30K output + ~12K thinking tokens (all ATLAS = Opus)
    est_opus   = (25_000 * ct_opus["input"] + 42_000 * ct_opus["output"]) / 1_000_000
    ct_son     = COST_TABLE[SONNET]
    est_sonnet = (25_000 * ct_son["input"]  + 42_000 * ct_son["output"])  / 1_000_000
    ct_hku     = COST_TABLE[HAIKU]
    est_haiku  = (25_000 * ct_hku["input"]  + 42_000 * ct_hku["output"])  / 1_000_000

    print(f"  ATLAS on Opus   (default, best quality):   ~${est_opus:.2f}")
    print(f"  ATLAS on Sonnet (--model sonnet, 5× off):  ~${est_sonnet:.2f}")
    print(f"  ATLAS on Haiku  (--model haiku, 19× off):  ~${est_haiku:.2f}")
    print()
    print("  Note: Prompt caching saves ~40% on repeated runs of the same step.")
    print("╚══════════════════════════════════════════════════════════════════════╝\n")


# ── Step Dispatch ─────────────────────────────────────────────────────────────

STEP_NAMES = {
    1: "Agent Identity Schema",
    2: "Post Synthesis Schema",
    3: "Capability Registry",
    4: "PostgreSQL DB Schema",
    5: "OpenAPI Contract",
    6: "Three-Token Architecture",
    7: "Protocol Stack",
}


def run_step(atlas, step: int) -> str:
    """Run a single ATLAS Phase 1 step."""
    dispatch = {
        1: atlas.generate_identity_schema,
        2: atlas.generate_post_schema,
        3: atlas.generate_capability_registry,
        4: atlas.generate_db_schema,
        5: atlas.generate_api_contract,
        6: atlas.generate_token_architecture,
        7: atlas.generate_protocol_layers,
    }
    fn = dispatch[step]
    print(f"\n  ▶  Running Step {step}: {STEP_NAMES[step]}\n")
    return fn()


# ── Interactive Chat ──────────────────────────────────────────────────────────

def interactive_chat(atlas, show_thinking: bool = False) -> None:
    """Start an interactive multi-turn conversation with ATLAS."""
    print("\n")
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print(f"║  🏛️  ATLAS Chat  ·  model={atlas.model:<38}║")
    print("║  Type 'exit' to quit · 'reset' to clear history · 'cost' for spend  ║")
    print("╚══════════════════════════════════════════════════════════════════════╝\n")

    while True:
        try:
            user_input = input("You > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            break

        if not user_input:
            continue

        cmd = user_input.lower()
        if cmd in ("exit", "quit", "q"):
            break
        if cmd == "reset":
            atlas.reset_session()
            print("  ✓ Session reset.\n")
            continue
        if cmd == "history":
            print(f"\n  Message history: {len(atlas.messages)} entries\n")
            continue
        if cmd == "cost":
            atlas.cost_report()
            continue

        atlas.think(user_input, max_tokens=8000, show_thinking=show_thinking)

    atlas.cost_report()
    print("  Session ended. Goodbye.\n")


# ── Final Cost Summary ────────────────────────────────────────────────────────

def print_cost_summary(atlas) -> None:
    """Print a clean cost summary after a run."""
    from agents.base_agent import _session_cost_usd, _session_input_tokens, _session_output_tokens

    print("\n╔══════════════════════════════════════════════════════════════════════╗")
    print("║  💰 Session Cost Summary                                             ║")
    print("╠══════════════════════════════════════════════════════════════════════╣")
    print(f"  Model           : {atlas.model}")
    print(f"  Input tokens    : {_session_input_tokens:,}")
    print(f"  Output tokens   : {_session_output_tokens:,}")
    print(f"  Total cost      : ${_session_cost_usd:.4f}")
    print("╚══════════════════════════════════════════════════════════════════════╝\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    # ── No-API-call commands ──────────────────────────────────────────────────
    if args.models:
        show_models()
        return

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
        agent_filter = None if args.audit == "ALL" else args.audit
        CEO().audit_report(agent=agent_filter, last_n=30)
        return

    if args.read:
        from orchestrator import CEO
        CEO().read_artifact(args.read)
        return

    # ── Resolve model override ────────────────────────────────────────────────
    model_override = resolve_model(args.model) if args.model else ""

    # ── Init ATLAS ────────────────────────────────────────────────────────────
    print("\n  Initializing ATLAS...", end=" ", flush=True)
    from agents import Atlas
    atlas = Atlas(model=model_override)
    print(f"ready.  [model: {atlas.model}]\n")

    # ── Interactive chat ──────────────────────────────────────────────────────
    if args.chat:
        interactive_chat(atlas, show_thinking=args.thinking)
        return

    # ── Single step ───────────────────────────────────────────────────────────
    if args.step:
        run_step(atlas, args.step)
        print_cost_summary(atlas)
        from orchestrator import CEO
        CEO().dashboard()
        return

    # ── Full Phase 1 ─────────────────────────────────────────────────────────
    show_models()   # show the routing table before asking to proceed

    print("  Starting AgentX Phase 1 — all 7 ATLAS deliverables.")
    print(f"  Model: {atlas.model}")
    if model_override:
        print(f"  ⚠  Model overridden via --model flag.")
    print("  This will make 7 API calls. Each may take 30–120 seconds.\n")
    confirm = input("  Proceed? [y/N] ").strip().lower()
    if confirm not in ("y", "yes"):
        print("  Aborted.\n")
        sys.exit(0)

    atlas.run_phase_1()

    print_cost_summary(atlas)
    from orchestrator import CEO
    CEO().dashboard()
    print("  Phase 1 complete. Next: CEO reviews artifacts, then unlocks Phase 2.")
    print("  Run: python run_atlas.py --dashboard  to see full status.\n")


if __name__ == "__main__":
    main()
