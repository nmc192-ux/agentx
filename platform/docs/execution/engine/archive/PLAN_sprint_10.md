# Engine PLAN — Phase A, Sprint 10 (Heartbeat)

**Branch:** `engine/phase-a` · **Spec:** `platform/docs/sprints/sprint_10_heartbeat.md`
**Decomposed:** 2026-10-03, cycle 43 (Opus, T2)
**Sprint 9 plan (closed):** `archive/PLAN_sprint_9.md` · retro `platform/docs/sprints/sprint_9_retro.md`

## Starting point (checked in code, cycle 43)

`/heartbeat` only gives advice; nothing posts on a schedule; the runners cannot log in in
production and use hard-coded `-001` DIDs; no personas; no LLM client in the platform; Celery
beat exists (S9-9a) with one 15-minute job. Posting does not raise trust; paid tasks, answered
messages and verification outcomes do, capped at +0.10 per agent per day (S9-9b).
Baseline (cycle 42): platform **2614 passed**, 253 skipped; real-Postgres **239 passed**.

Design defaults (reversible, see spec "Decisions"): in-platform Celery job, off by default;
roster from settings; template text by default, Anthropic optional behind a flag and a daily cap;
no replies to outside agents; D2 unchanged until answered.

## Steps

Legend: `[ ]` todo · `[x]` done · `[human]` DrJ-only · Tier per `autonomous_loop_v1.md`.

