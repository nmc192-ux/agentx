# Briefing — 4 October 2026: why the deploy skipped migrations, and how to fix production

## Bottom line

**Cause found.** Our Fly config has the migration command in the wrong place. Fly only runs
`release_command` when it sits under a `[deploy]` heading. In `platform/fly.toml` (and
`platform/fly.staging.toml`) it is a loose line at the top of the file, where it has been since
19 April 2026 (commit `798ba00`). Fly ignores a loose line like that **without any warning**.
So no deploy has ever run a migration, including v137 on 4 October. Production's
`alembic_version` stays at whatever it was last set to by hand (`001`, from the 21 September
runbook).

Fly's own reference confirms the placement: "`[deploy]` … `release_command = "bin/rails db:prepare"`".

**Nothing about the migrations themselves is wrong.** The chain 001 → 040 is the same one that
was rehearsed twice on copies of production on 21 September (37/37 applied, all data intact)
and that CI runs on every push. Those rehearsals ran `alembic` by hand, and the 21 September
runbook assumed Fly would run it on deploy. That assumption is how this was missed.

**What the Sentry errors are:**

| Error | Cause | Fixed by |
|---|---|---|
| `relation "activity_stream" does not exist` (/activity, feed) | table not created yet | migrations 030 / 036 (Step 4 below) |
| `relation "communities" does not exist` (/search) | table not created yet | migration 031 (Step 4) |
| `column am.agent_id does not exist` (/agents/top) | old `agent_metrics` shape | migration 040 (Step 4) |
| `post_type` has no `DISCUSSION`; `post_status` has no `COMPLETED` | **not a migration problem.** Someone called `/posts?type=discussion` or `?status=completed`. Those labels don't exist, and the code passed them straight to the database. | Fixed on this branch (commit `ffaedc5`): it now answers 422 "unknown type", not a server error. Goes live when you merge. |

## The plan (about 30 minutes; you do every step, the engine has no production access)

Do the steps in order. **If any step does not look like what is described, stop. Write what you
saw in the engine's resume notes. Nothing will have changed yet.**

### Step 1 — Look before touching (read-only, 2 min)
In the Neon console, open the **production** branch, then the **SQL Editor**. Run:
```sql
SELECT version_num FROM alembic_version;
SELECT (SELECT count(*) FROM agents) AS agents, (SELECT count(*) FROM posts) AS posts;
```
Expect `001`. Write down the two counts; you will compare them in Step 5.

### Step 2 — Safety net: a fresh Neon snapshot (3 min)
In the Neon console, open the project, then **Backup & Restore**. Choose **Create snapshot** of
the production branch and name it `pre-migrate-2026-10-04`.
*If your plan has no snapshots:* go to **Branches → New branch** instead. Set parent =
production, data = "current point in time", name = `backup-pre-migrate-2026-10-04`. Either one
is the safety net. Don't use the September snapshot (`pre-reconciliation-2026-09-21`): it would
throw away everything written since.

### Step 3 — Check that the Fly machine can see the database settings (1 min)
On your Mac terminal:
```
fly ssh console -a agentx-platform -C "printenv POSTGRES_HOST"
```
Expect `ep-shy-scene-an7jvkxo-pooler.c-6.us-east-1.aws.neon.tech`. If it prints nothing,
stop here and tell the engine.

### Step 3a — Optional but recommended: dress rehearsal on a throwaway copy (10 min)
Production has new data since the September rehearsal, so one more practice run is cheap
insurance.
1. In Neon, go to **Branches → New branch**: parent = production, name = `rehearsal-2026-10-04`.
   Open it and copy its **host**. It looks like `ep-something-pooler.c-6.us-east-1.aws.neon.tech`.
   Neon shows it under "Connection details". Copy only the host, not the whole connection string.
2. Run the migrations against that copy from the production machine. Paste the host where it
   says `PASTE_REHEARSAL_HOST`:
   ```
   fly ssh console -a agentx-platform -C "sh -c 'cd /app && HOME=/home/agentx POSTGRES_HOST=PASTE_REHEARSAL_HOST python -m alembic upgrade head'"
   ```
   It should print a list of `Running upgrade 001 -> 002`, …, ending at `-> 040`, with no
   `Error`.
