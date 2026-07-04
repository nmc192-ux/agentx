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

- **Sprint 9a — Router gating into the repo** (branch `phase-a-autonomous`, latest commit `026033a`, **not yet merged**). Router enable/disable now lives in version-controlled, commented repo config (`platform/src/router_config.py`) with the `DISABLED_ROUTERS` env var kept as an emergency override; startup logs the effective list and its source. Repo default set to the **20-router set DrJ confirmed by reading the live production value** on 2026-07-04 (all gated routers, incl. `memory`), for zero behavior change on merge or env-var removal. Parity re-verified EXACT at 20 (deterministic + independent Fable 5 check). Verified locally (startup log + OpenAPI + full suite 2031 passed / 14 skipped). **Note:** the first 9a pass had inferred 19 (memory enabled) from the 5 May audit; DrJ's live read corrected it to 20 (memory disabled). `memory` being off is a magna-carta core primitive with no known reason yet — to be investigated in Sprint 9. See `sprints/briefing_2026-07-04b.md` and `sprints/sprint_9a_retro.md`.
- **Sprint 9 spec gap closed** — `sprint_9a_router_gating.md` and `sprint_9_stabilize.md` committed to `main` (2026-07-03/04), resolving the missing-spec blocker from the first autonomous run.
- **Sprint 9 chain — 9 (safe fixes) + 9-sec (wallet security) + 9-wellknown (A2A discovery)** (branch `phase-a-autonomous`, commits `e9ef862`→`2cfa87a`, **not yet merged**). Shipped on branch: graph column/table typo fixes; deploy-safe `governance_votes` migration (039) + discovery reconciliation migration (040); `/health` git-commit field; the **unauthenticated wallet-drain fix** in `agent_economy` (SECURITY-REVIEW, tests prove it fails closed); the `.well-known` Vercel rewrite (NEEDS-DELIBERATE-MERGE). Full suite 2033 passed. **Memory investigation:** STALE GATING — a clean re-enable candidate (was collateral of a 2026-04-23 scope cut, not broken); left disabled per spec. **🔴 Two major findings:** (1) the Alembic migration chain was broken since 035 (never applied past 033 — fixed); (2) production's DB is **divergent** — stamped `037` but missing most post-baseline tables. No router was enabled (they'd 500 in prod until schema is reconciled). See `sprints/briefing_2026-07-04_chain.md` and `sprints/sprint_9_chain_retro.md`.

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

**Now:** Review the Sprint 9 chain on `phase-a-autonomous` per `sprints/briefing_2026-07-04_chain.md`. Order: (1) review + merge the **wallet security fix** (`73c6fe5`) — the one urgent, self-contained item — then verify against prod and enable via Fly.io; (2) read "Production schema divergence" and decide on a **prod-schema reconciliation** task (blocks router enablement; take a DB snapshot before merging the migration commits); (3) merge the SAFE commits at your pace; (4) handle `.well-known` (`2cfa87a`) as a deliberate merge-and-verify. `memory` is now a clean re-enable candidate once prod schema is confirmed.

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
