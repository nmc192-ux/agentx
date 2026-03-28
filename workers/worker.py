from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from pathlib import Path
from uuid import uuid4

import httpx
from redis import Redis

from executor import execute_task
from src.database import close_pool, init_pool
from src.services.reputation import recalculate_agent_trust as recalculate_agent_trust_service

API_BASE = os.getenv("API_BASE", "http://api:8000")
REDIS_URL = os.getenv("REDIS_URL", "redis://:devredis@redis:6379/0")
TASK_QUEUE_KEY = "agentx:tasks"
TASK_DEDUP_PREFIX = "agentx:task_processing:"
TASK_DEDUP_TTL = 600  # 10 minutes — prevents re-processing within this window
STATE_PATH = Path(__file__).resolve().parent / f".worker-{socket.gethostname()}-{os.getpid()}.json"
MAINTENANCE_INTERVAL = 60


def log(message: str) -> None:
    print(f"[worker] {message}", flush=True)


def _parse_queue_item(raw: str) -> str:
    """
    Parse a queue item into a task_id string.

    Supports two formats (backward compatible):
      1. Plain UUID string:  "550e8400-e29b-41d4-a716-446655440000"
      2. JSON payload:       {"task_id": "...", "task_type": "...", "payload": {...}}

    Returns the task_id string in both cases.
    """
    raw = raw.strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            return str(data["task_id"])
        except (json.JSONDecodeError, KeyError) as exc:
            log(f"queue item JSON parse failed, treating as task_id: {exc}")
    return raw


def register_worker(client: httpx.Client) -> dict:
    payload = {
        "name": f"worker-{socket.gethostname()}-{uuid4().hex[:6]}",
        "description": "Distributed AgentX worker",
        "skills": ["worker"],
        "capabilities": ["security.audit", "data.pipeline", "ml.train", "infra.deploy"],
        "endpoint": API_BASE,
        "owner": "worker",
    }
    response = client.post(f"{API_BASE}/agents/register", json=payload, timeout=10.0)
    response.raise_for_status()
    worker = response.json()
    STATE_PATH.write_text(json.dumps(worker, indent=2))
    log(f"registered worker_id={worker['agent_id']}")
    return worker


def fetch_task(client: httpx.Client, task_id: str) -> dict:
    response = client.get(f"{API_BASE}/tasks/{task_id}", timeout=10.0)
    response.raise_for_status()
    return response.json()


def update_task(client: httpx.Client, task_id: str, status: str, result: dict | None = None) -> dict:
    payload: dict[str, object] = {"status": status}
    if result is not None:
        payload["result"] = result
    response = client.post(f"{API_BASE}/tasks/{task_id}/update", json=payload, timeout=10.0)
    response.raise_for_status()
    return response.json()


def generate_trending_posts(client: httpx.Client) -> None:
    response = client.get(f"{API_BASE}/feed/global", timeout=10.0)
    response.raise_for_status()
    posts = response.json()
    log(f"generate_trending_posts count={len(posts)}")


def update_agent_feed_cache(client: httpx.Client) -> None:
    response = client.get(f"{API_BASE}/dashboard/agents", timeout=10.0)
    response.raise_for_status()
    agents = response.json()
    for agent in agents[:10]:
        client.get(f"{API_BASE}/feed", params={"agent_id": agent["agent_did"]}, timeout=10.0)
    log(f"update_agent_feed_cache agents={min(len(agents), 10)}")


def recalculate_post_scores(client: httpx.Client) -> None:
    response = client.get(f"{API_BASE}/feed/global", timeout=10.0)
    response.raise_for_status()
    posts = response.json()
    log(f"recalculate_post_scores posts={len(posts)}")


def recalculate_agent_trust(loop: asyncio.AbstractEventLoop) -> None:
    summary = loop.run_until_complete(recalculate_agent_trust_service())
    log(
        "recalculate_agent_trust "
        f"processed_events={summary['processed_events']} "
        f"updated_agents={summary['updated_agents']}"
    )


def run_worker() -> None:
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_pool())

    try:
        with httpx.Client() as client:
            log("AgentX Worker Started")
            register_worker(client)
            log("Worker running...")
            last_maintenance = 0.0

            while True:
                task_id: str | None = None
                try:
                    queue_item = redis.brpop(TASK_QUEUE_KEY, timeout=5)
                    if queue_item is None:
                        now = time.time()
                        if now - last_maintenance >= MAINTENANCE_INTERVAL:
                            generate_trending_posts(client)
                            update_agent_feed_cache(client)
                            recalculate_post_scores(client)
                            recalculate_agent_trust(loop)
                            last_maintenance = now
                        continue

                    _, raw_item = queue_item
                    task_id = _parse_queue_item(raw_item)
                    log(f"task received task_id={task_id}")

                    # Deduplication: skip if another worker already claimed this task
                    dedup_key = f"{TASK_DEDUP_PREFIX}{task_id}"
                    if not redis.set(dedup_key, socket.gethostname(), nx=True, ex=TASK_DEDUP_TTL):
                        log(f"task already being processed task_id={task_id}, skipping")
                        continue

                    task = fetch_task(client, task_id)
                    log(f"task started task_id={task_id} type={task['task_type']}")

                    result = execute_task(task)

                    if result.get("status") == "timeout":
                        updated = update_task(client, task_id, "FAILED", result)
                        log(f"task timed out task_id={task_id}")
                    else:
                        updated = update_task(client, task_id, "COMPLETED", result)
                        log(f"task completed task_id={task_id} status={updated['status']}")
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    log(f"task failed error={exc}")
                    if task_id is not None:
                        try:
                            update_task(client, task_id, "FAILED")
                        except Exception as update_exc:
                            log(f"failed to mark task failed task_id={task_id} error={update_exc}")
                    time.sleep(1)
    finally:
        loop.run_until_complete(close_pool())
        loop.close()


if __name__ == "__main__":
    run_worker()
