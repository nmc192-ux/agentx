# Engine PLAN — Phase C, Sprint 21 (bounties end to end, trust that notices)

**Branch:** `engine/phase-b` · **Goal:** `strategy/strategic_plan_v2.md` §4 Phase C, outlined in
`sprints/phase_c_plan.md` (Sprints 20–23). **Spec:** `sprints/sprint_21_bounties_trust.md`.
**Previous plan:** `archive/PLAN_sprint_20.md` (faucet; closed cycle 195). Sprints 13–20 are
closed on the branch, not merged; the 1 Nov launch merges this branch.

## Standing rules for this phase (from `phase_c_plan.md`)

- Every Phase C feature lands **off** (setting or UI flag defaults false); migrations additive
  only; `scripts/launch_rehearsal.py` re-run at each sprint close.
- **From 30 Oct:** if the branch head differs from the last rehearsed commit, re-run the launch
  rehearsal first thing in the cycle. Last rehearsed: `9562913` (cycle 195, 10/10 with `--economy`).
- No on-chain settlement, no outside-money bridge, no new fees (D12), $0 running cost.

## Steps

- [x] **BT-0 — Plan Sprint 21.** Done cycle 196. T2. Code inventory; spec
  `sprints/sprint_21_bounties_trust.md`; this list.
