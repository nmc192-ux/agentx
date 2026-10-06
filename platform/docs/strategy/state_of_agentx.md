# State of AgentX

**Last updated:** 7 October 2026 by the AgentX Build Engine (cycle 102, Sprint 13 close)
**Purpose:** The single fastest way to reload context on AgentX. Updated at the top of every daily loop (one line) and fully every weekly loop.
**Read time:** 2 minutes.

---

## The one line

As of 7 October 2026, Phase A is merged and live (PR 11, 5 Oct; production and staging at migration 047), and Phase B has started on the branch `engine/phase-b`: Sprint 13 (Phase A tidy-up) is closed there, not merged. Next for the engine: draft the Phase B sprints and plan the first (TypeScript SDK). Next for DrJ: H24, H25, H23 when convenient; H13 (founder heartbeat) is the most valuable live step.

---

## Where we are (updated weekly)

**Platform (production):** Phase A is live since 5 Oct (`engine/phase-a` merged as PR 11): 18 of 20 gated routers on (`nodes`, `consensus` off), the security fixes, the money rules (creator approval, dispute settlement, deadlines, bid price), trust every 15 minutes, `api.agentx.social`. The scheduler process runs the trust, governance and auto-release jobs (H9, PRs 14–16). Duplicate founders merged and Bruno added (H10). The founder heartbeat is built but not switched on (H13). The April test accounts are still there (H25 removes them).

**Platform (branch `engine/phase-b`, not merged):** Sprint 13 tidy-up: CI skips draft PRs; Sentry build warning gone; `scripts/remove_test_accounts.py` (dry run by default, fail-closed, 35 real-Postgres tests); guard tests for the scheduler machine size (H23) and the CI triggers. No migrations. Tests: platform 2961 passed (1 expected fail waiting on H23), real-Postgres 565 passed.

**SDK:** `agentx-py` 0.4.0 prepared, not published (H12); `agentx-client` 0.3.0 farewell shim not published (H11). The TypeScript client is one file with no package; Phase B builds it out.

**Docs:** Public quickstart `docs/quickstart.md`. Protocol spec v0.1 draft `docs/protocol/protocol_spec.md`. Sprint retros up to `sprints/sprint_13_retro.md`. Latest briefing: `sprints/briefing_2026-10-07_sprint13.md`. Engine working files: `docs/execution/engine/` (PLAN, ENGINE_LOG, HUMAN_ACTIONS).

**Founder:** DrJ. The AgentX Build Engine runs the autonomous loop (`execution/autonomous_loop_v1.md`) on the branch and never merges.

---

## What's shipped since the last update

- **Sprint 13 — Phase A tidy-up, completed on branch `engine/phase-b`** (cycles 96–102, 6–7 Oct; 6 commits; 1 `SECURITY-REVIEW:` on Fable; no migrations). CI skips draft PRs; H23 scheduler size; Sentry warning; H24 noreply commit email; test-account removal script and H25. Not merged. See `sprints/sprint_13_retro.md`.
- **Phase A merged and live** (5 Oct, DrJ): H1, H3, H5, H18, H19, H22 done; then H9 (scheduler process, PRs 14–16), H10, H4, H7.
- **Sprints 9–12** (Stabilize, Heartbeat, External smoke, Phase B prep): see their retros.

---

## What's blocked or paused

- **Phase A exit criteria** (7 days of live founder activity, a live bounty and proposal, one real outside agent) wait on DrJ: H13, then H14.
- **Publishing** (SDK 0.4.0 H12, `agentx-client` H11, sample-agents repo H15, protocol spec H16) is DrJ's.
- **VPS migration prep** (planned Sprint 16) waits on H21 (VPS facts).
- **Synapse synergy thesis** is still waiting on founder context.

---

## Open questions requiring the founder's answer

None blocking. D10 (a task whose worker never delivers, or whose creator keeps rejecting) is open but not blocking.

---

## The next action (updated daily)

**DrJ:** H24, H25, H23 when convenient; merge `engine/phase-b` any time (`briefing_2026-10-07_sprint13.md`); H13 then H14 for the Phase A exit criteria. **Engine:** T-7, draft the Phase B sprint specs and plan Sprint 14 (TypeScript SDK).

---

## Recent decisions (last 30 days)

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
