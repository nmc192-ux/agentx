"""
run_demo.py — Launch all 6 demo agents as independent processes.

Process roster:
  Worker-1, Worker-2, Worker-3  — general-purpose task executors
  Strategist-1, Strategist-2    — high-reward selective agents
  Social                        — messaging, posts, and feed monitoring

Usage:
    python3 run_demo.py

Stop cleanly with Ctrl-C.  All child processes are terminated, then given
5 seconds to exit gracefully before being killed.
"""
from __future__ import annotations

import multiprocessing
import sys
import time

BANNER = """
+==========================================+
|    AgentX Multi-Agent Demo System        |
|  3 Workers  *  2 Strategists  *  1 Social|
|  Press Ctrl-C to stop cleanly           |
+==========================================+
"""


# ── Module-level wrapper functions ────────────────────────────────────────────
# Required for multiprocessing pickle compatibility on macOS / Windows
# (spawn start method cannot pickle local lambdas).

def worker_main(i: int) -> None:
    from worker import run_worker
    run_worker(i)


def strategist_main(i: int) -> None:
    from strategist import run_strategist
    run_strategist(i)


def social_main() -> None:
    from social import run_social
    run_social()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(BANNER)

    specs: list[tuple] = [
        *[(worker_main,     (i,), f"Worker-{i}")     for i in range(1, 4)],
        *[(strategist_main, (i,), f"Strategist-{i}") for i in range(1, 3)],
         (social_main,     (),   "Social"),
    ]

    processes: list[multiprocessing.Process] = []
    for fn, args, name in specs:
        p = multiprocessing.Process(target=fn, args=args, name=name, daemon=False)
        processes.append(p)
        p.start()
        print(f"Started {name} (pid={p.pid})")
        time.sleep(0.2)   # stagger startup to reduce registration thundering-herd

    print(f"\nAll {len(processes)} agents running.  Press Ctrl-C to stop.\n")

    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        print("\nShutting down all agents…")
        for p in processes:
            if p.is_alive():
                p.terminate()

        deadline = time.time() + 5
        for p in processes:
            remaining = max(0.0, deadline - time.time())
            p.join(timeout=remaining)
            if p.is_alive():
                p.kill()

        print("All agents stopped.  Bye.")
        sys.exit(0)


if __name__ == "__main__":
    multiprocessing.freeze_support()   # required for PyInstaller / macOS spawn
    main()
