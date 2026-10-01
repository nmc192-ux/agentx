# Engine log

Newest at the top.

## 2026-10-01 · cycle 4 · Opus (T2) · S9-4 router smoke harness

- **S9-4 done** (`392c601`): `platform/scripts/smoke_routers.py` rebuilds a throwaway local DB
  (`agentx_smoke`: `init-db.sql` → `alembic stamp 001` → `upgrade head`, same chain as CI),
  starts the API with a chosen disabled-router list, onboards one agent, then GETs every route
  in `/openapi.json` with and without that agent's token. Any 5xx fails the run. It refuses
  database names not starting with `agentx_smoke` and only ever uses localhost.
- **Result:** repo default config, 49 GET routes, no 5xx. **All 20 gated routers on:** 96 GET
  routes, no 5xx either, so on a migrated DB the read side of every cohort is healthy. This
  says nothing about write endpoints or about production's divergent schema (H1).
- **Small finding:** `src/cache.py` silently turns the Redis cache off outside production
  whenever the URL contains "localhost", so `/health/ready` reports 503 "cache disabled" in such
  setups. The harness uses `127.0.0.1` to get the real cache path. Not changed (dev-only).
- **Check:** harness green (both configs); `tests/test_smoke_routers.py` 5 passed; full platform
  suite **2097 passed, 14 skipped** (was 2092).
- **Decisions I made (reversible):** script rather than pytest (it needs real Postgres/Redis and
  a fresh process per router list); rate limits run in log-only mode during the smoke so 429s
  don't hide 5xx.

## 2026-10-01 · cycle 3 · Fable (T1) · S9-2 nodes hardening + S9-3 consensus disposition

- **S9-2 done** (`4f17ef2`, `SECURITY-REVIEW:`): the `nodes` router is hardened **and** stays
  disabled. Both write endpoints (`POST /nodes/register`, `POST /nodes/events`) were open to
  anyone; they are now FOUNDER-only. Peer URLs must be public https — no internal hostnames,
  private/loopback/metadata addresses or numeric-host tricks — checked at registration and
  again before every outbound send.
- **New finding (why this was worth hardening even while off):** `node_consumer` is subscribed
  to the event bus regardless of router gating. Had `nodes` ever been switched on, anyone could
  register a URL and receive every contract/task/bounty event payload, or aim those POSTs at
  internal addresses.
- **S9-3 done** (same commit): `consensus` stays disabled with a precise reason in
  `router_config.py`. It cannot be "pointed at `governance_votes`": consensus is keyed on
  PROPOSAL posts, governance on the `proposals` table (different ids, vote values, weights),
  and any logged-in agent can open/advance any debate. It needs the O10 design decision.
- **Also fixed** (`f59f88a`): `test_rivalry_creates_edges` failed about 1 run in 6 (unseeded
  random interactions relabelled the edge under test). It failed once in this cycle's first
  full run; it is now deterministic. Unrelated to the nodes change.
- **New finding → new step S9-4a:** the Fly `DISABLED_ROUTERS` env var *replaces* the repo
  list, so a short emergency value turns ON every router it does not name, including the
  unsafe ones. H3 already tells DrJ to unset it rather than edit it, and its emergency-undo
  line names all 20 routers, so nothing is exposed today.
- **Check:** node tests 101 passed; full platform suite **2092 passed, 14 skipped**
  (was 2053). New `tests/test_router_config.py` pins `nodes` and `consensus` as disabled.
- **Decisions I made (reversible):**
  - Inbound federated events are FOUNDER-only rather than "any logged-in agent": without
    signatures a caller cannot prove it is the peer it names, so anything looser is spoofable.
  - Peer URLs are https-only with no development exception; local two-node testing would need
    one added deliberately.
  - `GET /nodes` stays public (it lists peers and their public keys only).
  - Did not build Ed25519 event signing: no signing helper exists in `src/auth`, outbound
    signing needs a new node key (a secret, so a human action), and federation is Phase D.

## 2026-10-01 · cycle 2 · Opus (T2) · DrJ note + S9-1 wallet security fix

- **DrJ note handled first** (`a6c899b`): H1 stays open (prod still on the old build;
  `/agents/top`, `/activity`, `/search` return 500). Added Sprint 9 steps S9-8a (post rate
  limits + max length + duplicate guard), S9-8b (`posts_count` fix; root cause: only
  `services/auto_post.py` increments it, the public `POST /posts` never does) and S9-8c
  (flag/hide moderation for solicitations). Added H4 (DrJ removes the OrchardsGuide and
  driftice posts in prod, with preview-then-delete SQL). H2 now points to resume notes.
- **S9-1 done** (`feaa59f`, `SECURITY-REVIEW:`): `POST /wallets` and `/wallets/by-did` now
  need a login, and self-created wallets start at 0 (minting is FOUNDER-only). Transfer and
  stake always use the logged-in agent's own wallet; a body naming someone else gets 403.
  Transfer type labels are limited to transfer/payment/tip. The e2e integration test now funds
  via a founder token.
- **Check:** `tests/routers/test_tokens.py` 32 passed; full platform suite **2053 passed,
  14 skipped** (baseline 2033).
- **Decisions I made (reversible):**
  - Funding a wallet (initial_balance > 0) is FOUNDER-only, not removed entirely, so a founder
    can still seed balances locally. Revisit when treasury-based grants exist.
  - Kept `from_id` / `agent_id` as optional body fields (verified against the caller), not
    deleted, so existing clients that send their own id keep working.
  - Moderation (S9-8c) is T1 because it adds permissions and a migration.

## 2026-10-01 · cycle 1 · Opus (T2) · decompose Sprint 9 remainder

- **What:** First engine run. Read the protocol, Plan v2 §4, state doc, Sprint 9 spec, the
  9-chain retro/briefing and the 2026-09-21 reconciliation briefing; checked the code.
  Sprint 9 is still the current sprint: its safe fixes, wallet-drain fix, `.well-known`
  rewrite and prod-schema reconciliation code are on `main`, but **no router has been enabled**,
  Trust Score has no scheduler (celery isn't even installed), founders aren't deduped, and the
  PyPI/SDK/LICENSE items are untouched. Wrote `PLAN.md` (14 steps + 1 human step) and seeded
  `HUMAN_ACTIONS.md` (H1–H3, decision D1).
- **New finding:** `POST /wallets` and `POST /wallets/by-did` are unauthenticated and accept an
  `initial_balance` → unlimited minting, on top of the already-known transfer/stake ownership gap.
  Both routers are off by default, so production is not exposed today. Folded into S9-1 (T1).
- **Check:** baseline platform suite **2033 passed, 14 skipped**. SDK suite not run yet (S9-12).
- **Commit:** see git log (`engine: cycle 1 — decompose Sprint 9 remainder`).
- **Decisions I made (reversible):**
  - Kept Sprint 9 as current rather than jumping to Sprint 10: router enablement and Trust
    Score scheduling are prerequisites for the heartbeat sprint to mean anything.
  - Router enablement split into four cohorts (social → work → money → governance), following
    the 2026-09-21 briefing's recommended order.
  - Treated the `sdk/` "dual-repo tangle" from the spec as resolved: `sdk/` is plain tracked
    files (no nested `.git`, no submodule), so S9-11/12 are not blocked.
  - LICENSE held as decision D1 (constitution Art. 14 vs Art. 15 tension); not blocking.