- [x] **BT-1 — Task work deadline (D10 default b).** Done cycle 197 (Fable). Built as
  specified below with two deliberate differences: `TASK_WORK_DAYS` defaults to **0 = off**
  (Phase C standing rule; H39 switches it on with 7), and the clock also restarts at each
  rejected result, so reject-then-reclaim is impossible. Fee kept by the platform. No migration.
  Original spec: **T1** (moves escrowed tokens back to the
  creator). Setting `TASK_WORK_DAYS=7`. `task_service.reclaim_task` + `POST /tasks/{id}/reclaim`
  (bearer; creator only): allowed only when the task is assigned, no result is pending or
  accepted, and `task_assignments.started_at <= CURRENT_TIMESTAMP - TASK_WORK_DAYS` (database
  clock). Row-locked; refunds the escrow once (`tx_type='task_work_deadline_refund'`); task
  → CANCELLED, assignment closed; a late `submit_result` is then refused. Additive migration
  only if a column is truly needed (prefer none). Update D10 in `HUMAN_ACTIONS.md` ("default
  (b) built"). Commit `SECURITY-REVIEW:`.
  Check: `tests/test_task_reclaim.py` (refusals: too early, result pending, not creator,
  anonymous 401, wrong status, twice) and `tests/integration/test_task_reclaim_db.py --db`
  (refund once; 10 concurrent reclaims refund once; reclaim racing a result submission: exactly
  one wins; wallet and ledger add up); full suite green.
- [x] **BT-2 — Bounties created without a deadline.** Done cycle 198 (Fable). Built as
  specified below with one deliberate difference: the legacy rule is behind its own setting
  `LEGACY_BOUNTY_DAYS`, **0 = off** by default (Phase C standing rule; H40 switches it on with
  30), so the 1 Nov merge moves no held pool. `DEFAULT_BOUNTY_DAYS` is a setting (30; under 1
  falls back to 30). Get/list report the effective deadline while the rule is on. No row
  written, no migration. Original spec: **T1** (changes when held pools are
  released). `release_overdue_bounty` and the `_DUE_BOUNTIES` query in `jobs/auto_release.py`
  use `COALESCE(deadline, created_at + DEFAULT_BOUNTY_DAYS)`; submissions to such a bounty
  close at the same effective deadline. `DEFAULT_BOUNTY_DAYS` becomes a setting (default 30).
  No data change: no row's `deadline` is written. Commit `SECURITY-REVIEW:`.
  Check: `--db` tests: a NULL-deadline bounty older than 30 + 7 days is released (paid to the
  top score, or refunded); one younger is not; its `deadline` column stays NULL; existing
  auto-release tests unchanged and green.
- [x] **BT-3 — Trust from paid work.** Done cycle 199 (Opus). Built as specified; the
  reporters read the ledger, so a call with no matching payout or deadline refund writes
  nothing. A dispute ruled for the contractor gives no `contract_completed` (a FOUNDER's
  ruling, not the creator's acceptance); "delivered by the deadline" for `sla_compliance`
  (spec line) not built: display-only today, left for later. Original spec: T2 (calls the reviewed `record_event` without changing
  its rules; adds event types and weights, so marked `SECURITY-REVIEW:` for BT-8a). New
  reporters in `reputation.py`: `record_bounty_won` (creator → winner, manual and automatic
  payout; not on refund), `record_contract_completed` (creator → worker, approval or
  auto-release; not on reclaim or dispute loss), `record_deadline_missed` (worker; task reclaim
  from BT-1 and contract reclaim). Weights +0.05 / +0.05 / −0.05. Called after commit, like
  `_after_payment`, so a trust failure cannot undo a payment. Dedupe keys per occurrence.
  Check: unit tests per reporter; `--db`: manual and automatic payout racing write one event;
  self-dealing and a < 24 h counterparty write none; daily cap holds; `recalculate_agent_trust`
  applies the new types.
- [x] **BT-4 — Showcase API.** Done cycle 200 (Opus). Built as specified; amounts read from
  the ledger (payouts out of escrow), a payment to a bounty's or contract's own creator and
  any agent that is not ACTIVE left out; top earners count `contract_dispute_release` too
  (money earned, unlike trust); open bounties = status open with the effective deadline not
  passed, largest pools first (20), plus open count and pool total. Cached 60 s (Redis or local)
  and in the anonymous response cache; on the per-IP list budget. Original spec: T2. `GET /markets/bounties/showcase`: open bounties (title,
  pool, deadline, submission count), recently paid (last 30 days: amount, winner DID, paid
  when, manual or automatic), top earners (bounty + contract payouts, last 30 days, top 10).
  Public read, Redis-cached 60 s, IP rate-limited; 404 unless `ECONOMY_SHOWCASE_ENABLED`
  (default false). No submission content, no wallet ids.
  Check: `tests/test_bounty_showcase.py` (flag off 404; shapes; no private fields; numbers
  match the ledger in a `--db` test).
- [x] **BT-5 — Showcase page.** Done cycle 201 (Sonnet). Page at `/markets/bounties`; links from `/markets` and `/stats` (both only with the economy flag); shows an "not available yet" note while the API 404s. T3 (small UI over BT-4). `ui/app/markets/bounties/page.tsx`
  behind `NEXT_PUBLIC_FEATURE_ECONOMY`: three sections, empty states, no client-side secrets;
  link from `/markets` and `/stats`. Check: `npm run build` and the UI test suite; page
  renders against a local API with seeded data.
- [ ] **BT-6 — Client parity.** T2 (client code). TS `contracts.ts` (create, list, get, bid,
  assign, submit, approve, reclaim, dispute) exported from the client; `tasks.reclaim` in
  Python and TS; MCP tools `create_bounty`, `submit_bounty_solution`, `reclaim_task` (check
  which exist first). Versions not bumped, not published.
  Check: `sdk/` pytest, `sdk/ts` build + tests, MCP tests.
- [ ] **BT-7 — Economy journey, part two.** T2 (test tooling). `scripts/economy_journey.py`
  gains: a task reclaimed after a missed work deadline and a bounty auto-released (time moved
  by back-dating rows on the local `agentx_smoke*` DB only, guarded like the rest of the
  script); the winner's trust events listed. The journey's own API must run with
  `TASK_WORK_DAYS=7` (it ships 0 = off), as it already does with `FAUCET_ENABLED`. Check: journey exits 0 from an empty local DB;
  `launch_rehearsal.py --economy` 10/10; guard tests still pass.
- [ ] **BT-8a — Sprint-close security review.** **T1.** Every marked Sprint 21 commit built on
  Opus or Sonnet (BT-3 at least; BT-1 and BT-2 were built on Fable). Adversarial tests; fix in
  the same cycle; record "reviewed N commits, found M issues".
- [ ] **BT-8 — Sprint close.** T2. Acceptance criteria from the spec; launch rehearsal 9/9 off
  and 10/10 `--economy`; `sprint_21_retro.md`; `state_of_agentx.md`; H item "switch the bounty
  showcase on" (after 1 Nov, with H38's faucet and H39's task deadline).
- [ ] **NEXT — Decompose Sprint 22** (collectives a newcomer can make in five minutes). T2.

## Open human items touching the branch

1 Nov launch per `launch_day_runbook.md` (H29–H37, H12, H26, H31–H33, H13, H27, H28); H38
(faucet switch-on). Decisions, none blocking: D10 (lands here as default (b) unless answered),
D11 (human role), D12 (pricing), D13 (launch freeze vs. Phase C work flag-off).
