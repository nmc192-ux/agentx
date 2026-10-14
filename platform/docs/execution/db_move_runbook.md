# Moving the database from Neon to the Pink Popcorn VPS: runbook

**Status:** files ready, nothing done. Written engine cycle 178, 2026-10-14 (PLAN step DB-1).
**Why:** `engine/free_tier_audit.md` (FT-1). The live API keeps Neon's free compute awake around
the clock: about 180 CU-hours a month against 100 free, so Neon pauses about day 17. Neon is also
suspended until 1 Nov for transfer. The database therefore moves to the VPS, where the API is
going anyway (`vps_migration_plan.md`).
**Who:** DrJ runs every step. The engine has no access to the VPS, Neon or Fly.
**The fuller day plan** (merge, packages, alerts, DNS) is the launch-readiness sprint's job
(PLAN LR-0). This runbook covers the database only, and LR-0 slots it in as written.

## 1. What changes, in one paragraph

A fourth container, `db` (Postgres 17 with pgvector, the same extension Neon has for
`posts.embedding`), runs beside `api-1`, `api-2` and `scheduler` on the VPS. It sits on AgentX's
private Docker network only. It is not on Caddy's network (which Pink Popcorn shares), it
publishes no port, and nothing outside the VPS can reach it. Its data lives in the Docker volume
`agentx_pgdata`. One settings file, `/etc/agentx/db.env`, holds its user, database name and
password, and the API reads the same file. The switch is one line in `/opt/agentx/compose.env`:

```
AGENTX_DB_ENV=/etc/agentx/db.env     # VPS database
AGENTX_DB_ENV=                       # Neon (as today)
```

While that line is empty, everything uses Neon exactly as before. `deploy/vps/db_move.sh` does
the copying: `check`, `dump`, `restore`, `verify`, `backup`. Its tests are in
`platform/tests/infrastructure/test_db_move.py`, rehearsed on local Postgres. They cover the real
migration chain, a round trip with identical row counts, a refused second restore, a half-broken
dump that leaves nothing behind, backup rotation, and the Neon password never appearing on a
command line.

## 2. Why the timing is simple this time

Production is down until Neon's allowance resets on 1 Nov, so **nobody is writing to Neon**.
That gives us something rare: a copy taken on 1 Nov is complete, with no "freeze writes" window
and no data typed in between to lose. The only rule is that **nothing may start writing to Neon
again before the copy is taken.** Fly's old API would do exactly that the moment Neon wakes, so
Fly goes to zero first (step B1).

After the move, **Neon becomes a frozen copy of the 1 Nov state**, and Fly stays at zero. They
are the fallback for a disaster in the first days. They are not a warm standby, because the
moment the VPS takes its first write, Neon is out of date (§5).

## 3. Before 1 Nov (any evening; about 20 minutes; nothing live changes)

Do these after H30 steps 1–8 (deploy user, `/etc/agentx`, `compose.env`, Caddy, DNS for
`api-vps`, GitHub secrets). H30 step 9, the first deploy, waits for 1 Nov (B6), because it needs
the merge.

**A1. Make the database settings file** (on the VPS):
```
openssl rand -hex 24
```
Copy the 48 letters and digits it prints, then:
```
sudo nano /etc/agentx/db.env
```
Put exactly this in it (the file `deploy/vps/db.env.example` shows the same lines), with the
48 characters after `POSTGRES_PASSWORD=`:
```
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_USER=agentx
POSTGRES_DB=agentx
POSTGRES_SSL_MODE=disable
POSTGRES_PASSWORD=<the 48 characters>
```
Save (Ctrl+O, Enter, Ctrl+X), then:
```
sudo chown root:deploy /etc/agentx/db.env && sudo chmod 640 /etc/agentx/db.env
```
You never need to type this password again. Nothing outside the VPS can reach this database,
and the API reads the password from this file.

**A2. Put the new files on the VPS.** The deploy workflow copies them on every deploy from the
merge on. Until then, copy them once from your Mac (Terminal, in the repo folder):
```
scp deploy/vps/docker-compose.yml deploy/vps/settings.env deploy/vps/db_move.sh deploy@2.25.235.174:/opt/agentx/
```
(If you log in as yourself rather than `deploy`, copy to your home folder and
`sudo cp … /opt/agentx/ && sudo chown deploy:deploy /opt/agentx/*` on the VPS.)

**A3. Add the two new lines to `/opt/agentx/compose.env`** (as in `deploy/vps/compose.env.example`):
```
sudo -u deploy nano /opt/agentx/compose.env
```
```
AGENTX_DB_ENV=
AGENTX_DB_SECRETS_FILE=/etc/agentx/db.env
```
`AGENTX_DB_ENV` stays **empty** for now (Neon).

