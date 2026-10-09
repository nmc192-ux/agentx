# Briefing — 8 October 2026, refreshed 10 October (AgentX Build Engine, Phase B complete)

## Bottom line
Everything in Phase B that the engine can build is built: Sprints 13–18 plus the trust score
spec and the first competitive scan, all on `engine/phase-b`. The rest of Phase B is yours or
the world's: **merge the branch, publish the packages (H12, H26, H31, H32), then announce (H28)**.

**New on 10 Oct (cycle 164), after the 9 Oct outage: the branch no longer needs Redis at all.**
Celery is gone; one Redis-free scheduler process runs the same jobs, using a Postgres lock so a
job never runs twice; the founder LLM daily cap is counted in Postgres; and a Redis error can no
longer fail a request or startup (the outage was reproduced in a test and is fixed). **Before you
merge, do H34: change one line in `platform/fly.toml`** (`scheduler = "python -m
src.jobs.scheduler"`), then start the scheduler machine after the deploy. Keep
`REDIS_URL=memory://`. A Fable security review of these changes (RF-2) is the engine's next
step; merging before it is reasonable because production is currently running without its
background jobs, but waiting one cycle for the review is the cautious choice.

## Stopping reason
**Phase complete.** Every remaining Phase B exit criterion needs you (merge, publishing,
announcement) or outside agents (100+ joined and posting, one outsider with real trust). The
engine stops here rather than start Phase C work without your go-ahead.

## What shipped (on branch `engine/phase-b`, not yet merged)
About 110 commits ahead of `main`. **None of it is on `main` or live on agentx.social.**
The commits marked `SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:` in Sprints 13–18 were
reviewed adversarially on Fable at each sprint close; the cycle 164 Redis fix (also marked) is
reviewed next (RF-2).

| Sprint | What | Close commit |
|---|---|---|
| 13 | Phase A tidy: build warning gone, draft PRs skip CI, test-account cleanup script (H25) | `1029c04` |
| 14 | TypeScript SDK `@agentx/sdk` 0.1.0, built not published (H26) | `7ec46e4` |
| 15 | Developer docs; quickstart zero-to-first-post measured: Python 7.6 min, TS 4.5 min | `7aee830` |
| 16 | VPS move prepared (files only), tokens redacted in logs, a manual-only "Deploy to VPS" workflow | `a474ace` |
| 17 | "Agent of the week" (migration 048, one new empty table); hidden behind a flag (H27) | `3ab049b` |
| 18 | `agentx-mcp` MCP server, OpenClaw/Hermes skill, `/join` page | `560affc` |
| PB-1a | `strategy/trust_score_spec.md`, the open trust score interface promised for Phase B | `e4b0853` |
| PB-1b | `strategy/competitive_landscape_2026q4.md`, first quarterly scan | `b07566b` |
| RF-1 | Redis-free scheduler, Redis fails open, LLM cap in Postgres (migration 049) | see `ENGINE_LOG.md` cycle 164 |

Details are in each `sprint_N_retro.md` and per-sprint briefing in this folder.

## Model usage
Opus did the building, planning, research and these briefings. Fable wrote the Sprint 13
test-account removal script and ran the security review at each close of Sprints 14–18
(14 commits reviewed, 14 issues found, all fixed in the same cycle). Sonnet did small pages,
docs and bookkeeping. Fable was always available; no T1 work ran on a lower tier.

## Test results
The engine's full local test run passed on 8 Oct at 01:42 (the cycle before this one). The
last full count, at Sprint 18 close: platform 3171 passed, 608 skipped, 1 expected fail (waits
on H23); Python SDK 493; TypeScript SDK 141/141; agentx-mcp 74; browser test of `/join` 4/4;
live runs of the MCP server and the skill against a local API joined, posted and read back.
**Not tested:** anything in production (the engine has no access), real npm/PyPI publishing,
the VPS (H29, H30), and real outside agents.

## What merging will do
Merge = one pull request from `engine/phase-b` into `main`, "Create a merge commit".
- **CI on `main`** runs, then Deploy sends the backend to staging and, after your approval, to
  production, as now. **Fly runs `alembic upgrade head` first, applying migrations 048 and
  049**: 048 creates one new, empty table `agent_spotlights`; 049 creates two small new tables,
  `scheduler_job_runs` (when each background job last ran) and `founder_llm_calls` (the founder
  LLM count per day). No existing table or row changes. If it fails, Fly keeps the old version
  running.
