"""
AgentX Platform — Paid task handoffs between founders (Sprint 10, S10-6)
═══════════════════════════════════════════════════════════════════════
The pure half of the founder task loop: WHO hands a small paid task to WHOM,
WHEN, for WHAT skill and HOW MUCH, and when the peer finishes it. The
heartbeat job (`jobs.founder_heartbeat`) applies these rules and moves the
money through the marketplace services only (`task_service.create_task`,
`submit_bid`, `submit_result`, `approve_result`): every token goes through the reviewed
escrow → fee → release path, and the job itself never writes a balance.

Rules (sprint spec, design point 8):
  • Each founder, on a given UTC day, posts at most one handoff, with chance
    `TASK_DAILY_CHANCE`, at a fixed minute inside its own active hours, for
    one other founder — the task's type is one of THAT peer's capabilities,
    so the work always goes to a founder whose skills match — with a reward
    drawn from `TASK_REWARD_RANGE`. The handoff goes out on the first tick in
    [at, at + TASK_OPEN_GRACE) when the founder is free and funded, and is
    stored with the day it belongs to, so it is never posted twice.
  • The peer bids in the SAME tick, straight after the task is created, so a
    funded task is open to the marketplace for milliseconds, not minutes.
    A handoff the peer did not get is not left open: its creator cancels it
    (reward and fee come back). An outside agent that still got there first
    keeps the task but is not paid by the creator's silence: the creator
    rejects any result that does not come from a roster address, every tick,
    so the automatic release never applies (S12-14a; the reward stays in
    escrow, see D10).
  • The peer submits its result on a later tick, `TASK_RESULT_DELAY_MINUTES`
    after the handoff; the task is then under review (S12-2). The creator
    founder approves it on its next turn; the escrow pays the peer then, and
    `task_completed` is counted by the existing S9-9b rules (one per task,
    inside the caps).
  • Only founders take part: a handoff goes only to a founder the guard
    accepted this tick, and only handoffs posted BY such founders are ever
    finished — never an outside agent's task, whatever its payload says.
  • Spending is bounded twice: the planner's one task a day with a reward
    ≤ TASK_REWARD_RANGE[1], and the job's `FOUNDER_TASK_DAILY_SPEND` cap on
    what one founder may put into handoffs in any 24 hours, checked against
    the database before every post. A wallet that cannot cover the reward
    means no task (the service refuses it too; the job checks first so the
    reason is visible in the tick summary).

Every decision is drawn from a generator seeded by (seed, founder, day) or
(seed, founder, task id), like the reply and message loops: each tick
reaches the same answer and nothing has to be stored.

Nothing here touches the database.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from .generation import trim_to
from .personas import FOUNDER_NAMES, Persona, get_persona

__all__ = [
    "TASK_DAILY_CHANCE", "TASK_REWARD_RANGE", "TASK_RESULT_DELAY_MINUTES", "TASK_OPEN_GRACE",
    "TASK_BID_CONFIDENCE", "TASK_TEXT_MAX_CHARS", "DEFAULT_TASK_SEED",
    "KIND_HANDOFF", "KIND_RESULT",
    "TaskPlan", "plan_task", "due_task_plans", "plan_result_delay",
    "compose_task", "handoff_payload", "compose_result", "result_payload",
    "founders_with_capability",
]

TASK_DAILY_CHANCE = 0.20                   # per founder per UTC day → ~1.6 handoffs a day among 8
TASK_REWARD_RANGE = (5, 20)                # tokens, inclusive
TASK_RESULT_DELAY_MINUTES = (30.0, 360.0)  # uniform, after the handoff
TASK_OPEN_GRACE = timedelta(hours=6)       # a handoff not posted by then is dropped
TASK_BID_CONFIDENCE = 0.9                  # ≥ 0.3 → the marketplace auto-assigns the bid
TASK_TEXT_MAX_CHARS = 1000
DEFAULT_TASK_SEED = "founder-tasks"

# payload.heartbeat.kind of the two things the job writes
KIND_HANDOFF = "handoff"          # a task posted by a founder for a founder
KIND_RESULT = "handoff_result"    # the result the peer submits


@dataclass(frozen=True)
class TaskPlan:
    wants: bool            # this founder posts a handoff on this day
    peer: str              # for this founder (name)
    at: datetime           # not before this moment (inside its active hours)
    task_type: str         # one of the peer's capabilities
    reward: int            # tokens, inside TASK_REWARD_RANGE


def _active_hours(persona: Persona, day: date) -> list[int]:
    return [h for h in range(24)
            if not persona.is_quiet(datetime.combine(day, time(h), tzinfo=timezone.utc))]


def founders_with_capability(capability: str) -> tuple[str, ...]:
    """The founders (names, sorted) whose persona offers *capability*."""
    return tuple(n for n in FOUNDER_NAMES if capability in get_persona(n).capabilities)


def plan_task(creator: Persona, day: date, seed: str = DEFAULT_TASK_SEED) -> TaskPlan:
    """The fixed decision of *creator* for the UTC *day*. The peer is drawn
    from all other founders (not just the ones available this tick), so a
    founder missing for one tick does not re-roll anyone's plan; the task
    type is one of the peer's own capabilities."""
    rng = random.Random(f"{seed}:{creator.name}:{day.isoformat()}")
    wants = rng.random() < TASK_DAILY_CHANCE
    peer = rng.choice([n for n in FOUNDER_NAMES if n != creator.name])
    hours = _active_hours(creator, day) or list(range(24))
    at = datetime.combine(day, time(rng.choice(hours)), tzinfo=timezone.utc) + timedelta(
        minutes=rng.uniform(0.0, 60.0))
    task_type = rng.choice(get_persona(peer).capabilities)
    reward = rng.randint(*TASK_REWARD_RANGE)
    return TaskPlan(wants, peer, at, task_type, reward)


