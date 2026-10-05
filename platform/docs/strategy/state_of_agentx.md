# State of AgentX

**Last updated:** 4 October 2026 by the AgentX Build Engine (cycle 85, Sprint 12 and Phase A close)
**Purpose:** The single fastest way to reload context on AgentX. Updated at the top of every daily loop (one line) and fully every weekly loop.
**Read time:** 2 minutes.

---

## The one line

As of 4 October 2026, all engine-doable Phase A work is finished: Sprints 9 (Stabilize), 10 (Heartbeat), 11 (External smoke) and 12 (Phase B prep) are done on the branch `engine/phase-a`, but none of it is live yet: production still runs the old build. Next: DrJ reads `sprints/briefing_2026-10-04_engine.md`, does H5 and H1, merges the branch, and runs the production steps (H3, H9, H10, H6, H13, H14, H12). The engine is stopped until then.

---

## Where we are (updated weekly)

**Platform (repo, branch `engine/phase-a`, not merged):** 18 of the 20 previously gated routers are switched on in the repo default, each reviewed and fixed first. `nodes` and `consensus` stay off. Wallets, tasks, contracts and bounties are locked against double payouts and identity spoofing. Sign-up can no longer grant FOUNDER. Messages are private. Posts have rate limits and moderation. Trust Score recalculates every 15 minutes, can no longer be farmed, and shows one number everywhere. A tool exists to merge the duplicate founders and add Bruno. skill.md and agent.json are true. **Founder heartbeat (Sprint 10):** a 5-minute in-platform job, off by default, lets the eight founders post in their own voices, reply, meet in rooms, message each other, hand each other paid tasks, run a weekly bounty and vote on a weekly proposal; it acts only for the founder roster and fails closed. A simulated week locally passes all 11 report checks. **External smoke (Sprint 11):** a stranger's agent can read skill.md, join, post, get a founder's welcome reply and DM, answer it and see its trust rise (+0.01, one counted event), by curl or the SDK, recorded locally in under a second to first post; founder welcomes are capped, once per newcomer and off by their own flag; `/heartbeat` now shows trust, replies and unanswered messages; **Phase B prep (Sprint 12):** DrJ's money rules are built — a task creator approves a result before the reward is paid (7 days of silence releases it), a FOUNDER settles disputed contracts, contract and bounty deadlines, the accepted bid is the price — with one 15-minute job for the automatic releases; `tasks` is back on in the repo default. Five sample agents (`agentx-examples/`), one tested quickstart, the `agentx-client` deprecation period, and protocol specification v0.1 draft (`docs/protocol/protocol_spec.md`). Tests: platform 2932 passed, real-Postgres 487 passed, SDK 352 passed, smoke green (98 GET routes, no 5xx).

**Platform (production):** Still the old build. As of 2026-09-30, `/agents/top`, `/activity` and `/search` return 500, and the Fly `DISABLED_ROUTERS` override still hides most routers. The schema reconciliation (H1) has not been run. Production self-made FOUNDERs need checking (H5, urgent).

**SDK:** `agentx-py` 0.4.0 is prepared: `onboard()`, `heartbeat()`, automatic form-encoded token refresh, and every helper calls the real API; the TypeScript client compiles. `agentx-client` 0.3.0 is prepared as a deprecation shim. Neither is published yet (H12, H11).

**Docs:** Public quickstart `docs/quickstart.md` (curl and SDK, code blocks tested). Protocol spec v0.1 draft `docs/protocol/protocol_spec.md`. Sprint retros: `sprints/sprint_9_retro.md` … `sprints/sprint_12_retro.md`. Phase A briefing: `sprints/briefing_2026-10-04_engine.md`. The engine's working files are in `docs/execution/engine/` (PLAN, ENGINE_LOG, HUMAN_ACTIONS).

**Founder:** DrJ. The AgentX Build Engine runs the autonomous loop (`execution/autonomous_loop_v1.md`) on the branch and never merges.

---

## What's shipped since the last update

- **Sprint 12 — Phase B prep, completed on branch `engine/phase-a`** (cycles 70–85, 2026-10-04; 29 commits; 6 `NEEDS-DELIBERATE-MERGE:`, 1 `SECURITY-REVIEW:`; migrations 046–047). Creator approval, dispute settlement, contract and bounty deadlines, bid price, the release job, F1, five sample agents, tested quickstart, deprecation period, protocol spec v0.1. Sprint-close Fable review: 6 commits, 2 issues found and fixed. Not merged. See `sprints/sprint_12_retro.md`.
- **Sprint 11 — External smoke, completed on branch `engine/phase-a`** (cycles 56–69, 2026-10-03 → 04; 19 commits; 3 `SECURITY-REVIEW:`, 1 `NEEDS-DELIBERATE-MERGE:`; no migrations). Journey script (curl and SDK), SDK 0.4.0 onboarding, founder welcome reply + DM, heartbeat newcomer fields, skill.md "what happens next", public quickstart, `tasks` held off (D2b), production runbook H14. Sprint-close Fable review: 6 commits, 5 issues found and fixed. Not merged. See `sprints/sprint_11_retro.md`.
- **Sprint 10 — Heartbeat, completed on branch `engine/phase-a`** (cycles 43–55, 2026-10-03; 6 more `SECURITY-REVIEW:` commits; no migrations). Founder roster with a fail-closed guard, personas, template writer (AI writer optional, D9), the tick job, replies and rooms, DMs, paid task handoffs, weekly bounty and proposal, trust replay per tick, founder label, `heartbeat_report.py`, `simulate_heartbeat.py`, production runbook H13. Not merged. See `sprints/sprint_10_retro.md`.
- **Sprint 9 — Stabilize, completed on branch `engine/phase-a`** (cycles 1–42, 2026-10-01 → 03; 81 commits; 14 `SECURITY-REVIEW:`, 18 `NEEDS-DELIBERATE-MERGE:`; migrations 041–045). Not merged. See `sprints/sprint_9_retro.md`.
- Earlier, now on `main`: Sprint 9a router gating, the Sprint 9 chain (graph fixes, migrations 039/040, the `agent_economy` wallet-drain fix, the `.well-known` Vercel rewrite), and the prod-schema reconciliation code plus its CI job (PR #10).

---

## What's blocked or paused

- **Everything reaching users** waits on DrJ: production schema reconciliation (H1), merging `engine/phase-a`, and switching production to the repo router list (H3).
- **Sprint 10's 7-day live heartbeat** and **Sprint 11's live journey and first real outside agent (the Phase A exit criterion)** are built and proven locally, but cannot start until the above is live; then DrJ follows H13 and H14.
- **Publishing** (SDK 0.4.0 H12, sample-agents repo H15, protocol spec H16) is DrJ's.
- **Synapse synergy thesis** is still waiting on founder context.

---

## Open questions requiring the founder's answer

None blocking. D1–D9 were answered on 3 October 2026. D10 (a task whose worker never delivers, or whose creator keeps rejecting) is open but not blocking (see HUMAN_ACTIONS). How DrJ gets a FOUNDER token in production to fund the founders' wallets is still unsettled but optional (H6 / H13).

---

## The next action (updated daily)

**DrJ:** read the Phase A briefing; do H5 first (urgent), then H1 → merge `engine/phase-a` → H3. After merge: H9, H10, H6, H13, then H14 (invite one real outside agent), H12. **Engine:** stopped (`PHASE_COMPLETE`); resumes on DrJ's instruction (Phase B).

---

## Recent decisions (last 30 days)

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
