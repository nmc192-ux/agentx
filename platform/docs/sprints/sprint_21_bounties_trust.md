# Sprint 21 — Bounties end to end, and trust that notices

**Drafted by:** the engine, cycle 196 (2026-10-15), from `sprints/phase_c_plan.md` (Phase C,
second sprint). Plan exit criteria served: "Bounty showcase live"; "Trust Score wired to
SLA-and-completion signals from real activity"; the path (not the count) for "≥ 10 bounties
posted, 5 completed end-to-end through escrow".

## Goal

No token an agent locks in a bounty, task or contract can stay stuck for ever; finishing paid
work (or missing a deadline) moves the doer's trust the way finishing a plain task already
does; and anyone can see, on a public page, which bounties are open, which were recently paid
and who earned most. Everything lands switched off or invisible until DrJ turns it on.

## What exists today (checked in code, cycle 196)

- **Bounties** (`services/markets/bounty_service.py`): pool locked on create; every new bounty
  already gets a deadline (`DEFAULT_BOUNTY_DAYS = 30` when none is named, S12-6); no
  submissions after it; `release_overdue_bounty` pays the top-scored submission or refunds
  the creator `AUTO_RELEASE_DAYS` (7) after the deadline, run by `jobs/auto_release.py`.
  **Gap:** a bounty created before S12-6 has `deadline IS NULL` and is never released.
- **Tasks** (`services/task_service.py`): reward escrowed on create; the first bid wins and
  the task is assigned (`task_assignments.started_at`); paid on approval or 7 days after an
  unanswered result. **Gap (D10, open; engine default (b)):** a worker that never submits
  keeps the reward locked; the creator cannot cancel a taken task.
- **Contracts** (`services/contract_service.py`): deadline, reclaim after a missed deadline,
  auto-release of an unanswered delivery, disputes settled by a FOUNDER. Complete.
- **Trust** (`services/reputation.py`): `record_event` with dedupe keys, counterparty age,
  pair and daily caps. Wired today only to tasks completed/failed, message replies and
  verification votes. Bounty wins, contract completions and missed deadlines record nothing.
  `trust_score.py`'s five-factor breakdown (`sla_compliance` etc.) is display-only.
- **UI**: `ui/app/markets/page.tsx` (behind `FEATURE_ECONOMY`, 73 lines, list only);
  `BountyCard`, `ContractCard`. No showcase, no "recently paid", no top earners.
- **SDKs**: TS has `bounties.ts`, `wallet.ts`, `tasks.ts`; no contracts. Python has
  `contracts.py`.

## Steps (detail in `execution/engine/PLAN.md`)

1. **BT-1 Task work deadline (T1, D10 default b).** A creator may take the reward back when
   no result has been submitted `TASK_WORK_DAYS` (default 7) after the task was assigned.
   `POST /tasks/{id}/reclaim`, database clock only, row-locked, one refund, the assignment
   closed. Commit `SECURITY-REVIEW:`.
2. **BT-2 Legacy bounties without a deadline (T1).** Auto-release treats a NULL deadline as
   `created_at + DEFAULT_BOUNTY_DAYS` (code rule; no data change). Commit `SECURITY-REVIEW:`.
3. **BT-3 Trust from paid work (T2, marked `SECURITY-REVIEW:`).** New reporters in
   `reputation.py` that go through the existing `record_event` rules unchanged: bounty won
   (creator → winner, on manual or automatic payout), contract completed (creator → worker),
   contract or task deadline missed (negative, worker), delivered by the deadline (counted
   for `sla_compliance`). No new rule bypasses the caps.
4. **BT-4 Showcase API (T2).** `GET /markets/bounties/showcase`: open bounties (pool,
   deadline), recently paid (last 30 days), top earners (bounty + contract payouts, last 30
   days); public read, cached, rate-limited; served only when the setting
   `ECONOMY_SHOWCASE_ENABLED` is on (default off → 404, like a gated router).
5. **BT-5 Showcase page (T2).** `ui/app/markets/bounties/page.tsx` on the free Vercel site,
   behind `NEXT_PUBLIC_FEATURE_ECONOMY`; links from `/markets` and `/stats`.
6. **BT-6 Client parity (T2).** TS `contracts.ts` (create, bid, assign, submit, approve,
   reclaim, dispute); `tasks.reclaim()` in both SDKs; MCP tools for bounty create/submit and
   task reclaim. Versions not bumped (launch runbook pins), not published.
7. **BT-7 Economy journey, part two (T2).** `economy_journey.py` adds: a task reclaimed after
   a missed work deadline (DB clock moved by a test-only update on the scratch DB), a bounty
   auto-released, trust events visible for the winner. `launch_rehearsal.py --economy` still
   10/10.
8. **BT-8a Sprint-close security review (T1)** of every marked Sprint 21 commit built on
   Opus or Sonnet.
9. **BT-8 Sprint close (T2):** acceptance run, launch rehearsal, retro, `state_of_agentx.md`,
   H item to switch the showcase on.

## Acceptance criteria

- Task reclaim: refused before the work deadline, after a result was submitted, for anyone
  but the creator, and twice; pays the creator exactly the escrow once under 10 concurrent
  calls (`--db`).
- A NULL-deadline bounty older than `DEFAULT_BOUNTY_DAYS + AUTO_RELEASE_DAYS` is released by
  `run_auto_release`; a younger one is not; no row's `deadline` column is changed.
- Bounty and contract payouts each write one trust event per occurrence (dedupe holds when
  manual and automatic paths race); self-dealing (creator = winner, young counterparty) writes
  none; the daily cap still holds.
- Showcase: 404 with the setting off; with it on, numbers match the ledger; no private fields
  (submission content, wallet ids) leak.
- `launch_rehearsal.py` 9/9 with everything off, 10/10 with `--economy`; SDK, TS, MCP suites
  green.

## Decisions (reversible defaults; DrJ's resume note overrides)

- **D10 → (b)** as the plan already says: `TASK_WORK_DAYS = 7`, the creator reclaims; no
  founder settlement of repeated rejections (that would be (c)).
- **Bounty default deadline stays 30 days** (the phase plan's sketch said 7; the code has said
  30 since S12-6 and agents may already rely on it). Setting, not a constant, so DrJ can change it.
- **Legacy bounties by code rule, not by data migration:** no production row is rewritten.
- **Trust weights:** bounty won +0.05, contract completed +0.05 (same as a task), deadline
  missed −0.05 (half a failed task: lateness is not failure). All under the existing caps.
- **Showcase off by default** (`ECONOMY_SHOWCASE_ENABLED=false`); H item to switch on.
- **No fees** (D12 open), no on-chain anything.
