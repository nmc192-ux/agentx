# Engine PLAN — Layer 1 (Social), Sprint S1 "Clear the stage"

**Source:** `platform/docs/sprints/layer_1_social_plan.md` (DrJ, 1 Nov 2026; replaces
`phase_x_plan.md`). DrJ's note (cycle 284): run S1 → S7 to completion without stopping between
sprints, brief at each sprint close, stop at 250 cycles or on a blocker; no merge, no deploy.
**Branch:** `engine/phase-b` (see decision below). **Budget:** Layer 1 began at engine cycle 284;
the 250-cycle guard is reached at **cycle 533**. Previous plan: `archive/PLAN_truthful_founders_and_oss.md`.

**Branch decision (cycle 284, reversible):** the note asks for `engine/layer-1-social` cut from
`main`. The engine's guard only lets this session push to `engine/phase-b`, and at the start of
cycle 284 `engine/phase-b` was **identical to `origin/main` (`9d6afbe`, 0 commits ahead)**, i.e.
exactly "cut from main at or after `15401ca`". So Layer 1 is built on `engine/phase-b`. DrJ can
rename it at any time with H55 (no work is lost).

## S1 acceptance (from the plan)

1. Every unfinished layer is hidden from the menus and the home page: markets, bounties, tasks,
   wallets, economy stats, governance, collectives/groups/communities, rooms, graph, map,
   sentinel, capabilities, services, leaderboard, spotlight, dashboard. Each uses a
   `NEXT_PUBLIC_FEATURE_*` flag (new flags where a page has none), default off.
2. A direct URL to a hidden page shows a short "coming later" page (HTTP 200 page, not a
   redirect to `/`, never a broken page). API routes are unchanged.
3. April test accounts: VPS ops tasks `test-accounts-report` / `test-accounts-remove` wrap the
   existing reviewed `platform/scripts/remove_test_accounts.py`; DrJ runs them (H25 rewritten).
4. Zero dead ends: every remaining link and button works; every empty state says something true.
5. Existing tests (platform pytest, UI vitest, import tool tests) keep passing.

## Steps

- [x] **S1-0 — Decompose S1 into this plan; seed H55; branch decision.** T2 (planning).
  Check: this file + `HUMAN_ACTIONS.md` H55 committed and pushed.
- [ ] **S1-1 — Layer flags and the "coming later" page.** T2 (new UI feature).
  Add flags in `ui/lib/flags.ts` for the hidden pages that have none (`FEATURE_ROOMS`,
  `FEATURE_LEADERBOARD`, `FEATURE_CAPABILITIES`, `FEATURE_SERVICES`; tasks/wallets/dashboard/stats
  economy under `FEATURE_ECONOMY`; communities under `FEATURE_COLLECTIVES`; graph/map under
  `FEATURE_CONSTELLATION`). One `ComingLater` component (what it is, "agents can still use the
  API: see /developer", link Home). Every hidden route (incl. `[id]` sub-routes) renders it when
  its flag is off, replacing today's `redirect("/")`. `.env.local.example` lists the new flags.
  Check: a vitest that imports each hidden route's gate and asserts the flag→component mapping;
  `npm run build` and `npm run lint` pass.
- [ ] **S1-2 — Menus and home page show only Layer 1.** T2.
  Sidebar, TopNav, MobileBottomNav, Footer, CommandPalette, SearchBar suggestions, keyboard
  shortcuts and the home right column (`LivePulseSidebar`, `PostTypeGuide`, spotlight card) show
  no link or widget for a hidden layer; profile/agent cards hide wallet/economy/bounty bits.
  Decide per page for `/activity`, `/trending`, `/tags`, `/explore`, `/stats`, `/welcome`,
  `/feed`, `/home` (keep only what is Social; duplicates of `/` redirect to `/`).
  Check: vitest that the nav item lists, with all flags off, contain no hidden-layer href;
  build/lint pass.
- [ ] **S1-3 — Sitemap, robots and in-page links.** T3. Hidden routes leave `sitemap.ts`; grep
  for hard-coded links to hidden routes in visible pages (`/join`, `/developer`, `/about`,
  `/welcome`, post bodies' renderers) and remove or gate them. Check: test on `sitemap.ts` output.
- [ ] **S1-4 — VPS ops tasks `test-accounts-report` / `test-accounts-remove`.** T2, commit
  prefix `NEEDS-DELIBERATE-MERGE:` (wraps a reviewed script that deletes production rows; the
  script itself is not changed). Add both to `deploy/vps/ops.sh` and the task list in
  `.github/workflows/vps-ops.yml` (dry run = report; remove requires the report's exact count as
  a confirmation input, mirroring `import-apply`). Check: shell tests / bats-style pytest of the
  ops.sh argument handling, `remove_test_accounts.py` tests (35) still pass; rewrite H25 as a
  two-click VPS-ops item. **[human] afterwards: H25.**
- [ ] **S1-5 — Dead-end sweep (automated).** T2. A Playwright (or fetch-based) crawl of the local
  site with all `NEXT_PUBLIC_FEATURE_*` off and seeded local data: every internal link from
  every visible page returns a working page (no 404/500, no "coming later" reachable from a
  menu), every button has a handler. Fix what it finds. Check: the crawl passes locally and is
  kept as an e2e test.
- [ ] **S1-6 — Truthful empty states.** T3. Feed, explore, agents, notifications, messages,
  profile tabs, tags, trending, search: each empty state says something true (e.g. "No posts
  yet — agents post through the API: see /developer"). Check: vitest snapshots of the empty
  states; no "coming soon" placeholders on visible pages.
- [ ] **S1-7 — Agent-first check for S1.** T3. `skill.md` and the developer page don't send
  agents to hidden website pages; API routes untouched (diff check on `platform/src` routers).
  Check: skill/docs tests pass; grep shows no hidden-page URLs in `skill.py`/developer page.
- [ ] **S1-8 — Sprint-close security review.** T1. Review every S1 commit marked
  `SECURITY-REVIEW:`/`NEEDS-DELIBERATE-MERGE:` (expected: S1-4), add adversarial tests, fix.
- [ ] **S1-9 — Sprint close.** T2. Run S1 acceptance locally (full platform pytest, UI vitest,
  build, crawl), write `platform/docs/sprints/layer_1_s1_retro.md` and the S1 briefing for DrJ,
  update `state_of_agentx.md`, then decompose S2 in the next cycle.

## Human-only items for S1

- H55 (optional): rename the engine branch to `engine/layer-1-social`.
- H25 (rewritten in S1-4): run `test-accounts-report`, then `test-accounts-remove`.
