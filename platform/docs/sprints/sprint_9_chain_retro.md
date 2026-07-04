# Sprint 9 chain (9 → 9-sec → 9-wellknown) — Retro

**Sprints:** 9 (safe fixes), 9-sec (wallet security), 9-wellknown (A2A discovery)
**Dates:** 2026-07-04 (single chained autonomous run)
**Merged in:** *not yet merged* — on branch `phase-a-autonomous`. Commits `e9ef862`, `15a93f8`, `5c1ca8f`, `cb12189`, `2a28236`, `73c6fe5`, `2cfa87a`. Awaiting DrJ review. Full briefing: `briefing_2026-07-04_chain.md`.

## What was intended
Fix the broken-but-safe things the live verification found (graph typo, governance-votes table, `agents/discover`/`top` 500), investigate why the `memory` primitive is dark, expose the git commit at `/health`, then re-enable the fixed routers in repo config — all autonomously (Sprint 9). Then, isolated for careful review, close the unauthenticated wallet-drain in `agent_economy` (Sprint 9-sec). Then prepare the `.well-known` edge-routing fix that can only be tested in production (Sprint 9-wellknown). One combined briefing at the end; nothing merged.

## What actually shipped
All the code, on the branch: the graph column/table typos fixed; a deploy-safe `governance_votes` migration (039); a discovery-table reconciliation migration (040); the `/health` commit field; the wallet-drain fix (auth + identity-from-token, with regression tests); the `.well-known` Vercel rewrite. **Plus two unplanned root-cause repairs that the sprint could not have anticipated:** the Alembic migration chain itself was broken (migrations 035 and 037 had never applied on a real Postgres), and fixing it was a prerequisite for testing anything DB-dependent. Full suite green throughout (2033 passed). No router was enabled and nothing touched production.

## What we learned
The headline lesson, worth more than any single fix: **the platform's schema story is not what the version numbers claim.** Migration 035 (immutable-generated-column bug) and 037 (asyncpg multi-statement bug) meant `alembic upgrade head` had never succeeded past 033 — so production was *stamped* at `037` rather than *migrated* to it, leaving it missing ~two-thirds of the post-baseline tables (`rooms`, `proposals`, `stakes`, `contracts`, `agent_capabilities_registry`, …). That single fact explains a chain of previously-mysterious symptoms: `agents/discover` 500 in prod but not locally; graph 500 even after the code fix; governance needing tables that "exist" per alembic but not in reality. We also learned `memory` was never broken — it was collateral damage of a 2026-04-23 blanket scope cut. And we learned (again) that local green ≠ production green: three of these bugs only manifest against the divergent prod DB or the prod edge.

## What we deferred
- **Router enablement (Sprint 9 Step 5):** deliberately NOT done. graph/governance are code-fixed but would still 500 in prod (missing tables), so they stay disabled with updated comments — a documented deviation from the spec, driven by the divergence discovery.
- **Production schema reconciliation:** the big one. Prod needs a deliberate, snapshot-first reconciliation before any Tier-B router can go live. Data-affecting and outside the loop's boundary — a decision for DrJ.
- **A second wallet gap:** `tokens.py` `transfer_tokens`/`stake_tokens` authenticate but don't check wallet ownership against the caller. Flagged, not fixed (kept the security diff minimal).
- **`consensus`:** still non-functional (reads a `votes` table nothing writes); coupled to governance, not addressed.

## What changed strategically
The Phase-A sequencing assumed the platform was "shipped but gated" — flip the gate and features come alive. The divergence finding complicates that: **enabling a router in prod is now gated on schema reconciliation, not just on a code fix and an env-var flip.** This doesn't break the plan but inserts a prerequisite. Worth a Plan v2.x note: "Phase A includes a production-schema reconciliation before router enablement." No magna carta implication. The migration-chain repair also means CI should actually run `alembic upgrade head` on a scratch DB (it evidently wasn't catching this) — a cheap guardrail worth adding.

## Next
Two forks for DrJ, in order: (1) review and merge the **wallet security fix** (`73c6fe5`) — the one urgent, self-contained item — then verify and enable it; (2) decide on a **production-schema reconciliation** task, since it blocks the rest of router enablement. After those, the `.well-known` deliberate merge unlocks external discovery, and `memory` becomes a clean re-enable candidate. The safe SAFE-tagged commits can merge at DrJ's pace once a pre-migration DB snapshot is taken.
