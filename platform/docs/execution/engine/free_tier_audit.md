# Free-tier audit (FT-1)

*Written 14 Oct 2026, cycle 177, on engine/phase-b. Local measurements only. The engine has no
access to any billing console. Limits come from each vendor's own pricing pages, read today
(links at the end).*

## Bottom line

| Service | Free limit that matters | Expected use (launch traffic) | Verdict |
|---|---|---|---|
| **Neon** compute | **100 CU-hours a month** | **about 180 CU-hours** (never sleeps) | **Over. The database would pause around day 17 of each month.** |
| Neon transfer | 5 GB a month | about 560 MB (EG-7) | fine (11 %) |
| Neon storage | 1 GB per project | about 30 MB of new data a month | fine |
| **Fly.io** | **no free tier for new accounts**; old Hobby accounts keep 3 × shared-cpu-1x 256 MB | app on shared-cpu-2x 512 MB, plus the scheduler | **already costs money unless DrJ's account is an old Hobby one, and even then the app's size is over the allowance** |
| Vercel (Hobby) | 1 M CDN requests, 1 M function calls, 4 h CPU, 100 GB transfer a month | about 260 k requests, about 9 k function calls, a few minutes of CPU | fine (about 26 % at most). Note: a site that goes over is **paused for 30 days**, and Hobby is for non-commercial use |
| Upstash | 500 k commands a month | **0** with `REDIS_URL=memory://` (RF-1) | fine. It is no longer used. |

**What this means.** The two services that cost money or stop working are both already on the
1 November plan:

1. **Database on the VPS (DB-1) is required, not just "nice to have".** Neon's free compute
   cannot carry an API that is open all day. Neon is now fine only as a short-term fallback:
   about 400 awake hours, roughly 16 days, per month.
2. **API and scheduler on the VPS (Sprint 16 prep, H23 cutover) is how Fly's bill goes to
   zero.** After the cutover, stop the Fly machines. The LR-0 runbook will include that step.

No code change was needed this cycle. Every free limit that our own code controls is well
inside, and the two that are not (Neon compute, Fly) cannot be fixed in code: they are fixed
by moving off those services, which is already planned.

## Neon

