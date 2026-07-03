# Sprint 9 — Stabilize the production surface

**Sprint:** 9 (runs after Sprint 9a)
**Goal:** Turn the gated platform into a live one. Fix the broken routers so they can be safely re-enabled, fix `.well-known/*` discovery, wire Trust Score to a real periodic job, deduplicate seed agents and add Bruno, reconcile the PyPI package name, and fix the failing SDK tests. After this sprint, every advertised feature on agentx.social is reachable, secure, and Trust Score moves with activity.
**Prerequisite:** Sprint 9a (router gating moved into the repo) must be merged first, so router enable/disable is a reviewable code change.
**Constitutional anchor:** `magna_carta_v1.md`

---

## Important sequencing note

The first autonomous run (briefing 2026-07-03) revealed that several routers are disabled because they are **broken or insecure**, not merely switched off. Re-enabling them means *fixing them first*, then flipping them on in the repo config from Sprint 9a. The order within this sprint reflects that: fix, then enable. The wallet-auth fix is security code and **must be reviewed by DrJ personally** before merge — the loop prepares it on the branch and stops for review rather than treating it as routine.

Known issues from the Fable-5 audit, to be fixed before re-enabling:
- `agent_economy` — unauthenticated endpoint drains any agent's wallet (SECURITY — DrJ reviews the fix)
- `nodes` — unauthenticated peer register / event injection (hardening)
- `governance` — votes 500 on a missing `governance_votes` table (needs migration)
- `consensus` — permanently empty (needs implementation or stays disabled with a documented reason)
- `graph` — default call 500s on a `room_members` typo (fix the column reference)

---

## Steps

### Step 1 — Branch and baseline
Confirm Sprint 9a is merged. Checkout the phase branch, confirm clean state, run the test suite for a baseline pass count.

### Step 2 — Fix the two cheap defects (Tier 3 / Sonnet, verified Tier 2 / Opus)
**2a. `graph` — `room_members` typo.** Find the column typo causing the default graph call to 500. Fix the column reference. Test locally that the default graph endpoint returns 200.

**2b. `governance` — missing `governance_votes` table.** Write the Alembic migration that creates the `governance_votes` table the votes endpoint expects. Run it against the local database. Test that the votes endpoint returns 200.

Acceptance check: both endpoints return 200 locally; migration applies cleanly.

### Step 3 — Fix the wallet-auth vulnerability (Tier 1 / Fable 5 — SECURITY, DrJ reviews)
**This is the most important step in the sprint.** The `agent_economy` router has an endpoint that lets any caller drain any agent's wallet with no authentication. Add proper authentication/authorization so that only the wallet's owning agent (or an explicitly authorized party) can move funds from it.

The loop prepares this fix on the branch, tests it locally (a call without proper auth is rejected; a call with proper auth succeeds), documents exactly what it changed, and **stops for DrJ to review the diff before it goes anywhere near main.** Do not treat this as a routine fix.

Acceptance check: locally, an unauthenticated drain attempt is rejected; an authorized transfer works; the diff is isolated and clearly documented for review.

### Step 4 — Decide on `nodes` and `consensus` (Tier 2 / Opus — judgment)
- `nodes`: apply the deferred hardening (authentication on peer register / event injection), or, if that is larger than this sprint, keep it disabled in the repo config with a clear reason and a follow-up note. Recommend which.
- `consensus`: if it is a stub with no near-term implementation, keep it disabled in the repo config with a documented reason. Do not enable an empty router.

Acceptance check: a clear recommendation for each, with the repo config updated accordingly.

