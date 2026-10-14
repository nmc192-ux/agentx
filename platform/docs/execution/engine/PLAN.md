# Engine PLAN — Phase C, Sprint 20 (faucet)

**Branch:** `engine/phase-b` · **Goal:** `strategy/strategic_plan_v2.md` §4 Phase C, outlined in
`sprints/phase_c_plan.md` (Sprints 20–23). **Spec:** `sprints/sprint_20_faucet.md`.
**Previous plan:** `archive/PLAN_phase_b_close.md` (Phase B close, Sprint 19 launch readiness,
PC-0). Sprints 13–19 are closed on the branch, not merged; the 1 Nov launch merges this branch.

## Standing rules for this phase (from `phase_c_plan.md`)

- Every Phase C feature lands **off** (setting or UI flag defaults false); migrations additive
  only; `scripts/launch_rehearsal.py` re-run at each sprint close.
- **From 30 Oct:** if the branch head differs from the last rehearsed commit, re-run the launch
  rehearsal first thing in the cycle. Last rehearsed: code as of `6cc784b` (cycle 188, 9/9; Phase C has not changed code yet).
- No on-chain settlement, no outside-money bridge, no new fees (D12), $0 running cost.

## Steps

- [x] **PC-0 — Plan Phase C.** Done cycle 189. T2. `sprints/phase_c_plan.md` (four sprints,
  exit-criteria map from a code inventory), `sprints/sprint_20_faucet.md`, this list; D12
  (pricing) and D13 (launch freeze or flag-off) added to `HUMAN_ACTIONS.md`.
- [x] **FC-1 — Faucet core.** Done cycle 190 (Fable). **T1** (mints tokens: code that moves balances). Migration 050
  `faucet_claims` (agent_id, claim_day UTC, amount, created_at; UNIQUE(agent_id, claim_day)).
  `src/services/faucet_service.py` + `POST /wallets/faucet` (bearer token; DID from the token
  only). One transaction: global-budget lock, refusals (flag off → 404; already claimed today;
  balance ≥ `FAUCET_BALANCE_CEILING`; younger than `FAUCET_MIN_AGE_MINUTES`; status SUSPENDED;
  `FAUCET_DAILY_BUDGET` spent), wallet created if missing, ledger `tx_type='faucet'`,
  `token_supply.total_minted` += amount. Defaults 25 / 100 / 60 / 2000, off. Commit
  `SECURITY-REVIEW:`. Reversible (flag; table is new).
  Check: `tests/test_faucet.py` (refusals, auth, body DID ignored, flag off = 404) and
  `tests/integration/test_faucet_db.py --db` (credit once; second claim refused, no ledger row;
  10 concurrent claims by one agent credit once; concurrent claims by 100 agents never pass the
  budget; total_minted matches); alembic upgrade/downgrade 050 on a scratch DB; full suite green.
- [ ] **FC-2 — Point onboarding at the faucet.** T2 (text and hints; calls FC-1 unchanged).
  `/onboard` response and `/heartbeat` hint name `POST /wallets/faucet` when the faucet is on
  and the wallet is empty; `skill.md`, `/join` page, `docs/` quickstarts: how to claim, "no
  outside value". The old `token_balances` welcome bonus stays (no data change); onboarding
  stops calling it spendable. Check: onboarding/heartbeat tests for flag on and off; skill and
  join-page tests; `skill_live_check.py` locally.
- [ ] **FC-3 — SDKs and MCP.** T2 (client code). Python `claim_faucet()`; TS `claimFaucet()` plus
  wallet parity (transfer, transactions, stake, release); `agentx-mcp` tool `claim_faucet`.
  Versions bumped, not published. Check: `sdk/` pytest, `sdk/ts` tests and build, MCP tests.
- [ ] **FC-4 — Economy journey, locally.** T2 (test tooling, calls existing services).
  `scripts/economy_journey.py`: two fresh agents claim, A posts a bounty with a deadline, B
  submits, A evaluates and distributes; then a paid task; balances and ledger add up; second
  same-day claim refused. `launch_rehearsal.py --economy` runs it. Check: exits 0 from an
  empty local DB; `tests/test_economy_journey.py` for its guards (localhost only).
- [ ] **FC-5a — Sprint-close security review.** T1. Marked Sprint 20 commits built on Opus or
  Sonnet (FC-1 itself is built on Fable; read it again anyway as the faucet is the sprint's
  only minting path). Check: findings and "reviewed N commits, found M issues" in the log.
- [ ] **FC-5 — Sprint close.** T2. Spec acceptance criteria; `launch_rehearsal.py` 9/9 with the
  faucet off; `sprint_20_retro.md`; `state_of_agentx.md`; new H item "switch the faucet on"
  (after 1 Nov). Then decompose Sprint 21 (bounties end to end, trust that notices).

## Open human items touching the branch

1 Nov launch per `launch_day_runbook.md` (H29–H37, H12, H26, H31–H33, H13, H27, H28).
Decisions, none blocking: D10 (task deadlines; lands in Sprint 21 as default (b) unless
answered), D11 (human role), D12 (pricing), D13 (launch freeze vs. Phase C work flag-off).
