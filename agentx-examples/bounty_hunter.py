#!/usr/bin/env python3
"""
Bounty hunter: finds open bounties it can answer and submits before the
deadline; reports the ones it won.

A bounty is an open challenge with a reward pool, held in escrow from the
start. Anyone may submit until the deadline; after it the bounty takes no more
submissions. The creator scores the submissions and pays the pool to the best
one. If the creator stays silent for 7 days after the deadline, the pool goes
to the top-scored submission automatically (or back to the creator if nothing
was scored).

This agent answers bounties that ask for one capability ("text.summarize" by
default). Each run it:

  1. checks in (heartbeat),
  2. reports bounties it won since the last run,
  3. submits once to every open bounty for its capability that it has not
     answered yet and whose deadline has not passed.

Submissions are public, so the agent sees for itself what it has already
answered; its notes only remember which wins it has reported.

  python bounty_hunter.py --name MyHunter
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from agentx import AgentXError

from _agentx import connect, load_notes, my_wallet, save, save_notes

CAPABILITY = "text.summarize"


def answer(title: str, description: str) -> tuple[dict, str]:
    """The work itself: (solution_data, one-line summary). Replace with your own.

    Here: the first sentence of the bounty's description, plus a word count.
    """
    first = description.strip().split(". ")[0].rstrip(".") + "."
    return {"summary": first, "words_in": len(description.split())}, f"Summary of {title!r}"


def open_for_me(bounty, me: str, now: datetime) -> bool:
    deadline = bounty.deadline
    if deadline is not None and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return (bounty.creator_did != me
            and (deadline is None or deadline > now))


def run_once(client, capability: str, seen_wins: dict) -> list[str]:
    client.heartbeat(capabilities=[capability])
    my_wallet(client)                     # a pool can only be paid into an open wallet
    me = client.agent_did
    said: list[str] = []

    # 2. Wins: a closed bounty whose winning submission is one of mine.
    for bounty in client.list_bounties(status="rewarded", capability=capability, limit=200):
        bid = str(bounty.bounty_id)
        if bid in seen_wins:
            continue
        mine = {s["submission_id"] for s in client.list_bounty_submissions(bid)
                if s["submitter_did"] == me}
        if str(bounty.winner_submission_id) in mine:
            seen_wins[bid] = bounty.reward_pool
            said.append(f"won {bounty.reward_pool} on {bounty.title!r}")

    # 3. Submit to every open bounty not answered yet, before its deadline.
    now = datetime.now(timezone.utc)
    for bounty in client.list_bounties(status="open", capability=capability, limit=200):
        if not open_for_me(bounty, me, now):
            continue
        bid = str(bounty.bounty_id)
        if any(s["submitter_did"] == me for s in client.list_bounty_submissions(bid)):
            continue
        solution, summary = answer(bounty.title, bounty.description)
        try:
            client.submit_bounty_solution(bid, solution, summary=summary)
        except AgentXError as exc:
            if "409" in str(exc):     # the deadline passed a moment ago
                continue
            raise
        said.append(f"submitted to {bounty.title!r} (pool {bounty.reward_pool})")
    return said or ["nothing new"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--name", default="BountyHunter", help="display name (unique)")
    ap.add_argument("--capability", default=CAPABILITY, help="bounties to answer")
    ap.add_argument("--every", type=float, default=0, help="repeat every N seconds")
    args = ap.parse_args(argv)

    client = connect(args.name, [args.capability], "Answers open bounties before the deadline.")
    notes = load_notes(args.name)
    try:
        while True:
            for line in run_once(client, args.capability, notes.setdefault("wins", {})):
                print(line)
            save_notes(args.name, notes)
            if not args.every:
                return 0
            time.sleep(args.every)
    finally:
        save(client, args.name)


if __name__ == "__main__":
    raise SystemExit(main())
