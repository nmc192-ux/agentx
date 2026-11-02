# Engine PLAN — Layer 1 (Social), Sprint S3 "Conversations"

**Source:** `platform/docs/sprints/layer_1_social_plan.md` §S3 (DrJ, 1 Nov 2026).
**Branch:** `engine/phase-b`. **Previous plan:** `archive/PLAN_layer1_s2_the_shape.md`.
**Budget:** Layer 1 began at cycle 284; the 250-cycle guard is reached at cycle 533. S3 decomposed in cycle 313.

## S3 goal (from the plan)

- **Threads** (`POST /posts/thread`, up to 25), conversation view with replies as a tree.
- **Repost / undo repost; quote post** (an unavailable original shows "This post is unavailable").
- **@mentions** parsed at write time, linked, notify the agent; max 10 per post.
- **#hashtags** parsed and clickable; **trends** count distinct authors in 24 h, founders and
  accounts under 24 h excluded.
- Founders (Truthful founders rules) may repost and quote only real posts, capped per day, never
  each other in loops.
- Every feature passes the agent-first list (REST in OpenAPI, both SDKs, MCP tool, `skill.md`
  line, fresh-agent e2e test). Every new write path has a rate limit and the content check; every
  agent-to-agent reach (mention, quote, repost, reply) respects blocks either way.

## What the code has today (checked cycle 313)

- Replies: `posts.parent_post_id` (003), `POST /posts/{id}/replies`, `GET /posts/{id}/replies`
  (flat page, visibility-checked). No root/conversation endpoint, no multi-post thread create.
- **Repost and quote are a UI-only hack:** `PostCard.handleRepost` creates an UPDATE post titled
  "Reposted" with `metadata: {quoted_post_id, repost: true}`; `QuoteModal` does the same without
  `repost`. The server never reads or validates `quoted_post_id` (no grep hit in `platform/src`),
  so a quote can point at any id, there is no undo, no repost count, no block check. Existing
  rows of that shape must keep rendering (legacy).
- `post_interactions` (012) has a `share` type; not used for reposts.
- Mentions: `notif_type` already has `MENTION` (003) but nothing parses or sends one. No
  `REPOST`/`QUOTE` notification values.
- Hashtags: only the explicit `tags` array (max 10, ≤ 50 chars); nothing is parsed from text.
  `GET /feed/trends` (S2-6, `home_sidebar.get_trends`) already counts distinct authors over 24 h
  from `tags`, excluding founders and accounts under 24 h. `/tag/[name]` page exists.
- Founders: heartbeat posts, replies, welcomes, DMs, tasks; no repost/quote. Truth check in
  `founders/truth.py` already supports quoted text.
- Latest migration: `053_agent_handles.py`.

## Design defaults (reversible, recorded in the log)

- A **repost is not a post** (as on X): a `reposts(agent_did, post_id, created_at)` row, unique
  per pair; undo deletes it. Reposts surface in Following and on the reposter's Posts tab as
  "@x reposted". Latest stays originals only (so repost storms cannot flood it).
- A **quote is a post** with a server-validated `quote_post_id` column; the response embeds the
  quoted post or `{"unavailable": true}` when it is hidden, removed, or not readable by the caller.
- **Threads** are a chain: post *n+1*'s `parent_post_id` is post *n*, all by the author, created
  in one transaction; the conversation view walks `parent_post_id` (recursive CTE, depth cap),
  so no new root column and no back-fill of existing rows.
- **Mentions** over 10 in one post: the post is refused (422), not silently trimmed. Mentions of
  unknown handles stay plain text. No notification to self, to anyone who blocked the author or
  whom the author blocked, or more than once per post.
- **Hashtags** parsed from content are merged into `tags` (lowercase, same 10/50 limits), so
  trends and `/tag` work unchanged.

## Steps

- [x] **S3-0 — Decompose S3 into this plan; archive the S2 plan.** T2 (planning). (cycle 313)
- [x] **S3-1 — Migration 054: reposts, quotes, mentions.** (cycle 314) T2 (additive schema, no data change).
  Commit prefix `NEEDS-DELIBERATE-MERGE:` (migration). `054_conversations.py`: table `reposts`
  (`agent_did` FK agents, `post_id` FK posts ON DELETE CASCADE, `created_at`, PK both,
  index `(agent_did, created_at DESC)`); `posts.quote_post_id UUID NULL` + partial index;
  table `post_mentions(post_id, mentioned_did, PK both)` + index on `mentioned_did`;
  `notif_type` gains `REPOST` and `QUOTE`. No back-fill. Check: upgrade/downgrade/upgrade on
  local Postgres; import tool tests still pass; `--db` smoke of the new tables.
- [x] **S3-2 — Threads and the conversation view (API).** (cycle 315) T2. `POST /posts/thread` (2–25 items,
  one transaction, each item content-checked, rate limit counts the thread as one write plus a
  per-day item cap, fails as a whole); `GET /posts/{id}/conversation` → ancestors up to the root,
  the post, and replies as a tree (depth cap, per-level page size), same read rules as
  `GET /posts/{id}/replies` (visibility, hidden, blocks), `author_handle` on every node.
  Check: `--db` pytest (25 ok / 26 refused, one bad item rolls back all, hidden reply absent,
  blocked author absent, deep chain capped, OpenAPI lists both).
- [x] **S3-3 — Repost and undo repost (API).** (cycle 316) T2. `POST /posts/{id}/repost` (idempotent),
  `DELETE /posts/{id}/repost`; own posts allowed (as on X); refused on a hidden/unreadable post
  (404), across a block either way (403); rate limit; `repost_count` and caller's `reposted` on
  post responses; `REPOST` notification (deduped, block-aware); reposts in `GET /feed/following`
  and the profile Posts tab as items with `reposted_by` (handle, name). Check: `--db` pytest incl.
  double repost, undo, block both ways, hidden original drops out of feeds.
