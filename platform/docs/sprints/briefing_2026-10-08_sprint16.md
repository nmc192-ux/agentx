# Briefing — 8 October 2026 (AgentX Build Engine, Sprint 16 close)

## Bottom line
Everything needed to move the API from Fly.io to your VPS is written and rehearsed on this Mac:
a compose file, the site block for your existing Caddy, a smoke test, a deploy workflow you
start by hand, and step-by-step instructions (H30). **Nothing was deployed and nothing ran on
the VPS.** It is on `engine/phase-b`, **not merged**. Merging deploys nothing to the VPS; it
does change one thing on Fly: login tokens stop appearing in the server logs (a fix found in
the security review). The engine carries on; you do not need to stop it.

## Stopping reason
None. This is a mid-phase sprint close. Status: `CONTINUE`.

## What shipped (on `engine/phase-b`, not yet merged)
The branch is 84 commits ahead of `main` (Sprints 13, 14, 15, 17 and 16); 15 are marked
`SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:`, 4 of them from this sprint. No migrations in
this sprint (Sprint 17's migration 048 is still on the branch). Details: `sprint_16_retro.md`.

1. `deploy/vps/`: compose file (two API copies, scheduler and migrate only when asked), the
   Caddy site block, `smoke.sh`, `deploy.sh` (the roll, also used for rollbacks), settings
   copied from Fly with no secrets.
2. `.github/workflows/deploy-vps.yml`: "Deploy to VPS", runs only when you press "Run
   workflow" and approve it in the `production` environment.
3. A log filter so login tokens never reach the API's logs (Fly today and the VPS later).
4. H29 and H30 in `HUMAN_ACTIONS.md`; `vps_migration_plan.md` updated for sharing Caddy.

## Model usage
7 cycles: Fable once (security review), Opus for building, planning and this close, Sonnet
once (human-action write-up).

## Test results (local, cycle 147)
Platform 3138 passed, 608 skipped, 1 expected fail (waits on H23). Native VPS rehearsal passed:
all smoke checks through a real Caddy, a faked caller address ignored, no token in any log,
and with one API copy stopped `/health` answered 200 twenty times out of twenty.
`docker compose config`, `actionlint` and `caddy adapt` clean; no secrets in `deploy/`.

## What merging will do
- **CI on `main`** runs, then Deploy sends the backend to staging and, after your approval, to
  production, as usual. Sprint 17's migration 048 is still in this merge (see the Sprint 17
  briefing); this sprint adds none.
- **On Fly, two log changes only:** live-update connections are logged with `token=REDACTED`
  instead of the real login token, and each request line shows `client=<address uvicorn sees>
  fwd=<X-Forwarded-For header>`. On Fly `client=` will show Fly's own proxy address; the
  caller's address is still there under `fwd=`. No behaviour change for users.
- **A new workflow "Deploy to VPS"** appears under Actions. It never runs by itself. If someone
  pressed "Run workflow" before H30, it would stop at your `production` approval, and without
  the VPS secrets it would fail before touching anything.
- **Nothing happens on the VPS, in DNS or at Hostinger.** `deploy.yml` (Fly) and `fly.toml`
  are unchanged.
- **To undo:** revert the merge commit on GitHub.

## Decisions I made (reversible)
- Share Pink Popcorn's Caddy through its Docker network (option B); publish no host port.
- Trust forwarded headers only from that network's subnet; the API refuses to start with `*`.
- Roll logic lives in `deploy/vps/deploy.sh` so the workflow, a manual run and a rollback
  (`SKIP_MIGRATE=1`) do exactly the same thing.
- The secrets file on the VPS is `root:deploy 640`, not root-only, so compose can read it.

## Decisions I need from you
None now. H29 (about five minutes, read-only) answers the last open facts: Caddy's network
name and subnet, what else is on that network, and where Upstash Redis lives.

## Recommended next action
1. Merge `engine/phase-b` when convenient (PR into `main`, mark it ready, wait for green,
   "Create a merge commit"); it still carries migration 048, so watch the staging deploy log.
2. Do H29 any time (it changes nothing).
3. When you want to start the move: H30, then ask the engine for the cutover-day write-up.

## Live-test checklist for after you merge
- [ ] Deploy workflow green on staging and production; `https://api.agentx.social/health`
      returns 200.
- [ ] In the Fly logs (`fly logs -a agentx-platform`), open the website feed once so a
      live-update connection is made: the line shows `token=REDACTED`, never a long `eyJ…` string.
- [ ] Request lines show `client=… fwd=…`.
- [ ] Under GitHub → Actions, "Deploy to VPS" is listed and has **no** runs.
- [ ] Everything on the Sprint 17 checklist still applies (spotlight routes, skill.md, website).
