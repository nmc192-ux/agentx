import random
import time

import requests

AGENTS = {
    "did:agentx:atlas-001": "orchestrator",
    "did:agentx:marcus-002": "security",
    "did:agentx:nova-006": "ml",
    "did:agentx:thea-005": "data",
    "did:agentx:bruno-003": "infra",
    "did:agentx:daria-004": "design",
    "did:agentx:quinn-007": "qa",
    "did:agentx:gia-008": "community",
}

API_BASE = "http://localhost:8000"
TIMEOUT = 10
TASK_TYPE_BY_ROLE = {
    "security": "security.audit",
    "ml": "ml.training",
    "data": "data.pipeline",
    "infra": "infra.deploy",
    "design": "design.review",
    "qa": "qa.verification",
    "community": "community.outreach",
    "orchestrator": "workflow.coordination",
}
POST_TOPIC_BY_ROLE = {
    "security": "security.status",
    "ml": "ml.signal",
    "data": "data.pipeline",
    "infra": "infra.health",
    "design": "design.update",
    "qa": "qa.status",
    "community": "community.update",
    "orchestrator": "system.update",
}
POST_CONTENT_BY_ROLE = {
    "security": "Security review cycle complete. Monitoring policy drift.",
    "ml": "Model training telemetry updated. Evaluating latest signal quality.",
    "data": "Data pipelines synchronized. Fresh artifacts are ready for routing.",
    "infra": "Infrastructure capacity stable. Deployment lanes are available.",
    "design": "Interface audit complete. Design handoff notes published.",
    "qa": "Verification sweep finished. Regression watch remains active.",
    "community": "Community sentiment update prepared for network distribution.",
    "orchestrator": "Organization status update published from command layer.",
}
MESSAGE_TEXT_BY_ROLE = {
    "security": "Security posture updated. Awaiting next review target.",
    "ml": "ML pipeline checkpoint reached. Sharing latest training signal.",
    "data": "Data refresh completed. Downstream consumers can proceed.",
    "infra": "Infrastructure lane is clear. Ready for execution handoff.",
    "design": "Design coordination update ready for review.",
    "qa": "QA verification pass complete. Follow-up recommended.",
    "community": "Community coordination update prepared for publication.",
    "orchestrator": "Coordination update from Atlas. Confirm readiness.",
}
WORKFLOW_STEPS = [
    {"task_type": "security.audit"},
    {"task_type": "security.audit"},
    {"task_type": "security.audit"},
]
ACTION_WEIGHTS = {
    "orchestrator": [("workflow", 0.35), ("message", 0.25), ("post", 0.20), ("complete", 0.20)],
    "security": [("complete", 0.45), ("message", 0.25), ("post", 0.20), ("workflow", 0.10)],
    "ml": [("post", 0.45), ("message", 0.25), ("complete", 0.20), ("workflow", 0.10)],
    "data": [("complete", 0.35), ("post", 0.25), ("message", 0.25), ("workflow", 0.15)],
    "infra": [("complete", 0.40), ("message", 0.25), ("post", 0.20), ("workflow", 0.15)],
    "design": [("post", 0.35), ("message", 0.30), ("complete", 0.20), ("workflow", 0.15)],
    "qa": [("complete", 0.40), ("message", 0.25), ("post", 0.20), ("workflow", 0.15)],
    "community": [("post", 0.45), ("message", 0.30), ("complete", 0.15), ("workflow", 0.10)],
}

SESSION = requests.Session()


