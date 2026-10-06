# Sprint 13 — Phase A tidy-up

**Drafted by:** the engine, cycle 96 (2026-10-06), from DrJ's note of 6 Oct starting Phase B.
**Branch:** `engine/phase-b` (made from `main` on 6 Oct: all of Phase A plus PRs 13–16).
**Size:** short (five small items), then the engine drafts and plans the Phase B sprints.

## Why

Phase A is merged and live. Five small loose ends cost money or cause noise and should be
closed before Phase B work starts. They are DrJ's list, in DrJ's order.

## Scope

1. **CI runs less often on the engine's draft PR.** Today `ci.yml` runs all six jobs on every
   push to any pull request into `main`, so each engine cycle that pushes to an open draft PR
   spends GitHub Actions minutes. Keep CI exactly as it is for pushes to `main` (the deploy
   pipeline waits on it) and for normal PRs. For a draft PR, run CI only when it is marked
   ready for review, or when someone starts it by hand ("Run workflow").
2. **The scheduler gets its own, smaller machine size.** `platform/fly.toml` has one `[[vm]]`
   (shared-cpu-2x, 512 MB) for both process groups. The scheduler (one Celery worker with
   beat, concurrency 1) needs only shared-cpu-1x, 512 MB. The engine may not edit `fly.toml`,
   so this is a copy-paste HUMAN_ACTION for DrJ (the same for `fly.staging.toml`), plus a
   repo test that checks the per-process sizes once DrJ has made the edit.
3. **A safe script to remove the April test accounts** — `A189_-002`, `A386_-002`,
   `A652_-002`, every `canary-*`, every `sdk-canary-*` and every `Prod Smoke *` agent — with
   a dry run by default. It deletes production data, so it is built on Fable (T1), refuses
   anything outside those exact patterns (founders above all), shows exactly what it would
   remove, writes the audit log, and has tests on real Postgres proving it fails closed.
   DrJ runs it (HUMAN_ACTION).
4. **The Sentry `automaticVercelMonitors` deprecation warning** in the website build
   (`ui/next.config.ts`). Move the option to where `@sentry/nextjs` 10 expects it, keep it
   off, and check that `npm run build` no longer prints the warning.
5. **Commits carry DrJ's GitHub noreply address,** so Vercel preview deployments stop failing
   (Vercel refuses to build commits whose author is not on the Vercel team; the engine's
   commits are authored `engine@agentx.social`). If the engine cannot set its own commit
   identity from inside the repo, write the exact setting for DrJ as a HUMAN_ACTION.

Then: **draft the Phase B sprint specs and plan the first one** (strategic plan v2 §4,
Phase B), doing work that does not need live founder behaviour first.

## Not in scope

No production actions. No change to `deploy.yml`, `publish-sdk.yml`, `fly.toml` or
`fly.staging.toml` by the engine. Nothing that needs the founders switched on (H13 pending).

## Acceptance

- `ci.yml` still runs on every push to `main` and on non-draft PRs; skips draft PRs unless
  marked ready or started by hand; `actionlint` clean; a repo test pins these triggers.
- HUMAN_ACTION with the exact `[[vm]]` blocks for both Fly files; a test that passes once
  they are in (xfail until then, like the release-command guard in Sprint 12).
- Clean-up script: dry run by default; refuses any agent not matching the list; tests on
  real Postgres pass; HUMAN_ACTION written for DrJ with dry run first.
- `npm run build` in `ui/` shows no `automaticVercelMonitors` deprecation warning; UI tests pass.
- Engine commits use DrJ's noreply address, or a HUMAN_ACTION says exactly how to set it.
- Platform suite green; retro written; Phase B sprint specs drafted.
