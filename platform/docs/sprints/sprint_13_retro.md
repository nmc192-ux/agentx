# Sprint 13 — Phase A tidy-up — Retro (engine run)

**Sprint:** 13 — Phase A tidy-up (`sprint_13_phase_a_tidy.md`, drafted by the engine in cycle 96 from DrJ's note of 6 Oct)
**Dates:** 2026-10-06 → 07, engine cycles 96–102
**Branch:** `engine/phase-b`. **Not merged.** Before this close the branch was 10 commits ahead of `main` (6 of them this sprint's work), 1 marked `SECURITY-REVIEW:` (T-5, built on Fable). No migrations.
**Step list and per-step detail:** `docs/execution/engine/archive/PLAN_sprint_13.md`. **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md` (H23–H25 are new this sprint).

## What was intended

Close five small Phase A loose ends from DrJ's list before Phase B starts: CI minutes spent on
the engine's draft PR, an oversized scheduler machine, the April test accounts still in
production, a Sentry deprecation warning in the website build, and Vercel preview builds
failing on the engine's commit author.

## What actually shipped (on the branch)

- **T-1 CI skips draft PRs** (`67a9608`). Pushes to `main` and normal PRs run CI exactly as
  before; a draft PR runs it once marked "Ready for review". No hand-start button: the deploy
  workflow fires on any green CI run on `main`, so a hand-run there would redeploy production.
  `tests/test_ci_triggers.py` pins all of this.
- **T-2 Scheduler machine size** (`00a9a53`, `[human]`). H23 has the exact `[[vm]]` blocks for
  `fly.toml` (the engine may not edit it). `tests/test_fly_vm_sizes.py` xfails until DrJ's edit
  lands and is proven to pass on a copy with the edit applied. Staging needed no change.
- **T-3 Sentry warning** (`10c9989`). `automaticVercelMonitors: false` moved under `webpack`
  in `ui/next.config.ts`. Same behaviour, no warning.
- **T-4 Noreply commit email** (`7a6b567`, `[human]`). The address is
  `263928593+nmc192-ux@users.noreply.github.com`; the engine's guard blocks `git config`, so H24
  tells DrJ the one command.
- **T-5 Test-account removal script** (`b418166`, Fable). `platform/scripts/remove_test_accounts.py`:
  matches only the named test accounts, refuses anything with tokens, a raised role, a founder
  look-alike or records shared with real agents, dry-runs by default, writes an audit row in
  the same transaction. 35 real-Postgres tests prove every refusal changes nothing. H25 gives
  DrJ show → dry run → apply.

## Acceptance criteria (run locally, cycle 102)

| Criterion | Result |
|---|---|
| `ci.yml` runs on push to `main` and non-draft PRs, skips drafts; `actionlint` clean; test pins triggers | ✅ `actionlint` clean; `test_ci_triggers.py` passes. Skip unless "ready"; no hand-start (decision above) |
| H23 with the exact `[[vm]]` blocks; a test that passes once they are in | ✅ H23 written; `test_fly_vm_sizes.py`: production check xfails, H23-applied copy passes |
| Clean-up script dry-runs by default, refuses non-matching agents, real-Postgres tests pass, H25 dry run first | ✅ 35 passed in `test_remove_test_accounts_db.py`; H25 written |
| `npm run build` in `ui/` shows no `automaticVercelMonitors` warning; UI tests pass | ✅ build succeeds; no Sentry warning (one unrelated Node `module.register()` notice). `ui/` has no test script |
| Engine commits use the noreply address, or a HUMAN_ACTION says how | ✅ H24 |
| Platform suite green | ✅ platform **2961 passed**, 579 skipped, 1 xfailed (H23); real-Postgres **565 passed** |
| Retro written; Phase B sprint specs drafted | ✅ this retro; Phase B specs are the next step (T-7) |

**Not run:** the SDK suite (no SDK change this sprint).

## Sprint-close security review

Not needed: the only `SECURITY-REVIEW:` commit (T-5) was built on Fable; the rest of the sprint
is configuration and docs.

## What we learned

- **A safe-looking convenience can be a deploy trigger.** The plan's `workflow_dispatch` for CI
  would have let a hand-run on `main` redeploy production, because the deploy waits on "any
  green CI on main". Read what listens to a workflow before adding a way to start it.
- **The engine's own guard rails decide what is `[human]`.** Two of five items (Fly config,
  git identity) are outside what the engine may touch; writing them up early kept the sprint moving.
- **Deleting production data needs a catalogue, not a guess.** The script is driven by the 74
  foreign keys to `agents`; any key without an explicit rule refuses.

## What we deferred (follow-ups)

- DrJ's H23 (scheduler size), H24 (commit email), H25 (remove test accounts). After H23, remove
  the xfail marker in `test_fly_vm_sizes.py`.
- Earlier items still open: H13/H14 (founders live, first outside agent), H12/H11 (PyPI),
  H15/H16 (publishing), H21 (VPS facts), D10.

## What changed strategically

Nothing. Phase A is merged and live; this sprint only tidies. Phase B planning is next.

## How the engine ran (calibration for DrJ)

- 7 cycles (96–102). T1 (Fable) once, for the script that deletes production data. T2 (Opus)
  for planning, CI, the Fly runbook, the commit-email lookup and this close. T3 (Sonnet) for
  the Sentry change.
- No step needed retries beyond normal self-correction.

## Next

T-7: draft the Phase B sprint specs (TypeScript SDK, developer docs and samples, VPS prep) and
decompose the first into `PLAN.md`. Merge briefing for this sprint:
`briefing_2026-10-07_sprint13.md`.
