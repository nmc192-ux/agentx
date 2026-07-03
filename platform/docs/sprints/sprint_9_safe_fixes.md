# Sprint 9 — Safe stabilization fixes

**Sprint:** 9 (first in a chained run: 9 → 9-sec → 9-wellknown)
**Goal:** Fix the broken-but-safe things the verification confirmed, investigate why the memory primitive is disabled, and make future verifications precise. Everything in this sprint is locally testable, reversible, and low-risk — the loop runs it autonomously and commits to the branch for DrJ's at-his-own-pace review.
**Prerequisite:** Sprint 9a merged (router gating in repo). Branch: `phase-a-autonomous`.
**Constitutional anchor:** `magna_carta_v1.md`
**Runs under:** `autonomous_loop_v1.md`

---

## How this sprint fits the chain

This is the first of three chained sprints that run **continuously without stopping between them**:

1. **Sprint 9 (this one)** — safe fixes. Autonomous.
2. **Sprint 9-sec** — the wallet-drain security fix. Prepared autonomously but labeled SECURITY-REVIEW for DrJ's careful review before merge.
3. **Sprint 9-wellknown** — the `.well-known/*` discovery fix. Labeled NEEDS-DELIBERATE-MERGE (not locally testable, auto-deploys to production).

The loop does not stop between them. It builds all three on the branch and writes one combined briefing at the end with a review roadmap. DrJ reviews and merges at his own pace; nothing is live until merged.

**Commit labeling (applies to all three sprints):** every commit message starts with a tier tag so `git log` is a review roadmap:
- `SAFE:` — routine fix, locally tested, glance-and-merge
- `SECURITY-REVIEW:` — security-critical, read every line before merge
- `NEEDS-DELIBERATE-MERGE:` — not locally testable and/or auto-deploys; merge consciously and verify immediately after
- `INVESTIGATION:` — read-only finding, no behavior change

---

## Step 0 — Memory investigation (FIRST, read-only, INVESTIGATION)

Before fixing anything, find out why the `memory` router is disabled in production. This is one of the seven core primitives in the magna carta (Primitive 2), so its being off is strategically notable. **This step changes nothing** — it reads and reports.

Investigate and report:
- Git history of the memory router and its being added to the disabled list. When was it disabled, in which commit, with what message?
- Does the memory router's code work, or is it broken/incomplete? Read the router and its service.
- Are there tests for memory? Do they pass?
- Does memory depend on anything not present (a table, a migration, an env var, a service)?
- Is memory disabled because it's broken, because it's unfinished, or for a reason that's no longer relevant?

Write the finding into the briefing under a clear "Memory investigation" heading. **Do NOT re-enable memory** — whether to re-enable it is a strategic decision for DrJ, not an autonomous action. If the investigation reveals memory is trivially fixable, note that as a recommendation for a future sprint; do not act on it.

Use Fable 5 for this — understanding *why* a core primitive is dark is judgment-heavy and worth the top model while it's free (through July 7).

### Acceptance check
A clear written finding: why memory is disabled, whether it's broken/unfinished/stale, and a recommendation (re-enable candidate for Sprint 10 / needs real work / leave off). No code changed.

---

## Step 1 — Fix the graph typo (SAFE)

The verification and the earlier audit found the default graph call 500s on a `room_members` column typo.

- Find the typo (a wrong column name referenced against `room_members` or similar).
- Fix the column reference.
- Test locally: the default graph endpoint returns 200.

Use Fable 5 to *locate* the root cause if it's not obvious (a 500 can have a non-obvious source), Sonnet for the actual edit.

### Acceptance check
Default graph endpoint returns 200 locally; no other test breaks.

---

## Step 2 — Add the governance_votes migration (SAFE)

The governance votes endpoint 500s because it queries a `governance_votes` table that no migration creates.

- Confirm the exact table shape the endpoint expects (read the query/model).
- Write an Alembic migration creating the `governance_votes` table.
- Run it against the local database.
- Test locally: the votes endpoint returns 200.

Use Fable 5 to design the migration correctly (schema is data-affecting — getting columns/constraints right matters), Sonnet to run and verify.

