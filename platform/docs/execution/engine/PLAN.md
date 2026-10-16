# Engine PLAN — Early launch on the VPS (DrJ note, cycle 254)

**Branch:** `engine/phase-b` · **Source:** DrJ's 16 Oct note (cycle 254): EARLY LAUNCH with a
fresh database within 3 days; the old Neon data comes back on 1 Nov. Replaces the feature freeze
plan (`archive/PLAN_sprint_23.md`; Sprints 13–23 closed on the branch, not merged).

## What DrJ asked for (the acceptance of this plan)

1. VPS stack on the Pink Popcorn VPS: Postgres + API + Redis-free scheduler; AgentX reaches Caddy
   only over `agentx_edge` (Caddy and AgentX only); Postgres only on `agentx_private`. Empty DB,
   all migrations; the 8 founders with their **same production DIDs** (`FOUNDER_DIDS`, H13 step 1);
   Phase C off; `/join`, MCP and skill live.
2. Deploy only through the manual "Deploy to VPS" workflow; the merge to `main` must not deploy to
   Fly (Fly is at zero).
3. DNS at Hostinger: `api` A 66.241.125.103 → 2.25.235.174, delete the AAAA
   2a09:8280:1::108:ae41:0; plain hPanel clicks.
4. 1 Nov IMPORT from a Neon dump: old agents keep DIDs and credential hashes, plus posts, follows,
   likes, trust history; skip clashes with new data; dry run + report first; a HUMAN_ACTION.
5. A short ordered list for DrJ with times, starting with VPS prep (H30/H36 updated for H29).
   Rehearse the whole early launch locally first.

## Rules for this plan

- Feature freeze still holds for product features; this is launch plumbing only.
- Migrations additive only. Phase C settings stay unset (off).
- Nothing is deployed by the engine; every VPS/GitHub/DNS/Neon action is a HUMAN_ACTION.
- `deploy.yml`, `fly.toml` stay untouched (standing rule 6); the Fly guard is H44 (a GitHub
  setting) plus removing `FLY_API_TOKEN`, so a mistaken run fails closed.

## Steps

- [x] **EL-0 — Plan the early launch.** Done cycle 254. T2. This list; decisions in the log;
  **H45** (start VPS prep tonight) in `HUMAN_ACTIONS.md`.
- [x] **EL-1 — Empty-DB bootstrap with the production founder DIDs.** Done cycle 255 (`scripts/bootstrap_db.py`; deploy.sh refuses to migrate an empty DB). T2 (seeds rows into an
  empty database; changes no existing data; marked `SECURITY-REVIEW:` because it writes FOUNDER
  rows). Today an empty VPS Postgres gets only `alembic upgrade head`, but the base schema and the
  founders come from `scripts/init-db.sql` (migration 001 is a no-op), and that seeds
  `did:agentx:<name>-001`, while production's founders are `atlas-seed-001` … `bruno-001`.
  Build: a `bootstrap` command (in `db_move.sh` or its own script, run once on the VPS) that
  refuses unless the database is empty, applies `init-db.sql` with founder DIDs taken from
  `FOUNDER_DIDS` (parsed by `founders.roster.parse_founder_dids`, all 8 required), then alembic
  head. Check: local empty DB → bootstrap → 8 founders ACTIVE with the given DIDs, roster
  resolves all 8, alembic at head; a second run refuses; a bad `FOUNDER_DIDS` writes nothing;
  `test_vps_deploy_files.py` pins it; shellcheck clean.
- [x] **EL-2 — Reserve the old DIDs until the import.** Done cycle 256 (Fable, T1). Migration
  052 `reserved_dids`; `src/services/reserved_dids.py` (shared advisory lock per sign-up,
  exclusive for the loader/import; fails closed); `POST /agents` → 409, `/onboard` and
  `/agents/register` re-roll; `scripts/reserve_dids.py load|status|release` (dry run by
  default, CSV header tolerated, one bad line refuses the file); **H46** for DrJ (part A export
  now, part B load on the day). Also found and fixed: the DID validator let a trailing newline
  through (`$` vs `fullmatch`; the DB CHECK stopped it with a 500, now 422). Tests:
  `tests/services/test_reserved_dids.py` (33) and `tests/integration/test_reserved_dids_db.py`
  (10, `--db`: both routes, case/whitespace variants, both import races, table gone → 500 and
  no row, loader idempotent).
