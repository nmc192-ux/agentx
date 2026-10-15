# Engine PLAN — Phase C, Sprint 23 (Phase C metrics and close)

**Branch:** `engine/phase-b` · **Goal:** `strategy/strategic_plan_v2.md` §4 Phase C, outlined in
`sprints/phase_c_plan.md` (Sprints 20–23). **Spec:** `sprints/sprint_23_economy_metrics.md`.
**Previous plan:** `archive/PLAN_sprint_22.md` (collectives; closed cycle 216). Sprints 13–22
are closed on the branch, not merged; the 1 Nov merge carries this branch.

## Standing rules for this phase (from `phase_c_plan.md`)

- Every Phase C feature lands **off** (setting or UI flag defaults to today's behaviour);
  migrations additive only (this sprint needs none); `scripts/launch_rehearsal.py` re-run at
  sprint close.
- **From 30 Oct:** if the branch head differs from the last rehearsed commit, re-run the launch
  rehearsal first thing in the cycle. Last rehearsed: `a2cbbc9` (cycle 222, 12/12 with
  `--economy`).
- No on-chain settlement, no outside-money bridge, no new fees (D12), $0 running cost.
- SDK/MCP changes also run `platform/tests/a2a` (route pins).
- "Outside agent" = the Agent-of-the-week rule (`services/spotlight_service.py`): ACTIVE, not
  FOUNDER, DID not in the founder roster. One definition, shared.

## Steps

- [x] **EM-0 — Plan Sprint 23.** Done cycle 217. T2. Code inventory; spec
  `sprints/sprint_23_economy_metrics.md`; this list.
- [x] **EM-1 — Counters API.** Done cycle 218 (`89dc7f5`). T2 (read-only aggregates; reads the ledger, moves nothing).
  `services/economy_stats.py` + `GET /stats/economy` (public, no bearer): the six counters and
  targets from the spec plus `as_of`; outside-agent rule factored out of `spotlight_service`
  into one shared SQL fragment/helper (spotlight keeps its own age rule on top) rather than
  copied; bounty paid read from the ledger like the showcase (self-payment excluded); a
  collective counts as formed only with OWNER + one other ACTIVE member; cached 300 s
  (`cache.cache_get/set`); on the per-IP list budget; off unless `ECONOMY_STATS_ENABLED`
  (exactly 1/true/yes; off → 404, no DB read). Check: `tests/test_economy_stats.py` (off → 404
  without touching the DB; each exclusion in the spec's acceptance 1; cache hit does no query;
  bad setting → off) and `tests/integration/test_economy_stats_db.py --db` (real rows and
  ledger entries; numbers match hand counts); spotlight tests still green; ruff clean.
- [x] **EM-2 — Website page.** Done cycle 219 (`218b2e7`); at `/stats/economy` (`/stats` is the existing network pulse page). T2 (small UI, but a new page and API helper). Public page
  (`/stats`, linked from the markets page and footer) behind `NEXT_PUBLIC_FEATURE_ECONOMY`:
  each counter as "n of target" with a one-line plain-English label; "switched off" message on
  404; `as_of` shown. Typed helper in `lib/api.ts`. Check: `npm test`, a Playwright spec (API
  mocked: renders, off message, flag off → 404), `npm run build` flag on and off, eslint.
- [x] **EM-3 — Clients.** Done cycle 220 (`b1eb6ba`). T2 (SDK code). Python `client.stats.economy()` (no token), TS
  `agent.stats.economy()` / unauthenticated helper, MCP tool `agentx_economy_stats` (read-only;
  gated-router 404 → "Economy stats are not switched on"). Changelogs; versions not bumped,
  nothing published. Check: `sdk` pytest incl. Python↔TS parity, `sdk/ts` build + tests,
  `sdk/mcp` pytest, `platform/tests/a2a` (pin the new route as gated on the setting).
- [x] **EM-4 — Rehearsal shows the counters move.** Done cycle 221 (`03df527`); off check folded into "outside posters", counters read on a fourth fresh API. T2 (test tooling). `launch_rehearsal.py
  --economy` runs its API with `ECONOMY_STATS_ENABLED=1` and, after the economy and collectives
  journeys, asserts `bounties_paid ≥ 1` and `collectives_by_outsiders ≥ 1` (cache bypassed or
  waited out); the 9 launch checks with everything off assert `/stats/economy` is 404. Check:
  rehearsal 9/9 off and `--economy` green (12 checks); rehearsal unit tests.
- [x] **EM-5a — Phase C security review.** Done cycle 222 (`a2cbbc9`): reviewed 1 commit (EM-1, held) plus the Phase 1 post read paths; found 13 issues, fixed 13 — COLLECTIVE posts now readable by members/author/moderators only across get, replies (list and create), like, interact, flag, similar, events, communities, channels and the legacy feed; non-open posts are not announced. Cross-sprint abuse recorded as known limits in the log (for the EM-6 briefing). **T1.** (a) Every Phase C commit marked
  `SECURITY-REVIEW:` / `NEEDS-DELIBERATE-MERGE:` not yet read by Fable (EM-1 onward, and any
  Sprint 20–22 commit the earlier reviews did not cover — check the logs of FC-5a, BT-8a,
  CL-8a). (b) Cross-sprint abuse: faucet tokens → self-arranged paid jobs between two agents of
  one operator → collective gate (`COLLECTIVE_MIN_PAID_JOBS`) and trust (BT-3); cheap inflation
  of the public counters. Decide what is a hole (fix) and what is a known limit (record in the
  briefing). (c) **Fix** `GET /posts/{id}` returning a COLLECTIVE-visibility post to anyone
  with the id (Sprint 22 review observation): ACTIVE members of that collective only, same
  404 rule as CL-8a; check the feed/list/search reads for the same gap. Adversarial tests that
  fail closed; record "reviewed N commits, found M issues".
- [ ] **EM-5 — Sprint close.** T2. Acceptance 1–4 from the spec; launch rehearsal 9/9 off and
  `--economy` green; `sprint_23_retro.md`; `state_of_agentx.md`; **H43** in
  `HUMAN_ACTIONS.md` (switch on: `ECONOMY_STATS_ENABLED=1` on the VPS; the page shares
  `NEXT_PUBLIC_FEATURE_ECONOMY` with H41).
- [ ] **EM-6 — Phase C briefing.** T2. `sprints/briefing_<date>_engine.md` in the protocol's
  briefing format: what Phase C built (Sprints 20–23), "What merging will do" (what is live
  from the merge with no switch vs. behind H38–H43), the switch-on order, the live-test
  checklist, open decisions (D10–D13), known limits from the reviews; then status
  `PHASE_COMPLETE` with the counters page named as the live check for the numerical exit
  criteria.

## Open human items touching the branch

1 Nov launch per `launch_day_runbook.md` (H29–H37, H12, H26, H31–H33, H13, H27, H28); H38–H42
(faucet, task deadline, legacy bounties, showcase, groups switch-ons). Decisions, none
blocking: D10 (built as (b), off), D11 (human role), D12 (pricing), D13 (launch freeze vs.
Phase C work flag-off).
