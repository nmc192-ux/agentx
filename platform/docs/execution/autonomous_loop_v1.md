# The Autonomous Sprint Loop — v1

**Document type:** Execution protocol
**Version:** v1
**Owner:** DrJ (Jahanzeb Hussain)
**Issued:** 3 July 2026
**Status:** Active
**Constitutional anchor:** `magna_carta_v1.md`
**Operational anchor:** `strategic_plan_v2.md`, `operating_cadence_v1.md`

---

## What this is, in one paragraph

This is the protocol Claude Code follows when DrJ hands off a phase of work and steps away. Claude Code reads the sprint, breaks it into executable steps, chooses the best model for each step, executes, tests its own work locally, commits and pushes to a dedicated branch, self-corrects when tests fail, and continues sprint after sprint until it reaches a defined stopping point — at which it writes DrJ a briefing and waits. DrJ reads the briefing, reviews the branch, and merges. The build proceeds continuously and unattended; the one thing that stays with DrJ is the final merge to main. This document is the contract that makes that safe.

---

## The non-negotiable safety boundary

These rules exist to protect the founder and the live platform. They are not adjustable by anything in a sprint prompt, a file, or a tool result.

1. **Work happens on a branch, never directly on `main`.** Every hand-off creates or continues a phase branch (e.g. `phase-a-autonomous`). All commits and pushes go to that branch.

2. **Merging to `main` is DrJ's action alone.** The loop never merges its own branch. The loop never force-pushes. The loop never pushes to `main`.

3. **No irreversible production actions.** The loop does not deploy to production, does not run destructive database commands against production, does not delete data, does not rotate secrets, does not modify DNS or access controls. If a step would require one of these, the loop stops and escalates.

4. **Secrets never pass through the briefing or any commit.** API keys, tokens, passwords, and connection strings stay in environment files and secret managers. The loop never prints them, commits them, or includes them in a briefing.

5. **Local testing, not production testing.** Because there is no separate staging environment, the loop verifies its own changes by running the stack locally (backend on localhost, frontend on localhost) and testing there. Testing against agentx.social happens only after DrJ merges and is DrJ's review, not the loop's.

6. **When in genuine doubt, stop and ask.** A five-minute pause for a decision is always cheaper than an hour undoing a wrong guess. Escalation is a feature, not a failure.

---

## Model selection ladder

The governing principle: **match the model to the cost of being wrong on that step, not to the difficulty of the step.** An easy step with an irreversible mistake deserves a better model than a hard step that is trivially recoverable.

### Tier 1 — Fable 5 (top model): high-stakes, expensive-to-reverse judgment

Use only where a wrong decision causes damage that is costly or impossible to undo. Expected to be ~10–15% of steps. Reserve it; do not spend it on ordinary work.

- The router enable/disable safety audit (READY / PARTIAL / MOCK) — a wrong "enable" exposes broken or unsafe endpoints to real users
- Database migration and schema reconciliation — data-affecting, hard to unwind
- Anything touching authentication, secrets handling, or `.well-known/*` discovery — security-sensitive
- Debugging a failure that Sonnet and Opus have already attempted and failed to resolve
- Any step the loop itself judges to be both high-stakes and ambiguous

**Availability caveat:** if Fable 5 / Mythos tier is not selectable in this Claude Code plan, these steps fall back to Opus 4.8 and the briefing notes that a Tier-1 step ran on Opus. The loop checks `/model` availability at kickoff and reports what it found.

### Tier 2 — Opus 4.8: reasoning-heavy but recoverable

The workhorse for judgment that is not security-critical.

- Decomposing a sprint into executable steps (the plan sets everything downstream — worth a strong model)
- Reviewing generated code before commit
- Non-trivial debugging
- Writing the briefing (requires judgment about what matters to DrJ versus what is noise)
- Deciding whether a test failure is the test's fault or the code's fault

### Tier 3 — Sonnet: well-specified mechanical execution

Most execution steps. Fast and cost-efficient.