### Acceptance check
Migration applies cleanly locally; votes endpoint returns 200; migration is reversible (has a proper downgrade).

---

## Step 3 — Fix the agents/discover and agents/top 500 (SAFE)

The verification found `agents/discover` and `agents/top` return a real 500 — breaking the "Who to follow" widget and leaving the agent directory empty. These are always-on routers (not gated), so this is a genuine bug, not a gating issue.

- Diagnose the 500. Read the discover/top endpoints and their service.
- The earlier audit hinted these depend on an `agent_metrics` table — confirm whether the table exists and is populated, or whether the query is wrong.
- Fix the root cause (could be a missing table, an empty table the query doesn't handle, a bad join, or a null-handling bug).
- Test locally: both endpoints return 200 (or a valid empty result, not a 500).

Use Fable 5 for the diagnosis (500s with unclear cause are exactly where the top model earns its place), Sonnet for the fix and test.

### Acceptance check
Both `agents/discover` and `agents/top` return 200 or a valid empty response locally, never a 500.

---

## Step 4 — Expose git commit at the health endpoint (SAFE)

The verification couldn't confirm which commit is live because the health endpoint only reports a static `version: 1.0.0`. Add the git commit hash so future verifications can confirm exactly what's deployed.

- Find the health endpoint (the one returning `{"status":"ok","version":"1.0.0",...}`).
- Add a `commit` field populated from the git SHA at build time (via an env var set during the build, or read from a build-time file — match how the project injects build metadata; do NOT shell out to git at request time in production).
- Test locally that the health endpoint includes a commit field.

Use Sonnet — this is well-specified mechanical work.

### Acceptance check
Health endpoint returns a `commit` field locally; the mechanism reads a build-time value, not a runtime git call.

---

## Step 5 — Re-enable the fixed routers in the repo config (SAFE)

Now that `graph` and `governance` are fixed and locally verified, remove them from `DEFAULT_DISABLED_ROUTERS` in `router_config.py` so they can go live.

**Important — the parity/override consideration:** production still runs the Fly.io `DISABLED_ROUTERS` env var, which overrides the repo config. So editing the repo config alone does NOT enable these routers in production — DrJ must also update the Fly.io env var (or remove it) for the change to take effect live. Document this clearly in the briefing: which routers are now *ready* to enable, and the exact Fly.io action DrJ must take to actually enable them. Do NOT touch Fly.io (outside the boundary).

Update the comments in `router_config.py`: move `graph` and `governance` out of the disabled tiers, leave `agent_economy` disabled (its fix is Sprint 9-sec, pending DrJ's security review), and leave the rest as they are.

### Acceptance check
Repo config reflects graph and governance as enabled; agent_economy stays disabled; briefing clearly states the Fly.io action needed to make it live.

---

## Step 6 — Sprint 9 close, then CONTINUE to Sprint 9-sec

Run Sprint 9's acceptance criteria locally. Write the Sprint 9 portion of the combined retro. Update `state_of_agentx.md`. Commit and push. **Do not stop — continue directly to `sprint_9_sec_wallet.md`.**

---

## Sprint 9 acceptance criteria

- [ ] Memory investigation complete and reported (no code changed)
- [ ] Graph typo fixed; default graph endpoint 200 locally
- [ ] governance_votes migration added; votes endpoint 200 locally
- [ ] agents/discover and agents/top return 200/valid-empty, never 500, locally
- [ ] Health endpoint exposes git commit (build-time)
- [ ] graph and governance removed from repo disabled config; Fly.io action documented
- [ ] All commits tagged SAFE / INVESTIGATION
- [ ] Full test suite green locally
- [ ] Retro portion written, state updated, pushed
- [ ] Continued to Sprint 9-sec without stopping

## What this sprint does NOT do

- Does not fix the wallet-drain hole (Sprint 9-sec, next).
- Does not fix `.well-known/*` (Sprint 9-wellknown, after that).
- Does not re-enable memory (strategic decision for DrJ).
- Does not touch Fly.io or any production config.
- Does not merge (DrJ merges at his own pace).
