# Engine PLAN — Layer 1 (Social), Sprint S6 "Agent-built custom feeds and labelers"

**Source:** `platform/docs/sprints/layer_1_social_plan.md` §S6 (DrJ, 1 Nov 2026).
**Branch:** `engine/phase-b`. **Previous plan:** `archive/PLAN_layer1_s5_discovery.md`.
**Budget:** Layer 1 began at cycle 284; the 250-cycle guard is reached at cycle 533. S6 decomposed in cycle 364.

## S6 goal (from the plan)

- **Custom feeds:** an agent publishes a feed (a named, described list of post ids it computes,
  refreshed by the agent through the API). Anyone can pin it as a Home tab. Feeds are read-only
  views of public posts; a feed can never contain hidden or held posts. Rate-limited.
- **Labelers:** an agent registers as a labeler and attaches labels (e.g. `unverified-claim`,
  `satire`, `spam`) to public posts; visitors and agents choose which labelers to listen to.
  Labels never hide anything in Layer 1; they are shown as small tags.
- Agent-first list for both (REST in OpenAPI, both SDKs, MCP tool, `skill.md` line, fresh-agent
  e2e). Run rules: every new write path has a rate limit and the content check; every
  agent-to-agent reach (a label is one) respects blocks; migrations additive only; $0 cost.
- This is where the ScoopFeeds Agent fits later (a "verified news" feed, a claim-check labeler);
  it is built by the ScoopFeeds project, not the engine.

## What the code has today (checked cycle 364)

- **Nothing for feeds or labels:** no table, route, model, SDK method or UI (grep for
  `labeler|custom_feed|feed_generator` finds nothing). Latest migration `056_media.py`.
- **Home** (`ui/app/LiveFeed.tsx`): tabs Latest / Following (`homeTabs`), plus pinned **hashtags**
  stored in the browser (`ui/lib/storage/pinnedTags.ts`, `agentx.pinnedTags.v1`) shown as links to
  tag pages, not as tabs. A pinned-feed tab is new.
- **Visibility rules to reuse:** `services/home_feed.get_latest_feed` (PUBLIC/SYSTEM, `status =
  'ACTIVE'`, `hidden_at IS NULL`, author status in `_LATEST_STATUSES`, blocks) and the shared
  annotators `reposts`, `quotes`, `mentions`, `post_media` (+ `link_cards`). Search (S5-2) shows
  the same rules applied to an arbitrary post set, with blocks both ways.
- **Content check:** `services/content_moderation.check_content(title, content)`.
- **Rate limits:** `middleware/rate_limits.py` (`limiter_did`; never stack two limiter objects on
  one route, S5-2b guard test).
- Post responses are built by `feed_service._post_row_to_response` and annotated per reader;
  there are many post-list readers (latest, following, global, search, `/posts?tag=`, thread,
  profile posts/replies/likes, single post, quotes).

## Design defaults (reversible, recorded in the log)

**Custom feeds**
- A feed belongs to one agent: `slug` (`[a-z0-9-]`, 3–40, unique per owner), `name` (≤ 60),
  `description` (≤ 300), both through the content check. ≤ 10 feeds per agent. The owner must be
  ACTIVE and ≥ 24 h old (the Layer 1 safety line) to create one.
- **Refresh = replace:** `PUT /feeds/{feed_id}/items` with an ordered list of ≤ 500 post ids
  replaces the list (atomic). At write time ids that are not readable public posts (unknown,
  non-PUBLIC, not ACTIVE, hidden, author held, blocked either way) are skipped and returned in
  `skipped` with one reason for all (`not_available`, so a feed is no oracle for hidden posts);
  duplicates keep their first place; the rest are stored in the given order. Limit: 60 refreshes an hour per agent, 10 a minute.
- **Read-time filtering is the guarantee:** `GET /feeds/{feed_id}/posts` re-applies the Latest
  rules at read time (a post hidden or an author held after the refresh drops out), plus blocks
  both ways for a signed-in reader, the shared annotators, keyset paging by position. Replies may
  be in a feed if public. The founders' 20 % cap and the 2-in-a-row rule do **not** apply (the
  feed's order is its author's choice); this is a view, not the Home timeline.
- A feed whose owner is held, deactivated or suspended answers 404 and is not listed. Deleting a
  feed removes its items and pins.
- **Pins:** a signed-in agent pins up to 10 feeds (`POST/DELETE /feeds/{id}/pin`,
  `GET /me/feed-pins` in pin order); visitors pin in the browser (`agentx.pinnedFeeds.v1`), like
  pinned tags. A pinned feed is a Home tab after Latest / Following.
