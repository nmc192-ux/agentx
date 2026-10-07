# Engine PLAN — Sprint 16: VPS migration prep (files only)

**Branch:** `engine/phase-b` · **Spec:** `sprints/sprint_16_vps_prep.md` · **Plan:**
`execution/vps_migration_plan.md` · **Previous plan:** `archive/PLAN_sprint_17.md`.

**Why now:** DrJ answered H21 (cycle 141 note) and said "go ahead with V-2/V-3 when Sprint 16
comes up; prepare files only, nothing is deployed without me". Sprint 16 was only waiting on
H21, so it comes before Sprint 18 (distribution). Gate passed: Neon 14–16 ms.

**Standing limits for this sprint:** nothing runs on the VPS, no DNS, no Fly, no secrets. Do
not edit `deploy.yml`, `fly.toml`, `fly.staging.toml`. No local Docker daemon on this Mac (see
spec, decision 3): compose files are checked with `docker compose config`, processes are
rehearsed natively.

## Steps

- [x] **S16-1 — Record H21, update the spec, decompose.** T2 (planning). Done cycle 141: H21
  ticked with its facts, H29 added (Caddy network + Upstash region), spec rewritten for option
  B (shared Caddy via an external Docker network). Check: this file exists; HUMAN_ACTIONS has H29.
- [x] **S16-2 — `deploy/vps/docker-compose.yml` + `api.env.example`.** T2 (configuration).
  *Done cycle 142:* split into `settings.env` (Fly's `[env]`, loaded directly), `secrets.env.example`
  (names only → `/etc/agentx/api.env`) and `compose.env.example` (image, tag, proxy network/subnet);
  API refuses to start if the trust list is empty or a wildcard. 19 tests.
  api-1, api-2 (image `ghcr.io/…/agentx-platform:${IMAGE_TAG}`, uvicorn flags from plan §3 with
  `--forwarded-allow-ips=${PROXY_SUBNET}`), `scheduler` under a compose profile so it never
  starts by default, one-shot `migrate` (`alembic upgrade head`) under a profile, `env_file:
  /etc/agentx/api.env` plus the example's non-secret values, 512 MB limits, `json-file` 20m×5,
  `unless-stopped`, healthchecks; networks: private `agentx` + external `${PROXY_NETWORK}`; no
  `ports:`. New `platform/tests/infrastructure/test_vps_deploy_files.py` pins: no `ports:`,
  allow-ips never `*`, scheduler/migrate profile-gated, example env keys ⊇ `fly.toml [env]`
  keys with equal values, no secret-looking values. Check: `docker compose config` with the
  example env succeeds; the new test passes.
- [x] **S16-3 — `deploy/vps/agentx.caddy` + `deploy/vps/smoke.sh`.** T2. *Done cycle 143:*
  rehearsal re-runnable as `platform/scripts/vps_rehearsal.py` (Caddy 2.11.7 installed locally);
  access log now reports the resolved caller as `client=` (raw header as `fwd=`). 12 tests. Site block from plan
  §4 (`api.agentx.social, api-vps.agentx.social`, `reverse_proxy api-1:8000 api-2:8000`,
  health checks, `lb_try_duration`, `flush_interval -1`); upstream names overridable for the
  rehearsal. `smoke.sh BASE_URL`: `/health`, `/health/ready`, sign-up, login, feed, a WebSocket
  handshake, and the real-caller-address check (send `X-Forwarded-For` from outside → must be
  ignored/replaced by Caddy's view). Check: native rehearsal (two uvicorn on 8001/8002 with the
  compose flags, `brew install caddy` locally if absent, the same site block on a local port,
  local Postgres/Redis) passes `smoke.sh`; kill one uvicorn → `/health` via Caddy still 200.
  If Caddy cannot be installed locally, the rehearsal goes straight to uvicorn and the Caddy
  layer is recorded as a gap for the VPS first start.
- [x] **S16-4 — `.github/workflows/deploy-vps.yml`.** T2. `NEEDS-DELIBERATE-MERGE:`. *Done cycle 144
  (e23df04):* roll logic lives in `deploy/vps/deploy.sh` (also the manual/rollback path,
  `SKIP_MIGRATE=1` for rollbacks); input must be a 40-hex SHA already on `main`; 24 tests.
  `workflow_dispatch` only (input: commit/tag), `environment: production`, build
  `platform/Dockerfile.fly` for `linux/amd64` with `GIT_COMMIT`, push to ghcr.io with
  `GITHUB_TOKEN` (`packages: write`), SSH via `VPS_SSH_KEY`/`VPS_HOST` secrets with pinned host
  key (`VPS_KNOWN_HOSTS`), then `migrate` → roll api-1 (wait healthy) → api-2 → scheduler only
  if it was running → `curl` verify `commit`; on failure print the rollback line. Extend the S16-2
  test: migrate step before any `up -d`, no `push:`/`pull_request:` trigger, third-party actions
  pinned. Check: `actionlint` clean; tests pass.
- [x] **S16-5 — Human-action write-up for the VPS (prepare + first start).** T3 (docs). *Done cycle 145:* HUMAN_ACTIONS H30; migration plan §3/§4/§11 updated for option B.
  HUMAN_ACTIONS item(s): deploy user + key, `/opt/agentx`, `/etc/agentx/api.env` (root, 600,
  `JWT_SECRET` copied from Fly unseen), GitHub `production` secrets, the Caddyfile `import` line
  and `caddy reload`, `api-vps` DNS record at Hostinger, first run of the workflow with the
  scheduler stopped, `smoke.sh https://api-vps.agentx.social`, uptime monitor. Also from S16-4: `deploy` user
  owns `/opt/agentx` and is in the `docker` group (root-equivalent; say so), `compose.env` there
  with `AGENTX_IMAGE=ghcr.io/<owner lowercase>/agentx-platform`, `VPS_KNOWN_HOSTS` secret
  (`ssh-keyscan` run by DrJ on the VPS itself, not over the network), optional `VPS_PUBLIC_URL`
  variable, rollback `SKIP_MIGRATE=1 bash deploy.sh <prev>`. Cutover day stays
  plan §9, written up only when DrJ asks. Update `vps_migration_plan.md` §3/§4/§11 for option B.
  Check: every command matches the files from S16-2..4 (read side by side).
- [ ] **S16-6 — Sprint-close security review.** T1. Review `NEEDS-DELIBERATE-MERGE:` commits
  (S16-4, S16-2's proxy trust, S16-3's Caddy block and access-log change): forwarded-header spoofing, secret exposure in logs/workflow,
  SSH host-key pinning, workflow injection through the dispatch input. Adversarial tests.
- [ ] **S16-7 — Sprint close.** T2. Acceptance list from the spec literally, retro, merge
  briefing (files only; nothing deploys on merge), `state_of_agentx.md`, archive this plan.

## Queued next

**Sprint 18 — distribution** (DrJ's cycle-132 note: MCP server, OpenClaw/Hermes skill,
browser-agent join test, "Join AgentX" page). Draft `sprints/sprint_18_distribution.md` and
decompose after Sprint 16 closes; see `archive/PLAN_sprint_17.md` and the cycle 140 log entry.

## Open human items touching this sprint

H29 (Caddy network/subnet + Upstash region) — S16-2 uses placeholders until then. DNS provider
confirmation (DrJ's later note).
