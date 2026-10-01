# Engine PLAN — Phase A, Sprint 9 (Stabilize), remainder

**Branch:** `engine/phase-a` · **Spec:** `platform/docs/sprints/sprint_9_stabilize.md`
**Decomposed:** 2026-10-01, cycle 1 (Opus, T2)

## Where Sprint 9 really stands (checked in code, not just docs)

Already on `main` (merged by DrJ):
- Sprint 9a router gating (`platform/src/router_config.py`, 20 routers disabled by default).
- Sprint 9 chain: graph typo fixes, migrations 039/040, `/health` commit, wallet-drain fix in
  `agent_economy` (SECURITY-REVIEW `73c6fe5`), `.well-known` Vercel rewrite (`2cfa87a`),
  memory investigation (verdict: stale gating, clean re-enable candidate).
- Prod schema reconciliation code + CI `migration-chain` job (PR #10, `84e64e1`, merged 2026-09-22).

Not yet done (this plan): the wallet-ownership gap in `routers/tokens.py`, `nodes`/`consensus`
dispositions, **router enablement (zero routers enabled so far)**, Trust Score schedule
(celery is not in `platform/requirements.txt`), founder dedupe + Bruno, PyPI naming,
SDK tests, LICENSE, README.

Unknown to the engine (no prod access): whether DrJ ran the 2026-09-21 reconciliation
runbook in production. Router enablement in the **repo** does not change production while
the Fly `DISABLED_ROUTERS` env var is set (it overrides the repo list), so repo-side work
can proceed; flipping production is a human action.

Baseline (cycle 1): platform suite **2033 passed, 14 skipped** locally.

## Steps

Legend: `[ ]` todo · `[x]` done · `[human]` DrJ-only · Tier per `autonomous_loop_v1.md`.

- [x] **S9-1 — Close the wallet holes in `routers/tokens.py` (routers `wallets`, `stakes`).**
  Done cycle 2, `feaa59f` (SECURITY-REVIEW). Self-service wallets start at 0; funding or acting
  for another agent is FOUNDER-only; transfer/stake use the JWT caller; tx labels allowlisted.
  Follow-up for S9-12: SDK `wallet.py` sends DIDs where the API expects agent UUIDs.
  Two gaps (found cycle 1): (a) `transfer_tokens` (`tokens.py:96`) and `stake_tokens`
  (`tokens.py:152`) authenticate but ignore the caller and trust `body.from_id` /
  `body.agent_id`, so any logged-in agent can move/stake anyone's tokens; (b) `POST /wallets`
  (`tokens.py:48`) and `POST /wallets/by-did` (`tokens.py:68`) have **no auth** and accept an
  `initial_balance`, so anyone can mint tokens. Fix: identity from JWT; initial balance only
  via an admin/system path (or forced to 0 for self-created wallets). Prerequisite for the
  money cohort. Tier **T1** (money/auth). Commit prefix `SECURITY-REVIEW:`.
  Check: new tests prove unauthenticated → 401, cross-identity (body names another agent) → 403,
  self-service wallet creation cannot mint, owner transfer/stake succeeds; full suite green.

- [x] **S9-2 — `nodes` disposition: hardened AND kept disabled.**
  Done cycle 3, `4f17ef2` (SECURITY-REVIEW). `POST /nodes/register` and `POST /nodes/events`
  are FOUNDER-only; peer URLs must be public https (checked at registration and before every
  outbound send). Stays off: no signed-event protocol, no Phase A need (revisit in Phase D).
  Goal: harden peer register / event injection (mandatory auth) if small; else keep disabled
  with a precise reason + follow-up note in `router_config.py`.
  Tier **T1** if hardening (auth), **T2** if keep-disabled decision only.
  Check: config/comment updated; if hardened, tests prove unauthenticated calls fail closed.

- [x] **S9-3 — `consensus` disposition: kept disabled, reason documented.**
  Done cycle 3, `4f17ef2`. Not wired: consensus is keyed on PROPOSAL *posts* and reads the
  baseline `votes` table nobody writes; `governance_votes` is keyed on `proposals` (different
  id space, vote values and weights). Also, any logged-in agent can open/advance any debate.
  Needs the O10 design decision (one proposal model) — not a stabilisation fix.
  Goal: either point tallies at `governance_votes` (small, if clean) or keep disabled with a
  documented reason. Never enable an empty router.
  Tier **T2**. Check: config comment updated; if wired, test shows non-empty tally locally.

- [x] **S9-4 — Local "all-routers" smoke harness.**
  Done cycle 4, `392c601`. Run from `platform/`:
  `.venv/bin/python scripts/smoke_routers.py [--enable a,b | --disabled csv] [--no-migrate]`.
  Green on the repo default (49 GET routes) and with **every** router on (96 routes, 0 × 5xx).
  GET-only: write endpoints still need per-cohort tests/review in S9-5..S9-8.
  Goal: a repeatable script (`platform/scripts/smoke_routers.py` or a pytest integration test)
  that migrates a scratch local DB to head, boots the app with a given disabled-list, and GETs
  every listed route, failing on any 5xx. Used as the acceptance check for S9-5..S9-8.
  Tier **T2**. Check: harness runs green on current default config.

- [ ] **S9-4a — Kill-switch safety: the env override must not switch unsafe routers ON.**
  Found cycle 3: `DISABLED_ROUTERS` (Fly env) *replaces* the repo list, so a short emergency
  value such as the one in `config.py`'s own example (`contracts,rooms,governance`) would turn
  ON every other gated router, including `agent_economy`, `nodes` and `consensus`.
  Goal: Tier A (`BROKEN_OR_INSECURE_ROUTERS`) stays disabled whatever the env var says
  (proposed, reversible: effective list = env list ∪ Tier A; startup log says so). Do this
  before S9-5 moves routers out of the default list.
  Tier **T1** (permissions surface). Check: test with `DISABLED_ROUTERS=posts` shows `nodes`,
  `consensus`, `agent_economy` still disabled; suite green.

- [ ] **S9-5 — Enable cohort 1 (social) in repo config:** `memory`, `graph`, `rooms`,
  `communities`, `conversations`, `channels`, `pulse`.
  Tier **T2**. Check: smoke harness green with these enabled; suite green; comments updated.

- [ ] **S9-6 — Enable cohort 2 (work):** `tasks`, `contracts`, `collectives`, `agentbus`,
  `verifications`, `markets`.
  Tier **T2**. Check: smoke harness green; quick auth review of write endpoints (no body-identity).

- [ ] **S9-7 — Enable cohort 3 (money):** `wallets`, `stakes`, `economy`, `agent_economy`.
  Depends on S9-1. Tier **T1**. Commit prefix `NEEDS-DELIBERATE-MERGE:`.
  Check: smoke harness green; ownership tests from S9-1 still green; a scan of every
  token-moving endpoint for body-supplied identity finds none.

- [ ] **S9-8 — Enable cohort 4 (governance):** `governance` only (`consensus` stays off, S9-3).
  Tier **T2**. Check: propose → vote → tally works locally; smoke green.

Added cycle 2 from DrJ's note (2026-10-01). Evidence from prod: an outside agent (driftice)
flooded the feed with 15 "probe" posts on 9 Sep; OrchardsGuide posted a referral scheme
(30% Bitcoin commission on follower purchases) on 22 Sep.

- [ ] **S9-8a — Per-agent post rate limits + sane max post length.**
  Today (`middleware/rate_limits.py:234`) top-level posts allow 10/min, 100/hr, 500/day per DID
  (trust-scaled), and `content_moderation.py` / `models/post.py` allow 10,000-char content.
  Goal: tighten to a feed-sane budget (proposed default, reversible: 2/min, 10/hr, 30/day for
  new/low-trust agents, trust-scaled upward; replies 6/min, 60/hr, 200/day), a duplicate-content
  guard (same author + same normalised content within 24 h → 409), and a max content length of
  2,000 chars (title 200). Confirm the limiter keys on the authenticated DID, not on a body field
  or IP alone, and that `RATE_LIMIT_MODE` defaults to `enforce`.
  Tier **T2** (anti-abuse, no money/auth change). Check: tests prove the 3rd post inside a
  minute → 429, 2,001-char content → 400/422, duplicate → 409; suite green.

- [ ] **S9-8b — Fix agent profile `posts_count` staying 0.**
  Cause found cycle 2: only `services/auto_post.py:147` increments `agents.posts_count`; the
  public `POST /posts` and reply paths in `routers/posts.py` never do. Goal: increment in the
  same transaction as the insert (top-level posts; decide and document whether replies count),
  decrement on delete if a delete path exists, plus an idempotent backfill script
  (`UPDATE agents SET posts_count = (SELECT count(*) …)`, dry-run by default).
  Tier **T2** (backfill touches data → commit prefix `NEEDS-DELIBERATE-MERGE:`).
  Check: test creates a post via the API → profile shows 1; backfill dry-run reports correct
  counts on a seeded local DB. Production backfill → `[human]`.

- [ ] **S9-8c — Simple moderation path for commercial / referral solicitations.**
  Goal: (1) agents can flag a post (`POST /posts/{id}/flag`, reason enum incl. `solicitation`,
  one flag per agent per post, authenticated DID only); (2) admin/system-only hide/unhide
  (`hidden_at`, `hidden_reason` columns via a new migration) — hidden posts drop out of
  feeds, lists, search and `/activity`; (3) auto-hold: posts matching a small solicitation
  pattern list (referral / commission / "buy followers" / crypto-payout phrasing) are hidden
  pending review, or auto-hidden after N distinct flags (default 3, reversible).
  Tier **T1** (permissions + migration). Commit prefix `NEEDS-DELIBERATE-MERGE:`.
  Check: tests prove non-admin hide → 403, unauthenticated flag → 401, hidden post absent from
  feed/list/search, OrchardsGuide-style text is held; migration upgrade/downgrade clean locally.

- [ ] **S9-9 — Trust Score on a schedule.**
  Goal: verify recalculation inputs are real (not always-null columns), add celery +
  celery-beat (15-minute recalc), wire the compose `worker`/`beat`. Tier **T2**.
  Note (cycle 1): two competing recalcs exist — `services/trust_score.py:188`
  (`agent_trust_breakdown` weighted sum) and `services/reputation.py:86` (replays
  `trust_events`). Event consumers only record `trust_events`, never recalc. Pick one as the
  scheduled job (likely `reputation.py`, since it consumes real activity events) and document why.
  Celery, xgboost, numpy are all missing from `platform/requirements.txt`; the compose `worker`
  is a stub that prints every 5 s.
  Check: locally, run the job once against seeded activity → scores show spread (not all 0.44);
  beat schedule registered; suite green.

- [ ] **S9-10 — Founder dedupe + Bruno (local only).**
  Goal: idempotent script that keeps one canonical row for each of the 8 founders
  (ATLAS, BRUNO, DARIA, GIA, MARCUS, NOVA, QUINN, THEA), repoints FKs, removes duplicates,
  creates Bruno if missing. Must coexist with migration 038's suffixed display names.
  Root cause (cycle 1): three seed sources disagree on DIDs — `platform/scripts/seed_agents.py`
  uses `atlas-001 … gia-008`; `runners/register_all.py` and `runners/start_all.sh` use
  `<name>-001`. Pick one canonical DID set and make every seed use it, so re-runs can't duplicate.
  Tier **T1** (data-affecting). Commit prefix `NEEDS-DELIBERATE-MERGE:`.
  Check: on a local DB loaded with duplicates, exactly 8 founders, no orphans; dry-run mode default.
  Production run → `[human]` (HUMAN_ACTIONS).

- [ ] **S9-11 — PyPI naming prep.**
  Goal: confirm which SDK source is canonical (in-repo `sdk/` is already `agentx-py` 0.2.2;
  a standalone `agentx-sdk` repo also exists; `platform/agentx_sdk` is deprecated). Prepare an
  `agentx-client` shim package that depends on `agentx-py` and warns. Tier **T2**.
  Check: `python -m build` succeeds for both locally; shim import emits DeprecationWarning.
  Publishing → `[human]`.

- [ ] **S9-12 — SDK tests.** Run `sdk/tests`, fix failures. Tier **T2**.
  Check: SDK suite green locally.

- [ ] **S9-13 — LICENSE + README.** Blocked on decision D1 in HUMAN_ACTIONS (licence scope for
  the platform repo). README pointing to the magna carta can proceed. Tier **T3**.
  Note: root `README.md` has a LICENSE badge that links to a missing file and says "MIT" (line ~317).
  Check: README renders; LICENSE present once D1 answered.

- [ ] **S9-14 — Sprint close.** Run the sprint acceptance criteria locally, write
  `sprint_9_retro.md` (engine run), update `state_of_agentx.md`. Tier **T2**.

- [human] **S9-H1 — Production reconciliation + router flip.** See HUMAN_ACTIONS H1–H3.
  Status 2026-09-30 (DrJ): H1 **not done**; prod still runs the old build and `/agents/top`,
  `/activity`, `/search` return 500.

- [human] **S9-H4 — Remove abusive posts in production.** See HUMAN_ACTIONS H4.

After Sprint 9 closes: draft `sprint_10_heartbeat.md` from Plan v2 §4 (open questions on LLM
provider and daily cost ceiling become DECISION_NEEDED unless a reversible default exists).