**A4. Start the database and the backup folder** (on the VPS):
```
sudo mkdir -p /var/backups/agentx && sudo chown deploy:deploy /var/backups/agentx && sudo chmod 700 /var/backups/agentx
cd /opt/agentx && sudo -u deploy docker compose --env-file compose.env --profile db up -d db
sleep 30; sudo -u deploy docker compose --env-file compose.env --profile db ps db
```
The last line must say `healthy`. The image is downloaded once (about 150 MB). The database
uses up to 1 GB of memory; the VPS has 6.6 GB free (H21).

**A4b. Check the VPS has its certificate bundle** (on the VPS; it is there on any normal
Ubuntu or Debian, this only confirms it):
```
ls -l /etc/ssl/certs/ca-certificates.crt
```
You must see a file. If you see "No such file", run `sudo apt-get install -y ca-certificates`
and look again. Why: the copy from Neon crosses the public internet, and the script checks
Neon's certificate against this bundle (`sslmode=verify-full`) so nobody between the VPS and
Neon can pose as Neon and read the copy (SR-1, Fable review, 14 Oct).

**A5. Nightly backup** (as `deploy`: `sudo -u deploy crontab -e`, add one line):
```
17 3 * * * cd /opt/agentx && bash db_move.sh backup >> /var/backups/agentx/backup.log 2>&1
```
That is 03:17 every night (VPS clock). It keeps the newest 14. Until the switch it backs up an
empty database, which is harmless. Copying backups off the VPS and a tested restore come in
LR-0 part 4.

**A6. Fly to zero** (Mac Terminal). Production is down anyway, and this stops Fly from billing
and from writing to Neon the moment Neon wakes on 1 Nov:
```
fly scale count app=0 -a agentx-platform
fly status -a agentx-platform
```
`fly status` must list no running machines. If H23 gave the scheduler its own process group,
also run `fly scale count scheduler=0 -a agentx-platform`. Do not destroy the app.

## 4. On 1 Nov (about 30 minutes for the database part)

All commands run on the VPS in `/opt/agentx` as `deploy` (`sudo -u deploy -i`, then
`cd /opt/agentx`), unless they say Mac or browser.