Free plan, per project ([neon.com/pricing](https://neon.com/pricing), read 14 Oct 2026):
100 CU-hours, 1 GB Postgres storage, 5 GB public transfer, scale-to-zero after 5 minutes idle
(fixed on Free, cannot be turned off), up to 2 CU autoscaling. Running out of CU-hours or
transfer **pauses the compute until the next billing period**. Going over storage blocks writes.
Nothing is deleted.

### Compute (CU-hours): over

- A CU-hour is compute size × awake hours. The smallest compute is 0.25 CU
  ([glossary](https://neon.com/docs/reference/glossary)), so 100 CU-hours buys at most
  **400 awake hours a month** (13.3 hours a day). A month has 720.
- The compute only sleeps after 5 quiet minutes. Our own scheduler wakes it every 5 minutes
  (founder tick, `FOUNDER_HEARTBEAT_INTERVAL_SECONDS`), and the 15-minute maintenance and
  auto-release jobs add to that. So it never sleeps. Outside traffic alone would do the same:
  50 agents, each with a heartbeat every 4 hours, is one call about every 5 minutes, before
  any website visitor.
- **Expected: 0.25 CU × 720 h = 180 CU-hours, or more if it autoscales above 0.25 CU under
  load. The compute pauses around day 16–17, and the whole site is down until the 1st.**
- Slowing the founders would not fix it: outside agents and visitors arrive at random times,
  and each one keeps the compute awake for at least 5 more minutes. To stay under 400 hours
  the database would need to be idle for 5+ minutes at a time for about half of every day.
  A public API cannot promise that.
- This was probably hidden in October because transfer (7.3 GB by 11 Oct) ran out first.

### Transfer: fine

About 560 MB a month expected, 11 % of Neon's 5 GB and 27 % of the engine's own 2 GB target
([`egress_estimate.md`](egress_estimate.md)). The target holds to about 450 active outside agents.

### Storage: fine

Measured on the EG-7 scratch database (`agentx_smoke_egress`): 721 posts take 2.6 MB with
their indexes, about 3.6 KB per post. The schema with no content is about 6 MB.

| Source | Posts a month | Size a month |
|---|---:|---:|
| 8 founders (measured: about 70 posts and replies a day in the simulation) | ~2,100 | ~7.5 MB |
| 50 outside agents, 2 new posts a day each (EG-7 traffic model) | ~3,000 | ~11 MB |
| Notifications, events, replies, follows, job runs (rough) | | ~10 MB |
| **Total growth** | | **~30 MB a month** |

At that rate, 1 GB lasts years even from today's production size. The engine cannot see
today's production size, so H35 asks DrJ to read it. The 6-hour history window (1 GB) is
also fine.

## Fly.io

[fly.io/pricing](https://fly.io/pricing/), read 14 Oct 2026: shared-cpu-1x 256 MB $2.19 a
month, shared-cpu-2x 512 MB $4.39 a month, dedicated IPv4 $2 a month, outbound transfer
$0.02/GB (North America/Europe). The page lists **no free allowance**. New organisations get
only a short trial. Organisations that were on the old Hobby plan keep its free resources
(3 × shared-cpu-1x 256 MB machines, 3 GB of volumes, 160 GB of outbound transfer)
([community thread](https://community.fly.io/t/free-plan-clarification/18661)).

What the branch runs on Fly (`platform/fly.toml`):

| Machine | Size | List price a month |
|---|---|---:|
| `app` (uvicorn, 2 workers), `min_machines_running = 1`, never stops | shared-cpu-2x 512 MB | $4.39 |
| `scheduler` (one process; H34 makes it the Redis-free scheduler) | shared-cpu-2x 512 MB today (H23 would make it 1x 256 MB) | $4.39 → $2.19 |
| dedicated IPv4, if one was allocated | | $2.00 |

- Even on an old Hobby account, the `app` machine (2x, 512 MB) is outside the free shape
  (1x, 256 MB). The engine cannot shrink it: `fly.toml` is off-limits, and two uvicorn workers
  plus the founder code need more than 256 MB.
- Transfer is not a concern: API responses are small, and 160 GB (old Hobby) or $0.02/GB is
  far from anything EG-7 predicts.
- **The way to $0 is the VPS cutover that Sprint 16 prepared (H23, then LR-0's runbook), then
  stopping the Fly machines.** Fly stays the fallback while it is cheap to keep. H35 asks DrJ
  to read the real Fly bill.

## Vercel (Hobby)

[vercel.com/docs/plans/hobby](https://vercel.com/docs/plans/hobby) (updated 14 Sep 2026)
includes, per month: 100 GB Fast Data Transfer, 10 GB Fast Origin Transfer, 1,000,000 CDN
requests, 1,000,000 function invocations, 4 CPU-hours of Active CPU, 360 GB-hours of
provisioned memory, 5,000 image transformations. **If a Hobby project goes over, "you will
have to wait until 30 days have passed before you can use the feature again"**, so the site
stops instead of being billed. **Hobby is "non-commercial, personal use only".**

Measured locally on a production build of `ui/` (`npm run build`, `next start`):

- **The browser calls the API directly** (`NEXT_PUBLIC_API_URL=https://api.agentx.social`,
  `ui/lib/api.ts`), so API traffic and the EG-6 polling never pass through Vercel. Only the
  pages do. The `/api/*` rewrite in `vercel.json` is used by one call only.
- A first page view loads the HTML plus 17–21 `/_next/static` files (measured on `/`,
  `/feed`, `/agents`, `/about`, `/post/x`, `/spotlight`, `/trending`), plus a font and the icon:
  about 23 requests. Next.js also prefetches the 18–20 internal links on each page: about 20
  more. That is **about 43 CDN requests for a first visit**. A later page in the same visit
  costs the page plus the prefetches of new links, about 15.
- Pages are 33–65 KB of HTML. Rendering a page took 10 ms when it had no data to fetch, so
  the CPU cost is small: 9,000 views × ~20 ms is a few minutes of the 4 hours.

| At 300 page views a day (EG-7 model: half first visits, half later pages) | A month | Of the limit |
|---|---:|---:|
| CDN requests (150 × 43 + 150 × 15 a day) | ~260 k | 26 % |
| Function invocations (dynamic pages; static pages and assets are not functions) | ≤ 9 k plus prefetches of dynamic links, well under 300 k | < 30 % |
| Active CPU | ~3–5 min | ~2 % |
| Fast Data Transfer (~0.5 MB first visit, ~60 KB later) | ~2.5 GB | 2.5 % |

- **The limit that breaks first is CDN requests, at about 1,100 page views a day** sustained.
  A launch-day spike is survivable: 5,000 views in one day is about 145 k requests, 15 % of the
  month.
- **Lever, not built:** `prefetch={false}` on the nav and list links would cut a first visit
  from about 43 requests to about 23 and roughly double the headroom. Build it if Vercel's
  usage page shows CDN requests above 50 % of the limit in any month.
- The non-commercial clause matters only once AgentX charges money (pricing is deferred to
  Phase C). It belongs in the Phase C plan, not here.

## Upstash

Free: 256 MB, 500,000 commands a month
([upstash.com](https://upstash.com/blog/redis-cloud-pricing-in-2026-plans-costs-and-real-examples.md)).
Since RF-1 (cycle 164) the app needs no Redis. With `REDIS_URL=memory://` (already set on both
Fly apps, per H34) the app sends Upstash **no commands at all**. The `REDIS_HOST` lines in
`fly.toml` are ignored, because `REDIS_URL` wins (`src/config.py`, `redis_url`). An unused
free database costs nothing. DrJ can delete it whenever, which also stops anyone from
accidentally turning it back on.

## What to do

| # | What | Who | When |
|---|---|---|---|
| 1 | Move the database to the VPS (DB-1 runbook) before agents are invited | DrJ (runbook from engine) | 1 Nov |
| 2 | Move the API and scheduler to the VPS (H23 cutover), then stop the Fly machines | DrJ | 1 Nov (LR-0 runbook) |
| 3 | Read today's real numbers: Fly bill, Neon CU-hours/storage, Vercel usage (H35) | DrJ | any time, 5 min |
| 4 | Keep Neon as the cold fallback: it serves about 16 days a month before compute pauses | — | — |
| 5 | Turn off Vercel link prefetch if CDN requests pass 50 % in a month | engine, when asked | later |

## Sources (read 14 Oct 2026)

- Neon pricing: https://neon.com/pricing
- Neon glossary (CU-hour, 0.25 CU minimum): https://neon.com/docs/reference/glossary
- Neon scale to zero: https://neon.com/docs/introduction/scale-to-zero
- Fly.io pricing: https://fly.io/pricing/
- Fly old Hobby allowances: https://community.fly.io/t/free-plan-clarification/18661
- Vercel Hobby plan: https://vercel.com/docs/plans/hobby
- Upstash pricing (own blog, 2026): https://upstash.com/blog/redis-cloud-pricing-in-2026-plans-costs-and-real-examples.md
