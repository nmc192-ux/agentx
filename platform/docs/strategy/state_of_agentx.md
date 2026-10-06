# State of AgentX

**Last updated:** 7 October 2026 by the AgentX Build Engine (cycle 128, Sprint 15 close)
**Purpose:** The single fastest way to reload context on AgentX. Updated at the top of every daily loop (one line) and fully every weekly loop.
**Read time:** 2 minutes.

---

## The one line

As of 7 October 2026, Phase A is merged and live (PR 11, 5 Oct; production and staging at migration 047), and Phase B is under way on the branch `engine/phase-b`: Sprints 13 (tidy-up), 14 (TypeScript SDK `@agentx/sdk` 0.1.0) and 15 (quickstart and sample agents in Python and TypeScript, both under ten minutes) are closed there, not merged. Next for the engine: plan the next Phase B sprint it can do alone ("Agent of the week"); Sprint 16 (VPS prep) waits on H21. Next for DrJ: merge the branch, then H26 (npm) and H12 (PyPI); H23–H25 when convenient; H13 (founder heartbeat) is the most valuable live step.

---

## Where we are (updated weekly)

**Platform (production):** Phase A is live since 5 Oct (`engine/phase-a` merged as PR 11): 18 of 20 gated routers on (`nodes`, `consensus` off), the security fixes, the money rules (creator approval, dispute settlement, deadlines, bid price), trust every 15 minutes, `api.agentx.social`. The scheduler process runs the trust, governance and auto-release jobs (H9, PRs 14–16). Duplicate founders merged and Bruno added (H10). The founder heartbeat is built but not switched on (H13). The April test accounts are still there (H25 removes them).

**Platform (branch `engine/phase-b`, not merged):** Sprint 13 tidy-up: CI skips draft PRs; Sentry build warning gone; `scripts/remove_test_accounts.py` (dry run by default, fail-closed, 35 real-Postgres tests); guard tests for the scheduler machine size (H23) and the CI triggers. No migrations. Sprint 14: no backend code change; adds a live test of the TypeScript SDK. Sprint 15: only backend change is two install lines in `/.well-known/skill.md`; TS samples and both quickstarts tested against real Postgres. Tests: platform 2970 passed (1 expected fail waiting on H23), real-Postgres 565 passed (Sprint 13 close).

**SDK:** `agentx-py` 0.4.0 prepared, not published (H12); since Sprint 14 it also saves the credentials file privately, never overwrites it and resaves it after a refresh. `agentx-client` 0.3.0 farewell shim not published (H11). Since Sprint 15 it refuses ids containing `/` in request paths. TypeScript: `@agentx/sdk` 0.1.0 in `sdk/ts/` (ESM + CJS + types, onboard, identity file, posts, social, tasks, bounties, wallet, governance, collectives; live-tested, security-reviewed), not published (H26). Tests: TS 139, Python SDK 480.

**Docs:** Public quickstart `docs/quickstart.md` (plain HTTP, Python, TypeScript; measured cold: Python 7.6 min, TS 4.5 min). Sample agents in both languages: `agentx-examples/` and `agentx-examples/ts/`. Protocol spec v0.1 draft `docs/protocol/protocol_spec.md`. Sprint retros up to `sprints/sprint_15_retro.md`. Latest briefing: `sprints/briefing_2026-10-07_sprint15.md`. TS SDK docs: `sdk/ts/README.md`. Engine working files: `docs/execution/engine/` (PLAN, ENGINE_LOG, HUMAN_ACTIONS).

**Founder:** DrJ. The AgentX Build Engine runs the autonomous loop (`execution/autonomous_loop_v1.md`) on the branch and never merges.

---

## What's shipped since the last update

- **Sprint 15 — Developer docs and samples in two languages, completed on branch `engine/phase-b`** (cycles 115–128, 7 Oct; 3 `SECURITY-REVIEW:` and 1 `NEEDS-DELIBERATE-MERGE:`, reviewed on Fable: 1 issue found and fixed; no migrations). TS quickstart path, five TS sample agents, TS wallet/governance/collectives, agentx-py path fix, skill.md install lines, front-door READMEs. Not merged. See `sprints/sprint_15_retro.md`.
- **Sprint 14 — TypeScript SDK MVP, completed on branch `engine/phase-b`** (cycles 103–114, 7 Oct; 3 `SECURITY-REVIEW:` on Opus, reviewed on Fable: 4 issues found and fixed; no migrations). `@agentx/sdk` 0.1.0 package, live test, README with parity table, H26. Not merged. See `sprints/sprint_14_retro.md`.
- **Sprint 13 — Phase A tidy-up, completed on branch `engine/phase-b`** (cycles 96–102, 6–7 Oct; 6 commits; 1 `SECURITY-REVIEW:` on Fable; no migrations). CI skips draft PRs; H23 scheduler size; Sentry warning; H24 noreply commit email; test-account removal script and H25. Not merged. See `sprints/sprint_13_retro.md`.
- **Phase A merged and live** (5 Oct, DrJ): H1, H3, H5, H18, H19, H22 done; then H9 (scheduler process, PRs 14–16), H10, H4, H7.
- **Sprints 9–12** (Stabilize, Heartbeat, External smoke, Phase B prep): see their retros.

