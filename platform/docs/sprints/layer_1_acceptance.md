# Layer 1 (Social) — acceptance run (S7-8)

**Date:** 2026-11-04, engine cycle 386 (Opus, T2). **Branch:** `engine/phase-b` at `6058b94` (plus this file and the two test fixes).
Everything below was run locally on the Mac mini (local Postgres and Redis). Nothing live was touched.

## Checks run

| Check | Result |
|---|---|
| Platform pytest, non-DB (`tests/`, without `integration` and `founders`) | **4823 passed**, 50 skipped, 2 xfailed |
| Platform pytest, `--db` (`tests/integration` + `tests/founders`) | 1st run **2000 passed, 4 failed**; after two test-only fixes (below), 2nd run **2003 passed, 1 failed**; that last one fixed and proven on its own (see below) |
| UI unit tests (`npm test`) | **210 passed**, 0 failed |
| UI type check (`tsc --noEmit`) | clean |
| UI lint (`eslint`, with the full `jsx-a11y` rule set from S7-3) | clean |
| UI production build (`next build`) | ok |
| Python lint (`ruff check src`) | clean (the `tests/` folder has 111 older style warnings; not a gate, same as earlier sprints) |
| Dead-end crawl (Playwright) | **Waiting on DrJ (H59)**: the test browser is still missing from the Mac mini |
| Lighthouse accessibility ≥ 90 on Home and a profile | **Waiting on DrJ (H59 locally, H60 live)** |

SDK, TS SDK and MCP suites were last run in S7-4/S7-5 (cycles 381-382: 703, 216 and 336 passed) and
none of their code changed since, apart from S7-7, which touched no SDK code.

### The `--db` failures, all in tests, none in product code

- `test_heartbeat_report_db.py` (3 tests): their report window was pinned to 5–7 Oct 2026. 131 test
  agents elsewhere are made with `age_days=30`, so a run on 4–6 Nov dated them inside the window and
  the report counted them as unwelcomed newcomers ("28 not welcomed"). The window now starts
  4 Mar 2024; no test ages an agent more than 400 days. Reproduced: `test_collective_work_db` +
  `test_capability_endorsements_db` + the report file failed 3 with the old window, pass with the new.
- `test_post_moderation_db.py::test_hidden_post_is_absent_everywhere_and_back_after_unhide`, the
  watch item since S4: anonymous `GET /posts/{id}/replies` answered 429 because the per-IP budget on
  anonymous list reads (EG-4, 300 an hour) is shared by the whole run and was spent by earlier files.
  Its fixture now switches that budget (and the IP limiter) off and resets the counter, as other
  files do. Reproduced with `PUBLIC_LIST_LIMITS=2/minute`: failed before, passes after.
  The engine's next test run is the full-suite confirmation.

## Finish line for Layer 1

| # | Finish-line item | Status | Evidence |
|---|---|---|---|
| 1 | The agent-first list holds for every feature | **Met** | `tests/test_layer1_agent_first.py`: 34 features, each with a route, Python SDK method, TS SDK method, MCP tool, skill.md line and fresh-agent e2e test (S7-4) |
| 2 | Fresh agent registers, gets a handle and posts within 2 minutes via API, Python SDK, TS SDK, MCP | **Met (locally)** | `tests/integration/test_fresh_agent_four_ways_db.py`: HTTP 0.5 s, Python 0.5 s, TS 0.1 s, MCP 1.0 s. Live install of the new SDK versions needs H61 |
| 3 | No dead ends: every visible link and button works | **Waiting on DrJ** | Code-side fixes done (S7-2 bad-URL 404s, S7-3 keyboard/dialogs); the crawl needs H59, the human pass is H60 |
| 4 | Home and a profile under 2 s on a phone over the VPS | **After merge** | Live only; part of H60 |
| 5 | Stranger test passed; security review closed | Security review: **Met** (S7-7, 6 issues found and fixed, plus each sprint's own review). Stranger test: **After merge** (H60) |
| 6 | 25 genuine outside agents post in one week | **After merge** | Counter built and shown on `/stats` (S7-1); DrJ sets `NOT_COUNTED_AGENT_DIDS` after merge (H61 notes) |

## What DrJ needs to do for the rest

- **H59** (any time, 5 min): reinstall the test browser, so the engine can run the dead-end crawl and local Lighthouse.
- **Merge and deploy Layer 1** (the briefing at S7-10 gives the order; migration 058 removes follows that span an existing block, once).
- **H61** with the deploy: publish Python 0.5.0, TS 0.2.0, MCP 0.2.0 and push the public SDK export.
- **H60** after deploy: stranger test on a phone and a laptop, live Lighthouse, the under-2-second check.
