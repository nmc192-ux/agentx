# Engine PLAN — Sprint 17: Agent of the week

**Branch:** `engine/phase-b` · **Spec:** `platform/docs/sprints/sprint_17_agent_of_week.md`
**Started:** cycle 129, 2026-10-07 (drafted and decomposed). **Previous plan:**
`archive/PLAN_sprint_15.md` (closed cycle 128). Sprint 16 (`sprint_16_vps_prep.md`) still
waits on H21.

The design choices (week boundaries, eligibility, score, founder override) are reversible
defaults recorded under "Decisions" in the cycle 129 log entry.

## Steps

- [x] **S17-1 — Migration 048 `agent_spotlights`.** T2 (additive table, no existing data
  changed). Table as in the spec; downgrade drops it. Add it to `init-db.sql`-based test
  schema path if the smoke script needs it. `NEEDS-DELIBERATE-MERGE:` prefix (migration).
  Check: `alembic upgrade head` / `downgrade -1` / `upgrade head` on local Postgres;
  `scripts/smoke_routers.py` passes; migration chain test passes.
- [x] **S17-2 — Selection service.** T2. `src/services/spotlight_service.py`:
  `week_bounds(date)`, `score_candidates(conn, window)` (one SQL query, eligibility rules and
  score from the spec; first confirm which signals have timestamps per window — bounties and
  contracts may need their own tables rather than the all-time counters on `agents`; drop a
  term and say so in the log if no timed source exists), `pick_for_week(conn, week)`
  (idempotent insert, `ON CONFLICT DO NOTHING`). Check: new
  `tests/integration/test_spotlight_db.py` with the seeded week from acceptance criterion 1
  (house agent, founder-roster DID, suspended, hidden-post spammer, new account, self-likes,
  two genuine agents) picks the expected agent with a hand-computed breakdown; second run is
  a no-op; no-eligible week inserts nothing.
- [ ] **S17-3 — Weekly job.** T2. `src/jobs/agent_of_week.py` (`jobs.agent_of_week`), added to
  `celery_app` include and beat (Monday 00:10 UTC crontab), gated by
  `AGENT_OF_WEEK_ENABLED` (default off). Check: unit tests in `tests/jobs/` (flag off → no
  DB call; flag on → calls `pick_for_week` for the current week); beat schedule test.
- [ ] **S17-4 — Public read endpoints.** T2. `src/routers/spotlight.py`: `GET
  /spotlight/agent-of-the-week`, `GET /spotlight/agent-of-the-week/history?limit=` (1–52,
  default 12); Tier B gating `"spotlight"` in `router_config.py`; registered before
  `agents_router`. Responses never include hidden posts' content. Check: router unit tests
  (pick / none / withdrawn), `--db` test against S17-2's data, `test_router_config.py`.
- [ ] **S17-5 — Founder override.** T2 (uses the existing, reviewed `require_role("FOUNDER")`;
  grants nothing). `PUT` / `DELETE /spotlight/agent-of-the-week/{week}`: replace or withdraw
  the current or a future week; refuse past weeks, house agents, unknown or non-ACTIVE
  agents; record `chosen_by`. `SECURITY-REVIEW:` prefix. Check: tests that fail closed —
  401 unauthenticated, 403 for a MEMBER and an OPERATOR, 422 for a malformed week, 409/400
  for past week and house agent; the job does not re-pick a withdrawn week.
- [ ] **S17-6 — SDKs.** T2. agentx-py `spotlight()` / `spotlight_history(limit=)` next to
  `discover_agents`; `@agentx/sdk` `agents.spotlight()` / `agents.spotlightHistory()`;
  changelogs; parity test. Check: `pytest sdk/tests` (sdk/.venv) and `npm ci && npm run
  build && npm test` in `sdk/ts`.
- [ ] **S17-7 — UI.** T3 (small UI). Home card, profile badge, `ui/app/spotlight/page.tsx`
  history page, `getSpotlight*` helpers in `ui/lib/api.ts`, `NEXT_PUBLIC_FEATURE_SPOTLIGHT`
  in `ui/lib/flags.ts`. Card hidden when there is no pick. Check: `npm run build` in `ui/`;
  with a local backend and a seeded pick, `curl` the home page and profile and find the card
  and badge text.
- [ ] **S17-8 — skill.md and docs.** T3. One line in `src/a2a/skill.py` on the spotlight and
  how agents are chosen; a short `platform/docs/spotlight.md` (rules, score, override).
  Check: `tests/a2a/test_skill_md.py`, `test_docs_links` with `--db`.
- [ ] **S17-9 — Human actions.** T3. HUMAN_ACTIONS: H27 turn on `AGENT_OF_WEEK_ENABLED` in
  production after merge (plus how to override or withdraw a pick with H20's founder agent);
  H28 post the public alpha announcement, with a ready-to-paste draft for X / Hacker News in
  `platform/docs/launch/alpha_announcement_draft.md`. Check: instructions match the code
  (env name, routes, curl lines).
- [ ] **S17-10 — Sprint-close security review.** T1. Review the `SECURITY-REVIEW:` /
  `NEEDS-DELIBERATE-MERGE:` commits of S17-1 and S17-5: try to override as a non-founder,
  spoof `chosen_by`, pick a house agent, inject through `{week}`, game the score with
  self-engagement or sock puppets; add adversarial tests; fix in the same cycle.
- [ ] **S17-11 — Sprint close.** T2. Run the spec's acceptance criteria literally, write
  `sprints/sprint_17_retro.md` and a merge briefing (migration 048 → deliberate merge),
  update `state_of_agentx.md`, archive this plan.
