# Briefing — 7 October 2026 (AgentX Build Engine, Sprint 15 close)

## Bottom line
A newcomer can now go from nothing to a first post in under ten minutes in Python (7.6 min)
or TypeScript (4.5 min), measured from a cold start. All five sample agents exist in both
languages and are tested against the real local stack. This is on `engine/phase-b`, **not
merged and not live**, and is safe to merge at any time: no migrations, and the only backend
change is two extra lines of text in the public `skill.md`. The engine carries on; you do not
need to stop it.

## Stopping reason
None. This is a mid-phase sprint close. Status: `CONTINUE`.

## What shipped (on `engine/phase-b`, not yet merged)
The branch is 53 commits ahead of `main` (Sprints 13, 14 and 15); 8 are marked
`SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:`. Details: `sprint_15_retro.md`.

1. The quickstart (`platform/docs/quickstart.md`) has a TypeScript path; every code block in it
   is run by a test.
2. `agentx-examples/ts/`: the five sample agents in TypeScript.
3. The TypeScript SDK gained wallet, governance and collectives.
4. `skill.md` (what agents read first) now names both libraries with pinned versions.
5. The root README, SDK README and samples README were rewritten for a cold reader.
6. Security: both SDKs now refuse an id that could steer a request to a different route
   (including the old, deprecated TypeScript client, found in review and fixed).

## Model usage
14 cycles: Fable once (security review), Opus for building, planning and this close, Sonnet
three times (docs and bookkeeping).

## Test results (local, cycle 128)
Platform 2970 passed, 586 skipped, 1 expected fail (waits on H23). Python SDK 480 passed.
TypeScript 139/139. Real-database tests for the TS samples, both quickstarts, the Python
samples and the TS SDK: 22 passed.

## What merging will do
- **CI on `main`** runs, then Deploy sends the backend to staging and, after your approval, to
  production. The one backend change: `https://api.agentx.social/.well-known/skill.md` gains a
  short "Client libraries (optional)" section with `pip install "agentx-py>=0.4.0"` and
  `npm install @agentx/sdk@^0.1.0`. Until you publish (H12, H26) those lines fail plainly with
  "not found", and the text says to use the plain HTTP calls in that case.
  No migration runs; no data changes.
- **Vercel** rebuilds the website; nothing on it changed.
- **Nothing is published.** npm (H26) and PyPI (H12) only happen when you run those steps.
- If anything looks wrong: revert the merge commit on GitHub; nothing needs undoing in a database.

## Decisions I made (reversible)
- skill.md pins versions instead of naming bare packages, so pip cannot install the old broken
  0.2.2 from PyPI before H12.
- The quickstart's promise changed from "five minutes" to "under ten minutes" to match the
  measured cold run.
- `@agentx/sdk` stays at 0.1.0 (never published, so no version bump was needed).

## Decisions I need from you
None.

## Recommended next action
Merge `engine/phase-b` when convenient (PR from `engine/phase-b` into `main`, mark it ready,
wait for green, "Create a merge commit"). Then H26 and H12 so the install lines work. H21 (VPS
facts) unblocks Sprint 16. H13 (founder heartbeat) is still the most valuable live step.

## Live-test checklist for after you merge
- [ ] Deploy workflow green; `https://api.agentx.social/health` returns 200.
- [ ] `https://api.agentx.social/.well-known/skill.md` shows a "Client libraries (optional)"
      section with both install lines.
- [ ] The website loads and the feed shows posts.
- [ ] After H12 and H26: in an empty folder, follow `platform/docs/quickstart.md` Path 2
      (Python) and Path 3 (TypeScript) against production; each ends with your post on the feed.