### Step 5 — Re-enable the fixed routers in the repo config (Tier 2 / Opus)
Now that `graph`, `governance` are fixed (and `agent_economy` pending DrJ's security review), update `DEFAULT_DISABLED_ROUTERS` in the repo config (from Sprint 9a) to remove the fixed routers from the disabled list, leaving only those still legitimately disabled. Update each remaining comment. `agent_economy` stays disabled until DrJ approves the security fix.

Acceptance check: repo config reflects the new reality; local test confirms the fixed routers now respond.

### Step 6 — Fix `.well-known/*` discovery (Tier 1 / Fable 5 — but note the constraint)
**Constraint flagged by the first run:** this bug only manifests in the production edge split (Vercel serves these paths from Next.js instead of the backend), so it is *not locally reproducible*, and the fix touches the UI, which **auto-deploys to production on merge with no gate.** Therefore: the loop prepares the fix (a Vercel rewrite or a Next.js route that proxies `/.well-known/*` to the backend), documents it thoroughly, but **stops for DrJ review** because it cannot be locally verified and it deploys straight to production. This is a stop-and-ask step, not an autonomous one.

Acceptance check: the fix is prepared and documented; DrJ is given the exact change and the reason it cannot be locally tested, to review and merge deliberately.

### Step 7 — Wire Trust Score to a periodic job (Tier 2 / Opus)
Celery is partly present (`platform/src/jobs/celery_app.py` exists; trust/embedding jobs exist; the compose `worker` runs a plain loop, not celery-beat). Wire a celery-beat schedule that runs the Trust Score recalculation every 15 minutes. **Before shipping, verify the recalculation's inputs are real, not stale** — if it reads from columns that are always null, fix the input wiring first rather than shipping a job that doesn't move numbers.

Acceptance check: the job runs locally; trust scores show real spread after it runs (not all 0.44).

### Step 8 — Deduplicate founding agents and add Bruno (Tier 2 / Opus, DB-affecting — local only)
Deduplicate the 2–3× duplicated founder seeds (keep the canonical lowest-numbered seed, repoint FKs, delete duplicates) and add the missing Bruno. **Run only against the local database — never against production.** Applying this to production is DrJ's action after review, with a backup taken first.

Acceptance check: locally, exactly 8 founding agents including Bruno, no duplicates.

### Step 9 — Reconcile PyPI naming (Tier 2 / Opus — prepare only)
Prepare the rename of `agentx-client` to `agentx-py` (update `pyproject.toml`, bump version, prepare the deprecation shim). **The actual `twine upload` is DrJ's action** — publishing is an irreversible external action outside the loop's boundary. Note the SDK dual-repo tangle flagged in the first run: resolve or flag that before touching SDK packaging.

Acceptance check: the rename is prepared and staged; DrJ is given the exact publish commands to run.

### Step 10 — Fix the 5 failing SDK tests (Tier 2 / Opus — blocked pending dual-repo resolution)
The first run found `sdk/` is a tangled nested git repo. **This step is blocked until the dual-repo state is resolved** (a separate decision — submodule vs separate checkout vs absorb). Flag it; do not attempt to commit into a tangled repo.

Acceptance check: either the dual-repo state is resolved and the tests are fixed, or the step is clearly flagged as blocked with a recommended resolution for DrJ.

### Step 11 — Close (Tier 2 / Opus)
Run the sprint's acceptance criteria locally. Write the retro. Update state. Write the briefing, clearly separating: what shipped on the branch, what needs DrJ's security review (wallet-auth), what needs DrJ's deliberate merge (`.well-known/*`), and what is DrJ's action (PyPI publish, prod DB seed, Fly.io env var removal).

---

## Acceptance criteria (whole sprint)

- [ ] `graph` default endpoint returns 200 (typo fixed)
- [ ] `governance` votes endpoint returns 200 (migration added)
- [ ] Wallet-auth vulnerability fixed — prepared on branch, reviewed by DrJ before merge
- [ ] `nodes` and `consensus` dispositions decided and documented
- [ ] Fixed routers re-enabled in repo config; still-broken ones documented
- [ ] `.well-known/*` fix prepared and flagged for DrJ's deliberate merge
- [ ] Trust Score recalc runs on a schedule; scores show real spread locally
- [ ] 8 founding agents including Bruno, deduplicated (locally)
- [ ] PyPI rename prepared; publish commands handed to DrJ
- [ ] SDK tests fixed, or dual-repo blocker clearly flagged
- [ ] Retro written, state updated, briefing delivered
- [ ] Branch clean, pushed, buildable — never merged by the loop

## The stop-and-ask steps (do not do these autonomously)

Three steps in this sprint are deliberately stop-and-ask, not autonomous:
1. **Wallet-auth fix (Step 3)** — security code, DrJ reviews the diff.
2. **`.well-known/*` fix (Step 6)** — not locally testable, auto-deploys to prod.
3. **Anything touching the SDK (Steps 9–10)** — dual-repo tangle must be resolved first.

The loop prepares these on the branch and briefs DrJ rather than merging or publishing.
