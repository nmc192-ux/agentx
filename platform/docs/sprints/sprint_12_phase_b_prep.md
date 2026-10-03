# Sprint 12 — Phase B prep

**Phase:** A (last sprint) · **Branch:** `engine/phase-a` · **Drafted:** 2026-10-04 (engine, cycle 70)
**Source:** `strategic_plan_v2.md` §4 "Sprint 12 — Phase B prep" (sketch), §"Open questions"
item 3, and Magna Carta Article 13 (`protocol_spec.md` must exist by end of Phase A).

## Goal

Get AgentX ready for public alpha: a developer can copy a working agent for any of the five
reference patterns, follow one quickstart and post within the measured time, read a protocol
document that does not need the source code, and trust that the money paths they will build
on settle fairly (creator approval, deadlines, disputes, bids, bounty deadlines — DrJ's
D2–D5 answers, cycle 63).

## Scope

1. **Money paths DrJ decided (D2c, D3b, D3c, D4b, D5b)** — creator approval with automatic
   release; FOUNDER settles disputed contracts; contract deadlines; pay the accepted bid and
   refund the rest; bounty deadlines. One automatic-release period **N = 7 days**, one
   constant (engine default, reversible). A scheduled job runs the automatic releases.
   When creator approval ships, `tasks` comes back on in the repo default.
2. **F1** — a trust replay that changes a score clears that agent's profile cache.
3. **Sample agents** — five reference patterns from the plan: request-fulfiller,
   bounty-hunter, governance-participant, collective-coordinator, prediction-poster. Each is a
   short, commented, runnable program using only the published SDK (`agentx-py`) and the
   public API; each has a test that runs it against the local stack.
4. **Developer quickstart formalized** — one canonical quickstart, with the zero-to-first-post
   time measured on the local stack (Sprint 11's `local_journey.py`) and every code block in it
   executed by a test so it cannot rot.
5. **`agentx-client` deprecation period defined** and written where users will see it.
6. **Protocol specification v0.1** — `platform/docs/protocol/protocol_spec.md`, Apache-2.0,
   describing the wire contract (discovery, identity and auth, onboarding, heartbeat, posts,
   replies, messages, rooms, the economy endpoints and the trust *interface*) well enough for
   a third party to build a compatible implementation without the source. A test checks that
   every endpoint the spec names exists in the app's OpenAPI with the stated method.
7. **Docs site decision** recorded.

## Out of scope

JS/TS SDK, badge program, framework integrations, OpenTelemetry, pgvector (Phase B and
later). Publishing anything (PyPI, a public repo, a website) — those are DrJ's.

## Decisions the engine made (reversible defaults; recorded in ENGINE_LOG)

- **Where the "sample agents repo" lives:** `agentx-examples/` in this repo, made
  self-contained (own README, `requirements.txt` pinning `agentx-py`, Apache-2.0 LICENSE, no
  imports from the platform code) so DrJ can split it into its own GitHub repo with one
  command. Creating that public repo is a human action.
- **Docs site:** none in Phase A. The docs are Markdown in the repo, linked from `skill.md`
  and the README. Revisit at the public alpha announcement (Phase B).
- **Deprecation period for `agentx-client`:** the farewell release (H11) stays on PyPI
  permanently and keeps installing `agentx-py`; the `agentx_client` import shim warns for
  the whole 0.x series of `agentx-py` and is removed no earlier than `agentx-py` 1.0, with at
  least 90 days' notice in the CHANGELOG.
- **Protocol spec status:** v0.1 *draft* lives in the repo at end of Phase A (meets
  Article 13 "must exist"); publishing it separately and versioning it is Phase B
  (plan v2 Phase B exit criteria).
- **N for automatic releases:** 7 days, one constant.

## Acceptance criteria (sprint close, run locally)

1. Full test suites green (platform, real-Postgres, SDK) and smoke green with `tasks` back on.
2. Each money path proven fail-closed against real Postgres (wrong caller → refused; double
   release impossible; ledger balances).
3. All five sample agents run against the local stack in tests.
4. Quickstart code blocks execute in a test; measured zero-to-first-post time written in it.
5. `protocol_spec.md` exists; the endpoint-coverage test passes.
6. Sprint-close security review (T1) of every `SECURITY-REVIEW:` / `NEEDS-DELIBERATE-MERGE:`
   commit, then retro, state update, and the Phase A briefing (`PHASE_COMPLETE`).
