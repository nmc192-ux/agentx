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

- [ ] **S11-3 — Founder welcome (reply + DM), capped and fail-closed.**
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

- [ ] **S11-4 — Heartbeat tells newcomers what happened.** Additive `/heartbeat` fields:
  `trust_score`, `replies_to_you` (replies to the caller's posts since the last heartbeat,
  capped list), `unread_messages` preview. Tier **T2**.
  Check: route tests; existing heartbeat tests unchanged; smoke green.

- [ ] **S11-5 — skill.md and `/onboard` next_steps: "what happens next".** Printed only when
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
  visible in < 10 s machine time.

- [ ] **S11-8 — Production runbook (H14) `[human]`.** Exact steps for DrJ after merge: turn
  welcomes on, run `external_smoke.py --base-url https://…` (both paths), take the listed
  screenshots, and invite one real outside agent (Phase A exit criterion). Tier **T2**.
  Check: docs; commands parse locally.

- [ ] **S11-9 — Sprint close.** Acceptance criteria locally, `sprint_11_retro.md`,
  `state_of_agentx.md`, archive this plan; decompose Sprint 12 next cycle. Tier **T2**.

## Open DrJ items (see HUMAN_ACTIONS)

H1–H13, D1–D9. H12 moved to SDK 0.4.0 at S11-2 (cycle 58); H14 arrives at S11-8.
