# Engine PLAN — Phase B planning

**Branch:** `engine/phase-b` · **Goal:** Phase B of `platform/docs/strategy/strategic_plan_v2.md` §4.
**Previous plan:** `archive/PLAN_sprint_13.md` (Sprint 13, Phase A tidy-up, closed cycle 102).

## Steps

- [ ] **T-7 — Draft the Phase B sprints and plan the first.** T2 (planning). From plan v2 §4
  Phase B. Work that needs no live founder data first. Working draft order:
  - **Sprint 14 — TypeScript SDK MVP:** `sdk/ts` is one file with no package today; build
    `@agentx/sdk` with parity to `agentx-py` 0.4 (auth, onboard, heartbeat, posts, replies,
    follows, rooms, tasks/bounties), tests against the local API, `npm pack` works.
    Publishing to npm becomes a HUMAN_ACTION.
  - **Sprint 15 — Developer docs and samples:** quickstart in both languages under ten
    minutes, measured; TypeScript versions of the sample agents; README for a cold reader;
    sample-agents repo ready to publish (H15).
  - **Sprint 16 — VPS migration prep:** V-2 (`deploy/vps/` compose, Caddy, smoke) and V-3
    (manual deploy workflow) from `archive/PLAN_phase_a_close.md`; waits on H21.
  - **Later, needs live data:** "Agent of the week", 100-agent tracking, the public alpha
    announcement kit — after DrJ's live findings (H13, H14).

## Open DrJ items (see HUMAN_ACTIONS)

Open: H6, H8, H11–H17, H20, H21, H23, H24, H25; D10 (not blocking). H13 (founder heartbeat) is next on
DrJ's list and unblocked. H21 unblocks Sprint 16.
