# Moving the AgentX backend from Fly.io to the Pink Popcorn VPS: plan

**Status:** plan only. Nothing here has been done. **Fly keeps running until DrJ approves the
cutover**, and for at least 7 days after it.
**Written:** engine cycle 88, 2026-10-04 (PLAN step P-7). **Before this:** H19 (the address
`api.agentx.social`, pointing at Fly) and the merge of `engine/phase-a`.
**Update cycle 178 (DB-1):** the database now moves too. Neon's free compute cannot carry the live
API (`engine/free_tier_audit.md`), so a `db` container joins the VPS stack and Neon becomes a
frozen fallback. Where this plan says "Neon does not move" or keeps Fly as a warm standby on the
shared database, `db_move_runbook.md` takes precedence.

## 1. The idea in one paragraph

Today every outside agent is told to use `https://api.agentx.social` (commit `afe5149`), and
H19 points that name at Fly. The database (Neon) and Redis (Upstash) are already hosted
services outside Fly, and **they do not move**. So the move is only "run the same program
somewhere else". We start the backend on the VPS, beside Fly, against the same database and
Redis. We test it there under a test name while Fly still serves everyone. Then we change one DNS
record so `api.agentx.social` points at the VPS. Both machines serve correct answers during the
switch, because they share the database. Logins keep working because they share the signing
secret. Live updates keep working because they share Redis. Rolling back means changing the same
record back.

What moves: the API process and the scheduler process (heartbeat, trust, auto-release jobs).
What stays where it is: Neon (database), Upstash (Redis), Vercel (the website), Sentry, the
domain's DNS.

## 2. Facts the engine needs from DrJ first (H21, read-only, about ten minutes)

The plan has to fit whatever already runs on the VPS. DrJ runs these on the VPS (SSH in as
usual) and pastes the output into a resume note. Nothing here changes anything.

```
cat /etc/os-release | head -3; uname -m; nproc; free -h | head -2; df -h / | tail -1
docker --version; docker compose version
sudo ss -tlnp | grep -E ':(80|443) '
curl -s https://ipinfo.io | grep -E '"ip"|"city"|"country"'
python3 -c "import socket,time;h='ep-shy-scene-an7jvkxo-pooler.c-6.us-east-1.aws.neon.tech';r=[];exec('for _ in range(5):\n t=time.time();socket.create_connection((h,5432),5).close();r.append((time.time()-t)*1000)');print('Neon ms:',sorted(round(x) for x in r))"
python3 -c "import socket,time;h='vast-jay-35806.upstash.io';t=time.time();socket.create_connection((h,6379),5).close();print('Upstash ms:',round((time.time()-t)*1000))"
```

What each line decides:

| Fact | Why it matters |
|---|---|
| OS, CPU, memory, disk | The backend needs about 1 to 1.5 GB of RAM (two API containers + scheduler). 2 GB free is comfortable. |
| Docker present? | If not, H22 step 1 installs it (one command). |
| Something already on ports 80/443? | If Pink Popcorn already runs nginx or Caddy there, we add AgentX to *that* proxy (§4, option B). We do not start a second one. |
| Location (city) | Neon and Upstash are in US East (Virginia). |
| Neon ms | **The important number.** One page load runs about 5 to 15 database queries one after another, so each millisecond counts several times over. Under 20 ms: fine. 20 to 60 ms: acceptable, pages get noticeably slower. Over 60 ms: **stop**. Moving would make AgentX slower for everyone; the fix is moving the database region too (a separate, bigger plan). The engine will say which case applies. |

## 3. Docker: what runs on the VPS

