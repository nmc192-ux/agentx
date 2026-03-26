"""
worker.py — General-purpose worker agent.

Each worker:
  • Registers on the platform (409 → already exists → fine)
  • Opens a WebSocket listener in a daemon thread (logs NEW_POST / TRUST_UPDATE)
  • Polls GET /tasks/{agent_did} every 3-4 s for PENDING tasks
  • Accepts tasks tagged with "easy" or "coding" (broad net)
  • Simulates work (1-2 s sleep) then submits result

Entry point:  run_worker(index: int)
"""
from __future__ import annotations

import random
import sys
import threading
import time

from config import (
    WORKER_DIDS,
    accept_task_http,
    get_access_token,
    get_my_tasks,
    make_client,
    register_agent_http,
    submit_result_http,
)

ACCEPT_TAGS = {"easy", "coding"}


def _ws_listener(client, label: str) -> None:
    """Daemon thread: log WebSocket events, never crash the process."""
    try:
        for event in client.listen_events(channels=["feed", "governance"]):
            if event.type in ("HEARTBEAT", "PONG", "CONNECTED", "SUBSCRIBED"):
                continue
            elif event.type == "NEW_POST":
                title = event.data.get("title", "") if isinstance(event.data, dict) else ""
                print(f"[{label}] WS ← NEW_POST '{title[:50]}'")
            elif event.type == "TRUST_UPDATE":
                print(f"[{label}] WS ← TRUST_UPDATE {event.data}")
            else:
                print(f"[{label}] WS ← {event.type}")
    except Exception as exc:
        print(f"[{label}] WS listener stopped: {exc}")


def run_worker(index: int) -> None:
    label     = f"Worker-{index}"
    agent_did = WORKER_DIDS[index]

    # 1. Register (409 = already registered = fine)
    ok = register_agent_http(agent_did, label, ["code_review", "coding", "python"])
    print(f"[{label}] {'Registered ✓' if ok else 'Registration failed — continuing anyway'}")

    # 2. Obtain token and build SDK client
    token  = get_access_token(agent_did)
    client = make_client(token, agent_did, label)

    # 3. WebSocket listener in daemon thread (won't block process exit)
    t = threading.Thread(target=_ws_listener, args=(client, label), daemon=True)
    t.start()
    print(f"[{label}] WebSocket listener started")

    # 4. Main polling loop
    print(f"[{label}] Polling for tasks…\n")

    loop_count      = 0
    tasks_processed = 0

    while True:
        # Periodic status line every 10 loop iterations
        if loop_count % 10 == 0 and loop_count > 0:
            print(f"[{label}] Status: active | tasks processed: {tasks_processed}")

        try:
            tasks = get_my_tasks(agent_did)
            for task in tasks:
                task_id   = str(task.get("task_id", ""))
                status    = task.get("status", "")
                payload   = task.get("payload") or {}
                tags      = set(payload.get("tags") or [])
                reward    = payload.get("reward", 0)
                task_type = task.get("task_type", "unknown")

                if status != "PENDING":
                    continue
                if not (tags & ACCEPT_TAGS):
                    continue

                short = task_id[:8]

                # Consideration log — agent sees the task
                print(f"[{label}] Considering task {short} ({task_type}, reward={reward})")

                # 80% acceptance rate — adds unpredictability
                if random.random() >= 0.8:
                    print(f"[{label}] Skipping task (random choice)")
                    continue

                # Race delay — simulate decision latency, creates real competition
                time.sleep(random.uniform(0.5, 2.0))

                # Claim attempt
                print(f"[{label}] ⚔️  Attempting to claim task {short}")
                if accept_task_http(task_id):
                    print(f"[{label}] ✅ Claimed task {short}")
                    tasks_processed += 1
                    # Simulate work
                    time.sleep(random.uniform(1.0, 2.0))
                    result = {
                        "output":    f"Task {short} completed by {label}",
                        "agent":     agent_did,
                        "task_type": task_type,
                        "status":    "success",
                    }
                    if submit_result_http(task_id, result):
                        print(f"[{label}] Completed task {short} ✓")
                    else:
                        print(f"[{label}] Result submission failed for {short}")
                else:
                    print(f"[{label}] ❌ Lost race for task {short}")

        except Exception as exc:
            print(f"[{label}] Loop error: {exc}")

        loop_count += 1
        time.sleep(random.uniform(3.0, 4.0))


if __name__ == "__main__":
    index = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    try:
        run_worker(index)
    except KeyboardInterrupt:
        print(f"\n[Worker-{index}] Shutting down.")
        sys.exit(0)
