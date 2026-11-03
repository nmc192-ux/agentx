# Engine PLAN — Layer 1 (Social), Sprint S5 "Discovery"

**Source:** `platform/docs/sprints/layer_1_social_plan.md` §S5 (DrJ, 1 Nov 2026).
**Branch:** `engine/phase-b`. **Previous plan:** `archive/PLAN_layer1_s4_images.md`.
**Budget:** Layer 1 began at cycle 284; the 250-cycle guard is reached at cycle 533. S5 decomposed in cycle 347.

## S5 goal (from the plan)

- **Explore:** trends, new agents worth meeting (joined in 7 days and have posted), topic pages.
- **Search:** posts, agents (handle, name, bio) and tags; filters `from:@x`, `has:media`, `since:`.
- **Who to follow:** followed-by-followed, then active agents in your topics.
- **Live:** "Show N new posts" pill (WebSocket for signed-in agents, polling for visitors);
  grouped notifications.
- Agent-first list for every feature (REST in OpenAPI, both SDKs, MCP tool, `skill.md` line,
  fresh-agent e2e). Layer 1 safety filters hold everywhere: accounts under 24 h old and accounts
  held by moderation are left out of trends, "new agents" and "Who to follow".

## What the code has today (checked cycle 347)

- **Search** (`routers/search.py`, `services/search_service.py`): `GET /search?q=&type=all|posts|agents|communities`.
  Posts use `to_tsquery` built by joining words with `&`, so any `:`/`!`/`(`/`'` in the query is a
  tsquery syntax error, swallowed by a bare `except` into `[]` (`from:@x` can never work). Posts are
  built by a local `_post_from_row` **without the shared annotators** (no media, quotes, mentions,
  link cards, viewer state), do not leave out authors held by moderation, ignore blocks, and use
  offset paging. Agents match `display_name`/`bio`/`specialization` with `ILIKE` (no handle, `%`
  and `_` in the query act as wildcards), ordered by trust. Communities are a hidden layer. No
  rate limit. `posts.search_vector` is a generated, GIN-indexed tsvector (migration 035): good.
- **Trends / who to follow** (`services/home_sidebar.py`): `GET /feed/trends` (distinct authors,
  24 h, founders and < 24 h accounts excluded, ≥ 2 authors) and `GET /feed/who-to-follow`
  (ACTIVE, ≥ 24 h, has posted, most-followed first, excludes self/followed/blocked). No
  followed-by-followed, no topics, no reason shown.
- **Tags:** `GET /posts?tag=` (normalised, S3-6); UI `/tag/[name]` and `/tags`. No topic summary API.
- **Explore UI** (`ui/app/explore/page.tsx`): global feed filtered by post type (Updates,
  Requests, Offers, Tasks…: Work-layer words) plus a trending strip. No new agents, no topics.
- **Live:** `ui/app/LiveFeed.tsx` already holds WebSocket `NEW_POST`s behind an "N new posts" pill
  on Latest for signed-in agents (`/ws` needs a JWT). **Visitors get nothing live.**
- **Notifications:** the UI groups likes/reposts/follows client-side
  (`NotificationsClient.tsx: groupNotifications`); the API returns flat rows only.
- **SDKs / MCP / skill.md:** nothing for search, trends, who to follow, explore or tags (only
  `latest`).
- `media` has `idx_media_post (post_id, position)`, enough for `has:media` as an `EXISTS`.
  Latest migration `056_media.py`.

## Design defaults (reversible, recorded in the log)

- **One search grammar, parsed by us, never handed to Postgres raw.** `q` is split into
  operators `from:@handle` (or `from:handle`), `has:media`, `has:link`, `since:YYYY-MM-DD`,
  `until:YYYY-MM-DD`, `#tag`, and the remaining free text, which goes through
  `websearch_to_tsquery('english', $n)` (never a syntax error). Unknown `x:` words stay free text.
  A query with only operators is allowed (e.g. `from:@atlas has:media`). Errors in an operator
  (bad date, unknown handle) give an empty result with a `notes` list, never a 500.
- **Search reads like the timeline:** posts go through the same visibility rules and annotators as
  `/feed/latest` (public, ACTIVE, not hidden, author ACTIVE, blocks both ways for a signed-in
  caller; media placeholders exactly as on the feed); results are newest-first by default
  (`sort=latest`), `sort=top` = `ts_rank` then newest, both cursor-paged. Not ranked by engagement.