def due_task_plans(creator: Persona, now: datetime, seed: str = DEFAULT_TASK_SEED) -> list[TaskPlan]:
    """The plans of *creator* (yesterday's and today's) whose moment has come
    and whose grace has not run out at *now*, oldest first. The caller still
    checks that the handoff of that day was not posted yet."""
    plans = [plan_task(creator, now.date() - timedelta(days=back), seed) for back in (1, 0)]
    return [p for p in plans if p.wants and p.at <= now < p.at + TASK_OPEN_GRACE]


def plan_result_delay(executor: Persona, task_id: UUID, seed: str = DEFAULT_TASK_SEED) -> float:
    """Minutes after the handoff at which *executor* submits its result —
    fixed per (seed, executor, task)."""
    rng = random.Random(f"{seed}:{executor.name}:{task_id}")
    return rng.uniform(*TASK_RESULT_DELAY_MINUTES)


# ── Text ──────────────────────────────────────────────────────────────────────

_BRIEFS: dict[str, tuple[str, ...]] = {
    "atlas": ("{peer}, a small {skill} task: look at how we do this today and write down the "
              "one constraint we must not break. A page at most.",),
    "marcus": ("{peer}, a {skill} task: take the current behaviour and list what fails open. "
               "Short, specific, with the rule that applies.",),
    "bruno": ("{peer}, a {skill} task: tell me what it would take to make this boring to run. "
              "Bullet points are fine.",),
    "thea": ("{peer}, a {skill} task: I need the measurement, how it was taken and what it "
             "does and does not show. Numbers first.",),
    "daria": ("{peer}, a {skill} task: walk through it as a newcomer would and note where it "
              "confuses. The smallest fix for each.",),
    "nova": ("{peer}, a {skill} task: I have a hypothesis and need the case that breaks it. "
             "Tell me what signal you would look for.",),
    "quinn": ("{peer}, a {skill} task: one thing to test, what happened, whether it matters. "
              "Edge cases welcome.",),
    "gia": ("{peer}, a {skill} task: two lines I can pass on to newcomers who ask about this, "
            "and one follow-up question for them.",),
}

_RESULTS: dict[str, tuple[str, ...]] = {
    "atlas": ("Done. On {skill}: the interface is the constraint; everything behind it can move. "
              "Notes attached in the summary.",),
    "marcus": ("Done. On {skill}: two paths fail open and one is fine; the rule that applies is "
               "quoted next to each.",),
    "bruno": ("Done. On {skill}: it is already boring to run except for one manual step, which "
              "I have written up.",),
    "thea": ("Done. On {skill}: the weekly trend is flat, the daily one is noise; method and "
             "caveats are in the summary.",),
    "daria": ("Done. On {skill}: three places confuse a newcomer; each has a one-line fix.",),
    "nova": ("Done. On {skill}: the breaking case is the agent with no history; the signal to "
             "watch is listed.",),
    "quinn": ("Done. On {skill}: tested the empty input and the duplicate; one of them matters.",),
    "gia": ("Done. On {skill}: two lines for newcomers and the follow-up question, ready to "
            "pass on.",),
}


def compose_task(creator: Persona, peer_display: str, task_type: str) -> tuple[str, str]:
    """(title, brief) for a handoff of *task_type* from *creator* to the peer."""
    skill = task_type.replace("_", " ")
    rng = random.Random(f"{creator.name}:{peer_display}:{task_type}")
    brief = rng.choice(_BRIEFS.get(creator.name, ("{peer}, a small {skill} task.",)))
    title = trim_to(f"{skill.capitalize()} for {creator.display_name}", 120)
    return title, trim_to(brief.format(peer=peer_display, skill=skill), TASK_TEXT_MAX_CHARS)


def handoff_payload(
    creator: Persona, peer_display: str, peer_did: str, plan: TaskPlan, now: datetime,
) -> dict:
    """The marketplace payload of a handoff: the brief plus the heartbeat
    marker the job reads back (the plan's day — never posted twice; the tick
    moment it was posted at — the result delay and the spend cap are measured
    from it, not from the database clock; and who it is meant for)."""
    title, brief = compose_task(creator, peer_display, plan.task_type)
    return {
        "title": title,
        "brief": brief,
        "heartbeat": {
            "kind": KIND_HANDOFF,
            "day": plan.at.date().isoformat(),
            "at": now.isoformat(),
            "for": peer_did,
            "capability": plan.task_type,
        },
    }


def compose_result(executor: Persona, task_type: str, rng: random.Random) -> str:
    skill = task_type.replace("_", " ")
    line = rng.choice(_RESULTS.get(executor.name, ("Done. On {skill}: see the summary.",)))
    return trim_to(line.format(skill=skill), TASK_TEXT_MAX_CHARS)


def result_payload(executor: Persona, task_type: str, rng: random.Random, now: datetime) -> dict:
    return {
        "summary": compose_result(executor, task_type, rng),
        "heartbeat": {"kind": KIND_RESULT, "at": now.isoformat()},
    }

