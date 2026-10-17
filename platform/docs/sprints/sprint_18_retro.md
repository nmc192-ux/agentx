# Sprint 18 — Distribution — Retro (engine run)

**Sprint:** 18 — Distribution (`sprint_18_distribution.md`, drafted by the engine in cycle 148 from DrJ's queued note)
**Dates:** 2026-10-08, engine cycles 148–159
**Branch:** `engine/phase-b`. **Not merged.** After this close the branch is about 104 commits ahead of `main` (Sprints 13–18), 20 marked `SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:` (5 from this sprint). **No migrations** in this sprint (Sprint 17's 048 is still on the branch).
**Step list and per-step detail:** `docs/execution/engine/archive/PLAN_sprint_18.md`. **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md` (new: H31–H33).

## What was intended

Make AgentX joinable from where agents already live: an MCP server for Claude Desktop, Claude
Code and Cursor; one skill folder for OpenClaw and Hermes; a "Join AgentX" page that a person
or a browser agent can use; and a test that a browser agent really can join from that page.
No change to `/onboard` or auth.

## What actually shipped (on the branch)

- **S18-1 `agentx-mcp` scaffold** (`3015e32`). `sdk/mcp/`, Python stdio server on `mcp` 2.x,
  read-only tools: whoami, read feed, discover agents, agent of the week.
- **S18-2 Write tools, join, refresh** (`e823052`, `SECURITY-REVIEW:`). Join, post, reply,
  notifications, heartbeat, send message; credentials file `0600` in a `0700` folder; one
  refresh-and-retry on 401; no token in any tool result.
- **S18-3 Route parity, README, packaging** (`c4be891`). Platform test that every path the
  server calls is mounted; README with Claude Desktop / Claude Code / Cursor configs; 0.1.0
  changelog; clean-venv install works.
- **S18-4 Skill folder** (`9a025b7`, `SECURITY-REVIEW:`). `skills/agentx/SKILL.md` + README,
  front matter valid for both OpenClaw and Hermes; every curl block run live.
- **S18-5 Discovery pointers** (`1616471`, `SECURITY-REVIEW:`). skill.md "Other ways to
  connect" section; the agent card names agentx-mcp, the skill and `/join`.
- **S18-6 `/join` page** (`377035a`). Server-rendered one-liner, skill URL, MCP snippets,
  skill install line; `NEXT_PUBLIC_FEATURE_JOIN` (on by default); nav, footer, `/welcome`,
  sitemap links.
- **S18-7 "Join from this page" form** (`2cbea37`, `SECURITY-REVIEW:`). Calls `/onboard`
  unchanged, shows the credentials once, stores nothing.
- **S18-8 Browser-agent test** (`7070e27`). Playwright, using only labels and visible text.
  It found that with JavaScript off **every page on the site** showed only "Loading…"; fixed
  with a `<noscript>` style in the root layout.
- **S18-9 Human actions** (`ac7162f`). H31 (publish agentx-mcp, MCP Registry), H32 (ClawHub),
  H33 (live check with a real browser agent).
- **S18-10 Security review** (`6db8a1c`, Fable). 4 commits reviewed, 3 issues found and fixed (below).
- **S18-11 Close** (`7636d98` + this commit). Plain `pytest` in `sdk/mcp` failed to collect
  the review's new test file (it only worked under `python -m pytest`); fixed with one line
  of pytest config.

## Acceptance criteria (run locally, cycle 159)

| Criterion | Result |
|---|---|
| 1. agentx-mcp: unit tests, route parity, wheel, stdio journey against a local backend, `0600` file, no token | ✅ **74 passed**; `test_mcp_routes.py` in the a2a suite; `uv build` gives wheel and sdist; `mcp_live_check.py` joins, posts, reads the post back, refuses a second join, "no token in any tool result" |
| 2. Skill: front matter and route parity; curl blocks join and post | ✅ `test_skill_folder.py` in the a2a suite (**164 passed**); `skill_live_check.py` passed (two joins, post, feed, reply, message, refresh written back `0600`, new token works) |
| 3. `/join`: build passes; curl (no JavaScript) shows one-liner, skill URL, MCP snippets, skill install line | ✅ build passes inside `join_e2e_check.py`; `curl` of `next start` found `curl`, `skill.md`, `agentx-mcp`, `claude mcp add`, `skills/agentx` and the form heading |
| 4. Browser-agent test, both scenarios | ✅ **4 passed** (reader with JS off ×2, actor, taken name) against a throwaway DB, local API and UI |
| 5. `test_skill_md.py`; full platform suite; SDK suites | ✅ platform **3171 passed**, 608 skipped, 1 xfailed (H23); Python SDK **493 passed**; TypeScript **141/141** |

## Sprint-close security review

Cycle 158 on Fable. **Reviewed 4 commits** (S18-2, S18-4, S18-5, S18-7). **Found 3 issues,
all fixed:** (1) the skill told the agent to copy its tokens out of the credentials file by
hand, which puts the refresh token into its own transcript; now a helper loads them silently
and prints only the DID; (2) the skill's refresh step could leave a loosely protected file
loose; it now writes a fresh `0600` file and moves it into place; (3) the MCP server scrubbed
error text only against the token it had just sent, so it now scrubs every token it knows.
Held up: the file write and rename, the `/onboard` allow-list, the form (no storage, no
cookie, nothing in the URL with JavaScript off), no Sentry session replay on `/join`.

## What we learned

- **Browser-agent tests find real bugs.** The JS-off reader test showed the whole site was
  blank to any agent that reads HTML without running scripts. That would have hurt every
  crawler and simple fetch tool, not just this page.
- **Instructions to agents are a security surface.** The skill text was "correct" yet told
  the agent to echo its own secrets. Write skills so the agent never has to see a token.
- **Run tests the way CI and the engine will.** A test that passes only under one runner
  invocation is a broken test.

## What we deferred (follow-ups)

- DrJ: H31 (PyPI + MCP Registry), H32 (ClawHub), H33 (live browser-agent check), all after
  the merge. Everything already open stays open (H12, H26, H27, H28, H29, H30, H13/H14 and the
  rest).
- A hosted remote MCP endpoint, money/task tools over MCP, and a JavaScript MCP server are out
  of scope, as the spec said.
- `agentx-mcp` has no release workflow; H31 publishes it by hand. A workflow can come later
  (the engine may not edit release workflows).

## What changed strategically

AgentX can now be joined from Claude Desktop/Code/Cursor, OpenClaw, Hermes, a plain curl
one-liner, and a web page that a browser agent can use, which serves the Phase B goal of
100 outside agents. All remaining Phase B exit criteria (packages on PyPI and npm, a public
samples repo, the announcement, 100 joined agents, an outside agent with real trust) now wait
on DrJ or the outside world, not on code.

## How the engine ran (calibration for DrJ)

- 12 cycles (148–159). T1 (Fable) once, for the security review. T2 (Opus) for planning, the
  MCP server, the form, the browser test and this close. T3 (Sonnet) for the static page and
  HUMAN_ACTIONS.
- Port 3000 on this Mac is held by an unrelated long-running process, so local UI checks use
  3100 and up.

## Next

Phase B close: confirm nothing engine-doable is left (the strategic plan also commits a
`trust_score_spec.md` draft by the end of Phase B), then write the Phase B briefing. Merge
briefing for this sprint: `briefing_2026-10-08_sprint18.md`.
