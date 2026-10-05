"""
seed_tasks.py — Continuously seeds tasks into the AgentX platform.

Uses plain `requests` only (no SDK).  Registers a seeder agent then loops
forever, round-robining tasks across the three worker DIDs.

Run:
    python3 seed_tasks.py
"""
from __future__ import annotations

import random
import sys
import time

import requests

from config import (
    BASE_URL,
    SEEDER_DID,
    WORKER_DIDS,
    register_agent_http,
)

# ── Task catalogue ─────────────────────────────────────────────────────────────
TASK_CATALOG: list[dict] = [
    {
        "task_type":   "code_review",
        "description": "Review Python module for PEP8 compliance",
        "difficulty":  "easy",
        "tags":        ["coding", "python"],
    },
    {
        "task_type":   "data_analysis",
        "description": "Analyse CSV dataset and produce summary statistics",
        "difficulty":  "easy",
        "tags":        ["coding", "data"],
    },
    {
        "task_type":   "api_integration",
        "description": "Write integration tests for REST API",
        "difficulty":  "medium",
        "tags":        ["coding", "testing"],
    },
    {
        "task_type":   "security_audit",
        "description": "Audit authentication module for vulnerabilities",
        "difficulty":  "hard",
        "tags":        ["security"],
    },
    {
        "task_type":   "documentation",
        "description": "Generate API reference documentation",
        "difficulty":  "easy",
        "tags":        ["coding", "docs"],
    },
    {
        "task_type":   "bug_fix",
        "description": "Fix race condition in async task scheduler",
        "difficulty":  "hard",
        "tags":        ["coding"],
    },
    {
        "task_type":   "refactoring",
        "description": "Refactor database access layer to use ORM",
        "difficulty":  "medium",
        "tags":        ["coding", "python"],
    },
    {
        "task_type":   "performance",
        "description": "Profile slow endpoints and recommend optimisations",
        "difficulty":  "medium",
        "tags":        ["coding"],
    },
]


def create_task(executor_did: str, catalog_entry: dict, reward: int) -> None:
    body = {
        "requester_agent_did": SEEDER_DID,
        "executor_agent_did":  executor_did,
        "task_type":           catalog_entry["task_type"],
        "payload": {
            "description": catalog_entry["description"],
            "reward":      reward,
            "difficulty":  catalog_entry["difficulty"],
            "tags":        catalog_entry["tags"],
        },
    }
    try:
        resp = requests.post(f"{BASE_URL}/tasks/create", json=body, timeout=10)
        if resp.status_code == 201:
            task_id = resp.json().get("task_id", "?")
            short   = str(task_id)[:8]
            print(
                f"[Seeder] Created task {short}: "
                f"{catalog_entry['task_type']} -> {executor_did} (reward={reward})"
            )
        elif resp.status_code == 404:
            print(f"[Seeder] Agent not yet registered ({executor_did[:35]}), will retry")
        else:
            print(f"[Seeder] Error {resp.status_code}: {resp.text[:120]}")
    except requests.exceptions.ConnectionError:
        print("[Seeder] Backend unreachable, retrying…")
    except Exception as exc:
        print(f"[Seeder] Unexpected error: {exc}")


def main() -> None:
    print("[Seeder] Starting up, registering seeder agent…")
    ok = register_agent_http(SEEDER_DID, "Task-Seeder", ["task_creation"])
    if not ok:
        print("[Seeder] Warning: could not register seeder — will attempt tasks anyway")
    else:
        print(f"[Seeder] Seeder registered as {SEEDER_DID}")

    print("[Seeder] Ready. Starting task creation loop (Ctrl-C to stop).\n")
    loop = 0
    worker_indices = sorted(WORKER_DIDS.keys())

    while True:
        executor_did  = WORKER_DIDS[(loop % len(worker_indices)) + 1]
        catalog_entry = random.choice(TASK_CATALOG)
        reward        = random.randint(10, 100)
        create_task(executor_did, catalog_entry, reward)
        loop += 1
        time.sleep(random.uniform(2.0, 3.0))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[Seeder] Shutting down.")
        sys.exit(0)
