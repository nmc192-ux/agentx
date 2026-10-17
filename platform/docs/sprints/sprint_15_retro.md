# Sprint 15 — Developer docs and samples in two languages — Retro (engine run)

**Sprint:** 15 — Developer docs and samples (`sprint_15_dev_docs.md`, drafted by the engine in cycle 103)
**Dates:** 2026-10-07, engine cycles 115–128
**Branch:** `engine/phase-b`. **Not merged.** After this close the branch is 53 commits ahead of `main` (Sprints 13, 14 and 15), 8 marked `SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:` (4 from this sprint). No migrations. The only backend change is the text of `/.well-known/skill.md`.
**Step list and per-step detail:** `docs/execution/engine/archive/PLAN_sprint_15.md`. **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md` (no new items; H15 and H26 updated).

## What was intended

Make a stranger's first ten minutes work in both Python and TypeScript: a quickstart for each,
measured from cold; the five sample agents in TypeScript too; skill.md and the READMEs written
for someone who has never heard of AgentX; and the agentx-py path fix carried over from Sprint 14.

## What actually shipped (on the branch)

- **S15-1 agentx-py path segments** (`8cb3f21`, `SECURITY-REVIEW:`). Every id put into a URL
  (71 places) goes through `_seg()`: a slash is refused before any request, the rest is
  percent-encoded. A test fails if a new unwrapped path appears.
- **S15-2 TS wallet, governance, collectives** (`e4cda85`, `SECURITY-REVIEW:`). Same routes and
  bodies as Python, pinned by 20 parity checks. Closes the last gaps the samples needed.
- **S15-3 to S15-5 TS samples** (`570aa76`, `5e5dd6a`, `f458fda`). `agentx-examples/ts/` with all
  five patterns, each tested against the real local stack with the same behaviour as its Python twin.
- **S15-6 Quickstart Path 3: TypeScript** (`2a145d3`). Every code block is run by the test.
- **S15-7 Timed cold run** (`96c534c`). Python 7.6 min, TypeScript 4.5 min, reading time
  included (`sprint_15_journey_local.md`). The quickstart's title now says ten minutes, not five.
- **S15-8 skill.md names both libraries** (`6d82473`, `NEEDS-DELIBERATE-MERGE:`). Version-pinned
  install lines, with what to do while they are unpublished.
- **S15-9, S15-10 Front-door docs.** Stranger checklist; root README, `sdk/README.md` and the
  samples README rewritten against it; a link-check test over six docs.
- **S15-11** H15 and H26 brought up to date.
- **S15-12 Security review** (`ae77a8d`, Fable). 3 commits reviewed, 1 issue found and fixed (below).

## Acceptance criteria (run locally, cycle 128)

| Criterion | Result |
|---|---|
| Both quickstarts under ten minutes, measured cold | ✅ Python 7.6 min, TS 4.5 min (cycle 122); `test_quickstart_db.py --db` passes |
| TypeScript samples pass against the local stack | ✅ `test_ts_samples_db.py --db` 5 passed; Python samples still pass |
| READMEs reviewed against the stranger checklist | ✅ checklist ticked for all four docs; `test_docs_links.py` 6 passed |
| H15 still accurate | ✅ checked cycle 126 (notes `ts/` and its `file:` dependency) |
| Full suites | ✅ platform **2970 passed**, 586 skipped, 1 xfailed (H23); SDK **480 passed**; npm **139/139**; the `--db` integration set (TS samples, quickstart, Python samples, TS SDK live, links) **22 passed** |

## Sprint-close security review

Cycle 127 on Fable. **Reviewed 3 commits** (S15-1, S15-2, S15-8). **Found 1 issue, fixed:** the
deprecated TypeScript `AgentClient`, still exported, put ids into paths raw. `fetch()` folds `..`
away, so `getProfile("../tasks/X/approve")` called the task-approval route. All its ids now go
through `seg()`, and a TS source-scan test (mirroring the Python one) stops a new raw path.

## What we learned

- **Old code shipped beside new code needs the same rules.** The fix went into the new client;
  the deprecated one, still in the package, was missed until the review looked at everything exported.
- **Measure, then change the promise.** The quickstart promised five minutes; a cold Python
  install alone takes 3.5. The docs now promise what was measured.
- **Running every doc block in a test pays off.** The TS quickstart and samples could not drift
  from the SDK without a test failing.

## What we deferred (follow-ups)

- DrJ: H26 (npm) and H12 (PyPI) gate every install line in the docs; H15 (public samples repo)
  needs the TS samples' `file:` dependency switched to `^0.1.0` after H26. Everything already
  open stays open (H23–H25, H13/H14, H11, H16, H21, D10).
- The deprecated TS `AgentClient` could be removed in `@agentx/sdk` 0.2.0.

## What changed strategically

Nothing. "Developer quickstart proves the zero-to-first-post path under ten minutes" is met
locally in both languages. The rest of the Phase B exit list is publishing (DrJ), real outside
agents, an "Agent of the week" feature and the public alpha announcement.

## How the engine ran (calibration for DrJ)

- 14 cycles (115–128). T1 (Fable) once, for the security review. T2 (Opus) for planning, the
  path fix, the TS SDK additions, the samples, the quickstart, timing, skill.md and this close.
  T3 (Sonnet) for the READMEs, checklist and HUMAN_ACTIONS bookkeeping.
- No interrupted cycles.

## Next

Sprint 16 (VPS prep) still waits on H21. The engine will plan the next Phase B sprint it can do
without DrJ: "Agent of the week" (an exit criterion). Merge briefing for this sprint:
`briefing_2026-10-07_sprint15.md`.
