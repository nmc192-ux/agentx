# Sprint 20 — Faucet — Retro (engine run)

**Sprint:** 20 — Faucet (`sprint_20_faucet.md`, planned by the engine in cycle 189 as the first sprint of Phase C, `phase_c_plan.md`)
**Dates:** 2026-10-15, engine cycles 189–195
**Branch:** `engine/phase-b`. **Not merged.** After this close the branch is 164+ commits ahead of `origin/main` (Sprints 13–20 and the Neon/free-tier work), 31 marked `SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:` (2 from this sprint). **One migration:** 050 `faucet_claims` (new table only, additive).
**Step list:** `docs/execution/engine/PLAN.md` (FC-1 to FC-5). **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md` (new: H38).

## What was intended

Let a brand-new agent afford its first bounty or paid task on day one without a founder
grant: a small daily faucet of AgentX tokens (no outside value), hard to abuse, shipped
**off** so 1 Nov launches exactly as rehearsed.

## What actually shipped (on the branch, switched off)

- **FC-1 Faucet core** (`46d5673`, Fable, `SECURITY-REVIEW:`). Migration 050 `faucet_claims`
  (UNIQUE agent + UTC day); `POST /wallets/faucet`, payee from the bearer token only. One
  transaction under a platform-wide lock: refusals (off → 404, already claimed, balance ≥ 100,
  younger than 60 min, not ACTIVE, daily budget of 2,000 spent) are checked before any write;
  then wallet credit, `faucet` ledger row, `token_supply.total_minted` += 25.
- **FC-2 Onboarding points at it** (`6854f95`). `/onboard` next step, heartbeat `faucet_hint`,
  `skill.md`, `SKILL.md`, `/join` (behind `NEXT_PUBLIC_FEATURE_FAUCET`), quickstart; all shown
  only while the faucet is on, all say "no outside value".
- **FC-3 SDKs and MCP** (`674fdb5`). Python `claim_faucet()`, TS `claimFaucet()` plus TS
  wallet parity, MCP tool `claim_faucet`. Versions unchanged (0.4.0 / 0.1.0 / 0.1.0).
- **FC-4 Economy journey** (`e888699`). `scripts/economy_journey.py`: two fresh agents claim,
  bounty with a deadline, paid task, books add up; `launch_rehearsal.py --economy` runs it.
- **FC-5a Security review** (`9562913`, Fable). 4 commits reviewed, 1 issue fixed (below).
- **FC-5 Close** (this commit). H38 "switch on the faucet" added for after 1 Nov.

## Acceptance criteria (run locally, cycle 195)

| Criterion | Result |
|---|---|
| Faucet unit + DB tests: credit once, same-day second claim refused with no ledger row, 10 concurrent claims by one agent credit once, many agents never pass the budget, every refusal writes nothing, body DID ignored, 401 for anonymous/bad tokens, `total_minted` rises by what was paid | ✅ `tests/test_faucet*.py`, `tests/integration/test_faucet_db.py`, `tests/test_economy_journey.py` with `--db`: **129 passed** |
| `economy_journey.py` exits 0 from an empty local database | ✅ 7/7 (inside the rehearsal below) |
| `launch_rehearsal.py` passes 9/9 with the faucet off | ✅ **PASSED 10/10** with `--economy`: the 9 launch checks with the faucet off, then the economy journey with it on in its own API |
| Both SDK suites green; `skill.md` and `/join` name the faucet | ✅ Python SDK **506 passed**, TS build + **155 passed**, MCP **79 passed**; faucet text in `src/a2a/skill.py`, `skills/agentx/SKILL.md`, `ui/app/join/page.tsx` |

## Sprint-close security review

Fable, cycle 194: **reviewed 4 commits, found 1 issue, fixed.** `POST /wallets/faucet` had no
rate limit, yet every call (paid or refused) takes the faucet's platform-wide lock, so one
agent looping could slow every other claim. Now 6 a minute and 30 an hour per agent, plus 10
adversarial tests (other payee, off-the-clock, inactive statuses, tiny budget, bad ceiling,
duplicated supply row, the cap on the real route).

**Known limit, not a hole:** the 2,000-a-day budget is first come, first served. Someone with
a few addresses' worth of throwaway agents could take it all once the agents are an hour old,
and honest newcomers would hear "dry, try tomorrow". Bounded (no outside value, never more
than 2,000 a day) and visible in `faucet_claims`. H38 tells DrJ what to watch; a fairer rule
is Sprint 21 "trust that notices" material.

## What went well

- The money path was designed on Fable once and then only *called* by Opus steps; the review
  found nothing wrong in the transaction itself.
- The economy journey is the first end-to-end proof that tokens can go round (claim → bounty
  → paid task) with the books equal to the ledger.

## What didn't

- An interrupted cycle left the H38 text uncommitted; the engine recovered it from a stash
  in cycle 195 and checked its numbers against the code before keeping it.
- `pytest -n` still cannot be used (random ids in parametrised tests); full runs are serial.

## Decisions made by the engine (reversible)

- Defaults 25 a claim / ceiling 100 / 60 minutes / 2,000 a day / 6 a minute; all settings.
- SDK versions not bumped so the 1 Nov runbook's pinned versions stay right.

## Next

Sprint 21 — bounties end to end, and trust that notices (`phase_c_plan.md`): decompose next
cycle. Nothing from Sprint 20 changes 1 Nov unless DrJ does H38 (and D13 says Phase C work
rides along switched off).
