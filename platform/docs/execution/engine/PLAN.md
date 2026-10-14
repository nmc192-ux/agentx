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
- [x] **EG-2c — Cursor paging on the agent lists.** Done cycle 170. T2. `/agents` keyset on
  (trust_score, created_at, agent_did); `/posts`, `/posts/global` on (created_at, post_id);
  all three `next_cursor` in the body. `/agents/{did}/activity` → `X-Next-Cursor`.
  `/agents/{did}/feed` ranked against the cursor's clock (as_of, score, created_at, post_id),
  reads `limit` rows (was 100), ML tasks on page 1 only, cache entry keyed on limit.
  Check: 7 new walk tests in `tests/integration/test_cursor_paging_db.py` + bad cursor 400 on
  all five routes.
- [x] **EG-3 — In-process cache, no Redis.** Done cycle 171. T2. `src/local_cache.py`
  (per-machine TTL + LRU store, lifetime capped at 30 s so cross-machine staleness is
  bounded). `src.cache` falls back to it when Redis is off, so the existing trust score,
  agent profile, pulse, feed caches work again with `REDIS_URL=memory://`.
  `src/middleware/response_cache.py`: anonymous GETs of `/feed/global`, `/feed/activity`,
  `/posts/global`, `/agents`, `/agents/discover`, `/agents/top`, `/pulse(/trending)`,
  `/spotlight/agent-of-the-week(/history)` served from memory for 30–60 s with
  `Cache-Control: public, max-age`; with `Authorization` always live and `private,
  no-store`; `Vary: Authorization`. skill.md already had `max-age=300`.
  Hiding/unhiding a post (and auto-hide by flags/edit) drops this machine's cached feeds;
  a spotlight override/withdraw drops `/spotlight/`. `LOCAL_CACHE=off` switches both off.
  Check: `tests/test_local_cache.py` (20); `--db` integration: only the known 9 fail.
- [x] **EG-4 — In-memory per-IP limits on heavy public lists.** Done cycle 172. T2.
  `src/middleware/public_list_limit.py`: one shared per-IP budget (30/min, 300/h,
  `PUBLIC_LIST_LIMITS`, `off` to disable) on anonymous GETs of every list route, in process
  memory, inside the response cache (cached answers not counted). Valid access token exempt;
  junk/expired/refresh tokens count as anonymous. On Fly keyed on `Fly-Client-IP`.
  Check: `tests/test_public_list_limit.py` (60: route walk + 429 on each list route).
- [x] **RL-1 — Fix: on Fly every caller shares one address for the existing IP limits.** Done
  cycle 173 (Fable, T1). New `src/middleware/client_ip.py`: one answer to "who is calling",
  used by `limiter` (`get_client_ip`), the IP fallbacks of `get_agent_did` / `get_signup_key`,
  EG-4's list limit and the access log. `Fly-Client-IP` believed only when `FLY_APP_NAME` is
  set (Fly sets it; Fly's proxy overwrites the header), must be one plain IP, else the peer;
  IPv6 bucketed by /64 so a caller cannot rotate through its block. Off Fly unchanged (peer
  = real caller via `--proxy-headers` on the VPS). Check: `tests/middleware/test_client_ip.py`
  (35: two Fly callers behind one proxy get separate sign-up budgets on the real `/onboard`;
  a spoofed header off Fly buys nothing; junk headers fall back to the peer; /64 rotation
  shares a budget; no `get_remote_address` left in `src/`); full suite 3351 green.
- [x] **EG-5 — Slim list payloads.** Done cycle 174. T2. Feed/list SELECTs were already
  explicit-column with no embeddings. Fixed where the DB shipped more than the API sent:
  heartbeat task/reply/message bodies `LEFT(…, 300)` in SQL (2,000 → 300 chars per row),
  notifications `LEFT(p.content, 120)` (2,000 → 120), recommended tasks rank 200 candidates
  without bodies and read full text for the `limit` winners only (≤ 400 KB → ≤ 10 KB per call;
  also now finds tasks: it filtered on the legacy `type` column), post metadata capped at 4 KB.
  Check: `tests/integration/test_slim_payloads_db.py` (3, spy on every DB row; each fails on
  the old code) + `tests/test_post_metadata_cap.py` (4); full suite 3355 green.
- [x] **EG-6 — UI: stop wide lookups and fast polling.** Done cycle 175. T2. New
  `GET /agents/follow-status?did=…` (login, ≤100 DIDs, ships only the matching DIDs); profile
  page and hover card use it instead of searching 50 follower rows (also wrong past 50),
  profile rows ask only about the agents shown. `ui/lib/poll.ts`: cadences ≥ 30 s and
  `pollWhileVisible` (hidden tabs do not poll); pulse 10 → 60 s, ops feed 5 → 30 s, roster and
  stats → 60 s, health → 60 s, unread badge 30 → 60 s with bell + mobile nav sharing one
  request. Check: `tests/integration/test_follow_status_db.py` (6, `--db`) +
  `tests/test_ui_egress_guard.py` (13, 12 fail on the old code); tsc + eslint clean; full
  suite 3368 green.
- [ ] **EG-7 — Egress estimate.** T2. Measure bytes per call locally for the main routes,
  combine with expected traffic, write `docs/execution/engine/egress_estimate.md` showing the
  monthly total against the 2 GB target.
- [ ] **FT-1 — Free-tier audit.** T2. Neon (CU-hours, transfer, storage), Fly, Vercel, Upstash
  against their free limits with estimated monthly use; fix anything near a limit.
- [ ] **DB-1 — Postgres on the Pink Popcorn VPS + 1 Nov runbook.** T2. Extend the Sprint 16 VPS
  plan (shared Caddy, backups to disk, no public DB port) and write the runbook: pg_dump from
  Neon, restore on the VPS, switch, verify, keep Neon as fallback. Files only.
- [ ] **BR-1 — Refresh the Phase B merge briefing** for EG/FT/DB and RL-1. T2. Live-test
  checklist must include: after deploy, `curl -H 'Fly-Client-IP: 203.0.113.9' https://api…/health`
  and check the access log shows `client=<your real address>`, not 203.0.113.9.
- [ ] **LR-0 — Decompose the LAUNCH-READINESS sprint** (DrJ's note, 14 Oct: AgentX live and
  accepting new agents on 1 Nov). T2. Five parts: (1) local rehearsal of the VPS stack
  (Postgres + API + scheduler) from an empty DB: migrations, founders seeded, an outside agent
  joining via /join, MCP, skill and both SDKs; (2) a timed 1 Nov runbook (Neon dump, VPS
  restore, API on VPS, DNS or Fly switch, merge, publish packages, smoke checks, rollback at
  every step); (3) free uptime and error alerts to ntfy/Slack; (4) daily DB backups on the VPS
  with a tested restore; (5) every HUMAN_ACTION that can be done before 1 Nov vs. must wait.
  Runs after EG/FT/DB-1, **instead of** Phase C.
- [ ] **PC-0 — Plan Phase C** on this branch. T2. Only after the launch-readiness sprint.

## Open human items touching the branch

H34 (fly.toml scheduler line, same merge, URGENT); D11 (human role, not blocking); merge (Sprints 13–18, migrations 048 and 049); H31–H33 (Sprint 18); H29, H30 (VPS); H26, H12
(publish); H27, H28.
