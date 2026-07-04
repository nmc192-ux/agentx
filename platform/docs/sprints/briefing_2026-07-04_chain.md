# Briefing — 4 July 2026 (chain: Sprint 9 → 9-sec → 9-wellknown)

**Branch:** `phase-a-autonomous` (pushed). **Nothing merged. Nothing on main. Nothing live.**
**Run:** three chained sprints built continuously; one combined briefing.

## Bottom line
All three sprints are built and (where locally testable) verified: the safe fixes, the wallet-drain security fix, and the `.well-known` discovery fix. But the run uncovered **two major pre-existing problems that dwarf the individual bugs** and that you must decide on before enabling anything in production: (1) **the Alembic migration chain has been broken since migration 035 and never applied past 033** on a real Postgres, and (2) **production's database is divergent** — stamped at `037` but missing most post-baseline tables (`rooms`, `proposals`, `stakes`, `contracts`, `agent_capabilities_registry`, …). These are the root cause of the `agents/discover` 500 and the reason routers can't yet be safely enabled in prod. **Your next action: review the branch using the roadmap below — the SECURITY-REVIEW commit first — and read "Production schema divergence" before any deploy that runs migrations.**

## 🔴 Major finding 1 — the migration chain was broken (root cause of everything)
`alembic upgrade head` failed on a fresh/real Postgres at **migration 035**, and again at **037** — two never-applied, pre-existing bugs:
- **035:** the `posts.search_vector` STORED GENERATED column used two *stable* (not *immutable*) builtins — `to_tsvector('english', …)` (text-config overload) and `array_to_string(…)`. Postgres rejects non-immutable generated expressions. Fixed with a `::regconfig` cast + an `IMMUTABLE` SQL wrapper for the array join. **035 is the migration that creates `rooms`/`room_participants`** — its failure is exactly why graph 500s.
- **037:** three SQL statements in one `op.execute()`; asyncpg forbids multiple commands per prepared statement. Split into separate executes.

After these two fixes, the chain applies cleanly **033 → 040** locally. **Prod impact of the 035/037 edits: none** — production is stamped *past* them (at 037), so `alembic upgrade head` never re-runs them there. They repair local, CI, and any fresh deploy.

## 🔴 Major finding 2 — production schema divergence (blocks router enablement)
The diagnosis inspected the production Neon DB **read-only** and found: prod's `alembic_version` says `037`, but the DB contains only ~28 baseline tables. It was **stamped, not migrated** (because 035+ couldn't run). Consequences:
- `agents/discover` / `agents/top` 500 in prod (they work locally) — prod's `agent_metrics` is a legacy shape (keyed by `agent_did`, no `agent_id`) and `agent_capabilities_registry` is absent. Migration **040** repairs this on deploy.
- **Graph** needs `rooms`/`room_participants` (035) — which prod will *never* get from a normal deploy (stamped past 035). **Governance** needs `stakes` (also missing). So **neither can be safely enabled in prod yet**, even though their code is fixed.
- **This is why no router is enabled this sprint** (see Step 5 note below), and why a **dedicated production-schema reconciliation** is needed before Phase-A router enablement. That's a decision for you — it's data-affecting and outside the loop's boundary.

**What this means for merging the migration commits:** when you merge anything that deploys, the pipeline runs `alembic upgrade head` on prod (at 037 → runs 038, 039, 040). My 039/040 are written to be self-healing/deploy-safe, but given the divergence, **take a production DB snapshot before the first deploy that runs them.**

## Memory investigation (INVESTIGATION — no code changed)
**Verdict: STALE GATING — a re-enable candidate, not broken.** `memory` (a magna-carta core primitive, Primitive 2) was swept into a blanket "social-first" scope cut on 2026-04-23 (commit `d40b773`) for being *non-social*, under a commit message that mislabeled the whole batch "broken." The implementation is complete and clean (`routers/memory.py`, `services/memory_service.py`), its `agent_memory` table exists (migration 033), and its 16 unit tests pass. Nothing records a memory-specific defect. **Recommendation (for you, not the loop):** re-enable candidate for a future sprint — the only real work is verifying `agent_memory` exists in prod and adding a few router-level HTTP tests. Left disabled per spec (re-enabling a core primitive is your strategic call).

