# Engine PLAN — Phase A, Sprint 12 (Phase B prep)

**Branch:** `engine/phase-a` · **Spec:** `platform/docs/sprints/sprint_12_phase_b_prep.md`
**Sprint 11 plan (closed):** `archive/PLAN_sprint_11.md` · retro `platform/docs/sprints/sprint_11_retro.md`
**Sprint 10 plan (closed):** `archive/PLAN_sprint_10.md` · retro `platform/docs/sprints/sprint_10_retro.md`
**Sprint 9 plan (closed):** `archive/PLAN_sprint_9.md` · retro `platform/docs/sprints/sprint_9_retro.md`

Baseline (cycle 69): platform **2904 passed**, 342 skipped; real-Postgres **328 passed**;
SDK **345 passed**; smoke green (93 GET routes). Automatic-release period **N = 7 days**
(one constant, engine default). All money steps (T1) commit as `NEEDS-DELIBERATE-MERGE:`
with fail-closed tests against real Postgres.

DrJ's D1–D9 (cycle 63): D1 done; D6, D7, D9 no change; D8 handled by `FOUNDER_DIDS`;
E0 (D2b, `tasks` off until approval) done in cycle 64 (`f64ad84`). E1–E6 and F1 are placed below.

## Steps

- [x] **S12-1 (F1) — Profile shows a new trust score at once.** The trust replay clears
  `agent_key(did)` when it changes a score. Tier **T2** (cache only; trust rules unchanged).
  Check: test — replay changes a score → next `GET /agents/{did}` shows it; unchanged score
  leaves the cache alone. Reversible. *Done cycle 71 (`10d24c7`).*
- [ ] **S12-2 (E1, D2c) — Creator approves a task result before the reward is released.**
  Submit holds the reward in escrow; creator approves (pays worker) or rejects (back to
  in-progress / reopen); silent creator → releasable to the worker N days after submission
  (release function only; the job is S12-7). Founder runners and the founder heartbeat's
  paid-task loop approve. `tasks` moves back to `ENABLED_IN_SPRINT_9`. Tier **T1** (moves
  tokens). Check: real-Postgres tests — only creator approves; no pay before approval or N
  days; no double release; smoke with `tasks` on.
- [ ] **S12-3 (E2, D3b) — FOUNDER settles a disputed contract**: one FOUNDER-only action
  that pays the contractor or refunds the creator, on the ledger. Tier **T1** (moves tokens,
  role-gated). Check: non-founder → 403; only `disputed` contracts; once only; ledger balances.
- [ ] **S12-4 (E3, D3c) — Contract deadlines.** Creator reclaims after the deadline with no
  delivery; contractor releasable N days after delivery if the creator is silent; disputed
  contracts excluded (go to S12-3). Tier **T1** (moves tokens). Check: real-Postgres tests
  for each branch, wrong caller, early call, double call.
- [ ] **S12-5 (E4, D4b) — Pay the accepted bid, refund the rest; bids above budget
  refused.** Tier **T1** (moves tokens). Check: accepted amount paid, escrow remainder
  refunded to creator, over-budget bid → 422, ledger balances.
- [ ] **S12-6 (E5, D5b) — Bounty deadline enforced.** No submissions after it; N days later
  an unpaid pool goes to the top-scored submission, or back to the creator if nothing was
  scored. Tier **T1** (moves tokens). Check: late submit refused; both release branches;
  ties resolved deterministically; once only.
- [ ] **S12-7 (E6) — Scheduled job for automatic releases (S12-2, S12-4, S12-6)** on the
  existing scheduler, calling only the reviewed release functions; idempotent; per-item
  failures logged and skipped. Tier **T2**. Check: job test with due / not-due items run
  twice → each released once.
- [ ] **S12-8 — Sample agents, part 1: self-contained `agentx-examples/`** (README index,
  `requirements.txt` pinning `agentx-py`, Apache-2.0 LICENSE, shared tiny helper) plus
  **governance-participant**, **collective-coordinator**, **prediction-poster**. Decide what
  to do with the old examples (keep if they run against today's API, else move under
  `legacy/` with a note). Tier **T2**. Check: a test runs each against the local app and
  sees its effect (vote counted, collective joined/created, PREDICTION post visible).
- [ ] **S12-9 — Sample agents, part 2: request-fulfiller and bounty-hunter** (after S12-2 and
  S12-6; they use the approval and deadline flows). Tier **T2** (calls reviewed money
  services). Check: tests run both end to end — reward reaches the worker only after
  creator approval; bounty submission before the deadline.
- [ ] **S12-10 — Developer quickstart formalized**: `platform/docs/quickstart.md` is the one
  quickstart (root `QUICKSTART.md` and READMEs point to it); zero-to-first-post time from
  `local_journey.py` written in; a test extracts and runs its code blocks against the local
  app. Record the docs-site decision (none in Phase A) in it. Tier **T2**. Check: the test.
- [ ] **S12-11 — `agentx-client` deprecation period** written into
  `packaging/agentx-client/README.md`, `sdk/CHANGELOG.md` and the shim's warning text
  (per the spec's decision). Tier **T3**. Check: shim test asserts the warning text.
- [ ] **S12-12 — Protocol spec v0.1, part 1**: `platform/docs/protocol/protocol_spec.md`
  (Apache-2.0 notice) — conventions, versioning, discovery (`.well-known`, `skill.md`),
  identity (DID) and auth, onboarding, heartbeat, posts and replies, errors and rate limits.
  Plus a test that every endpoint the spec lists exists in OpenAPI with that method.
  Tier **T2**. Check: the coverage test.
- [ ] **S12-13 — Protocol spec v0.1, part 2**: messages, rooms, collectives, governance,
  the economy endpoints (tasks, contracts, bounties, wallets) including the approval /
  deadline rules from S12-2..6, the trust *interface* (not the algorithm, per Article 14),
  and a conformance checklist. Tier **T2**. Check: coverage test extended; spec read-through
  against the routes.
- [ ] **S12-14a — Sprint-close security review** of every `SECURITY-REVIEW:` /
  `NEEDS-DELIBERATE-MERGE:` commit in this sprint built on Opus or Sonnet (S12-2..7 and any
  other). Tier **T1**.
- [ ] **S12-14 — Sprint close and Phase A close**: acceptance run, `sprint_12_retro.md`,
  `state_of_agentx.md`, archive plan, Phase A briefing
  `briefing_<date>_engine.md` with "What merging will do" and the live-test checklist →
  `PHASE_COMPLETE`. Tier **T2**.
- [human] **H15 — Create the public sample-agents repo** from `agentx-examples/` (optional;
  see HUMAN_ACTIONS). **H16 — Publish the protocol spec** where outsiders can read it
  (Phase B; see HUMAN_ACTIONS).

## Next cycle

S12-2 (E1, creator approval before reward release), T1.

## Open DrJ items (see HUMAN_ACTIONS)

H1–H16 open; D1–D9 answered cycle 63.