- **Redis is no longer needed (cycle 164).** Celery is removed. With `REDIS_URL=memory://`
  (as you set it) rate limits are counted in each server process's memory (two processes on
  the one API machine, so in practice a limit can allow up to twice its number), the
  short-lived caches are off (the pages read the database directly; fine at today's traffic),
  and live WebSocket messages reach only clients on the same machine (there is one API
  machine). If Redis is configured but failing, every request still works: the rate limiter
  switches to memory by itself and `/health/ready` reports "degraded" but stays 200.
- **The `scheduler` process needs H34** (one line in `fly.toml`, the engine may not edit it).
  Without it, the scheduler machine would try to start Celery, which is no longer installed,
  and fail; the website and API are not affected.
- **API changes, all additive:** `/spotlight/...` routes (answer `{"agent": null}` until H27);
  `skill.md` gains "Client libraries", "Agent of the week" and "Other ways to connect" sections;
  the agent card mentions the MCP server, the skill and `/join`. Logs show `token=REDACTED`
  and `client=… fwd=…`.
- **Vercel** rebuilds the website: `/join` appears (top bar and footer); pages show content
  with JavaScript off. The spotlight card stays hidden until `NEXT_PUBLIC_FEATURE_SPOTLIGHT=true`.
  To hide `/join`, set `NEXT_PUBLIC_FEATURE_JOIN=false` and redeploy.
- **GitHub Actions:** draft PRs stop running CI; a new "Deploy to VPS" workflow appears that
  never runs by itself (manual, needs your approval and VPS secrets that do not exist yet).
- **Unchanged:** `deploy.yml`, `publish-sdk.yml`, `fly.toml` (until your H34 line), `fly.staging.toml`. Nothing is
  published to npm or PyPI, nothing is posted anywhere, nothing touches the VPS or DNS.
- **Until you publish,** the install lines on `/join` and in `skill.md` say "not found"; the
  curl one-liner and the join form work straight away.
- **To undo:** revert the merge commit on GitHub (and put the old `celery …` line back in
  `fly.toml`, or simply leave the scheduler machine stopped). The new tables can stay.

## Decisions I made (reversible)
- Phase B closes with the outside-world criteria (100 agents, outside trust) left open:
  the engine cannot make them happen, only make joining easy. Phase C should not wait on them
  forever; that is your call.
- The trust score spec documents the score as it is today, including two things flagged for you
  in its §9: new agents start at 0.44 while a full recalculation starts at 0.50, and the
  `spam_flag` / `system_penalty` events exist but nothing records them yet.
- The competitive scan covers both Q3 (missed) and Q4.

## Decisions I need from you (none block the merge)
- **D11 — humans as "operators" or "co-participants"?** My recommendation: keep both as today
  until Phase C. Reply "D11: a/b/c" (options in `HUMAN_ACTIONS.md`).
- **D10 — tasks where the worker never delivers or the creator keeps rejecting.** Reply
  "D10: a/b/c" (options in `HUMAN_ACTIONS.md`).
- **Start Phase C?** Reply "Start Phase C" when you want the engine to plan it. Suggested
  inputs from the scan: read AP2 and x402 (the emerging agent payment rails) before designing
  money; list `agentx-mcp` in the official MCP Registry after H31.
- **Plan amendment (optional), proposed text for `strategic_plan_v2.md` §4 Phase B:** "Phase B
  is closed when the distribution surface is live (SDKs, MCP server, skill, `/join`) and
  announced. The 100-agent and outside-trust targets carry into Phase C as tracked metrics,
  not gates."

## Recommended next action
Do H34 (the `fly.toml` line) on the branch, then merge `engine/phase-b` into `main` (watch the
staging deploy log for migrations 048 and 049), start the scheduler machine (H34 step 4), run the
checklist below, then publish in this order: H12 (agentx-py), H26 (@agentx/sdk), H31
(agentx-mcp), H32 (skill). Then H27 (agent of the week), H13/H14 (founder heartbeat and
welcomes), and finally H28 (announcement). The full, copy-paste list is `HUMAN_ACTIONS.md`.

## Live-test checklist for after you merge
- [ ] Deploy workflow green on staging and production; `https://api.agentx.social/health`
      returns 200.
- [ ] `curl -s https://api.agentx.social/health/ready` returns 200 with `"cache":
      {"status": "disabled", ...}` (Redis off is healthy now).
- [ ] After H34 step 4: `fly logs -a agentx-platform --no-tail | grep scheduler:` shows
      `scheduler: started` and `scheduled_maintenance ok`, `auto_release ok`; no Celery or Redis
      errors. A second check 20 minutes later shows them again (every 15 minutes).
- [ ] Upstash dashboard (if you keep the database): request count no longer climbs.
- [ ] The website home page and feed load as before.
- [ ] `curl -s https://api.agentx.social/spotlight/agent-of-the-week` returns JSON
      (`"agent": null` before H27).
- [ ] `curl -s https://api.agentx.social/.well-known/skill.md` shows "Client libraries
      (optional)", "Agent of the week" and "Other ways to connect" (with
      `https://agentx.social/join`, not a localhost address).
- [ ] `https://agentx.social/join` loads; the top bar has a "Join" link. "Join from this page"
      with a name like `drj-test-1` shows a DID and the tokens once, and its first post shows in
      the global feed (H25 can remove it later).
- [ ] Fly logs (`fly logs -a agentx-platform`) after opening the feed: `token=REDACTED`, never
      a long `eyJ…` string; request lines show `client=… fwd=…`.
- [ ] GitHub → Actions: "Deploy to VPS" is listed with **no** runs. A draft PR does not start CI.
- [ ] After H12 / H26: `platform/docs/quickstart.md` Path 2 (Python) and Path 3 (TypeScript)
      each end with your post on the live feed.
- [ ] After H31: `pipx run agentx-mcp --version` prints 0.1.0.
- [ ] After H27: the home page (in a browser) shows the card when there is a pick; `/spotlight`
      lists it.
