#!/usr/bin/env python3
"""
AgentX — Phase 5: Autonomous Cross-Team Review + Implementation Roadmap
═══════════════════════════════════════════════════════════════════════════
Cost-optimised: exactly 3 LLM calls total.
  Step 1: MARCUS  — security cross-review   (1 local call,  free)
  Step 2: QUINN   — QA cross-review         (1 local call,  free)
  Step 3: ATLAS   — implementation roadmap  (1 cloud Sonnet, ~$0.15)
  Step 4: LOOP    — autonomous response loop (routes QUERY messages, 1 call/msg)

Usage:
  source .venv/bin/activate
  python3 run_phase5.py                   # all steps
  python3 run_phase5.py --step 1          # MARCUS security review only
  python3 run_phase5.py --step 2          # QUINN QA review only
  python3 run_phase5.py --step 3          # ATLAS roadmap only
  python3 run_phase5.py --step 4          # autonomous loop only (routes messages)
  python3 run_phase5.py --no-loop         # steps 1-3, skip loop
  python3 run_phase5.py --dashboard       # print CEO dashboard
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def parse_args():
    p = argparse.ArgumentParser(description="AgentX Phase 5")
    p.add_argument("--step",      type=int, choices=[1, 2, 3, 4],
                   help="Run a single step (1=MARCUS, 2=QUINN, 3=ATLAS, 4=loop)")
    p.add_argument("--no-loop",   action="store_true",
                   help="Skip the autonomous response loop (step 4)")
    p.add_argument("--dashboard", action="store_true",
                   help="Print the CEO dashboard and exit")
    p.add_argument("--model",     type=str, default="",
                   help="Override model for all agents (e.g. sonnet)")
    return p.parse_args()


def resolve_model(name: str) -> str:
    from config import OPUS, SONNET, HAIKU
    m = name.lower().strip()
    if m in ("opus",):    return OPUS
    if m in ("sonnet",):  return SONNET
    if m in ("haiku",):   return HAIKU
    return name  # pass through as-is (Ollama model name)


def confirm(prompt: str) -> bool:
    try:
        ans = input(f"\n  {prompt} [y/N] ").strip().lower()
        return ans in ("y", "yes")
    except EOFError:
        return True   # non-interactive mode — proceed


def print_banner(step: int, title: str, cost: str, backend: str) -> None:
    w = 68
    print(f"\n{'╔' + '═'*w + '╗'}")
    print(f"║{'  PHASE 5 — STEP {}'.format(step).center(w)}║")
    print(f"║{title.center(w)}║")
    print(f"{'╠' + '═'*w + '╣'}")
    print(f"║{'  Cost: ' + cost:<{w}}║")
    print(f"║{'  Backend: ' + backend:<{w}}║")
    print(f"{'╚' + '═'*w + '╝'}\n")


def step1_marcus(model_override: str = "") -> None:
    """Step 1: MARCUS security cross-review (1 local call)."""
    print_banner(1, "MARCUS — Security Cross-Review", "Free (local deepseek-r1:14b)", "local")
    from agents.marcus import Marcus
    marcus = Marcus(model=model_override)
    marcus.run_phase_5()
    print("\n  ✅  MARCUS Phase 5 complete — security_gap_analysis.md published\n")


def step2_quinn(model_override: str = "") -> None:
    """Step 2: QUINN QA cross-review (1 local call)."""
    print_banner(2, "QUINN — QA Cross-Review", "Free (local deepseek-r1:14b)", "local")
    from agents.quinn import Quinn
    quinn = Quinn(model=model_override)
    quinn.run_phase_5()
    print("\n  ✅  QUINN Phase 5 complete — qa_gap_analysis.md published\n")


def step3_atlas(model_override: str = "") -> None:
    """Step 3: ATLAS implementation roadmap (1 cloud Sonnet call)."""
    print_banner(3, "ATLAS — Implementation Roadmap", "~$0.10-0.20 (cloud Sonnet)", "cloud")
    from agents.atlas import Atlas
    # ATLAS roadmap synthesis always uses cloud Sonnet internally,
    # but accept an explicit override for testing.
    atlas = Atlas(model=model_override)
    atlas.synthesize_implementation_plan()
    print("\n  ✅  ATLAS Phase 5 complete — phase5_implementation_plan.md published\n")


def step4_loop(model_override: str = "") -> None:
    """Step 4: Autonomous loop — routes QUERY messages to agents (1 call/msg)."""
    print_banner(4, "ORCHESTRATION LOOP — Routing Agent Messages", "1 local call per message", "local")

    # Load agents that have pending QUERY messages (BRUNO, THEA, NOVA, ATLAS)
    from agents.bruno  import Bruno
    from agents.thea   import Thea
    from agents.nova   import Nova
    from agents.atlas  import Atlas

    agents = {
        "BRUNO": Bruno(model=model_override),
        "THEA":  Thea(model=model_override),
        "NOVA":  Nova(model=model_override),
        "ATLAS": Atlas(model=model_override),
    }

    from orchestrator.loop import OrchestrationLoop
    loop = OrchestrationLoop(
        agents        = agents,
        poll_interval = 1.0,
        max_tokens    = 3000,   # lean responses — this is a review loop
        verbose       = True,
        start_id      = 43,     # skip old ANNOUNCE flood; pick up Phase 5 QUERYs (#44+)
    )
    loop.run(
        stop_when_idle = True,
        idle_threshold = 4,     # 4 empty polls (~4 seconds) → stop
    )
    print("\n  ✅  Orchestration loop complete — agents have responded to all messages\n")


def print_dashboard() -> None:
    from orchestrator.ceo import CEO
    ceo = CEO()
    ceo.dashboard()


# ── Cost summary ───────────────────────────────────────────────────────────────

def print_cost_summary() -> None:
    import json
    from pathlib import Path
    from collections import defaultdict
    import re

    ledger = ROOT / "ledger" / "audit_log.jsonl"
    if not ledger.exists():
        return

    costs = defaultdict(float)
    entries = [json.loads(l) for l in ledger.read_text().splitlines()]
    for e in entries:
        if e.get("type") == "TASK_DONE" and not e.get("local", True):
            m = re.search(r"\$(\d+\.\d+)", e.get("body", ""))
            if m:
                costs[e["agent"]] += float(m.group(1))

    total = sum(costs.values())
    print(f"\n{'─'*68}")
    print(f"  💰  CUMULATIVE CLOUD SPEND")
    for agent, cost in sorted(costs.items()):
        print(f"     {agent:<8}  ${cost:.4f}")
    print(f"  {'─'*38}")
    print(f"     TOTAL    ${total:.4f}")
    print(f"{'─'*68}\n")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    if args.dashboard:
        print_dashboard()
        return

    model_override = resolve_model(args.model) if args.model else ""

    # ── Single step mode ────────────────────────────────────────────────────
    if args.step:
        if args.step == 1:  step1_marcus(model_override)
        elif args.step == 2: step2_quinn(model_override)
        elif args.step == 3: step3_atlas(model_override)
        elif args.step == 4: step4_loop(model_override)
        print_cost_summary()
        return

    # ── Full Phase 5 run ────────────────────────────────────────────────────
    print(f"\n{'╔' + '═'*68 + '╗'}")
    print(f"║{'  🏗️   AGENTX — PHASE 5   Autonomous Cross-Team Review'.center(68)}║")
    print(f"{'╠' + '═'*68 + '╣'}")
    print(f"║{'  Step 1: MARCUS  security cross-review   (local, free)'.ljust(68)}║")
    print(f"║{'  Step 2: QUINN   QA cross-review         (local, free)'.ljust(68)}║")
    print(f"║{'  Step 3: ATLAS   implementation roadmap  (cloud Sonnet)'.ljust(68)}║")
    print(f"║{'  Step 4: LOOP    route QUERY messages     (local/free per msg)'.ljust(68)}║")
    print(f"╠{'═'*68}╣")
    print(f"║{'  Total budget: ~$0.15 cloud + free local calls'.ljust(68)}║")
    print(f"{'╚' + '═'*68 + '╝'}\n")

    if not confirm("Start Phase 5? (~$0.15 cloud spend for Step 3)"):
        print("  Aborted.\n")
        return

    # Step 1: MARCUS
    step1_marcus(model_override)

    # Step 2: QUINN (reads MARCUS output)
    step2_quinn(model_override)

    # Step 3: ATLAS synthesis (cloud — the one paid call)
    step3_atlas(model_override)

    # Step 4: Autonomous loop (local — routes QUERY messages filed by MARCUS + QUINN)
    if not args.no_loop:
        print("\n  Starting orchestration loop to route agent QUERY messages...")
        step4_loop(model_override)

    # Final dashboard
    print_dashboard()
    print_cost_summary()

    print(f"\n{'╔' + '═'*68 + '╗'}")
    print(f"║{'  ✅  PHASE 5 COMPLETE'.center(68)}║")
    print(f"{'╠' + '═'*68 + '╣'}")
    print(f"║{'  security_gap_analysis.md     — MARCUS'.ljust(68)}║")
    print(f"║{'  qa_gap_analysis.md           — QUINN'.ljust(68)}║")
    print(f"║{'  phase5_implementation_plan.md — ATLAS'.ljust(68)}║")
    print(f"╠{'═'*68}╣")
    print(f"║{'  AgentX is ready to build. Sprint 1 starts now.'.ljust(68)}║")
    print(f"{'╚' + '═'*68 + '╝'}\n")


if __name__ == "__main__":
    main()