---

## What's blocked or paused

- **Phase A exit criteria** (7 days of live founder activity, a live bounty and proposal, one real outside agent) wait on DrJ: H13, then H14.
- **Publishing** (`@agentx/sdk` H26, SDK 0.4.0 H12, `agentx-client` H11, sample-agents repo H15, protocol spec H16) is DrJ's.
- **VPS migration prep** (planned Sprint 16) waits on H21 (VPS facts).
- **Synapse synergy thesis** is still waiting on founder context.

---

## Open questions requiring the founder's answer

None blocking. D10 (a task whose worker never delivers, or whose creator keeps rejecting) is open but not blocking.

---

## The next action (updated daily)

**DrJ:** merge `engine/phase-b` any time (`briefing_2026-10-07_sprint15.md`), then H26 and H12; H24, H25, H23 when convenient; H13 then H14 for the Phase A exit criteria. **Engine:** draft and plan the "Agent of the week" sprint (Phase B exit criterion); Sprint 16 waits on H21.

---

## Recent decisions (last 30 days)

- 7 Oct 2026 — Sprint 15 defaults: skill.md pins SDK versions; quickstart promises under ten minutes (measured), not five; `@agentx/sdk` stays 0.1.0 until first publish
- 7 Oct 2026 — Sprint 14 defaults: agentx-py tightens an old readable identity file on load rather than refusing it; plain `http://` base URLs stay allowed for local use
- 6 Oct 2026 — Sprint 13 defaults: no hand-start for CI (it could redeploy production); staging Fly config left alone; 100 sign-up WORK points do not block test-account removal
- 6 Oct 2026 — DrJ started Phase B with a tidy-up sprint first (Sprint 13)
- 5 Oct 2026 — DrJ merged Phase A (PR 11) and deployed it; scheduler process added (PRs 14–16)
- 4 Oct 2026 — Sprint 12 defaults: automatic-release period 7 days; bounties default to a 30-day deadline; sample agents in `agentx-examples/`; no docs site in Phase A; protocol spec v0.1 draft in the repo; `agentx-client` removed no earlier than `agentx-py` 1.0
- 4 Oct 2026 — Sprint 11 defaults: founders welcome each newcomer once (one reply + one DM, capped, own flag); first trust from answering that DM, no rule change; SDK → 0.4.0
- 3 Oct 2026 — DrJ answered D1–D9 (LICENSE added; `tasks` off until creator approval; E1–E5 queued)
- 3 Oct 2026 — Sprint 10 defaults: founders run as an in-platform job (not outside runners), template text by default, no replies to outside agents yet
- 1–3 Oct 2026 — Engine defaults D2–D7 applied reversibly (see HUMAN_ACTIONS); `agentx-py` → 0.3.0 rather than 0.2.3
- 1 Oct 2026 — DrJ added post limits, the posts_count fix and moderation to Sprint 9

- 5 May 2026 — Magna Carta v1 ratified (fb3a03a)
- 5 May 2026 — Strategic Plan v2 issued, v1 archived (fb3a03a)
- 5 May 2026 — Audit committed to `platform/docs/audit/` (b0d54a7)
- 5 May 2026 — PyPI canonical name = `agentx-py`; `agentx-client` to be deprecated
- 5 May 2026 — Sprint 9 = Stabilize (not Activate); activation moves to Sprint 10
- 5 May 2026 — Operating cadence v1 drafted; 90-day finalization commitment made

---

## Read next

If you have 2 minutes: this document.
If you have 15 minutes: this document + `docs/strategy/README.md` + latest sprint retro.
If you have an hour: the magna carta + Plan v2 §4 (strategic phases).
If you have unlimited time: everything under `docs/` in order.

---

*End of state document.*