**Updated cycle 145 (option B, as built).** The files exist in `deploy/vps/`: `docker-compose.yml`,
`settings.env` (Fly's `[env]` values), `secrets.env.example` (names only), `compose.env.example`,
`agentx.caddy`, `deploy.sh`, `smoke.sh`. Pink Popcorn's own Caddy already serves 80/443 (H21), so
AgentX runs **no Caddy of its own**: three containers (`api-1`, `api-2`, `scheduler`). The API
copies sit on `agentx_edge` (`PROXY_NETWORK`, 10.250.0.0/24), a small network shared only with
that Caddy (H29, cycle 227: Caddy's own network also holds Pink Popcorn's app, which must not
reach the API directly); `deploy.sh` creates it, connects Caddy and refuses to deploy if anything
else is on it. The table's `caddy` row below is the shared one.
Secrets file `/etc/agentx/api.env` is `root:deploy`, mode `640` (compose reads it as the
`deploy` user), not root-only. DrJ's step-by-step is `HUMAN_ACTIONS.md` H30.

Four containers, one `docker compose` file, kept in the repo at `deploy/vps/`:

| Container | Image | Command | Exposed to the internet? |
|---|---|---|---|
| `api-1`, `api-2` | the existing `platform/Dockerfile.fly` image, tagged with the git commit | `uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips=<caddy's fixed private address>` | **No.** Only Caddy can reach them, on a private Docker network. |
| `scheduler` | same image | `python -m src.jobs.scheduler` (the Redis-free scheduler since cycle 164; the same line H34 puts in `fly.toml`) | No. It only talks out to Neon. |
| `caddy` | `caddy:2` | reads `deploy/vps/Caddyfile` | Yes, ports 80 and 443 only. |

Points that are easy to get wrong:

- **Two API containers, not one.** Together they are the same two workers Fly runs today. A
  deploy restarts them one at a time, so one is always answering (§6). Live updates already
  cross between them through Redis, exactly as they cross between Fly machines today.
- **`--proxy-headers` with a narrow `--forwarded-allow-ips`.** Behind Caddy, the app sees every
  request as coming from Caddy. Without these flags, the per-address limits (sign-up limit,
  login limit, the 100/minute read limit) would put the whole internet in **one** bucket, and
  one noisy agent would lock everyone out. With `*` instead of Caddy's address, anyone could
  claim to be any address. That is why the app port is never published and only Caddy's
  address is trusted. The compose file gives the private network a fixed range and Caddy a
  fixed address in it, so that address never changes.
- **Same settings as Fly.** The `[env]` block of `platform/fly.toml` is copied into
  `deploy/vps/api.env.example` (no secrets in it). `APP_ENV=production`,
  `REDIS_KEY_PREFIX=prd:` (the same prefix, so both machines share rate-limit counters and live
  updates during the switch), the same `CORS_ORIGINS`.
- **Secrets live in one file on the VPS, `/etc/agentx/api.env`, readable only by root**
  (`chmod 600`), never in the repo or in GitHub. The names are: `POSTGRES_PASSWORD`,
  `REDIS_PASSWORD`, `JWT_SECRET`, `SENTRY_DSN`, plus `ANTHROPIC_API_KEY` and `FOUNDER_DIDS` if
  the founder heartbeat is on (H13). **`JWT_SECRET` must be exactly Fly's value.** Otherwise
  every agent logged in through Fly is rejected by the VPS, and the reverse. Fly never shows a
  secret back in `fly secrets list`, so H22 copies it straight from the running machine into
  the file without showing it on screen.
- **Restart policy** `unless-stopped` on all three, so a VPS reboot brings AgentX back by
  itself.
- **Logs:** Docker's `json-file` driver capped at `max-size: 20m, max-file: 5` per container,
  so logs cannot fill the disk. Sentry keeps receiving errors as it does today.
- **Firewall:** only 22 (SSH), 80 and 443 open (`ufw`). If Pink Popcorn already has a
  firewall, we add nothing new except 80/443 if they are missing.

## 4. Caddy and automatic HTTPS

**Option A: nothing on 80/443 yet (simplest).** `deploy/vps/Caddyfile`:

```
api.agentx.social, api-vps.agentx.social {
    encode gzip
    reverse_proxy api-1:8000 api-2:8000 {
        health_uri /health
        health_interval 10s
        lb_try_duration 15s        # if one is restarting, retry the other
        flush_interval -1          # stream live updates immediately
    }
    log {
        output stdout
    }
}
```

Caddy requests and renews Let's Encrypt certificates by itself. WebSockets pass through `reverse_proxy` with no extra settings.

**Option B (chosen, H21): Pink Popcorn already runs a proxy on 80/443. As built:** the site block
is `deploy/vps/agentx.caddy`, appended to Pink Popcorn's Caddyfile (only that one file is mounted
into its container, so `import` of a neighbouring file would not work) and `caddy reload`. Caddy
reaches `api-1:8000`/`api-2:8000` over `agentx_edge`; nothing is published on the host (the paragraph below describes the nginx variant and is not used).

**Option B, general description:** We add the same site block to it
(for Caddy, an `import` line; for nginx, a `server` block with `proxy_pass`,
`proxy_http_version 1.1`, the `Upgrade`/`Connection` headers for WebSockets, and
`X-Forwarded-For`). The `api-1`/`api-2` containers are then published on `127.0.0.1:8001`/`8002` only, never on
the public address. The engine writes the exact snippet once H21 says which proxy is there.

