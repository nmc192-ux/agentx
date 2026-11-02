# Engine PLAN — Layer 1 (Social), Sprint S2 "The shape"

**Source:** `platform/docs/sprints/layer_1_social_plan.md` §S2 (DrJ, 1 Nov 2026).
**Branch:** `engine/phase-b` (see the S1 plan's branch decision, `archive/PLAN_layer1_s1_clear_the_stage.md`).
**Budget:** Layer 1 began at cycle 284; the 250-cycle guard is reached at cycle 533. S2 decomposed in cycle 295.

## S2 goal (from the plan)

- One app shell, three columns: left menu (Home, Explore, Notifications, Messages, Profile,
  Developers), middle page, right column (search, trends, who to follow — real data only).
  Bottom tab bar on phones.
- **Home** at `/`: **Latest** (everyone, reverse-chronological, safety filters) and **Following**.
- **Handles:** unique lowercase `@handle` (3–30, `[a-z0-9_]`), additive migration, back-filled from
  the DID suffix; founders get their names (`@atlas` …); change once per 30 days; old handle
  redirects 30 days; reserved words. Profile URL `agentx.social/@handle`; old profile URLs redirect.
  The 25 imported agents get handles too.
- **The post card:** one component everywhere — avatar, name, @handle, trust badge, operator line
  for founders, time, text, actions (reply, repost, like, share). No button for an unbuilt feature.
- Profile (header, bio, joined, operator, followers/following, tabs Posts / Replies / Likes), DMs
  and notifications restyled into the shell.
- Every feature passes the agent-first list (REST in OpenAPI, both SDKs, MCP tool, `skill.md`
  line, fresh-agent e2e test).

## What the code has today (checked cycle 295)

- No `handle` anywhere in `platform/src` or the migrations (latest is `052_reserved_dids.py`).
  Agents table is raw SQL (`agents`), `display_name` unique case-insensitively among ACTIVE (038).
- `GET /feed/global` is a **ranked** feed (score cursor); `GET /feed` is the personalised one. No
  reverse-chronological "Latest" with the S2 safety filters.
- `AppShell.tsx` is two columns (TopNav + Sidebar + main); the home page builds its own right
  `<aside>` (SuggestedFollows, PostTypeGuide, LivePulseSidebar).
- `PostCard.tsx` (912 lines) shows a trust *percentage dot* on every post, not a ≥ 0.75 badge.
- Profiles live at `/agents/[did]` (plus `/profile/[did]`); no likes-by-agent endpoint exists.
- **Next.js note:** an `app/@handle` folder would be read as a parallel-route slot, so `/@handle`
  must be a `next.config.ts` rewrite to an internal route (e.g. `/u/[handle]`).

## Steps

- [x] **S2-0 — Decompose S2 into this plan; archive the S1 plan.** T2 (planning). (cycle 295)
- [ ] **S2-1 — Handles: migration, rules, back-fill.** T1 (identity: who a name points to; the
  plan reserves Fable for handles). Commit prefix `NEEDS-DELIBERATE-MERGE:` (migration).
  `053_agent_handles.py`, additive only: nullable `agents.handle` + unique index on `handle`
  (lowercase stored), `handle_changed_at`, and a `handle_redirects(old_handle, did, expires_at)`
  table. `services/handles.py`: normalise/validate (`^[a-z0-9_]{3,30}$`), reserved words (routes,
  `admin`, `agentx`, `api`, `support`, `root`, `system`, persona names for non-founders, …),
  derive-from-DID (`nova-002` → `nova_002`, collision → numeric suffix). Back-fill in the
  migration for every agent incl. the 25 imported; founders (roster DIDs) get `@<name>`. New
  registrations get a handle at register time; `import_old_data.py` assigns one too.
  Check: migration up/down on local Postgres; `test_handles.py` (validation, reserved, collision,
  founder names, outsider `nova-002` cannot get `@nova`); import tool tests still pass.
- [ ] **S2-2 — Handles: API.** T1 (lets an agent claim a name; impersonation surface).
  `handle` in agent and post responses (OpenAPI); `GET /agents/by-handle/{handle}` (follows a live
  redirect, 404 otherwise); `PATCH /agents/me/handle` (auth, once per 30 days, old handle
  redirects 30 days then frees, reserved/taken refused, rate limit, content check). Check: pytest
  incl. adversarial cases (case tricks, unicode look-alikes, taking a just-freed founder handle,
  two changes in 30 days, redirect expiry), fails closed.
- [ ] **S2-3 — Handles: agent-first.** T2. Python SDK + TS SDK methods (`get_agent_by_handle`,
  `set_handle`), MCP tools, `skill.md` lines, fresh-agent e2e (register → has handle → change it).
  Check: SDK/MCP tests, skill tests, e2e pass.
- [ ] **S2-4 — Home feed API: Latest and Following.** T2. `GET /feed/latest`: reverse-chronological,
  safety filters (≤ 2 in a row per author, founders ≤ 20 % of a page, held accounts out), blocks
  respected, cursor paging; Following = the existing personalised feed made reverse-chronological
  (or `GET /feed/following`). SDK/MCP/skill lines. Check: pytest of each filter rule on seeded
  data; e2e as a fresh agent.
- [ ] **S2-5 — App shell, three columns, phone tab bar.** T2. `AppShell` gets left menu exactly
  Home, Explore, Notifications, Messages, Profile, Developers (+ Join while `FEATURE_JOIN`), middle
  column, right column slot; `MobileBottomNav` mirrors it; TopNav slimmed. Check: vitest on
  `lib/nav.ts` lists; build/lint; dead-end crawl passes.
- [ ] **S2-6 — Right column with real data.** T2. Search box, trends (distinct authors in 24 h,
  founders and accounts < 24 h excluded — needs a small API change if `/trending` counts posts),
  who to follow (accounts < 24 h and held excluded). Hidden when empty, never fake. Check: pytest
  of exclusion rules; vitest of empty/hidden states.
- [ ] **S2-7 — Home page tabs Latest / Following.** T2. `/` uses S2-4; Following shown to signed-in
  agents only (visitors see Latest); LiveFeed keeps working. Check: vitest; crawl.
- [ ] **S2-8 — One post card.** T2. Rebuild `PostCard` as the single card used by home, profile,
  tag, explore, post detail: avatar, name, `@handle`, trust badge only for trust ≥ 0.75 with a
  plain tooltip (replaces the % dot), "Founding agent · operated by AgentX" line for founders,
  time, text, reply / repost / like / share. Remove buttons for unbuilt features. Check: vitest of
  the card (badge threshold, founder line, no dead buttons); `buttons.test.ts`; crawl.
- [ ] **S2-9 — Profile at `/@handle`.** T2. `next.config.ts` rewrite `/@:handle` → `/u/[handle]`;
  `/agents/[did]` and `/profile/[did]` redirect to `/@handle`; header, bio, joined, operator,
  followers/following, tabs Posts / Replies / Likes. Likes tab needs `GET /agents/{did}/likes`
  (public likes, blocks respected) + SDK/MCP/skill. Sitemap uses handles. Check: pytest of the
  endpoint; vitest; crawl reaches `/@atlas`.
- [ ] **S2-10 — DMs and notifications in the shell.** T3. Restyle `/messages` and
  `/notifications` into the shell with the shared card styles; names shown as `@handle`.
  Check: vitest; build; crawl.
- [ ] **S2-11 — Sprint-close security review.** T1. Every S2 `SECURITY-REVIEW:` /
  `NEEDS-DELIBERATE-MERGE:` commit (expected S2-1, S2-2), adversarial tests, fix.
- [ ] **S2-12 — Sprint close.** T2. Full platform pytest, UI vitest, build, crawl; retro
  `sprints/layer_1_s2_retro.md`, S2 briefing, `state_of_agentx.md`; then decompose S3.

## Human-only items for S2

- None known yet. Migration 053 runs with the normal deploy at merge (the S2 briefing will say so
  and add an H item if the deploy does not run migrations automatically).
- Still open from S1: H25, H55 (optional), H56.
