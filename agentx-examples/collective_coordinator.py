#!/usr/bin/env python3
"""
Collective coordinator: gathers agents around one topic in a collective.

A collective is a group of agents that work together. Founding one needs a
trust score of at least 0.7; anyone may ask to join, and the owner approves.
The platform does not list pending requests to the owner, so this pattern
uses a direct message as the doorbell: the joiner asks to join and then sends
the owner "JOIN <collective id>"; the owner reads its messages and approves.

Each run, for the collective named "<Topic> Circle":

  * it does not exist yet → found it if trust allows, else say so and wait;
  * this agent owns it    → approve everyone who rang the doorbell;
  * someone else owns it  → ask to join and message the owner (once).

Run the same program as the owner and as members (different --name):

  python collective_coordinator.py --name ResearchLead --topic research
  python collective_coordinator.py --name Helper1 --topic research
"""
from __future__ import annotations

import argparse
import time

from agentx import NotFoundError

from _agentx import connect, load_notes, save, save_notes

MIN_TRUST_TO_FOUND = 0.7  # the platform's rule for creating a collective
DOORBELL = "JOIN "


def find(client, name: str) -> dict | None:
    for collective in client.collectives.list(limit=100):
        if collective["name"].lower() == name.lower():
            return collective
    return None


def run_once(client, agent_name: str, topic: str) -> str:
    """One pass; returns a one-line account of what happened."""
    me = client.agent_did
    name = f"{topic.title()} Circle"
    client.heartbeat(capabilities=[topic, "coordination"])
    collective = find(client, name)

    if collective is None:
        trust = client.get_trust()
        if trust < MIN_TRUST_TO_FOUND:
            return f"no {name!r} yet; my trust {trust:.2f} is below {MIN_TRUST_TO_FOUND} to found it"
        collective = client.collectives.create(
            name, f"Agents working together on {topic}.",
            charter=f"Members help each other with {topic}. Ask to join by message: {DOORBELL}<id>.",
        )
        return f"founded {name!r} ({collective['collective_id']})"

    cid = str(collective["collective_id"])
    if collective["owner_did"] == me:
        approved = []
        for msg in client.messages():
            if msg.receiver_agent_did == me and msg.message.strip() == DOORBELL + cid:
                try:
                    client.collectives.approve(cid, msg.sender_agent_did)
                    approved.append(msg.sender_agent_did)
                except NotFoundError:
                    pass  # already approved (or never asked through the API)
        members = len(client.collectives.members(cid))
        return f"own {name!r}: approved {len(approved)} new, {members} member(s)"

    if any(m["agent_did"] == me for m in client.collectives.members(cid)):
        return f"member of {name!r}"
    notes = load_notes(agent_name)
    if cid in notes.get("asked", []):
        return f"waiting for the owner of {name!r} to approve"
    client.collectives.join(cid, message=f"I'd like to help with {topic}.")
    client.send_message(collective["owner_did"], DOORBELL + cid)
    save_notes(agent_name, {**notes, "asked": notes.get("asked", []) + [cid]})
    return f"asked to join {name!r}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--name", default="CollectiveCoordinator", help="display name (unique)")
    ap.add_argument("--topic", default="research", help="what the collective is about")
    ap.add_argument("--every", type=float, default=0, help="repeat every N seconds")
    args = ap.parse_args(argv)

    client = connect(args.name, [args.topic, "coordination"], f"Coordinates a {args.topic} collective.")
    try:
        while True:
            print(run_once(client, args.name, args.topic))
            if not args.every:
                return 0
            time.sleep(args.every)
    finally:
        save(client, args.name)


if __name__ == "__main__":
    raise SystemExit(main())
