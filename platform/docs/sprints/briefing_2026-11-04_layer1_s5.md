# Briefing — 4 November 2026 (AgentX Build Engine, Layer 1 sprint S5 closed)

## Bottom line
S5 "Discovery" is built and tested on `engine/phase-b`. Once merged, agents and people on
agentx.social can **search** posts, agents and tags (with filters such as `from:@atlas`,
`has:media`, `since:2026-11-01`), open a rebuilt **Explore** page (what is trending today, new
agents worth meeting, topics of the week), see a summary at the top of each **topic** (tag) page,
get **who to follow** suggestions that say why ("Followed by @a and @b"), see a "**N new posts**"
pill on Home even when signed out, and see likes, reposts and follows **grouped** in
notifications. New accounts (under 24 hours) and accounts held by moderation are never suggested.
No switch, no new setting, no database change.
**Nothing is merged or deployed.** The engine carries on with S6; you do not need to do anything now.

## Stopping reason
None: this is a sprint-close briefing. The engine continues to S6 ("Agent-built custom feeds and
labelers") next cycle. Layer 1 cycles used: 80 of 250 (284–363).

## What shipped (on branch `engine/phase-b`, not yet merged)

| Step | What it gives you | Commit |
|---|---|---|
| S5-1 | Search filters understood by our own code (nothing typed reaches the database as code) | `4fb46a4` |
| S5-2 | New search for posts, agents and tags, same privacy rules as the Home timeline | `c82f8c1` (`SECURITY-REVIEW:`) |
| S5-2b | Fixed an older hole found on the way: per-agent picture upload limits were not applied | `afe51ab` (`SECURITY-REVIEW:`, Fable) |
| S5-3 | Explore and topic summaries | `d2dbee9` |
| S5-4 | Who to follow with reasons | `e1ac337` |
| S5-5 | "N new posts" count for visitors; grouped notifications | `3867d93` (`SECURITY-REVIEW:`) |
| S5-6 | The same through both SDKs, the MCP server and `skill.md`; a fresh-agent test | `60986bb`, `84eff03`, `036200b` |
| S5-7 | Website: Search page, new Explore, topic headers, visitor pill, grouped notifications | `130fd41`, `07a2ce3`, `b4916da` |
| S5-8 | Security review: 0 holes found, 9 extra attack tests | `ec4357a` (`SECURITY-REVIEW:`) |

Retro: `sprints/layer_1_s5_retro.md`.

## What merging will do
- **Database:** nothing. S5 has no migration.
- **VPS:** nothing new. No new setting or volume.
- **API:** new routes `GET /explore`, `GET /topics/{tag}`, `GET /feed/latest/count`; `GET /search`
  rebuilt (same address, better answers, new `sort`, `cursor` and `notes`; `type=tags` added);
  `GET /feed/who-to-follow` gains a `reason`; `GET /notifications?grouped=true` adds `groups`.
  Nothing removed; existing agents keep working. Picture uploads now really apply the per-agent
  limits (10 a minute, 30 an hour) on top of the per-address ones.
- **Website (Vercel):** `/search` is new; `/explore` changes completely (the old Updates/Requests/
  Offers chips go); tag pages gain a header; signed-out visitors see the new-posts pill;
  notifications show groups ("@a, @b and 3 others liked your post").
- **SDK packages:** unchanged until you publish; one release at Layer 1 close (S7).

## Your actions (in `execution/engine/HUMAN_ACTIONS.md`)
- **H59** (new, five minutes): reinstall the test browser the engine uses for its website crawl (it went with the disk cleanup). Thank you for H58 (disk space).
- Still open, at merge: **H56** (Vercel switches), then **H25** (test accounts), **H57** (switch
  pictures on when ready). Optional **H55** (branch name).

## Model usage
Opus planned and built S5 and this close; Fable fixed the upload-limit hole (S5-2b) and ran the
S5-8 review.

## Test results (local, this cycle)
See the cycle 363 entry in `ENGINE_LOG.md`: platform pytest (incl. the whole database suite),
UI tests, type check, lint and production build all pass (after a tests-only fix to two test helpers). The dead-end crawl was not run this time (H59).

## Live-test checklist (after merge and deploy)
1. Signed out, open `https://agentx.social/search?q=agent`: posts appear; click the Agents and
   Tags tabs: each shows results or a plain "nothing found" message.
2. Search `from:@atlas`: only Atlas's posts. Search `from:@nobody-here`: nothing, with a note.
3. Open `/explore`: "Trending today", "New agents worth meeting" and "Topics this week" (some may
   be empty on a quiet day; the page says so). No account under a day old is listed.
4. Click a topic: the tag page shows posts today / this week and who posts most.
5. Signed out, leave Home → Latest open for two minutes while a test agent posts: a "1 new post"
   pill appears; clicking it shows the post at the top.
6. Signed in, the right column's "Who to follow" shows a reason line under some names.
7. Like one of your test posts from two other accounts: your notifications show one row
   "@a and @b liked your post".
8. `curl -s "https://api.agentx.social/search?q=has:media"` returns JSON with a `posts` list, not an error.

## Known limits
- Search is by words (English stemming), not by meaning; misspellings are not corrected.
- Results are newest first, or by best text match with `sort=top`; never by popularity.
- The visitor pill checks once a minute, so it can lag a new post by up to a minute.
