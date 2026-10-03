# Engine PLAN — Phase A, Sprint 12 (Phase B prep)

**Branch:** `engine/phase-a` · **Spec:** not drafted yet (`platform/docs/sprints/sprint_12_phase_b_prep.md`,
from Plan v2 §4 "Sprint 12 — Phase B prep")
**Sprint 11 plan (closed):** `archive/PLAN_sprint_11.md` · retro `platform/docs/sprints/sprint_11_retro.md`
**Sprint 10 plan (closed):** `archive/PLAN_sprint_10.md` · retro `platform/docs/sprints/sprint_10_retro.md`
**Sprint 9 plan (closed):** `archive/PLAN_sprint_9.md` · retro `platform/docs/sprints/sprint_9_retro.md`

## Next cycle (T2)

Draft the Sprint 12 spec from the plan's sketch (sample agents repo with five reference
patterns, quickstart formalized, `agentx-client` deprecation period, docs-site decision) and
the protocol specification scoping the plan assigns to Sprint 12 (Magna Carta Article 13),
then decompose it here. Place the queued items below in the step list (E1–E5 are T1 each,
E6 and F1 are T2). Baseline (cycle 69): platform **2904 passed**, 342 skipped; real-Postgres
**328 passed**; SDK **345 passed**; smoke green (93 GET routes).

## Queued from DrJ's decisions (cycle 63) — to be placed when Sprint 12 is decomposed

DrJ answered D1–D9 (cycle 63 note): D1 a, D2 b+c, D3 b+c, D4 b, D5 b, D6 a, D7 a, D8 a, D9 a.
D1 is done (root LICENSE). D6, D7, D9: no change. D8 (a): production keeps its addresses and
lists them in `FOUNDER_DIDS` (already how H13 works). D2 (b): `tasks` stays off in production
until creator approval ships (HUMAN_ACTIONS H3 note). The rest is code that moves tokens, so
each is its own **T1** step with a `NEEDS-DELIBERATE-MERGE:` commit and fail-closed tests:

- [x] **E0 (D2b) — Hold `tasks` off in the repo default until E1 ships** *(cycle 64, Opus T2, `f64ad84`; placed in Tier A so no env value turns it on)*: move it from
  `ENABLED_IN_SPRINT_9` back onto the off-list in `src/router_config.py` with the reason;
  check the founder heartbeat's paid-task loop (it uses the services, not the route) and the
  smoke/e2e tests still pass. Do this next (Sprint 11, before S11-6): it decides what the
  merge switches on. Tier **T2** (configuration that only turns a route off).
- [ ] **E1 (D2c) — Creator approves a task result before the reward is released**; automatic
  release to the worker N days after submission if the creator stays silent; founder runners
  and the founder heartbeat's paid-task loop updated to approve. Tier **T1** (moves tokens).
- [ ] **E2 (D3b) — FOUNDER settles a disputed contract**: one founder-only action that pays
  the contractor or refunds the creator, on the ledger. Tier **T1** (moves tokens, role-gated).
- [ ] **E3 (D3c) — Contract deadlines**: creator may reclaim after the deadline with no
  delivery; contractor paid automatically N days after delivery if the creator is silent;
  disputes still go to E2. Tier **T1** (moves tokens).
- [ ] **E4 (D4b) — Pay the accepted bid, refund the rest; bids above budget refused.**
  Tier **T1** (moves tokens).
- [ ] **E5 (D5b) — Bounty deadline enforced**: no submissions after it; N days later an
  unpaid pool goes to the top-scored submission, or back to the creator if nothing was
  scored (the trade-off flagged in D5 stands as DrJ chose it). Tier **T1** (moves tokens).
- [ ] **F1 — Public profile shows the new trust score at once** (found cycle 66): the trust
  replay does not clear the 5-minute `GET /agents/{did}` cache, so a profile can lag
  `/agents/{did}/trust` by up to 5 minutes. Clear `agent_key(did)` when the replay changes
  a score. Tier **T2** (cache only; trust rules unchanged).
- [ ] **E6 — Scheduled job that runs the automatic releases (E1/E3/E5)**, reusing the existing
  scheduler; calls the reviewed release functions only. Tier **T2**.
  N for all automatic releases: engine default 7 days, one constant (reversible).

## Open DrJ items (see HUMAN_ACTIONS)

H1–H14 open; D1–D9 answered cycle 63.
