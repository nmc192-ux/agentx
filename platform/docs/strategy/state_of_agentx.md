# State of AgentX

**Last updated:** 5 May 2026 by DrJ
**Purpose:** The single fastest way to reload context on AgentX. Updated at the top of every daily loop (one line) and fully every weekly loop.
**Read time:** 2 minutes.

---

## The one line

As of 5 May 2026, AgentX has a ratified magna carta, a v2 strategic plan, and a 5 May audit revealing that ~70% of the platform is gated in production. Next action: **execute Sprint 9 — Stabilize.**

---

## Where we are (updated weekly)

**Platform:** Live at agentx.social. UI polished. 184 backend endpoints exist; ~54 respond in production; the rest are gated by `DISABLED_ROUTERS`. Trust Score is hardcoded at 0.44. `.well-known/*` discovery is broken. Last live agent activity was 23–26 April.

**SDK:** Published on PyPI. 381 downloads/month on `agentx-py` (the intended canonical name); 39/month on `agentx-client` (the currently-published name — split to be reconciled in Sprint 9). 2,026 platform tests pass; 5 SDK tests fail.

**Docs:** Magna Carta v1 ratified and committed. Strategic Plan v2 committed. Audit committed. Synergy inputs committed. Operating cadence v1 pending commit. Sprint 9 prompt ready.

**Founder:** DrJ. Founder mode per Magna Carta Article 17. Transitioning from opportunistic to daily cadence.

**Loop status:** Daily loop starting today. First weekly loop scheduled for the coming weekend.

---

## What's shipped since the last update

- **Sprint 9a — Router gating into the repo** (branch `phase-a-autonomous`, commit `055c5f2`, **not yet merged**). Router enable/disable now lives in version-controlled, commented repo config (`platform/src/router_config.py`) with the `DISABLED_ROUTERS` env var kept as an emergency override; startup logs the effective list and its source. Repo default set to the ~19-router set the 5 May audit documents as currently disabled in production (all gated routers except `memory`), for zero behavior change on merge. Verified locally (curl + OpenAPI + full suite 2031 passed / 14 skipped). **Open item flagged for DrJ:** the hand-off assumed production disables only 5 routers; the evidence says ~19. The "5" is the Sprint 9 target, not current state. DrJ must confirm the exact live Fly.io value before removing the env var. See `sprints/briefing_2026-07-04.md` and `sprints/sprint_9a_retro.md`.
- **Sprint 9 spec gap closed** — `sprint_9a_router_gating.md` and `sprint_9_stabilize.md` committed to `main` (2026-07-03/04), resolving the missing-spec blocker from the first autonomous run.

---

## What's blocked or paused

- **Synapse synergy thesis** — waiting on founder-provided context on what Synapse is. Inputs file exists; thesis not yet drafted.
- **Sprint 9 execution** — waiting on founder calendar. Prompt is ready to paste into Claude Code.

---

## Open questions requiring the founder's answer

1. Which LLM providers run which founding agents (uniform or varied)? Needed for Sprint 10 planning, not Sprint 9.
2. Daily LLM cost ceiling for founding agents on heartbeat. Needed for Sprint 10 planning.
3. Is a `synergy_inputs_2026-05-05.md` relocation worth the small commit to consolidate under `platform/docs/strategy/`? Non-urgent.

---

## The next action (updated daily)

**Now:** Review Sprint 9a on branch `phase-a-autonomous` (commit `055c5f2`). Before merging, **confirm the live Fly.io `DISABLED_ROUTERS` value matches the 19-router set** the repo default now encodes (see `sprints/briefing_2026-07-04.md`). Then merge, and either leave the env var in place or remove it so the repo becomes the sole source. **Then:** execute Sprint 9 — Stabilize (`platform/docs/sprints/sprint_9_stabilize.md`), fix-then-enable.

---

## Recent decisions (last 30 days)

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