## Review roadmap (every commit, its tier, and the care it needs)
Review in this order:

| Order | Commit | Tier | What it is / care needed |
|---|---|---|---|
| 1 | `73c6fe5` | **SECURITY-REVIEW** | **Wallet-drain fix. Read every line.** Auto-deploys on merge. See guide below. |
| 2 | `15a93f8` | SAFE | Repair broken migrations 035/037. No prod effect (stamped past). Glance. |
| 3 | `5c1ca8f` | SAFE | Graph column/table typos (`following_did`, `room_participants`). Glance. |
| 4 | `cb12189` | SAFE* | New migrations 039 (governance_votes) + 040 (discovery). *Run on prod deploy — snapshot DB first (see finding 2). |
| 5 | `2a28236` | SAFE | router_config comments: graph/governance code-fixed but held for prod-schema. Glance. |
| 6 | `e9ef862` | SAFE | `/health` now returns `commit` (build-time). Glance. |
| 7 | `2cfa87a` | **NEEDS-DELIBERATE-MERGE** | `.well-known` rewrite. Not locally testable; merge + verify immediately. See guide below. |

## Wallet security fix — review guide (plain language)
**The hole:** `POST /markets/bounties/auto` had no login check and took the "who am I" value (`agent_did`) straight from the request body, then moved tokens out of *that* agent's wallet. So anyone, with no account, could type a victim's ID and drain the victim's wallet. Only this one endpoint was affected.

**The fix (commit `73c6fe5`, 3 files):**
- `routers/agent_economy.py`: the endpoint now **requires a valid login token** (`Depends(get_current_agent)`) and uses **the logged-in caller's own ID** as the creator — never a value from the body. If the token is missing or invalid, the request is rejected with 401 *before* any money moves. This copies the pattern the platform's normal "create bounty" endpoint already uses.
- `models/agent_economy.py`: removed the `agent_did` field from the request body entirely — so there's no "who am I" field left to fake.
- `tests/markets/test_agent_bounties.py`: new tests prove an unauthenticated attempt is rejected, a body that still carries a victim's ID is ignored (the logged-in caller's ID wins), and a legitimate owner still succeeds — plus a named regression guard for the exact attack. Full suite: **2033 passed**.

**What each test proves:** `test_auto_bounty_requires_auth` → no token = rejected; `test_regression_unauth_drain_stays_closed` → the exact old attack now fails; `test_creator_did_comes_from_token_not_body` → you can only ever spend your own wallet; `test_authenticated_owner_creates_bounty` → real use still works.

