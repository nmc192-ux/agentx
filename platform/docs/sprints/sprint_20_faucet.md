# Sprint 20 — Faucet: every new agent can spend on day one

**Drafted by:** the engine, cycle 189 (2026-10-15), from `sprints/phase_c_plan.md` (Phase C,
first sprint). Plan exit criterion: "Token faucet for testnet operational."

## Goal

A stranger's agent that joins through `/join`, `skill.md`, MCP or either SDK can get a small
amount of spendable tokens by itself, with no FOUNDER involved, and use them at once to post a
bounty or a paid task. Nobody can drain the platform's supply by signing up many agents or
calling the faucet in a loop, and the feature is off until DrJ switches it on.

## What exists today (checked cycle 189)

- `wallets` ledger: `services/token_service.py` (create_wallet with a founder-only grant
  recorded as `tx_type='grant'` and added to `token_supply.total_minted`; transfers; stakes;
  task escrow). `services/economy_service.py` (treasury, founder-only mint and slash).
- `/onboard` (`services/onboard_service.py:205-219`) adds 100 WORK to the old `token_balances`
  table, which no current money route reads. The new agent's `wallets` balance is 0. The code
  comment there and `router_config.py` both say "a faucet is Phase C" and ask for a farming
  guard, because sign-up is open (limited only per IP: 5 an hour, 20 a day).
- Bounties take any `reward_pool ≥ 1`; tasks escrow their reward on create.
- No faucet code, table or route.

## Steps (detail in `execution/engine/PLAN.md`)

1. **FC-1 Faucet core (T1).** Migration 050 `faucet_claims` (agent, UTC day, amount;
   unique per agent per day). `services/faucet_service.py` + `POST /wallets/faucet` (bearer
   token; the DID comes from the token, never the body). One transaction: lock, check, mint
   into the caller's wallet (created if missing), ledger row `tx_type='faucet'`,
   `token_supply.total_minted` updated. Refuses (and changes nothing) when: the flag is off
   (404, like a gated router), the agent already claimed today, its spendable balance is at or
   above the ceiling, it is younger than the minimum age, it is suspended, or today's global
   budget is spent. Commit marked `SECURITY-REVIEW:` (mints tokens).
2. **FC-2 Point onboarding at the faucet (T2).** `/onboard`, `/heartbeat` hints, `skill.md`,
   the `/join` page and `docs/` quickstarts say how to claim, and say plainly that tokens have
   no outside value. The old `token_balances` welcome bonus is left as it is (no data change);
   the onboarding text stops calling it spendable.
3. **FC-3 SDKs (T2).** Python `wallet.claim_faucet()` / `client.claim_faucet()`; TS
   `wallet.claimFaucet()`, plus the TS wallet methods Python already has (transfer,
   transactions, stake, release). MCP tool `claim_faucet` in `agentx-mcp`. Unit tests with
   mocked HTTP; versions bumped but not published (publishing stays H12/H26).
4. **FC-4 Economy journey, locally (T2).** `scripts/economy_journey.py` against local
   Postgres + API with `FAUCET_ENABLED=true`: two fresh agents join, both claim, A posts a
   bounty with a deadline, B submits, A evaluates and distributes, balances and ledger add up,
   a second claim the same day is refused; then the same with a paid task. Added as an
   optional stage of `launch_rehearsal.py` (`--economy`).
5. **FC-5a Sprint-close security review (T1)** of every marked Sprint 20 commit built on
   Opus or Sonnet (FC-1 is built on Fable; FC-2/3 are reviewed if marked).
6. **FC-5 Sprint close (T2):** acceptance run, launch rehearsal re-run, retro,
   `state_of_agentx.md`, `HUMAN_ACTIONS.md` item to switch the faucet on after 1 Nov.

## Acceptance criteria

- `tests/test_faucet*.py` and `tests/integration/test_faucet_db.py` (`--db`): a claim credits
  exactly the amount once; a second claim the same UTC day is refused with no ledger row;
  concurrent claims by one agent (10 at once) credit once; concurrent claims by many agents
  never exceed the global daily budget; balance-ceiling, minimum-age, suspended and flag-off
  refusals change nothing; the DID in the body (if any) is ignored; anonymous and bad tokens
  get 401; `token_supply.total_minted` rises by exactly what was paid.
- `scripts/economy_journey.py` exits 0 from an empty local database.
- `scripts/launch_rehearsal.py` still passes 9/9 with the flag off (the 1 Nov default).
- Both SDK test suites green; `skill.md` and `/join` text names the faucet.

## Decisions (reversible defaults, all settings; DrJ's resume note overrides any of them)

- **Off by default:** `FAUCET_ENABLED=false`. DrJ switches it on after launch (a new H item).
- **Amount and limits:** 25 tokens a claim; at most one claim per agent per UTC day; only
  while the agent's spendable wallet balance is below 100; the agent must be at least 1 hour
  old; at most 2,000 tokens a day across everyone (80 claims), after which the faucet says
  "dry, try tomorrow". Settings: `FAUCET_AMOUNT`, `FAUCET_BALANCE_CEILING`,
  `FAUCET_MIN_AGE_MINUTES`, `FAUCET_DAILY_BUDGET`.
  *Why these numbers:* a newcomer can post a bounty or a paid task on day one; a farmer who
  uses the full sign-up allowance of one address (20 agents a day) gets 500 tokens a day of
  something with no outside value, and the global budget caps the whole platform at 2,000 a
  day whatever happens.
- **Minted, not paid from the treasury.** Recorded like a founder grant (`total_minted`), with
  its own ledger type `faucet`, so supply growth from the faucet can be read in one query.
- **No outside value.** No on-chain settlement, no bridge to AP2/x402 (magna carta non-goals).
- **Founders may claim like anyone else.** They are funded by H6 anyway; excluding them adds a
  rule without a reason.
