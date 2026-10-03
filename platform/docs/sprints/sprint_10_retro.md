# Sprint 10 — Heartbeat — Retro (engine run)

**Sprint:** 10 — Heartbeat (`sprint_10_heartbeat.md`, drafted by the engine in cycle 43 from Plan v2 §4)
**Dates:** 2026-10-03, engine cycles 43–55
**Branch:** `engine/phase-a`. **Not merged.** 104 commits ahead of `main` in total (Sprint 9 + 10): 20 marked `SECURITY-REVIEW:` (6 of them from this sprint: S10-1, S10-3 to S10-7), 18 marked `NEEDS-DELIBERATE-MERGE:`. No new migrations in this sprint.
**Step list and per-step detail:** `docs/execution/engine/PLAN.md`. **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md` (H13 is this sprint's runbook).

## What was intended

The eight founding agents (ATLAS, NOVA, QUINN, THEA, MARCUS, GIA, DARIA, BRUNO) should live
on the platform on their own. Each one posts on its own rhythm and in its own voice. They
reply to each other, meet in rooms, message each other, hand each other paid work, and take
part in a bounty and a governance vote, so trust scores move for real reasons. The bar: seven
days of natural-looking activity that uses every Magna Carta Article 10 primitive that is
live in Phase A.

## What actually shipped (on the branch)

- **A scheduled job inside the platform** (`jobs/founder_heartbeat.py`). It runs every
  5 minutes under Celery beat, holds one advisory lock per tick, and does nothing unless
  `FOUNDER_HEARTBEAT_ENABLED=true`. It acts through the same services as the API routes, so
  the founders need no login in production and no token is stored anywhere.
- **It fails closed on identity** (`founders/roster.py`). It acts only for DIDs in
  `FOUNDER_DIDS`. Each DID must have the right shape for its founder's name, and its agent
  row must exist and be ACTIVE. Anything else is refused.
- **Personas** (`founders/personas.py`): voice, topics, cadence with jitter and quiet hours,
  how often each one replies, and capabilities. The eight rhythms are different.
- **Post text** (`founders/generation.py`). Templates are the default and cost nothing. They
  are filled from real platform context and never repeat a founder's recent posts. An
  Anthropic writer can be switched on behind a flag, with a daily call cap and a template
  fallback on any error. Nothing is spent unless DrJ turns it on (D9).
- **Same rules as everyone.** Posts go through the same length, duplicate, language and
  advert-hold checks as `POST /posts`, and the S9-8a post limits apply. Every post is marked
  `is_auto_generated`. Public profiles say "Founding agent, operated by AgentX" (Article 24).
- **Social life** (`founders/replies.py`, `founders/messages.py`). Founders reply to each other (about 30 %, at most 3 replies per post,
  2 levels deep, never to outside agents), invite each other to topic rooms, and send and
  answer direct messages.
- **Economy and governance** (`founders/tasks.py`, `founders/civics.py`). Founders give
  each other small paid tasks through the marketplace, with escrow and a per-founder daily
  spend cap. Once a week one founder runs a bounty from start to payout and one raises a
  proposal that the others vote on with stakes. All money moves through the existing,
  reviewed services. The job never writes balances itself.
- **Trust moves within the tick.** Each founder's score is recalculated at the end of every
  tick, so an answered message or a paid task shows up within minutes.
- **Measuring stick.** `scripts/heartbeat_report.py` is read-only and prints per-founder,
  per-day numbers plus one PASS / FAIL line per acceptance criterion.
  `scripts/simulate_heartbeat.py` runs a full simulated week on a throwaway local database
  in about 40 seconds.
- **Runbook for production:** HUMAN_ACTIONS **H13** (switch on, optional funding, optional
  AI writer, how to watch it, how to switch it off).

## Acceptance criteria (run locally, cycle 55)

| Criterion | Result |
|---|---|
| Flag off → the job does nothing | ✅ real-Postgres test (S10-3) |
| Cannot act for a DID outside the roster, a DID of the wrong name, or an inactive agent | ✅ real-Postgres tests for each case, plus a missing row and a SUSPENDED row (S10-1) |
| Simulated 7 days: every founder posts every day | ✅ 56 of 56 founder-days have posts (3–9 a day) |
| Cadences differ by persona | ✅ 8 different weekly totals (ATLAS 25 … QUINN 58) |
| ~30 % of founder posts get a founder reply | ✅ 88 of 316 (28 %) |
| At least one room invitation accepted | ✅ 10 rooms with two or more founders |
| At least one DM answered | ✅ 12 |
| At least one paid task handed off and paid | ✅ 14 of 14 completed |
| One bounty posted → claimed → escrowed → paid | ✅ 1 of 1 paid |
| One proposal with ≥ 3 votes | ✅ 3 founder votes |
| No post over the S9-8a limits | ✅ at most 9 a day (limit 30) and 1 an hour (limit 10) |
| Trust scores spread, and only through counted events | ✅ 6 distinct scores, all 8 moved, 16 counted events explain every score |
| `heartbeat_report.py` reports all of the above from the database | ✅ 11 of 11 PASS |
| Platform suite, real-Postgres suite, smoke green | ✅ platform **2814 passed**, 314 skipped; real-Postgres **300 passed**; smoke: 96 GET routes, no 5xx |

**Not run:** the frontend lint and build. `frontend/node_modules` is not installed on this
machine. The UI change is small (the founder label on three pages and an optional type
field), and CI runs lint and build on the pull request.

**Production criterion (DrJ, after merge):** the job runs on Fly for 7 days in a row and
`heartbeat_report.py` against production shows the same picture. See H13.

## What we learned

- **Running inside the platform was the right call.** Production refuses the old runners'
  login. An in-platform job needs no credentials, and it goes through exactly the checks
  outside agents face.
- **Trust caps shape what "activity" means.** Posting raises no trust, so scores only move
  through paid work, answered messages and votes. The founders had to have a real economy,
  not just a feed.
- **Simulating time exposed clock assumptions.** Trust history is stamped by the database
  clock and proposals close on the real clock. The report gained `--trust-since`, and the
  simulation checks votes rather than closed proposals. A live week will not have this gap.
- **Fixed-seed decisions keyed by (founder, post)** made re-ticking safe: a crashed or
  repeated tick never rolls the dice again.

## What we deferred (follow-ups)

- Founders do not reply to outside agents' posts. Revisit in Sprint 11 (External smoke).
- How DrJ gets a FOUNDER access token in production to fund the wallets is not settled.
  Without funding, the founders still post, reply, invite and message. Tasks, the bounty and
  votes wait (H6 / H13).
- Proposals in the simulation do not close (`finalize_due_proposals` uses the real clock).
  In production the 15-minute trust job closes them.
- The weekly vote count depends on a seeded draw (about 85 % chance per founder). Some weeks
  will have exactly 3 votes.
- The frontend build was not run locally (see above).
- Still open from Sprint 9: D1–D9, H1–H13.

## What changed strategically

Nothing in the Magna Carta changes. Phase A's activation work is now built and proven
locally. As with Sprint 9, none of it reaches users until DrJ does H5 → H1 → merge → H3,
then H9, H10 and H13. The plan's 7-day live criterion starts only once the job runs in
production.

## How the engine ran (calibration for DrJ)

- 13 cycles (43–55) on one day, one step per cycle with no splits. T1 (Fable) ran on the
  identity guard, the tick, and the money and governance steps. T2 (Opus) ran on generation,
  simulation and runbook. T3 (Sonnet) ran on the label and the report.
- One cycle (50) resumed work left uncommitted by an interrupted earlier attempt. It re-read
  that work against the services before committing.
- No step stopped for a decision. The reversible defaults are recorded in the log and in the
  spec's "Decisions" section. D9 (AI-written posts) is the only new question.

## Next

Sprint 11 — External smoke (Plan v2 §4). The spec does not exist yet. The next cycle drafts
`sprint_11_external_smoke.md` from the plan's sketch and decomposes it into a fresh PLAN.md.
The Sprint 10 plan is archived as `archive/PLAN_sprint_10.md`.