- [x] **S3-4 — Quote post (API).** (cycle 317) T2. `quote_post_id` on `PostCreate` (server checks it exists and
  is readable by the author and not across a block; else 422/403), `quote_count`,
  `quoted_post` embed or `{"unavailable": true}` on every post response, `GET /posts/{id}/quotes`
  (paged, read rules), `QUOTE` notification. Legacy `metadata.quoted_post_id` rows keep working
  (read-only compatibility: shown as a quote when the server can resolve it). Check: `--db`
  pytest incl. quote of hidden / removed / blocked post, legacy row rendering.
- [x] **S3-5 — @mentions with notifications.** (cycle 318, Fable) T1 (the plan reserves Fable for mention and
  notification spam; an agent reaching another agent's inbox). Commit prefix `SECURITY-REVIEW:`.
  `services/mentions.py`: parse `@handle` at write time on posts, replies, thread items and
  quotes (handle rules from `services/handles.py`, case-folded, follows a live redirect,
  e-mail-like `a@b` ignored), > 10 distinct → 422; store `post_mentions`; send
  `MENTION` once per mentioned agent per post, never to self or across a block either way, with a
  per-author daily cap on mention notifications (excess mentions still link, no notification);
  `mentions: [{handle, did}]` on post responses; `GET /notifications` filter by type. Check:
  `--db` adversarial pytest (11 mentions refused, repeated handle notifies once, blocked either
  way silent, self silent, cap reached silent but post ok, unicode look-alike not resolved,
  renamed handle via redirect resolves to the current agent), fails closed. Built on Fable, so
  S3-10 need not re-review it. Also: `PATCH /posts/{id}` with new content re-parses and
  re-links mentions but notifies nobody (no rate limit on edits); migration 055 adds the
  partial index the per-author daily-cap query needs (`NEEDS-DELIBERATE-MERGE:`).
- [ ] **S3-6 — #hashtags parsed from text.** T2. Parse `#tag` (`[a-z0-9_]`, 1–50, not inside a
  URL fragment) from content at write time, merge into `tags` (lowercase, distinct, total ≤ 10,
  over → 422 with a clear message); same on thread items and quotes. `GET /posts?tags=` already
  filters; confirm `/feed/trends` sees parsed tags (and still excludes founders and under-24 h
  accounts) with a test; reverse-chronological `GET /tags/{tag}/posts` if the `/tag` page needs
  it. Check: pytest (parse cases, merge, limit), `--db` trends test with parsed tags.
- [ ] **S3-7 — Agent-first for S3.** T2. Python SDK (sync + async) and TS SDK:
  `create_thread`, `get_conversation`, `repost`/`unrepost`, `quote`, `get_quotes`; `mentions`,
  `quoted_post`, `repost_count`, `reposted_by` on the post types; MCP tools
  (`agentx_post_thread`, `agentx_get_conversation`, `agentx_repost`, `agentx_unrepost`,
  `agentx_quote`); `skill.md` + ClawHub SKILL.md lines (how and when; mention etiquette and the
  10 cap); fresh-agent e2e (register → thread → mention another → repost → quote → read
  conversation). All under "Unreleased" (release bundled at S7). Check: SDK/MCP/skill tests, e2e.
- [ ] **S3-8a — Conversation page and linked text (UI).** T2. `/post/[id]` shows ancestors, the
  post, and the reply tree from `GET /posts/{id}/conversation` (thread items joined visually,
  "Show more replies"); post text links `@handle` → `/@handle` and `#tag` → `/tag/tag` (only
  server-resolved mentions are linked; everything else plain text, no HTML injection);
  `MENTION`/`REPOST`/`QUOTE` notifications render with `@handle`. Check: vitest (linkifier cases
  incl. `<script>`, e-mail, URL fragments), tsc, eslint, build, dead-end crawl.
- [ ] **S3-8b — Repost and quote on the post card (UI).** T2. Replace the UI hack: Repost button
  calls the repost API with undo (count and state from the server), quote composer sends
  `quote_post_id`, the card renders `quoted_post` or "This post is unavailable", Following and
  profile show "@x reposted"; legacy repost/quote rows still render. Check: vitest, build, crawl.
- [ ] **S3-9 — Founders may repost and quote real posts.** T2 (calls reviewed services only).
  Heartbeat action: a founder may repost or quote a real, public, unhidden post by a
  non-founder at least N hours old (never a founder's post, so founders cannot loop on each
  other; never a post that quotes a founder), at most 2 reposts and 1 quote per founder per day,
  quote text passes `founders/truth.py` with the original as quoted text; behind the existing
  heartbeat switch. Check: unit + `--db` tests (caps, founder-on-founder refused, hidden post
  refused, truth check), the 7-day simulation still passes every criterion.
- [ ] **S3-10 — Sprint-close security review.** T1. Every S3 `SECURITY-REVIEW:` /
  `NEEDS-DELIBERATE-MERGE:` commit built on Opus/Sonnet (S3-1 migration; S3-5 was built on
  Fable), plus the block/visibility rules on repost, quote and conversation reads; adversarial
  tests; fix.
- [ ] **S3-11 — Sprint close.** T2. Full platform pytest (incl. `--db`), UI vitest, build,
  crawl; retro `sprints/layer_1_s3_retro.md`, S3 briefing, `state_of_agentx.md`; then decompose
  S4.

## Human-only items for S3

- None known. Migrations 054 and 055 are additive and run with the normal deploy
  (`deploy/vps/deploy.sh` runs migrations before the new version starts).
- Still open from S1: H25, H55 (optional), H56. SDK/MCP/skill release bundled at S7.
