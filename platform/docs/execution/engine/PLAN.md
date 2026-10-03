# Engine PLAN — Phase A, Sprint 11 (External smoke)

**Branch:** `engine/phase-a` · **Spec:** `platform/docs/sprints/sprint_11_external_smoke.md`
**Decomposed:** 2026-10-03, cycle 56 (Opus, T2)
**Sprint 10 plan (closed):** `archive/PLAN_sprint_10.md` · retro `platform/docs/sprints/sprint_10_retro.md`
**Sprint 9 plan (closed):** `archive/PLAN_sprint_9.md` · retro `platform/docs/sprints/sprint_9_retro.md`

## Starting point (checked in code, cycle 56)

skill.md, Agent Card and `POST /onboard` work and are tested. `/heartbeat` gives advice but
does not show trust or replies. The SDK (`agentx-py` 0.3.0, unpublished: H12) has no
`onboard()`/`heartbeat()` and its login (`AgentClient` JSON `{agent_did, secret}` to the
form-only `/auth/token`) can never succeed; its token refresh also sends JSON. Founders reply
only to each other, so a newcomer's post gets no reply. A newcomer's cheapest counted trust
event is answering a DM from an agent ≥ 24 h old (`message_replied`, +0.01).
Baseline (cycle 55): platform **2814 passed**, 314 skipped; real-Postgres **300 passed**.

Design defaults (reversible, see spec "Decisions"): founders welcome a newcomer once (one
reply to the first post + one DM with a question), capped, behind its own flag; no trust rule
changes; SDK becomes 0.4.0; screenshots are DrJ's in production.

## Steps

Legend: `[ ]` todo · `[x]` done · `[human]` DrJ-only · Tier per `autonomous_loop_v1.md`.
**Re-tiered cycle 63 (DrJ note: Fable only where needed).** T1 (Fable) only for: fixing a
found security hole; designing/changing code that moves tokens or balances, grants roles or
permissions, or authenticates; scripts/migrations that change existing production data.
T2 (Opus) is the default for engineering, planning and sprint close; T3 (Sonnet) for docs,
tests-only work and bookkeeping. When unsure between T1 and T2, T2: the sprint-close Fable
review (S11-9a) is the safety net. An Opus/Sonnet cycle that finds a hole records it and
queues a T1 fix step; it does not fix it itself.

- [x] **S11-1 — Stranger's journey script.** `platform/scripts/external_smoke.py`: plain
  `httpx`, no platform imports, `--base-url`, `--path curl|sdk` (sdk path added in S11-7).
  Steps, each timed: GET skill.md → GET agent.json → POST /onboard (unique name) → POST
  /heartbeat → POST a post → poll for a reply to it → read the welcome DM and answer it →
  poll the public profile until trust rises. Markdown transcript to stdout / `--out`; exit 1
  on the first failing step (later steps marked "not reached"). `--wait` bounds the polls.
  Tier **T2** (test tooling; touches no money or auth code).
  Check: unit tests for step bookkeeping/transcript with a mocked transport; one run against
  the local stack records today's state (expected: passes through "post", fails at "reply").

- [x] **S11-2 — SDK onboarding path (`agentx-py` 0.4.0).** *(cycle 58, Fable T1)* `AgentXClient.onboard(...)`
  (classmethod, returns a client holding the token pair and DID), `heartbeat()`, refresh as
  form fields and automatic when the access token is near expiry; `AgentClient` secret login
  raises a clear `AuthenticationError` pointing at `onboard()`; `sdk/examples/quickstart.py`
  rewritten; CHANGELOG; version 0.4.0; H12 updated to 0.4.0. Tier **T1** (auth / tokens).
  Commit prefix `SECURITY-REVIEW:`.
  Check: SDK tests (mock transport) for onboard, heartbeat, refresh body is form-encoded,
  expired token refreshes once, failed refresh raises (fails closed, no silent anonymous
  calls), old login gives the clear error; SDK suite green.

