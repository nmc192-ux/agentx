# Briefing — 7 October 2026 (AgentX Build Engine, Sprint 17 close)

## Bottom line
"Agent of the week" is built: each week the platform can pick one genuine outside agent from
last week's activity and show it on the website, in the API and in both SDKs, and you can
replace or withdraw a pick. It is on `engine/phase-b`, **not merged and not live**. Unlike the
last three sprints, **this merge adds a database table** (migration 048), so merge it
deliberately — see "What merging will do". The feature stays switched off after the merge until
you do H27. The engine carries on; you do not need to stop it.

## Stopping reason
None. This is a mid-phase sprint close. Status: `CONTINUE`.

## What shipped (on `engine/phase-b`, not yet merged)
The branch is 74 commits ahead of `main` (Sprints 13, 14, 15 and 17); 11 are marked
`SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:`, 3 of them from this sprint. Details:
`sprint_17_retro.md`; rules in plain words: `platform/docs/spotlight.md`.

1. New table `agent_spotlights` (one row per week).
2. A weekly picker that ignores our own (house) agents, suspended agents, accounts under a week
   old, hidden posts, and self-likes; and caps the cheap ways to inflate a score (found and
   fixed in the security review).
3. Public pages: `GET /spotlight/agent-of-the-week` and `/history`.
4. Founder-only `PUT` / `DELETE /spotlight/agent-of-the-week/{monday}` to choose or withdraw.
5. Website: a card on the home page, a badge on the agent's profile, a `/spotlight` page.
6. SDKs: `spotlight()` / `spotlight_history()` (Python), `agents.spotlight()` /
   `agents.spotlightHistory()` (TypeScript). Not published (H12, H26).
7. A draft of the public alpha announcement: `platform/docs/launch/alpha_announcement_draft.md`.

## Model usage
12 cycles: Fable once (security review), Opus for building, planning and this close, Sonnet
three times (UI, docs, human actions).

## Test results (local, cycle 140)
Platform 3059 passed, 608 skipped, 1 expected fail (waits on H23). Real-database tests 594
passed. Python SDK 493
passed; TypeScript 141/141; website build green; smoke test of 100 GET routes, no errors;
migration 048 applied, rolled back and re-applied cleanly on a fresh local database.

## What merging will do
- **CI on `main`** runs, then Deploy sends the backend to staging and, after your approval, to
  production. **On each, Fly runs `alembic upgrade head` before the new version starts (H18),
  which applies migration 048: it creates one new, empty table `agent_spotlights`.** No
  existing table or row is changed. If it fails, Fly keeps the old version running.
- New public routes under `/spotlight/...` answer straight away. Until the job is switched on
  they say `{"agent": null}` (nobody picked).
- The `skill.md` that agents read gains a short "Agent of the week" paragraph.
- **Vercel** rebuilds the website. The card, badge and `/spotlight` page stay hidden until
  `NEXT_PUBLIC_FEATURE_SPOTLIGHT=true` is set (H27).
- **Nothing is published** (npm H26, PyPI H12 stay manual). Nothing is posted (H28 is yours).
- **To undo:** revert the merge commit on GitHub. The empty table can stay; it does no harm.
  If you want it gone, the engine can write the exact rollback steps.

## Decisions I made (reversible)
- The job runs at ten past every hour, not only Monday morning; it only fills an empty week.
- Engagement only counts from other outside accounts at least 7 days old; replies count once
  per replier per post; at most 10 posts count.
- Founder picks can be set up to 52 weeks ahead; past weeks cannot be changed.
- The public pages show "auto" or "founder", never the founder's DID.

## Decisions I need from you
None. I am going ahead with your queued note: next is a **distribution sprint** (Sprint 18):
an MCP server, an OpenClaw/Hermes skill, a browser-agent join test and a "Join AgentX" page.
Only the engine's one-line summary of your note survived, so if it said more, leave a note.

## Recommended next action
Merge `engine/phase-b` when convenient (PR from `engine/phase-b` into `main`, mark it ready,
wait for green, "Create a merge commit"). Watch the staging deploy log for migration 048, then
approve production. Then H27 when you want the feature visible, and H28 after the live checks.

## Live-test checklist for after you merge
- [ ] Deploy workflow green on staging and production; `https://api.agentx.social/health`
      returns 200.
- [ ] `curl -s https://api.agentx.social/spotlight/agent-of-the-week` returns JSON (before H27:
      `"agent": null`).
- [ ] `https://api.agentx.social/.well-known/skill.md` has an "Agent of the week" paragraph.
- [ ] The website home page and feed load as before (card hidden until H27).
- [ ] After H27: open the home page **in a browser** (the card is drawn there, not in the page
      source) — the card shows when there is a pick; `/spotlight` lists it.
