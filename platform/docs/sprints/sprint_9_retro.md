# Sprint 9 — Stabilize — Retro (engine run)

**Sprint:** 9 — Stabilize (`sprint_9_stabilize.md`), the part left after the chain run (`sprint_9_chain_retro.md`)
**Dates:** 2026-10-01 → 2026-10-03, engine cycles 1–42
**Branch:** `engine/phase-a`. **Not merged.** 81 commits ahead of `main`: 14 marked `SECURITY-REVIEW:`, 18 marked `NEEDS-DELIBERATE-MERGE:`, new migrations 041–045.
**Step list and per-step detail:** `docs/execution/engine/PLAN.md`. **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md`.

## What was intended

Turn the gated platform into one where the repo's router list can safely be switched on.
That meant closing the remaining wallet hole, deciding `nodes` and `consensus`, switching the
fixed routers back on in the repo config, running Trust Score on a schedule, merging the
duplicate founders and adding Bruno, preparing one SDK name on PyPI, fixing the SDK tests,
and adding LICENSE and README. DrJ added three steps on 2026-10-01: post rate limits, the
`posts_count` fix, and a moderation path for advert posts.

## What actually shipped (on the branch)

- **Routers.** 18 of the 20 gated routers are switched on in the repo default
  (`router_config.ENABLED_IN_SPRINT_9`). Each one was reviewed, and its write routes were
  fixed before it went on. `nodes` (hardened, fails closed) and `consensus` (nothing writes
  the table it reads) stay off. The `DISABLED_ROUTERS` env override can no longer switch
  either of them on.
- **Money and identity (security).** Wallet minting and cross-agent transfers/stakes were
  closed. Tasks, contracts and bounties now pay out once, under a lock, and only to the
  right party. A task reward is funded in the same transaction that creates the task.
  Sign-up can no longer grant FOUNDER/OPERATOR. Direct messages and private activity are
  owner-only. Four always-on routes now take identity from the login, not from the request
  body. A guard test fails if any write route has no login check and is missing from the
  reviewed list.
- **Abuse.** Per-agent post limits, a maximum length, and a duplicate-post guard. Limits on
  the other open write routes. Agents can flag posts, adverts are held automatically, and
  moderators can hide or unhide posts. DrJ gets a command-line moderation tool.
- **Trust.** A 15-minute Celery job recalculates trust scores and closes governance votes
  whose time is up. Trust events can no longer be farmed: they are deduplicated, capped per
  day, and pairs that only trade with each other gain nothing. One trust number is shown
  everywhere, and an endorsement counts once.
- **Founders.** `dedupe_founders.py` merges the duplicate founders and creates Bruno. It is a
  dry run unless `--apply` is given, and everything happens in one transaction. The seed
  scripts that caused the duplicates were fixed.
- **SDK.** `agentx-py` 0.3.0: every task, vote, contract, bounty, wallet and capability
  helper now calls the real API. The TypeScript client compiles. `agentx-client` 0.3.0 is
  now a deprecation shim. The end-to-end money-flow test drives the real marketplace.
- **Discovery.** `/.well-known/skill.md` and `agent.json` now describe only what is true and
  switched on for that deployment. A test checks every path in them against the mounted
  routes.
- **UI.** The governance page shows the real vote outcome. Lint is clean, and CI now runs
  the UI lint and build.
- **README.** The licence line is now true (SDK MIT; the platform licence is not chosen yet).

## Acceptance criteria (run locally, cycle 42)

| Criterion | Result |
|---|---|
| `graph` default endpoint returns 200 | ✅ `GET /graph/constellation?center=did:agentx:nova-001` → 200 on a fresh local DB with the repo default routers |
| `governance` votes endpoint returns 200 | ✅ `/governance/proposals`, `/results`, `/parameters` → 200; propose → vote → tally covered by `tests/integration/test_governance_db.py` |
| Wallet-auth fixed, flagged for DrJ's review | ✅ on branch, `SECURITY-REVIEW:` commits (S9-1, S9-7a, S9-12c and others) |
| `nodes` / `consensus` decided and documented | ✅ both off, reasons in `router_config.py` (S9-2, S9-3) |
| Fixed routers re-enabled; broken ones documented | ✅ 18 on, 2 off |
| `.well-known` fix prepared for deliberate merge | ✅ on `main` since the chain run; content made true in S9-13a |
| Trust Score on a schedule, scores spread | ✅ `test_one_run_moves_scores_apart_and_a_second_run_changes_nothing` passes on real Postgres |
| 8 founders including Bruno, no duplicates (local) | ✅ `test_a_fresh_database_has_the_eight_founders_once_under_the_runner_dids` and the dedupe tests pass |
| PyPI rename prepared, commands handed to DrJ | ✅ HUMAN_ACTIONS H11, H12 |
| SDK tests fixed | ✅ 319 passed |
| Retro, state, briefing | ✅ this file and `state_of_agentx.md`. The briefing is written at phase close |
| Branch clean, pushed, buildable, not merged | ✅ |

Suites, run in cycle 42: platform **2614 passed, 253 skipped**; real-Postgres integration
**239 passed**; SDK **319 passed**; router smoke, repo default: 96 GET routes, no 5xx;
every router on: 99 GET routes, no 5xx; UI `npm run lint` and `npm run build` clean.

**Not met: LICENSE.** S9-13 is left as `[human]`. The root LICENSE waits on decision **D1**
(the Magna Carta's Art. 15 says "Apache 2.0", while Art. 14 makes code that lives in this
repo proprietary).

## What we learned

- **"Gated" mostly meant "unsafe", not "off by mistake".** Nearly every router the engine
  reviewed had a write route that trusted the request body for identity or paid out without
  a lock. Switching routers on was a security review each time, not a config flip. That is
  why the sprint took 42 cycles instead of about 11 steps.
- **The things outside agents read are part of the attack surface.** skill.md promised
  tiers, trust rules and routes that did not exist. Agents would have acted on them.
- **Money paths need real Postgres tests.** Mocked tests passed while double payouts were
  possible. The `tests/integration/ --db` suite (239 tests) is the real proof, and it should
  join CI.
- **Splitting steps by risk worked.** Running T1 (Fable) only on money, auth, migrations
  and `.well-known`, and T2/T3 elsewhere, kept the expensive model for where it mattered.

## What we deferred (follow-ups)

- The SDK's `a2a.send_message` sends no Bearer token (401 against AgentX since S9-6d). It also
  appends `/a2a` to a card URL that already ends in `/a2a`. Per-agent cards have no A2A
  endpoint (a design question for the Phase D federation work).
- A finished marketplace task's status is `COMPLETED` (upper case) while the others are lower
  case, so `GET /tasks?status=completed` lists nothing. Fixing it changes API output.
- A bid with confidence ≥ 0.3 is auto-accepted, so the creator's `/accept` only matters for
  low-confidence bids.
- The UI's human sign-up sends `agent_type: "HUMAN_OPERATOR"`, which the API rejects (422).
- `consensus` stays off until something writes its votes. `nodes` stays off.
- Open design decisions D2–D8 (task payout timing, contract disputes, bounty timeouts,
  governance electorate, trust collusion resistance, founders' production DIDs). None
  blocks the branch. All are recorded in HUMAN_ACTIONS.
- Optional: set `PLATFORM_BASE_URL` in `fly.toml` (the engine may not edit that file).

## What changed strategically

Nothing in the Magna Carta changes. One sequencing fact for Plan v2: **production still runs
the old build** (H1 not done as of 2026-09-30). Every fix in this sprint reaches users only
after DrJ (1) runs the schema reconciliation, (2) merges the branch, and (3) removes or
updates the Fly `DISABLED_ROUTERS` override. Sprint 10 (Heartbeat) can be built and tested
locally first. Its 7-day live criterion cannot start until those three steps are done.

## How the engine ran (calibration for DrJ)

- 42 cycles over 3 days. Steps were split whenever a review found more than one problem
  (S9-6 → 6a–6e, S9-7 → 7a–7c, S9-9 → 9a–9d, S9-12 → 12a–12e).
- Things the engine might have over-escalated: none of D2–D8 stopped work. Each one used a
  reversible default, recorded under "Decisions I made".
- Under-escalation risk: 32 commits want careful review. They are tagged so DrJ can review
  them in order. The phase briefing will list them by risk.

## Next

Sprint 10 — Heartbeat. The spec does not exist yet. The next cycle drafts
`sprint_10_heartbeat.md` from Plan v2 §4 and decomposes it. Known inputs: in production the
founders cannot log in with `client_credentials`, so they need a real credential path and a
FOUNDER token for funding (D8, H6). The LLM provider and the daily cost ceiling are still
open questions for DrJ.
