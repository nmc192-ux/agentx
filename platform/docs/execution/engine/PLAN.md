# Engine PLAN — Phase B close

**Branch:** `engine/phase-b` · **Goal:** `strategy/strategic_plan_v2.md` §4 Phase B.
**Previous plan:** `archive/PLAN_sprint_18.md` (Sprint 18 closed cycle 159). Sprints 13–18 are
closed on the branch, not merged.

Every Phase B exit criterion still open needs DrJ or the outside world: `pip install
agentx-py` (H12) and `npm install @agentx/sdk` (H26) working, a public samples repo (H15), 100+
outside agents joined and posting, an outside agent with real trust, "Agent of the week" live
(merge + H27), the alpha announcement (H28). The engine's job now is to check nothing
engine-doable is left, then write the Phase B briefing.

## Steps

- [x] **PB-1 — Inventory engine-doable Phase B leftovers.** T2 (planning). Done cycle 160.
  Walked §4 Phase B, §9 and §11 of `strategic_plan_v2.md` and Appendix A of `magna_carta_v1.md`
  against the code and docs. Result:

  | Leftover | Status | Owner |
  |---|---|---|
  | `pip install agentx-py` works | built, published by H12 | DrJ |
  | `npm install @agentx/sdk` works | built (S14), published by H26 | DrJ |
  | Sample agents repo public | `agentx-examples/` built (S12); public by H15 | DrJ |
  | Quickstart zero-to-first-post < 10 min | met (S15: Python 7.6, TS 4.5 min) | done |
  | 100+ outside agents joined and posted | join paths built (S15, S18); needs the world | outside |
  | Outside agent with non-trivial trust | trust recalc live since S10; needs the world | outside |
  | "Agent of the week" live | built (S17); on by merge + H27 | DrJ |
  | Public alpha announcement | drafted; H28 | DrJ |
  | `trust_score_spec.md` (plan §11.2, "by end of Phase B") | **missing** | engine → PB-1a |
  | Protocol spec (Phase A carry-over) | `protocol/protocol_spec.md` exists; publish = H16 | DrJ |
  | Competitive scan (§11.6, magna carta Art. 5, quarterly) | **missing**, overdue since Q3 | engine → PB-1b |
  | Human role: operator vs co-participant (§11.5) | open; needs DrJ's call, not code | DrJ → D11 |
  | Synapse synergy (§11.1) | waits on DrJ's context | DrJ (unchanged) |
  | Pricing (§11.4) | deferred to Phase C start by the plan | Phase C |
  | Plan v2.x amendments (§10) | none written since v2; steward's job | DrJ (briefing proposes text) |

- [x] **PB-1a — Draft `strategy/trust_score_spec.md`.** Done cycle 161. T2 (documentation of an existing,
  already-reviewed service; no code change). The open *interface* only (magna carta Art. 14):
  what the score is, its range, the public endpoints and fields that expose it, recalc cadence,
  the inputs it is allowed to use, anti-collusion rules as decided in D7, versioning and what
  stays proprietary. Every claim checked against the code (`trust` service, recalc job, API).
  Check: file exists; every endpoint/field it names exists in the code (grep listed in the log).
- [x] **PB-1b — First competitive landscape scan `strategy/competitive_landscape_2026q4.md`.**
  Done cycle 162. T2 (research). Web research on agent social networks / agent registries / A2A platforms,
  dated sources, and what each means for AgentX's phases. Q3 was missed; this is Q4's.
  Check: file exists; every entry has a dated source link.
- [x] **PB-2 — Phase B briefing.** Done cycle 163 (`sprints/briefing_2026-10-08_engine.md`). T2. `sprints/briefing_<date>_engine.md` in the protocol's
  format: what merging the whole branch will do, the combined live-test checklist, the
  ordered DrJ list. Then report `PHASE_COMPLETE`.
  Check: briefing exists; status file says `PHASE_COMPLETE`.

### Urgent fix before the merge (DrJ's note, 9 Oct outage)

Production went down 9 Oct: the Upstash free plan ran out of requests (Celery broker polling)
and every API request crashed on the Redis error. DrJ will not pay for Redis.

- [x] **RF-1 — Redis-free scheduler, Redis fails open, founder LLM budget in Postgres.** Done
  cycle 164. T2 (scheduled jobs, configuration; calls the reviewed release/trust services
  without changing them) with `SECURITY-REVIEW:` / `NEEDS-DELIBERATE-MERGE:` commits for RF-2.
  `src/jobs/scheduler.py` (one process, `pg_try_advisory_xact_lock` + `scheduler_job_runs` so
  a job never runs twice), migration 049 (two new tables), Celery removed, rate limiter falls
  back to memory, cache/SSE/readiness/`REDIS_PASSWORD` fail open.
  Check: `tests/jobs/test_scheduler.py`, `tests/test_redis_fail_open.py` (API starts and answers
  in production mode with `REDIS_URL=memory://` and with a dead Redis — the outage reproduced
  before the fix), `tests/integration/test_scheduler_db.py` (`--once` with `REDIS_URL=memory://`
  against Postgres; lock, recent-skip, concurrency of the budget); full suite green.
- [human] **RF-1h — H34: one line in `fly.toml` (`scheduler = "python -m src.jobs.scheduler"`)
  in the same merge, then start the scheduler machine.** `tests/test_fly_scheduler_command.py`
  is xfail until then.
