# Layer 1 (Social), Sprint S6 "Agent-built custom feeds and labelers": Retro (engine run)

**Sprint:** S6 of `sprints/layer_1_social_plan.md` (DrJ, 1 Nov 2026)
**Dates:** 2026-11-04, engine cycles 364–376
**Branch:** `engine/phase-b`. **Not merged.** S1–S6 ride together on the branch. S6 adds
1 `NEEDS-DELIBERATE-MERGE:` (`fda3611`, migration 057, additive) and 5 `SECURITY-REVIEW:` commits:
`86c0adc` (feeds write), `eb4bc8b` (feeds read and pins), `c3d5829` (labelers and labels),
`59a34bb` (labels on every post), `63ee286` (the sprint-close review, Fable).
New API routes and one additive response field (`labels` on posts), none removed. Nothing touches
money, wallets, permissions or sign-in.
**Step list:** `docs/execution/engine/PLAN.md` (S6-0 to S6-9; moved to
`archive/PLAN_layer1_s6_feeds_labelers.md` when S7 is decomposed).
**Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`.
**Briefing for DrJ:** `sprints/briefing_2026-11-04_layer1_s6.md`.

## What was intended

An agent publishes a custom feed (a named list of post ids it computes and refreshes through the
API); anyone pins it as a Home tab; a feed never carries hidden or held posts. An agent registers
as a labeler and attaches labels from its own vocabulary to public posts; readers choose which
labelers to listen to; labels only tag, never hide. Agent-first for both, rate limits and the
content check on every write, blocks respected on every agent-to-agent reach, additive
migrations, $0 cost.

## What shipped (on the branch)

- **S6-1 Migration 057 and models** (`fda3611`). Tables `custom_feeds`, `custom_feed_items`,
  `feed_pins`, `labelers`, `labeler_values`, `post_labels`, `labeler_subscriptions` (cascades to
  agents and posts); request/response models; switches `CUSTOM_FEEDS_ENABLED` and
  `LABELERS_ENABLED` (default on).
- **S6-2 Feeds write** (`86c0adc`). Create, edit, delete; `PUT /feeds/{id}/items` replaces the
  whole list (≤ 500 ids) in one transaction; unreadable ids are skipped with one reason
  (`not_available`) so a feed is no oracle; ≤ 10 feeds, ACTIVE and ≥ 24 h old, content check,
  per-agent limits.
- **S6-3 Feeds read, directory and pins** (`eb4bc8b`). `GET /feeds` (popular / new),
  `/feeds/{id}`, `/feeds/{id}/posts` (rules applied again on read), `/agents/{did}/feeds`,
  pin / unpin, `/me/feed-pins` (≤ 10).
- **S6-4 Labelers and labels** (`c3d5829`). Register / edit / delete a labeler with a vocabulary
  of ≤ 20 values; `POST` / `DELETE /labels` in batches of ≤ 50; subscriptions (≤ 20);
  `GET /labelers`, `/labelers/{did}`, `/posts/{id}/labels`. Refused across a block; no
  notification to the author.
- **S6-5 Labels on every post** (`59a34bb`). One annotator on every post reader (Latest,
  Following, global, search, tags, threads, profile tabs, single post, quotes, feeds), one query
  per page; visitors choose labelers with the `X-AgentX-Labelers` header; a guard test walks every
  route returning posts.
- **S6-6 Agent-first** (`194303f`, `68858ef`, `8230fc4`). Python (sync + async) and TS SDK calls;
  nine MCP tools (`agentx_feed_publish`, `agentx_feed_read`, `agentx_feeds`, `agentx_pin_feed`,
  `agentx_labeler_setup`, `agentx_label`, `agentx_labelers`, `agentx_listen_labeler`,
  `agentx_post_labels`); `skill.md` and ClawHub SKILL.md sections; a fresh-agent e2e through the SDK.
- **S6-7 Website** (`6edacc7`, `87588bf`). Feed page at `/@handle/feed/slug`, pinned feeds as Home
  tabs (browser storage for visitors), a Feeds section on Explore; label tags on the post card
  (≤ 4, "+N"), `/labelers` and `/labelers/{did}`, a Labels section in Settings.
- **S6-8 Security review** (`63ee286`, Fable). 5 marked commits reviewed, **4 issues found and
  fixed**, 17 adversarial tests (see "What didn't").

## Acceptance (run locally at close, cycle 376)

| # | Criterion | Result |
|---|---|---|
| 1 | An agent publishes a named, described feed it computes and refreshes through the API | Met. `test_custom_feeds_write_db.py`, fresh-agent `test_feeds_labels_sdk_live_db.py`. |
| 2 | Anyone pins a feed as a Home tab | Met. Pins API (signed in), browser pins (visitors), Home tabs; `lib/customFeeds.test.ts`. |
| 3 | A feed never contains hidden or held posts (at write and at read) | Met. Write skip rules, read re-check; S6-3 and S6-8 tests. |
| 4 | Agents register as labelers and label public posts | Met. `test_labelers_db.py`, e2e. |
| 5 | Readers choose which labelers to listen to; labels only tag, never hide | Met. Subscriptions, header, `PostLabels` tags; nothing is hidden or dimmed. |
| 6 | Rate limit and content check on every write; blocks on every agent-to-agent reach | Met after the S6-8 fixes (feeds and labeler pages across a block; labeler text and label values now content-checked). |
| 7 | Agent-first list (REST in OpenAPI, both SDKs, MCP, `skill.md`, fresh-agent e2e) | Met. |
| 8 | Migration additive; $0 cost | Met. 057 only adds tables; no paid service. |
| 9 | Existing tests keep passing, incl. the whole `--db` suite | See the cycle 376 entry in `ENGINE_LOG.md`. Dead-end crawl not run (H59 still open). |

## What went well

- Writing the design defaults into the plan at decomposition (one skip reason, rules re-applied on
  read, opt-in labels, 24 h gate) meant every build step and the review tested the same promises.
- Applying the visibility rules again at read time made "a post hidden later drops out" free; the
  review found no way to smuggle a hidden post through a feed.
- One annotator with a guard test over every post route kept labels consistent across a dozen
  readers without touching each one by hand twice.

## What didn't

- The review found that blocks were honoured in feed and labeler **lists** but not when a feed or
  labeler page was opened directly by its address (S6-3 had recorded "the feed's meta stays
  readable across a block" as a decision; the review judged that inconsistent with profiles).
  Lesson: "every agent-to-agent reach respects blocks" includes direct reads by id, not only lists.
- A label kept showing on a post its author later made private; the shown-labels query now also
  checks the post's visibility. Lesson: annotators need the same visibility check as the reader.
- Labeler text accepted a NUL byte (a 500 from Postgres) although feed text already refused control
  characters. Lesson: reuse one text cleaner across sibling models from the start.
- The dead-end crawl still waits on the test browser (H59), for the second sprint running.

## Decisions I made (reversible)

- A feed refresh replaces the whole list; one skip reason for every bad id; feeds keep their
  author's order (no founders cap inside a feed) (S6-0).
- Publishing a feed or being a labeler needs an ACTIVE account ≥ 24 h old; pinning needs ACTIVE
  only; caps 10 feeds, 10 pins, 20 subscriptions, 20 values, 500 items, 50 labels per call (S6-0, S6-3).
- Labels are opt-in: nobody listens to anyone by default; the header, when present, overrides a
  signed-in reader's subscriptions; an empty header means "nobody" (S6-0, S6-5).
- Pin and subscriber counts count ACTIVE agents only; a pin across a later block is kept but not
  shown (S6-3, S6-4).
- Deleting your own feed, labels or labeler is always allowed, even with a switch off (S6-2, S6-4).
- Write answers and the Work-layer community feeds carry `labels: []` (S6-5).
- No MCP tool to delete a feed or stop being a labeler; publishing is by slug (S6-6b).
- Signed in, the website never sends the header and never merges browser pins into the account;
  ≤ 4 tags on a card (S6-7).
- Still no SDK release at this close; it ships once at Layer 1 close (S7).

## Observations for later (residual, by design)

- A labeler can make a fresh account after 24 h to keep labelling an author who blocked it; only
  listeners see it and `LABELERS_ENABLED=0` stops all of it.
- Pin and subscriber counts can be pumped by many ACTIVE accounts, as follows can.
- A visitor who sends the labelers header skips the shared anonymous cache (per-IP limits still apply).
- The Python SDK has no `block` / `unblock` call (pre-S6 gap); worth a small step in S7.
- A malformed URL escape in any dynamic website route (`/agents/%E0%A4%A`) gives a 500 from Next
  before the page runs (pre-S6); harmless, worth a tidy-up in S7.

## Next

S7 "Close" (stranger test, Lighthouse, Fable review of S2–S6, docs and SDK export, Layer 1
briefing). Decomposed into `PLAN.md` next cycle.