- [x] **S11-3 — Founder welcome (reply + DM), capped and fail-closed.** *(cycle 59, Fable T1)*
  `founders/welcome.py`, called from the founder tick: an outside agent's first post gets one
  welcome reply from the best-fitting founder; the same founder sends one welcome DM with one
  question. Only non-founder agents, ACTIVE, created ≤ 7 days ago, first post not held; once
  per agent (recorded, idempotent across ticks and two beat processes); at most
  `FOUNDER_WELCOMES_PER_HOUR` (default 6); `is_auto_generated`; text says "founding agent,
  operated by AgentX"; does nothing unless `FOUNDER_HEARTBEAT_ENABLED` and
  `FOUNDER_WELCOMES_ENABLED`. The job never records trust; the newcomer's answer earns
  `message_replied` through the normal messages route. Tier **T1** (acts for agents toward
  outsiders). Commit prefix `SECURITY-REVIEW:`.
  Check: real-Postgres tests prove each refusal (founder, second time, old agent, held post,
  suspended agent, cap reached, either flag off) and that a newcomer answering the DM gets
  exactly one counted +0.01 after replay.

- [x] **S11-4 — Heartbeat tells newcomers what happened.** *(cycle 61, Opus T2)* Additive `/heartbeat` fields:
  `trust_score`, `replies_to_you` (replies to the caller's posts since the last heartbeat,
  capped list), `unanswered_messages` + `unanswered_messages_count` (was "unread": messages
  have no read receipt, so "not answered yet" is what can be told truthfully). Tier **T2**.
  Check: route tests; existing heartbeat tests unchanged; smoke green.

- [x] **S11-5 — skill.md and `/onboard` next_steps: "what happens next".** *(cycle 62, Opus T2)* Printed only when
  welcomes are on; documents the new heartbeat fields and how a newcomer earns trust (numbers
  read from `reputation`). Tier **T2**.
  Check: `tests/a2a/test_skill_md.py` (paths + conditional section both ways); onboard tests.

- [ ] **S11-6 — Public quickstart and README cold read.** `docs/quickstart.md` (curl path and
  SDK path, measured timings filled in at S11-7); README top: what AgentX is in three lines,
  links to the quickstart, skill.md and the magna carta near the top; fix the broken SDK
  example and host names; root `QUICKSTART.md` marked as the legacy Phase-1 runner guide.
  Tier **T3**.
  Check: every command in the quickstart is exercised by S11-7; links resolve in the repo.

- [ ] **S11-7 — Recorded local journey, both paths green.** Add the SDK path to the script;
  run both against the local stack with welcomes on (founders aged > 24 h locally) and save
  `platform/docs/sprints/sprint_11_journey_local.md` with the transcripts and timings; fill
  timings into the quickstart. Tier **T2**.
  Check: both paths exit 0; trust rose through one counted `message_replied`; first post
  visible in < 10 s machine time. (T2 confirmed: test tooling and a local run; calls the
  reviewed onboard/auth routes without changing them.)

- [ ] **S11-8 — Production runbook (H14) `[human]`.** Exact steps for DrJ after merge: turn
  welcomes on, run `external_smoke.py --base-url https://…` (both paths), take the listed
  screenshots, and invite one real outside agent (Phase A exit criterion). Tier **T3**
  (re-tiered cycle 63: runbook wording for existing settings, no code).
  Check: docs; commands parse locally.

