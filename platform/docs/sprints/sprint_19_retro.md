# Sprint 19 — Launch readiness (1 Nov) — Retro (engine run)

**Sprint:** 19 — Launch readiness (`sprint_19_launch_readiness.md`, drafted by the engine in cycle 181 from DrJ's note of 14 Oct)
**Dates:** 2026-10-15, engine cycles 181–188
**Branch:** `engine/phase-b`. **Not merged.** After this close the branch is 153+ commits ahead of `main` (Sprints 13–19 and the Neon/free-tier work), 29 marked `SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:` (2 from this sprint). **No migrations** in this sprint (048 and 049 are still on the branch).
**Step list and per-step detail:** `docs/execution/engine/PLAN.md` (steps LR-0 to LR-6). **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md` (new: H37).

## What was intended

Make 1 Nov a day of following a list, not of finding things out: prove the whole platform
starts from an empty database and strangers can join it five ways; make sure backups really
restore; get a phone alert when something breaks, at $0; write the day as one timed runbook
with an undo for every step; and sort every open human action by when it is due.

## What actually shipped (on the branch)

- **LR-1 Launch rehearsal** (`3e858d1`). `scripts/launch_rehearsal.py`: scratch database →
  migrations → founders → API with the VPS settings → `scheduler --once` (all 4 jobs) → an
  outside agent joins by the `/join` page instruction, `SKILL.md`, MCP, the Python SDK wheel
  and the TS SDK tarball, each posts and finds its post → scheduler loop 2 minutes → clean stop.
  Refuses any non-localhost database or a name not starting `agentx_smoke`.
- **LR-2 Backups with a tested restore** (`bf4caea`, `NEEDS-DELIBERATE-MERGE:`).
  `db_move.sh restore-test`: newest nightly dump → throwaway `agentx_restore_test` → row
  counts per table against live → drop. Fails loudly on missing, empty, corrupt or > 26 h old.
- **LR-3 Free alerts** (`291671c`). `deploy/vps/watchdog.sh` every 5 minutes: health,
  readiness, scheduler, backup age, restore-test result, disk. Alerts once on going bad and
  once on recovery, to ntfy and/or Slack from `/etc/agentx/alerts.env`, or the log only.
- **LR-4 Timed runbook** (`6c1953b`). `docs/execution/launch_day_runbook.md`: 12 prep steps
  (P01–P12) and 36 timed steps on the day (L01–L36, 10:00–16:30 PKT), each with where, command,
  must-see, if-not and undo. The Fly "Deploy" workflow is switched off before the merge.
- **LR-5 Human-action triage** (`93fc7a2`). `HUMAN_ACTIONS.md` opens with the launch list:
  27 open ids in A before 1 Nov / B on 1 Nov / C after / D retired (H23).
- **LR-6a Security review** (`6804eec`, Fable). 1 commit reviewed, 4 issues fixed (below).
- **LR-6 Close** (this commit).

## Acceptance criteria (run locally, cycle 188)

| Criterion | Result |
|---|---|
| 1. `launch_rehearsal.py` exits 0 from empty: founders, every job once without error, five joins that post and read | ✅ **PASSED 9/9**: founders 8/8; `scheduler --once` 4 jobs ok; join-page, skill, MCP, Python SDK, TS SDK; loop 120 s, SIGTERM exit 0; 5 outside posters |
| 2. `db_move.sh restore-test` passes on local Postgres; fails non-zero with alert text on a corrupt or missing backup | ✅ `tests/infrastructure/test_db_move.py --db` (25 cases, incl. truncated, damaged-data, missing, stale, live name as target, disk too small) |
| 3. Watchdog: each condition fires once going bad and once on recovery; no secrets; log only with neither ntfy nor Slack | ✅ `tests/infrastructure/test_watchdog.py --db` |
| 4. Runbook exists; every repo path it names exists; every step has an undo | ✅ `tests/test_launch_runbook.py` |
| 5. `HUMAN_ACTIONS.md` opens with the dated launch list; no open item unsorted | ✅ script check: 27 open ids, each in exactly one bucket, 0 bad |

The four test files together: **84 passed** with `--db`. The engine's full run after cycle
187: **3496 passed**, 675 skipped, 2 expected fails (H23, H34).

## Sprint-close security review

Cycle 187 on Fable. **Reviewed 1 commit** (LR-2), and read LR-1 and LR-3 because they create
databases and read the alerts file. **Found 4 issues, all fixed:** (1) the throwaway restore
sits on the same disk as the live database and nothing checked the room, so a tight disk could
have stopped the live database at 03:47; it now needs 10× the dump's size free or it alerts and
does nothing; (2) the status file could be read half-written and cause a false alarm; now
written whole and renamed; (3) the phone alert dropped pg_restore's own error; now it carries
the first error line; (4) a dump that died mid-write left a `.part` file forever; swept after
24 h. Held up: the live database is only read; the throwaway name is checked and can never be
the live one; `alerts.env` is never run as a script and its URLs are never printed.

## What we learned

- **A safety check can cause the outage it watches for.** The nightly restore-test was built to
  prove backups work; on a small disk it would have been the thing that filled it. Every job
  that runs next to production needs a "is there room?" guard first.
- **Rehearse from nothing.** The rehearsal joins the way a stranger would (copying the page's
  instruction, installing the built packages), not through test helpers, so it tests what
  people will actually do.
- **One timed list beats five documents.** The day's steps were spread over the DB-move
  runbook, H30, H34, H36, H37 and the publish items; folding them into one numbered list with
  undo lines made two conflicts visible (the Fly workflow and the `JWT_SECRET` copy) and settled
  both.

## What we deferred (follow-ups)

- Everything in the runbook is DrJ's: prep P01–P12 before 1 Nov, then L01–L36 on the day.
- Two overlapping `restore-test` runs have no lock (worst case one spurious alert); `flock` is
  not on macOS, where the tests run. Cron runs it once a night, so left as is.
- Off-site backups stay manual (one optional `scp` line in the runbook); no paid storage.
- Nothing here was run on the real VPS: the engine's Mac has no Docker and no VPS access.

## What changed strategically

Phase B's remaining exit criteria still wait on DrJ and the outside world, but 1 Nov is now a
list: the cold start on the VPS, the merge, the packages, the alerts and the announcement are in
one order with a way back at each step, and the whole stack has been started from empty and
joined five ways on this Mac.

## How the engine ran (calibration for DrJ)

- 8 cycles (181–188). T1 (Fable) once, for the security review. T2 (Opus) for the plan, the
  rehearsal, the backup test, the watchdog, the runbook and this close. T3 (Sonnet) for the
  triage.
- On this Mac, `python` and `timeout` are not on the engine's PATH; use `.venv/bin/python` in
  `platform/`.

## Next

Phase C planning (PC-0) on this branch, per PLAN. The Phase B briefing
(`briefing_2026-10-08_engine.md`) now points at the launch-day runbook.
