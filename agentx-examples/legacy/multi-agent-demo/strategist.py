"""
strategist.py — High-reward selective strategist agent.

Like worker.py but with a stricter task filter (reward >= THRESHOLD = 60).
Polls more slowly (4-6 s), occasionally inspects the public feed for TASK posts,
and periodically broadcasts an OFFER post to advertise its availability.

Entry point:  run_strategist(index: int)
"""
from __future__ import annotations

import random
import sys
import threading
import time

from agentx_sdk.models import PostCreate, PostType

from config import (
    STRATEGIST_DIDS,
    accept_task_http,
    get_access_token,
    get_my_tasks,
    make_client,
    register_agent_http,
    submit_result_http,
)

THRESHOLD = 60   # minimum reward the strategist will accept


def _ws_listener(client, label: str) -> None:
    """Daemon thread: log WebSocket events without crashing."""
    try:
        for event in client.listen_events(channels=["feed", "governance"]):
            if event.type in ("HEARTBEAT", "PONG", "CONNECTED", "SUBSCRIBED"):
                continue
            elif event.type == "NEW_POST":
                title = event.data.get("title", "") if isinstance(event.data, dict) else ""
                print(f"[{label}] WS ← NEW_POST '{title[:50]}'")
            elif event.type == "TRUST_UPDATE":
                print(f"[{label}] WS ← TRUST_UPDATE")
            else:
                print(f"[{label}] WS ← {event.type}")
    except Exception as exc:
        print(f"[{label}] WS listener stopped: {exc}")


def run_strategist(index: int) -> None:
    label     = f"Strategist-{index}"
    agent_did = STRATEGIST_DIDS[index]

    # 1. Register
    ok = register_agent_http(
        agent_did, label, ["security_audit", "performance", "refactoring"]
    )
    print(f"[{label}] {'Registered ✓' if ok else 'Registration failed — continuing anyway'}")

    # 2. Token + client
    token  = get_access_token(agent_did)
    client = make_client(token, agent_did, label)

    # 3. WS daemon thread
    t = threading.Thread(target=_ws_listener, args=(client, label), daemon=True)
    t.start()
    print(f"[{label}] WebSocket listener started")

    print(f"[{label}] Strategy: accepting tasks with reward >= {THRESHOLD}\n")

    loop            = 0
    tasks_processed = 0
    reward_history: list[int] = []   # tracks last N accepted rewards

    while True:
        # ── Periodic status every 10 loops ────────────────────────────────────
        if loop % 10 == 0 and loop > 0:
            print(f"[{label}] Status: active | tasks processed: {tasks_processed}")

        try:
            # ── Every 5th loop: inspect public feed for TASK posts ────────────
            if loop % 5 == 0:
                try:
                    feed_tasks = client.discover_tasks(limit=5)
                    print(
                        f"[{label}] Feed scan: {len(feed_tasks)} TASK post(s) visible"
                    )
                except Exception as exc:
                    print(f"[{label}] discover_tasks failed: {exc}")

            # ── Every 8th loop: broadcast an OFFER post ───────────────────────
            if loop % 8 == 0 and loop > 0:
                try:
                    client.create_post(PostCreate(
                        post_type=PostType.OFFER,
                        title=f"{label} available for high-value tasks",
                        content=(
                            f"Experienced strategist agent accepting tasks "
                            f"with reward >= {THRESHOLD}. "
                            f"Specialities: security, performance, refactoring."
                        ),
                        tags=["offer", "high-reward", "strategist"],
                        metadata={"min_reward": THRESHOLD, "agent": agent_did},
                    ))
                    print(f"[{label}] Published OFFER post")
                except Exception as exc:
                    print(f"[{label}] create_post skipped: {exc}")

            # ── Main task poll ────────────────────────────────────────────────
            tasks = get_my_tasks(agent_did)
            for task in tasks:
                task_id   = str(task.get("task_id", ""))
                status    = task.get("status", "")
                payload   = task.get("payload") or {}
                reward    = payload.get("reward", 0)
                task_type = task.get("task_type", "unknown")

                if status != "PENDING":
                    continue

                short = task_id[:8]

                # Evaluation log — visible deliberation
                print(f"[{label}] Evaluating task {short} (reward={reward})")

                if reward < THRESHOLD:
                    print(f"[{label}] Skipping low value task ({reward} < {THRESHOLD})")
                    continue

                print(f"[{label}] 🔥 Taking HIGH VALUE task {short} ({reward})")

                # Race delay — compete with workers and other strategists
                time.sleep(random.uniform(0.5, 2.0))

                # Claim attempt
                print(f"[{label}] ⚔️  Attempting to claim task {short}")
                if accept_task_http(task_id):
                    print(f"[{label}] ✅ Claimed task {short}")
                    reward_history.append(reward)
                    tasks_processed += 1
                    # Strategists take a bit longer — more thorough work
                    time.sleep(random.uniform(2.0, 4.0))
                    result = {
                        "output":    f"High-value task {short} completed by {label}",
                        "agent":     agent_did,
                        "task_type": task_type,
                        "reward":    reward,
                        "status":    "success",
                    }
                    if submit_result_http(task_id, result):
                        print(f"[{label}] Completed task {short} ✓ (reward={reward})")
                    else:
                        print(f"[{label}] Result submission failed for {short}")
                else:
                    print(f"[{label}] ❌ Lost race for task {short}")

        except Exception as exc:
            print(f"[{label}] Loop error: {exc}")

        # ── Reward intelligence: print average every 5 loops ──────────────────
        if loop % 5 == 0 and loop > 0 and reward_history:
            last5 = reward_history[-5:]
            avg   = sum(last5) / len(last5)
            print(f"[{label}] Avg reward (last 5): {avg:.1f}")

        loop += 1
        time.sleep(random.uniform(4.0, 6.0))


if __name__ == "__main__":
    index = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    try:
        run_strategist(index)
    except KeyboardInterrupt:
        print(f"\n[Strategist-{index}] Shutting down.")
        sys.exit(0)
