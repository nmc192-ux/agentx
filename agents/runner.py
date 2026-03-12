import random
import time

import requests

AGENTS = [
    "did:agentx:atlas-001",
    "did:agentx:marcus-002",
    "did:agentx:nova-006",
    "did:agentx:thea-005",
    "did:agentx:bruno-003",
    "did:agentx:daria-004",
    "did:agentx:quinn-007",
    "did:agentx:gia-008",
]

API_BASE = "http://localhost:8000"
TIMEOUT = 10


def create_post(agent):
    payload = {
        "agent_id": agent,
        "type": "signal",
        "topic": "system.update",
        "content": "Autonomous agent signal",
        "confidence": 0.8,
    }
    response = requests.post(f"{API_BASE}/posts", json=payload, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def send_message(sender, receiver):
    payload = {
        "sender_agent_did": sender,
        "receiver_agent_did": receiver,
        "message": "Coordination message",
        "metadata": {"priority": "normal"},
    }
    response = requests.post(f"{API_BASE}/messages/send", json=payload, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def create_task(sender, receiver):
    payload = {
        "requester_agent_did": sender,
        "executor_agent_did": receiver,
        "task_type": "analysis.run",
        "payload": {"dataset": "sample"},
    }
    response = requests.post(f"{API_BASE}/tasks/create", json=payload, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def complete_task(task_id):
    payload = {
        "status": "COMPLETED",
        "result": {"status": "ok"},
    }
    response = requests.post(
        f"{API_BASE}/tasks/{task_id}/update",
        json=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def _pick_sender_receiver():
    sender = random.choice(AGENTS)
    receiver_choices = [agent for agent in AGENTS if agent != sender]
    receiver = random.choice(receiver_choices)
    return sender, receiver


def _maybe_complete_task(task):
    if random.random() < 0.5:
        completed = complete_task(task["task_id"])
        print(f"[task.complete] {completed['task_id']} -> {completed['status']}")


def run_agent_network():
    actions = ["post", "message", "task"]

    while True:
        sender, receiver = _pick_sender_receiver()
        action = random.choice(actions)

        try:
            if action == "post":
                post = create_post(sender)
                print(f"[post] {sender} -> {post}")
            elif action == "message":
                message = send_message(sender, receiver)
                print(f"[message] {sender} -> {receiver} :: {message['message_id']}")
            else:
                task = create_task(sender, receiver)
                print(f"[task.create] {sender} -> {receiver} :: {task['task_id']}")
                _maybe_complete_task(task)
        except requests.RequestException as exc:
            print(f"[error] action={action} sender={sender} receiver={receiver} error={exc}")
        except Exception as exc:
            print(f"[error] unexpected action={action} error={exc}")

        time.sleep(random.randint(3, 10))


if __name__ == "__main__":
    run_agent_network()
