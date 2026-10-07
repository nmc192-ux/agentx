# Engine PLAN — Phase B close

**Branch:** `engine/phase-b` · **Goal:** `strategy/strategic_plan_v2.md` §4 Phase B.
**Previous plan:** `archive/PLAN_sprint_18.md` (Sprint 18 closed cycle 159). Sprints 13–18 are
closed on the branch, not merged.

Every Phase B exit criterion still open needs DrJ or the outside world: `pip install
agentx-py` (H12) and `npm install @agentx/sdk` (H26) working, a public samples repo (H15), 100+
outside agents joined and posting, an outside agent with real trust, "Agent of the week" live
(merge + H27), the alpha announcement (H28). The engine's job now is to check nothing
engine-doable is left, then write the Phase B briefing.

## Steps

- [x] **PB-1 — Inventory engine-doable Phase B leftovers.** T2 (planning). Done cycle 160.
  Walked §4 Phase B, §9 and §11 of `strategic_plan_v2.md` and Appendix A of `magna_carta_v1.md`
  against the code and docs. Result:

  | Leftover | Status | Owner |
  |---|---|---|
  | `pip install agentx-py` works | built, published by H12 | DrJ |
  | `npm install @agentx/sdk` works | built (S14), published by H26 | DrJ |
  | Sample agents repo public | `agentx-examples/` built (S12); public by H15 | DrJ |
  | Quickstart zero-to-first-post < 10 min | met (S15: Python 7.6, TS 4.5 min) | done |
  | 100+ outside agents joined and posted | join paths built (S15, S18); needs the world | outside |
  | Outside agent with non-trivial trust | trust recalc live since S10; needs the world | outside |
  | "Agent of the week" live | built (S17); on by merge + H27 | DrJ |
  | Public alpha announcement | drafted; H28 | DrJ |
  | `trust_score_spec.md` (plan §11.2, "by end of Phase B") | **missing** | engine → PB-1a |
  | Protocol spec (Phase A carry-over) | `protocol/protocol_spec.md` exists; publish = H16 | DrJ |
  | Competitive scan (§11.6, magna carta Art. 5, quarterly) | **missing**, overdue since Q3 | engine → PB-1b |
  | Human role: operator vs co-participant (§11.5) | open; needs DrJ's call, not code | DrJ → D11 |
  | Synapse synergy (§11.1) | waits on DrJ's context | DrJ (unchanged) |
  | Pricing (§11.4) | deferred to Phase C start by the plan | Phase C |
  | Plan v2.x amendments (§10) | none written since v2; steward's job | DrJ (briefing proposes text) |

- [ ] **PB-1a — Draft `strategy/trust_score_spec.md`.** T2 (documentation of an existing,
  already-reviewed service; no code change). The open *interface* only (magna carta Art. 14):
  what the score is, its range, the public endpoints and fields that expose it, recalc cadence,
  the inputs it is allowed to use, anti-collusion rules as decided in D7, versioning and what
  stays proprietary. Every claim checked against the code (`trust` service, recalc job, API).
  Check: file exists; every endpoint/field it names exists in the code (grep listed in the log).
- [ ] **PB-1b — First competitive landscape scan `strategy/competitive_landscape_2026q4.md`.**
  T2 (research). Web research on agent social networks / agent registries / A2A platforms,
  dated sources, and what each means for AgentX's phases. Q3 was missed; this is Q4's.
  Check: file exists; every entry has a dated source link.
- [ ] **PB-2 — Phase B briefing.** T2. `sprints/briefing_<date>_engine.md` in the protocol's
  format: what merging the whole branch will do, the combined live-test checklist, the
  ordered DrJ list. Then report `PHASE_COMPLETE`.
  Check: briefing exists; status file says `PHASE_COMPLETE`.

## Open human items touching the branch

D11 (human role, not blocking); merge (Sprints 13–18, migration 048); H31–H33 (Sprint 18); H29, H30 (VPS); H26, H12
(publish); H27, H28.
