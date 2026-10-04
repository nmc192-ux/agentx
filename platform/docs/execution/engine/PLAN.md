# Engine PLAN — Phase A closed

**Branch:** `engine/phase-a` · **Status:** `PHASE_COMPLETE` (cycle 85, 2026-10-04)
**Briefing:** `platform/docs/sprints/briefing_2026-10-04_engine.md`
**Closed plans:** `archive/PLAN_sprint_9.md` … `archive/PLAN_sprint_12.md`; retros in `platform/docs/sprints/`.

All engine-doable Phase A work is done. The remaining Phase A exit criteria need production
and DrJ (see HUMAN_ACTIONS: H5, H1, merge, H3, H9, H10, H6, H13, H14, H12).

## Steps

- [x] **P-1 — Merge origin/main (H5 hotfix) into the branch.** T2. Check: merge commits, tree
  unchanged, tests pass. Done cycle 86 (`463d0c8`).
- [x] **P-2 — Why production did not migrate on deploy; safe plan for DrJ.** T2 (debugging,
  runbook). Check: cause shown in the repo, and DrJ's step-by-step plan written. Done cycle 86:
  `sprints/briefing_2026-10-04_migrations.md`, H18 added, H1 updated.
- [x] **P-3 — `/posts?type=…` / `?status=…` with an unknown label is a 500 (Sentry).** T2.
  Check: 422 in unit tests and against real Postgres. Done cycle 86 (`ffaedc5`).
- [ ] **P-4 — After DrJ reports H18 done: merge main, drop the xfail marker on
  `tests/test_fly_release_command.py`, run tests.** T3. [waits on H18]
- [ ] **Next (from DrJ's note): the api.agentx.social work.** Needs a spec or note from DrJ
  before the engine can plan it.

## Open DrJ items (see HUMAN_ACTIONS)

H1–H18 open (H1 + H18 urgent); D10 open (not blocking).