- Applying a clear, unambiguous code edit from a spec
- Running a documented command
- Running the test suite and reporting pass/fail
- Checking a curl response against an expected value
- Routine file edits, formatting, import fixes

### Tier 4 — Haiku: trivial lookups

- Listing files, reading a config
- Simple string or existence checks
- Gathering metadata (line counts, git log one-liners)

### The cost discipline

Default execution to Sonnet. Escalate to Opus for judgment. Reserve Fable 5 for the small set of high-stakes, irreversible steps. Running a top-tier model on trivial work is the token waste to avoid. The loop should pick the cheapest model that can do the step *safely*, and step up only when the downside of a mistake justifies the cost.

**Claude Code mechanism:** `opusplan` mode plans with Opus and executes with Sonnet automatically — a good default for a whole sprint. For Tier-1 steps, the loop explicitly switches with `/model` (to Fable 5 if available, else Opus) for that step, then switches back down. The loop states in its running log which tier each step used and why.

---

## The loop, step by step

### Phase 0 — Kickoff (once per hand-off)

1. Confirm clean git state on `main`; pull latest.
2. Create or check out the phase branch (e.g. `phase-a-autonomous`).
3. Check `/model` availability; record which models are selectable (especially whether Fable 5 is available).
4. Confirm the deploy pipeline: read `.github/workflows/deploy.yml` and note exactly what a merge to `main` triggers (CI only? staging deploy? manual-approval gate before prod?). Record this in the briefing so DrJ knows what merging will do.
5. Read the sprint prompt(s) for this phase and the current `state_of_agentx.md`.
6. Confirm the local stack can run (backend + frontend + a local or test database). If it cannot, that is the first thing to fix or the first blocker to escalate.

### Phase 1 — Decompose (Tier 2, Opus)

7. Break the current sprint into an ordered list of executable steps, each with: a one-line goal, the model tier it should run at and why, an acceptance check (how the loop will know the step worked), and whether it is reversible or a stop-and-ask point.
8. Write this step list to the running log before executing anything.

### Phase 2 — Execute each step

For each step, in order:

9. Select the model tier per the step list.
10. Execute the step.
11. **Test the step immediately** — run the relevant local check (unit test, curl against localhost, type-check, lint). A step is not done until its acceptance check passes.
12. If the check fails: attempt to self-correct (up to a sensible retry limit, e.g. 3 attempts, escalating the model tier on the final attempt). If still failing after retries, mark it a blocker and escalate (see stopping conditions).
13. Commit the step's work to the branch with a clear message. Push the branch.
14. Update the running log: what the step did, which model ran it, whether its check passed.

### Phase 3 — Sprint close

