# Briefing — 7 October 2026 (AgentX Build Engine, Sprint 13 close)

## Bottom line
Your five tidy-up items are done or written up for you. The branch `engine/phase-b` holds them,
is **not merged and not live**, and is safe to merge at any time: no migrations, no change to
how the live site behaves. Three items need you (H23, H24, H25). The engine carries on with
Phase B planning; you do not need to stop it.

## Stopping reason
None. This is a mid-phase sprint close, not a stop. Status: `CONTINUE`.

## What shipped (on `engine/phase-b`, not yet merged)
10 commits ahead of `main`; 1 marked `SECURITY-REVIEW:` (the test-account script, built and
reviewed on Fable). Details: `sprint_13_retro.md`.

1. CI no longer runs on the engine's draft pull request until you mark it "Ready for review".
2. H23: copy-paste change to make the scheduler machine smaller (the engine may not edit `fly.toml`).
3. The website build no longer prints the Sentry warning.
4. H24: one command so the engine's commits carry your GitHub noreply address.
5. A script that safely removes the April test accounts; H25 tells you how to run it (look, dry run, apply).

## Model usage
7 cycles: Fable once (the script that deletes production data), Opus four times, Sonnet once,
plus this close on Opus.

## Test results (local, cycle 102)
Platform suite 2961 passed, 579 skipped, 1 expected fail (waits on H23). Real-Postgres suite
565 passed. `actionlint` clean. Website build succeeds without the Sentry warning.

## What merging will do
- **CI on `main`** runs as before, then the Deploy workflow sends the backend to staging and,
  after your approval, to production. The backend gains one script file that does nothing
  unless you run it (H25). No migration runs; no data changes.
- **Vercel** rebuilds the website from `main`. It looks and behaves the same; only the build
  warning is gone.
- **Draft pull requests** stop spending CI minutes. A normal (non-draft) pull request still runs CI.
- If anything looks wrong: revert the merge commit on GitHub; nothing here needs undoing in a database.

## Decisions I made (reversible)
- No "Run workflow" button for CI (it would let a hand-run on `main` redeploy production).
- `fly.staging.toml` left alone (staging has no scheduler and is already the small size).
- The script's 100 sign-up WORK points do not count as "holding tokens".

## Decisions I need from you
None.

## Recommended next action
Any order, when convenient: H24 (one minute), H25 (about ten minutes; dry run first), H23 (about
ten minutes plus deploy). Merge `engine/phase-b` whenever you like (PR from `engine/phase-b` into
`main`, mark it ready, wait for green, "Create a merge commit"). H13 (founder heartbeat) is
still the most valuable live step.

## Live-test checklist for after you merge
- [ ] Deploy workflow green; `https://api.agentx.social/health` returns 200.
- [ ] The website loads and the feed shows posts.
- [ ] Open a draft PR: CI does not start. Mark it ready: CI starts.
- [ ] After H25: `show` lists no test accounts.
- [ ] After H23: `fly scale show` lists `scheduler` on shared-cpu-1x.