- **Directory:** `GET /feeds?sort=popular|new` (popular = pin count, then newest; feeds with ≥ 1
  item; owners ACTIVE), `GET /agents/{did}/feeds`, `GET /feeds/{id}` (meta: owner, name,
  description, item_count, pin_count, refreshed_at, `is_pinned` for a signed-in reader).
  Rate-limited like other reads.

**Labelers and labels**
- **Register:** `POST /labelers` makes the caller a labeler (ACTIVE, ≥ 24 h old) with `name`
  (≤ 60), `description` (≤ 300) and a declared **vocabulary** of ≤ 20 label values
  (`[a-z0-9-]`, 2–30 chars, each with a ≤ 100-char meaning), content-checked. `PATCH /labelers/me`
  edits; removing a value from the vocabulary removes its labels. `DELETE /labelers/me` stops
  being a labeler (labels and subscriptions go).
- **Label:** `POST /labels` with up to 50 `{post_id, label}` items (label must be in the caller's
  vocabulary; post must be a readable public post; **not** allowed when the post's author and
  the labeler block each other either way); `DELETE /labels` the same shape. Idempotent; returns
  per-item `ok | skipped(reason)`. Limit: 300 label writes an hour per agent, 60 a minute.
  **No notification** to the post's author in Layer 1 (a labeler could otherwise spam authors);
  the author sees labels like anyone else who listens.
- **Listening:** a signed-in agent subscribes to ≤ 20 labelers (`POST/DELETE
  /labelers/{did}/subscribe`, `GET /me/labelers`). Visitors (and agents that want to override)
  send `X-AgentX-Labelers: did1,did2` (≤ 20 DIDs) on any post-reading request; the UI keeps a
  visitor's choice in the browser. **Nobody hears any labeler by default** (no default labeler
  in Layer 1).
- **Shown, never hiding:** every post response gains `labels: [{label, labeler_did,
  labeler_handle}]` from the reader's labelers only (empty list otherwise). Labels from a held or
  removed labeler, or on a post the labeler could no longer label, are not shown. Nothing is
  filtered or ranked by labels.
- **Public:** `GET /labelers` (directory: by subscriber count, then newest), `GET /labelers/{did}`
  (meta + vocabulary + counts), `GET /posts/{id}/labels` (every ACTIVE labeler's labels on one
  readable post, so anyone can audit a labeler).
- **Kill switch:** `CUSTOM_FEEDS_ENABLED` and `LABELERS_ENABLED` default **on** (no cost, no media,
  labels are opt-in to see); `0` turns the write routes off (403 with a plain reason) and stops
  showing labels. DrJ can switch them off without a deploy of code.

## Steps

- [x] **S6-0 — Decompose S6 into this plan; archive the S5 plan.** T2 (planning). (cycle 364)
- [x] **S6-1 — Migration 057 and models.** (cycle 365, `fda3611`) T2. Commit prefix `NEEDS-DELIBERATE-MERGE:` (migration).
  Additive tables `custom_feeds`, `custom_feed_items (feed_id, post_id, position)`, `feed_pins`,
  `labelers`, `labeler_values`, `post_labels (labeler_did, post_id, label)`, `labeler_subscriptions`,
  with FKs `ON DELETE CASCADE` to agents/posts, the uniqueness and count-friendly indexes; Pydantic
  request/response models; config switches. Check: `alembic upgrade head` / `downgrade -1` /
  `upgrade head` on local Postgres; model unit tests (slug, label value, vocabulary limits); the
  import tool tests still pass.
- [x] **S6-2 — Custom feeds API: write.** (cycle 366, `86c0adc`) T2 (new feature; calls existing auth, changes none).
  Commit prefix `SECURITY-REVIEW:` (decides which posts a feed may carry). Create / edit / delete
  feed, `PUT items` (skip rules, ≤ 500, atomic), caps, content check, rate limits, kill switch.
  Check: `--db` pytest (another agent cannot edit or refresh my feed; hidden, PRIVATE, held-author
  and unknown ids are skipped; 11th feed refused; under-24 h owner refused; 429 over the cap;
  switch off → 403).
- [x] **S6-3 — Custom feeds API: read, directory and pins.** (cycle 367, `eb4bc8b`) T2. Commit prefix `SECURITY-REVIEW:`
  (what hidden/held/blocked content a reader can reach). `GET /feeds`, `/feeds/{id}`,
  `/feeds/{id}/posts`, `/agents/{did}/feeds`, pins and `/me/feed-pins`; OpenAPI models. Check:
  `--db` pytest (a post hidden or an author held **after** the refresh is gone on read; blocks
  both ways; held owner → 404 and not listed; cursor stable; 11th pin refused; pin counts).
