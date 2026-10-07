# Engine PLAN — Sprint 18: Distribution

**Branch:** `engine/phase-b` · **Spec:** `platform/docs/sprints/sprint_18_distribution.md`
**Started:** cycle 148, 2026-10-08 (drafted and decomposed). **Previous plan:**
`archive/PLAN_sprint_16.md` (closed cycle 147). Sprints 13–17 are closed on the branch, not
merged.

The design choices (Python stdio MCP server talking HTTP directly, one AgentSkills folder for
OpenClaw and Hermes, server-rendered `/join` with a browser form, Playwright browser-agent
test) are reversible defaults recorded under "Decisions" in the cycle 148 log entry.

## Steps

- [x] **S18-0 — Draft the Sprint 18 spec and decompose it into this file.** T2 (planning).
  Check: spec exists; this file has the step list; DrJ-only items are in HUMAN_ACTIONS.
- [x] **S18-1 — `agentx-mcp` package and read-only tools.** T2 (new package). `sdk/mcp/`
  (`pyproject.toml`, `src/agentx_mcp/`, own `.venv` like `sdk/`), FastMCP stdio server,
  `httpx` client with base URL from `AGENTX_BASE_URL`, credential loading (env, then
  `~/.agentx/credentials.json`). Tools: `agentx_whoami`, `agentx_read_feed`,
  `agentx_discover_agents`, `agentx_agent_of_the_week`. Check: `pytest sdk/mcp/tests`
  (mocked HTTP; in-memory MCP client lists the four tools with typed schemas); `uv build`.
  *Done cycle 149 (`3015e32`): 18 tests pass, wheel builds, stdio subprocess lists the tools.
  Note: `mcp` is now 2.x, where `FastMCP` is `MCPServer`; pinned `mcp>=2.3,<3`.*
- [x] **S18-2 — Write tools, join and token refresh.** T2 (calls the reviewed `/onboard` and
  `/auth/token`; changes neither). `agentx_join`, `agentx_create_post`, `agentx_reply`,
  `agentx_notifications`, `agentx_heartbeat`, `agentx_send_message`; credentials file `0600`
  in a `0700` dir, refuse join when credentials exist; one refresh-and-retry on 401; no token
  in any tool result or log. `SECURITY-REVIEW:` prefix (stores credentials). Check: unit tests
  that fail closed (no credentials → clear error, refresh fails → clear error, file mode,
  token-absence scan of every tool result); live run over stdio against a local backend:
  join → post → read the post back from the feed.
  *Done cycle 150 (`e823052`): 62 tests pass; `platform/scripts/mcp_live_check.py` (throwaway
  DB + local API) joins, posts and reads back over stdio, no token in any result. Refresh of
  an env token is held in memory only; a file that cannot be written also falls back to
  memory with a stderr warning.*
- [x] **S18-3 — Route parity, README, packaging.** T2. Test that every path the server calls
  is a mounted route (reuse `test_skill_md.py`'s route collection); `README.md` with Claude
  Desktop, Claude Code (`claude mcp add`) and Cursor configs; `CHANGELOG.md` 0.1.0; wheel
  installs into a clean venv and `agentx-mcp --help` (or a stdio `initialize`) works.
  Check: parity test in the platform suite; clean-venv install.
  *Done cycle 151 (`c4be891`): `platform/tests/a2a/test_mcp_routes.py` scans the package
  source for its 11 calls; all mounted in every config except Agent of the week when the
  `spotlight` gate is off, which now gives a plain "not switched on" error. Clean-venv wheel
  install: `--version` and stdio `initialize` + `tools/list` (10 tools) work.*
- [x] **S18-4 — OpenClaw / Hermes skill folder.** T2. Confirm current front-matter rules from
  the OpenClaw and Hermes docs; write `skills/agentx/SKILL.md` + `README.md` (install paths
  for both). Check: platform test parses the front matter (name, description length) and
  checks every path against mounted routes; a script runs the skill's curl blocks against a
  local backend and the agent joins and posts.
  *Done cycle 152 (`9a025b7`): front matter checked against both docs (Hermes: name =
  folder, `version`, description ≤1,024; OpenClaw: `metadata.openclaw.requires.bins`), metadata
  as one JSON line so both parse it. 9 tests; `scripts/skill_live_check.py` runs every block as
  written: two joins, heartbeat, post, feed, reply, notifications, message, refresh, discover.
  Prefixed `SECURITY-REVIEW:` (tells agents how to store tokens), so S18-10 covers it.*
- [ ] **S18-5 — Discovery pointers in `skill.md` and `agent.json`.** T2. "Other ways to
  connect" section (MCP, skill folder, `/join`). `SECURITY-REVIEW:` prefix (`.well-known`).
  Check: `tests/a2a/` green.
- [ ] **S18-6 — `/join` page, static sections.** T3 (UI). Server-rendered sections 1–4 of the
  spec, `NEXT_PUBLIC_FEATURE_JOIN`, nav / `/welcome` / home links, sitemap. Check: `npm run
  build` in `ui/`; `curl` of the page from a local `next start` contains the one-liner, skill
  URL, MCP snippets and skill install line.
- [ ] **S18-7 — "Join from this page" form.** T2 (shows credentials; calls `/onboard`
  unchanged). Client component; credentials shown once, never stored; 409/429/422 messages.
  `SECURITY-REVIEW:` prefix. Check: `npm run build`; manual local run joins an agent; grep
  the built bundle for `localStorage`/`sessionStorage`/`document.cookie` use in the component.
- [ ] **S18-8 — Browser-agent join test.** T2. Playwright dev dependency in `ui/`,
  `ui/e2e/join.spec.ts` with the reader (JS off) and actor scenarios, `npm run test:e2e`.
  Check: both pass against a local backend and UI.
- [ ] **S18-9 — Human actions H31–H33.** T3. Exact instructions for publishing `agentx-mcp`
  (PyPI + MCP Registry), the skill (ClawHub), and the live browser-agent check.
  Check: entries present, copy-paste ready.
- [ ] **S18-10 — Sprint-close security review.** T1 (protocol 5a). All `SECURITY-REVIEW:`
  commits of this sprint (S18-2, S18-5, S18-7). Check: adversarial tests added; log records
  "reviewed N, found M".
- [ ] **S18-11 — Sprint close.** T2. Acceptance criteria 1–5 from the spec, retro, briefing,
  `state_of_agentx.md`, archive this plan.

## Open human items touching the branch

Merge (Sprints 13–17, migration 048); H29, H30 (VPS); H26, H12 (publish); H27, H28.
H31–H33 (this sprint) are placeholders until S18-9 writes them out.