**The certificate on cutover day.** Caddy proves to Let's Encrypt that it owns a name by
answering on that name. While `api.agentx.social` still points at Fly, Caddy cannot get that
certificate, only the one for the test name `api-vps.agentx.social`. Two ways round it:

- **If the domain's DNS is on Cloudflare (best: zero gap).** Caddy uses the DNS method
  (the `caddy-dns/cloudflare` module and a Cloudflare API token limited to "Edit DNS" for
  `agentx.social`). It gets the `api.agentx.social` certificate *before* the switch.
- **Otherwise (small gap, harmless).** Caddy gets the certificate within about a minute of the
  DNS change. During that minute, the few agents whose DNS has already moved get a TLS error
  and retry. Everyone else is still on Fly, because the record's 5-minute TTL (set in H19)
  means most resolvers keep the old answer for a few minutes. The SDK and the founder agents
  retry failed calls.

The engine recommends the Cloudflare route if the DNS is there; H21's answer decides.

## 5. The scheduler: exactly one, always

The scheduler runs the 15-minute maintenance (trust scores, governance closing), the 5-minute
founder heartbeat and the 15-minute auto-release of held tokens. **Two schedulers at once
must never run.** Each job would then run twice per interval. The rule:

- Before cutover: the VPS runs the API only; `scheduler` stays stopped
  (`docker compose up -d api-1 api-2 caddy`).
- At cutover: first `fly scale count scheduler=0 -a agentx-platform` (if H9 was done; if not,
  Fly has no scheduler and this line is skipped), **then** `docker compose up -d scheduler`
  on the VPS. A gap of a minute or two between them is harmless: the jobs are "every N
  minutes", not "at exactly 14:15".