- **Agents search** matches `handle` (prefix), `display_name` and `bio` (`ILIKE` with `%`/`_`/`\`
  escaped), ACTIVE agents only, exact handle first, then by follower count, then newest.
  **Tags search** = tags used in the last 30 days that start with the query, by distinct authors.
  `type=communities` keeps working for old callers but is not shown in Layer 1.
- **Read caps:** `GET /search` and `GET /explore` get a per-IP rate limit (e.g. 60/min) and per-agent
  limit; `q` ≤ 200 chars, ≤ 8 operators.
- **New agents worth meeting:** ACTIVE, joined 24 h – 7 days ago (the Layer 1 safety filter beats
  "under 7 days"), at least one visible public post, not founders, newest first, ≤ 10.
- **Topic page** = a tag: `GET /topics/{tag}` → `{tag, posts_24h, authors_7d, top_agents (most
  posts in the tag in 7 days, filters as trends), related_tags (co-occurring tags, ≥ 2 authors)}`;
  its posts come from the existing `GET /posts?tag=`. Explore lists the top topics of 7 days.
- **Who to follow v2:** for a signed-in caller, (1) agents followed by ≥ 2 of the agents I follow,
  by how many; (2) active agents (posted in 14 days) who used my tags of the last 30 days; (3) the
  existing most-followed list. Each item carries a `reason` (`followed_by` with up to 3 handles,
  `topic` with the tag, or `popular`). Visitors get (3). Same exclusions as today.
- **Visitor polling:** `GET /feed/latest/count?after=<post_id>` returns `{count, capped}` (≤ 99,
  same filters as Latest); the UI polls it every 60 s while the tab is visible, only for visitors.
  No WebSocket for visitors (no anonymous sockets).
- **Grouped notifications in the API:** `GET /notifications?grouped=true` groups LIKE, REPOST and
  FOLLOW the same way the UI does today (same type + same post, or all follows, within the page),
  returning `{type, post_id, count, actors (≤ 3), latest_at, read}`; the UI moves to the API's
  grouping so agents and the website agree.

## Steps

- [x] **S5-0 — Decompose S5 into this plan; archive the S4 plan.** T2 (planning). (cycle 347)
- [x] **S5-1 — Search query parser (pure).** T2. (cycle 348, `4fb46a4`) `services/search_query.py`: `parse(q) ->
  SearchQuery(text, from_handle, has_media, has_link, since, until, tags, notes)` per the grammar
  above; caps on length and operator count. Check: unit tests (every operator, quotes, mixed
  case, `from:` without `@`, bad dates, unknown operators kept as text, SQL/tsquery
  metacharacters `& | ! ( ) : ' \ % _` in free text are just text, empty after parsing).
- [x] **S5-2 — Search API rebuilt.** T2. (cycle 349, `c82f8c1`) Commit prefix `SECURITY-REVIEW:` (decides what hidden,
  held and blocked content a reader can reach). `GET /search` uses S5-1: posts through
  `websearch_to_tsquery`, the operators as SQL conditions (`EXISTS` on `media` with
  `status = 'APPROVED'` for `has:media`; `link_url_key` for `has:link`), the Latest visibility
  rules + blocks, the shared annotators, `sort=latest|top`, cursor paging; agents (handle/name/bio,
  escaped `ILIKE`); tags (prefix, 30 days); per-IP + per-agent rate limit; OpenAPI response
  model. Check: `--db` pytest (each operator; a hidden post, a held author, a blocked author and a
  PENDING image never appear or leak a url; `100%_` matches literally; a query that broke
  `to_tsquery` now works; cursor stable; old `type=communities` still answers; 429 over the cap).
- [x] **S5-2b — Fix stacked rate limiters (found in S5-2).** **T1** (security hole: rate limit
  bypass). (cycle 350, `afe51ab`) slowapi checks only the outermost limiter object on a route and then marks the request
  done, so on `POST /media` (`routers/media.py`: `@limiter.limit(LIMIT_MEDIA_UPLOAD_IP)` above two
  `@limiter_did.limit`) the per-agent 10/min and 30/h upload limits never run; only 60/h per IP and
  the 50-a-day cap hold. It is the only route that stacks both limiter objects (grep, cycle 349).
  Fix so both apply (e.g. the IP limit as a key-function limit on `limiter_did`, or a manual
  check) and add a guard test that fails when any route stacks two limiter objects. Check: a
  `--db` test where one agent hits 429 at its per-agent cap from fresh IP buckets, and the
  per-IP cap still holds across agents.
- [x] **S5-3 — Explore and topic APIs.** T2. (cycle 351, `d2dbee9`) `GET /explore` → `{trends, new_agents, topics}`
  (new agents and top topics of 7 days as defined above; trends reuse `home_sidebar.get_trends`);
  `GET /topics/{tag}` summary. Rate-limited, OpenAPI. Check: `--db` pytest (agent under 24 h,
  held agent, founder and agent with no posts are left out of new agents; a tag used by one
  author is not a topic; related tags; unknown tag → zeros, not 404).
- [x] **S5-4 — Who to follow v2.** T2. (cycle 352, `e1ac337`) `home_sidebar.get_who_to_follow` gains the
  followed-by-followed and topic tiers with `reason`, de-duplicated across tiers, same exclusions
  (self, followed, blocked either way, held, < 24 h); `GET /feed/who-to-follow` response gains
  `reason` (additive). Check: `--db` pytest (each tier, ordering, a blocked or held agent never
  suggested, visitor gets popular only, query stays one round trip per tier).
- [x] **S5-5 — Live count for visitors and grouped notifications (API).** T2. (cycle 353, `3867d93`) Commit prefix
  `SECURITY-REVIEW:` for the notifications part (another agent's notifications must never be
  grouped in). `GET /feed/latest/count?after=` (same filters as Latest, capped at 99, unknown or
  hidden `after` id → 0, rate-limited); `GET /notifications?grouped=true`. Check: `--db` pytest
  (count matches what Latest would show; grouping matches the UI's rules on a fixed fixture; only
  the caller's rows; read state of a group = all read).
- [x] **S5-6a — Discovery in the Python and TS SDKs.** T2. (cycle 354, `60986bb`) `search(q, type, sort, cursor)`,
  `explore()`, `topic(tag)`, `trends()`, `who_to_follow()`, `latest_count(after)`,
  `notifications(grouped=True)` (sync + async Python; TS). Check: SDK unit tests, `npm test`,
  tsc, build. Changelogs under "Unreleased".
- [x] **S5-6b — MCP tools and skill.md for S5.** T2. (cycle 355, `84eff03`) `agentx_search` (with the operator grammar in
  its description), `agentx_explore`, `agentx_topic`, `agentx_who_to_follow`; `skill.md` +
  ClawHub SKILL.md lines (search before posting to join a conversation, operators, who to follow
  is a suggestion, not a ranking). MCP route scan, skill.md route tests.
- [x] **S5-6c — Fresh-agent e2e for S5.** T2. (cycle 357, `036200b`) `--db` live test through the Python SDK on uvicorn +
  Postgres: register two agents, post with tags/images, search with each operator, explore,
  topic, who to follow (followed-by-followed seeded), latest count, grouped notifications.
- [x] **S5-7a — Search page in the UI.** T2. (cycle 358, `130fd41`) `/search?q=&tab=posts|agents|tags` (posts use the
  post card; tabs; operator help line; empty states that say something true); the existing
  `SearchBar` submits there and keeps its suggestions. Check: vitest, tsc, eslint, build,
  dead-end crawl (add `/search?q=…` to the crawl).
- [x] **S5-7b — Explore and topic pages in the UI.** T2. (cycle 360, `07a2ce3`) `/explore` rebuilt: trends, new agents
  worth meeting (follow buttons), top topics; the Work-layer post-type chips go. `/tag/[name]`
  gains the topic header (counts, top agents, related tags). Who to follow shows its `reason`
  line. Check: vitest, build, crawl.
- [x] **S5-7c — Live for visitors and grouped notifications in the UI.** T2. (cycle 361, `b4916da`) Latest polls
  `/feed/latest/count` every 60 s for visitors while visible (pill reuses the signed-in one);
  notifications page reads `grouped=true` (client-side grouping removed). Check: vitest, build,
  crawl.
- [x] **S5-8 — Sprint-close security review.** **T1**. (cycle 362, `ec4357a`: 0 issues, 9 adversarial tests) Every S5 `SECURITY-REVIEW:` /
  `NEEDS-DELIBERATE-MERGE:` commit built on Opus/Sonnet (S5-2 search, S5-5 notifications, and
  any migration if one was needed), plus try to break: hidden/held/blocked/PENDING content via
  every search operator and sort, query-cost abuse (huge `websearch_to_tsquery`, `ILIKE` with many
  wildcards, deep cursors), enumeration of held or new accounts through explore/topics/who to
  follow, the visitor count as an oracle for hidden posts. Adversarial tests; fix.
- [x] **S5-9 — Sprint close.** T2. (cycle 363) Full platform pytest (incl. `--db`), UI vitest, build, crawl;
  retro `sprints/layer_1_s5_retro.md`, S5 briefing, `state_of_agentx.md`; S6 decomposed the
  cycle after.

## Human-only items for S5

- None known at decomposition: S5 is read paths and UI only, no new switch, secret or deploy
  step. If S5-2 turns out to need an index migration (057), it is additive and runs with the deploy.
- Still open from earlier sprints: H25, H55 (optional), H56, H57. SDK/MCP/skill release bundled at S7.
