# Sprint 16 — VPS migration prep (draft)

**Drafted by:** the engine, cycle 103 (2026-10-07). **Status:** draft; **waits on H21**
(the VPS facts, above all its distance from the database). Plan:
`platform/docs/execution/vps_migration_plan.md`.

## Scope (sketch)

Carried over from `execution/engine/archive/PLAN_phase_a_close.md`:

- **V-2:** `deploy/vps/` with a compose file (api-1, api-2, scheduler, caddy), Caddyfile,
  `api.env.example`, `smoke.sh`. Check: the stack starts locally against local Postgres and
  Redis; the smoke script passes (sign-up, login, feed, WebSocket, real caller address seen);
  restarting one API container keeps `/health` answering.
- **V-3:** `.github/workflows/deploy-vps.yml`, manual trigger only, behind the `production`
  approval. `NEEDS-DELIBERATE-MERGE:`. Check: `actionlint` clean; migrate-then-roll order; no
  secret values in the repo.

The move itself (DNS, secrets, switching traffic) is DrJ's, as HUMAN_ACTIONs.

## Gate

If H21 shows the VPS is too far from Neon (plan §11), this sprint stops at a short briefing
and the backend stays on Fly.