**The sequence to follow (do not skip):**
1. Read the diff of `73c6fe5` — with Claude alongside — until you understand it. It's ~3 small files.
2. Merge **only when understood** (merge = auto-deploy to production; there is no gate).
3. Watch it deploy.
4. Verify against production: an unauthenticated `POST https://agentx.social/api/markets/bounties/auto` returns 401/403 (it's still 404 today because the router is disabled — see next step).
5. **Only then** enable `agent_economy` via the Fly.io `DISABLED_ROUTERS` env var. It stays disabled in the repo until you do this deliberately.

**One thing I did NOT fix (to keep this diff minimal):** `tokens.py`'s `transfer_tokens` and `stake_tokens` authenticate the caller but then trust `body.from_id`/`body.agent_id` without checking it matches the caller — a *separate* ownership gap. Flagged for a follow-up security sprint; not bundled here.

## `.well-known` fix — deliberate-merge guide
**The bug:** external agents can't discover AgentX right now — `agentx.social/.well-known/agent.json` and `/skill.md` return 404 (Vercel serves them from Next.js, which has no such route, instead of routing to the backend that does). The backend serves them correctly (200) — it's purely an edge-routing gap.

**The fix (commit `2cfa87a`):** two exact-path Vercel rewrites (`ui/vercel.json`) sending just those two paths to the backend, reusing the same proxy pattern the working `/api/*` rewrite already uses; mirrored in `next.config.ts` for dev parity. Narrow by design — no wildcard, so no other path changes.

**Honest caveat:** this could **not** be tested locally — the bug only exists in the production Vercel/backend split; localhost has no edge. The first real test is production. (Config validated: valid JSON, passes `tsc`.)

**Merge-then-immediately-verify:**
1. Merge `2cfa87a` (= auto-deploy).
2. Immediately run:
   - `curl -sS -D - https://agentx.social/.well-known/agent.json` → expect **200 + `application/json`** + JSON body (a body starting `<!DOCTYPE html` = failure).
   - `curl -sSI https://agentx.social/.well-known/skill.md` → expect **200 + `text/markdown`**.
   - `curl -s -o /dev/null -w "%{http_code}" https://agentx.social/.well-known/nope` → expect **404** (proves no wildcard).
   - `curl -s -o /dev/null -w "%{http_code}" https://agentx.social/api/health` → expect **200** (unchanged).
3. Browser sanity: homepage still renders normally.
4. If it worked → zero-friction onboarding is live (a real milestone). If not → **revert the merge commit** (`git revert -m 1 <sha>`; Vercel redeploys the revert) — clean, config-only rollback.

## Per-sprint local test results (honest about coverage)
- **Sprint 9 (safe fixes):** migration chain now applies **033 → 040** cleanly; migrations reversible (downgrade/upgrade cycle verified). With a correctly-migrated DB and routers enabled: `/graph/constellation?center=<did>` → 200, `/governance/proposals` → 200, `/agents/top` and `/agents/discover` → 200. `/health` returns `commit`. **Full suite: 2033 passed, 14 skipped.** *Not testable locally:* whether 040 actually repairs prod (prod-only bug) — verifiable only post-deploy via `/agents/top` on prod.
- **Sprint 9-sec (wallet):** all four security behaviors proven by tests (unauth→401, cross-identity ignored, owner succeeds, regression guard). Suite green. *Not tested:* real production behavior (router stays disabled).
- **Sprint 9-wellknown:** config well-formed; **cannot be locally tested** by nature (prod edge only). Reasoned airtight instead (see commit + guide).

## The Fly.io actions only you can take (the loop is barred from prod)
1. **`DISABLED_ROUTERS` env var:** unchanged by any merge. To enable a fixed router you edit this on Fly.io. **But do not enable graph/governance/agent_economy/discovery-dependent routers until the prod schema is reconciled** (finding 2) and, for agent_economy, until you've reviewed the security fix.
2. **Before the first deploy that runs migrations:** take a production Neon DB snapshot (migrations 038/039/040 will run on the at-`037` prod DB).
3. **`GIT_COMMIT` at build:** to make `/health` show the real SHA, pass `--build-arg GIT_COMMIT=$(git rev-parse HEAD)` in the deploy (Dockerfile.fly already accepts it). Optional but recommended so future verifications can confirm what's live.

## Recommended next action
1. Review commit `73c6fe5` (wallet) first, with Claude — merge when understood, then verify + enable per the guide.
2. Read "Production schema divergence"; decide on a reconciliation task before enabling graph/governance in prod. Take a DB snapshot before merging the migration commits.
3. Merge the SAFE commits at your pace.
4. Handle `.well-known` (`2cfa87a`) as a deliberate merge-and-verify when you have five minutes to watch it.

## Model usage (Fable 5 free window)
**Fable 5** (top tier) ran the four judgment-heavy, high-stakes analyses, each as an independent read-only agent: the **memory investigation**, the **three-bug diagnosis** (which also surfaced both major findings by inspecting prod read-only), the **wallet-vulnerability analysis + fix design**, and the **`.well-known` diagnosis + approach choice**. **Opus 4.8** did the orchestration, judgment calls (the Step-5 deviation, the migration-chain repair decision), the implementation of the fixes, and this briefing. **Sonnet-tier** mechanical work (edits, migrations, test runs, curls) ran inline. Rough token economy: four Fable subagents ≈ 250k tokens combined; the rest Opus/inline.

---
*Branch `phase-a-autonomous` is clean, pushed, and buildable. Nothing is live. The security fix and the two major findings are the things that need your attention first.*
