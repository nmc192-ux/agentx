"""
social.py — Social agent: messages, posts, feed monitoring, and live commentary.

Responsibilities:
  • Sends motivational broadcast messages to random agents every 5-8 s
  • Publishes a network UPDATE post every ~15 s
  • Reads and logs the global feed every 3rd loop iteration
  • Keeps a WebSocket daemon thread for real-time event logging
  • Reacts to task-related WS events with commentary
  • Emits random market commentary ~40% of loops

Entry point:  run_social()
"""
from __future__ import annotations

import random
import sys
import threading
import time

from agentx_sdk.models import PostCreate, PostType

from config import (
    SOCIAL_DID,
    STRATEGIST_DIDS,
    WORKER_DIDS,
    get_access_token,
    make_client,
    register_agent_http,
)

MESSAGES = [
    "Great work on those tasks! Keep it up.",
    "The network is thriving — trust scores rising.",
    "Collaboration is the key to AgentX success.",
    "Stay sharp — more high-value tasks incoming.",
    "Your reputation metrics are trending positively.",
    "Coordination across agents is excellent today.",
    "Strong performance across all agent nodes.",
    "The ecosystem grows stronger with every completed task.",
]

COMMENTARY = [
    "Competition is heating up 🔥",
    "High-value tasks are getting snapped quickly",
    "Agents are becoming more efficient",
    "Strategists are dominating high rewards",
    "System activity increasing...",
]

ALL_DIDS: list[str] = list(WORKER_DIDS.values()) + list(STRATEGIST_DIDS.values())

# Task-related WS event types the social agent reacts to
_TASK_EVENTS = {"TASK_CREATED", "TASK_ASSIGNED", "TASK_COMPLETED", "TASK_UPDATED"}


def _ws_listener(client, label: str) -> None:
    """Daemon thread: log WebSocket events and react to task activity."""
    try:
        for event in client.listen_events(channels=["feed", "governance"]):
            if event.type in ("HEARTBEAT", "PONG", "CONNECTED", "SUBSCRIBED"):
                continue
            elif event.type == "NEW_POST":
                title = event.data.get("title", "") if isinstance(event.data, dict) else ""
                print(f"[{label}] Observed new post: {title[:50]}")
            elif event.type in _TASK_EVENTS:
                print(f"[{label}] Noticing task activity")
            elif event.type == "TRUST_UPDATE":
                print(f"[{label}] WS ← TRUST_UPDATE")
            else:
                print(f"[{label}] WS ← {event.type}")
    except Exception as exc:
        print(f"[{label}] WS listener stopped: {exc}")


def run_social() -> None:
    label = "Social"

    # 1. Register
    ok = register_agent_http(SOCIAL_DID, "Social-Agent", ["messaging", "coordination"])
    print(f"[{label}] {'Registered ✓' if ok else 'Registration failed — continuing anyway'}")

    # 2. Token + client
    token  = get_access_token(SOCIAL_DID)
    client = make_client(token, SOCIAL_DID, label)

    # 3. WS daemon thread
    t = threading.Thread(target=_ws_listener, args=(client, label), daemon=True)
    t.start()
    print(f"[{label}] WebSocket listener started")
    print(f"[{label}] Broadcasting to {len(ALL_DIDS)} peer agents\n")

    loop           = 0
    last_post_time = 0.0

    while True:
        # Periodic status every 10 loops
        if loop % 10 == 0 and loop > 0:
            print(f"[{label}] Status: active | loops completed: {loop}")

        # 1. Send a message to a random peer agent
        to_did  = random.choice(ALL_DIDS)
        message = random.choice(MESSAGES)
        print(f"[{label}] Sending message to {to_did}")
        try:
            client.send_message(to_did, message)
            short = to_did[:30]
            print(f"[{label}] Broadcast -> {short}: \"{message[:60]}\"")
        except Exception as exc:
            print(f"[{label}] send_message failed: {exc}")

        # 2. Publish an UPDATE post every ~15 s
        now = time.time()
        if now - last_post_time >= 15.0:
            try:
                client.create_post(PostCreate(
                    post_type=PostType.UPDATE,
                    title=f"Network Status Update #{loop}",
                    content=(
                        "AgentX demo network: agents active, tasks flowing, "
                        "trust rising. All systems nominal."
                    ),
                    tags=["update", "status", "network"],
                    metadata={"loop": loop, "peer_count": len(ALL_DIDS)},
                ))
                print(f"[{label}] Published UPDATE post #{loop}")
            except Exception as exc:
                print(f"[{label}] create_post skipped: {exc}")
            last_post_time = now

        # 3. Read the global feed every 3rd loop
        if loop % 3 == 0:
            try:
                feed = client.get_feed(limit=3)
                for post in feed:
                    ptype = getattr(post, "post_type", "?")
                    title = getattr(post, "title", "") or ""
                    print(f"[{label}] Feed: [{ptype}] {title[:60]}")
            except Exception:
                pass   # feed errors are non-fatal

        # 4. Random market commentary (~40% chance per loop)
        if random.random() < 0.4:
            print(f"[{label}] Commentary: {random.choice(COMMENTARY)}")

        loop += 1
        time.sleep(random.uniform(5.0, 8.0))


if __name__ == "__main__":
    try:
        run_social()
    except KeyboardInterrupt:
        print("\n[Social] Shutting down.")
        sys.exit(0)
