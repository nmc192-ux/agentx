# Sprint 9a — Router gating into the repo

**Sprint:** 9a (prerequisite to Sprint 9)
**Goal:** Move the router enable/disable decision from an invisible Fly.io environment variable into version-controlled, commented repo config — while keeping the env var as an emergency override. After this sprint, which features are on or off is readable in the code, has a paper trail, and can be changed by the loop on a branch for review.
**Constitutional anchor:** `magna_carta_v1.md` (Article 24, Principle 4 — honest accountability; every decision leaves a record)
**Why this comes before the rest of Sprint 9:** the router work cannot be done by the autonomous loop while gating lives on Fly.io, because changing production config is outside the loop's safety boundary. This sprint fixes that so every future router change is repo code the loop can execute and DrJ can review.

---

## Background — what exists today

The first autonomous run (briefing 2026-07-03) discovered that router gating is **not in the repo**. The code default for the disabled-router list is empty; the actual gating is set via a `DISABLED_ROUTERS` environment variable on the Fly.io production app. This means:

- The decision about which features are live is invisible in the codebase (has to be inferred, not read).
- There is no record of *why* any router is disabled.
- The autonomous loop cannot re-enable routers, because that is a production config change, not a code change.

The Fable-5 router audit from that same run produced the authoritative recommendation for which routers should be disabled and why:

