from __future__ import annotations

import random
import time


def execute_task(task: dict) -> dict:
    task_type = task.get("task_type", "")
    time.sleep(random.uniform(0.5, 2.0))

    if task_type == "security.audit":
        return {"status": "worker_ok", "audit_score": random.randint(88, 98)}
    if task_type == "data.pipeline":
        return {"status": "worker_ok", "records_processed": random.randint(1200, 5000)}
    if task_type == "ml.train":
        return {"status": "worker_ok", "accuracy": round(random.uniform(0.84, 0.97), 3)}
    if task_type == "infra.deploy":
        return {"status": "worker_ok", "deployment": "successful"}

    # Marketplace / generic task handler
    if task_type.startswith("marketplace.") or task_type:
        return {"status": "worker_ok", "task_type": task_type, "completed": True}

    return {"status": "worker_ok", "task_type": task_type or "generic"}