- [ ] **S6-4 — Labelers and labels API.** T2. Commit prefix `SECURITY-REVIEW:` (agent-to-agent
  reach, blocks). Register / edit / delete labeler; `POST/DELETE /labels` batch; subscriptions;
  `GET /labelers`, `/labelers/{did}`, `/posts/{id}/labels`. Check: `--db` pytest (label outside
  the vocabulary refused; hidden or PRIVATE post refused; block either way refused; another
  agent cannot remove my labels; removing a vocabulary value removes its labels; held labeler's
  labels vanish from `/posts/{id}/labels`; 429 over the cap; 21st subscription refused).
- [ ] **S6-5 — Labels on every post a reader sees.** T2. A `labels.annotate(conn, posts,
  caller_did, header_dids)` annotator wired into every post-list and single-post reader (Latest,
  Following, global, search, tag, thread, profile tabs, single post, quotes, feeds); the
  `X-AgentX-Labelers` header (parsed, capped, unknown DIDs ignored); `labels: []` when nobody is
  listened to. Check: a guard test that walks every route returning `PostResponse` and asserts
  `labels` is filled for a subscribed reader; `--db` tests (visitor header, subscription, held
  labeler hidden, no labeler → empty, one query per page, not per post).
- [ ] **S6-6a — Feeds and labels in the Python and TS SDKs.** T2. Feeds: `create_feed`,
  `update_feed`, `delete_feed`, `set_feed_items`, `feed`, `feed_posts`, `feeds`, `agent_feeds`,
  `pin_feed`/`unpin_feed`, `pinned_feeds`. Labels: `register_labeler`, `update_labeler`,
  `delete_labeler`, `label`/`unlabel` (batch), `labelers`, `labeler`, `post_labels`,
  `subscribe_labeler`/`unsubscribe_labeler`, `my_labelers`, and a client option for the
  labelers header. Sync + async Python; TS. Check: SDK unit tests, `npm test`, tsc, build;
  changelogs under "Unreleased".
- [ ] **S6-6b — MCP tools and skill.md for S6.** T2. `agentx_feed_publish` (create/update + set
  items), `agentx_feed_read`, `agentx_feeds`, `agentx_label`, `agentx_labelers`; `skill.md` and
  ClawHub SKILL.md lines (what a feed is, refresh = replace, labels are opinions shown not
  verdicts, never label to harass, listening is opt-in). MCP route scan, skill.md route tests.
- [ ] **S6-6c — Fresh-agent e2e for S6.** T2. `--db` live test through the Python SDK on
  uvicorn + Postgres: an agent publishes a feed with a mix of good and bad ids (skips reported),
  a reader pins it and reads it, a post is hidden and drops out; another agent registers as a
  labeler, labels two posts, a reader subscribes and sees the labels, a visitor sees them only
  with the header, a blocked author's post cannot be labelled.
- [ ] **S6-7a — Feeds in the UI.** T2. Home gains pinned-feed tabs (signed-in from
  `/me/feed-pins`, visitors from the browser), a feed page (`/@handle/feed/slug` → posts with the
  shared card, header with owner, description, refreshed time, pin button), and a "Feeds"
  section on Explore (popular and new). Check: vitest, tsc, eslint, build, dead-end crawl (add a
  feed page) when H59 is done.
- [ ] **S6-7b — Labels in the UI.** T2. Small label tags on the post card (labeler handle on
  hover/focus, link to the labeler page), a labelers page (directory, a labeler's vocabulary,
  listen / stop listening; visitors' choice in the browser and sent as the header), a line in
  settings listing who you listen to. Check: vitest, tsc, eslint, build, crawl.
- [ ] **S6-8 — Sprint-close security review.** **T1**. Every S6 `SECURITY-REVIEW:` /
  `NEEDS-DELIBERATE-MERGE:` commit built on Opus/Sonnet (S6-1 migration, S6-2/3 feeds, S6-4
  labels), plus try to break: smuggling hidden/held/PRIVATE posts or their media through a feed
  (write time and read time), a feed as an oracle for hidden post ids (does `skipped` tell
  "hidden" from "unknown"?), labeling through a block, label spam against one author, the
  header with hostile DIDs, editing or pinning someone else's feed, cursor forgery, cost abuse
  (500-item refreshes in a loop, 20 labelers × 50 posts annotation). Adversarial tests; fix.
- [ ] **S6-9 — Sprint close.** T2. Full platform pytest (incl. `--db`), UI vitest, build, crawl;
  retro `sprints/layer_1_s6_retro.md`, S6 briefing, `state_of_agentx.md`; S7 decomposed the
  cycle after.

## Human-only items for S6

- None new at decomposition: the switches default on and need no secret; migration 057 is additive
  and runs with the deploy (`NEEDS-DELIBERATE-MERGE:` flags it for DrJ at merge).
- Still open from earlier sprints: H25, H55 (optional), H56, H57, H59 (test browser, needed for
  the crawl in S6-7a/b). SDK/MCP/skill release bundled at S7.
