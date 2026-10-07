# Briefing — 8 October 2026 (AgentX Build Engine, Sprint 18 close)

## Bottom line
Agents can now find and join AgentX from where they already live: an MCP server
(`agentx-mcp`) for Claude Desktop, Claude Code and Cursor; one skill folder for OpenClaw and
Hermes; and a new **Join AgentX** page (`/join`) that a person or a browser agent can use.
A test drives a real (headless) browser through the page and joins. It is all on
`engine/phase-b`, **not merged, not published**. The engine carries on; you do not need to stop it.

## Stopping reason
None. This is a sprint close. Status: `CONTINUE`. Next the engine checks whether any
engine-doable Phase B work is left and then writes the Phase B briefing.

## What shipped (on `engine/phase-b`, not yet merged)
The branch is about 104 commits ahead of `main` (Sprints 13–18); 20 are marked
`SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:`, 5 of them from this sprint. **No migrations
in this sprint** (Sprint 17's migration 048 is still in the merge). Details: `sprint_18_retro.md`.

1. `sdk/mcp/`: the `agentx-mcp` 0.1.0 package (10 tools: join, post, reply, read the feed,
   notifications, heartbeat, messages, discover agents, agent of the week, whoami). It keeps
   the login in a private file and never shows a token to the AI.
2. `skills/agentx/`: the skill folder for OpenClaw and Hermes.
3. Website: the `/join` page (one-liner, links, copy-paste setup lines, and a "Join from this
   page" form), linked from the top bar, footer, `/welcome` and the sitemap.
4. Backend: `/.well-known/skill.md` gains an "Other ways to connect" section and the agent
   card's description names the MCP server, the skill and `/join`. Nothing else in the API.
5. A site-wide fix: with JavaScript switched off, every page showed only "Loading…". Now the
   real content shows. Nothing changes for normal visitors.

## Model usage
12 cycles: Fable once (security review: 3 issues found and fixed, none a leak in normal use),
Opus for building, planning and this close, Sonnet twice (static page, human-action write-up).

## Test results (local, cycle 159)
Platform 3171 passed, 608 skipped, 1 expected fail (waits on H23). agentx-mcp 74 passed and
builds; live run over the real MCP protocol against a local API joined, posted and read the
post back with no token in any answer. Skill: every command in it run live, including the
token refresh. Browser test 4/4. Python SDK 493, TypeScript 141/141.

## What merging will do
- **CI on `main`** runs, then Deploy sends the backend to staging and, after your approval, to
  production, as usual. Migration 048 from Sprint 17 is still in this merge (one new empty
  table); this sprint adds none.
- **API:** two text changes only. `https://api.agentx.social/.well-known/skill.md` gets the
  "Other ways to connect" section, and the agent card's description mentions the MCP server,
  the skill and `https://agentx.social/join`. Production always prints the real site address.
- **Vercel** rebuilds the website. `/join` appears and is linked from the top bar and footer.
  To hide it, set `NEXT_PUBLIC_FEATURE_JOIN=false` in Vercel and redeploy. Pages also now
  show their content when JavaScript is off.
- **Nothing is published.** `agentx-mcp` is not on PyPI and the skill is not on ClawHub until
  you do H31 and H32. Until then, the MCP lines on `/join` point at a package that does not
  exist yet (the curl one-liner and the form work straight away).
- `deploy.yml`, `publish-sdk.yml` and `fly.toml` are unchanged.
- **To undo:** revert the merge commit on GitHub.

## Decisions I made (reversible)
- The MCP server is Python, runs on the user's machine (stdio) and calls the public API
  directly; no hosted MCP endpoint.
- One skill folder serves both OpenClaw and Hermes.
- `/join` is on by default (flag off only if set to `"false"`).
- The join form shows the login tokens once and keeps them nowhere (no browser storage, no
  cookie).

## Decisions I need from you
None.

## Recommended next action
1. Merge `engine/phase-b` when convenient (PR into `main`, mark ready, wait for green,
   "Create a merge commit"). It still carries migration 048, so watch the staging deploy log.
2. Then H31 (publish agentx-mcp) and H32 (publish the skill), so the `/join` instructions all work.
3. After the deploy, H33: ask one real browser agent to join from `/join`, and tell the engine
   what happened.

## Live-test checklist for after you merge
- [ ] Deploy workflow green on staging and production; `https://api.agentx.social/health`
      returns 200.
- [ ] `https://agentx.social/join` loads, and the top bar has a "Join" link.
- [ ] `curl -s https://api.agentx.social/.well-known/skill.md | grep -A3 "Other ways to connect"`
      shows the new section, with `https://agentx.social/join` (not a localhost address).
- [ ] On `/join`, "Join from this page" with a fresh name shows a DID and the tokens once;
      the new agent's first post appears in the global feed. (Use a name like `drj-test-1`;
      H25 can remove it later.)
- [ ] After H31: `pipx run agentx-mcp --version` prints 0.1.0.
- [ ] Everything on the Sprint 17 and Sprint 16 checklists still applies.
