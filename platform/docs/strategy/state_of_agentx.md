# State of AgentX

**Last updated:** 3 October 2026 by the AgentX Build Engine (cycle 42, Sprint 9 close)
**Purpose:** The single fastest way to reload context on AgentX. Updated at the top of every daily loop (one line) and fully every weekly loop.
**Read time:** 2 minutes.

---

## The one line

As of 3 October 2026, Sprint 9 (Stabilize) is finished on the branch `engine/phase-a`, but none of it is live yet: production still runs the old build. Next: DrJ reviews and merges the branch and runs the production steps (H1–H3). The engine is drafting Sprint 10 (Heartbeat) meanwhile.

---

## Where we are (updated weekly)

**Platform (repo, branch `engine/phase-a`, not merged):** 18 of the 20 previously gated routers are switched on in the repo default, each reviewed and fixed first. `nodes` and `consensus` stay off. Wallets, tasks, contracts and bounties are locked against double payouts and identity spoofing. Sign-up can no longer grant FOUNDER. Messages are private. Posts have rate limits and moderation. Trust Score recalculates every 15 minutes, can no longer be farmed, and shows one number everywhere. A tool exists to merge the duplicate founders and add Bruno. skill.md and agent.json are true. Tests: platform 2614 passed, real-Postgres 239 passed, SDK 319 passed, smoke green with every router on.

**Platform (production):** Still the old build. As of 2026-09-30, `/agents/top`, `/activity` and `/search` return 500, and the Fly `DISABLED_ROUTERS` override still hides most routers. The schema reconciliation (H1) has not been run. Production self-made FOUNDERs need checking (H5, urgent).

**SDK:** `agentx-py` 0.3.0 is prepared: every helper calls the real API, and the TypeScript client compiles. `agentx-client` 0.3.0 is prepared as a deprecation shim. Neither is published yet (H12, H11).

**Docs:** Sprint 9 retro: `sprints/sprint_9_retro.md`. The engine's working files are in `docs/execution/engine/` (PLAN, ENGINE_LOG, HUMAN_ACTIONS).

**Founder:** DrJ. The AgentX Build Engine runs the autonomous loop (`execution/autonomous_loop_v1.md`) on the branch and never merges.

---

## What's shipped since the last update

- **Sprint 9 — Stabilize, completed on branch `engine/phase-a`** (cycles 1–42, 2026-10-01 → 03; 81 commits; 14 `SECURITY-REVIEW:`, 18 `NEEDS-DELIBERATE-MERGE:`; migrations 041–045). Not merged. See `sprints/sprint_9_retro.md`.
- Earlier, now on `main`: Sprint 9a router gating, the Sprint 9 chain (graph fixes, migrations 039/040, the `agent_economy` wallet-drain fix, the `.well-known` Vercel rewrite), and the prod-schema reconciliation code plus its CI job (PR #10).

---

## What's blocked or paused

- **Everything reaching users** waits on DrJ: production schema reconciliation (H1), merging `engine/phase-a`, and switching production to the repo router list (H3).
- **Root LICENSE file** waits on decision D1.
- **Sprint 10's 7-day live heartbeat** cannot start until the above is live. The code can be built locally first.
- **Synapse synergy thesis** is still waiting on founder context.

---

## Open questions requiring the founder's answer

1. **D1:** the licence for the platform repo (blocks LICENSE).
2. **D8:** which DIDs the founders run under in production, and how they log in there (needed for Sprint 10).
3. Which LLM providers run which founding agents, and the daily LLM cost ceiling (Sprint 10).
4. D2–D7: design defaults the engine chose reversibly (see HUMAN_ACTIONS). Confirm or change them when convenient.

---

## The next action (updated daily)

**DrJ:** do H5 first (urgent), then H1 → merge `engine/phase-a` → H3, following HUMAN_ACTIONS. Answer D1. **Engine:** draft and decompose Sprint 10 — Heartbeat.

---

## Recent decisions (last 30 days)

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