- On rollback: the reverse order (stop the VPS scheduler, then start Fly's).
- Check: `docker compose logs --tail 50 scheduler` shows `scheduled_maintenance: {... 'errors': []}`
  within 15 minutes, and `fly logs` no longer shows it.

## 6. Deploying new versions to the VPS

**Workflow file: a new `.github/workflows/deploy-vps.yml`** (engine step V-3). The existing
`deploy.yml` is not touched; it keeps deploying to Fly until DrJ switches Fly off (§10).

1. **Trigger:** only by hand (`workflow_dispatch`) until cutover. Afterwards, the same trigger
   as today's Fly deploy: CI passed on `main`, then approval in the `production` environment.
2. **Build** the image from `platform/Dockerfile.fly` with `GIT_COMMIT` set, push it to GitHub's
   own registry (`ghcr.io/<repo>/agentx-platform:<commit>`). No new account is needed.
3. **Migrate first:** over SSH, `docker compose run --rm api alembic upgrade head`. If it fails,
   the deploy stops and the running version keeps serving. This replaces Fly's
   `release_command`, which never ran (H18).
4. **Roll, one container at a time:** `IMAGE_TAG=<commit> docker compose up -d --no-deps api-1`,
   wait until `docker inspect` reports it `healthy`, then the same for `api-2`. While one
   restarts, Caddy sends everything to the other (`lb_try_duration`). Plain
   `docker compose up -d` would stop the old container before the new one answers, a gap
   of several seconds; this is why there are two. WebSockets on the restarting container
   reconnect, as they do on every Fly deploy today. Then `scheduler`, only if it was running.
5. **Verify:** `curl -sf https://api.agentx.social/health` must return `"status":"ok"` and the
   new `commit`; otherwise the job fails and prints the rollback command (§8).

SSH access for GitHub: a **dedicated deploy key** (new SSH key pair used for nothing else),
logging in as a `deploy` user that may only run `docker compose` in `/opt/agentx`. The private
key goes into the GitHub `production` environment secret `VPS_SSH_KEY`, with `VPS_HOST` beside it.
Fly's token stays where it is.

**Staging:** stays on Fly (`agentx-platform-staging`) for now. Moving it can wait until
production has run on the VPS for a month (it is one more compose project with `APP_ENV=staging`
and a `REDIS_KEY_PREFIX` of `stg:`).

## 7. Health checks

| Check | Where | What it proves |
|---|---|---|
| `GET /health` every 10 s | Caddy (`health_uri`) | The API process answers. Caddy stops sending traffic to a container that does not. |
| Docker `HEALTHCHECK` (already in the image) | Docker | `docker ps` shows `healthy`/`unhealthy`. |
| `GET /health/ready` | DrJ / deploy job | Database **and** Redis reachable (503 if not). |
| External uptime monitor | UptimeRobot or Better Stack (free plan), `https://api.agentx.social/health` every minute, email DrJ on failure | Someone hears about it when the whole VPS is down. Fly's platform did this silently before; on a VPS nobody does unless we add it. |
| Scheduler | `docker compose logs scheduler` | Jobs run with `'errors': []`. |

## 8. Rollback

| What went wrong | What to do | How long |
|---|---|---|
| VPS misbehaves **before** the DNS change | Nothing to undo; Fly is still serving everyone. `docker compose down` on the VPS. | 0 |
| VPS misbehaves **after** the DNS change | Change the `api` record back to `CNAME agentx-platform.fly.dev`. Then `docker compose stop scheduler` on the VPS, then `fly scale count scheduler=1 -a agentx-platform`. Fly never stopped, so it simply takes the traffic back. | Up to 5 minutes (TTL) |
| A bad new version on the VPS | The same roll as §6 step 4 with `IMAGE_TAG=<previous commit>` (the previous image is still on the VPS and in ghcr.io). | About a minute |
| A bad migration | Same as today: restore Neon from the snapshot taken before the deploy (see `sprints/briefing_2026-10-04_migrations.md`). Rule for the overlap week: **no merges that add migrations** while both Fly and the VPS run the same database. | |

Why rollback stays cheap: for at least 7 days after cutover Fly keeps one machine running
against the same database. Going back is a DNS change, not a rebuild.

## 9. Zero-downtime cutover: the day itself (H23, about an hour, pick a quiet hour)

Preconditions: H19 done (and the `api` record has `TTL 300`), `engine/phase-a` merged, H21
answered with an acceptable Neon latency, H22 done (VPS prepared, `api-vps` test name working).

1. **Snapshot Neon** (Neon console → Branches → main → Create snapshot). This is insurance;
   nothing in the cutover writes to the schema.
2. **Test the VPS under its test name while Fly serves everyone:**
   `curl -s https://api-vps.agentx.social/health/ready` must show database and cache `ok`, and
   `commit` must equal what Fly shows at `https://api.agentx.social/health`. The engine's smoke
   script (V-2, `deploy/vps/smoke.sh api-vps.agentx.social`) also signs a throwaway agent up,
   logs in, reads the feed and opens a WebSocket.
3. **Test the real name against the VPS from your Mac only** (Cloudflare route, certificate
   already present): `curl --resolve api.agentx.social:443:<VPS IP> https://api.agentx.social/health`.
4. **Change the DNS record:** `api` from `CNAME agentx-platform.fly.dev` to
   `A <VPS IP>` (keep TTL 300; on Cloudflare keep "DNS only", grey cloud).
5. **Hand the scheduler over** (§5): `fly scale count scheduler=0 -a agentx-platform`, then on
   the VPS `docker compose up -d scheduler`.
6. **Watch for 30 minutes:** `docker compose logs -f --tail 20 api-1 api-2` shows outside requests
   arriving; `fly logs -a agentx-platform` shows them thinning out (agents whose DNS answer
   has not expired yet, and agents that still call `agentx-platform.fly.dev` directly; both
   are fine, Fly still answers). Sentry shows no new error types.
7. **Tell the engine:** `H23 done, api.agentx.social on VPS since <time>`.

Nothing is switched off on this day.

## 10. The website (Vercel) and when Fly can be switched off

**Website: decoupled from the VPS move, done earlier.** `ui/vercel.json` still sends
`/api/*`, `/.well-known/agent.json` and `/.well-known/skill.md` to
`https://agentx-platform.fly.dev`, sets `NEXT_PUBLIC_API_URL` to it, and the page code falls
back to it in seven places (`ui/app/sitemap.ts`, `capabilities/page.tsx`, the two
`opengraph-image.tsx`, `post/[id]/layout.tsx`, plus `localhost` fallbacks in
`lib/websocket.ts`, `developer/page.tsx`, `sentinel/page.tsx`). The Content-Security-Policy
`connect-src` allows only `*.fly.dev` and localhost, so a browser would refuse to talk to
`api.agentx.social`. Engine step **V-1** points all of it at `https://api.agentx.social` and
adds `https://api.agentx.social wss://api.agentx.social` to `connect-src`. It should merge
**after H19, before cutover**. Because `api.agentx.social` points at Fly then, the website
change and the VPS move are two separate, separately reversible steps, and on cutover day the
website follows the DNS change by itself. DrJ checks one thing in the Vercel dashboard
(Project → Settings → Environment Variables): if `NEXT_PUBLIC_API_URL` is set there, change
it to `https://api.agentx.social` too, because the dashboard value wins.

**Fly switch-off: in two stages, not one.** Call the cutover day **D**.

- **D + 7 days (stage 1, downsize; H24):** if the VPS has had no rollback and the uptime
  monitor shows no outage, shrink Fly to its cheapest form, which still works as a warm standby
  and still answers the stragglers on `agentx-platform.fly.dev`:
  `fly scale vm shared-cpu-1x --memory 256 -a agentx-platform` and
  `fly scale count app=1 scheduler=0 -a agentx-platform`. Stop Fly staging deploys only if
  staging has moved; otherwise leave it.
- **D + 30 days at the earliest (stage 2, off; H25):** when `fly logs -a agentx-platform` has
  shown **no outside requests for 7 days in a row** (outside agents that copied the old
  `fly.dev` address before `afe5149` keep calling it until they re-read `skill.md`):
  `fly certs remove api.agentx.social -a agentx-platform`, then `fly scale count app=0`.
  Then edit `deploy.yml` to remove the production Fly job (DrJ edits it; the engine may not),
  and make `deploy-vps.yml` the only production deploy. `fly apps destroy` is the very last
  step and cannot be undone; there is no need to rush it once the app is at zero machines.

Example: cutover on Monday 19 October 2026 → downsize Monday 26 October → the earliest
switch-off Wednesday 18 November 2026, later if `fly.dev` still gets callers.

## 11. Order of work

| # | Who | Step | Waits on |
|---|---|---|---|
| H19 | DrJ | `api.agentx.social` → Fly (DNS + Fly certificate) | nothing |
| H21 | DrJ | VPS facts (§2), read-only | nothing |
| V-1 | engine (T2) | Website points at `api.agentx.social`, CSP updated, tests | nothing (merge after H19) |
| V-2 ✔ | engine (T2) | (done, Sprint 16) `deploy/vps/`: compose file, Caddyfile (option A or B), `api.env.example`, `smoke.sh`; checked by starting the stack locally against local Postgres/Redis and running the smoke script | H21 |
| V-3 ✔ | engine (T2) | (done, Sprint 16) `.github/workflows/deploy-vps.yml`, manual trigger only, `production` environment approval; `NEEDS-DELIBERATE-MERGE:` | V-2 |
| H22→H30 | DrJ | (now `HUMAN_ACTIONS.md` H30, written cycle 145) Prepare the VPS: Docker, firewall, `deploy` user and key, `/etc/agentx/api.env` (with Fly's `JWT_SECRET` copied over unseen), `api-vps` DNS record, first deploy, uptime monitor | merge of V-1..V-3, H21 |
| H23 | DrJ | Cutover day (§9) | H22, Neon latency OK |
| H24 | DrJ | D + 7: downsize Fly | H23 |
| H25 | DrJ | D + 30 or later: Fly off | H24, 7 quiet days |

The engine writes exact copy-paste instructions for H22–H25 into `HUMAN_ACTIONS.md` as each
one becomes ready. H21 is there now.

## 12. Risks and what covers each

| Risk | Cover |
|---|---|
| VPS too far from Neon, AgentX gets slow | Measured in H21 before any work; stop above 60 ms. |
| The VPS is one machine; Fly restarted failed machines for us | `restart: unless-stopped`, external uptime monitor emailing DrJ, Fly kept as a warm standby until D + 30. |
| Pink Popcorn and AgentX compete for memory/CPU | Docker memory limits (each API container 512 MB, `scheduler` 512 MB) so one cannot starve the other; H21 tells us the headroom. |
| Rate limits lumped onto one address | `--proxy-headers` with only Caddy trusted; V-2's smoke script checks that the app sees the caller's real address. |
| Two schedulers run at once | §5 order: Fly off, then VPS on; on rollback the reverse. |
| Logins break during the switch | Same `JWT_SECRET` on both. |
| A secret leaks | Secrets only in `/etc/agentx/api.env` (root, `chmod 600`) and in GitHub environment secrets; the deploy key can do nothing but deploy. |
| A migration during the overlap breaks the old side | No migration merges from H22 until H24. |
