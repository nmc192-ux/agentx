# Sprint 16 — VPS migration prep (files only) — Retro (engine run)

**Sprint:** 16 — VPS migration prep (`sprint_16_vps_prep.md`, drafted cycle 103, rewritten cycle 141 after H21)
**Dates:** 2026-10-07 to 2026-10-08, engine cycles 141–147
**Branch:** `engine/phase-b`. **Not merged.** After this close the branch is 84 commits ahead of `main` (Sprints 13, 14, 15, 17 and 16), 15 marked `SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:` (4 from this sprint). **No migrations.**
**Step list and per-step detail:** `docs/execution/engine/archive/PLAN_sprint_16.md`. **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md` (new: H29, H30).

## What was intended

Prepare everything needed to move the API from Fly.io to DrJ's Hostinger VPS, as files only
(DrJ, H21 note: "prepare files only, nothing is deployed without me"): a compose file, the
site block for the VPS's existing Caddy, a smoke script, a hand-started deploy workflow, and
exact steps for DrJ. Nothing runs on the VPS, no DNS, no secrets, no Fly change.

## What actually shipped (on the branch)

- **S16-1 Plan** (`61ad5a4`). H21's facts recorded; spec rewritten for option B (share Pink
  Popcorn's Caddy over a Docker network, publish no host port); H29 added.
- **S16-2 Compose** (`f25922a`, `SECURITY-REVIEW:`). `deploy/vps/docker-compose.yml`: api-1,
  api-2, scheduler and one-shot `migrate` (both behind profiles, so they never start by
  default), 512 MB caps, log rotation, healthchecks, no `ports:`. Settings split into
  `settings.env` (same values as Fly's `[env]`), `secrets.env.example` (names only) and
  `compose.env.example`. The API refuses to start if the proxy trust list is empty or `*`.
- **S16-3 Caddy and smoke** (`07c18d9`, `SECURITY-REVIEW:`). `agentx.caddy` site block for
  `api.agentx.social` and `api-vps.agentx.social` with health checks and retry; `smoke.sh`
  (health, ready, sign-up, login, feed, WebSocket, spoofed caller address);
  `platform/scripts/vps_rehearsal.py` runs it all natively behind a real local Caddy. The API's
  request log now records the resolved caller as `client=` and the raw header as `fwd=`.
- **S16-4 Deploy workflow** (`e23df04`, `NEEDS-DELIBERATE-MERGE:`). `.github/workflows/deploy-vps.yml`:
  hand-started only, `production` approval, input must be a full commit already on `main`;
  build → ghcr.io → migrate → api-1 healthy → api-2 healthy → scheduler only if it was running
  → `/health` must report the commit. The roll is `deploy/vps/deploy.sh`, also the manual and
  rollback path. `deploy.yml` (Fly) untouched.
- **S16-5 Human actions** (`fcf5bce`). H30 (prepare the VPS and first start, step by step);
  `vps_migration_plan.md` §3/§4/§11 updated for option B.
- **S16-6 Security review** (`8dd6532`, `SECURITY-REVIEW:`, Fable). 3 commits reviewed, 3
  issues found and fixed (below).

## Acceptance criteria (run locally, cycle 147)

| Criterion | Result |
|---|---|
| 1. `docker compose … config` succeeds with the example env | ✅ `docker compose --env-file compose.env.example config` with `AGENTX_SECRETS_FILE=./secrets.env.example`; also pinned in the test file |
| 2. Native rehearsal passes `smoke.sh`, incl. the real-caller-address check | ✅ `vps_rehearsal.py`: all 7 smoke checks; `client=127.0.0.1 (spoofed 203.0.113.77 ignored)`; plus `no-token-log` |
| 3. One API process stopped → `/health` through Caddy stays 200 | ✅ 20/20 answers 200 after api-1 was stopped |
| 4. `actionlint` clean; migrate before any container is replaced | ✅ `actionlint` clean; `deploy.sh` runs `migrate` before any `up -d`, pinned by tests (incl. against a fake `docker`) |
| 5. No secret values in `deploy/`; full suite green | ✅ grep for keys, tokens, JWTs and passworded URLs: nothing. Platform **3138 passed**, 608 skipped, 1 xfailed (H23) |

Also: `caddy adapt` accepts the site block. `shellcheck` reports only SC2015 *info* notes in
`smoke.sh` (`A && pass || fail`); `pass` always succeeds, so they are harmless.

## Sprint-close security review

Cycle 146 on Fable. **Reviewed 3 commits** (S16-2, S16-3, S16-4). **Found 3 issues, all fixed:**
(1) uvicorn wrote every live-update connection as `WebSocket /ws?token=<jwt>` into the log, so
login tokens ended up in server logs — **this is also true on Fly today**; a log filter now
replaces them with `REDACTED`. (2) Caddy's access log did the same; it now filters the token.
(3) The workflow would have failed on a private repository; it now checks `main` from its own
checkout and fails closed. 32 adversarial tests. Accepted, written up for DrJ: anything else on
Caddy's Docker network can reach the API directly (H29 asks what shares it); the `production`
environment must be limited to `main` (H30 step 8); the deploy key is root-equivalent on the VPS.

## What we learned

- **Logs leak what URLs carry.** A token in a query string is copied by every layer that logs
  URLs. Review every logger in the path, not only our own code.
- **No Docker daemon is fine if the rehearsal is honest.** Running the exact container commands
  natively behind a real Caddy caught real problems; the in-container start is the first thing
  H30 does on the VPS, before any traffic moves.
- **Reading human steps beside the files finds bugs.** S16-5 found that a root-only `600`
  secrets file would have broken every deploy (`root:deploy 640` is used instead).

## What we deferred (follow-ups)

- DrJ: H29 (Caddy network and subnet, Upstash region), then H30 after the merge. Cutover day
  (plan §9: DNS, Fly shutdown) is written up only when DrJ asks.
- If H29 shows Redis is far from the VPS (first sample 146 ms), the engine proposes moving it
  before cutover; the files do not change.
- If H29 shows other containers share Caddy's network, propose a dedicated Caddy-plus-AgentX network.
- Everything already open stays open (H11–H16, H23–H28, H13/H14).

## What changed strategically

The move off Fly is ready on paper and rehearsed locally; it now waits only on DrJ (merge, H29,
H30, then cutover). The log redaction fix improves Fly too, as soon as the branch is merged.

## How the engine ran (calibration for DrJ)

- 7 cycles (141–147). T1 (Fable) once, for the security review. T2 (Opus) for planning,
  compose, Caddy and smoke, the workflow and this close. T3 (Sonnet) for the human-action write-up.
- The local Docker CLI without a daemon was enough for `docker compose config`; Caddy was
  installed locally with Homebrew so the proxy layer was rehearsed, not assumed.

## Next

Sprint 18, the distribution sprint (MCP server, OpenClaw/Hermes skill, browser-agent join test,
"Join AgentX" page): the engine drafts its spec and decomposes it next cycle. Merge briefing
for this sprint: `briefing_2026-10-08_sprint16.md`.
