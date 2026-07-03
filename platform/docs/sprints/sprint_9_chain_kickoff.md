# Chained hand-off — Sprints 9, 9-sec, 9-wellknown

Paste the block below into a fresh Claude Code window. Requires the `phase-a-autonomous` branch (exists from Sprint 9a). Fable 5 free through July 7 — use it for the judgment-heavy steps.

The loop runs all three sprints **continuously without stopping**, labels every commit by care-level, and writes one combined briefing at the end. DrJ reviews and merges at his own pace; nothing is live until merged.

---

```
You are running a chained autonomous hand-off under the Autonomous Sprint Loop protocol.
Run THREE sprints continuously, without stopping between them, then write ONE combined
briefing and stop.

READ FIRST:
- platform/docs/execution/autonomous_loop_v1.md   ← the protocol you follow
- platform/docs/strategy/magna_carta_v1.md         ← what AgentX is (constraints)
- platform/docs/strategy/state_of_agentx.md        ← current state
- platform/docs/verification/verify_2026-07-04.md  ← the live verification that found the bugs
- platform/docs/sprints/sprint_9_safe_fixes.md     ← sprint 1 of 3
- platform/docs/sprints/sprint_9_sec_wallet.md     ← sprint 2 of 3 (SECURITY)
- platform/docs/sprints/sprint_9_wellknown.md      ← sprint 3 of 3 (deliberate merge)

CHAIN
- Branch: phase-a-autonomous (continue on it)
- Run in order: Sprint 9 (safe fixes) → Sprint 9-sec (wallet security) → Sprint 9-wellknown
- DO NOT stop between sprints. Build all three on the branch.
- Write ONE combined briefing at the very end, then stop.

NON-NEGOTIABLE:
- Work on the branch. NEVER push to main. NEVER merge. NEVER force-push.
- No production actions: no prod deploy, no Fly.io changes, no destructive DB commands,
  no secret handling in commits/briefing. Test locally.
- The git remote URL contains an embedded token — never echo, commit, or brief it.
- STOP only at: the end of the chain (combined briefing), a blocker you can't self-correct,
  a major decision the founding docs don't answer, or a safety boundary reached.

COMMIT LABELING (critical — this is DrJ's review roadmap):
Every commit message starts with a tier tag:
- SAFE: — routine fix, locally tested, glance-and-merge
- SECURITY-REVIEW: — read every line before merge (the wallet fix)
- NEEDS-DELIBERATE-MERGE: — not locally testable / auto-deploys; merge consciously, verify after
- INVESTIGATION: — read-only finding, no behavior change

MODEL DISCIPLINE (Fable 5 free through July 7 — use generously for judgment):
- Fable 5 for: the memory investigation, diagnosing the 500s, designing the governance
  migration, the ENTIRE wallet security fix (understanding + fix + test design), and the
  .well-known diagnosis and approach choice. These are the judgment-heavy, high-stakes steps.
- Sonnet for: mechanical edits, running migrations, running the test suite, curl checks.
- Haiku for: trivial lookups.
Note in the briefing which steps used Fable 5.

SPECIAL CARE — Sprint 9-sec (wallet security):
This fix auto-deploys to production the moment DrJ merges (no gate). The branch review is
the ONLY checkpoint. So the fix must be MINIMAL, match the platform's existing auth pattern,
fail closed, and be explained plainly enough that DrJ can understand it before approving.
A wrong auth fix that hides the hole is worse than the known hole. Include a plain-language
"review guide" in the briefing. Do NOT re-enable agent_economy — it stays disabled until
DrJ reviews, merges, and enables it deliberately.

SPECIAL CARE — Sprint 9-wellknown:
This cannot be tested locally (the bug only exists in the production Vercel/backend edge
split) and the fix auto-deploys on merge. Prepare and document thoroughly, reason explicitly
about failure modes since there's no local test, and write the exact post-merge verification
DrJ runs immediately after merging.

EXECUTE:
0. Kickoff: confirm clean main, pull, continue branch phase-a-autonomous, confirm local
   stack runs. Report kickoff findings.
1. Sprint 9 — start with the memory INVESTIGATION (read-only, report it), then the safe
   fixes (graph typo, governance migration, discover/top 500, health commit field), then
   re-enable graph+governance in repo config (documenting the Fly.io action DrJ must take).
2. Continue to Sprint 9-sec — the wallet security fix, prepared and locally tested, labeled
   SECURITY-REVIEW, agent_economy left disabled.
3. Continue to Sprint 9-wellknown — the discovery fix, prepared and documented, labeled
   NEEDS-DELIBERATE-MERGE.
4. Write ONE combined briefing at platform/docs/sprints/briefing_<date>_chain.md covering all
   three sprints, with:
   - Bottom line
   - Memory investigation finding
   - A REVIEW ROADMAP: every commit listed with its tier tag and what care it needs
   - The wallet security "review guide" (plain language)
   - The .well-known "deliberate merge guide"
   - Per-sprint local test results (honest about what could and couldn't be tested)
   - The Fly.io actions DrJ must take to actually enable the fixed routers
   - Recommended review order
   Commit and push it. Then STOP.

For each step: select model → execute → test locally → self-correct (max 3 tries, escalate
tier) → commit with the right tier tag → push → log. Update state_of_agentx.md and write
per-sprint retros as you close each sprint. Leave the branch clean, pushed, buildable.

Begin with Phase 0 kickoff. Report findings, then run the chain.
```

---

## What DrJ does after the chain finishes

The loop builds all three sprints and hands back one combined briefing with a review roadmap. DrJ then, at his own pace:

1. Reads the **memory investigation** finding — and we decide together (strategic) whether re-enabling memory is Sprint 10 work.
2. Reviews and merges the **SAFE** commits freely — routine fixes, glance and merge.
3. Sits down with the **SECURITY-REVIEW** wallet fix — with Claude reading it alongside — and merges only when understood. Then verifies against production, then enables the router via Fly.io.
4. Handles the **NEEDS-DELIBERATE-MERGE** `.well-known` fix consciously — merge, then immediately verify against production, since it couldn't be locally tested.
5. Runs a **post-deploy verification** after the merges to confirm the live site is healthy.

Nothing is live until DrJ merges. The loop never gets ahead of his merges — only ahead of his attention, which is exactly the point.