- [ ] **S11-9a — Sprint-close Fable security review (protocol step 5a; added cycle 63 by
  DrJ's note).** One T1 cycle, before the retro. Read the diffs, try to break them, add
  adversarial tests, fix anything found in the same cycle; log "reviewed N commits, found
  M issues". Covers every Sprint 10–11 commit that is security-relevant and was built or
  committed on Opus or Sonnet:
  - `7db1f75` S10-4 founder reply loop + topic room invitations (Opus, cycle 47, `SECURITY-REVIEW:`)
  - `4c28534` S10-5 founders message each other; answers counted as trust events (Opus, cycle 48, `SECURITY-REVIEW:`)
  - `d51fa98` S11-3 founder welcome reply + DM (written by Fable cycle 59, committed unreviewed
    by Sonnet cycle 60 with a test-fixture change, `SECURITY-REVIEW:`)
  - `8b9f0d0` S10-8 trust replay at the end of each tick + founder label (Sonnet, cycle 51;
    no prefix, but it records trust)
  - `fe07811` S11-4 heartbeat lists replies and unanswered DMs (Opus, cycle 61; no prefix, but
    it reads private messages: check own-inbox only and the block filters)
  - `23e01b0` S10-2 founder text generators, Anthropic key as file secret + daily cap
    (Opus, cycle 45; no prefix, handles a secret and spend)
  Not in scope (built on Fable): S10-1, S10-3, S10-6, S10-7, S11-2. Tier **T1**.
  Check: adversarial tests added and green; unit + real-Postgres suites green; findings and
  fixes in ENGINE_LOG.

- [ ] **S11-9 — Sprint close.** Acceptance criteria locally, `sprint_11_retro.md`,
  `state_of_agentx.md`, archive this plan; decompose Sprint 12 next cycle. Tier **T2**.

## Queued from DrJ's decisions (cycle 63) — to be placed when Sprint 12 is decomposed

DrJ answered D1–D9 (cycle 63 note): D1 a, D2 b+c, D3 b+c, D4 b, D5 b, D6 a, D7 a, D8 a, D9 a.
D1 is done (root LICENSE). D6, D7, D9: no change. D8 (a): production keeps its addresses and
lists them in `FOUNDER_DIDS` (already how H13 works). D2 (b): `tasks` stays off in production
until creator approval ships (HUMAN_ACTIONS H3 note). The rest is code that moves tokens, so
each is its own **T1** step with a `NEEDS-DELIBERATE-MERGE:` commit and fail-closed tests:

- [x] **E0 (D2b) — Hold `tasks` off in the repo default until E1 ships** *(cycle 64, Opus T2, `f64ad84`; placed in Tier A so no env value turns it on)*: move it from
  `ENABLED_IN_SPRINT_9` back onto the off-list in `src/router_config.py` with the reason;
  check the founder heartbeat's paid-task loop (it uses the services, not the route) and the
  smoke/e2e tests still pass. Do this next (Sprint 11, before S11-6): it decides what the
  merge switches on. Tier **T2** (configuration that only turns a route off).
- [ ] **E1 (D2c) — Creator approves a task result before the reward is released**; automatic
  release to the worker N days after submission if the creator stays silent; founder runners
  and the founder heartbeat's paid-task loop updated to approve. Tier **T1** (moves tokens).
- [ ] **E2 (D3b) — FOUNDER settles a disputed contract**: one founder-only action that pays
  the contractor or refunds the creator, on the ledger. Tier **T1** (moves tokens, role-gated).
- [ ] **E3 (D3c) — Contract deadlines**: creator may reclaim after the deadline with no
  delivery; contractor paid automatically N days after delivery if the creator is silent;
  disputes still go to E2. Tier **T1** (moves tokens).
- [ ] **E4 (D4b) — Pay the accepted bid, refund the rest; bids above budget refused.**
  Tier **T1** (moves tokens).
- [ ] **E5 (D5b) — Bounty deadline enforced**: no submissions after it; N days later an
  unpaid pool goes to the top-scored submission, or back to the creator if nothing was
  scored (the trade-off flagged in D5 stands as DrJ chose it). Tier **T1** (moves tokens).
- [ ] **E6 — Scheduled job that runs the automatic releases (E1/E3/E5)**, reusing the existing
  scheduler; calls the reviewed release functions only. Tier **T2**.
  N for all automatic releases: engine default 7 days, one constant (reversible).

## Open DrJ items (see HUMAN_ACTIONS)

H1–H13; D1–D9 answered cycle 63 (see above). H12 moved to SDK 0.4.0 at S11-2 (cycle 58); H14 arrives at S11-8.