| # | Step | Command / where | Must see | If not |
|---|---|---|---|---|
| B1 | Fly is still at zero | Mac: `fly status -a agentx-platform` | no running machines | `fly scale count app=0 -a agentx-platform`, then continue |
| B2 | Neon is awake again | browser: console.neon.tech → project | no "suspended" banner; usage reset | wait; the reset can be hours into 1 Nov (UTC) |
| B3 | Insurance copy inside Neon | Neon console → Branches → `main` → **Create branch** named `before-vps-2026-11-01` | branch listed | continue anyway; the dump in B5 is the main copy |
| B4 | Pre-flight | `bash db_move.sh check` | `neon postgres: N vps postgres: 17 (… sslmode verify-full)`, `extensions: all available`, `tables: 0`, `OK` | `FAIL … newer` or `FAIL … extensions`: stop, send the line to the engine (resume note); the API stays on Neon (§5 row 1). `no CA bundle` or `certificate verify failed`: do A4b, then run `check` again; never set `SRC_SSLMODE=require` to get past it (that is the interception the check exists for) |
| B5 | Copy Neon | `bash db_move.sh dump` | `dump: /var/backups/agentx/neon-<time>.dump (<size>)` | send the error to the engine; nothing changed anywhere |
| B6 | Load it on the VPS | `bash db_move.sh restore /var/backups/agentx/neon-<time>.dump` (copy the name from B5) | `restored … N tables` | prints `restore failed: nothing was kept`: send the error; API stays on Neon |
| B7 | Compare | `bash db_move.sh verify` | every table listed, then `OK: … identical` | `DIFFERENT`: something wrote to Neon after B5 (is Fly really at zero?). Start again from §6 |
| B8 | Switch | `sed -i 's#^AGENTX_DB_ENV=.*#AGENTX_DB_ENV=/etc/agentx/db.env#' compose.env && grep AGENTX_DB_ENV compose.env` | `AGENTX_DB_ENV=/etc/agentx/db.env` | |
| B9 | Merge + first deploy | H30 step 9 (GitHub → Actions → "Deploy to VPS"). Its migration step now runs on the **VPS** database (048 and 049 arrive there; Neon keeps the old schema) | workflow green; `"status":"ok"`. **The merge also starts the old Fly "Deploy" workflow: GitHub → Actions → Deploy → "Review deployments" → Reject the production step** (approving it would start Fly on Neon after your copy) | the workflow prints the reason; the API is not live yet, so there is nothing to roll back: fix and run again. If the Fly production step was approved by mistake: `fly scale count app=0 -a agentx-platform` at once, then start again from §6 |
| B10 | The API really uses the VPS database | `docker compose --env-file compose.env logs api-1 \| grep "PostgreSQL pool"` | `host=db db=agentx ssl=disable` | `host=ep-…neon.tech`: B8 did not take; repeat B8, then `docker compose --env-file compose.env up -d --no-deps api-1 api-2` |
| B11 | Ready check | `curl -s https://api-vps.agentx.social/health/ready` | database `ok` | `docker compose --env-file compose.env logs --tail 50 api-1` → engine |
| B12 | Smoke test | H30 step 10 (`bash smoke.sh https://api-vps.agentx.social`) | every line PASS | send the output to the engine |
| B13 | Scheduler on (exactly one: Fly's is at zero) | `docker compose --env-file compose.env --profile scheduler up -d scheduler` | after 15 min, `logs --tail 50 scheduler` shows `'errors': []` | `docker compose --env-file compose.env stop scheduler` → engine |
| B14 | First real backup | `bash db_move.sh backup` | `backup: /var/backups/agentx/agentx-<time>.dump` | → engine |

After B14, `api.agentx.social` is pointed at the VPS (migration plan §9 step 4, part of LR-0's
day plan). The database part is done.

**Neon afterwards:** leave the project as it is for at least 30 days. With nothing connected,
its compute sleeps after 5 minutes and uses no hours. Do not delete it. It is the §5 fallback.

## 5. Going back

| When | What | Data lost |
|---|---|---|
| Any step up to B7 | Nothing to undo: `AGENTX_DB_ENV` is still empty, the API (once deployed) uses Neon. Neon's ~16 free days a month buy time for the engine to fix the copy. | none |
| B8–B12, before the address points at the VPS | Empty `AGENTX_DB_ENV` again (`sed -i 's#^AGENTX_DB_ENV=.*#AGENTX_DB_ENV=#' compose.env`), stop the scheduler, `docker compose --env-file compose.env up -d --no-deps api-1 api-2`. Then the API runs on Neon. **But** B9 already ran migrations 048/049 only on the VPS database. Deploying with Neon needs `--profile migrate run --rm migrate` once, which is safe (it only adds two tables). | only smoke-test agents |
| After outside agents have used the VPS database | Prefer fixing forward. If the VPS itself is lost, restore the newest nightly backup on a new machine (the dump runs with `pg_restore` exactly as in B6). Going back to Neon means its 1 Nov copy plus the newest backup loaded into a **new** Neon database: ask the engine to write that procedure for the day (it writes to production, so it is not pre-scripted). | up to a day without the off-VPS copies of LR-0 part 4 |

## 6. Starting the VPS database afresh

Use this only if B6 or B7 failed, or before a second attempt. The API must not be using the VPS
database (`AGENTX_DB_ENV` empty). This deletes the VPS copy, never Neon:
```
docker compose --env-file compose.env --profile db down db
docker volume rm agentx_pgdata
docker compose --env-file compose.env --profile db up -d db
```
Then continue from B4.

## 7. What the engine checked locally (cycle 178)

- `docker compose config` with the example files: by default the four app services get Neon's
  `POSTGRES_HOST`. With `AGENTX_DB_ENV` set, every service gets `db`. The `db` service is only
  on `agentx_private`, has no `ports`, and never loads `api.env`. A deploy with no `db.env` on
  the VPS still works; only `--profile db` needs the file
  (`tests/infrastructure/test_vps_deploy_files.py::TestDatabaseService`, `TestComposeConfig`).
- `db_move.sh` natively against local Postgres 17 + pgvector: a scratch "Neon" built with the
  real migration chain (`smoke_routers.build_database`) → dump → restore → verify OK. That
  covers alembic version, row counts, and the `vector(1536)` column. Also covered: one deleted
  row → `DIFFERENT`, a second restore refused, a half dump → target stays empty, a missing
  extension → `check` fails, backup keeps the newest N and never touches `neon-*.dump`, and the
  password is in no tool's argv (`tests/infrastructure/test_db_move.py`, `--db`, 8 tests).
- **SR-1 (Fable review, cycle 180):** the Neon side now runs in a throwaway container of the
  same image with the VPS's CA bundle mounted and `sslmode=verify-full`; the running `db`
  container (and `db.env`) never sees the Neon password. Checked natively: with no mode given
  the tools get `verify-full` plus the root cert, an unverifiable server stops `check` before
  anything is read, the VPS-side tools get no SSL settings, and an empty `POSTGRES_HOST` is
  refused (3 more tests, 11 in all). The `docker run` line itself is file-checked only.
- **Not checked here:** the containers themselves. This Mac has a Docker CLI but no Docker
  daemon, the same gap as Sprint 16, and its rehearsal script `scripts/vps_rehearsal.py` runs
  natively too. A real Neon dump also could not be checked, because Neon is suspended and the
  engine has no credentials. B4 (`check`) is what finds a Neon-specific surprise on the day,
  before anything changes.
