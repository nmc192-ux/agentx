# Sprint 16 — VPS migration prep

**Drafted by:** the engine, cycle 103 (2026-10-07). **Updated:** cycle 141, after H21.
**Status:** planned (`execution/engine/PLAN.md`). Plan: `platform/docs/execution/vps_migration_plan.md`.

**Files only.** DrJ (H21 note): "prepare files only, nothing is deployed without me." This
sprint writes `deploy/vps/` and a manual-only deploy workflow and checks them locally. It runs
nothing on the VPS, touches no DNS, no secrets and no Fly app.

## What H21 told us (2026-10-07)

| Fact | Value | Consequence |
|---|---|---|
| Host | 2.25.235.174, Boston US; Ubuntu 24.04.5 x86_64 | Images built for `linux/amd64`. |
| Size | 2 CPU, 7.8 GiB RAM (6.6 free), 96 GB disk (35% used) | Plan's memory caps (512 MB per API container and scheduler, about 1.5 GB total) fit easily. |
| Docker | 29.8.1, Compose v5.5.1 | No install step in H-prepare. |
| 80/443 | Already served by Pink Popcorn's **Caddy container** | Plan §4 **option B**: AgentX adds a site block to that Caddy; it starts no proxy of its own and publishes no public port. |
| Neon (us-east-1) | 14/14/15/16 ms | **Gate passed** (under 20 ms, plan §2). |
| Upstash | 146 ms, one sample incl. DNS; region being checked | Open risk, not a gate in the plan. H29 re-measures without DNS. If it stays high, a follow-up proposes moving Redis; files do not change. |
| DNS | Hostinger (H19 note); DrJ to confirm | No Cloudflare DNS challenge; cutover uses the "small gap" certificate route (plan §4). |

## Design decisions (reversible, recorded in the log)

1. **Sharing Caddy through a Docker network, not host ports.** Pink Popcorn's Caddy runs in a
   container, so `127.0.0.1:8001` on the host is not reachable from it without changing that
   container. Instead the AgentX compose project joins Caddy's existing network as an
   `external` network (name from `PROXY_NETWORK`, filled in by H29). The API containers expose
   port 8000 on that network only; nothing is published on the host. Pink Popcorn's container
   is not modified; the only change on its side is one `import` line in its Caddyfile and a
   `caddy reload`, done by DrJ.
2. **Trusting forwarded headers from the proxy network's subnet only.** The Caddy container's
   own address is not fixed (Pink Popcorn owns that network), so `--forwarded-allow-ips` is set
   to the proxy network's subnet (`PROXY_SUBNET`, from H29). Only containers on that network can
   reach the API at all; the plan's rule (never `*`) holds.
3. **No local Docker daemon on the engine Mac.** The check "the stack starts locally" is done in
   two halves: (a) `docker compose config` validates the compose file, and the exact container
   commands (two uvicorn processes with the same flags, the scheduler command) run natively
   behind a local Caddy using the same site block, against local Postgres and Redis; (b) the
   in-container start is the first thing DrJ's VPS preparation step runs, before any traffic
   moves, using the same `smoke.sh`.

## Steps

- **V-2a:** `deploy/vps/docker-compose.yml` (api-1, api-2, scheduler, one-shot `migrate`),
  `api.env.example` copied from `fly.toml` `[env]` with no secrets, memory limits, log caps,
  `unless-stopped`. A test pins: no secret values, env keys match Fly's, ports not published,
  scheduler not started by default, forwarded-allow-ips never `*`.
- **V-2b:** `deploy/vps/agentx.caddy` (the site block to import) and `smoke.sh` (health, ready,
  sign-up, login, feed, WebSocket, real caller address). Check: the native run in decision 3(a)
  passes the smoke script; stopping one API process keeps `/health` answering through Caddy.
- **V-3:** `.github/workflows/deploy-vps.yml`, `workflow_dispatch` only, `production`
  environment approval, build → push to ghcr.io → migrate → roll api-1 then api-2 → verify.
  `NEEDS-DELIBERATE-MERGE:`. Check: `actionlint` clean; a test pins migrate-before-roll and
  that no secret value is in the repo. `deploy.yml` is not touched.
- **Human-action write-up:** exact steps for DrJ to prepare the VPS (deploy user and key,
  `/etc/agentx/api.env`, the `import` line, first start with the scheduler stopped, `smoke.sh`
  against `api-vps.agentx.social`, uptime monitor), referenced to plan §9 for cutover day.

The move itself (DNS, secrets, switching traffic) is DrJ's, as HUMAN_ACTIONs.

## Acceptance

1. `docker compose -f deploy/vps/docker-compose.yml config` succeeds with the example env.
2. The native rehearsal (decision 3a) passes `smoke.sh`, including the real-caller-address check.
3. With one API process stopped, `/health` through Caddy keeps returning 200.
4. `actionlint` clean on `deploy-vps.yml`; migrate runs before any container is replaced.
5. `grep` finds no secret values in `deploy/`; full platform test suite still green.

## Gate

Passed: Neon 14–16 ms (H21). If H29 shows Redis is far away, the sprint still finishes (files
only) and the briefing recommends moving Redis before cutover.