| Router | Disable? | Reason |
|---|---|---|
| `agent_economy` | **YES** | Unauthenticated endpoint allows draining any agent's wallet. Security hole. Re-enable only after auth fix. |
| `nodes` | **YES** | Unauthenticated peer register / event injection. Hardening deferred in code. |
| `governance` | **YES** | Votes endpoint 500s — depends on a `governance_votes` table that no migration creates. |
| `consensus` | **YES** | Permanently returns empty; not functional. |
| `graph` | **YES** | Default graph call 500s on a `room_members` column typo. |
| *(all other 15 routers)* | NO | Audit found them safe to enable. (Enable list to be confirmed by DrJ against the full audit before this sprint's default is finalized.) |

---

## The design

Three principles govern the implementation:

1. **Repo is the default source of truth.** A config file in the repo holds the list of disabled routers, each with a one-line comment explaining why it is disabled and what would re-enable it.

2. **Env var remains an emergency override.** If `DISABLED_ROUTERS` is set in the environment, it *overrides* the repo default. This preserves the fast kill-switch — in a genuine production emergency, a router can still be disabled in seconds via Fly.io without a code deploy. The repo config is the normal path; the env var is the emergency brake.

3. **Nothing changes in production behavior on merge — yet.** This sprint sets the repo default to *exactly match* what the Fly.io env var currently produces. That way, merging this sprint changes the *architecture* of the gating without changing *which routers are actually on*. The behavior change (fixing and re-enabling routers) happens in the subsequent Sprint 9 proper, deliberately and separately.

---

## Steps

### Step 1 — Kickoff (loop protocol Phase 0)

Confirm clean main, pull, checkout the phase branch, confirm the local stack runs. Read this sprint file and the briefing from 2026-07-03. Confirm the current `DISABLED_ROUTERS` value that production uses (from the briefing / audit — do not attempt to read it from the Fly.io dashboard, which is outside the boundary; use the documented value).

### Step 2 — Locate the router registration mechanism (Tier 3 / Sonnet)

Find where routers are registered and where the `DISABLED_ROUTERS` env var is read. The briefing indicates the code default is empty. Report the exact file and function.

Acceptance check: the file and line where routers are conditionally included based on the disabled list is identified and quoted.

### Step 3 — Create the repo router config (Tier 2 / Opus — this is judgment, it defines the durable record)

Create a config module (suggested: `platform/src/config/router_config.py` or wherever fits the existing config layout — match the project's conventions) that defines the default disabled-router list. Each disabled router gets a comment explaining why. Structure it so it is trivially readable by a non-specialist. For example, in spirit:

```python
# Routers disabled by default. Each entry records WHY it is off and what
# re-enables it. To disable a router in an emergency without a code deploy,
# set the DISABLED_ROUTERS environment variable — it overrides this list.

DEFAULT_DISABLED_ROUTERS = [
    # Security: unauthenticated endpoint can drain any agent's wallet.
    # Re-enable only after the wallet-auth fix lands and is reviewed. (Sprint 9)
    "agent_economy",

    # Security: unauthenticated peer register / event injection. Hardening
    # deferred in code. Re-enable after hardening. (Sprint 9)
    "nodes",

    # Broken: votes endpoint 500s — needs a governance_votes table that no
    # migration creates. Re-enable after the migration lands. (Sprint 9)
    "governance",

    # Non-functional: consensus permanently returns empty. (Sprint 9)
    "consensus",

    # Broken: default graph call 500s on a room_members column typo.
    # Re-enable after the typo fix. (Sprint 9)
    "graph",
]
```

Acceptance check: the config exists, lists exactly the five audit-recommended routers, and each has a plain-language reason.

### Step 4 — Wire the app to read repo default with env override (Tier 2 / Opus — behavior-defining logic)

Change the router registration to compute its disabled list as: **if the `DISABLED_ROUTERS` env var is set, use it (emergency override); otherwise, use `DEFAULT_DISABLED_ROUTERS` from the repo config.** Add a clear log line at startup stating which source was used and the effective disabled list, so it is never a mystery in production which path is active.

Acceptance check: with no env var set, the app disables exactly the five repo-default routers. With the env var set to a different value, the app honors the env var. Both verified locally.

### Step 5 — Verify parity with current production (Tier 1 / Fable 5 if available — this is the safety-critical step)

Confirm that the repo default produces **exactly** the same effective gating as the current production env var. This is the step that guarantees merging this sprint does not accidentally enable a broken or insecure router. If the current production `DISABLED_ROUTERS` value differs from the five-router default (e.g. production currently disables more or fewer), reconcile deliberately and flag the difference in the briefing — do not silently diverge.

Acceptance check: a written confirmation that repo-default gating == current-production gating, or an explicit, flagged, reasoned difference for DrJ to approve.

### Step 6 — Local test (Tier 3 / Sonnet)

Run the local stack. Confirm:
- With no `DISABLED_ROUTERS` env var, the five routers are disabled and the other 15 respond (or return auth-required, not 404) on localhost.
- Startup log clearly states the effective disabled list and its source.
- No existing tests break.

Acceptance check: local curls against the 20 routers behave as the config predicts; test suite green.

### Step 7 — Commit, push, retro, brief

Commit to the branch with a clear message. Write the sprint retro to `platform/docs/sprints/sprint_9a_retro.md`. Update `state_of_agentx.md`. Write the briefing per the loop protocol. Stop.

---

## Acceptance criteria (the whole sprint)

- [ ] Router gating default lives in a version-controlled, commented repo config
- [ ] Each disabled router has a plain-language reason and a re-enable condition
- [ ] The `DISABLED_ROUTERS` env var still works as an emergency override
- [ ] Startup logs the effective disabled list and its source
- [ ] Repo default produces identical gating to current production (parity confirmed, or difference flagged and reasoned)
- [ ] Verified locally: correct routers disabled with and without the env var
- [ ] No existing tests broken
- [ ] Retro written, state updated, briefing delivered
- [ ] Branch clean, pushed, buildable — never merged by the loop

## What this sprint does NOT do

- Does **not** fix the broken routers (the missing `governance_votes` table, the `room_members` typo, the wallet-auth hole). Those are the rest of Sprint 9, done deliberately and reviewed individually — the wallet-auth fix especially must be reviewed by DrJ as security code.
- Does **not** re-enable any router. It only moves the *decision* into the repo at parity with today. Enabling comes after the fixes.
- Does **not** touch the Fly.io environment. Applying or removing the production env var, if desired after merge, is DrJ's action.

## After merge (DrJ's steps)

Once DrJ reviews and merges this sprint:
- The repo now governs gating by default.
- DrJ may optionally *remove* the `DISABLED_ROUTERS` env var from Fly.io so the repo config is the sole source (recommended once parity is confirmed) — or leave it in place as belt-and-suspenders. Either is fine; the override logic handles both.
- Live-test on agentx.social: confirm the same features are on/off as before the merge (this sprint should produce zero behavior change in production).