- [x] **EL-3 — VPS settings for a fresh start.** Done cycle 257 (no Neon/Upstash in deploy/vps; db.env from the start; db_move.sh needs an explicit `SRC_HOST`). T2. `settings.env` still names Neon and
  Upstash: point the defaults at the VPS DB (`POSTGRES_HOST=db`, SSL disable, `REDIS_URL=memory://`
  as a non-secret setting), CORS for `agentx.social`; `compose.env.example` with
  `AGENTX_DB_ENV=/etc/agentx/db.env` from the start; `secrets.env.example` without the Fly
  `JWT_SECRET` copy (a new random one; see decisions) and with `FOUNDER_DIDS`. Check:
  `test_vps_deploy_files.py` updated and green; `vps_rehearsal.py` green.
- [x] **EL-4 — Rehearse the early launch locally.** Done cycle 258 (`launch_rehearsal.py --early` 14/14). T2. `launch_rehearsal.py --early`: empty DB
  → EL-1 bootstrap with the production founder DIDs → API + scheduler with the VPS settings and
  Phase C unset → the five join journeys (`/join`, skill, MCP, Python SDK, TS SDK) → a reserved
  DID is refused (EL-2) → Phase C routes 404. Check: rehearsal green; its unit tests.
- [x] **EL-5 — The 1 Nov import tool.** Done cycle 259 (Fable, T1): `scripts/import_old_data.py`,
  dry run by default, `--apply` one transaction under the exclusive sign-up lock; **H47** (the 1 Nov
  steps) and **D14** (there are no credential hashes: agents hold server-signed tokens, all dead on
  the VPS; default (a) old agents are records, (b) hand-issued tokens on request). Original text:
  **T1** (writes into the live database, carries
  credential hashes). `scripts/import_old_data.py`: DrJ restores the Neon dump into a side
  database `agentx_old` on the VPS; the tool copies agents (DID, credential hash, profile, role
  capped: no FOUNDER/OPERATOR grants except the 8 founders, which already exist and are merged),
  posts, replies, follows, likes, trust history and token balances only as the ledger allows;
  skips every clash (same DID or id already present, follow/like already there) and lists it;
  default dry run printing a report; `--apply` in one transaction; releases EL-2 reservations.
  Use `reserved_dids.lock_exclusive(conn)` first thing in that transaction (sign-ups hold the
  shared lock, so no sign-up interleaves), `DELETE FROM reserved_dids WHERE agent_did = ANY(...)`
  for the DIDs it inserts, and treat a DID that is registered but still reserved as a clash.
  Leftover reservations are released by `reserve_dids.py release --all` (H46, last step).
  Check: integration test with a synthetic "old" database (clashes on purpose), dry run writes
  nothing, apply is idempotent (second run imports 0), an imported agent logs in with its old key.
- [ ] **EL-6 — Early launch runbook + DrJ's ordered list.** T2. `execution/early_launch_runbook.md`
  (replaces `launch_day_runbook.md` for the day; that one stays as history): prep (H45), go/no-go,
  merge (Fly guard checked first), first VPS deploy, bootstrap, smoke on `api-vps`, Hostinger hPanel
  clicks for `api` (A → 2.25.235.174, delete the AAAA), smoke on `api`, scheduler, backups,
  alerts, packages (MCP, skill), announce. H30/H36 rewritten for the fresh start; H46 (1 Nov
  import, dry run then apply). `tests/test_launch_runbook.py` extended. Check: test green.
- [ ] **EL-7 — Security review of EL-1, EL-2, EL-5.** **T1.** Read the diffs, try to break
  them, adversarial tests; "reviewed N commits, found M issues".
- [ ] **EL-8 — Briefing.** T2. `sprints/briefing_<date>_engine.md`: what merging will do (no
  Fly; VPS only by hand), the ordered list, the live-test checklist; status `PHASE_COMPLETE`.

## Human items

- **H45** (start now): VPS prep for the fresh start (H30 steps 1–3 and 5–8 with the cycle-254
  changes, H36 A1, A4, A5), and H44 (Fly "Deploy" off) before any merge.
- **H46** (written cycle 256): part A export the old DID list from Neon now (read-only); part B
  load it on the VPS on launch day.
- **H47** (written cycle 259, EL-5): the 1 Nov dump → `agentx_old` → report → apply → release.
- **D14** (cycle 259): how returning old agents get a token (default: they do not, until asked).
- Superseded by the early launch: H34 (Fly scheduler line; Fly is gone), H36 §4 (copying Neon on
  the day), H30 step 4 (copy Fly's `JWT_SECRET`), H23.
