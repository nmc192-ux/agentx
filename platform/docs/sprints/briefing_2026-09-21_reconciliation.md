# Briefing — 21 September 2026: production schema reconciliation

## Bottom line
Production's database has been stuck since April: `alembic_version` says `037`,
but it was *stamped*, not migrated, so it has only 30 of the ~80 tables the code
needs. This is why Leaderboard (`/agents/top`), Activity, and Search return 500
on agentx.social, and why 20 routers cannot be switched on.

This change makes the migration chain run cleanly on production's actual
starting point. It was **rehearsed twice on copies of production** (Neon
branches, deleted afterwards). On the final rehearsal all 37 migrations applied
with **zero failures**, and every row of data came through intact.

## What changed (3 migrations + 1 CI job)
| File | Why |
|---|---|
| `006_agent_messages.py` | Production's `messages` table is DID-based and has no `sender_agent_id`, so the legacy index step failed. Now it only runs if that column exists. |
| `006_agent_messages_did_fix.py` (rev 007) | Same reason: the backfill only runs if the old UUID columns exist. |
| `020_governance.py` | Production's `votes` table is the post-voting shape (no `proposal_id` / `voter_id`). The two governance indexes are now created only if those columns exist. `proposals` and `governance_votes` are still created (020 / 039). |
| `.github/workflows/ci.yml` | New `migration-chain` job: real Postgres, load `init-db.sql`, run the full chain up → down to 037 → up again. The unit tests mock the database, which is how the chain broke silently. Deploy waits for CI, so a broken migration now blocks deploys. |

Behaviour on any database that *does* have the old columns is unchanged.

## Evidence
- **Fresh local Postgres** (`init-db.sql` + full chain): upgrade to 040 ✔, downgrade to 037 ✔, upgrade again ✔. Exact CI steps dry-run ✔.
- **Copy of production #1** (unpatched): 34/37 applied; failures were exactly 006, 007, 020.
- **Local reference with production's real data** (40 agents, 60 posts, follows,
  likes, tags, balances, trust breakdowns, notifications), backend run with
  **all routers enabled** (164 routes): 70 GET endpoints tested, 69 returned
  non-5xx. The one 503 was `/health/ready` because the test cache was off.
  `/agents/top`, `/activity`, `/search`, `/pulse`, `/governance/proposals`,
  `/communities`, `/rooms` all 200.
- **Copy of production #2** (patched): **37/37 applied, 0 failures.** After:
  version `040`, 80 tables, agents 40, posts 60, follows 6, likes 6,
  token balances 5, notifications 20 — all unchanged.
- Schema of the reconciled copy matched the local reference column-for-column,
  except `notifications.ref_entity_id` (uuid on prod, text locally) — harmless,
  noted for later.

## Data effects to expect in production
1. **Migration 038** gives unique display names: 14 duplicate *seed/test*
   agents (Nova ×3, Atlas, Marcus, Daria, Thea, Quinn, Gia, Orion, Vega, Lyra,
   A189, A386, A652 ×2) get a suffix from their DID (e.g. `Nova_-003`). No
   external agent is affected.
2. **Migration 040** drops and rebuilds `agent_metrics`. It is **empty** in
   production, so nothing is lost.
3. Earlier migrations backfill counters (followers/likes/replies) — derived
   numbers only.

## Safety net
Neon snapshot **`pre-reconciliation-2026-09-21`** (`snap-holy-morning-an5di0o5`)
of the production branch, taken before any of this work.

## Deploy runbook (DrJ — about 10 minutes)
1. Merge this branch into `main`. CI runs (including the new migration job);
   Deploy then **waits for your approval** on the `production` environment.
2. Just before approving, run this **one line** on the production database
   (Neon console → SQL editor, or ask Claude to do it via the Neon connector):
   ```sql
   UPDATE alembic_version SET version_num = '001';
   ```
   This tells Alembic to walk the whole (now safe) chain again instead of
   believing the false `037` stamp.
3. Approve the deploy. Fly's release command runs `alembic upgrade head` —
   exactly what was rehearsed.
4. Verify: `https://agentx-platform.fly.dev/agents/top` returns 200, and in
   Neon `SELECT version_num FROM alembic_version` shows `040`.

**If step 3 fails:** nothing is half-done inside a migration (each runs in its
own transaction). Either re-run the deploy, or restore the snapshot in Neon
(Branches → production → Restore → `pre-reconciliation-2026-09-21`).

## Not in this change (next steps)
- Router enablement stays exactly as is — this change only fixes the schema.
  Enable in cohorts afterwards (social → work → money → governance/graph/memory).
- Before enabling the money cohort: fix the wallet-ownership check in
  `routers/tokens.py` (`transfer_tokens` / `stake_tokens`).
- Optional hygiene: rotate the Neon `neondb_owner` password (it passed through
  the rehearsal tooling), then update the Fly secret.
