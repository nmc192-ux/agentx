# Sprint 22 — Collectives a newcomer can make in five minutes — Retro (engine run)

**Sprint:** 22 (`sprint_22_collectives.md`, planned by the engine in cycle 207; third sprint of Phase C, `phase_c_plan.md`)
**Dates:** 2026-10-15, engine cycles 207–216
**Branch:** `engine/phase-b`. **Not merged.** After this close the branch is 200+ commits ahead of `origin/main` (Sprints 13–22 and the Neon/free-tier work), 37 marked `SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:` (3 from this sprint). **Migration 051** (`collective_members.request_message`, additive nullable column).
**Step list:** `docs/execution/engine/PLAN.md` (CL-0 to CL-8). **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md` (new: H42).

## What was intended

Let an agent that has done one paid job create a collective (a "group"), let others ask to
join and be approved, and show the work the group has done, from the website, either SDK or
the MCP server, in under five minutes from a standing start. Everything ships **off** (or
unchanged), so 1 Nov launches exactly as rehearsed.

## What actually shipped (on the branch, switched off)

- **CL-1 Creation gate as settings** (`f3a364d`, Opus, `SECURITY-REVIEW:`). `COLLECTIVE_MIN_TRUST`
  (0.7, today's value), `COLLECTIVE_MIN_PAID_JOBS` (0 = off; H42 sets 1, counted from the
  ledger, self-payment excluded), `COLLECTIVE_CREATE_PER_DAY` (3, on from merge, under a
  per-agent advisory lock). Bad values fail closed.
- **CL-2 Membership reads** (`cf48bcd`, Opus, `SECURITY-REVIEW:`). Pending requests (ACTIVE
  OWNER/ADMIN only), the caller's own membership, the join note kept (migration 051).
- **CL-3 Work done** (`25d8def`). `GET /collectives/{id}/work`: tasks, counts, tokens earned
  from the ledger; cached 60 s; private groups hidden from non-members.
- **CL-4 Create form** (`282db5b`) and **CL-5 group page** (`d0285f9`) on the website, behind
  `NEXT_PUBLIC_FEATURE_COLLECTIVES` (off).
- **CL-6 Client parity** (`162d977`). Python and TS `requests`, `membership`, `work`, `leave`
  (TS also `assignTask`); `collective_type` deprecated; MCP `agentx_create_collective`,
  `agentx_join_collective`, `agentx_approve_member`. Versions unchanged, nothing published.
- **CL-7 Five-minute check** (`057570b`). `scripts/collective_journey.py` (run by
  `launch_rehearsal.py --economy`) and the website checklist `sprint_22_stranger_checklist.md`.
- **CL-8a Security review** (`7d92ee3`, Fable). Reviewed 7 commits, found 4 issues, fixed 4.
- **CL-8 Close** (this commit). H42 "switch on groups for newcomers" added for after 1 Nov.

**Live from the merge without a switch** (tighter only, nothing new opens): at most 3 groups
per agent a day; a private group's profile, members and work are 404 to non-members; only the
OWNER removes an ADMIN; a banned agent stays banned; a task belongs to one group.

## Acceptance criteria (run locally, cycle 216)

| Criterion | Result |
|---|---|
| `collective_journey.py` from an empty DB: faucet → paid task → creates a group → second agent asks → approved → task shows under work done; exit 0, wall time < 300 s | ✅ inside `launch_rehearsal.py --economy` (see below) |
| `COLLECTIVE_MIN_PAID_JOBS=0` (default): a 0.5-trust agent with paid jobs is still refused 403 | ✅ `test_collective_gate.py` + `integration/test_collective_gate_db.py --db` |
| Collectives unit suites (gate, membership, work, security review, journey) | ✅ **137 passed**; `--db` (gate, membership, work, review) **19 passed** |
| `launch_rehearsal.py` 9/9 off and `--economy` (now 11 checks: the spec's 10 plus the collectives journey) | ✅ **PASSED 11/11** at `1674d6e` (9 launch checks with everything off, the 10-step economy journey, the 9-step collectives journey in 0.8 s) |
| Python SDK, TS, MCP suites | ✅ Python SDK **523 passed**; TS build OK + **167 passed**; MCP **125 passed** |
| `npm run build` for `ui/` | ✅ build OK (flag off, the default) |

## Sprint-close security review

Fable, cycle 215: **reviewed 7 commits (2 marked, 5 unmarked that touch membership), found 4
issues, fixed 4** (`7d92ee3`, 39 tests): a private group's profile and member list were
visible to anyone with its id; an ADMIN could remove another ADMIN; a banned agent could lift
its own ban and ask again; one task could be shown as work done by several groups.

**Known limits, not holes (for Sprint 23 or later):** `POST /join` tells anyone holding a
private group's UUID that it exists (asking is the only way in; ids are not guessable);
`GET /posts/{id}` (Phase 1 code) shows a COLLECTIVE-visibility post to anyone with the post id;
flooding an owner's pending list costs one agent per row (list capped at 200).

## What went well

- The plan carried the two items CL-0 found (private read, ADMIN removing ADMIN) straight to the
  Fable review, which closed both and found two more.
- One command (`launch_rehearsal.py --economy`) now proves faucet → paid work → group → join →
  approve → work done against the ledger from an empty database.

## What didn't

- The four review findings sat in the older collectives routes this sprint built on (private
  read, removal, leave, task assignment), not in the sprint's new reads; earlier reviews only
  looked at their own diffs, so this code had never been tried by an attacker before.
- The plan had the task poster hand work to the group; the API only lets an OWNER/ADMIN who is
  the poster or the doer do that, so the journey uses the doer. Fine, but the plan was written
  without checking that rule.
- The five-minute website path is checked by a script and mocked browser tests only; the timed
  check with real people is the checklist in H42 step 3.

## Decisions made by the engine (reversible)

- No collective treasury (founding documents do not call for one).
- The join note is a column (migration 051), not dropped from the docs.
- Work done shows the task's own status, the 50 newest tasks, titles capped at 200 characters.
- The collectives journey runs whenever `--economy` does (no separate flag).
- New TS methods are `async`; MCP routes pinned as gated on `collectives`.

## Next

Sprint 23 — Phase C metrics and close (`phase_c_plan.md`): decompose next cycle. Nothing from Sprint 22 changes 1 Nov
beyond the tighter rules above unless DrJ does H42 (and D13 says Phase C work rides along
switched off).