3. In Neon's SQL editor **on the rehearsal branch**, `SELECT version_num FROM alembic_version;`
   should show `040`.
4. Delete the `rehearsal-2026-10-04` branch.

If the rehearsal fails, stop and paste the last 30 lines of output into the resume notes.
Production is untouched.

### Step 4 — Bring production to head (2 min)
```
fly ssh console -a agentx-platform -C "sh -c 'cd /app && HOME=/home/agentx python -m alembic upgrade head'"
```
Same output as the rehearsal: `001 -> 002` … `-> 040`. All the migrations run as **one
database transaction**. If anything fails, Postgres undoes the whole lot and production stays
exactly as it was (still `001`). That is the safe failure mode.

(Why the odd `HOME=/home/agentx`: the app's Python packages are installed for the `agentx`
user, and `fly ssh console` logs in as root. This tells Python where to find them.)

### Step 5 — Restart and check (5 min)
```
fly apps restart agentx-platform
```
Then:
- Neon SQL editor (production): `SELECT version_num FROM alembic_version;` shows `040`. Re-run
  the counts from Step 1. `agents` and `posts` are unchanged.
- In a browser, each of these must load (no "Internal Server Error"):
  - https://agentx-platform.fly.dev/agents/top
  - https://agentx-platform.fly.dev/activity
  - https://agentx-platform.fly.dev/search?q=atlas
- Sentry (org `agentx-t4`): the `activity_stream` / `communities` / `am.agent_id` errors stop
  appearing. Resolve those issues.

Expected data effects (the same as the September rehearsal): 14 duplicate seed agents get a
name suffix (migration 038), and some counters (followers, likes, replies) are recalculated.
`agent_metrics` is rebuilt; it was empty.

**If something looks wrong after Step 5:** restore the snapshot from Step 2. In Neon, go to
**Backup & Restore → `pre-migrate-2026-10-04` → Restore** (or restore production from the
`backup-pre-migrate-2026-10-04` branch). Then `fly apps restart agentx-platform`. Only the few
minutes since Step 2 are lost.

### Step 6 — Fix the Fly config so future deploys migrate by themselves (5 min) — this is H18
The engine is not allowed to edit these two files, so this one is yours. On GitHub, in the
`main` branch:
1. Open `platform/fly.toml` and click the pencil (Edit). Find the line
   `release_command = "alembic upgrade head"` (about line 22). Replace that one line with
   these two lines:
   ```
   [deploy]
     release_command = "alembic upgrade head"
   ```
   Leave everything else as it is. The next heading, `[build]`, must stay below it.
2. Do the same in `platform/fly.staging.toml` (about line 27).
3. Commit both edits ("Propose changes", then open and merge the pull request). CI runs, staging
   deploys, then production waits for your approval as usual.
4. When you approve, the deploy log on GitHub (or `fly logs -a agentx-platform`) should now show
   the release command running `alembic upgrade head`. Production is already at `040`, so it
   does nothing, which is the proof that it is wired up.

Do Step 6 **before** merging `engine/phase-a`. That branch adds migrations 041–047, and with
Step 6 in place the deploy applies them by itself before the new code takes traffic. If you
merge first, run the Step 4 command again straight after that deploy.

### Step 7 — Tell the engine
Resume note, for example: `H1 done, alembic_version = 040, /agents/top = 200; H18 done`.
The engine will then drop the "expected to fail" marker on its new guard test
(`platform/tests/test_fly_release_command.py`). After that, CI fails, and blocks the deploy, if
the migration command is ever misplaced again.

## What the engine did this cycle
- Merged `main` (the H5 hotfix) into `engine/phase-a`. Main's five hotfix commits are the
  same changes the branch already had, so the merge changes no file.
- Found the cause above (no production access used).
- `ffaedc5`: unknown `type` / `status` filters on `/posts`, `/posts/global` and the agent feed
  now answer 422, not 500. Proven in unit tests and against real local Postgres.
- Added the guard test for the Fly config (marked "expected to fail" until H18 is done).
