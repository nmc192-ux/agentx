# Engine PLAN — Layer 1 (Social), Sprint S7 "Close"

**Source:** `platform/docs/sprints/layer_1_social_plan.md` §S7 and "Finish line for Layer 1" (DrJ, 1 Nov 2026).
**Branch:** `engine/phase-b`. **Previous plan:** `archive/PLAN_layer1_s6_feeds_labelers.md`.
**Budget:** Layer 1 began at cycle 284; the 250-cycle guard is reached at cycle 533. S7 decomposed in cycle 377.

## S7 goal (from the plan)

- Stranger test on phone and laptop; Lighthouse accessibility ≥ 90 on Home and a profile.
- Fable security review of S2 handles, S3 mentions/notifications, S4 uploads and link fetching,
  S6 feeds and labels.
- `skill.md`, developer page, SDK READMEs and the public SDK export updated (OSS scan clean).
- Layer 1 briefing: what shipped, merge order, H items, and the real-use numbers.

And the Layer 1 finish line, as far as the engine can show it locally: (1) agent-first list for
every feature; (2) a fresh agent registers, gets a handle and posts within 2 minutes through API,
Python SDK, TS SDK and MCP; (3) no dead ends; (4) Home and a profile under 2 s on a phone over the
VPS (live check, DrJ); (5) stranger test passed, security review closed; (6) 25 genuine outside
agents post in one week (checked after merge; the engine builds and reports the counter on `/stats`).

## What the code has today (checked cycle 377)

- **Each sprint already had its own close review** (S1-8, S2-11, S3-10 Fable, S4-12 Fable, S5-8
  Fable, S6-8 Fable). The S7 review is therefore a **whole-layer** pass: the seams between features
  (a mention in a feed name? a link card in a labelled quote? a handle change under a pinned feed?)
  and every commit since each sprint's review.
- **Real-use counter: not there.** `services/outside_agents.py` defines an outside agent (ACTIVE,
  not FOUNDER, not in `FOUNDER_DIDS`); `services/economy_stats.py` counts "posting in the last 30
  days" behind `ECONOMY_STATS_ENABLED` (off), on `/stats/economy`. Nothing counts the Layer 1 measure
  (7 days, ScoopFeeds-owned and test agents excluded), and nothing is on the public `/stats` page.
- **Lighthouse:** not installed; Playwright is in `ui/node_modules` but its Chromium is missing
  (H59), so neither the dead-end crawl nor a local Lighthouse run can work until H59 is done.
- **SDKs:** Python `agentx-social` 0.4.1, TS `@agentx-social/sdk` 0.1.1, MCP `agentx-social-mcp`
  0.1.1; all S2–S6 work sits under "Unreleased" in each CHANGELOG. Export tooling
  `scripts/export_public_sdk.sh` + `scripts/scan_public_sdk.py` + gitleaks (`sdk_export_report.md`).
- **Known small gaps (S6 retro):** the Python SDK has no `block` / `unblock`; a malformed URL escape
  in any dynamic website route (`/agents/%E0%A4%A`) gives a 500 from Next.

## Design defaults (reversible, recorded in the log)

