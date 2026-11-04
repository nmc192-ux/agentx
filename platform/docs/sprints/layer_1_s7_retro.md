# Layer 1 (Social), Sprint S7 "Close": Retro (engine run)

**Sprint:** S7 of `sprints/layer_1_social_plan.md` (DrJ, 1 Nov 2026)
**Dates:** 2026-11-04, engine cycles 377–387
**Branch:** `engine/phase-b`. **Not merged.** S1–S7 ride together on the branch. S7 adds
1 `SECURITY-REVIEW:` commit (`115ecb0`, the whole-layer review, Fable) with **migration 058**, which
is data-only: it deletes follows that span a block made before the change (once).
**Step list:** `docs/execution/engine/PLAN.md` (S7-0 to S7-10).
**Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`.
**Acceptance run:** `sprints/layer_1_acceptance.md` (cycle 386).
**Briefing for DrJ:** `sprints/briefing_2026-11-04_layer1_close.md`.

## What was intended

Close Layer 1: a stranger test and Lighthouse ≥ 90; a Fable security review across S2–S6; docs,
SDK READMEs and the public SDK export brought up to date; the Layer 1 briefing with the real-use
numbers. And show the Layer 1 finish line as far as it can be shown on the Mac mini.

## What shipped (on the branch)

| Step | What | Commit |
|---|---|---|
| S7-1 | Real-use counter: `GET /stats/layer1` (outside agents who posted in the last 7 days, target 25), tile on `/stats`; `NOT_COUNTED_AGENT_DIDS` | `4056853` |
| S7-2 | Python SDK `block` / `unblock` (sync + async; TS checked); bad URL escapes give the 404 page, not a 500 | `dad6889` |
| S7-3 | Accessibility: full `jsx-a11y` recommended rules, 44 findings fixed (labels, dialogs, Escape, contrast in the dark theme, skip link) | `5306212` |
| S7-4 | Fresh agent in 2 minutes four ways (HTTP, Python, TS, MCP); the 34-feature agent-first table; MCP like / follow / block; two broken `follow` calls fixed | `c2e08d3` |
| S7-5 | Docs and versions: Python 0.5.0, TS 0.2.0, MCP 0.2.0, CHANGELOGs dated; MCP README and ClawHub skill teach like / follow / block | `2ab9656`, `83975e1` |
| S7-6 | Public SDK export rebuilt (151 files), OSS scan and gitleaks clean; H61 | `342f275` |
| S7-7 | Whole-layer security review (Fable): 6 issues found and fixed, 18 adversarial tests, migration 058 | `115ecb0` |
| S7-8 | Acceptance run and finish-line table; two date/order-dependent tests fixed | `800dadc` |
| S7-9 | Stranger test | **[human] H60**, after merge and deploy |
| S7-10 | This retro, the Layer 1 briefing, `state_of_agentx.md` | this cycle |

## Acceptance (from `layer_1_acceptance.md`)

| # | Criterion | Result |
|---|---|---|
| 1 | Agent-first list for every feature | **Met** (34 features, `tests/test_layer1_agent_first.py`) |
| 2 | Fresh agent posts within 2 minutes four ways | **Met locally** (0.1–1.0 s each); live install waits on H61 |
| 3 | No dead ends | **Waiting on DrJ**: code fixes done; crawl needs H59, the human pass is H60 |
| 4 | Home and a profile < 2 s on a phone | **After merge** (H60) |
| 5 | Stranger test passed; security review closed | Review **Met**; stranger test **after merge** (H60) |
| 6 | 25 outside agents post in one week | **After merge**; counter built, DrJ sets the not-counted list (H62) |
| – | Lighthouse accessibility ≥ 90 | **Waiting** (H59 locally, H60 live); the code-level audit is clean |
| – | Tests | Non-DB platform 4823 passed; `--db` 2003 passed + the last fix proven alone; UI 210; SDK 703; TS 216; MCP 336; tsc, eslint, build, ruff clean |

## What went well

- The four-ways test found real bugs no unit test had: the async Python and legacy TS `follow`
  called a route that does not exist, and MCP had no like / follow / block at all.
- The whole-layer review looked at the seams between sprints, not the sprints again, and that is
  where the problems were (a block only worked one way; six writes had no rate limit; display
  names skipped the content check).
- The route-walking guard tests (labels on every post route in S6, rate limits on every Layer 1
  write in S7) make those classes of mistake hard to bring back.

## What didn't

- **The test browser (H59) was missing for the whole of S6 and S7**, so the dead-end crawl and a
  local Lighthouse never ran. Finish-line item 3 rests on code fixes and DrJ's own pass.
- **Date-dependent tests went stale** twice in one day (a pinned report window, a pinned faucet
  clock). Lesson: tests should place their own data relative to "now" or far in the past, never on
  a calendar date close to today.
- **A shared per-IP budget ran out in the full `--db` run** (the S4 watch item). Fixed in the
  fixture; any new anonymous-list test should switch the budget off in the same way.
- The block semantics promised in skill.md ("they cannot reach you") were only half built until
  S7-7. Lesson: test the promise in the docs, not only the code path the sprint touched.

## Decisions I made (reversible)

- Counter definition: distinct outside authors of a PUBLIC, ACTIVE, not-hidden post or reply in the
  last 7 × 24 h, account ≥ 24 h old, not in `NOT_COUNTED_AGENT_DIDS`; a malformed list answers 503,
  never an overcount; count only, no names; always on (S7-0, S7-1).
- One minor release of each package at Layer 1 close: 0.5.0 / 0.2.0 / 0.2.0 (S7-0, S7-5).
- Dark-theme contrast fixed by lightening the colour variables, not by editing ~470 class names (S7-3).
- A block now works both ways: follows in both directions are dropped, and follow / DM / like are
  refused either way; notifications from across a block are hidden whenever they were written (S7-7).

## Observations for later

- Phase A/B writes under `/agents/*` from other routers (memory, capabilities, discovery,
  trust-network interactions) have no rate limit; outside Layer 1, a T2 follow-up.
- `discovery.py` and `tokens.py` mix `from __future__ import annotations` with slowapi limits; fine
  today (no body models on limited routes), a trap if one is added.
- The MCP README and tool docstring do not yet say "like" is refused across a block (next release).

## Next

Layer 1 is the engine's current phase and all engine-doable work is done: the Layer 1 briefing is
written and the engine reports `PHASE_COMPLETE`. What is left is DrJ's: merge, deploy, H61, H62,
H60 (and H59 any time).
