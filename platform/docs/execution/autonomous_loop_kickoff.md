# Autonomous hand-off — kickoff prompt

Paste the block below into Claude Code to start an unattended hand-off. Edit the two bracketed values first: the phase and its sprints, and the branch name.

Recommended session mode: `opusplan` (plans with Opus, executes with Sonnet). The loop will step up to Fable 5 for high-stakes steps if available.

---

```
You are running an autonomous hand-off under the Autonomous Sprint Loop protocol.

READ FIRST — these govern everything you do:
- platform/docs/execution/autonomous_loop_v1.md   ← the protocol you follow
- platform/docs/strategy/magna_carta_v1.md         ← what AgentX is (constraints)
- platform/docs/strategy/strategic_plan_v2.md      ← phases and sprint sequence
- platform/docs/strategy/state_of_agentx.md        ← current state

HAND-OFF SCOPE
- Phase: [Phase A — Stabilization & Activation]
- Sprints to run, in order: [Sprint 9 — Stabilize; then Sprint 10 if its prompt exists]
- Branch: [phase-a-autonomous]

NON-NEGOTIABLE (from the protocol — do not deviate):
- Work on the branch above. NEVER push to main. NEVER merge. NEVER force-push.
- No irreversible production actions: no prod deploy, no destructive DB commands,
  no secret rotation, no DNS or access-control changes, no data deletion.
- Test your own work LOCALLY (run backend + frontend locally, curl/click against
  localhost). Do NOT test against agentx.social — that is DrJ's post-merge review.
- Secrets never appear in commits or the briefing.
- When genuinely uncertain, or at any stopping condition, STOP and write the briefing.

MODEL DISCIPLINE (match model to cost-of-being-wrong, not difficulty):
- Fable 5 (if available) for high-stakes irreversible steps: router enable/disable
  safety audit, migrations/schema, auth/secrets/.well-known, and failures the
  cheaper models couldn't crack. If Fable 5 is unavailable, use Opus and flag it.
- Opus for judgment: decomposition, code review, hard debugging, the briefing.
- Sonnet for well-specified execution: clear edits, documented commands, tests.
- Haiku for trivial lookups.
Default to Sonnet; escalate deliberately; reserve Fable 5. State the tier used
per step in your running log.

EXECUTE THE LOOP:
0. Kickoff: confirm clean main, pull, create/checkout the branch, check /model
   availability (report whether Fable 5 is selectable), read
   .github/workflows/deploy.yml and record what a merge to main triggers,
   confirm the local stack runs.
1. Decompose the current sprint into ordered steps (model tier + acceptance
   check + reversible/stop-and-ask per step). Write the step list before executing.
2. For each step: select model → execute → test locally → self-correct on failure
   (max 3 tries, escalate tier on last) → commit + push to branch → log it.
3. Sprint close: run full acceptance criteria locally, write the retro to
   docs/sprints/, update state_of_agentx.md, commit + push.
4. Continue to the next sprint on the same branch UNLESS a stopping condition hit.

STOP AND BRIEF when: phase complete, a blocker you can't self-correct, a major
decision the founding docs don't answer, a safety boundary reached, or a scope
surprise. Leave the branch clean, pushed, and buildable — never mid-edit.

BRIEFING: write docs/sprints/briefing_<date>.md per the protocol's format,
commit and push it, then stop and wait for DrJ. Make it readable in five minutes,
lead with the bottom line, be honest about what was and wasn't tested, and state
plainly that the work is on the branch — not on main, not live.

Begin with Phase 0 kickoff. Report the kickoff findings (especially model
availability and what merging will trigger) in your first response, then proceed.
```

---

## Before your first hand-off

Two things worth doing once:

1. **Confirm Fable 5 availability.** Open Claude Code, run `/model`, and see whether Fable 5 / Mythos tier is selectable on your plan. If it is, the high-stakes steps use it. If not, they use Opus 4.8 and the briefing flags it — still safe, just worth knowing.

2. **Confirm the local stack runs.** The loop tests locally because there is no staging. If the backend and frontend can be started on your Mac mini (they should — the repo has run there throughout), the loop can self-test. If there is any friction starting them locally, that is the first thing to sort, because without local testing the loop is committing untested work.

## How to think about your first run

Start with a **single sprint** as the stopping point, not the whole phase — set "Sprints to run" to just Sprint 9. Read the briefing, review the branch, merge, live-test agentx.social. Once you trust how the loop behaves, widen the stopping point to the full phase (Sprint 9 through 12) and hand off longer runs. The protocol supports both; the difference is one line in the kickoff prompt.