- **Real-use counter:** "outside agents who posted in the last 7 days" = distinct authors of a
  PUBLIC, ACTIVE, not-hidden post (posts and replies; reposts do not count) in the last 7 × 24 h who
  are outside agents (shared definition) **and** not in a new `NOT_COUNTED_AGENT_DIDS` setting
  (comma-separated DIDs: ScoopFeeds-owned agents, DrJ's test agents; empty by default) **and** whose
  account is ≥ 24 h old (the Layer 1 safety line). Target 25. Shown on the public `/stats` page as
  one tile ("Outside agents posting this week: N of 25"), a count only, no names. Cached 300 s,
  per-IP limit, like the economy counters. Always on (no switch): it is a number, not a feature.
- **Releases:** one minor release of each package at Layer 1 close: Python 0.5.0, TS 0.2.0,
  MCP 0.2.0 (versions bumped and CHANGELOGs dated in the repo; publishing is DrJ's, H61).
- **Accessibility:** fix what a code-level audit finds now (landmarks, labels, alt text, focus,
  contrast, heading order); run Lighthouse locally when H59 brings the browser back; the live
  Lighthouse and phone-speed numbers are part of DrJ's stranger test (H60).

## Steps

- [x] **S7-0 — Decompose S7 into this plan; archive the S6 plan.** T2 (planning). (cycle 377)
- [x] **S7-1 — Real-use counter.** (cycle 378) T2 (read-only count; no money, auth or permission change).
  `NOT_COUNTED_AGENT_DIDS` setting (validated like `FOUNDER_DIDS`; malformed → the counter answers 503,
  never an overcount); a `layer1_counter` service using `outside_agent_sql`; `GET /stats/layer1`
  (`{outside_posters_7d, target: 25, window_days: 7}`), public, cached, rate-limited; the tile on
  `/stats`. Check: `--db` tests (founder, FOUNDER role, not-counted DID, under-24 h, held, hidden,
  PRIVATE, repost-only, 8-days-ago, two posts by one agent = 1); bad setting → 503; UI test; build.
- [x] **S7-2 — Small gaps from S6.** (cycle 379) T2. Python SDK `block` / `unblock` (sync + async; TS checked
  for parity) with unit tests; the website answers a malformed URL escape with its normal 404 page,
  not a 500 (middleware or a safe decode in the dynamic routes). Check: SDK tests; UI test for the
  decoder; `next start` smoke `/agents/%E0%A4%A` and `/labelers/%E0%A4%A` → 404.
- [x] **S7-3 — Accessibility pass.** (cycle 380; Lighthouse waits on H59) T2 (UI). `eslint-plugin-jsx-a11y` (already a Next dependency)
  at its recommended rules over `ui/`; fix findings on Home, profile, post card, composer, menus,
  dialogs (labels, `alt`, button names, landmarks, heading order, focus visible, colour contrast of
  muted text). When H59 is done: Lighthouse (local `next start`, mobile) on `/` and `/@handle`
  ≥ 90 accessibility, numbers in the log. Check: eslint clean with the a11y rules; `npm test`;
  build; Lighthouse if the browser is back, else noted as waiting on H59.
- [x] **S7-4 — Fresh agent in 2 minutes, four ways.** (cycle 381) T2. One timed `--db` e2e that, for each of raw
  HTTP, the Python SDK, the TS SDK (node script) and the MCP server (stdio), registers a fresh
  agent, claims a handle and posts, asserting each path under 120 s; plus a check that the
  agent-first list holds for every Layer 1 feature (a table in the test or a doc: route in OpenAPI,
  Python method, TS method, MCP tool, `skill.md` line). Fix any gap found. Check: the test passes.
- [x] **S7-5 — Docs.** (cycle 382) T3. `skill.md` (and ClawHub SKILL.md) read top to bottom for Layer 1 truth
  (hidden layers not advertised as live; every S2–S6 feature present once); the developer page;
  SDK READMEs; version bumps (Python 0.5.0, TS 0.2.0, MCP 0.2.0) and dated CHANGELOGs; `NOTICE`
  credit lines (x-algorithm, Bluesky social-app) present if anything was borrowed.
  ClawHub SKILL.md and the MCP README must teach the new like / follow / block (S7-4). Check: the
  skill/doc truth tests; SDK and MCP test suites; `npm run build` for TS.
- [x] **S7-6 — Public SDK export and OSS scan.** (cycle 384; H61 written) T3. Rebuild with `scripts/export_public_sdk.sh`,
  run `scan_public_sdk.py` and gitleaks, update `sdk_export_report.md` (file count, results);
  write **H61** (publish the three packages and push the export; supersedes the open release
  steps in H12 / H26 / H31–H33 / H54 where they overlap). Check: scan exit 0, gitleaks no leaks,
  `test_public_sdk_export.py` passes.
- [ ] **S7-7 — Whole-layer security review.** **T1** (Fable). Every Layer 1 commit after its
  sprint's review (incl. S7-1 to S7-6), and the seams: handles (S2) × feeds/labelers pages;
  mentions and notifications (S3) × feed/labeler text, quotes and labels; uploads and link fetching
  (S4) × feed descriptions, labeler pages and the stats page; S6 feeds and labels × handle changes,
  account holds, deactivation and blocks; one pass over every rate limit and the content check on
  every Layer 1 write path. Adversarial tests in `tests/integration/test_layer1_security_review_db.py`.
  Also look at (noted in S7-4): an agent may still **follow an agent it has blocked** (only the
  blocked side is refused, `routers/follows.py`); decide whether a block should also refuse the
  blocker's follow and drop existing follows both ways.
  Check: new tests pass; full `--db` run.
- [ ] **S7-8 — Layer 1 acceptance run.** T2. Full platform pytest (incl. `--db`), UI vitest, tsc,
  eslint, build; dead-end crawl and Lighthouse if H59 is done (else recorded as waiting); the
  finish-line table with each item Met / Waiting-on-DrJ / After-merge.
- [ ] **S7-9 — Stranger test.** **[human]** H60 (after merge and deploy; DrJ on a phone and a laptop,
  with the live Lighthouse and the < 2 s check). The engine writes the script in H60 (done this cycle).
- [ ] **S7-10 — Layer 1 close.** T2. `sprints/layer_1_s7_retro.md`; the Layer 1 briefing
  `sprints/briefing_<date>_layer1_close.md` (what shipped S1–S7, merge order and what merging will
  do, every open H item in order, the real-use counter and how DrJ reads it, live-test checklist);
  `state_of_agentx.md`. Then report `PHASE_COMPLETE` (Layer 1 is the engine's current phase).

## Human-only items for S7

- **H59** (open): reinstall the test browser → unblocks the dead-end crawl and local Lighthouse.
- **H60** (new, after merge and deploy): stranger test on a phone and a laptop, live Lighthouse ≥ 90
  on Home and a profile, Home and a profile load in under 2 s on the phone.
- **H61** (written at S7-6): publish Python 0.5.0, TS 0.2.0, MCP 0.2.0 and push the public SDK export.
- After merge: set `NOT_COUNTED_AGENT_DIDS` to the ScoopFeeds agents' and test agents' DIDs (in H61
  or the Layer 1 briefing, once S7-1 exists).
