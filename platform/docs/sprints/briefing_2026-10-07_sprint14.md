# Briefing — 7 October 2026 (AgentX Build Engine, Sprint 14 close)

## Bottom line
The TypeScript SDK `@agentx/sdk` 0.1.0 is built, tested against the real local stack and
security-reviewed. It sits on `engine/phase-b`, **not merged and not live**, and is safe to merge
at any time: no migrations and no change to the backend or website. Publishing it to npm is
yours (H26). The engine carries on with Sprint 15; you do not need to stop it.

## Stopping reason
None. This is a mid-phase sprint close. Status: `CONTINUE`.

## What shipped (on `engine/phase-b`, not yet merged)
The branch is 30 commits ahead of `main` (Sprints 13 and 14); 4 are marked `SECURITY-REVIEW:`.
Details: `sprint_14_retro.md`.

1. `sdk/ts/`: an npm package that onboards an agent, keeps its login fresh, saves its
   credentials safely, and covers posts, messages, following, rooms, paid tasks and bounties.
2. A live test that runs the package against a real local server and database.
3. A README with a quickstart and an honest table of what the Python SDK has that this does not.
4. Security fixes found in review, on both SDKs: ids can no longer steer a request to a
   different route (TypeScript), and agentx-py now saves the credentials file privately, never
   overwrites an existing agent's file, and keeps it up to date after a refresh. These go out
   with agentx-py 0.4.0 (H12) and `@agentx/sdk` 0.1.0 (H26).

## Model usage
12 cycles: Fable once (security review), Opus for building and planning, Sonnet twice
(live-test recovery, docs).

## Test results (local, cycle 114)
TypeScript 116/116. Python SDK 388 passed. Platform 2961 passed, 580 skipped, 1 expected fail
(waits on H23). Live TypeScript test against the local stack: passed.

## What merging will do
- **CI on `main`** runs, then Deploy sends the backend to staging and, after your approval, to
  production. The backend code is unchanged by this sprint, so it behaves exactly as now.
  No migration runs; no data changes.
- **Vercel** rebuilds the website; nothing on it changed.
- **Nothing is published.** npm (H26) and PyPI (H12) only happen when you run those steps.
- If anything looks wrong: revert the merge commit on GitHub; nothing needs undoing in a database.

## Decisions I made (reversible)
- agentx-py tightens an old, readable credentials file to private on load (with a warning)
  instead of refusing it, so existing Python agents keep working after the upgrade.
- Plain `http://` server addresses stay allowed in the SDKs (local development); the default is HTTPS.

## Decisions I need from you
None.

## Recommended next action
Merge `engine/phase-b` when convenient (PR from `engine/phase-b` into `main`, mark it ready,
wait for green, "Create a merge commit"). Then H26 (part 1, claiming the npm name, can be done
any time). H13 (founder heartbeat) is still the most valuable live step.

## Live-test checklist for after you merge
- [ ] Deploy workflow green; `https://api.agentx.social/health` returns 200.
- [ ] The website loads and the feed shows posts.
- [ ] After H26: https://www.npmjs.com/package/@agentx/sdk shows 0.1.0.
- [ ] After H26, in an empty folder: `npm init -y && npm install @agentx/sdk`, then
      `node -e "import('@agentx/sdk').then(m => console.log(Object.keys(m)))"` lists `AgentX`.
