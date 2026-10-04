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
- [x] **P-5 — One public API address, `https://api.agentx.social` (DrJ's note, Phase 1).** T2.
  Production skill.md / agent.json print only that address; SDK (Python + TS) default, sample
  agents, quickstart, protocol spec and READMEs use it. Check: tests fail on fly.dev, localhost
  or http:// in skill.md, agent.json, the SDK defaults (fail on the old code); platform and SDK
  suites green. Done cycle 87 (`afe5149`). H19 (DNS + Fly certificate) must come before merge.
- [x] **P-6 — Answer DrJ's H5 role finding: does H10 need to assign FOUNDER?** T2. Check:
  answered in HUMAN_ACTIONS H20 (no; one separate admin agent needs it). Done cycle 87.
- [ ] **P-7 — Phase 2 plan: move the backend from Fly to the Pink Popcorn VPS (plan only, no
  changes).** T2 (planning, runbook). Write `platform/docs/execution/vps_migration_plan.md`:
  Docker, Caddy with automatic HTTPS, the scheduler process (heartbeat, trust, auto-release
  jobs), a deploy workflow to the VPS, health checks, rollback, a zero-downtime cutover that
  repoints api.agentx.social, the website (Vercel rewrites and `NEXT_PUBLIC_API_URL` in `ui/`
  still name fly.dev and move with the cutover), and the date Fly can be switched off. Check:
  every item DrJ listed has a section; every DrJ step is copy-paste; Fly stays on until DrJ
  approves.
- [ ] **P-8 — Safe steps to give FOUNDER to one admin agent of DrJ's (H20).** T1 (grants a
  role in production). Check: a dry-run-first tool or exact SQL that can only touch the one
  named agent, refuses the 8 founder bots, writes the audit log; tests prove it fails closed;
  H20 rewritten with copy-paste steps.

## Open DrJ items (see HUMAN_ACTIONS)

H1–H20 open (H1 + H18 urgent; H19 before merging); D10 open (not blocking).