- [x] **RF-2 — T1 security review of the RF-1 commits.** Done cycle 165 (Fable). Reviewed
  `83c8330` + `000785f`; found 3 issues, fixed all with tests: (1) the per-DID rate-limit key
  function could raise on a crafted bearer token, which with the new fail-open limiter became an
  unlimited request on the public feed/discover routes; (2) no per-job timeout, so one hung job
  would stop every job including token auto-release; (3) the LLM budget read a naive time as
  local time. Lock/pooler, double-run, budget overspend, half-up Redis and readiness checked and
  recorded in `ENGINE_LOG.md`. Check: findings in the log; new tests green; full suite green.
- [x] **RF-3 — Refresh the Phase B merge briefing after RF-2.** Done cycle 166. T2. (A first refresh for RF-1
  was done in cycle 164.) Bottom line, shipped table, test counts, accepted no-Redis limits and
  the scheduler log check updated in `sprints/briefing_2026-10-08_engine.md`.

### Neon egress and free tiers (DrJ's note, 11 Oct suspension)

Neon's free plan was suspended 11 Oct (7.3 GB transfer against 5 GB; resets 1 Nov). DrJ will
not pay for any service and will wait until 1 Nov; nothing is merged or deployed before then.
Target: under 2 GB/month of database transfer. Order is DrJ's.

- [x] **EG-1 — Cap every list at 50.** Done cycle 167. T2. `src/middleware/list_limit.py`
  clamps any `limit` query parameter above 50 to 50 before routing (clamped, not rejected, so
  older SDKs/UIs keep working); `/agents` discovery slices to 50; consensus history default
  100 → 50; UI callers that asked for 100/200/500 now ask for 50 (they were getting 422s).
  Check: `tests/test_list_limit.py` (incl. a route walk: no `limit` default above 50); 11
  older "over-cap → 422" tests updated to "clamped to 50"; full suite green.
- [x] **EG-2 — Cursor paging on the chronological lists.** Done cycle 168. T2.
  `src/pagination.py` (opaque keyset cursor; bad cursor → 400). `cursor` + `next_cursor` on
  followers/following (created_at, agent_did) and notifications (is_read, created_at,
  notif_id); `cursor` + `X-Next-Cursor` header (CORS-exposed) on `/activity` and
  `/agents/{did}/activity-stream` (bodies are bare lists). `page` keeps working.
  Check: `tests/integration/test_cursor_paging_db.py` (11: no overlap/gaps incl. tied
  timestamps, a mid-walk insert does not shift pages, visibility kept on page 2, someone
  else's cursor reaches nothing, bad cursors 400) + `tests/test_pagination.py`.
- [x] **EG-2b — Cursor paging on the ranked feeds.** Done cycle 169. T2. `/feed/global`
  keyset on (score, created_at, post_id); `/feed` (personal) the same plus the ranking clock
  (`as_of`) in the cursor, so every page of one walk is scored against the same time instead
  of NOW(); `/feed/activity` (UNION) keyset on (created_at, id). All three return
  `X-Next-Cursor`. Check: 5 new walk tests in `tests/integration/test_cursor_paging_db.py`
  (ties, block filter on page 2, whole personal feed walked once, a fresh top post does not
  shift page 2, both kinds in the activity feed), bad cursors 400 on all three.
- [ ] **EG-2c — Cursor paging on the agent lists.** T2. `/agents` (list, sorted by trust),
  `/agents/{did}/feed`, `/agents/{did}/activity`, `/posts` and `/posts/global`
  (chronological, OFFSET + COUNT(*) today). Same approach: score-carrying keyset where the
  sort is a score, (created_at, id) where it is time; keep `page`.
  Check: same walk tests as EG-2/EG-2b.
- [ ] **EG-3 — In-process cache, no Redis.** T2. Small TTL cache (per machine) for the global
  feed, agent list/discover, trust score reads and `/.well-known/skill.md`, plus
  `Cache-Control` headers so Vercel/browsers reuse responses. Check: second call within the
  TTL does not touch the DB (test); stale after TTL.
- [ ] **EG-4 — In-memory per-IP limits on heavy public lists.** T2. Tighter per-IP slowapi
  limits on unauthenticated list routes (memory store, per machine). Check: 429 test per route.
- [ ] **EG-5 — Slim list payloads.** T2. List queries select only the columns the list shows
  (no `SELECT *`, no embeddings/full metadata, content truncated where the UI truncates).
  Check: response-shape tests; bytes-per-row before/after recorded.
- [ ] **EG-6 — UI: stop wide lookups and fast polling.** T2. Replace "fetch 50 followers to see
  if I follow X" with a cheap follow-status check; review UI polling intervals. Check: tsc,
  UI tests.
- [ ] **EG-7 — Egress estimate.** T2. Measure bytes per call locally for the main routes,
  combine with expected traffic, write `docs/execution/engine/egress_estimate.md` showing the
  monthly total against the 2 GB target.
- [ ] **FT-1 — Free-tier audit.** T2. Neon (CU-hours, transfer, storage), Fly, Vercel, Upstash
  against their free limits with estimated monthly use; fix anything near a limit.
- [ ] **DB-1 — Postgres on the Pink Popcorn VPS + 1 Nov runbook.** T2. Extend the Sprint 16 VPS
  plan (shared Caddy, backups to disk, no public DB port) and write the runbook: pg_dump from
  Neon, restore on the VPS, switch, verify, keep Neon as fallback. Files only.
- [ ] **BR-1 — Refresh the Phase B merge briefing** for EG/FT/DB. T2.
- [ ] **PC-0 — Plan Phase C** on this branch (decompose into PLAN.md). T2.

## Open human items touching the branch

H34 (fly.toml scheduler line, same merge, URGENT); D11 (human role, not blocking); merge (Sprints 13–18, migrations 048 and 049); H31–H33 (Sprint 18); H29, H30 (VPS); H26, H12
(publish); H27, H28.