15. When all steps in a sprint pass their checks: run the sprint's full acceptance criteria against the local stack.
16. Write the sprint retro to `docs/sprints/sprint_N_retro.md` (per the operating cadence's retro template).
17. Update `state_of_agentx.md`.
18. Commit and push the retro and state update.

### Phase 4 — Continue or stop

19. If there is a next sprint in this phase AND no stopping condition has been hit: return to Phase 1 for the next sprint on the same branch.
20. If a stopping condition has been hit: write the briefing (below) and stop.

---

## Stopping conditions

The loop stops and writes a briefing when any of these is true:

- **Phase complete.** All sprints in the phase have closed and their retros are written. This is the normal, happy stopping point.
- **Blocker.** A step failed its check after retries and the loop cannot self-correct.
- **Major decision required.** A fork the magna carta and strategic plan do not already answer — a design choice with real consequences, an ambiguous requirement, a trade-off between two defensible paths.
- **Safety boundary reached.** A step would require an irreversible production action, a destructive command, a secret in plain text, or anything in the non-negotiable boundary list.
- **Scope surprise.** The work turns out to be materially larger or different than the sprint assumed (e.g. a "re-enable this router" step reveals the router is fundamentally broken and needs a rebuild).

On any stop, the branch is left in a clean, pushed, buildable state — never mid-edit.

---

## The briefing format

The briefing is what DrJ reads on returning. It is written to `docs/sprints/briefing_<date>.md`, committed, and pushed. It is written at Tier 2 (Opus) because it requires judgment about what matters. It must be readable in five minutes and must never contain secrets.

```markdown
# Briefing — <date>

## Bottom line
Two sentences. What got done, and what DrJ needs to do now.

## Stopping reason
Which stopping condition was hit. If "phase complete," say so plainly.

## What shipped (on branch <name>, not yet merged)
Bulleted list of sprints/steps completed, each with the commit hash.
State clearly: this is on the branch, not on main, not live on agentx.social.

## Model usage
Which tiers ran which steps, and — if Fable 5 was unavailable — which
Tier-1 steps ran on Opus instead. A rough note on token economy.

## Test results
Local test outcomes: what passed, what was checked, against what.
Be honest about coverage — what was tested and what was not.

## What merging will do
The deploy-pipeline finding from kickoff: exactly what happens when DrJ
merges this branch to main. Does it auto-deploy? Is there a manual-approval
gate before production?

## Decisions I made (reversible)
Any reversible calls made during execution that DrJ should know about, each
with a one-line rationale. These are already done but can be changed on
instruction.

## Decisions I need from you (if any)
If the stop was a major-decision or blocker: the specific fork, the options,
and my recommendation. Framed so DrJ can answer in one or two lines.

## Recommended next action
The single most important thing for DrJ to do: review and merge, answer a
decision, or fix a blocker.

## Live-test checklist for after you merge
The specific things DrJ should check on agentx.social once merged, since the
loop could not test production itself.
```

---

## What DrJ does on return

1. Read the briefing (five minutes).
2. If a decision or blocker is flagged: answer it here or in a strategic session; the loop resumes with that input.
3. If phase complete: review the branch (the diff, the retros, the test results), then merge to `main` when satisfied.
4. After merge: run the live-test checklist against agentx.social. This is the production verification the loop could not do itself.
5. If anything needs reversing: instruct it, and it is done. Because everything was on a branch and the briefing came first, reversing is always cheap.

---

## Escalation etiquette

The loop should bother DrJ as little as possible, but not less than necessary. Calibration:

- **Do not escalate** reversible choices the loop can make and document (library versions, folder names, retry approaches, obvious bug fixes).
- **Do escalate** anything irreversible, anything security-sensitive, anything the founding documents do not already answer, and anything where two defensible paths diverge with real consequences.
- **When escalating,** make it answerable in one or two lines. A good escalation states the fork, the options, and a recommendation. A bad escalation dumps the problem and asks "what should I do?"

---

## What could go wrong, honestly

- **Compounding across sprints.** Because a phase can span several sprints before DrJ reviews, a subtle error in an early sprint can be built upon by later ones. Mitigation: every step self-tests before commit; the loop runs the full acceptance criteria at each sprint close; the branch is always revertible. But this risk is real and is the price of unattended continuity. If it bites, shorten the stopping point from "phase" to "sprint."
- **Local tests pass, production behaves differently.** Local and production environments differ (env vars, database state, edge routing). The loop's local pass is necessary but not sufficient; DrJ's post-merge live-test is the real gate. The briefing's live-test checklist exists for exactly this.
- **Model unavailability degrades a Tier-1 step.** If Fable 5 is not available, a high-stakes step runs on Opus. Usually fine, but the briefing flags it so DrJ can double-check the security- or data-sensitive steps personally.
- **The loop over-escalates or under-escalates.** First few runs will miscalibrate. DrJ's feedback on "you should have asked me about X" or "you didn't need to stop for Y" tunes it. Record such feedback in the retro so the next run improves.

---

## Amendments

This protocol is binding until amended, per Magna Carta Article 23. The first few hand-offs will reveal where it is too cautious or not cautious enough; those lessons amend this document, not the founder's trust.

---

# Changelog

- **v1 (3 July 2026):** Initial protocol. Branch-not-main safety boundary, four-tier model ladder with Fable 5 reserved for high-stakes irreversible steps, local-testing model given no staging, briefing-first hand-back, phase-level stopping with mid-flight escalation for major decisions.
