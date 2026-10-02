# Engine PLAN — Phase A, Sprint 9 (Stabilize), remainder

**Branch:** `engine/phase-a` · **Spec:** `platform/docs/sprints/sprint_9_stabilize.md`
**Decomposed:** 2026-10-01, cycle 1 (Opus, T2)

## Where Sprint 9 really stands (checked in code, not just docs)

Already on `main` (merged by DrJ):
- Sprint 9a router gating (`platform/src/router_config.py`, 20 routers disabled by default).
- Sprint 9 chain: graph typo fixes, migrations 039/040, `/health` commit, wallet-drain fix in
  `agent_economy` (SECURITY-REVIEW `73c6fe5`), `.well-known` Vercel rewrite (`2cfa87a`),
  memory investigation (verdict: stale gating, clean re-enable candidate).
- Prod schema reconciliation code + CI `migration-chain` job (PR #10, `84e64e1`, merged 2026-09-22).

Not yet done (this plan): the wallet-ownership gap in `routers/tokens.py`, `nodes`/`consensus`
dispositions, **router enablement (zero routers enabled so far)**, Trust Score schedule
(celery is not in `platform/requirements.txt`), founder dedupe + Bruno, PyPI naming,
SDK tests, LICENSE, README.

Unknown to the engine (no prod access): whether DrJ ran the 2026-09-21 reconciliation
runbook in production. Router enablement in the **repo** does not change production while
the Fly `DISABLED_ROUTERS` env var is set (it overrides the repo list), so repo-side work
can proceed; flipping production is a human action.

Baseline (cycle 1): platform suite **2033 passed, 14 skipped** locally.

## Steps

Legend: `[ ]` todo · `[x]` done · `[human]` DrJ-only · Tier per `autonomous_loop_v1.md`.

- [x] **S9-1 — Close the wallet holes in `routers/tokens.py` (routers `wallets`, `stakes`).**
  Done cycle 2, `feaa59f` (SECURITY-REVIEW). Self-service wallets start at 0; funding or acting
  for another agent is FOUNDER-only; transfer/stake use the JWT caller; tx labels allowlisted.
  Follow-up for S9-12: SDK `wallet.py` sends DIDs where the API expects agent UUIDs.
  Two gaps (found cycle 1): (a) `transfer_tokens` (`tokens.py:96`) and `stake_tokens`
  (`tokens.py:152`) authenticate but ignore the caller and trust `body.from_id` /
  `body.agent_id`, so any logged-in agent can move/stake anyone's tokens; (b) `POST /wallets`
  (`tokens.py:48`) and `POST /wallets/by-did` (`tokens.py:68`) have **no auth** and accept an
  `initial_balance`, so anyone can mint tokens. Fix: identity from JWT; initial balance only
  via an admin/system path (or forced to 0 for self-created wallets). Prerequisite for the
  money cohort. Tier **T1** (money/auth). Commit prefix `SECURITY-REVIEW:`.
  Check: new tests prove unauthenticated → 401, cross-identity (body names another agent) → 403,
  self-service wallet creation cannot mint, owner transfer/stake succeeds; full suite green.

- [x] **S9-2 — `nodes` disposition: hardened AND kept disabled.**
  Done cycle 3, `4f17ef2` (SECURITY-REVIEW). `POST /nodes/register` and `POST /nodes/events`
  are FOUNDER-only; peer URLs must be public https (checked at registration and before every
  outbound send). Stays off: no signed-event protocol, no Phase A need (revisit in Phase D).
  Goal: harden peer register / event injection (mandatory auth) if small; else keep disabled
  with a precise reason + follow-up note in `router_config.py`.
  Tier **T1** if hardening (auth), **T2** if keep-disabled decision only.
  Check: config/comment updated; if hardened, tests prove unauthenticated calls fail closed.

- [x] **S9-3 — `consensus` disposition: kept disabled, reason documented.**
  Done cycle 3, `4f17ef2`. Not wired: consensus is keyed on PROPOSAL *posts* and reads the
  baseline `votes` table nobody writes; `governance_votes` is keyed on `proposals` (different
  id space, vote values and weights). Also, any logged-in agent can open/advance any debate.
  Needs the O10 design decision (one proposal model) — not a stabilisation fix.
  Goal: either point tallies at `governance_votes` (small, if clean) or keep disabled with a
  documented reason. Never enable an empty router.
  Tier **T2**. Check: config comment updated; if wired, test shows non-empty tally locally.

- [x] **S9-4 — Local "all-routers" smoke harness.**
  Done cycle 4, `392c601`. Run from `platform/`:
  `.venv/bin/python scripts/smoke_routers.py [--enable a,b | --disabled csv] [--no-migrate]`.
  Green on the repo default (49 GET routes) and with **every** router on (96 routes, 0 × 5xx).
  GET-only: write endpoints still need per-cohort tests/review in S9-5..S9-8.
  Goal: a repeatable script (`platform/scripts/smoke_routers.py` or a pytest integration test)
  that migrates a scratch local DB to head, boots the app with a given disabled-list, and GETs
  every listed route, failing on any 5xx. Used as the acceptance check for S9-5..S9-8.
  Tier **T2**. Check: harness runs green on current default config.

- [x] **S9-4a — Kill-switch safety: the env override must not switch unsafe routers ON.**
  Done cycle 5, `8101e92` (SECURITY-REVIEW). Effective disabled set = configured list ∪ Tier A
  (`BROKEN_OR_INSECURE_ROUTERS`), in `config.Settings.disabled_router_set`. Tests and the smoke
  harness opt out with `ALLOW_UNSAFE_ROUTERS=1`, honoured in development only.
  **Consequence for S9-5 / S9-7 / S9-8:** `graph`, `agent_economy` and `governance` are Tier A,
  so enabling them means moving them out of `BROKEN_OR_INSECURE_ROUTERS` (not just out of the
  default list). Tier B/C routers are still switched on by a short env value, as before.
  Found cycle 3: `DISABLED_ROUTERS` (Fly env) *replaces* the repo list, so a short emergency
  value such as the one in `config.py`'s own example (`contracts,rooms,governance`) would turn
  ON every other gated router, including `agent_economy`, `nodes` and `consensus`.
  Goal: Tier A (`BROKEN_OR_INSECURE_ROUTERS`) stays disabled whatever the env var says
  (proposed, reversible: effective list = env list ∪ Tier A; startup log says so). Do this
  before S9-5 moves routers out of the default list.
  Tier **T1** (permissions surface). Check: test with `DISABLED_ROUTERS=posts` shows `nodes`,
  `consensus`, `agent_economy` still disabled; suite green.

- [x] **S9-5 — Enable cohort 1 (social) in repo config:** `memory`, `graph`, `rooms`,
  `communities`, `conversations`, `channels`, `pulse`.
  Done cycle 7, `2840b1a` (SECURITY-REVIEW). `graph` left Tier A; Tier C now empty; record kept
  in `router_config.ENABLED_IN_SPRINT_9`. Canvas PATCH/DELETE now check the node's room.
  Smoke: 71 GET routes, no 5xx.
  Tier **T2**. Check: smoke harness green with these enabled; suite green; comments updated.

- [x] **S9-6 — Enable cohort 2 (work):** `tasks`, `contracts`, `collectives`, `agentbus`,
  `verifications`, `markets`.
  Done cycle 8, `4bb333d` (SECURITY-REVIEW). Enabled `collectives` (task hand-off now needs the
  task's requester/executor, task unfinished) and `agentbus` (envelope `agent_id` must be the
  JWT caller, else 403; inboxes show `sender_did`). Review found token holes, so `tasks`,
  `contracts`, `markets` moved to Tier A (→ S9-6a); `verifications` held (only acts on
  contracts). Smoke: 76 GET routes, no 5xx.
  Tier **T2**. Check: smoke harness green; quick auth review of write endpoints (no body-identity).

- [x] **S9-6a — Fix and enable `tasks`.** (Was "tasks, contracts, markets"; split in cycle 9
  because each is its own money path — contracts → S9-6b, markets → S9-6c.)
  Done cycle 9, `6d4b666` (NEEDS-DELIBERATE-MERGE). Every `/tasks` POST needs a login and acts
  as the logged-in agent (a body DID naming anyone else → 403); accept = creator only; result =
  assigned executor only, once, with "completed" and the payout in one locked transaction;
  update = executor (or FOUNDER) only, forward-only. `POST /workflows/create` (always on) had
  the same body-identity hole and is fixed too. `tasks` is on in the repo default.
  Proof: `tests/integration/test_task_escrow_db.py` (17 tests, real local Postgres, run with
  `--db`), incl. 12 concurrent submits → paid once. Smoke: 79 GET routes, no 5xx.
  Left as is, on purpose (see D2 and the notes on S9-6d, S9-7, S9-9, S9-12): auto-accept +
  pay-on-submit; unfunded rewards (soft-fail escrow); no cancel/refund for an untaken task.

- [x] **S9-6b — Fix and enable `contracts`, then `verifications`.**
  Done cycle 10, `c9259a0` (NEEDS-DELIBERATE-MERGE). Disputes: creator or contractor only,
  `assigned` / `submitted` only. New creator-only `POST /contracts/{id}/complete` (pays the
  contractor) and `/cancel` (refunds an open contract): row locked, status change and payout
  in one transaction, paid once. Budget escrowed in the same transaction as the create (no
  funds → no contract; was soft-fail). No self-bids; assign / result locked.
  `verifications`: votes and finalisation locked, contractor cannot vote on own result,
  verifier-reward payout switched off (the pool is never funded — it would mint).
  Both routers on in the repo default. Proof: `tests/integration/test_contract_escrow_db.py`
  (24 tests, real local Postgres, `--db`). Smoke: 82 GET routes, no 5xx.
  Left as is, on purpose: no dispute resolution and no timeouts, so some escrow can stay
  locked (→ D3); the contractor is paid the whole budget whatever the bid was (→ D4);
  contracts need a funded wallet, so they are only usable once `wallets` is on (S9-7).
  From the cycle 8 review, plus what cycle 9 saw while reading the code:
  (1) `contract_service.open_dispute`: creator or contractor only, status `assigned` /
  `submitted` only (today: any agent, any status, and it freezes the escrow for good).
  (2) Creator may not bid on own contract.
  (3) Escrow release: `contract_service.complete_contract` already exists but has **no route**
  and is not safe yet: it reads the contract without `FOR UPDATE` and its UPDATE has no status
  guard, so two concurrent completes both pay the (stale) escrow amount; and the release is
  soft-fail inside the transaction, so a contractor without a wallet leaves the contract
  `completed` and unpaid for ever. Fix like tasks (S9-6a): lock the row, status-guarded,
  payout in the same transaction, create the payee wallet if missing; then add creator-only
  `POST /contracts/{id}/complete`.
  (4) `assign_contract` / `submit_result`: lock the row (two concurrent assigns).
  (5) Check `verification_service._distribute_rewards` (it moves tokens by vote power) and
  `subcontract_service` for the same read-then-pay pattern before enabling `verifications`.
  (6) Stuck escrow that stays out of scope unless small: open contract nobody bids on,
  contractor never delivers, disputed contract (nothing resolves a dispute) — record as a
  design question (arbitration / refund), do not invent a policy.
  (7) Then move `verifications` out of Tier B (contractor may still vote on own result —
  note it, design question for Phase B).
  Tier **T1** (money/auth). Commit prefix `NEEDS-DELIBERATE-MERGE:`.
  Check: real-Postgres tests like S9-6a's (extend `tests/integration/`): outsider dispute →
  403, double / concurrent complete pays once, tokens conserved; smoke green; suite green.

- [x] **S9-6c — Fix and enable `markets` (bounties).**
  Done cycle 15 (started cycle 11, recovered from stash), `b1219cb` + `5680d2d` + `7ac7757`
  (NEEDS-DELIBERATE-MERGE). Every bounty write locks the bounty row; "rewarded" and the payout
  are one transaction behind a status guard, paid once; pool escrowed in the same transaction
  as the create (no funds → no bounty); creator cannot submit to or win own bounty; new
  creator-only `POST /markets/bounties/{id}/cancel` refunds an open bounty with no
  submissions; wrong caller 403, wrong state 409. Migration **041** adds
  UNIQUE(`bounty_rewards.bounty_id`) (duplicates archived, not deleted). `markets` is on in
  the repo default. Proof: `tests/integration/test_bounty_escrow_db.py` (19 tests, real local
  Postgres, `--db`). Smoke: 85 GET routes, no 5xx.
  Left as is, on purpose: a bounty with submissions cannot be cancelled and nothing makes a
  creator pick a winner, so that pool can stay locked (→ D5); deadlines are stored but not
  enforced (→ D5); bounties need a funded wallet, so they are only usable once `wallets` is
  on (S9-7). `POST /markets/bounties/auto` is `agent_economy` (still Tier A, S9-7).
  `bounty_service.distribute_rewards`: `SELECT … FOR UPDATE` + status-guarded close before
  crediting; migration adding UNIQUE(`bounty_rewards.bounty_id`); creator may not submit to
  own bounty. Review every other write in `routers/markets.py` for body identity.
  Tier **T1** (money; migration). Commit prefix `NEEDS-DELIBERATE-MERGE:`.
  Check: concurrent distribute pays once (real Postgres); migration upgrade/downgrade clean
  locally; anonymous → 401, other agent → 403; smoke green; suite green.

- [x] **S9-6d — Always-on routes that take identity from the request body.**
  Done cycle 16, `7a2fbe6` + `272077b` + `09f7a3b` + `3eb2c2a` (SECURITY-REVIEW) + `7564d7b`
  (guard test). Every write route in the app was listed mechanically and each one without a
  login, or with an identity field in its body, was read. Fixed, all live in production
  until merged (→ **H5**):
  (1) `POST /agents` (open sign-up) stored the body's `governance_role` — anyone could sign
  up as FOUNDER. Now MEMBER / OBSERVER only; any other role needs a FOUNDER token.
  (2) `POST /agents/{id}/trust-network/interactions`: no login → FOUNDER only.
  (3) `POST /services/register`: no login, body DID → login, own DID only.
  (4) `POST /posts/{id}/interact`: stored under the body DID → own DID only.
  (5) `POST /agents/{id}/discovery/capabilities`: any agent for any agent → own agent only
  (or FOUNDER).
  (6) A2A `message/send`: needs a Bearer token, the task belongs to the caller; anonymous
  A2A tasks are refused (founding documents silent → default refuse; `tasks/get` is public).
  (7) Not a write, but found on the way and fixed: `GET /messages/{did}` gave any agent's
  direct messages to anyone, and message text was copied into the public activity feed
  (`GET /dashboard/activity`, `WS /events/stream`). Own inbox only; no text in events; the
  public readers skip `MESSAGE_SENT`.
  Guard: `tests/test_write_routes_need_login.py` fails on any new write route without a
  login that is not on its reviewed list (10 entries).
  Proof: 64 new tests (suite 2370 passed); live check on a real local server + database,
  52 of 52. Left for other steps: see S9-6e, and the notes added to S9-7, S9-8a, S9-9, S9-12.
  Found cycle 9. These are NOT behind the router gate, so they are live in production today:
  `POST /a2a` method `message/send` (`a2a/handler.py`) creates a marketplace task whose
  creator is `metadata.caller_did`, with no login (reward is always 0, so no tokens move, but
  anyone can list tasks in any agent's name). `POST /workflows/create` had the same hole and
  was fixed in S9-6a. Goal: (1) A2A: attribute a task to a DID only when the request carries
  that agent's JWT; otherwise use the anonymous external DID (which is not seeded, so decide
  and document whether anonymous A2A tasks are accepted at all — if the founding documents do
  not say, default to refusing and record it); (2) scan every router mounted with plain
  `app.include_router` in `main.py` (not `_include_if_enabled`) for write endpoints with no
  `get_current_agent`, or with a `*_did` / `*_id` identity field in the body, and list or fix.
  Tier **T1** (auth). Commit prefix `SECURITY-REVIEW:`.
  Check: tests prove unauthenticated / mismatched identity fails closed; suite green.

- [x] **S9-6e — Direct messages: sending is broken on the baseline schema; finish the read-side check.**
  Done cycle 17, `92d32cd` (SECURITY-REVIEW — a private-data leak turned up, so T1 work).
  (a) `POST /messages/send` now matches whichever `messages` shape exists (DID-only
  baseline, or 006's `*_agent_id` + 007's DID columns; looked up once per process).
  (b) **Leak:** `GET /agents/{did}/activity-stream` and `GET /agents/{did}/activity` gave
  PRIVATE / FOLLOWERS / COLLECTIVE entries to anyone → PUBLIC for everyone, all for the
  agent itself; service defaults to `public_only=True`. `GET /activity` and
  `/feed/activity` already filtered PUBLIC (now tested). `GET /ws/stats` gives counts and a
  machine id only, left as is. `GET /workflows/{id}` is readable by anyone who has the
  random id; its steps are marketplace tasks, already public via `GET /tasks/{id}`, left as
  is. `WS /events/stream` stays login-free (the UI's public feed uses it) but is capped at
  200 sockets per process (1013 over the cap). (c) A2A internal errors return the request
  id, not the exception text. Added to H5's fast fix (cherry-picks cleanly onto `main`).
  Proof: `tests/integration/test_messages_db.py` (5, `--db`), `tests/test_event_stream_cap.py`,
  one A2A test; all 8 fail on the old code. Suite 2374 passed; `--db` 65 passed; smoke 85
  GET routes, no 5xx.
  Not done, noted: FOLLOWERS / COLLECTIVE entries are owner-only (nothing checks follow or
  membership yet); the stream cap is per process, not per IP.
  Found cycle 16. (a) `POST /messages/send` (always on) answers 500 on a database built
  from `init-db.sql` + migrations: its INSERT names `sender_agent_id` / `receiver_agent_id`,
  which the DID-based `messages` table does not have (the reconciliation briefing says
  production's table is DID-based too, so sending is probably broken there as well). Make
  the INSERT match the table that exists (check both shapes migration 006/007 can leave).
  (b) Finish the read-side review that cycle 16 only did by path name: confirm the public
  activity routes (`GET /activity`, `/agents/{did}/activity-stream`, `/feed/activity`)
  respect an entry's `visibility`; check what `GET /ws/stats` and `GET /workflows/{id}`
  give an anonymous caller; `WS /events/stream` takes no login and runs one database query
  per second per open connection (cap or require a login).
  (c) `POST /a2a` returns the raw exception text to the caller on an internal error
  (`data=str(exc)`); return a request id instead.
  Tier **T2** (bug fix + read review; **T1** if a private-data leak turns up).
  Check: real-Postgres test sends and reads a message; anonymous reads of private-visibility
  activity return nothing; suite green.

- [x] **S9-7a — Fix and enable `wallets`, `stakes`, `economy`.** (Was "S9-7, cohort 3"; split
  in cycle 18 because the review found holes — tasks funding → S9-7b, `agent_economy` → S9-7c.)
  Done cycle 18, `8001ece` + `34bf912` (NEEDS-DELIBERATE-MERGE). Found: `POST /economy/mint`
  and `POST /economy/slash` only asked for a login — any agent could create tokens in the
  treasury (and pick the ledger label) or forfeit any agent's stake; a slash was not locked
  (two at once credited the treasury twice); nothing could ever release a stake (staking
  locked tokens for good); a founder grant left no ledger record; the task fee could be
  credited after the escrow had been paid out; A→B and B→A transfers at the same moment
  deadlocked (one failed with a 500). Fixed: mint / slash FOUNDER-only, mint always labelled
  `mint`, slash locked and refused without a treasury; new owner-only
  `POST /stakes/{id}/release` (not before `locked_until`, paid once); grants written to the
  ledger (`grant`) and to `total_minted`; fee charged on the real escrow, row locked;
  transfers lock both wallets in a fixed order, no self-transfer; amounts ≤ 1e12, page size
  1–200. All three routers on in the repo default; Tier B is empty, the default now disables
  Tier A only (`agent_economy`, `nodes`, `governance`, `consensus`).
  Proof: `tests/integration/test_money_db.py` (24 tests, real local Postgres, `--db`; 15 fail
  on the old code); live check on a real local server, real logins, 38 of 38. Smoke: 90 GET
  routes, no 5xx. None of it was live in production (all three are off there).
  Left as is, on purpose: balances and transaction history are public (open ledger); nothing
  moves tokens out of the treasury; ordinary agents get spendable tokens only from a FOUNDER
  grant or by earning them (a faucet is Phase C in the plan); a transfer to an agent who has
  not opened a wallet is refused (400), not auto-created.

- [x] **S9-7b — Tasks: fund the reward in the same transaction; let a creator cancel an untaken task.**
  Done cycle 19, `daf8c64` (NEEDS-DELIBERATE-MERGE). (a) Task row, escrow and fee are one
  transaction; a non-zero reward the creator's wallet cannot cover (or no wallet) → 400, no
  task, no token moved; `reward` capped at the INT column's range (422). (b) New
  creator-only `POST /tasks/{id}/cancel` for an `open` task: row locked, reward refunded
  (`escrow_refund`) and the fee given back from the treasury (`fee_refund`, guarded so the
  treasury cannot go below zero), status `cancelled`; other caller (FOUNDER included) 403,
  not open 409. Migration **042** lets `tasks.status` be `cancelled` (widens a CHECK, no row
  changed). `fail_task` removed.
  Proof: `tests/integration/test_task_escrow_db.py` (31 tests, 14 new, real local Postgres,
  `--db`; 12 of the 14 fail on the old code); live check on a real local server with real
  logins, 35 of 35. Smoke: 90 GET routes, no 5xx.
  Left as is, on purpose: a creator can post and cancel tasks at no cost (no rate limit on
  task creation — fold into S9-8a); bids already made on a cancelled task stay in the table;
  no event is published for a cancel (contracts and bounties publish none either); an
  `assigned` task whose executor never delivers still locks its escrow (→ D2, Sprint 10).
  Consequence: `runners/task_seeder.py` offers a reward from a wallet it can no longer fund
  itself, so its `POST /tasks` now answers 400 instead of creating an unfunded task → S9-7c (e).
  From the cycle 9 notes, now reachable because wallets are on. (a) `task_service.create_task`
  inserts the task, then escrows the reward *soft-fail* in a second transaction and takes the
  fee in a third: a task can advertise a reward its creator could not fund (the executor is
  then paid 0). Make create + escrow + fee one transaction and refuse the task when the
  wallet does not cover a non-zero reward (as contracts and bounties do since S9-6b/c).
  (b) No cancel/refund route for an open task nobody takes: its escrow is stuck
  (`task_service.fail_task` is dead code and writes a status the CHECK constraint rejects).
  Add creator-only `POST /tasks/{id}/cancel` for an `open` task: row locked, refund once.
  The 2.5 % fee is taken at creation — decide and document whether a cancel refunds it
  (default: refund it; the task never ran).
  Tier **T1** (money). Commit prefix `NEEDS-DELIBERATE-MERGE:`.
  Check: real-Postgres tests — unfunded reward → no task, tokens unchanged; concurrent
  cancels refund once; cancel of a taken task → 409; other agent → 403; tokens conserved.

- [x] **S9-7c — Review and enable `agent_economy`; founder-funded seeding for the runners.**
  Done cycle 20, `8046e48` + `a750199` (NEEDS-DELIBERATE-MERGE). (a) Sub-contract: parent row
  locked and child created (budget escrowed from the caller's own wallet) in one
  transaction; not the assigned contractor → 403, parent not in flight → 409; the payload
  cannot overwrite the parent reference. (b) `bounties/auto` confirmed on real Postgres
  (creator = login, whatever the body says); docstrings corrected. (c) The two login-free
  calculators take a typed, bounded body (a malformed one was a 500). (d) `agent_economy`
  left Tier A: the repo default now disables `nodes`, `governance`, `consensus` only.
  (e) Runners open their wallet at 0; new `runners/fund_wallets.py` (FOUNDER grant, top-up
  to a target, dry run unless `--apply`); the seeder backs off 10 min on "Insufficient
  funds". (f) `/onboard` answers `wallet_balance: 0` + `welcome_points: 100`, names only
  routes that are on; new public `GET /wallets/by-did`; skill.md says the wallet starts
  at 0. Also: amounts beyond BIGINT (contract budget, bid, sub-contract, auto-bounty) → 422.
  Proof: `tests/integration/test_agent_economy_db.py` (17 tests, real local Postgres,
  `--db`; 6 fail on the old code); `tests/runners` (15); live check on a real local server
  with real logins, 37 of 37. Smoke: 92 GET routes, no 5xx (97 with everything on).
  Left as is, on purpose: the welcome bonus is still not spendable (needs a farming guard;
  faucet is Phase C); a sub-contract is a label only (nothing ties it to the parent, and
  `POST /contracts` accepts `contract_type: "subcontract"`); `register_all.py` and
  `sdk_agent_runner.py` were compiled, not run (they need the standalone SDK, not on this
  machine); the rest of skill.md was not audited (→ S9-13a).
  (a) `subcontract_service.spawn_subcontract` reads the parent contract without a lock
  before creating the child (the child's own escrow is safe since S9-6b) — lock or re-check.
  (b) `POST /markets/bounties/auto` takes the creator from the login since Sprint 9 (chain)
  and goes through the fixed `bounty_service.create_bounty`; confirm with a real-Postgres
  test, then update its stale docstrings ("accepts the agent's DID in the request body",
  "soft-fail"). (c) `POST /economy/strategies/select` and `/economy/market-analysis` take
  no login and only calculate on the request body (on the guard test's reviewed list) —
  bound the list sizes. (d) Then move `agent_economy` out of Tier A.
  (e) `runners/register_all.py`, `sdk_agent_runner._ensure_wallet` and
  `task_seeder._ensure_seeder_wallet` fund their own wallets, which is FOUNDER-only since
  S9-1 — give them a founder-funded path (Sprint 10 heartbeat needs it). Since S9-7b the
  seeder's rewarded `POST /tasks` is refused (400) until its wallet is funded; make the
  seeder handle that answer cleanly (log once, back off) rather than retrying every loop.
  (f) `/onboard` tells a new agent it has "a funded wallet (100 AXP)" and to check
  `GET /wallets/by-did?agent_did=…`. That route does not exist, and the 100 is a row in the
  legacy `token_balances` table, not in `wallets`: it cannot be spent. Make the message
  true (point at `GET /wallets/{agent_id}`, say the wallet starts at 0) — do NOT make the
  bonus spendable without a farming guard (5 sign-ups/hour/IP × 100).
  Tier **T1** (money/auth). Commit prefix `NEEDS-DELIBERATE-MERGE:`.
  Check: smoke green with only `nodes`, `governance`, `consensus` off; real-Postgres tests
  for (a) and (b); suite green.

  Notes carried over from the old S9-7 (kept for S9-7b / S9-7c):
  Notes from cycle 9 (tasks): (a) `task_service.create_task` escrows the reward *soft-fail*
  in a second transaction, so a task can advertise a reward its creator could not fund —
  make it one transaction and refuse the task (or show the escrowed amount) as part of this
  step; (b) there is no cancel/refund route for an open task nobody takes, so its escrow is
  stuck (`task_service.fail_task` is dead code and writes a status the CHECK constraint
  rejects); (c) `runners/register_all.py`, `sdk_agent_runner._ensure_wallet` and
  `task_seeder._ensure_seeder_wallet` fund their own wallets, which is FOUNDER-only since
  S9-1 — the Sprint 10 heartbeat needs a founder-funded seeding path.
  Note from cycle 10 (contracts): creating a contract now needs a wallet that covers the
  budget, and with `wallets` off no agent can get one through the API — so `contracts` (on
  since S9-6b) only becomes usable when this step lands. `agent_economy`'s
  `subcontract_service` reads the parent contract without a lock before creating the child
  (the child's own escrow is safe); review it with the rest of `agent_economy` here.
  Note from cycle 15 (bounties): same for `markets` — creating a bounty needs a funded
  wallet. `agent_economy`'s `POST /markets/bounties/auto` goes through the fixed
  `bounty_service.create_bounty`, so its escrow is safe; review its caller identity here.

  Note from cycle 16 (sign-up): `POST /onboard` gives every new agent a 100 AXP welcome
  bonus, limited only per IP (5/hour, 20/day). Checked cycle 18: the bonus is written to
  `token_balances`, which no route can spend or transfer, so there is nothing to farm
  through `wallets` today (see S9-7c (f)). `POST /economy/market-analysis` and `/economy/strategies/select`
  (`agent_economy`) take no login; they only calculate on the request body (they are on the
  guard test's reviewed list) — confirm when reviewing `agent_economy`. Staging: the
  `client_credentials` grant (a token for any DID, no secret) is refused only when
  `APP_ENV=production`; `fly.staging.toml` sets `staging`, so anyone can get a FOUNDER token
  on staging. Fine while staging holds nothing of value; do not point staging at real funds.

- [x] **S9-8 — Review and enable cohort 4 (governance):** `governance` only (`consensus` stays off, S9-3).
  Done cycle 21, `2b51e91` (NEEDS-DELIBERATE-MERGE; the review found holes, so T1 work).
  (a) The stake behind a vote stays put: a vote locks the voter's stake rows while it counts
  them, and `POST /stakes/{id}/release` answers 409 while the owner has a weighted vote on a
  proposal still open (it was: vote, release, move the tokens to a second account, vote
  again). (b) Proposals close: `finalize_due_proposals` closes every proposal whose voting
  period is over; the two list routes call it first (nothing called `finalize_proposal`, so
  results were always empty). (c) The outcome follows the rules seeded in
  `governance_parameters`, which nothing read: total weight (abstentions included) ≥ quorum
  (100) and yes > 50 % of yes + no, on a recount of the vote rows (it was "yes > no": one
  vote of weight 0.5 passed a proposal). (d) A vote locks the proposal row and uses the
  database clock (no vote after the close); a concurrent duplicate vote was a 500, now 409.
  (e) Wrong state → 409 (was 400); lists page (≤ 200); description / type / payload
  bounded; at most 3 open proposals per agent; new `GET /governance/parameters`; responses
  carry `abstain_power` and yes / no / abstain head counts. (f) skill.md's Governance
  section named a vote route that never existed — corrected. `governance` is on in the repo
  default: only `nodes` and `consensus` are off. No migration.
  Proof: `tests/integration/test_governance_db.py` (34 tests, real local Postgres, `--db`;
  25 fail on the old code); live check on a real local server with real logins, 44 of 44.
  Smoke: 95 GET routes, no 5xx (98 with everything on).
  Left as is, on purpose (→ D6): any logged-in agent may propose and vote —
  `governance_role` (OBSERVER included) is not looked at, weight is stake × trust only; a
  passed proposal changes nothing by itself (`execute_proposal` has no route and no
  effect); a FOUNDER slash after a vote does not reduce that vote; all of a voter's stakes
  are held while they have a weighted vote open, including stakes made after the vote;
  `min_vote_power` and `default_voting_days` in `governance_parameters` are shown but not
  read (the seeded values match what the code does).
  Tier **T2**. Check: propose → vote → tally works locally; smoke green.
  Note (cycle 20): `/onboard` and skill.md advertise governance only when the router is on
  (`_build_next_steps`); skill.md's Governance section is static and still tells agents to
  vote — make it match when this lands (or in S9-13a).
  Note (cycle 18): vote power = the voter's unreleased stakes × trust score, read when the
  vote is cast (`governance_service.py:216`). Since S9-7a a stake with no `locked_until`
  can be released at once, so the same tokens can vote, be released, be transferred to a
  second account and vote again. Before enabling: count only stakes locked past the
  proposal's closing time, or refuse to release a stake while its owner has a vote on an
  open proposal. Review the write routes for body identity like the other cohorts
  (→ **T1** if anything is found).

- [x] **S9-8d — Governance page (UI): show the real outcome.** (Added cycle 21.)
  Done cycle 22, `c823dab`. Badge and Passed/Failed filter read `status`; results show the
  vote weight and the quorum / pass rule from `GET /governance/parameters`; the debate panel
  is behind `NEXT_PUBLIC_FEATURE_GOVERNANCE_DEBATE` (default off); a refused vote shows its
  message. `npm run build` passes; eslint clean on the changed files. Repo-wide
  `npm run lint` was already failing (31 errors in other files, same before and after; lint
  is not in CI) → S9-8e. Rendered `/governance` against a local API: a 3-yes / 1-no
  proposal the API failed on weight now says FAILED (said PASSED before).
  `ui/app/governance/GovernanceClient.tsx` decides PASSED / FAILED itself, as "more yes
  votes than no votes" by head count (lines ~360 and ~604). The API decides by weight and
  quorum, so the page can say PASSED for a proposal the API closed as failed. Use the
  proposal's `status`. The page also calls the debate / consensus routes
  (`/governance/proposals/{id}/debate` …), which belong to `consensus` and are off (404):
  hide that panel while they are. The head counts the page reads (`yes_votes`, `no_votes`,
  `abstain_votes`) exist in the API since S9-8. Needs `npm ci` in `ui/` first (no
  `node_modules` on the engine machine yet).
  Tier **T3**. Check: `npm run build` and `npm run lint` in `ui/` pass.

- [ ] **S9-8e — UI lint clean.** (Added cycle 22.) `npm run lint` in `ui/` reports 31 errors
  and 22 warnings, all in files outside governance (e.g. `app/graph/page.tsx`,
  `app/tasks/page.tsx`, `components/DevPanel.tsx`, `components/pulse/*`, `components/rooms/*`):
  mostly unused imports and React-hooks rules. Fix them, then consider adding a `ui` lint +
  build job to CI (a CI change is not `deploy.yml`, so it is engine-doable).
  Tier **T3**. Check: `npm run lint` and `npm run build` pass in `ui/`.

Added cycle 2 from DrJ's note (2026-10-01). Evidence from prod: an outside agent (driftice)
flooded the feed with 15 "probe" posts on 9 Sep; OrchardsGuide posted a referral scheme
(30% Bitcoin commission on follower purchases) on 22 Sep.

- [ ] **S9-8a — Per-agent post rate limits + sane max post length.**
  Today (`middleware/rate_limits.py:234`) top-level posts allow 10/min, 100/hr, 500/day per DID
  (trust-scaled), and `content_moderation.py` / `models/post.py` allow 10,000-char content.
  Goal: tighten to a feed-sane budget (proposed default, reversible: 2/min, 10/hr, 30/day for
  new/low-trust agents, trust-scaled upward; replies 6/min, 60/hr, 200/day), a duplicate-content
  guard (same author + same normalised content within 24 h → 409), and a max content length of
  2,000 chars (title 200). Confirm the limiter keys on the authenticated DID, not on a body field
  or IP alone, and that `RATE_LIMIT_MODE` defaults to `enforce`.
  Note (cycle 10): in `RATE_LIMIT_MODE=log` a breached limit does not let the request
  through — `middleware/rate_limits.py:213` answers 200 with `{"_log_only": true}` and the
  handler never runs (seen locally: the 6th `/onboard` in an hour "succeeds" with no agent
  created). Decide whether log mode should pass the request on; fix or document here.
  Note (cycle 19): `POST /tasks` has no per-agent limit either, and since S9-7b a task can
  be created and cancelled at no cost — give task creation a budget here too.
  Note (cycle 20): `POST /economy/market-analysis` and `/economy/strategies/select` take
  no login and have no rate limit (cheap, bounded bodies since S9-7c) — give them a per-IP
  budget here. Read in code, not tested: the 64 KiB body limit in `main.py` only looks at
  the `Content-Length` header, so a chunked upload without one is not limited — check and
  fix here.
  Note (cycle 16): `POST /agents` and `POST /agents/register` (open sign-up, no login) have
  no rate limit at all — only `/onboard` does. `/agents/register` creates an agent row and
  returns no token, so it is mostly a way to fill the agents list with junk. Give both the
  `/onboard` per-IP limits here (or retire `/agents/register` if nothing uses it).
  Tier **T2** (anti-abuse, no money/auth change). Check: tests prove the 3rd post inside a
  minute → 429, 2,001-char content → 400/422, duplicate → 409; suite green.

- [ ] **S9-8b — Fix agent profile `posts_count` staying 0.**
  Cause found cycle 2: only `services/auto_post.py:147` increments `agents.posts_count`; the
  public `POST /posts` and reply paths in `routers/posts.py` never do. Goal: increment in the
  same transaction as the insert (top-level posts; decide and document whether replies count),
  decrement on delete if a delete path exists, plus an idempotent backfill script
  (`UPDATE agents SET posts_count = (SELECT count(*) …)`, dry-run by default).
  Tier **T2** (backfill touches data → commit prefix `NEEDS-DELIBERATE-MERGE:`).
  Check: test creates a post via the API → profile shows 1; backfill dry-run reports correct
  counts on a seeded local DB. Production backfill → `[human]`.

- [ ] **S9-8c — Simple moderation path for commercial / referral solicitations.**
  Goal: (1) agents can flag a post (`POST /posts/{id}/flag`, reason enum incl. `solicitation`,
  one flag per agent per post, authenticated DID only); (2) admin/system-only hide/unhide
  (`hidden_at`, `hidden_reason` columns via a new migration) — hidden posts drop out of
  feeds, lists, search and `/activity`; (3) auto-hold: posts matching a small solicitation
  pattern list (referral / commission / "buy followers" / crypto-payout phrasing) are hidden
  pending review, or auto-hidden after N distinct flags (default 3, reversible).
  Tier **T1** (permissions + migration). Commit prefix `NEEDS-DELIBERATE-MERGE:`.
  Check: tests prove non-admin hide → 403, unauthenticated flag → 401, hidden post absent from
  feed/list/search, OrchardsGuide-style text is held; migration upgrade/downgrade clean locally.

- [ ] **S9-9 — Trust Score on a schedule.**
  Goal: verify recalculation inputs are real (not always-null columns), add celery +
  celery-beat (15-minute recalc), wire the compose `worker`/`beat`. Tier **T2**.
  Note (cycle 1): two competing recalcs exist — `services/trust_score.py:188`
  (`agent_trust_breakdown` weighted sum) and `services/reputation.py:86` (replays
  `trust_events`). Event consumers only record `trust_events`, never recalc. Pick one as the
  scheduled job (likely `reputation.py`, since it consumes real activity events) and document why.
  Celery, xgboost, numpy are all missing from `platform/requirements.txt`; the compose `worker`
  is a stub that prints every 5 s.
  Correction (cycle 9): the image copies the repo-root `workers/worker.py`, which is a real
  worker — it pops task ids from Redis, completes them through `POST /tasks/{id}/update` and
  runs `reputation.recalculate_agent_trust` every 60 s. Since S9-6a that update call needs
  `WORKER_API_TOKEN` (a FOUNDER token). It is not deployed on Fly.
  Before scheduling the recalculation (cycle 9): task-completion trust events are easy to
  farm. Two accounts can hand each other direct tasks (+0.07 per completed task) or
  0-reward marketplace tasks (+0.05), with no check that any work was done. S9-6a only
  stopped the single-account versions (self-assigned task, creator bidding on own task,
  re-opening a finished task). Decide what a completion must satisfy to count (e.g. a
  funded reward, a distinct requester with history, a per-pair cap) before the scores go live.
  Same for verifications (cycle 10): every vote publishes `VERIFICATION_SUBMITTED`, which
  gives the voter a `peer_validation` trust event; any agent can vote, a creator can open
  any number of verifications on one result, and three fresh accounts decide the outcome.
  A completed contract also bumps the contractor's `contracts_completed` / influence score,
  and two accounts can pass one funded budget back and forth for free.
  Same for bounties (cycle 15): two accounts can pass one funded pool back and forth; check
  what `BOUNTY_REWARD_DISTRIBUTED` / `BOUNTY_SUBMISSION` events add to trust before scoring.
  Same for capability endorsements (cycle 16): `POST /agents/{did}/capabilities/{id}/verify`
  counts every call, so one other account calling it twice makes a capability "verified";
  it needs one endorsement per endorser (a table, so a migration). The trust graph
  (`agent_reputation_graph`) has no writer except the now FOUNDER-only manual route, so
  graph scores are empty until real events feed it.
  Note (cycle 21): put `governance_service.finalize_due_proposals()` on the same schedule.
  Today a proposal past its closing time is only closed when somebody reads
  `GET /governance/proposals` or `/results`. Trust score is also half of every vote's weight
  (stake × trust), so whatever makes trust farmable makes votes farmable.
  Check: locally, run the job once against seeded activity → scores show spread (not all 0.44);
  beat schedule registered; suite green.

- [ ] **S9-10 — Founder dedupe + Bruno (local only).**
  Goal: idempotent script that keeps one canonical row for each of the 8 founders
  (ATLAS, BRUNO, DARIA, GIA, MARCUS, NOVA, QUINN, THEA), repoints FKs, removes duplicates,
  creates Bruno if missing. Must coexist with migration 038's suffixed display names.
  Root cause (cycle 1): three seed sources disagree on DIDs — `platform/scripts/seed_agents.py`
  uses `atlas-001 … gia-008`; `runners/register_all.py` and `runners/start_all.sh` use
  `<name>-001`. Pick one canonical DID set and make every seed use it, so re-runs can't duplicate.
  Note (cycle 20): `runners/fund_wallets.py` funds `did:agentx:<name>-001` (what the runners
  use); on a database built from `init-db.sql` only `atlas-001` exists under that name.
  Keep its `RUNNER_DIDS` in step with the canonical set chosen here. The root
  `scripts/seed_ecosystem.py` still posts `initial_balance: 10_000` to `/wallets/by-did`
  with no login (401 since S9-1) — fix or retire it with the other seeds.
  Tier **T1** (data-affecting). Commit prefix `NEEDS-DELIBERATE-MERGE:`.
  Check: on a local DB loaded with duplicates, exactly 8 founders, no orphans; dry-run mode default.
  Production run → `[human]` (HUMAN_ACTIONS).

- [ ] **S9-11 — PyPI naming prep.**
  Goal: confirm which SDK source is canonical (in-repo `sdk/` is already `agentx-py` 0.2.2;
  a standalone `agentx-sdk` repo also exists; `platform/agentx_sdk` is deprecated). Prepare an
  `agentx-client` shim package that depends on `agentx-py` and warns. Tier **T2**.
  Check: `python -m build` succeeds for both locally; shim import emits DeprecationWarning.
  Publishing → `[human]`.

- [ ] **S9-12 — SDK tests.** Run `sdk/tests`, fix failures. Tier **T2**.
  Check: SDK suite green locally.
  Note (cycle 9): the SDK's task helpers do not match the API — `client.act()` sends
  `action_type` / `data` (API: `task_type` / `payload`), `accept_task` PATCHes `/tasks/{id}`
  (API: `POST /tasks/{id}/update`), the async client posts to `/tasks/{id}/bids` (API:
  `/bid`) and sends `{"result": …}` (API: `result_payload`). Identity is now taken from the
  token, so the SDK no longer needs to send any DID. Root `tests/integration/test_e2e_flow.py`
  steps 7–8 are stale in the same way (and name another agent as requester → now 403).
  Note (cycle 10): `sdk/agentx_sdk/contracts.py` has no `complete()` or `cancel()` (the new
  creator-only routes), and should surface the new 403 / 409 answers; the deprecated
  `platform/agentx_sdk` already calls `/contracts/{id}/complete`.
  Note (cycle 15): check the SDK's bounty helpers (if any) against the bounty routes — new
  `/cancel`, 403 / 409 answers, and `GET /markets/bounties` now pages (`limit` ≤ 200, default 50).
  Note (cycle 19): the SDK has no helper for `POST /tasks/{id}/cancel`, and task creation
  can now answer 400 ("Insufficient funds") — surface both. Task status has a new value,
  `cancelled`.

  Note (cycle 20): `/onboard` now answers `wallet_balance: 0` and a new `welcome_points`;
  there is a new `GET /wallets/by-did?agent_did=…` (the SDK's `wallet.py` sends DIDs where
  the API wants UUIDs — this route is the DID one); `POST /contracts/{id}/subcontract`
  answers 403 / 409 where it answered 400; contract and bid amounts above 2^63-1 → 422.

  Note (cycle 21): governance. The async client's `vote()` (`sdk/agentx_sdk/client.py:488`)
  posts to `/governance/proposals/{id}/vote` with `voter_did` / `choice` — that route does
  not exist; the real one is `POST /governance/vote` with `proposal_id` / `vote` (the sync
  `client.governance.vote` is right). "Already voted" and "voting closed" answer 409 now
  (were 400), a 4th open proposal 409; proposals carry `abstain_power`, `yes_votes`,
  `no_votes`, `abstain_votes`; new `GET /governance/parameters`; `POST /stakes/{id}/release`
  can answer 409 while the caller has a weighted vote on an open proposal.
  `runners/sdk_agent_runner.py` (~line 996) calls the debate / consensus routes, which are off.

  Note (cycle 16): `register_capability` in the SDK (Python and TypeScript) calls
  `/agents/{did}/discovery/capabilities` with a DID, but the route takes the agent's UUID
  (422 today). SDK callers of `/services/register`, `/a2a` `message/send` and
  `GET /messages/{did}` must send the Bearer token (now required). The UI's human sign-up
  (`ui/app/login/page.tsx`) sends `agent_type: "HUMAN_OPERATOR"`, which the API's enum does
  not have (422) — fix with the UI work.

- [ ] **S9-13 — LICENSE + README.** Blocked on decision D1 in HUMAN_ACTIONS (licence scope for
  the platform repo). README pointing to the magna carta can proceed. Tier **T3**.
  Note: root `README.md` has a LICENSE badge that links to a missing file and says "MIT" (line ~317).
  Check: README renders; LICENSE present once D1 answered.

- [ ] **S9-13a — skill.md truth audit.** (Added cycle 20.)
  `GET /.well-known/skill.md` is what outside agents act on. S9-7c fixed its wallet claims
  only. Still unchecked: every `curl` in it names a route that exists and is on in the
  repo default (the Governance section tells agents to vote while `governance` is off;
  `/agents/<did>/recommended-tasks`, `/notifications`, `/rooms/<id>/join` not verified);
  "raises your trust score and unlocks higher tiers (STANDARD → PRO → ENTERPRISE)" against
  what the code does. Cycle 21 corrected the Governance section (real routes, real rules);
  still untrue there: "PRO tier — higher API rate limits, weighted governance votes" (a
  vote's weight is stake × trust, the tier plays no part). The agent card
  (`a2a/agent_card.py`, `/.well-known/agent.json`) lists the governance, token and contract
  skills whether or not those routers are on — gate them the same way.
  Goal: each claim true or removed; sections for gated routers shown
  only when the router is on; a test that every path in the document is a mounted route
  (extend `tests/a2a/test_skill_md.py`).
  Tier **T1** (`.well-known`). Commit prefix `SECURITY-REVIEW:`.
  Check: the route-existence test passes on the repo default router list; suite green.

- [ ] **S9-14 — Sprint close.** Run the sprint acceptance criteria locally, write
  `sprint_9_retro.md` (engine run), update `state_of_agentx.md`. Tier **T2**.

- [human] **S9-H1 — Production reconciliation + router flip.** See HUMAN_ACTIONS H1–H3.
  Status 2026-09-30 (DrJ): H1 **not done**; prod still runs the old build and `/agents/top`,
  `/activity`, `/search` return 500.

- [human] **S9-H4 — Remove abusive posts in production.** See HUMAN_ACTIONS H4.

- [human] **S9-H5 — Check production for self-made FOUNDERs; get the S9-6d fixes live.**
  See HUMAN_ACTIONS H5 (urgent).

Note for Sprint 10 (cycle 20): the founder agents get tokens only from
`runners/fund_wallets.py` (a FOUNDER grant). In production the runners cannot log in the
way they do locally (the `client_credentials` grant is refused there), so the heartbeat
needs a real credential path for the founders and a FOUNDER token for the funding step —
both are decisions for the Sprint 10 spec, and the funding run itself is a human action.

After Sprint 9 closes: draft `sprint_10_heartbeat.md` from Plan v2 §4 (open questions on LLM
provider and daily cost ceiling become DECISION_NEEDED unless a reversible default exists).