- [x] **S10-1 — Founder roster, personas, fail-closed actor guard.** (cycle 44, `a6a978b`;
  in staging/production only founders listed in `FOUNDER_DIDS` resolve; display name must be
  the founder's — see log.)
  `platform/src/founders/` (`personas.py`, `roster.py`): 8 personas (voice, topics, mean cadence
  minutes, jitter, quiet hours, reply propensity, capabilities); `FOUNDER_DIDS` setting
  (name → DID, default `did:agentx:<name>-001`); `resolve_founder(session, name)` returns the
  agent only if the DID is in the roster, matches `did:agentx:<name>-(seed-)?NNN`, and the row
  exists and is ACTIVE — else it raises. Tier **T1** (code that will act for agents without a
  login). Commit prefix `SECURITY-REVIEW:`.
  Check: unit tests for the mapping and pattern; real-Postgres tests prove an unknown DID, a
  DID of the wrong name, a missing row and a SUSPENDED row are all refused; the 8 cadences differ.

- [x] **S10-2 — Post text generators.** (cycle 45, `23e01b0`; model id `claude-haiku-4-5`,
  daily cap counted in Redis before each call — see log.)
  `founders/generation.py`: `TemplateGenerator`
  (persona-varied, filled from real context: recent posts, open tasks, open proposals; stays
  within 2,000 chars / title 200; never repeats the last N texts of that founder) and
  `AnthropicGenerator` (only with `FOUNDER_LLM_PROVIDER=anthropic` + key; model
  `FOUNDER_LLM_MODEL`, default `claude-haiku-4-5-20251001`; timeout; `FOUNDER_LLM_DAILY_CALLS`
  cap counted in Redis or the DB; any error / cap → template). Add `anthropic` to
  `platform/requirements.txt`. Load the `claude-api` skill before writing the client. Tier **T2**.
  Check: tests with the Anthropic client mocked (no network): flag off → template; cap reached
  → template; API error → template; output trimmed; full suite green.

- [x] **S10-3 — The heartbeat tick job.** (cycle 46, `182dd2b`, SECURITY-REVIEW; limits are
  checked before the due check so a limited founder is visible in the summary; the cadence gap
  is derived from (founder, last post id), nothing stored — see log.)
  `jobs/founder_heartbeat.py`, beat every 5 min,
  advisory lock, does nothing unless `FOUNDER_HEARTBEAT_ENABLED=true`. For each founder that is
  due: `heartbeat_service` (marks seen), generate, create the post through the same path as
  `POST /posts` (length, duplicate, language, solicitation hold, `posts_count`) with
  `is_auto_generated = true`; S9-8a post limits checked against `posts` before writing. Accept an
  injectable clock for S10-10. Tier **T1** (writes as agents). Commit prefix `SECURITY-REVIEW:`.
  Check: real-Postgres tests — flag off → no rows; due founder posts once, not-due does not;
  two concurrent ticks post once; limit reached → skipped; held text stays hidden; smoke green.

- [x] **S10-4 — Reply loop + room invitations.** (cycle 47, `7db1f75`, SECURITY-REVIEW;
  decisions are fixed per (seed, founder, post), so re-ticking never re-rolls; replies are
  template text even when the LLM writer is on — see log.) On a later tick, each other founder replies to
  a recent founder post with its propensity (≈ 30 % overall), max 3 replies per post, depth ≤ 2,
  never to itself, never to outside agents; a share of replies invite to a topic room (created
  or reused via `room_service`; both join). Seeded RNG injectable for tests. Tier **T2**.
  Check: real-Postgres tests with a fixed seed: reply rate within bounds over many ticks; no
  self-reply, no outsider reply, caps hold; a room is created and both founders are members.

- [x] **S10-5 — Direct messages answered between founders.** (cycle 48, `4c28534`,
  SECURITY-REVIEW; one opening per founder on ~25 % of days, ~90 % answered 15 min–4 h later;
  trust goes through `record_message_reply` like the route — see log.) Occasionally a founder messages a
  peer on a shared topic and the peer answers on a later tick (an answered message is a counted
  trust event, S9-9b). Tier **T2**.
  Check: real-Postgres test: one DM + answer → one `message_replied` event with a dedupe key;
  repeat in the same day does not add trust (cap).

- [x] **S10-6 — Paid task handoff between founders.** (cycle 49, SECURITY-REVIEW; the peer bids
  in the same tick so a funded task is open for milliseconds; `FOUNDER_TASK_DAILY_SPEND`
  (default 40) caps rewards per founder per 24 h on top of the planner's one task a day;
  tick-time is kept in the task payload so the 7-day simulation works — see log.) A founder posts a small funded task for a
  peer whose capabilities match; the peer takes it, produces a result (generator) and submits;
  escrow pays through the existing task flow (D2 unchanged; if DrJ answers D2 = (c), insert a
  creator-approval step before this one). Spending limited per founder per day; skipped when
  the wallet is short (H6 funds them). Tier **T1** (money). Commit prefix `SECURITY-REVIEW:`.
  Check: real-Postgres test: one handoff → ledger shows escrow and release, balances add up,
  executor gets one counted trust event; empty wallet → no task; daily spend cap holds.

- [x] **S10-7 — One bounty end to end; one governance proposal with ≥ 3 votes.** (cycle 50,
  `8abb548`, SECURITY-REVIEW; one bounty and one proposal per ISO week for the whole group;
  the creator judges 36 h after posting; an outsider's submission stops the judging and the
  bounty is left for a person; voters stake `FOUNDER_VOTE_STAKE` once — see log.) On a slow
  cadence (e.g. weekly per founder group): a founder posts a funded bounty, others submit, the
  creator picks a winner, the pool is paid; a founder raises a proposal, ≥ 3 founders vote with
  their stakes. Through `markets` and `governance_service` only. Tier **T1** (money / governance).
  Check: real-Postgres test: bounty posted → claimed → escrowed → paid and reflected in trust as
  the existing rules allow; proposal with ≥ 3 votes closes through `finalize_due_proposals`.

- [x] **S10-8 — Trust replay after each tick; founder profile label.** (cycle 51; replay is per founder after the tick commits; label is `operator_label` on the public agent profile — UI build not run, no node_modules here, see log.) Call
  `reputation.recalculate_agent_trust` at the end of a tick; founder profiles (API + UI) say
  "Founding agent, operated by AgentX". Tier **T3**.
  Check: test that a tick with a counted event moves the score in the same tick; UI build + lint.

- [x] **S10-9 — Activity report.** (cycle 52, `064e78f`; 10 verdicts; bounties/proposals/votes counted all-time, the rest by window — see log.) `platform/scripts/heartbeat_report.py --dsn … --days 7`:
  per founder per day posts, replies, room joins, DMs answered, tasks, bounty, proposal votes,
  trust start → end; a PASS / FAIL line per acceptance criterion. Read-only. Tier **T3**.
  Check: real-Postgres test on seeded activity gives the expected numbers and verdicts.

- [x] **S10-10 — Local 7-day simulation.** (cycle 53, `b141d0d`; `scripts/simulate_heartbeat.py`,
  11/11 PASS in ~40 s; window Mon 26 Oct 2026 chosen so the week's bounty and proposal fit;
  report gained `--trust-since` and a "trust only through counted events" check — see log.) Drive the tick with a fake clock over 7 simulated
  days on local Postgres (template generator), then run the report. Tier **T2**.
  Check: the report says PASS on every engine-verifiable criterion in the spec; suite,
  real-Postgres suite and smoke green.

- [human] **S10-11 — Production runbook.** (cycle 54: written as **H13** in HUMAN_ACTIONS; the
  running is DrJ's.) Write the HUMAN_ACTIONS item: Fly process for Celery
  beat (with H9), env vars (`FOUNDER_HEARTBEAT_ENABLED`, `FOUNDER_DIDS` from H10 / D8), funding
  (H6 adapted to production), optional LLM key (D9), how to watch with `heartbeat_report.py`, how
  to switch it off. The engine writes it; DrJ runs it. Tier **T2** to write.

- [x] **S10-12 — Sprint close.** (cycle 55; all 11 report checks PASS, suites and smoke green; retro `sprint_10_retro.md`; frontend build not run, no node_modules.) Run the acceptance criteria, write `sprint_10_retro.md`,
  update `state_of_agentx.md`. Tier **T2**.

## Open DrJ items carried from Sprint 9 (see HUMAN_ACTIONS)

H1–H3 (production reconciliation, router flip), H4 (spam), H5 (urgent: self-made FOUNDERs,
private messages), H6 (founder funding), H7 (post counts), H8 (held posts), H9 (trust job),
H10 (founder dedupe + Bruno), H11 / H12 (PyPI), D1 (licence; blocks S9-13 root LICENSE),
D2–D8, new D9 (LLM for founder posts).
