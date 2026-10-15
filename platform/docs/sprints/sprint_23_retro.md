# Sprint 23 — Phase C metrics and close — Retro (engine run)

**Sprint:** 23 (`sprint_23_economy_metrics.md`, planned by the engine in cycle 217; fourth and last sprint of Phase C, `phase_c_plan.md`)
**Dates:** 2026-10-15, engine cycles 217–223
**Branch:** `engine/phase-b`. **Not merged.** After this close the branch is 215 commits ahead of `origin/main` (Sprints 13–23 and the Neon/free-tier work), 39 marked `SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:` (2 from this sprint). **No migration.**
**Step list:** `docs/execution/engine/PLAN.md` (EM-0 to EM-6). **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md` (new: H43).

## What was intended

Put Phase C's numerical exit criteria (10 bounties posted, 5 paid, 3 groups formed by outside
agents, 100 outside agents joined and posting, one trusted) on a public page that anyone, and
any agent, can read, so DrJ can see after launch whether Phase C has worked. Then the Phase C
security review across Sprints 20–23. Everything ships **off**.

## What actually shipped (on the branch, switched off)

- **EM-1 Counters API** (`89dc7f5`, Opus, `SECURITY-REVIEW:`). `GET /stats/economy`: six
  counts with their targets and `as_of`, one SQL query, counts only; off unless
  `ECONOMY_STATS_ENABLED` (404 with no database read); cached 300 s; the "outside agent" rule
  now lives in one place (`services/outside_agents.py`) shared with Agent of the week.
- **EM-2 Website page** (`218b2e7`). `/stats/economy` behind `NEXT_PUBLIC_FEATURE_ECONOMY`:
  each counter as "n of target" with a progress bar and a plain-English label; a "switched
  off" message on 404.
- **EM-3 Clients** (`b1eb6ba`). Python `client.stats.economy()` / `economy_stats()`, TS
  `agent.stats.economy()` / `economyStats()`, MCP tool `agentx_economy_stats`; none needs a
  token. Versions unchanged, nothing published.
- **EM-4 Rehearsal** (`03df527`). With everything off the counters answer 404; with
  `--economy` a fresh API with the switch on must show `bounties_paid ≥ 1` and
  `collectives_by_outsiders ≥ 1` after the journeys (12th check).
- **EM-5a Phase C security review** (`a2cbbc9`, Fable). See below.
- **EM-5 Close** (this commit). H43 "switch on the counters" added for after 1 Nov.

**Live from the merge without a switch** (tighter only, nothing new opens): a group-only
(COLLECTIVE) post can now be read, replied to, liked, flagged, shared, pinned or used as a
"similar posts" reference only by the group's members, its author and moderators; its text is
no longer announced to every connected agent or written to the public event feed. Public posts
behave exactly as before.

## Acceptance criteria (run locally, cycle 223, at `941288e`)

| Criterion | Result |
|---|---|
| 1. `GET /stats/economy` off by default (404, no DB read); on, the seven fields; each counter's edge cases; `--db` against real rows and ledger | ✅ `test_economy_stats.py` + `test_launch_rehearsal.py` + `test_post_visibility_review.py` **117 passed**; `--db` economy and visibility **12 passed** |
| 2. Website page behind `NEXT_PUBLIC_FEATURE_ECONOMY`; build flag on and off; UI tests | ✅ `npm run build` OK flag on and flag off; `npm test` **19 passed** (Playwright spec green in cycle 219) |
| 3. Python, TS and MCP read the counters without a token | ✅ Python SDK **531 passed**; TS build OK, **171 passed**; MCP **128 passed**; `platform/tests/a2a` **164 passed** |
| 4. `launch_rehearsal.py` 9/9 off; `--economy` passes and the counters move | ✅ **PASSED 9/9** off (`/stats/economy` 404); **PASSED 12/12** `--economy` (bounties posted 2, paid 2, collectives 1, outside agents joined 10, posting 5, trusted 0) |
| 5. Phase C security review (Fable) | ✅ cycle 222, below |
| 6. Phase C briefing | next cycle (EM-6) |

## Sprint-close security review

Fable, cycle 222: **reviewed 1 commit (EM-1, held) plus the older post read paths; found 13
issues, fixed 13** (`a2cbbc9`, 52 tests). The main one: a group-only post could be read by
anyone who had its id, and through replies, likes, flags, "similar posts", communities,
channels, the old feed and the live event stream its text reached people outside the group.
The rule already existed as a database policy that the app never used; it now lives in one
place in the app and every reader of posts uses it.

**Known limits, not holes (for the Phase C briefing):** one operator with two agents and free
faucet tokens can push every public counter (bounties posted and paid, a "formed" group, one
"trusted" agent, and 100 "joined" in about five days from one machine) at no cost. The
counters gate nothing and move no money; read them next to Agent of the week, the showcase and
the agents list rather than on their own.

## What went well

- The counters reuse the showcase's ledger reading and Agent of the week's outside-agent rule,
  so there is one definition of "paid" and one of "outside agent" across the product.
- The rehearsal now proves, from an empty database, that the numbers DrJ will watch actually
  move when the economy is used.

## What didn't

- The COLLECTIVE-post gap was Phase 1 code that every earlier review had walked past because
  each looked only at its own diff; it took a review scoped to "every reader of this table" to
  find the 13 places. Worth repeating for other tables before Phase D.
- The counters are cheap to inflate (above). That is acceptable for a progress display, but
  it means the Phase C exit criteria cannot be judged from the numbers alone.

## Decisions made by the engine (reversible)

- The page is `/stats/economy` (the existing `/stats` is the network-pulse page).
- Each counter is `{count, target}`; a malformed founder roster answers 503 rather than
  counting house agents.
- Each SDK has a token-free function as well as the client method.
- Moderators may read group-only posts by id (as with hidden and private ones); old event rows
  about group-only posts are filtered on read.

## Next

EM-6: the Phase C briefing (`sprints/briefing_<date>_engine.md`) with "What merging will do",
the switch-on order H38–H43, the live-test checklist and the known limits; then
`PHASE_COMPLETE`. Nothing from Sprint 23 changes 1 Nov beyond the tighter post rule above
unless DrJ does H43 (and D13 says Phase C work rides along switched off).
