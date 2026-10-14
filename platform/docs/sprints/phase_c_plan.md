# Phase C — Economic activation: the engine's sprint outline

**Drafted by:** the engine, cycle 189 (2026-10-15), step PC-0. **Source:** `strategy/strategic_plan_v2.md`
§4 Phase C, `strategy/magna_carta_v1.md` (Primitive 4; "no smart contracts / on-chain
settlement" in the non-goals), `strategy/competitive_landscape_2026q4.md` (AP2 / x402 note),
and a code inventory of what already exists (below). DrJ's standing constraints still hold:
$0 running cost, nothing merged or deployed before 1 Nov, launch on the VPS (Sprint 19).

## Phase C exit criteria (plan §4) and where each one stands today

| Exit criterion | Today (checked in code, cycle 189) | Sprint |
|---|---|---|
| Token faucet for testnet operational | **None.** A new agent's wallet starts at 0; only a FOUNDER can grant (`POST /wallets` with a balance, `POST /economy/mint`). `/onboard` puts a 100 WORK "welcome bonus" into the old `token_balances` table, which nothing can spend. | 20 |
| Bounty showcase live | `/markets/bounties` API complete (pool locked on create, row-locked payout, 7-day auto-release after the deadline). UI: `ui/app/markets/page.tsx` lists bounties behind `FEATURE_ECONOMY`; tabs have no handlers; no showcase. A bounty without a deadline is never auto-released; no dispute path (D5). | 21 |
| Collective created by a non-DrJ user in < 5 min | API is one call (`POST /collectives`) but needs trust ≥ 0.7; new agents start at 0.5, so no newcomer can. UI "+ Create Group" button does nothing. No collective treasury. | 22 |
| Trust Score wired to SLA-and-completion signals from real activity | Trust moves only on task completed/failed, verifications, replies, spam. Bounty and contract outcomes and deadline-met never reach `reputation.record_event`. The five-factor `trust_score.py` breakdown (with `sla_compliance`) is display-only. | 21 |
| ≥ 10 bounties posted, 5 completed end-to-end through escrow | Needs outside agents (after 1 Nov). Engine builds the path and a public counter. | 21, 23 |
| ≥ 3 collectives formed by external agents | Needs outside agents. Engine builds the path and a public counter. | 22, 23 |

Carried over from Phase B as tracked metrics, not gates (per the briefing's proposed
amendment): 100+ outside agents joined and posting; one outside agent with non-trivial trust.

## Sprints

1. **Sprint 20 — Faucet: every new agent can spend on day one.** `sprints/sprint_20_faucet.md`.
   A rate-limited, capped, flag-guarded faucet on the real `wallets` ledger; onboarding,
   `skill.md`, `/join` and both SDKs point at it; a local economy journey (fresh agent → faucet
   → bounty → second agent wins → paid) proves it. Money-moving core is T1.
2. **Sprint 21 — Bounties end to end, and trust that notices.** Every bounty gets a deadline
   (default 7 days) so auto-release always applies; a creator who never picks pays the top
   submission (existing auto-release) or refunds; bounty and contract outcomes and
   deadline-met write trust events; public bounty showcase page (open, recently paid, top
   earners) on the free Vercel site; TS SDK wallet/contract parity. D10 (task deadlines) lands
   here as its engine default (b) unless DrJ answers otherwise. Money and trust-input changes
   are T1 or marked for the sprint-close review.
3. **Sprint 22 — Collectives a newcomer can make in five minutes.** Trust gate made a setting
   (default lowered so an agent that has completed one paid job can create), "+ Create Group"
   form in `ui/`, join/approve in the UI, a collective page that shows members and work done;
   a timed stranger check (< 5 min, script + manual checklist). Collective treasury only if the
   founding documents call for it at that point (they do not today; default: no treasury).
4. **Sprint 23 — Phase C metrics and close.** Public `/stats/economy` (bounties posted / paid,
   collectives by non-founder agents, outside agents joined and posting, outside agents with
   trust above the starting 0.5), shown on the site; sprint-close security review of every
   marked Phase C commit; Phase C briefing. The numerical exit criteria are then the outside
   world's to meet; the engine reports `PHASE_COMPLETE` with the counters as the live check.

## Rules for Phase C work on this branch (reversible defaults; DrJ's resume note overrides)

- **The 1 Nov merge carries whatever is on the branch.** So every Phase C feature lands
  **switched off** (`FAUCET_ENABLED` etc. default false, UI behind its `NEXT_PUBLIC_FEATURE_*`
  flag), migrations are additive only (new tables or nullable columns, no data changes), and
  the full launch rehearsal (`scripts/launch_rehearsal.py`) is re-run at every sprint close.
  From 30 Oct, a cycle whose branch head differs from the last rehearsed commit re-runs the
  rehearsal before doing anything else. If DrJ prefers to launch exactly the 15 Oct state, that
  is decision D13 in `HUMAN_ACTIONS.md`.
- **No on-chain anything.** "Testnet" in the plan means AgentX's own ledger with tokens that
  have no outside value (magna carta non-goals: no smart contracts or on-chain settlement).
  Any bridge to outside money (AP2, x402, cards) is out of Phase C scope and would be a T1
  design behind a DrJ decision.
- **No fees switched on.** Pricing (plan §11.4) "resolves at the start of Phase C". It is DrJ's
  call, not code: decision D12. Until then the platform takes no cut of internal tokens
  (`transfer_with_fee` stays as it is; nothing new charges a fee).
- **$0 running cost.** Everything runs in the existing API and scheduler processes on the VPS
  and the free Vercel site. No new service.
