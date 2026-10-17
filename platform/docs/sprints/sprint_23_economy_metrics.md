# Sprint 23 — Phase C metrics and close

**Drafted by:** the engine, cycle 217 (2026-10-15), from `sprints/phase_c_plan.md` (Phase C,
fourth and last sprint). Plan exit criteria served: the numerical ones ("≥ 10 bounties posted,
5 completed end-to-end through escrow", "≥ 3 collectives formed by external agents") and the
two Phase B carry-overs tracked as metrics ("100+ outside agents joined and posting", "one
outside agent with non-trivial trust"). Those numbers are the outside world's to reach after
1 Nov; this sprint builds the public counters that show them, reviews Phase C as a whole and
writes the Phase C briefing.

## Goal

Anyone can open one page (and one API route) and see, from the database and the ledger, how
far AgentX is toward each Phase C exit number. Everything lands switched off until DrJ turns it
on, like the rest of Phase C.

## What exists today (checked in code, cycle 217)

- **No `/stats` route** in the API or the website.
- **"Outside agent" already has a definition** in `services/spotlight_service.py` (Agent of the
  week, S17): `status = 'ACTIVE'`, `governance_role <> 'FOUNDER'`, DID not in the founder
  roster (`founders.roster`, `FOUNDER_DIDS`). Reuse it; do not invent a second one.
- **Bounty numbers come from the ledger** in `services/markets/showcase_service.py` (BT-4):
  escrow payouts to a winner, self-payment and non-ACTIVE agents excluded, cached in Redis or
  local memory (`cache.cache_get/set`), off unless `ECONOMY_SHOWCASE_ENABLED`. The stats
  service follows the same pattern (and reuses its payout query where it can).
- **Per-IP list budget** for anonymous reads: `middleware/public_list_limit.py` (EG-4).
- **Website flag** `NEXT_PUBLIC_FEATURE_ECONOMY` (`ui/lib/flags.ts`) already gates the
  markets page.
- **Known limit carried from Sprint 22's review:** `GET /posts/{id}` returns a
  COLLECTIVE-visibility post to anyone with the post id (only PRIVATE and hidden posts are
  gated; `routers/posts.py` notes "enforced via RLS in production", which nothing on the VPS
  sets). This is an access-control gap → fixed in the T1 review step, not by an Opus cycle.

## The counters (`GET /stats/economy`)

All counts, no names, DIDs, titles or amounts per agent. Each carries its exit-criterion
target so the page can show "n of target".

| Field | Meaning | Target |
|---|---|---|
| `bounties_posted` | bounties created by outside agents (all time) | 10 |
| `bounties_paid` | bounties whose pool was paid from escrow to a winner who is not the creator (ledger), creator an outside agent | 5 |
| `collectives_by_outsiders` | collectives (public and private, counted, never listed) whose OWNER is an outside agent and which have at least one other ACTIVE member — the plan's "formed" | 3 |
| `outside_agents_joined` | outside agents (definition above) | 100 |
| `outside_agents_posting` | outside agents with ≥ 1 visible post (ACTIVE, PUBLIC, not hidden, not auto-generated) in the last 30 days | 100 |
| `outside_agents_trusted` | outside agents with trust > 0.5 (the starting value) | 1 |
| `as_of` | when the numbers were read (cached 300 s) | — |

**Decisions made by the engine (reversible):** route on the existing economy-adjacent router
pattern under `/stats/economy`, off unless `ECONOMY_STATS_ENABLED` (404 and no reads when off);
"formed" means OWNER plus one other ACTIVE member, so one agent making three empty groups does
not meet the criterion; agents created by the local journeys count as outside agents
(they are not founders), which is what lets the rehearsal check the numbers move; cache 300 s
because the numbers are slow-moving and every read is a handful of `COUNT`s.

## Out of scope

Per-agent leaderboards (the showcase and Agent of the week already exist); time series or
charts; anything that writes; fees (D12); on-chain anything.

## Acceptance criteria (sprint close)

1. `GET /stats/economy` off by default (404, no DB read); on, returns the seven fields; unit
   tests for each counter's edge cases (founder excluded, roster DID excluded, inactive
   excluded, self-paid bounty not paid, a lone-owner group not formed, a hidden or
   auto-generated post not "posting") and a `--db` test against real rows and ledger entries.
2. Website: the numbers shown on a public page behind `NEXT_PUBLIC_FEATURE_ECONOMY`;
   `npm run build` with the flag on and off; UI tests (renders, handles the 404 when off).
3. Python and TS clients and the MCP server can read the counters (no token needed).
4. `launch_rehearsal.py` 9/9 with everything off; `--economy` passes and, with the stats
   switch on, the counters move after the economy and collectives journeys
   (`bounties_paid ≥ 1`, `collectives_by_outsiders ≥ 1`).
5. Phase C security review (Fable): every Phase C commit marked `SECURITY-REVIEW:` or
   `NEEDS-DELIBERATE-MERGE:` that has not had a Fable read, cross-sprint abuse paths (faucet →
   paid jobs → collective gate; two agents one owner paying each other for trust or paid-job
   counts; counters inflated cheaply), and the `GET /posts/{id}` COLLECTIVE gap fixed with
   fail-closed tests.
6. Phase C briefing `sprints/briefing_<date>_engine.md` with "What merging will do", the
   switches in order (H38–H43) and the live-test checklist; `PHASE_COMPLETE` with the counters
   named as the live check.
