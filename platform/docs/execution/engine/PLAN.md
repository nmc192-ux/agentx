# Engine PLAN — Sprint 18: distribution (not yet drafted or decomposed)

**Branch:** `engine/phase-b` · **Previous plan:** `archive/PLAN_sprint_17.md` (closed cycle 140;
retro `sprints/sprint_17_retro.md`, briefing `sprints/briefing_2026-10-07_sprint17.md`).

Sprint 16 (`sprints/sprint_16_vps_prep.md`, VPS prep) still waits on H21, so it cannot start.

**DrJ's queued note (arrived around cycle 132; only the engine's summary of it survived):** a
distribution sprint after Sprint 17 with four items:

1. an **MCP server** for AgentX (so MCP-capable agents can join and act through it);
2. an **OpenClaw / Hermes skill** (an installable skill for those agent runtimes);
3. a **browser-agent join test** (a browser-driving agent can join from the public site);
4. a **"Join AgentX" page** on the website.

Next cycle (T2): draft `sprints/sprint_18_distribution.md` from these four items and the Phase
B exit criteria (`strategy/strategic_plan_v2.md` §4: first 100 outside agents), then decompose
it here per Phase 1 of `autonomous_loop_v1.md`. Check the code first for anything that already
exists (e.g. an MCP router or skill.md pieces). Publishing anything (an MCP registry entry, a
skill marketplace listing, npm/PyPI) is a human action. Where the note's intent is unclear,
use a reversible default recorded in the log; make it a `DECISION_NEEDED` stop only if no
reversible default exists.
