# Engine PLAN — Sprint 13: Phase A tidy-up

**Branch:** `engine/phase-b` · **Spec:** `platform/docs/sprints/sprint_13_phase_a_tidy.md`
**Started:** cycle 96, 2026-10-06 (DrJ's note: tidy-up first, then Phase B).
**Previous plan:** `archive/PLAN_phase_a_close.md` (V-2, V-3 carry into the Phase B VPS sprint).

Steps run in this order (cheap, low-risk first; the one Fable step last). "DrJ #n" is the
item's number in DrJ's note.

## Steps

- [x] **T-1 — CI skips the engine's draft PR (DrJ #1).** Done cycle 97 (no `workflow_dispatch`: it would let a hand-run on main redeploy production). T2 (CI configuration).
  `ci.yml`: keep `push: [main, develop]`; `pull_request` gains
  `types: [opened, reopened, synchronize, ready_for_review]`; every job gets
  `if: github.event_name != 'pull_request' || !github.event.pull_request.draft`; add
  `workflow_dispatch` so DrJ can start it by hand. `deploy.yml` is untouched (it waits on CI
  for `main`, which still runs). Check: `actionlint` clean; new `tests/test_ci_triggers.py`
  pins push-to-main, ready_for_review, the draft guard on all jobs and workflow_dispatch
  (fails on the old file); platform suite green.
- [human] **T-2 — Scheduler on shared-cpu-1x 512 MB (DrJ #2).** Engine part done cycle 98: H23 written (`fly.toml` only; staging has no scheduler and is already 1x), `tests/test_fly_vm_sizes.py` xfails now and XPASSes on a patched copy. Remove the xfail marker after `H23 done`. T2 (configuration, runbook).
  `[human]` for the edit itself. Write H23: the exact two `[[vm]]` blocks (`processes =
  ["app"]` shared-cpu-2x 512mb; `processes = ["scheduler"]` shared-cpu-1x 512mb) for
  `platform/fly.toml` and `platform/fly.staging.toml`, how to commit them, what the next
  deploy does, and how to check (`fly scale show`). Add a guard test, xfail until DrJ's edit
  lands. Check: test xfails now and passes against a scratch copy with the blocks applied.
- [x] **T-3 — Sentry `automaticVercelMonitors` deprecation (DrJ #4).** Done cycle 99 (no UI test script exists; build is the check). T3 (small config).
  Move it under the `webpack` options `@sentry/nextjs` 10 expects, still `false`. Check:
  `npm run build` in `ui/` has no deprecation line for it; UI tests pass.
- [ ] **T-4 — Commits use DrJ's GitHub noreply address (DrJ #5).** T2 (configuration).
  Find the address (`<id>+nmc192-ux@users.noreply.github.com`, read-only GitHub lookup).
  The engine's commit identity is set outside the repo by the engine runner, so this is most
  likely `[human]`: write H24 with the exact setting for DrJ, and say that past commits keep
  their author (only new commits change). Check: H24 written; if the engine can set it, the
  next commit's author email is the noreply address.
- [ ] **T-5 — Safe removal of the April test accounts (DrJ #3).** **T1** (script deletes
  production data). `platform/scripts/remove_test_accounts.py`, modelled on
  `grant_founder.py`: `show` / `remove`, dry run unless `--apply` (the dry run runs the same
  statements and rolls back); matches only `A189_-002`, `A386_-002`, `A652_-002`,
  `canary-*`, `sdk-canary-*`, `Prod Smoke *`; refuses any founder, any FOUNDER/ADMIN role,
  any agent with a non-zero balance or open escrow, and any match count above a cap unless
  named; prints every row it would touch (agent, posts, follows, etc.); writes `audit_logs`
  in the same transaction. `SECURITY-REVIEW:`. Check: real-Postgres tests prove every
  refusal leaves the database unchanged and the dry run changes nothing; H25 written with
  dry run first, then apply.
- [ ] **T-6 — Sprint close.** T2. Sprint acceptance (spec) run locally; retro
  `sprint_13_retro.md`; `state_of_agentx.md` updated; short briefing for DrJ to merge this
  sprint. (The 5a security review is only needed for `SECURITY-REVIEW:` commits built on
  Opus/Sonnet; T-5 is built on Fable.)
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

Open: H6, H8, H11–H17, H20, H21, H23; D10 (not blocking). H13 (founder heartbeat) is next on
DrJ's list and unblocked. H21 unblocks Sprint 16.
