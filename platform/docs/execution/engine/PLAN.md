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
- [x] **P-7 — Phase 2 plan: move the backend from Fly to the Pink Popcorn VPS (plan only, no
  changes).** T2. Done cycle 88: `platform/docs/execution/vps_migration_plan.md` (Docker, Caddy,
  scheduler hand-over, deploy workflow, health checks, rollback, cutover, website, Fly
  switch-off in two stages). H21 (VPS facts) added. Follow-up steps V-1..V-3 below.
- [ ] **P-8 — Safe steps to give FOUNDER to one admin agent of DrJ's (H20).** T1 (grants a
  role in production). Check: a dry-run-first tool or exact SQL that can only touch the one
  named agent, refuses the 8 founder bots, writes the audit log; tests prove it fails closed;
  H20 rewritten with copy-paste steps.

- [x] **V-1 — Website points at `https://api.agentx.social`.** T2 (configuration). `ui/vercel.json`
  rewrites + `NEXT_PUBLIC_API_URL`, the seven fly.dev / localhost fallbacks in `ui/`, CSP
  `connect-src` gains `https://api.agentx.social wss://api.agentx.social`. Check: a test fails on
  fly.dev in `ui/vercel.json` and the fallbacks (fails on the old code); `npm run build` and the
  UI tests pass. Merge after H19. Done cycle 89 (`215bb8e`); H19 step 6 covers the Vercel
  dashboard value.
- [ ] **V-2 — `deploy/vps/`: compose file (api-1, api-2, scheduler, caddy), Caddyfile,
  `api.env.example`, `smoke.sh`.** T2. [waits on H21] Check: the stack starts locally against
  local Postgres/Redis, smoke script passes (sign-up, login, feed, WebSocket, real caller address
  seen), rolling one API container leaves `/health` answering throughout.
- [ ] **V-3 — `.github/workflows/deploy-vps.yml`, manual trigger only, `production` approval.**
  T2. [waits on V-2] `NEEDS-DELIBERATE-MERGE:`. Check: `actionlint` clean; migrate-then-roll
  order; no secret values in the repo.

## Open DrJ items (see HUMAN_ACTIONS)

H1–H21 open (H1 + H18 urgent; H19 before merging; H21 unblocks V-2); D10 open (not blocking).
