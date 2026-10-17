# Sprint 17 — Agent of the week — Retro (engine run)

**Sprint:** 17 — Agent of the week (`sprint_17_agent_of_week.md`, drafted by the engine in cycle 129)
**Dates:** 2026-10-07, engine cycles 129–140
**Branch:** `engine/phase-b`. **Not merged.** After this close the branch is 74 commits ahead of `main` (Sprints 13, 14, 15 and 17), 11 marked `SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:` (3 from this sprint). **One migration: 048** (new table `agent_spotlights`; no existing data touched).
**Step list and per-step detail:** `docs/execution/engine/archive/PLAN_sprint_17.md`. **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md` (new: H27, H28).

## What was intended

Meet the Phase B exit criterion "Agent of the week or equivalent feature live": each week the
platform picks one genuine outside agent from the previous week's activity, shows it on the
site, in the API and in both SDKs, and lets the founder replace or withdraw a pick. House
agents, suspended agents and spammers must never win. Also draft the public alpha announcement.

## What actually shipped (on the branch)

- **S17-1 Migration 048** (`e4605e7`, `NEEDS-DELIBERATE-MERGE:`). Table `agent_spotlights`, one
  row per ISO week (Monday CHECK), `chosen_by` CHECK, agent FK `ON DELETE SET NULL`. Downgrade
  drops the table.
- **S17-2 Selection service** (`bab6614`). One SQL query scores last week's outside agents
  (posts, replies received, likes received, distinct engagers, bounties won, contracts
  completed, trust); eligibility rules from the spec; idempotent `pick_for_week`.
- **S17-3 Weekly job** (`31c7842`). `jobs.agent_of_week` at ten past every hour, behind
  `AGENT_OF_WEEK_ENABLED` (off by default). Only fills a week that has no row.
- **S17-4 Read endpoints** (`16edb57`). `GET /spotlight/agent-of-the-week` and `/history`;
  router `spotlight`, kill switch works. Never shows post content.
- **S17-5 Founder override** (`6a6eef6`, `SECURITY-REVIEW:`). `PUT` / `DELETE
  /spotlight/agent-of-the-week/{week}`, FOUNDER only, current or future weeks only.
- **S17-6 SDKs** (`a3c60f0`). agentx-py `spotlight()` / `spotlight_history()`, `@agentx/sdk`
  `agents.spotlight()` / `agents.spotlightHistory()`.
- **S17-7 UI** (`20ee4eb`). Home card, profile badge, `/spotlight` page, behind
  `NEXT_PUBLIC_FEATURE_SPOTLIGHT`.
- **S17-8 Docs** (`d1f0dfb`). skill.md passage; `platform/docs/spotlight.md`.
- **S17-9 Human actions** (`5eb7a67`). H27 (switch it on), H28 (post the announcement) and
  `platform/docs/launch/alpha_announcement_draft.md`.
- **S17-10 Security review** (`3f68cff`, Fable). 2 commits reviewed, 3 issues found and fixed (below).

## Acceptance criteria (run locally, cycle 140)

| Criterion | Result |
|---|---|
| 1. Seeded week picks the expected agent; re-run is a no-op; breakdown matches hand numbers | ✅ `test_spotlight_db.py` + `test_spotlight_adversarial_db.py` in the `--db` run: genuine agent wins with 28 (others 21, 10); second run inserts nothing |
| 2. Override and withdraw work; non-founder 403; unauthenticated 401; house agent / past week refused | ✅ `tests/routers/test_spotlight.py` and the `--db` HTTP flow (401/403/409/400/200) |
| 3. GET answers for pick / no pick / withdrawn; history leaves out withdrawn weeks | ✅ tests, and by hand on a throwaway local DB: current pick returned, history showed the past pick and left out the withdrawn week |
| 4. Migration 048 up and down on local Postgres; smoke routers pass | ✅ fresh `init-db.sql → 048` chain, smoke green (100 GET routes, no 5xx); `downgrade -1` removed the table, `upgrade head` restored it |
| 5. SDK tests both languages; `ui` build; home page renders the card against a local backend | ✅ Python SDK **493 passed**; TS **141/141**; `npm run build` green. Against a real local backend with a seeded pick, curl found the pick on `/spotlight` and the badge on the profile. **Note:** the home card is drawn in the browser, so curl cannot see its text; curl confirmed the `/home` page ships the code that calls `/spotlight/agent-of-the-week`. Check it by eye after the merge (live-test checklist). |
| 6. Full platform suite green | ✅ platform **3059 passed**, 608 skipped, 1 xfailed (H23); real-Postgres `--db` integration **594 passed** |

## Sprint-close security review

Cycle 139 on Fable. **Reviewed 2 commits** (S17-1, S17-5) plus the scoring query.
**Found 3 issues, all fixed:** the weekly score could be bought cheaply with (1) brand-new sock
puppet accounts liking and replying, (2) one account replying many times to each post, and
(3) bulk posting. Now engagement counts only from accounts at least 7 days old, replies count
once per replier per post, and at most 10 posts count. The founder check, `chosen_by`, house
agent refusal and the `{week}` parsing all held. What remains by design: a ring of week-old
puppets still counts; suspending them removes their effect, and the founder can withdraw a pick.

## What we learned

- **Ranking features attract gaming first.** The first version counted every like and reply;
  the review showed a few minutes of scripting could win. Caps and an account-age floor belong
  in the first draft of any leaderboard.
- **Run hourly, act once.** Scheduling the job every hour instead of once a week costs one
  cheap query and means a worker that was down on Monday still picks that week.
- **Client-rendered pages need a browser check.** curl proves server pages; the home card needs
  a look in a real browser.

## What we deferred (follow-ups)

- DrJ: H27 (switch on the job and the website flag after merging), H28 (post the alpha
  announcement after the live checks). Everything already open stays open (H26, H12, H21,
  H23–H25, H13/H14, H11, H15, H16, D10).
- A cron-scheduled cleanup of withdrawn rows is not needed (one row per week).
- Rewards for the chosen agent are Phase C (money).

## What changed strategically

The "Agent of the week" exit criterion is met in code; it becomes live when DrJ merges and
does H27. The alpha announcement is drafted. Remaining Phase B exit items all need DrJ or the
outside world: publishing to PyPI and npm (H12, H26), the public samples repo (H15), the
announcement (H28), and 100 outside agents joining.

## How the engine ran (calibration for DrJ)

- 12 cycles (129–140). T1 (Fable) once, for the security review. T2 (Opus) for planning, the
  migration, service, job, endpoints, override, SDKs and this close. T3 (Sonnet) for the UI,
  docs and HUMAN_ACTIONS.
- Cycle 132 queued a note from DrJ but did not copy it into the repo. Only the engine's own
  summary of it survived (in the cycle 132 run record): a **distribution sprint** after Sprint
  17 with four items — an MCP server, an OpenClaw/Hermes skill, a browser-agent join test, and
  a "Join AgentX" page. Lesson: copy a DrJ note into `PLAN.md` the cycle it arrives.

## Next

Sprint 18, the distribution sprint above: the engine drafts its spec from those four items and
decomposes it next cycle. Merge briefing for this sprint: `briefing_2026-10-07_sprint17.md`.
Sprint 16 (VPS prep) still waits on H21.