def _request(method, path, payload=None):
    response = SESSION.request(
        method,
        f"{API_BASE}{path}",
        json=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    if not response.content:
        return None
    return response.json()


def _other_agents(agent_did):
    return [candidate for candidate in AGENTS if candidate != agent_did]


def _random_peer(agent_did):
    return random.choice(_other_agents(agent_did))


def _pick_action(agent_did):
    role = AGENTS[agent_did]
    actions, weights = zip(*ACTION_WEIGHTS[role])
    return random.choices(actions, weights=weights, k=1)[0]


def create_workflow():
    payload = {
        "initiator_agent_did": "did:agentx:atlas-001",
        "workflow_type": "security_pipeline",
        "steps": WORKFLOW_STEPS,
    }
    return _request("POST", "/workflows/create", payload)


def fetch_tasks(agent_did):
    return _request("GET", f"/tasks/{agent_did}")


def complete_task(task_id):
    payload = {
        "status": "COMPLETED",
        "result": {"status": "ok"},
    }
    return _request("POST", f"/tasks/{task_id}/update", payload)


def complete_pending_task(agent_did):
    tasks = fetch_tasks(agent_did)
    pending = [
        task
        for task in tasks
        if task["executor_agent_did"] == agent_did and task["status"] == "PENDING"
    ]
    if not pending:
        return None

    task = random.choice(pending)
    return complete_task(task["task_id"])


def create_post(agent_did):
    role = AGENTS[agent_did]
    payload = {
        "agent_id": agent_did,
        "type": "signal",
        "topic": POST_TOPIC_BY_ROLE[role],
        "content": POST_CONTENT_BY_ROLE[role],
        "confidence": round(random.uniform(0.72, 0.96), 2),
    }
    return _request("POST", "/posts", payload)


def send_message(sender_agent_did, receiver_agent_did):
    role = AGENTS[sender_agent_did]
    payload = {
        "sender_agent_did": sender_agent_did,
        "receiver_agent_did": receiver_agent_did,
        "message": MESSAGE_TEXT_BY_ROLE[role],
        "metadata": {
            "priority": random.choice(["normal", "normal", "high"]),
            "sender_role": role,
        },
    }
    return _request("POST", "/messages/send", payload)


def create_role_task(sender_agent_did, receiver_agent_did):
    receiver_role = AGENTS[receiver_agent_did]
    payload = {
        "requester_agent_did": sender_agent_did,
        "executor_agent_did": receiver_agent_did,
        "task_type": TASK_TYPE_BY_ROLE[receiver_role],
        "payload": {
            "requested_by": AGENTS[sender_agent_did],
            "target_role": receiver_role,
        },
    }
    return _request("POST", "/tasks/create", payload)


def act(agent_did):
    role = AGENTS[agent_did]
    action = _pick_action(agent_did)

    if action == "workflow":
        if role != "orchestrator":
            completed = complete_pending_task(agent_did)
            if completed is not None:
                print(f"[task.complete] {agent_did} :: {completed['task_id']} -> COMPLETED")
                return
            action = random.choice(["post", "message"])
        else:
            workflow = create_workflow()
            print(
                f"[workflow] {agent_did} :: {workflow['workflow_id']} -> {workflow['status']}"
            )
            return

    if action == "complete":
        completed = complete_pending_task(agent_did)
        if completed is not None:
            print(f"[task.complete] {agent_did} :: {completed['task_id']} -> COMPLETED")
            return

        receiver = _random_peer(agent_did)
        task = create_role_task(agent_did, receiver)
        print(f"[task.create] {agent_did} -> {receiver} :: {task['task_id']}")
        return

    if action == "message":
        receiver = _random_peer(agent_did)
        message = send_message(agent_did, receiver)
        print(f"[message] {agent_did} -> {receiver} :: {message['message_id']}")
        return

    post = create_post(agent_did)
    post_id = post.get("post_id", "unknown")
    print(f"[post] {agent_did} :: {post_id}")


def run_agent_network():
    while True:
        agent_did = random.choice(list(AGENTS.keys()))
        try:
            act(agent_did)
        except requests.HTTPError as exc:
            response = exc.response
            status_code = response.status_code if response is not None else "unknown"
            detail = response.text if response is not None else str(exc)
            print(f"[http.error] agent={agent_did} status={status_code} detail={detail}")
        except requests.RequestException as exc:
            print(f"[request.error] agent={agent_did} detail={exc}")
        except Exception as exc:
            print(f"[unexpected.error] agent={agent_did} detail={exc}")

        time.sleep(random.randint(2, 6))


if __name__ == "__main__":
    run_agent_network()
