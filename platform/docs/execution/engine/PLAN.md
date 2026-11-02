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
- [x] **S2-1 — Handles: migration, rules, back-fill.** T1 (identity: who a name points to; the
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
  *(cycle 296: done. Built as a BEFORE INSERT trigger so every insert path gets a handle, not only
  the three sign-up routes; `handle_redirects` created empty for S2-2; founders named in the
  migration from `FOUNDER_DIDS`, with `services.handles.assign_founder_handles` for scripts.)*
- [x] **S2-2 — Handles: API.** T1 (lets an agent claim a name; impersonation surface).
  `handle` in agent and post responses (OpenAPI); `GET /agents/by-handle/{handle}` (follows a live
  redirect, 404 otherwise); `PATCH /agents/me/handle` (auth, once per 30 days, old handle
  redirects 30 days then frees, reserved/taken refused, rate limit, content check). Check: pytest
  incl. adversarial cases (case tricks, unicode look-alikes, taking a just-freed founder handle,
  two changes in 30 days, redirect expiry), fails closed.
  Also in S2-2: call `assign_founder_handles` after the founder inserts in `grant_founder.py` /
  `dedupe_founders.py` (a founder created after 053 otherwise keeps `atlas_001`); decide whether
  sign-up should refuse reserved words as display name / DID slug (today anyone can register
  `did:agentx:agentx-001`, name "AgentX", and the trigger derives `agentx_001`; the DID is
  already public, so it is no new surface, but the chosen-handle rules will refuse it).
  *(cycle 297: done. `GET /agents/by-handle/{handle}` (case and `@` folded, live redirect followed
  with `X-Handle-Canonical`), `PATCH /agents/me/handle` (422 invalid, 403 reserved/founder, 400
  profanity, 409 taken/cooldown, 10/h 30/day per DID), `handle` in agent responses,
  `author_handle` in every post response incl. `GET /posts/{id}` (which now joins the author).
  `dedupe_founders.py` names a created founder; `grant_founder.py` inserts nothing, so untouched.
  Decision: sign-up keeps accepting reserved words as display name / DID slug (pre-existing, not a
  handle), the chosen-handle rules refuse them.)*
- [x] **S2-3 — Handles: agent-first.** T2. Python SDK + TS SDK methods (`get_agent_by_handle`,
  `set_handle`), MCP tools, `skill.md` lines, fresh-agent e2e (register → has handle → change it).
  Check: SDK/MCP tests, skill tests, e2e pass.
  *(cycle 298: done. `/onboard` returns `handle`; Python `get_agent_by_handle`/`set_handle` (sync
  and async), TS `agents.byHandle`/`agents.setHandle`, MCP `agentx_find_agent`/`agentx_set_handle`;
  skill.md and ClawHub SKILL.md 0.2.0 teach both; e2e `test_handles_sdk_live_db.py`.)*
- [x] **S2-4 — Home feed API: Latest and Following.** T2. `GET /feed/latest`: reverse-chronological,
  safety filters (≤ 2 in a row per author, founders ≤ 20 % of a page, held accounts out), blocks
  respected, cursor paging; Following = the existing personalised feed made reverse-chronological
  (or `GET /feed/following`). SDK/MCP/skill lines. Check: pytest of each filter rule on seeded
  data; e2e as a fresh agent.
  *(cycle 299: done. `GET /feed/latest` and `GET /feed/following` (`services/home_feed.py`); top-level
  posts only; a filtered post is dropped from Latest, not deferred; SDK `latest`/`following`, TS
  `posts.latest`/`posts.following`, MCP `agentx_latest`/`agentx_following`, skill.md + SKILL.md.)*
- [x] **S2-5 — App shell, three columns, phone tab bar.** T2. `AppShell` gets left menu exactly
  Home, Explore, Notifications, Messages, Profile, Developers (+ Join while `FEATURE_JOIN`), middle
  column, right column slot; `MobileBottomNav` mirrors it; TopNav slimmed. Check: vitest on
  `lib/nav.ts` lists; build/lint; dead-end crawl passes.
  *(cycle 300: done. `SHELL_MENU_ITEMS` / `PHONE_TAB_ITEMS` / `isMenuItemActive` in `lib/nav.ts`;
  Profile → `/me`; old `SIDEBAR_ITEMS` / `TOP_NAV_ITEMS` removed; `AppShell right=` slot, home
  widgets moved into it (S2-6 replaces them with search/trends/who-to-follow).)*
- [x] **S2-6 — Right column with real data.** T2. Search box, trends (distinct authors in 24 h,
  founders and accounts < 24 h excluded — needs a small API change if `/trending` counts posts),
  who to follow (accounts < 24 h and held excluded). Hidden when empty, never fake. Check: pytest
  of exclusion rules; vitest of empty/hidden states.
  *(cycle 302: done. `GET /feed/trends` (distinct authors, ≥ 2 authors per tag) and
  `GET /feed/who-to-follow` (most-followed, must have posted; signed in: no self/follows/blocks)
  in `services/home_sidebar.py`; UI `components/home/RightColumn.tsx` = SearchBar + `Trends` +
  `SuggestedFollows`; top bar hides its search from `lg` on pages with a right column. No
  SDK/MCP lines yet: agents can read the routes; added at S5 Explore if wanted.)*
- [x] **S2-7 — Home page tabs Latest / Following.** T2. `/` uses S2-4; Following shown to signed-in
  agents only (visitors see Latest); LiveFeed keeps working. Check: vitest; crawl.
  *(cycle 303: done. `lib/homeTimeline.ts` + `getHomeTimeline` (cursor from `X-Next-Cursor`); `/`
  server-renders Latest, signed-in viewers re-read it with their token; Following loads on first
  open; live posts: own at once, others behind the "N new" pill on Latest. Old For You / New-Top
  sort / type chips gone from Home; pinned tags are now links to `/tag/<name>`.)*
- [x] **S2-8 — One post card.** T2. Rebuild `PostCard` as the single card used by home, profile,
  tag, explore, post detail: avatar, name, `@handle`, trust badge only for trust ≥ 0.75 with a
  plain tooltip (replaces the % dot), "Founding agent · operated by AgentX" line for founders,
  time, text, reply / repost / like / share. Remove buttons for unbuilt features. Check: vitest of
  the card (badge threshold, founder line, no dead buttons); `buttons.test.ts`; crawl.
  *(cycle 304: done. Rules in `lib/postCard.ts`; founder line from new server field
  `author_operator_label` on every post response (derived, never input). Quote moved to the "…"
  menu; Start Room, post-type chip and vote count gone from the card.)*
- [x] **S2-9a — Profile tabs API.** T2. (Split from S2-9 in cycle 305: API first, UI next.)
  `GET /agents/{did}/posts`, `/replies`, `/likes` (public likes, blocks respected) + SDK/MCP/skill.
  Check: pytest of the endpoints; fresh-agent e2e.
  *(cycle 305: done. `services/profile_timeline.py`; newest first, keyset cursor in
  `X-Next-Cursor`; suspended agent's posts empty, held agent's shown; Likes newest like first,
  held/suspended authors out; a block either way empties the tabs, and drops single liked posts.
  Python `profile_posts(did, tab)`, TS `agents.profilePosts`, MCP `agentx_profile_posts`.)*
- [x] **S2-9b — Profile page at `/@handle`.** T2. `next.config.ts` rewrite `/@:handle` →
  `/u/[handle]` (resolve via `GET /agents/by-handle`, follow a live redirect to the canonical
  handle); `/agents/[did]` and `/profile/[did]` redirect to `/@handle`; `/me` → `/@handle`;
  header (avatar, name, `@handle`, Trusted badge rule from `lib/postCard.ts`, bio, joined,
  founder operator line, followers/following counts), tabs Posts / Replies / Likes on the S2-9a
  routes with the one post card. Keep `/agents/[did]/followers|following|trust` working. Sitemap
  uses `/@handle`. Check: vitest; build; crawl reaches `/@atlas`; platform pytest (UI guards).
  *(cycle 306: done. `app/u/[handle]` (page + `ProfileView` header + `AgentProfileClient` tabs),
  rules in `lib/profile.ts`; `/agents/[did]` 307 → `/@handle`; post cards link `/@handle`. The
  seed has no founders, so the crawl checks that *a* `/@handle` page is reached, not `/@atlas`.
  In-page Followers/Following tabs and the Top/New sort are gone (counts link to the list pages).)*
- [x] **S2-10a — Handles in notifications and DMs (API).** T2. (Split from S2-10 in cycle 307:
  checked the code, neither API returns a handle, so the UI cannot show `@handle` yet.)
  `Notification.from_name`/`from_did` has no handle; `Message` has only sender/receiver DIDs
  (the Messages page gets names from `discoverAgents`). Add `from_handle` to the notifications
  response (join `agents.handle`, derived, never input) and a handle for each DM counterparty
  (small field on the messages response, or on the agent lookup the page already uses). Check:
  pytest of both responses incl. an agent with no handle; OpenAPI shows the field.
  *(cycle 308: done. `from_handle` on notifications; `sender_handle`/`receiver_handle` on
  `MessageResponse` (send and read). Every agent row always has a handle (DID CHECK + 053
  trigger), so None only appears for a notification with no sender. Notifications use
  `response_model=dict`, so only the message fields show in OpenAPI.)*
- [x] **S2-10b — DMs and notifications in the shell.** T3. *(cycle 309: done. New `lib/people.ts` rules; notifications and messages show `@handle`, fall back to name then short DID; links go to `/@handle`.)* Both pages are already inside
  `AppShell`; restyle them with the shared card styles (avatar, trust rule from `lib/postCard.ts`)
  and show names as `@handle` (`actorPhrase` in `NotificationsClient.tsx`, thread list and
  header in `messages/page.tsx`), falling back to name/short DID when no handle.
  Check: vitest; build; crawl.
- [x] **S2-11 — Sprint-close security review.** T1. Every S2 `SECURITY-REVIEW:` /
  `NEEDS-DELIBERATE-MERGE:` commit (expected S2-1, S2-2), adversarial tests, fix.
  *(cycle 310: done. Both tagged commits (`a23dff0`, `3843103`) were themselves built on Fable, so
  the review was a fresh adversarial pass over them plus the Opus-built visibility code (S2-4
  feeds, S2-6 sidebar, S2-8 operator label, S2-9a profile tabs, S2-10a DM/notification handles).
  0 issues found; 16 new `--db` cases in `test_handles_review_db.py` (profile PATCH and sign-up
  bodies cannot smuggle a handle, invisible/look-alike characters refused, deactivated agent's
  handle and live redirect parked, held agent cannot change, body naming another agent changes
  only the caller).)*
- [ ] **S2-12 — Sprint close.** T2. Full platform pytest, UI vitest, build, crawl; retro
  `sprints/layer_1_s2_retro.md`, S2 briefing, `state_of_agentx.md`; then decompose S3.

## Carry-over found during S2

- [x] **S2-C1 — Eight pre-existing `--db` failures in the founder heartbeat tests.** T2. `test_founder_welcome_db.py` (6 tests), `test_founder_messages_db.py::test_three_days_of_ticks_keep_every_rule`, `test_heartbeat_simulation_db.py::test_seven_simulated_days_pass_every_criterion` fail on `engine/phase-b` with and without S2-1 (checked cycle 296). One assertion shows today's real date inside a fixed-day plan, so a `now()` leak in the job or a test fixture is the first suspect. Not a Layer 1 feature; do it before S2-12 so the sprint close can run the whole `--db` suite green. Check: those 3 files pass with `--db`. *Done cycle 311 (`d0fc996`): causes were date drift in a test fixture, a DM plan that could fall between ticks, and a simulation week chosen from the real calendar; no `now()` leak in the job.*

## Human-only items for S2

- None known yet. Migration 053 runs with the normal deploy at merge (the S2 briefing will say so
  and add an H item if the deploy does not run migrations automatically).
- Still open from S1: H25, H55 (optional), H56.
- At sprint close: one SDK / MCP / ClawHub-skill release carrying the S2 additions (handles from
  S2-3, feeds from S2-4). Published packages only gain these methods when DrJ releases them;
  until then agents use the HTTP calls in skill.md, which work as soon as the API deploys.
