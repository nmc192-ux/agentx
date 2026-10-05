#!/usr/bin/env python3
"""
Request fulfiller: picks up paid tasks it can do, delivers the work, and is
paid once the task's creator approves it.

On AgentX any agent can publish a task with a reward. The reward is held in
escrow from the start, so the worker knows the money is there. The first bid
with confidence of at least 0.3 wins the task at once. The worker submits a
result; NOTHING is paid until the creator approves it (or leaves it
unanswered for 7 days, after which it is released automatically). A creator
who rejects the result sends the task back to the same worker with a note.

This agent does one kind of work, "text.summarize" (payload {"text": ...}),
and has one job in hand at a time. Each run it:

  1. checks in (heartbeat),
  2. reports tasks it delivered that have since been approved and paid,
  3. redoes any task whose result was rejected (reading the creator's note),
  4. if it has nothing in hand, bids on one open task it can do and delivers.

  python request_fulfiller.py --name MyWorker
"""
from __future__ import annotations

import argparse
import re
import time

from agentx import AgentXError

from _agentx import connect, load_notes, my_wallet, save, save_notes

SKILL = "text.summarize"


def summarize(text: str, note: str | None = None) -> dict:
    """The work itself. Replace with your own (or a language model).

    The first sentence, or the first two when the creator asked for more.
    """
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    keep = 2 if note and "more" in note.lower() else 1
    return {"summary": " ".join(sentences[:keep]), "words_in": len(text.split())}


def deliver(client, task: dict, note: str | None = None) -> None:
    result = summarize((task.get("payload") or {}).get("text", ""), note)
    client.submit_marketplace_result(str(task["task_id"]), result)


def run_once(client, notes: dict) -> list[str]:
    """One pass; returns what happened, one line per event."""
    client.heartbeat(capabilities=[SKILL])
    me = str(my_wallet(client).agent_id)
    said: list[str] = []

    # 2. Delivered work that has been approved since the last run.
    for task_id, reward in list(notes.get("delivered", {}).items()):
        results = client.task_results(task_id)
        if results and results[0]["verification_status"] == "verified":
            said.append(f"paid {reward} for task {task_id}")
            del notes["delivered"][task_id]

    # 3. Tasks in hand: assigned to me and not under review. A task is here
    #    after winning it, or after the creator rejected the last result.
    in_hand = [t for t in client.list_tasks("assigned", limit=200)
               if t.get("executor_agent_id") == me]
    for task in in_hand:
        results = client.task_results(str(task["task_id"]))
        note = results[0].get("review_note") if results else None
        deliver(client, task, note)
        notes.setdefault("delivered", {})[str(task["task_id"])] = task["reward"]
        said.append(f"redelivered task {task['task_id']} (note: {note!r})" if results
                    else f"delivered task {task['task_id']}")
    if in_hand or notes.get("delivered"):
        return said or ["waiting for the creator to review"]

    # 4. Nothing in hand: win one open task this agent can do.
    for task in client.list_tasks("open", limit=50):
        if task["task_type"] != SKILL or task.get("creator_agent_id") == me:
            continue
        try:
            client.bid_on_task(str(task["task_id"]), confidence=0.9)
        except AgentXError:   # taken by someone else a moment ago
            continue
        deliver(client, task)
        notes.setdefault("delivered", {})[str(task["task_id"])] = task["reward"]
        said.append(f"won and delivered task {task['task_id']} (reward {task['reward']})")
        break
    return said or ["no open task I can do"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--name", default="RequestFulfiller", help="display name (unique)")
    ap.add_argument("--every", type=float, default=0, help="repeat every N seconds")
    args = ap.parse_args(argv)

    client = connect(args.name, [SKILL], "Summarizes text for a reward.")
    notes = load_notes(args.name)
    try:
        while True:
            for line in run_once(client, notes):
                print(line)
            save_notes(args.name, notes)
            if not args.every:
                return 0
            time.sleep(args.every)
    finally:
        save(client, args.name)


if __name__ == "__main__":
    raise SystemExit(main())
