# Sprint 21 — Bounties end to end, trust that notices — Retro (engine run)

**Sprint:** 21 (`sprint_21_bounties_trust.md`, planned by the engine in cycle 196; second sprint of Phase C, `phase_c_plan.md`)
**Dates:** 2026-10-15, engine cycles 196–206
**Branch:** `engine/phase-b`. **Not merged.** After this close the branch is 184+ commits ahead of `origin/main` (Sprints 13–21 and the Neon/free-tier work), 34 marked `SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:` (3 from this sprint). **No migration.**
**Step list:** `docs/execution/engine/PLAN.md` (BT-0 to BT-8). **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md` (new: H39, H40, H41).

## What was intended

Make bounties and paid work finish properly (no tokens stuck for ever when a worker never
delivers or a bounty has no deadline), make trust notice paid work, and show newcomers that
bounties really pay. Everything ships **off**, so 1 Nov launches exactly as rehearsed.

## What actually shipped (on the branch, switched off)

- **BT-1 Task work deadline** (`40f2cd9`, Fable, `SECURITY-REVIEW:`). `POST /tasks/{id}/reclaim`:
  the creator takes the escrow back once the worker has had `TASK_WORK_DAYS` (database clock,
  restarting at each rejected result) and nothing is pending. Row-locked, refunds once, a late
  result is refused. `TASK_WORK_DAYS=0` (off) by default; H39 switches it on with 7. D10 (b).
- **BT-2 Bounties with no deadline** (`1561114`, Fable, `SECURITY-REVIEW:`). A bounty stored
  without a deadline is treated as if it had one `LEGACY_BOUNTY_DAYS` after posting (closes to
  entries, then auto-release or refund 7 days later). No row written. Off (0) by default; H40.
  `DEFAULT_BOUNTY_DAYS` is now a setting (30).
- **BT-3 Trust from paid work** (`1984f0c`, Opus, `SECURITY-REVIEW:`). `bounty_won` +0.05,
  `contract_completed` +0.05, `deadline_missed` −0.05, each written only when the ledger shows
  the matching payout or refund, after commit, under the existing caps and dedupe.
- **BT-4 Showcase API** (`570951b`). `GET /markets/bounties/showcase`: open bounties, paid in
  the last 30 days, top 10 earners; ledger amounts; cached 60 s; 404 unless
  `ECONOMY_SHOWCASE_ENABLED`.
- **BT-5 Showcase page** (`07523c9`). `/markets/bounties` behind `NEXT_PUBLIC_FEATURE_ECONOMY`.
- **BT-6 Client parity** (`81f42dd`, fix `35726aa`). TS `contracts`, `tasks.reclaim`; Python
  `reclaim_task`, `contracts.reclaim`; MCP `agentx_create_bounty`,
  `agentx_submit_bounty_solution`, `agentx_reclaim_task`. Versions unchanged.
- **BT-7 Economy journey part two** (`cfc6234`). Reclaim, auto-release by the real job, and the
  winner's trust events, all checked against the ledger.
- **BT-8a Security review** (`c7f6dc1`, Fable). Reviewed 1 commit, found 0 issues, 12 tests.
- **BT-8 Close** (this commit). H41 "switch on the bounty showcase" added for after 1 Nov.

## Acceptance criteria (run locally, cycle 206, head `3beb81b`)

| Criterion | Result |
|---|---|
| Task reclaim refused too early, with a result pending, for anyone but the creator, and twice; one refund under 10 concurrent calls | ✅ `test_task_reclaim.py` + `integration/test_task_reclaim_db.py --db` |
| A NULL-deadline bounty past `DEFAULT_BOUNTY_DAYS + AUTO_RELEASE_DAYS` released, a younger one not, `deadline` column untouched | ✅ `test_legacy_bounty_deadline.py`, `integration/test_legacy_bounty_db.py`, `test_auto_release_job_db.py`, `test_bounty_deadline_db.py` |
| One trust event per payout (manual and automatic racing), none for self-dealing or a young counterparty, daily cap holds | ✅ `test_paid_work_trust.py` + `integration/test_paid_work_trust_db.py --db` |
| Showcase 404 when off; numbers match the ledger; no wallet ids or submission content | ✅ `test_bounty_showcase.py` + `integration/test_bounty_showcase_db.py --db` |
| (all of the above together) | ✅ unit **103 passed**, `--db` **100 passed** |
| `launch_rehearsal.py` 9/9 off, 10/10 `--economy` | ✅ **PASSED 10/10** (9 launch checks with everything off, then the 10-step economy journey in its own API) |
| SDK, TS, MCP suites green | ✅ Python SDK **513 passed**; TS build OK + **162 passed**; MCP **101 passed** |

## Sprint-close security review

Fable, cycle 205: **reviewed 1 commit (BT-3), found 0 issues.** BT-1 and BT-2 were built on
Fable directly. 12 adversarial tests added (dispute rulings are neither completions nor missed
deadlines, hand-flipped statuses and forged reward rows earn nothing, a worker who is also the
creator loses nothing, the ledger types each reporter accepts are pinned).

**Known limits, not holes:** trust farming through a sock-puppet creator costs the platform fee
and is bounded by 0.10 a day and one event per pair per day (same as `task_completed` since
Sprint 9); a contract assigned just before its own deadline leaves no time (Sprint 12, D3c),
and the new −0.05 rides on that.

## What went well

- The three steps that move tokens or decide when pools are released were built on Fable;
  the Opus steps only called them. The review found nothing.
- The economy journey now proves every way a token leaves escrow (manual payout, paid task,
  reclaim, automatic release) against the ledger, from an empty database, in one command.

## What didn't

- Cycle 202 changed MCP calls without running `platform/tests/a2a` (route pins); the engine's
  own test run caught it and cycle 203 fixed it. Lesson recorded: SDK/MCP changes also run
  `platform/tests/a2a`.
- "Delivered by the deadline" for `sla_compliance` (spec line under BT-3) was not built: the
  value is display-only today. Left for later.
- The fairer faucet rule H38 mentions ("planned for Sprint 21") was not in this sprint's spec
  and was not built; it stays a backlog item, only needed if H38's daily check shows the faucet
  drained.
- No UI unit-test suite exists; BT-5 was checked by build, lint and a render against a mock API.

## Decisions made by the engine (reversible)

- `TASK_WORK_DAYS` and `LEGACY_BOUNTY_DAYS` default to 0 = off (spec said 7 and 30; the Phase C
  rule "every feature off" wins). H39/H40 give the recommended values.
- The task work clock restarts at each rejected result.
- Showcase leaves out payouts to the bounty's own creator and suspended agents; top earners count
  dispute releases (money earned), trust does not.
- No `contracts.get` in the clients (the API has no such route).

## Next

Sprint 22 — collectives a newcomer can make in five minutes (`phase_c_plan.md`): decompose next
cycle. Nothing from Sprint 21 changes 1 Nov unless DrJ does H39, H40 or H41 (and D13 says
Phase C work rides along switched off).
