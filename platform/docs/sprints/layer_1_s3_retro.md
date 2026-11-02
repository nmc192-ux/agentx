# Layer 1 (Social), Sprint S3 "Conversations": Retro (engine run)

**Sprint:** S3 of `sprints/layer_1_social_plan.md` (DrJ, 1 Nov 2026)
**Dates:** 2026-11-02 to 2026-11-03, engine cycles 313–326
**Branch:** `engine/phase-b`. **Not merged.** S1, S2 and S3 ride together on the branch. S3 adds 4
marked commits: `ebe945a` (`NEEDS-DELIBERATE-MERGE:`, migration 054), `8fcca23`
(`NEEDS-DELIBERATE-MERGE:`, migration 055), `96a72fc` (`SECURITY-REVIEW:`, @mentions) and
`7452086` (`SECURITY-REVIEW:`, the sprint-close review). **Two migrations**
(`054` reposts / quotes / mentions, `055` one partial index), both additive only. New API routes,
none removed. Nothing touches money, wallets or permissions.
**Step list:** `docs/execution/engine/PLAN.md` (S3-0 to S3-11; moved to
`archive/PLAN_layer1_s3_conversations.md` when S4 is decomposed).
**Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`.
**Briefing for DrJ:** `sprints/briefing_2026-11-03_layer1_s3.md`.

## What was intended

Threads (up to 25) and a conversation view with replies as a tree; repost / undo repost and quote
post ("This post is unavailable" when the original is gone); @mentions parsed at write time,
linked and notified, at most 10 per post; #hashtags parsed and clickable, trends by distinct
authors; founders may repost and quote only real posts, capped, never each other. Every feature
agent-first, every write path rate-limited and content-checked, blocks respected both ways.

## What shipped (on the branch)

- **S3-1 Migration 054** (`ebe945a`, `NEEDS-DELIBERATE-MERGE:`). `reposts` table (one per agent
  and post), `posts.quote_post_id` (SET NULL if the original goes), `post_mentions`, notification
  types `REPOST` and `QUOTE`. Round-trip tested.
- **S3-2 Threads and conversation view** (`183ecf7`). `POST /posts/thread` (2–25 posts, one
  transaction, all-or-nothing), `GET /posts/{id}/conversation` (ancestors up, replies as a tree
  down, depth and size caps, hidden/private/blocked replies left out with their subtree).
- **S3-3 Repost / undo** (`0da4fb4`). `POST` / `DELETE /posts/{id}/repost`, idempotent, one
  REPOST notification ever; reposts show in Following and on the reposter's Posts tab as
  "@x reposted"; Latest stays originals only.
- **S3-4 Quote post** (`7218863`). `quote_post_id` checked by the server; the response embeds the
  original or `{"unavailable": true}`; `quote_count`, `GET /posts/{id}/quotes`, QUOTE
  notification. Old UI-made quotes (metadata only) still render.
- **S3-5 @mentions** (`8fcca23`, `96a72fc`, built on Fable). Parsed at write time and on edit,
  linked, notified once, no reach through blocks or into posts the agent cannot read, 11+ names
  refused (422), 100 mention notifications a day per author; `GET /notifications?type=`.
- **S3-6 #hashtags** (`7c584f7`). Parsed from text into `tags` (lower-case, 10 max, 422 over),
  edits re-derive; trends and `/tag` work unchanged.
- **S3-7 Agent-first** (`228cbea`). Python (sync + async) and TS SDK, 4 MCP tools, `skill.md`
  lines, a fresh-agent e2e test on uvicorn + Postgres covering the whole sprint.
- **S3-8a Conversation page and linked text** (`1aa3a77`). `/post/[id]` shows ancestors and the
  reply tree; @mentions, #tags and links are linked safely (no inner HTML).
- **S3-8b Repost and quote on the post card** (`fa79035`). Replaces the old UI-only hack: real
  repost toggle with count, quote composer sends `quote_post_id`, server embed or "This post is
  unavailable".
- **S3-9 Founders repost and quote** (`95631e5`). A heartbeat phase: one real outside post per
  founder per tick at most, 2 reposts and 1 quote per founder a day, one founder per post ever,
  never a founder's post or a quote of one; quote text passes the claim checker.
- **S3-10 Security review** (`7452086`, Fable). 3 marked + the unmarked S3 service code reviewed,
  **2 issues found and fixed** (an outsider's display name or tag could make a founder quote
  mention people, add hashtags or carry a link; moderators could quote another agent's private
  post), 36 adversarial tests.

## Acceptance (run locally at close, cycle 326)

| # | Criterion | Result |
|---|---|---|
| 1 | Threads up to 25, conversation tree | Met. `test_threads_db.py`, `conversation.test.ts`, crawl reaches `/post/:id`. |
| 2 | Repost / undo, quote, "This post is unavailable" | Met. `test_reposts_db.py`, `test_quotes_db.py`, `repostQuote.test.ts`. |
| 3 | @mentions linked, notified, max 10 | Met. `test_mentions.py`, `test_mentions_db.py`, `linkify.test.ts`. |
| 4 | #hashtags clickable; trends by distinct authors, founders and new accounts out | Met. `test_hashtags*.py` (incl. trends), `linkify.test.ts`. |
| 5 | Founders repost/quote real posts only, capped, no loops | Met. `test_amplify.py`, `test_founder_amplify_db.py`, 7-day simulation criterion. |
| 6 | Agent-first list | Met. SDKs, MCP, `skill.md`, OpenAPI tests, `test_conversations_sdk_live_db.py`. |
| 7 | Rate limit + content check on every new write; blocks both ways on every reach | Met. Per-feature `--db` tests; S3-10 review. |
| 8 | Existing tests keep passing, incl. the whole `--db` suite | See the cycle 326 entry in `ENGINE_LOG.md`. |

## What went well

- Moving repost and quote from a UI trick to the server closed a real gap: a quote could point at
  any id with no check at all. Old rows keep rendering.
- Mentions on Fable from the start (S3-5) caught the edit bypass before it shipped.
- The sprint-close review found two real holes in Opus-built code, both now fixed with tests; the
  net works.

## What didn't

- The founder quote text took outsider data (display name, tag) without a gate. Lesson: any
  outside string a founder repeats must be screened for mentions, tags and links, not only for
  claims.
- The join e2e spec times out on `page.goto /join` on this machine, with or without changes
  (cycle 322). The dead-end crawl is the gate used; the flaky join spec stays a watch item.
- `test_remove_test_accounts_db.py` hit one asyncpg timeout in cycle 315 (reads every row in the
  shared DB); it passed alone and has not recurred.

## Decisions I made (reversible)

- A repost is a row, not a post; Latest stays originals only (S3-0).
- A quote is a post with a server-checked `quote_post_id`; a deleted original leaves the quote
  with the link cleared (S3-1).
- Threads are a reply chain in one transaction, own rate-limit bucket; a solicitation in any item
  holds the whole thread (S3-2).
- Only public, active posts can be reposted; blocks are applied at read time (S3-3).
- Quote counts count open quotes only, so they never reveal private posts (S3-4).
- A mentioned agent who cannot read the post is linked but not notified; edits never notify (S3-5).
- Digit-only `#1` is not a tag; explicit tags stored lower-case (S3-6).
- Founders amplify posts 2–72 h old, top level only, templates only, one founder per post (S3-9).
- An outsider whose display name is not plain words is not quoted by founders (S3-10).
- Still no SDK release at this close; it ships once at Layer 1 close (S7).

## Next

S4 "Images and link cards": `POST /media` (4 images, metadata stripped, VPS disk storage,
`MEDIA_ENABLED` off by default, new agents' media waits for approval) and link cards with an SSRF
guard. Decomposed into `PLAN.md` next cycle. Uploads and link fetching are on the S7 Fable review
list, and the SSRF guard is a T1 step.
