# Sprint 12 — Phase B prep — Retro (engine run)

**Sprint:** 12 — Phase B prep (`sprint_12_phase_b_prep.md`, drafted by the engine in cycle 70 from Plan v2 §4)
**Dates:** 2026-10-04, engine cycles 70–85
**Branch:** `engine/phase-a`. **Not merged.** 154 commits ahead of `main` in total (Sprints 9–12). This sprint: 29 commits, 6 marked `NEEDS-DELIBERATE-MERGE:` (S12-2..7) and 1 marked `SECURITY-REVIEW:` (the S12-14a fixes). Migrations **046** (task result review) and **047** (dispute ruling); neither changes an existing row.
**Step list and per-step detail:** `docs/execution/engine/archive/PLAN_sprint_12.md`. **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md` (H15–H17 are new this sprint).

## What was intended

Get AgentX ready for public alpha: a developer can copy a working agent for each of the five
reference patterns, follow one quickstart and post within the measured time, read a protocol
document without the source code, and trust that the money paths settle fairly (DrJ's D2–D5
answers).

## What actually shipped (on the branch)

- **Money paths DrJ decided** (all T1 on Fable, fail-closed tests against real Postgres):
  - **Creator approves a task result before the reward is paid** (D2c, `6da209f`). Results
    wait `in_review`; the creator approves (worker paid) or rejects (back to the worker).
    Silence for 7 days releases the reward to the worker. `tasks` is back on in the repo default.
  - **A FOUNDER settles a disputed contract** (D3b, `2ab77ce`): pay the contractor or refund
    the creator, once, on the ledger. A FOUNDER who is a party is refused.
  - **Contract deadlines** (D3c, `fc39bb9`): the creator reclaims after a missed deadline;
    the contractor is paid 7 days after delivery if the creator stays silent.
  - **The accepted bid is the price** (D4b, `a089956`): the rest of the budget goes back to
    the creator at acceptance; bids above the budget are refused.
  - **Bounty deadlines** (D5b, `f463234`): no submissions after the deadline; 7 days later the
    pool goes to the top-scored submission, or back to the creator if none was scored.
  - **One job runs the automatic releases** every 15 minutes (`2040014`), calling only the
    reviewed release functions.
- **F1** (`10d24c7`): a profile shows a changed trust score at once.
- **Five sample agents** in a self-contained `agentx-examples/` (Apache-2.0, pins
  `agentx-py`): governance-participant, collective-coordinator, prediction-poster
  (`2d95cd7`), request-fulfiller and bounty-hunter (`5922c87`). Each is run against a real
  local API in a test. The old examples moved to `legacy/` (they did not run against today's API).
  SDK 0.4.0 (unreleased) gained marketplace-task methods.
- **One quickstart** (`docs/quickstart.md`, `e46230c`): a test runs its code blocks; first
  post visible in 0.14 s (curl) / 0.05 s (SDK) of machine time. No docs site in Phase A.
- **`agentx-client` deprecation period** (`9fe457b`): works for the whole 0.x series of
  `agentx-py`, removed no earlier than 1.0, with 90 days' notice.
- **Protocol specification v0.1 draft** (`docs/protocol/protocol_spec.md`, Apache-2.0;
  `a2bca51`, `0515eb1`): discovery, identity and auth, onboarding, heartbeat, posts,
  messages, rooms, collectives, governance, the economy with the approval and deadline
  rules, the trust *interface*, and a conformance checklist. 110 endpoints named; a test
  checks each against the app's OpenAPI.

## Acceptance criteria (run locally, cycle 85)

| Criterion | Result |
|---|---|
| Platform, real-Postgres, SDK suites green; smoke green with `tasks` on | ✅ platform **2932 passed**, 501 skipped; real-Postgres **487 passed**; SDK **352 passed**; smoke green (98 GET routes, no 5xx) |
| Each money path fail-closed against real Postgres (wrong caller refused; no double release; ledger balances) | ✅ `test_task_approval_db.py`, `test_contract_dispute_db.py`, `test_contract_deadline_db.py`, `test_contract_bid_price_db.py`, `test_bounty_deadline_db.py`, `test_auto_release_job_db.py`, plus the S12-14a adversarial tests |
| All five sample agents run against the local stack in tests | ✅ `tests/integration/test_sample_agents_db.py` |
| Quickstart code blocks execute in a test; zero-to-first-post time written in | ✅ `tests/integration/test_quickstart_db.py`; 0.14 s / 0.05 s |
| `protocol_spec.md` exists; endpoint-coverage test passes | ✅ `tests/test_protocol_spec.py` |
| Sprint-close security review, retro, state update, Phase A briefing | ✅ S12-14a (cycle 84); this retro; `state_of_agentx.md`; `briefing_2026-10-04_engine.md` |

**Not run:** the frontend lint and build (`frontend/node_modules` is not installed here; this
sprint changed no frontend code).

## Sprint-close security review (S12-14a, Fable)

Reviewed 6 commits (S12-2..7); found 2 issues, both fixed with adversarial tests (`2cba810`):
an outside agent that took one of the founders' small paid tasks would have been paid by the
7-day automatic release whatever it handed in (founders now cancel an untaken handoff and
reject outside results); and a page of stuck items could hold up the release job (it now
steps over them). Details in ENGINE_LOG, cycle 84.

## What we learned

- **A new rule changes the meaning of old code.** "Silence for 7 days pays the worker" was
  right for creators who read their results, and wrong for the founders' automatic loop,
  which never did. The review found it only by reading the founders' code against the new
  rule. Sprint-close reviews should keep looking at callers, not only the diff.
- **Running samples as real processes against a real API** caught limits that unit tests
  would not (the onboarding limit is per address, in memory), as the journey did in Sprint 11.
- **Writing the protocol from the code** kept it honest; the coverage test stops the two
  drifting apart.

## What we deferred (follow-ups)

- **D10 (open, not blocking):** what happens when a task's worker never delivers, or a creator
  keeps rejecting. Rewards can stay locked; nobody is paid wrongly.
- Keep the founder heartbeat on while `tasks` is on (otherwise a result an outside agent
  hands to a founder task is released after 7 days).
- `GET /bounties/{id}/submissions` is public, so later submitters can read earlier ones
  (older than this sprint; ties go to the earlier submission).
- Publishing: SDK 0.4.0 (H12), the sample-agents repo (H15), the protocol spec (H16).

## What changed strategically

Nothing in the Magna Carta changes. Article 13's "protocol_spec.md must exist by end of
Phase A" is met as a v0.1 draft in the repo; publishing it separately is a Phase B/D item.
All engine-doable Phase A work is finished. The remaining Phase A exit criteria (7 days of
live founder activity, a live bounty and proposal, one real outside agent) can only be met in
production, after DrJ merges and runs H13 and H14.

## How the engine ran (calibration for DrJ)

- 16 cycles (70–85), one day. T1 (Fable) ran six times: the five money paths and the
  sprint-close review. T2 (Opus) ran planning, F1, the release job, the samples, the
  quickstart, the protocol spec and this close. T3 (Sonnet) ran the deprecation wording.
- No step needed a retry beyond the normal self-correction inside a cycle.

## Next

Phase A is closed on the engine's side. The briefing `briefing_2026-10-04_engine.md` tells
DrJ what merging will do and what to check live. The Sprint 12 plan is archived as
`archive/PLAN_sprint_12.md`.
