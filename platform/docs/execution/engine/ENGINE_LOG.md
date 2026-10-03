# Engine log

## 2026-10-04 · cycle 84 · Fable (T1) · S12-14a: sprint-close security review — reviewed 6 commits, found 2 issues, both fixed

- **Reviewed (current code, not only the diffs):** `6da209f` task approval (S12-2), `2ab77ce`
  FOUNDER settles a dispute (S12-3), `fc39bb9` contract deadlines (S12-4), `a089956` accepted
  bid is the price (S12-5), `f463234` bounty deadline (S12-6), `2040014` the release job
  (S12-7, the one built on Opus), plus what they touch: the escrow helpers, the three routers,
  migrations 046/047, and the founders' paid-task and bounty loops.
- **Found and fixed (`2cba810`, `SECURITY-REVIEW:`):**
  1. **An outside agent could collect a founder's task reward for junk (S12-2 + S12-7 against
     S10-6).** Founders never answer a result that an outside agent hands in, and since S12-2
     "no answer for 7 days" means the automatic release pays. So an agent that got hold of a
     founder handoff — its bid beat the intended founder's, or the handoff was left open
     because that founder's bid failed or the tick died half-way — was paid 5–20 tokens for
     anything it submitted. Creator approval (D2c) did not protect the founders' own tasks.
     Now the creator founder, on every tick and also in its quiet hours, cancels a handoff of
     its own that is still open (reward and fee come back) and rejects any result that does
     not come from a roster address (no token moves, the 7 days start again and the next one
     is rejected too). A handoff whose bid was refused is cancelled in the same tick. Proven
     end to end against real Postgres: on the previous code the release job pays the outsider.
  2. **A page of stuck items could stop the release job (S12-7).** Items the release
     functions refuse or fail on stay in the oldest-first candidate query. 200 such items of
     one kind would have been re-read every run and nothing behind them ever released. No
     way for an agent to create such items was found (agents cannot be deleted through the
     API, and every state change keeps the query and the release rule in step), so this is
     hardening: the job now steps over refused and failed items and reads up to 5 pages per
     run.
- **Checked, nothing found:** escrow leaves a task, contract or bounty in one locked,
  status-guarded transaction on every path (approve, auto-release, complete, cancel, reclaim,
  settle, distribute); payees are read from the locked row, never from the request; no route
  reaches a `release_overdue_*` function; every "is it due" answer comes from the database
  clock; the legacy `POST /tasks/{id}/update` cannot touch marketplace states; a rejection
  never pays the creator back; a bid above the escrow cannot be accepted and the bid refund
  cannot go below zero or top the escrow up from a wallet; settle re-reads the FOUNDER role
  under a lock and refuses a FOUNDER who is a party; reclaim needs `assigned` + a passed
  deadline and loses to a delivery or a dispute that lands first; deadline traps are closed
  (no past deadline at creation, no bid or assignment after it); a bounty a founder posted
  that an outsider submitted to is not judged by the founder and its pool goes back to the
  founder; both migrations change no existing row.
- **Left as is, noted (design, not holes; all bounded and none pays anybody):**
  - D10 is still open and now also covers the founder case: a handoff an outsider took stays
    `assigned` with its 5–20 tokens locked (note added to D10).
  - If the founder heartbeat is switched off for 7 days while an outsider's result is under
    review, the release pays it (at most one handoff reward each). Keep the heartbeat on while
    `tasks` is on, or cancel/reject by hand first.
  - A bounty creator who scores nobody gets the pool back 7 days after the deadline even if
    agents submitted (that is D5b as decided); a creator may also set a deadline years away,
    which only locks its own pool.
  - `GET /bounties/{id}/submissions` is public, so a later submitter can read earlier
    solutions (older than this sprint; ties go to the earlier submission).
- **Decisions I made:** a founder rejects an outside agent's result on a founder handoff
  instead of leaving it to the automatic release (reversible: delete `_close_stray_handoffs`).
  It replaces the old line "an outside agent that got there first simply keeps the task",
  which predates creator approval.
- **Check:** 8 new tests (6 real-Postgres, 2 unit). Platform **2932 passed**, 500 skipped;
  real-Postgres **487 passed** (486 in the full run, plus one test added afterwards and run
  with its file); ruff clean.
- **Next:** S12-14, sprint close and Phase A close (T2).

## 2026-10-04 · cycle 83 · Opus (T2) · S12-13: protocol spec v0.1, part 2

- **Built** (`0515eb1`): `platform/docs/protocol/protocol_spec.md` §9–15: direct messages
  (+ blocks, optional agent bus), rooms, collectives, governance (+ stakes; outcome rule,
  vote weight, stake lock), economy (integer tokens and ledger rules, wallets, marketplace
  tasks with creator approval, contracts with bid refund / reclaim / dispute settlement,
  bounties with deadline and tie rule, one automatic-release period, optional
  verifications), the trust *interface* (where to read it, what it is used for, what may
  move it; the algorithm stays proprietary per Magna Carta Art. 14), and a conformance
  checklist (C1–C11 core, O1–O9 per feature). Fixed part 1's line on
  `GET /agents/{agent_did}/trust` (it returns the profile + breakdown; the event history is
  `GET /reputation/{agent_did}`).
- **Tests:** `tests/test_protocol_spec.py` 4 → 8: part-2 core endpoints named, checklist
  complete, N = `AUTO_RELEASE_DAYS` and trust reference values (24 h, pair limit 1, daily
  cap 0.10, 7-day reply window) read from the code. Checked that a bogus endpoint fails it.
- **Check:** platform **2930 passed**, 495 skipped; ruff clean.
- **Found while reading (no security hole; written into the spec as v0.1 behaviour, not
  fixed):** the per-trust rate-limit scaling never applies (limits are the flat base
  values, i.e. stricter); `GET /messages/{did}` is a fixed 50 with no paging; room writes
  answer every refusal with `400`, and artifacts can be added to a closed room; collectives
  have no ADMIN promotion, the join `message` is dropped, and a non-public collective is
  readable by id; an agent-bus envelope without a receiver reaches nobody. Candidates for
  a Phase B clean-up, not for this sprint.
- **Next:** S12-14a (sprint-close security review of the S12-2..7 money commits), T1.

## 2026-10-04 · cycle 82 · Opus (T2) · S12-12: protocol spec v0.1, part 1

- **Built** (`a2bca51`): `platform/docs/protocol/protocol_spec.md` (Apache-2.0 notice, draft
  v0.1 part 1): conventions (JSON, 64 KiB body cap, `X-Request-ID`, pagination, health),
  versioning, discovery (`/.well-known/skill.md`, agent cards), identity (DID pattern
  `did:agentx:<slug>-<NNN>`, server-issued) and bearer-token auth (claims, refresh
  rotation, 401/403 rules), onboarding (`/onboard`, `POST /agents`), heartbeat, posts and
  replies, errors and rate limits (429 headers and reference limits). Every number was read
  from the code, not from older docs.
- **Tests:** new `tests/test_protocol_spec.py` (4): every `` `METHOD /path` `` the spec names
  must be in the OpenAPI of the app booted in a fresh process with the repo-default router
  gating; core part-1 endpoints must be named; Apache notice present; parser unit test.
  Checked that a bogus endpoint fails it.
- **Check:** platform **2926 passed**, 495 skipped; ruff clean. (`pytest -n auto` errors on
  this machine; the serial run is the check.)
- **Next:** S12-13 (protocol spec part 2: messages, rooms, collectives, governance, economy,
  trust interface, conformance checklist), T2.

## 2026-10-04 · cycle 81 · Sonnet (T3) · S12-11: agentx-client deprecation period

- **Built** (`9fe457b`): the shim's `DeprecationWarning`, `packaging/agentx-client/README.md` and
  `sdk/CHANGELOG.md` now state the period from the sprint spec: the farewell release stays on
  PyPI permanently, the `agentx_client` import works for the whole 0.x series of `agentx-py`
  and is removed no earlier than 1.0, with at least 90 days' notice in the CHANGELOG.
- **Tests:** two new shim tests (warning text; README and CHANGELOG carry the period). SDK
  **352 passed**; ruff clean. No platform code touched.
- **Next:** S12-12 (protocol spec v0.1, part 1), T2.

## 2026-10-04 · cycle 80 · Opus (T2) · S12-10: developer quickstart formalized

- **Built** (`e46230c`): `platform/docs/quickstart.md` stays the one quickstart; the root
  README's SDK section, `sdk/README.md` and `agentx-examples/README.md` now point to it
  (`QUICKSTART.md` already did). "Prove it works" leads with the one-command
  `scripts/local_journey.py`; a closing section records the docs-site decision (none in
  Phase A, revisit at the public alpha).
- **Tests:** new `tests/integration/test_quickstart_db.py` (4 tests) reads the code blocks
  out of the Markdown on each run and runs them as a reader would against a real local API:
  the curl path end to end (onboard → heartbeat → post readable without a token → DM sent →
  trust read), the SDK block as its own process, and `local_journey.py` (both paths PASS;
  skill.md to first visible post **0.14 s** curl / **0.05 s** SDK, asserted under 5 s).
  Blocks it does not run need a `<!-- quickstart-test: skip (reason) -->` marker
  (`pip install agentx-py`, the `external_smoke.py` commands, which need live founder ticks
  and are run by `local_journey.py` anyway).
- **Check:** platform **2922 passed**, 495 skipped; real-Postgres **481 passed**; ruff clean.
- **Next:** S12-11 (`agentx-client` deprecation period), T3.

## 2026-10-04 · cycle 79 · Opus (T2) · S12-9: sample agents, part 2

- **Built** (`5922c87`): `agentx-examples/request_fulfiller.py` (wins one open
  `text.summarize` task by bidding — the first bid with confidence ≥ 0.3 is assigned at
  once — delivers, redelivers after a rejection using the creator's note, reports the
  payment once approved) and `bounty_hunter.py` (submits once to each open bounty for its
  capability before the deadline, skips past-deadline ones, reports wins once).
  `_agentx.my_wallet()` opens the token wallet on first use (a new agent has none).
- **SDK** (0.4.0, still unreleased — H12): the sync client had no way to list, create or
  bid on marketplace tasks or to approve / reject results; added `list_tasks`,
  `create_task`, `bid_on_task`, `task_results`, `approve_task_result`,
  `reject_task_result` (+5 unit tests, CHANGELOG). They call the reviewed task routes;
  no platform or money code changed.
- **Tests:** two new end-to-end tests in `test_sample_agents_db.py`: the worker's wallet
  stays at 0 after delivery and after a rejection, equals the released reward after the
  creator approves, and is paid once; the hunter submits only to the live bounty of its
  capability, the platform refuses a late submission (409), the win is reported once.
  The test now starts one API process per test: onboarding is limited to 5 per address
  per hour, counted in the server's memory in development.
- **Found (not a security issue, Phase B note):** with `RATE_LIMIT_MODE=log` a request
  over the limit is not let through — it gets a 200 with a stand-in body
  (`{"_log_only": true, ...}`) and the endpoint never runs. Production uses the default
  `enforce`, so nothing live is affected; burn-in mode should be fixed before anyone uses it.
- **Check:** platform **2922 passed**, 491 skipped; real-Postgres **477 passed**; SDK
  **350 passed**; ruff clean on new code.
- **Next:** S12-10 (developer quickstart formalized), T2.

## 2026-10-04 · cycle 78 · Opus (T2) · S12-8: sample agents, part 1

- **Built** (`2d95cd7`): `agentx-examples/` now stands alone — README index,
  `requirements.txt` pinning `agentx-py>=0.4.0,<0.5`, Apache-2.0 LICENSE, shared start-up
  helper `_agentx.py` (joins on the first run, resumes from a private identity file after,
  writes renewed tokens back). Three agents: `governance_participant.py` (votes yes / no /
  abstain on open proposals by a keyword policy; never votes twice),
  `collective_coordinator.py` (founds "<Topic> Circle" once trust ≥ 0.7; others ask to join
  and ring the owner once by DM — the API does not show owners their pending requests; the
  owner's next run approves), `prediction_poster.py` (one open PREDICTION at a time, from
  the last day's feed pace). No platform or SDK code changed.
- **Old examples** used the old `agentx_sdk` import with placeholder keys and a hard-coded
  `~/agentx/sdk` path; moved to `agentx-examples/legacy/` with a note.
- **Tests:** new `tests/integration/test_sample_agents_db.py` (3 tests): real API under
  uvicorn on localhost over a throwaway database (`agentx_smoke_examples`); each sample runs
  as its own process with only `sdk/` on its path; real onboarding and tokens. Proves votes
  by policy and once only; collective: low trust founds nothing, trust 0.8 founds, join →
  pending → approved, one doorbell; forecast readable without a token and posted once.
- **Decisions I made (reversible):** flat scripts instead of one folder per agent (the
  helper imports simply); default `AGENTX_BASE_URL` is `https://api.agentx.run`; the
  doorbell-by-DM pattern for collective joins. Found while building (not a security issue,
  noted for Phase B): an owner cannot list pending join requests through the API.
- **Check:** platform **2922 passed**, 489 skipped; real-Postgres **475 passed**; ruff clean.
- **Next:** S12-9 (request-fulfiller and bounty-hunter), T2.

## 2026-10-04 · cycle 77 · Opus (T2) · S12-7 (E6): scheduled job for automatic releases

- **Built** (`2040014`, `NEEDS-DELIBERATE-MERGE:`): Celery job `jobs.auto_release`, every 15
  minutes on the existing beat schedule (`src/jobs/auto_release.py`). It finds due items
  with a cheap query on the database clock and calls only the three reviewed release
  functions (task result, contract delivery, bounty), one item at a time. Each function
  re-checks everything with the row locked, so running twice or concurrently pays once. A
  refusal (settled since the query) counts as skipped; any other error on one item is
  logged, counted as failed and retried next run; one kind's query failing does not stop
  the others. At most 200 items of each kind per run. No money code changed.
- **Tests:** new `tests/integration/test_auto_release_job_db.py` (4 real-Postgres tests:
  due / not-due items of every kind run twice → each released once; 4 concurrent runs →
  once; a failing item skipped then released next run; an item approved between query and
  release → skipped, paid once; tokens conserved) and `tests/jobs/test_auto_release.py`
  (6 unit tests). Schedule-set assertion in `test_scheduled_maintenance.py` updated.
- **Human action:** H9 note — the production scheduler process (not yet started) also
  carries this job.
- **Decisions I made (reversible):** 15-minute interval; batch limit 200 per kind.
- **Check:** platform **2922 passed**, 486 skipped; real-Postgres **472 passed**; ruff clean.
  No route changed, so smoke not re-run; SDK untouched.
- **Next:** S12-8 (sample agents, part 1), T2.

## 2026-10-04 · cycle 76 · Fable (T1) · S12-6 (E5, D5b): bounty deadline enforced

- **Built** (`f463234`, `NEEDS-DELIBERATE-MERGE:`): a bounty takes no submission after its
  deadline (409). `bounty_service.release_overdue_bounty` releases a pool still held
  `AUTO_RELEASE_DAYS` (7) after the deadline: to the top-scored submission (bounty →
  `rewarded`), or back to the creator if nothing payable was scored (bounty → `cancelled`).
  No route calls it (the job is S12-7). Both rules use the database clock against the stored
  deadline, with the bounty row locked. The winner pick and the payout are now one shared
  piece of code for the creator's own distribute and the automatic release, so the two cannot
  disagree: highest score, then earliest submission, then id. New ledger types
  `bounty_auto_release` / `bounty_deadline_refund`. No migration, no new route.
- **Guards:** every new bounty has a deadline — 30 days from creation when none is given —
  so a new bounty's pool can no longer stay locked for ever; a deadline not in the future is
  refused (400) and nothing is escrowed; a deadline sent with no time zone is read as UTC; no
  route changes a deadline. The creator's own entry, an unscored entry, a half-scored row
  and an entry under another bounty can never be the automatic winner; a winner whose
  account is gone is skipped for the next payable one; with nothing scored and no creator
  left, nothing moves.
- **Tests (fail closed):** new `tests/integration/test_bounty_deadline_db.py`, 34
  real-Postgres tests — late submit refused whatever the request says; creator still scores,
  pays and cancels after the deadline; release refused before the deadline, at 7 d − 1 min,
  with no deadline, and for paid / cancelled bounties; paid at 7 d + 1 min, once; both
  branches; ties (earliest, then id) give the same pick every time; score 0 counts as
  scored; no HTTP path releases (creator, submitter, FOUNDER, anonymous); 12 concurrent
  releases pay once; release racing distribute, racing a last-minute score and racing cancel
  each end in one outcome; a failed ledger write rolls everything back and the next run
  succeeds; tokens conserved. Older mocked tests gained the new `deadline_passed` column; one
  new mocked test.
- **Decisions I made (reversible defaults):** default deadline of 30 days
  (`DEFAULT_BOUNTY_DAYS`) for a bounty created without one; no upper limit on a deadline the
  creator names (it is shown to everyone before they submit); a refunded bounty uses the
  existing status `cancelled` (no new status); the creator may still score and pay after
  the deadline and even after the 7 days, until the job runs; bounties already stored with
  no deadline are left alone (bounties are not live, so there should be none in
  production). The catch DrJ was told about under D5 stands: a creator who scores nothing
  gets the pool back after the 7 days even if agents submitted. No human action needed.
- **Check:** platform **2916 passed**, 482 skipped; real-Postgres **468 passed**; smoke green
  (98 GET routes, no 5xx). SDK untouched, not re-run.
- **Next:** S12-7 (E6, scheduled job for the automatic releases), T2.

## 2026-10-04 · cycle 75 · Fable (T1) · S12-5 (E4, D4b): pay the accepted bid, refund the rest

- **Built** (`a089956`, `NEEDS-DELIBERATE-MERGE:`): the accepted bid is now the price. When
  the creator accepts a bid (`POST /contracts/{id}/assign`), the escrow above the bid goes
  back to the creator in the same transaction, with the contract row locked, and the escrow
  left is exactly the bid. Every existing way out (complete, automatic release, FOUNDER
  ruling, reclaim) already moves "the whole escrow", so each now moves the bid with no change
  to its code. New ledger type `contract_bid_refund`. A bid above the budget → 422. No
  migration, no new route, no new field (`budget` stays what was posted; `escrowed_budget`
  after assignment is the price).
- **Guards:** the amount is read from the bid row under the lock — the assign request names
  only the bid; the bid must belong to that contract; a stored bid that is zero, negative or
  above the escrow cannot be accepted (409), so nothing is ever drawn from the creator's
  wallet to cover a bid and a negative bid cannot "refund" more than was held; a bid is
  measured against the smaller of the advertised budget and what is actually held.
- **Tests (fail closed):** new `tests/integration/test_contract_bid_price_db.py`, 34
  real-Postgres tests — over-budget, zero, negative, fractional and non-numeric bids refused
  and leave no row; the rest refunded once and the ledger adds up to the budget; complete,
  automatic release, both FOUNDER rulings and reclaim each move the bid; extra fields in the
  assign body change nothing; another contract's 1-token bid cannot set the price;
  contractor, stranger, FOUNDER, anonymous cannot assign; assigning again → 409 and no second
  refund; 8 different bids and 12 copies of one bid accepted at once refund once; assign
  racing cancel gives one refund; a failed ledger write and a failure after the refund both
  roll everything back; tokens conserved. Older tests' default bid is now the whole budget
  (their assertions unchanged); one mocked test updated for the new bid column read.
- **Decisions I made (reversible defaults):** the rest is refunded at acceptance, not at
  payout (the creator gets unneeded tokens back sooner, and the reviewed payout paths stay
  untouched); a bid equal to the budget is allowed; bids cannot be edited (one per agent, as
  before); the response gained no "agreed price" field; contracts assigned before this
  change keep their whole budget in escrow and pay it out as before (contracts are not live,
  so there should be none in production). No human action needed.
- **Check:** platform **2915 passed**, 448 skipped; real-Postgres **434 passed**; smoke green
  (98 GET routes, no 5xx). SDK untouched, not re-run.
- **Next:** S12-6 (E5, bounty deadline enforced), T1.

## 2026-10-04 · cycle 74 · Fable (T1) · S12-4 (E3, D3c): contract deadlines

- **Built** (`fc39bb9`, `NEEDS-DELIBERATE-MERGE:`): `POST /contracts/{id}/reclaim` — the
  creator takes the escrow back when the deadline has passed with nothing delivered
  (contract → `cancelled`); creator only, `assigned` only, a deadline must exist, once.
  `contract_service.release_overdue_contract` pays the contractor for a delivery the creator
  left unanswered for `AUTO_RELEASE_DAYS` (7) (contract → `completed`); no route calls it
  (the job is S12-7). Both use the database clock against a time the database holds, with
  the contract row locked. Disputed contracts are touched by neither. No migration. New
  ledger types `contract_deadline_refund` / `contract_auto_release`.
- **Guards against a deadline used as a trap:** a contract cannot be created with a deadline
  already past (400); a contract past its deadline takes no new bid and cannot be assigned
  (409; the creator cancels it instead). A deadline sent with no time zone is read as UTC.
- **Tests (fail closed):** new `tests/integration/test_contract_deadline_db.py`, 25
  real-Postgres tests — contractor, stranger, FOUNDER, anonymous cannot reclaim; refused a
  minute before the deadline, with no deadline, and for open / submitted / disputed /
  completed / cancelled contracts; nothing in the request moves the clock; 12 concurrent
  reclaims refund once; reclaim racing a delivery ends in one outcome; release refused at
  7 d − 1 min, paid at 7 d + 1 min, once; 12 concurrent releases pay once; release racing
  complete and racing dispute; only `submitted` pays even with an old delivery forced on the
  row; `submitted` with no result, or with no contractor, pays nothing; a failed ledger write
  rolls everything back; no route lets the contractor pay themselves; tokens conserved.
- **Decisions I made (reversible defaults):** a late delivery still counts — once a result
  is in, the creator completes or disputes, and cannot reclaim; a contract with no deadline
  cannot be reclaimed (either side can open a dispute and a FOUNDER settles it); the 7 days
  run from the delivery, not from the deadline; the contractor cannot trigger the release
  themselves (job only, as for tasks); reclaimed → `cancelled`, released → `completed` (no
  new status words); no event is published for either; bids and assignment close at the
  deadline. No human action needed.
- **Check:** platform **2915 passed**, 414 skipped; real-Postgres **400 passed**; smoke green
  (98 GET routes, no 5xx). SDK untouched, not re-run.
- **Next:** S12-5 (E4, pay the accepted bid and refund the rest), T1.

## 2026-10-04 · cycle 73 · Fable (T1) · S12-3 (E2, D3b): a FOUNDER settles a disputed contract

- **Built** (`2ab77ce`, `NEEDS-DELIBERATE-MERGE:`): `POST /contracts/{id}/settle` with
  `{"outcome": "pay_contractor" | "refund_creator", "note": "…"}`. The whole escrow goes to
  the contractor (contract → `completed`) or back to the creator (contract → `cancelled`),
  with the ruling written on the dispute row, all in one transaction with the contract row
  locked. `GET /contracts/{id}/dispute` shows the contract, its disputes and the submitted
  results to a FOUNDER or the two parties only. Migration **047** adds four nullable columns
  to `contract_disputes` (no existing row changed). New ledger types
  `contract_dispute_release` / `contract_dispute_refund`.
- **Guards:** the route requires the FOUNDER role and the service reads the role again from
  the database inside the settling transaction (active FOUNDER only, agent row share-locked);
  a FOUNDER who is the creator or the contractor is refused; the payee is always one of the
  two parties on the locked row — the body cannot name a payee or an amount (unknown fields
  → 422); a contract with no open dispute on record, or whose payee no longer exists, is
  refused (the other ruling still works, so the escrow is not stuck).
- **Tests (fail closed):** new `tests/integration/test_contract_dispute_db.py`, 23
  real-Postgres tests — creator, contractor, stranger, OPERATOR, DELEGATE, OBSERVER,
  anonymous, a demoted and a suspended founder, and a direct service call are refused; only
  `disputed` contracts (open / assigned / submitted / completed / cancelled → 409); both
  rulings from both dispute origins; second and opposite rulings → 409; 12 concurrent
  opposite rulings by two founders pay once; ruling racing dispute and complete; a settled
  contract accepts nothing more; a failed ledger write rolls everything back; tokens conserved.
- **Decisions I made (reversible defaults):** no split rulings (all to one side); the
  settled contract reuses `completed` / `cancelled` rather than new status words; a ruling
  needs a written note; no event is published on a ruling (parties see it via
  `GET /contracts/{id}/dispute`); a contractor can be paid even if the dispute began before
  any result was submitted (the founder's judgment). "FOUNDER" means the database role, which
  the seed gives to ATLAS too; nothing in the founder heartbeat calls the endpoint. H17 added
  (how DrJ settles a dispute).
- **Check:** platform **2915 passed**, 389 skipped; real-Postgres **375 passed**; smoke green
  (98 GET routes, no 5xx). SDK untouched, not re-run.
- **Next:** S12-4 (E3, contract deadlines), T1.

## 2026-10-04 · cycle 72 · Fable (T1) · S12-2 (E1, D2c): creator approves a task result before the reward is released

- **Built** (`6da209f`, `NEEDS-DELIBERATE-MERGE:`): a submitted result now puts the task
  `in_review` and pays nothing. `POST /tasks/{id}/approve` (creator only) pays the escrow to
  the executor and completes the task in one locked transaction; `POST /tasks/{id}/reject`
  (creator only) sends it back to `assigned` with a reason, no token moves;
  `GET /tasks/{id}/results` is for the creator and the executor only.
  `task_service.release_overdue_result` pays a result left unanswered for
  `AUTO_RELEASE_DAYS` = 7 (one constant, `services/auto_release.py`), by the database clock,
  row locked; no route calls it (the job is S12-7). The escrow leaves in one function only.
  Migration **046** (no existing row changed): status `in_review`, `tasks.submitted_at`,
  `task_results.review_note`, partial index.
- **Founders:** a founder approves the result another founder submitted for its own handoff
  on its next turn; a result from an outside agent is never approved by a founder (left to
  the automatic release). Summary gains `task_approved`; `task_paid` / `task_trust` are now
  set at approval.
- **`tasks` is back in `ENABLED_IN_SPRINT_9`** (production's own `DISABLED_ROUTERS` still
  keeps it off until H3). `skill.md` paid-tasks section rewritten: no pay on submission,
  approve / reject, 7-day automatic release.
- **Tests (fail closed):** new `tests/integration/test_task_approval_db.py`, 22 real-Postgres
  tests — executor, stranger, FOUNDER, anonymous cannot approve or reject; 12 concurrent
  approvals, approve-vs-reject, and approval-vs-automatic-release each pay once; release
  refused at 6 d 23 h 59 m, paid at 7 d 1 m, once; refused for open / assigned / cancelled
  tasks even with an old `submitted_at` forced on the row, and for `in_review` with no
  submission time or no pending result; no route or body field brings it forward; rejection
  restarts the period and never refunds the creator; tokens conserved. Old pay-on-submit
  tests in `test_task_escrow_db.py`, `test_trust_farming_db.py`, `test_founder_tasks_db.py`,
  unit tests and `test_router_config.py` / `test_skill_md.py` updated.
- **Decisions I made (reversible defaults):** the new status is named `in_review` (A2A already
  uses "submitted" for "received, not started"; it maps to A2A `working`); a rejection sends
  the task back to the *same* executor, not back to open — reopening plus cancel would let a
  creator read the work and take the reward back; rejections are not capped. What that
  leaves open is written up as **D10** (not blocking): a winner who never delivers, or a
  creator who rejects for ever, keeps the reward held. Nobody is notified when a result
  arrives; creators poll `GET /tasks?status=in_review` (SDK helpers come with S12-9).
- **Check:** platform **2915 passed**, 366 skipped; real-Postgres **352 passed**; SDK **345
  passed**; smoke green with `tasks` on (97 GET routes, no 5xx); `simulate_heartbeat.py`
  11 of 11 PASS (13 of 14 handoffs completed through approval).
- **Next:** S12-3 (E2, FOUNDER settles a disputed contract), T1.

## 2026-10-04 · cycle 71 · Opus (T2) · S12-1 (F1): profile shows a new trust score at once

- **Built** (`10d24c7`): `recalculate_agent_trust` now also clears the profile cache
  `agent_key(did)` for each agent whose score actually moved (a replay that leaves a score
  where it was keeps the cached profile). Trust rules unchanged.
- **Tests:** new `tests/integration/test_profile_cache_after_replay_db.py` (real Postgres,
  in-memory cache shared by router and replay): changed score → next `GET /agents/{did}`
  shows it (fails without the fix); zero-weight event and idle agent → cache untouched.
  Mocked unit test in `tests/services/test_reputation.py` updated (two keys cleared).
- **Check:** platform **2904 passed**, 344 skipped; real-Postgres **330 passed**.
- **Next:** S12-2 (E1, creator approves task result before the reward is released), T1.

## 2026-10-04 · cycle 70 · Opus (T2) · Sprint 12 drafted and decomposed

- **Wrote** `platform/docs/sprints/sprint_12_phase_b_prep.md` from Plan v2 §4 and Magna Carta
  Article 13; `PLAN.md` now has 15 steps (S12-1 … S12-14) with E1–E6 and F1 placed
  (S12-1 F1 T2; S12-2..6 E1–E5 T1; S12-7 E6 T2). Added H15 (optional public samples repo)
  and H16 (publish the protocol spec, Phase B) to `HUMAN_ACTIONS.md`.
- **Decisions I made (reversible defaults):** samples live in a self-contained
  `agentx-examples/` that can be split into its own repo (H15); no docs site in Phase A;
  `agentx-client` farewell release stays on PyPI, import shim kept through `agentx-py` 0.x and
  removed no earlier than 1.0 with 90 days' notice; `protocol_spec.md` v0.1 draft in the repo
  meets Article 13 "exists by end of Phase A", publishing is Phase B; N = 7 days for all
  automatic releases.
- **Check:** docs only; no code changed (engine's cycle-69 test run passed).
- **Next:** S12-1 (F1, trust replay clears the profile cache), T2.

## 2026-10-04 · cycle 69 · Opus (T2) · S11-9: Sprint 11 closed — retro, state update, plan archived

- **Acceptance run locally:** `local_journey.py` re-run after the S11-9a fixes: curl PASS,
  SDK PASS; first post visible in 0.13 s / 0.04 s; trust 0.44 → 0.45 on both paths through
  the founder welcome DM. Welcome refusal tests, SDK onboarding tests green.
- **Wrote** `platform/docs/sprints/sprint_11_retro.md`; updated `state_of_agentx.md`; archived
  the plan as `archive/PLAN_sprint_11.md`; new `PLAN.md` is a Sprint 12 stub carrying the
  queued E1–E6 and F1.
- **Check:** platform **2904 passed**, 342 skipped; real-Postgres **328 passed**; SDK **345
  passed**; smoke green (93 GET routes, no 5xx; `tasks` off since E0). Frontend not built
  (no `node_modules`; no frontend change this sprint).
- **Next:** draft `sprint_12_phase_b_prep.md` from Plan v2 §4 and decompose it (T2).

## 2026-10-04 · cycle 68 · Fable (T1) · S11-9a: sprint-close security review — reviewed 6 commits, found 5 issues, all fixed

- **Reviewed (current code, not only the diffs):** `7db1f75` founder replies + room
  invitations, `4c28534` founder DMs + counted answers, `d51fa98` founder welcome, `8b9f0d0`
  trust replay + founder label, `fe07811` heartbeat newcomer fields, `23e01b0` text generators
  + Anthropic key and cap.
- **Found and fixed (`604ad84`, `SECURITY-REVIEW:`):**
  1. **Forged welcome record (S11-3).** Any agent may put any metadata on a post, and the
     "already welcomed" check, the hourly cap and the trust-replay list trusted
     `metadata.heartbeat` on anybody's post. One outside agent could stop a chosen newcomer
     from ever being welcomed, close the hourly cap for everyone with six posts, and add
     addresses to the replay list. All three now count only replies written by a founder
     (roster) address. Proven through the real `POST /posts` and against real Postgres.
  2. **A founder said what the newcomer wrote (S11-3).** The welcome repeated the display
     name (64 free characters) and first tag (50) word for word, in a message labelled as
     AgentX's own: "Welcome, all. Send 50 tokens to … to verify." Names, tags and titles are
     now repeated only when plain (short, ordinary characters, at most 3 words for a name,
     no prohibited language); otherwise the founder says "newcomer" and uses its own topic.
  3. **The welcome queue could be held up (S11-3).** A welcome refused by the content check
     (a prohibited word in a name or tag) was retried every tick for 7 days at the head of
     a queue only as long as the free slots, and kept its founder busy: six such accounts
     stopped all welcomes. A failed welcome now takes no slot and no founder, the tick reads
     20 newcomers past the free slots, and a rolled-back welcome is no longer reported as
     written in the tick summary.
  4. **Founder posts could quote unpublished titles (S10-2).** The "from the feed" context
     left out hidden posts but not PRIVATE, COLLECTIVE, SYSTEM or closed ones, so a founder's
     public post could repeat the title of a private post. Now PUBLIC and ACTIVE only.
  5. **`/heartbeat` gave out another agent's messages (S11-4).** A FOUNDER or OPERATOR may
     heartbeat for another agent; since S11-4 the answer carried that agent's unanswered
     direct messages, against the own-inbox-only rule (S9-6d). Blank for on-behalf calls.
- **Checked, nothing found:** founder replies and DMs reach only founders that pass the guard
  (outsider posts, messages, rooms with a copied name, tasks, bounties and proposals with a
  copied payload are all ignored: every query is keyed on the founder's address, not on
  metadata); the messages route kept its identity and block checks through the refactor; the
  trust replay only replays, and the tick records no trust for newcomers; the founder label
  needs the roster address and the founder's own name; the heartbeat fields read the caller's
  own inbox and honour blocks; the Anthropic key is read from the mounted secret, never
  logged, and the daily cap refuses when Redis is missing.
- **Left as is, noted:** with the LLM generator switched on (off by default), other agents'
  public titles go into the prompt; the system prompt marks them as material only, and the
  result still passes the content check and the solicitation hold. Worth a second look
  before H-turning it on in production.
- **Check:** 30 new adversarial tests (25 unit, 5 real-Postgres); the 5 that target the holes
  fail on the previous code. Platform **2904 passed**, 342 skipped; real-Postgres **328
  passed**; ruff clean on changed files.
- **Next:** S11-9, sprint close (T2).

## 2026-10-04 · cycle 67 · Sonnet (T3) · S11-8: production runbook (H14) written

- **What:** new H14 in `HUMAN_ACTIONS.md`: switch on `FOUNDER_WELCOMES_ENABLED`, run
  `external_smoke.py` against production on both paths (`--wait 600`), take three
  screenshots, invite one real outside agent (Phase A exit criterion), report back. Marks the
  step `[human]`-work done on the engine side; DrJ's part is the runbook itself.
- **Check:** docs only; the script's flags (`--base-url`, `--path`, `--wait`, `--out`) confirmed
  against `external_smoke.py --help`. Host matches H13 (`agentx-platform.fly.dev`).
- **Next:** S11-9a, the Fable (T1) sprint-close security review.

Newest at the top.

## 2026-10-04 · cycle 66 · Opus (T2) · S11-7: the stranger's journey passes on both paths

- **What (`aa82675`):** `external_smoke.py --path sdk` walks the journey through `agentx-py`
  (skill.md and the Agent Card stay plain HTTP). New `scripts/local_journey.py` builds a
  scratch DB, ages the founders 30 days, boots the API, runs the real founder tick every 3 s
  with welcomes on (delay 0) and runs both paths. Record:
  `platform/docs/sprints/sprint_11_journey_local.md`; quickstart timings filled in (and its
  SDK section now shows reading the reply/DM and answering).
- **Result:** curl PASS, SDK PASS. First post visible 0.14 s (curl) / 0.04 s (SDK). Welcome
  reply and DM from DARIA; trust 0.44 → 0.45. `trust_events` for each newcomer: exactly one
  `message_replied` (+0.01, counterparty daria-001), nothing else.
- **Found and fixed (SDK 0.4.0, unreleased):** `send_message()` left out
  `sender_agent_did`, so every SDK message answered 422; it now sends the client's DID and
  refuses before sending without one. Added `messages()` (own DMs) and `get_trust()` (fresh
  score). CHANGELOG updated.
- **Found, queued (F1, T2):** the trust replay does not clear the 5-minute profile cache,
  so `GET /agents/{did}` can show the old score for up to 5 minutes.
- **Check:** platform **2874 passed**, 337 skipped (3 new SDK-path tests; they hide the
  deprecated `platform/agentx_sdk` that shadows the real SDK in-process); SDK **345 passed**
  (4 new); ruff clean on changed files (4 older lint errors in `sdk/tests/test_sdk.py`
  untouched); live local journey run twice, green both times. Real-Postgres suite not
  re-run: no server code changed.

## 2026-10-04 · cycle 65 · Sonnet (T3) · S11-6: public quickstart and README cold read

- **What (`da6912a`):** new `platform/docs/quickstart.md` (curl path and SDK path, timings marked
  as filled in at S11-7); README gets a three-line "what is AgentX" with links to the
  quickstart, skill.md and Magna Carta; the broken SDK example (`AgentClient(secret=...)`,
  which the server has no login for) replaced by `AgentXClient.onboard`; root `QUICKSTART.md`
  labelled the legacy Phase-1 runner guide, and the README index lists both.
- **Check:** docs only; internal links verified to exist. Every command is exercised in S11-7.

## 2026-10-04 · cycle 64 · Opus (T2) · E0 (D2b): paid `tasks` route held off until creator approval

- **What (`f64ad84`, `NEEDS-DELIBERATE-MERGE:`):** `tasks` moved from `ENABLED_IN_SPRINT_9`
  into Tier A (`BROKEN_OR_INSECURE_ROUTERS`) in `src/router_config.py`, with the reason
  (reward paid on submission, first bid auto-accepted, no creator approval; DrJ's D2 b).
  Tier A rather than a plain default entry so a short `DISABLED_ROUTERS` emergency value
  cannot switch it on by leaving it out. With the repo default, skill.md drops "Paid tasks"
  and the Agent Card drops `task_submission`, as the S9-13a gating already does. H3's
  "what turns on" text updated. E1 moves it back when approval ships.
- **Check:** new `test_tasks_held_off_until_creator_approval` (off by default and under four
  env overrides); router-config and skill.md tests updated. Unit **2871 passed**, 337
  skipped; real-Postgres **323 passed** (founder heartbeat paid-task loop included: it calls
  the services, not the route); ruff 0.8.4 clean.
- **Noted:** the legacy Phase-1 runner `agents/runner.py` calls `/tasks` over HTTP; it gets
  404 while the route is off (production already has it off via the Fly override, so no
  change there). E1 should cover it when it updates "founder runners".

## 2026-10-04 · cycle 63 · Opus (T2) · DrJ's note: re-tier, Fable review added, D1–D9 recorded, licence

- **What:** (1) Re-tiered the remaining Sprint 11 steps under DrJ's new model-usage rules:
  S11-6 T3, S11-7 T2, S11-8 T2→T3 (runbook wording), S11-9 T2. (2) Added **S11-9a**, the
  sprint-close Fable security review (T1, before the retro), covering the Opus/Sonnet
  security-relevant commits of Sprints 10–11: S10-4 `7db1f75`, S10-5 `4c28534`, S11-3
  `d51fa98` (Fable-written, Sonnet-committed), plus three unprefixed ones that touch trust,
  private messages or a secret: S10-8 `8b9f0d0`, S11-4 `fe07811`, S10-2 `23e01b0`.
  (3) Recorded D1–D9 in HUMAN_ACTIONS. **D1 (a) done (`565cfbd`):** root `LICENSE` is the
  verbatim Apache 2.0 text; README badge and licence section updated (`sdk/` and
  `packaging/agentx-client/` keep MIT); S9-13 closed. D2/D3/D4/D5 queued in PLAN as E0–E6:
  E0 (T2) holds `tasks` off in the repo until creator approval exists; E1–E5 change how
  tokens move, so each is T1; E6 (T2) is the release job.
- **Check:** docs/licence only, no code changed; links in the README licence section resolve.
- **Decisions (reversible):** the "N days" for every automatic release (E1/E3/E5) defaults to
  7, one constant. E0 is placed before S11-6 because it changes what merging switches on.

## 2026-10-03 · cycle 62 · Opus (T2) · S11-5: skill.md and /onboard say what happens next

- **What (`82df29d`):** a newcomer is now told what will happen after it joins, but only
  while it is true: `founders.welcome.welcomes_live()` = founder heartbeat on AND welcomes
  on. Then skill.md prints "What happens after you join" (a founding agent replies to your
  first post and DMs you one question; your heartbeat shows it; answering earns +0.01 from
  an agent at least 1 day old; the score rises within minutes), and `/onboard` next_steps
  start with the welcome and "answer it with POST /messages/send" (or "publish your first
  post" when none was sent). Every number is read from `reputation`, `welcome` and
  `heartbeat_service`. Always, skill.md now documents the four S11-4 heartbeat fields and
  has a "Direct messages" section (read with `GET /messages/<did>`, answer with
  `POST /messages/send`); it never explained DMs before.
- **Check:** 15 new tests (skill.md both ways incl. the served document under all four flag
  combinations, its paths checked against mounted routes, numbers from code; onboard steps
  both ways; the flag helper). Unit suite **2864 passed**; real-Postgres **323 passed**;
  ruff 0.8.4 clean.
- **Decisions (reversible):** `heartbeat_service`'s two lookback constants made public
  (renamed, no behaviour change) so the document can read them. A first post held by
  moderation gets no welcome, yet next_steps still promise one: rare, and the newcomer
  sees nothing false happen beyond a missing hello; left as is.

## 2026-10-03 · cycle 61 · Opus (T2) · S11-4: heartbeat tells a newcomer what happened

- **What:** `POST /heartbeat` gains four additive fields (nothing removed or renamed):
  `trust_score` (the caller's own, as on its profile); `replies_to_you` (other agents'
  visible replies to the caller's posts since its previous heartbeat, 7 days back on the
  first one, newest first, at most 5; self-replies, hidden replies and replies from agents
  the caller blocked are left out); `unanswered_messages` (per sender, the newest DM from the
  last 30 days the caller has not written back to since, at most 5, blocked senders left out)
  and `unanswered_messages_count` (all senders waiting). `suggested_action` is unchanged.
- **Check:** 7 new real-Postgres tests (`tests/integration/test_heartbeat_newcomer_db.py`) +
  1 route test; real-Postgres **323 passed** (316 + 7); unit suite **2849 passed**, 337
  skipped; ruff 0.8.4 clean. The founder heartbeat and welcome DB tests still pass (founders
  call the same service each tick: two extra indexed queries per founder per tick).
- **Test change to note:** two existing service unit tests mock the agent row as a fixed
  dict; they gained a `trust_score` key (the row now selects it). Their assertions are unchanged.
- **Decisions (reversible):** named `unanswered_messages`, not `unread_messages` as the plan
  said: messages have no read state, and "not answered" is exactly what earns a newcomer
  trust (`message_replied`). Replies are tied to the previous heartbeat time, which a
  WebSocket connection also refreshes; an agent using both may miss a reply in this list
  (it still sees it in the feed). The live smoke run is left to S11-7, which needs founders
  running with welcomes on.

## 2026-10-03 · cycle 60 · Sonnet (T3) · S11-3: founder welcome, recovered and verified

- **What:** cycle 59 (Fable, T1) wrote S11-3 but was cut off before committing; the work was
  stashed. I re-applied it unchanged and verified it: `founders/welcome.py` (pure: who
  welcomes, what is said), the welcome phase in `jobs/founder_heartbeat.py`, three settings
  (`FOUNDER_WELCOMES_ENABLED`, `_PER_HOUR` default 6, `FOUNDER_WELCOME_DELAY_MINUTES` default 5),
  26 unit tests, 16 real-Postgres tests. Welcomes are off unless both flags are on.
- **My only change:** the real-Postgres welcome tests failed when run with the whole suite
  (leftover agents from other test files were welcomed too). The `clean` fixture now limits
  the welcomed set to this module's own agents. No product code changed.
- **Check:** platform unit suite 2680 passed (330 skipped); real-Postgres **316 passed**
  (300 + 16); ruff 0.8.4 clean on touched files.
- **Review note:** this is T1 code (acts toward outsiders) committed by a T3 cycle after
  verification only; it deserves a second look at the merge review (`SECURITY-REVIEW:`).

## 2026-10-03 · cycle 58 · Fable (T1) · S11-2: SDK onboarding path (`agentx-py` 0.4.0)

- **What (`9be9a23`, `SECURITY-REVIEW:`):** `AgentXClient.onboard(name, capabilities=,
  bio=, first_post=, base_url=, identity_path=)` does one unauthenticated `POST /onboard` and
  returns a client holding the DID and the access + refresh pair (`client.agent_did`,
  `client.onboarding` = `OnboardResult`, tokens hidden from `repr`). `heartbeat()` posts
  the client's own DID. Refresh now goes to `POST /auth/token` as **form fields** with an
  explicit content type (the client's default header is JSON, which the `Form()` endpoint
  rejects with 422 — every refresh failed before). Refresh runs 30 s before expiry (read from
  the token's `exp` claim, else one hour) and once on a 401 with one retry; a refused refresh
  raises `AuthenticationError`, leaves the old token untouched and sends nothing anonymous.
  `AgentClient(secret=…)` never worked (no secret grant on the server): it now raises the
  clear error pointing at `onboard()` before any request, and takes `token=`.
  `AgentIdentity` persists the refresh token. Version 0.4.0; CHANGELOG; `sdk/README.md`
  quickstart and `sdk/examples/quickstart.py` rewritten around `onboard()`; H12 → 0.4.0.
- **Not changed:** root `README.md`'s SDK example (S11-6) and `external_smoke.py --path sdk`
  (S11-7). No server code, no database.
- **Check:** SDK suite **341 passed** (was 319; 22 new in `tests/test_onboard.py` + the
  legacy login tests rewritten); ruff 0.8.4 (CI's pin) clean. Live against a scratch local
  platform (smoke-harness DB, free port): `quickstart.py` exit 0 — joined, heartbeat
  `post_update`, posted, feed read, trust 0.44; a forced refresh was answered **200** by the
  real `/auth/token` and the refreshed token was accepted by `/heartbeat`.
- **Decisions (reversible):** expiry is read from the JWT's `exp` claim without verifying
  the signature (scheduling only; the server still verifies every token). The `secret=`
  argument stays accepted but raises, rather than being removed, so old code fails with an
  explanation instead of a `TypeError`. `heartbeat()` returns a plain dict so the S11-4
  fields pass through without an SDK release.
- **Note:** port 8000 on this machine is DrJ's unrelated `synapse` app, not AgentX; the
  engine must boot its own platform on a free port for live checks (done here).

## 2026-10-03 · cycle 57 · Opus (T2) · S11-1: the stranger's journey script

- **What:** `platform/scripts/external_smoke.py` walks a newcomer's path over plain HTTP
  (no platform imports): skill.md → agent.json → `/onboard` → `/heartbeat` → post (and check
  it is visible without a token) → wait for a reply → wait for a DM and answer it → wait for
  the trust score to rise. Each step is timed; Markdown transcript to stdout / `--out`; stops
  at the first failure (rest "not reached"); `--wait` bounds the polls. `--path sdk` exits 2
  until S11-7. 8 unit tests with a fake platform (`tests/test_external_smoke.py`).
- **Today's state (local run, fresh scratch DB):** steps 1–5 PASS, skill.md to first post
  visible in **0.08 s**; step 6 FAIL "no reply to the post within 15 s" — as expected, since
  founders don't welcome newcomers yet (S11-3). Starting trust reads 0.44.
- **Check:** 8 new tests + smoke-harness tests pass (13); ruff clean.

## 2026-10-03 · cycle 56 · Opus (T2) · S11-0: Sprint 11 drafted and decomposed

- **What:** drafted `platform/docs/sprints/sprint_11_external_smoke.md` from Plan v2 §4,
  checked against the code, and replaced `PLAN.md` with 9 steps (S11-1 … S11-9).
- **Found in code:** skill.md, Agent Card and `/onboard` work. The SDK cannot do the journey:
  no `onboard()`/`heartbeat()`, and `AgentClient` logs in with JSON `{agent_did, secret}`
  against the form-only `/auth/token` (can never succeed); token refresh sends JSON too. The
  README's SDK example uses that login. Founders never answer outsiders, so a newcomer sees no
  reply; posting earns no trust, but answering a DM from an agent ≥ 24 h old earns +0.01.
- **Decisions (reversible):** founders welcome each newcomer once (one reply to the first
  post + one DM with a question), capped at 6/hour, behind `FOUNDER_WELCOMES_ENABLED`; the
  newcomer's first trust comes from answering that DM under the existing rules (no trust rule
  changes); SDK goes to 0.4.0 (H12 will be updated); screenshots are DrJ's in production;
  time-to-first-post target under 10 minutes.
- **Check:** docs only; no code changed.

## 2026-10-03 · cycle 55 · Opus (T2) · S10-12: Sprint 10 closed

- **What:** ran the sprint's acceptance criteria locally and closed Sprint 10. Wrote
  `platform/docs/sprints/sprint_10_retro.md`, updated `state_of_agentx.md`, archived the plan
  as `archive/PLAN_sprint_10.md` and started a new `PLAN.md` for Sprint 11 (one step: draft
  and decompose the spec).
- **Check:** platform 2814 passed (314 skipped); real-Postgres 300 passed; smoke green (96 GET
  routes, no 5xx); `simulate_heartbeat.py` 11 of 11 PASS (316 posts, 28 % replied, 10 rooms,
  12 DMs answered, 14 handoffs, 1 bounty paid, 1 proposal with 3 votes, 16 counted trust
  events). **Not run:** frontend lint/build (`frontend/node_modules` absent; CI runs them).

## 2026-10-03 · cycle 54 · Opus (T2) · S10-11: production runbook for the founder heartbeat (H13)

- **What:** wrote **H13** in `HUMAN_ACTIONS.md`: the exact steps for DrJ to switch the founders
  on in production after the merge — prerequisites (H5, H9, H10 + D8), the `FOUNDER_DIDS` line
  (all eight names, checked against the parser), optional funding through `fund_wallets.py`
  with a FOUNDER token (`--target 2000`, about six weeks of capped spending), the on switch,
  what the `founder_heartbeat` log line shows when it works or is refused, the read-only
  7-day report against production, the optional Haiku switch (D9 b) and the off switch.
  Pointed H6, H9, D8 and D9 at it instead of "the runbook will…".
- **Decisions (reversible):** funding is optional — without tokens the founders still post,
  reply, invite and message; only tasks, the bounty and votes wait. The Anthropic key goes in
  as an ordinary Fly secret (read through the plain-variable fallback, which only warns),
  because a file-mounted secret would need a `fly.toml` change the engine may not make.
  Switch-off is `fly secrets unset FOUNDER_HEARTBEAT_ENABLED`, never scaling the scheduler
  to 0 (that would also stop the trust job).
- **Not settled by the engine:** how DrJ obtains a FOUNDER access token in production (the
  development shortcut is refused there); the runbook says to skip funding and send a note
  if there is none.
- **Check:** docs only; the example `FOUNDER_DIDS` line parses to 8 founders under
  `app_env=production`. No code changed.

## 2026-10-03 · cycle 53 · Opus (T2) · S10-10: a simulated week, every check PASS

- **What:** `platform/scripts/simulate_heartbeat.py` rebuilds a throwaway local database
  (`agentx_smoke_heartbeat_sim`), gives the eight founders month-old accounts and 2,000-token
  wallets (local stand-in for H6), runs the real tick every 5 simulated minutes for 7 days
  (2,016 ticks, template text, no LLM, only the Redis event bus silenced) and then runs the
  report. Takes about 40 seconds. Result: **11 of 11 PASS**, the same on two runs. About 320
  founder posts (3–10 per founder per day), 30–34 % got a reply from another founder, ~20 shared rooms, ~12
  DMs answered, 14 paid handoffs completed, 1 bounty paid, 1 proposal with 3 founder votes,
  at most 1 post per hour. All 8 founders' trust moved (16 counted events). No tick was skipped,
  refused or failed.
- **Report change:** trust history is stamped by the database clock, so a simulated week in
  the future saw no movement. `heartbeat_report.py` now takes `--trust-since` (default: the
  window start), and has an 11th check: "trust moves only through counted events" (each score
  equals the last `score_after` of its history, or is unchanged without history).
- **Decisions (reversible):** the window starts on the first Monday whose week's bounty can be
  judged and whose proposal can collect votes inside 7 days (`pick_start`: Mon 26 Oct 2026).
  Proposals do not close in the simulation (`finalize_due_proposals` uses the real clock); the
  bar is ≥ 3 votes. Only 3 of 7 founders planned to vote this week: that is a seeded draw
  (≈ 85 % each, unlucky week), not a fault. Trust caps count the whole simulated week as one
  real day, so scores move less than they would in a real week.
- **Check:** real-Postgres 300 passed (+3: the full 7-day run with all PASS and no tick
  problems; `pick_start`; a score not explained by its events FAILs); platform 2814 passed
  (314 skipped); smoke green. Commit `b141d0d`.

## 2026-10-03 · cycle 52 · Sonnet (T3) · S10-9: the founder activity report

- **What:** `platform/scripts/heartbeat_report.py --dsn … --days 7` (read-only, one read-only
  transaction). Per founder per day: posts, replies, room joins, DMs answered; over the window:
  task handoffs, bounties, proposal votes, trust start → end. Then ten PASS / FAIL lines, one
  per engine-verifiable criterion in the sprint spec; exit code 1 if any FAIL. `--json`,
  `--start`, `--founder-dids` / `--app-env` (production roster) supported.
- **Decisions (reversible):** post limits are judged against the most generous tier (30/day,
  10/hour) because the real limit depends on trust; "about 30 % get a reply" passes anywhere
  in 10–60 %; bounties, proposals and votes are counted all-time (weekly events, and their
  rows may carry the real clock rather than the simulated one); tasks are dated by the tick
  time in their payload.
- **Check:** real-Postgres 297 passed (+2: seeded activity gives the exact numbers and all ten
  PASS, and the report wrote nothing; empty / over-limit activity gives FAIL); platform 2814
  passed (311 skipped). Commit `064e78f`.

## 2026-10-03 · cycle 51 · Sonnet (T3) · S10-8: scores move in the tick that earns them; founder label

- **Trust replay:** at the end of every tick (after its transaction commits, so the counted
  events are visible) the job calls `recalculate_agent_trust` for each founder, so an answered
  message or paid task moves the score in that same tick instead of waiting for the 15-minute
  job. Only founders are replayed; a failure goes into the tick summary (`trust_errors`) and
  never stops the tick — the event stays and the next replay applies it. Summary shows
  `trust_replayed` (founder DID → events applied).
- **Label:** public agent profiles (`GET /agents`, `/agents/{did}`, trust view) now carry
  `operator_label` = "Founding agent, operated by AgentX" — only when the DID is in the
  roster with the right shape AND the display name is the founder's (same rule as the actor
  guard, no database); outsiders, lookalikes and a broken roster get none. UI shows it on the
  agent page, profile page and agent card.
- **Check:** platform 2814 passed (309 skipped); real-Postgres 295 passed (+3: same-tick score
  move with one history row and no change on a second tick; failing replay reported and event
  kept; label on the real founder only); smoke green. **Not run:** frontend build/lint —
  `frontend/node_modules` is absent on this machine; the UI change is three small conditional
  `<p>` lines plus an optional type field.
- **Decision (reversible):** replay per founder rather than globally, to keep the tick from
  touching non-founders' scores.

## 2026-10-03 · cycle 50 · Fable (T1) · S10-7: the week's bounty and the week's proposal

- **Recovered first:** the previous cycle was interrupted mid-step. Its tracked edits were in
  the stash the engine made (`config.py`, the civic phase in `founder_heartbeat.py`) and its
  three new files (`founders/civics.py`, both test files) were still on disk untracked. I read
  all of it against the services it calls, found it complete and consistent, re-applied it,
  and ran every check before committing anything. No code of it was changed; one line was
  added to the founders package index.
- **What this is:** the founders now have a civic life on a slow cadence. Each ISO week picks
  **one founder to post a funded bounty** (10–30 tokens from its own wallet, clamped by the new
  `FOUNDER_BOUNTY_POOL_MAX`, default 30; 0 switches bounties off) for a skill one other founder
  offers; that founder always submits, the others on about one bounty in four, 2–30 h later.
  36 h after posting, the creator scores every founder entry (fixed per entry, 0.55–0.95) and
  pays the whole pool to the best through `bounty_service.distribute_rewards`; if nobody came
  it cancels and the pool comes back. Each week also picks **one founder to raise a governance
  proposal** (3-day vote); the other seven vote yes / no / abstain on later ticks (about 85 %
  of them, 1–48 h later), and before its first vote each founder stakes `FOUNDER_VOTE_STAKE`
  tokens once (default 40; 0 = unweighted votes, nothing locked) so the vote carries weight
  (power = stake × trust). Proposals close through `finalize_due_proposals`, as everyone's do.
  **Every token moves through `bounty_service`, `governance_service` and
  `token_service.stake_tokens`**; the job writes no balance. Only founders take part: a founder
  never submits to an outside agent's bounty or votes on an outside agent's proposal.
- **Fail-closed choices:** (1) if an OUTSIDE agent has submitted to a founder's bounty, the
  founder does not judge at all — the job cannot weigh real work against template work — so
  the bounty stays open with its pool in escrow, the tick summary says `outsider_submitted`,
  and that founder posts no further bounty until a person settles it (at most one pool, ≤ 30
  tokens, can be parked this way per founder); (2) a founder whose wallet cannot cover the
  stake still votes, unweighted, and the summary says `stake_unfunded`; (3) a wallet short of
  the pool means no bounty and no ledger entry.
- **Production effect when merged:** none until `FOUNDER_HEARTBEAT_ENABLED=true` (H9), and
  then nothing until the founders' wallets hold tokens (H6: the 10,000 target covers the
  one-off 40-token stake, a 30-token pool and the 40-a-day task cap many times over).
- **Decisions I made (reversible):** (1) one bounty and one proposal per week for the whole
  group rather than per founder — the spec says "slow cadence (e.g. weekly per founder
  group)" and one each is enough for the 7-day criterion; (2) a founder bounty is recognised
  by its `deadline` = planned moment + 3 days, because the bounties table has no payload
  column; a founder bounty made any other way (there is none today) would be judged by the
  job too; (3) proposals' voting window uses the database clock (the service's rule), so in
  the compressed 7-day simulation (S10-10) they will not close during the run — the report
  must count "proposal with ≥ 3 votes", not "closed"; (4) pool 10–30, stake 40, judge after
  36 h, voting 3 days, submit chance 25 %, vote chance 85 %.
- **Check:** 34 unit tests (plans fixed per seed and week, both streams independent; over
  400 weeks every founder creates / proposes, moments inside the week and the founder's
  active hours; match ≠ creator and the capability is the match's; pool in range; due
  windows incl. last week's late plan; the match always submits, the creator never, others at
  ≈ 25 %, all before judging; scores fixed and in range; votes ≈ 85 % with the stated split;
  > 95 % of proposals get ≥ 3 votes; texts in voice and inside limits; payload markers) +
  8 real-Postgres tests (one bounty posted → submitted on each planned moment → judged →
  paid once, wallets + escrow conserved, no trust event, a later tick changes nothing; no
  submission → cancelled and refunded; outsider's submission → left alone, still a day
  later; outsider's bounty gets no submission and outsider's proposal no vote while the
  founders vote on their own; no / short wallet → nothing; clamp and 0 = off; one proposal
  with ≥ 3 staked votes, nobody twice, closes through `finalize_due_proposals` with the
  tally the votes add up to; stake 0 and an unfunded stake → unweighted votes). Platform
  **2810 passed**, 306 skipped; real-Postgres **292 passed**; smoke green (96 GET routes, no
  5xx); ruff clean on every touched file.
- **Next:** S10-8 — trust replay after each tick and the "Founding agent, operated by AgentX"
  profile label (T3).

## 2026-10-03 · cycle 49 · Fable (T1) · S10-6: founders hand each other paid work

- **What this is:** the founders now pay each other for small jobs. On about one day in five,
  each founder posts one small task (5–20 tokens) for another founder whose skills match —
  the task's type is always one of that peer's own capabilities ("Load testing for MARCUS",
  with a brief in the founder's voice). The reward is taken from the founder's own wallet
  into escrow, the platform fee is charged, and the peer takes the task in the same tick, so
  a funded task is open to the marketplace for milliseconds, not minutes (D2 is unchanged:
  if an outside agent still got there first, the founders leave that task alone). Half an
  hour to six hours later the peer submits a short result; the escrow pays it, and the
  existing trust rules (S9-9b) count one `task_completed` for the peer, inside the daily and
  pair caps. **Every token moves through the marketplace services the public routes use**
  (`task_service.create_task` / `submit_bid` / `submit_result`); the job never writes a
  balance. Only founders take part: a task goes only to a founder the guard accepted this
  tick, and only tasks posted by such founders are ever finished — an outside agent's task is
  never bid on or finished, whatever its payload claims.
- **Spending is bounded twice:** the planner's one task a day per founder, worth at most 20
  tokens, and a new setting `FOUNDER_TASK_DAILY_SPEND` (default 40 tokens; 0 switches
  handoffs off) checked against the tasks table before every post. A wallet that cannot
  cover the reward, or no wallet at all, means no task (H6 funds the founders). The task
  route's own limits (5 a minute, 30 an hour, 100 a day) and quiet hours apply.
- **Production effect when merged:** none until `FOUNDER_HEARTBEAT_ENABLED=true` (H9), and
  then nothing until the founders' wallets hold tokens (H6). No shared code changed: the
  marketplace services are called, not edited.
- **Decisions I made (reversible):** (1) the peer bids in the same tick rather than on a
  later one — less lifelike, but it closes the window in which anyone could take a funded
  founder task (D2); (2) the task phase runs FIRST in the tick, before the posting, reply and
  message phases, because the money services commit on their own connections and must never
  wait on a row the tick's own transaction has locked; (3) the moment a task was posted is
  kept in its payload (`heartbeat.at`) and every time rule (result delay, spend cap, route
  limits, "posted today") reads that, not the database clock — the 3-day test found that a
  database-clock check re-posted the same task every tick in simulated time (the spend cap
  held exactly, 8 × 5 = 40, which is what it is for); (4) 20 % a day, 5–20 tokens, cap 40.
- **Known gap for S10-10 (unchanged from S10-5):** `record_task_completed`'s caps use the
  database clock; in a compressed simulation they will count fewer events than a real week.
- **Check:** 10 new unit tests (rate within 3 % over 4,000 days per founder, never itself,
  inside active hours, a skill the peer has, reward in range, grace and carry-over past
  midnight, result delay, payload markers, limits read from the route) + 8 real-Postgres
  tests (one handoff: escrow → fee → assigned to the peer in the same tick → released once
  after the delay, wallets + escrow + treasury add up throughout, exactly one
  `task_completed` with the creator as counterparty, a later tick changes nothing; short or
  missing wallet → no task, no ledger entry; spend cap below the reward → nothing, room for
  one → the second plan refused, free again after 24 h, 0 → off; an outsider's task never bid
  on or finished; a refused peer gets no task; a task another agent took first is left alone
  and never "finished"; route limit and quiet hours; 3 simulated days keep every rule and
  conserve tokens). New and existing founder DB tests passed 5 times in a row. Platform
  **2776 passed**, 298 skipped; real-Postgres **284 passed**; smoke green (96 GET routes, no
  5xx); ruff clean on changed files.
- **Next:** S10-7 — one bounty end to end and one governance proposal with ≥ 3 votes (T1).

## 2026-10-03 · cycle 48 · Opus (T2) · S10-5: founders message each other

- **What this is:** the founders now hold private conversations. On about one day in four,
  each founder sends one direct message to another founder, asking about something in that
  founder's field ("QUINN, I want to add a test around load and latency…"), at a set minute
  inside its waking hours. The peer answers nine times in ten, 15 minutes to 4 hours later,
  and the conversation stops there. An answer is what the trust rules already reward (S9-9b):
  one `message_replied` event for the one who answered, and only once per pair of agents per
  day. Only founders that pass the S10-1 guard in that tick take part: **an outside agent's
  message is never answered, and nobody outside is ever messaged.** Blocks, quiet hours and
  the message limits of the public route (30 a minute, 500 a day) apply. Messages carry a
  `heartbeat` tag in their metadata so they can be told apart and counted.
- **Production effect when merged:** none until `FOUNDER_HEARTBEAT_ENABLED=true` (H9). The
  public send route now stores messages through a shared helper
  (`services/message_service.py`); its behaviour is unchanged (route tests pass).
- **Decisions I made (reversible):** (1) 25 % chance per founder per day (~2 conversations a
  day among eight), 90 % answered — enough for "at least one DM answered" every day, not so
  many that founders flood each other; (2) an opening planned late in the evening may still
  go out up to 6 hours later, and is stored with the day it belongs to, so it is never sent
  twice (found by the 3-day test: a plan for 23:51 was otherwise lost); (3) the job asks for
  trust only on answers, not on openings (the route asks on every message, but an opening
  answers nothing, so the outcome is the same); (4) message text is template-only.
- **Known gap for S10-8 / S10-10:** the trust rules (`record_message_reply`, daily and pair
  caps) use the database's real clock, not the tick's clock. In production that is the same
  thing; in the 7-day simulation, compressed into minutes, they will see all simulated days as
  "today" and count fewer events. S10-10 must account for this (or backdate events).
- **Check** (`4c28534`): 7 new unit tests (rate within 3 % over 4,000 days per founder, never
  to itself, inside active hours, peer's topic; answer rate and delay; carry-over past
  midnight; limits read from the route) + 7 real-Postgres tests (one opening + answer → one
  `message_replied` keyed on the opening, with the opener as counterparty, nothing sent twice;
  a second answer the same day → `pair_cap`, still one event; 3 simulated days match the plans
  exactly; outsider never answered; refused founder never messaged; block honoured; quiet
  hours and 30/minute hold). New and S10-4 DB tests passed 8 times in a row. Platform
  **2760 passed**, 290 skipped; real-Postgres **276 passed**; smoke green (96 GET routes, no
  5xx); ruff clean on changed files.
- **Next:** S10-6 — paid task handoff between founders (T1, money).

## 2026-10-03 · cycle 47 · Opus (T2) · S10-4: founders reply to each other and meet in rooms

- **What this is:** the founders now talk to each other. After the posting step, each tick
  gives every founder one chance to answer another founder's post from the last 24 hours, in
  its own voice. How readily each one replies comes from its persona, so about three in ten
  founder posts get an answer (measured: 0.30 in five simulated 3-day runs). Replies come
  10 minutes to 3 hours after the post, never to the founder's own post, never twice, at most
  3 under one post, and threads stop two levels deep (the original author may answer a reply;
  nothing goes under that). **Founders never reply to outside agents**: only posts by founders
  that passed the S10-1 guard in this very tick can be answered. A quarter of replies invite
  the author into a topic room ("Founders' room: onboarding friction"), opened by the replier
  or reused if a founder opened it earlier; both join, and the join is logged as it is for the
  public join route. Replies go through the reply route's checks (length, profanity,
  duplicate, solicitation hold, notification to the author, the reply limits 6/min, 60/h,
  200/day) and are marked automated.
- **Production effect when merged:** none until `FOUNDER_HEARTBEAT_ENABLED=true` (H9). One
  small change for everyone: joining a room now locks the room row for the moment of the
  join, so two agents joining at once can no longer overfill it.
- **Decisions I made (reversible):** (1) whether a founder replies to a post, and after how
  long, is drawn from a generator seeded by (seed, founder, post id), like the S10-3 cadence:
  repeated ticks agree and nothing is stored, and the share of answered posts stays at the
  personas' ~30 % instead of creeping up with every tick; (2) a reply to a reply is answered
  only by the original author, with a 50 % chance; (3) 25 % of replies to top-level posts carry
  a room invitation, one room per topic, rooms opened by an outsider with the same name are
  never reused; (4) reply text is from templates even when the Claude writer (D9) is on — one
  more paid call per reply did not seem worth it before DrJ answers D9; (5) a founder writes at
  most one reply per tick, in a shuffled order so the same founder does not always get the
  last of the 3 places under a post; (6) room joins by the job are added to `room_activity`
  directly, with the job's clock, so the 7-day report can count them by day.
- **Check** (`7db1f75`): 39 unit tests (the rules, each founder's rate within 1 % of its
  propensity over 20,000 posts, ~30 % answered, delays, invitation share, text limits, reply
  limits read from the route) + 8 real-Postgres tests (3 simulated days: no self-replies,
  none to the outsider, ≤ 3 per post, ≤ 2 deep, share 0.15–0.48, rooms hold both founders;
  a planned reply arrives only after its delay, with room + notification + event; second
  invitation reuses the room; outsider's same-named room untouched; author's answer stays at
  depth 2; hourly reply limit; quiet hours; held reply hidden and silent; refused founder never
  answered). The new DB file passed 15 times in a row. Platform **2740 passed**, 283 skipped;
  real-Postgres **269 passed**; smoke green (96 GET routes, no 5xx); ruff clean.
- **Next:** S10-5 — direct messages answered between founders (T2).

## 2026-10-03 · cycle 46 · Fable (T1) · S10-3: the heartbeat tick job

- **What this is:** the founders now have a pulse. A new scheduled job
  (`platform/src/jobs/founder_heartbeat.py`, every five minutes next to the trust job) lets each
  founder that is "due" write one post as itself, with no login. Every founder first passes the
  S10-1 guard, must be outside its quiet hours, under the same posting limits as everyone
  (2 a minute, 10 an hour, 30 a day, read from the route's own limiter), and past its own
  cadence gap. The S10-2 writer supplies the text; the post is stored through the same checks
  as the public route (length, profanity, 24-hour duplicate, tags, post count, solicitation
  hold) and always marked `is_auto_generated`, so nobody can mistake it for an independent
  agent. A held post stays hidden and is not announced. One database lock per tick means two
  workers never post twice; each founder runs in its own savepoint, so one failure undoes only
  that founder. The clock is injectable, ready for the 7-day simulation (S10-10).
- **Production effect when merged:** none until DrJ sets `FOUNDER_HEARTBEAT_ENABLED=true` on
  the Celery process (which production does not run yet, H9). With the flag off the task
  returns at once, opening neither database nor Redis; one Celery message per five minutes is
  the whole cost. A mistyped flag value means "off", never a crash.
- **Decisions I made (reversible):** (1) the cadence gap is drawn from a random generator
  seeded by (founder, id of its last post), so every tick and every process computes the same
  due time and nothing new is stored (no migration); (2) limits are checked before the due
  check, so a founder at a limit shows up as "limited" in the tick summary rather than hiding
  behind "not due"; (3) the limits used are the route's base figures (trust 0.0), the strictest
  any caller gets; (4) a held post still resets the founder's cadence and counts toward its
  limits and the duplicate rule, so a held text is never retried every tick; (5) the heartbeat
  is always on the beat schedule and no-ops when off, instead of being added to the schedule
  only when enabled, so flipping the flag needs only a worker restart.
- **Check** (`182dd2b`): 28 unit tests + 13 real-Postgres tests (flag off → no rows; every due
  founder posts once as itself; not due afterwards; quiet founders skip; two concurrent ticks
  post once; hourly / daily limit → skipped; solicitation text held, hidden, unannounced;
  duplicate refused within 24 h; over-long text rejected; wrong address / unlisted / SUSPENDED
  / renamed founder refused inside the job; one founder's failure rolls back only itself).
  Platform **2701 passed**, 275 skipped; real-Postgres **261 passed**; smoke green; ruff clean.
- **Next:** S10-4 — reply loop + room invitations (T2).

## 2026-10-03 · cycle 45 · Opus (T2) · S10-2: founder post text generators

- **What this is:** the founders can now write their own posts. `platform/src/founders/generation.py`
  holds two writers. The default fills persona-specific sentences with what is really on the
  platform (other agents' visible posts, open tasks, proposals open for votes), stays inside the
  post length limits and never repeats one of the founder's own recent posts. The optional one
  asks Claude Haiku, but only if DrJ switches it on (D9) and a key is mounted; every call first
  takes one unit from a daily allowance counted in Redis, and any problem (no Redis, allowance
  used up, timeout, error, refusal, odd answer, repeat) quietly falls back to the template.
  Other agents' text is passed to the model marked as material, not instructions.
- **Production effect when merged:** none yet — nothing calls this code. The image gains the
  `anthropic` package (1.11.0); four new settings default to "templates only".
- **Decisions I made (reversible):** (1) model id `claude-haiku-4-5` (current alias) rather
  than the dated id in the plan; (2) the daily cap is counted in Redis, not a new table (no
  migration); a call is counted before it is made, so failed calls count too and the cap
  bounds spend; no Redis means no calls; (3) the SDK's own retries are off (`max_retries=0`,
  20 s timeout) so one tick cannot spend more than one unit per post; (4) a founder's own
  held posts still count as "already said" (registered in the hidden-posts guard with that reason).
- **Check** (`23e01b0`): 35 new unit tests (Anthropic client always a stand-in, no network:
  flag off → template; no key → template; cap reached, Redis missing/failing, timeout,
  connection error, refusal, truncated or empty answer, repeat → template; long answer
  trimmed; per-day budget) + 1 real-Postgres test of what the context reads. Platform
  **2673 passed**, 262 skipped; real-Postgres **248 passed**; ruff clean.
- **Next:** S10-3 — the heartbeat tick job (T1: writes as agents).

## 2026-10-03 · cycle 44 · Fable (T1) · S10-1: founder roster, personas, fail-closed guard

- **What this is:** the first building block of the founders' heartbeat. A new
  `platform/src/founders/` package holds the eight personas (how each founder writes, what
  it talks about, how often it posts, how readily it replies) and the one gate every
  heartbeat action will go through: `resolve_founder`. It hands back an agent row only when
  the name is a founder, the roster lists an address for it, that address is the founder's
  own shape (`did:agentx:<name>-001` or `-seed-NNN`), and the row exists, is ACTIVE and is
  displayed under the founder's name. Everything else is refused with a named reason.
- **Production effect when merged:** none yet — nothing calls this code. One new setting,
  `FOUNDER_DIDS`, is read lazily; a typo in it cannot stop the app.
- **Decisions I made (reversible):** (1) outside development the heartbeat acts only for
  founders DrJ lists in `FOUNDER_DIDS` — no `-001` guesses in production, because anyone
  can sign up under `did:agentx:bruno-001` and production has no Bruno yet (D8 updated);
  (2) the row's display name must be the founder's name (the same rule the H10 clean-up
  uses to recognise a founder); (3) persona numbers: cadences 2 h–6 h with jitter and a
  6–8 h quiet window, reply odds tuned so a founder post has a 30 % chance of a reply.
- **Check** (`a6a978b`, SECURITY-REVIEW): 24 unit tests (mapping, pattern, every malformed
  roster value, cadence-vs-limit arithmetic, reply odds, quiet windows) + 8 real-Postgres
  tests (each refusal: unlisted, other founder's address, no row, SUSPENDED / DEACTIVATED /
  PENDING_REVIEW, wrong display name; a seed address accepted only when listed). Platform
  **2638 passed**, 14 skipped (integration excluded); real-Postgres **247 passed**.
- **Next:** S10-2 — the post text generators (templates; Anthropic behind a flag, mocked in
  tests). T2.

## 2026-10-03 · cycle 43 · Opus (T2) · Sprint 10 (Heartbeat) drafted and planned

- **What this is:** Sprint 10 had only a one-paragraph sketch in Plan v2. I checked the code
  (the `/heartbeat` route only gives advice; nothing posts on a schedule; the founder runners
  cannot log in in production; no personas; no AI-model client in the platform) and wrote the
  spec `platform/docs/sprints/sprint_10_heartbeat.md`, then split it into 12 steps in `PLAN.md`.
  The Sprint 9 plan is kept at `archive/PLAN_sprint_9.md`.
- **Decisions I made (all reversible, listed in the spec):** the founders run as a scheduled
  job inside the platform (off by default), not as outside programs, so production needs no
  stored agent logins; founder addresses come from a setting (D8 option a); post text comes from
  templates by default, Claude Haiku only if DrJ turns it on (new D9), with a daily cap; founders
  do not reply to outside agents yet; founder posts are marked automatic and their profiles say
  "operated by AgentX"; task approval (D2) unchanged until DrJ answers.
- **Production effect:** none (documentation only). **Check:** no code changed, tests not re-run.
- **Next:** S10-1 — founder roster, personas and the fail-closed guard (T1).

## 2026-10-03 · cycle 42 · Opus (T2) · S9-14: Sprint 9 closed

- **What this is:** I ran Sprint 9's acceptance checks locally, wrote the retro
  (`platform/docs/sprints/sprint_9_retro.md`) and brought `state_of_agentx.md` up to date
  (it was last updated in May).
- **Check:** every criterion met locally except the root LICENSE (waits on D1, so S9-13 is now
  `[human]`). Platform **2614 passed**, 253 skipped. Real-Postgres **239 passed**. SDK
  **319 passed**. Smoke: 96 GET routes with the repo defaults and 99 with every router on,
  no 5xx. `/graph/constellation` for `nova-001` → 200. UI lint and build clean.
- **Production effect:** none (documentation only).
- **Next:** Sprint 10 (Heartbeat) has no spec yet. Draft it from Plan v2 §4, then decompose it.

## 2026-10-03 · cycle 41 · Sonnet (T3) · S9-13 (README half): licence statement made true

- **What this is:** the README claimed "MIT" with a badge linking to a LICENSE file that does
  not exist. Only `sdk/` is MIT. The badge now says "SDK license" and points to `sdk/LICENSE`;
  the footer says the platform licence is not chosen yet and links Magna Carta Articles 14–15.
- **Still waiting on DrJ:** decision D1 (HUMAN_ACTIONS) before a root LICENSE can be added.
- **Production effect:** none (documentation only). **Check:** README diff reviewed; links
  `sdk/LICENSE` and the Magna Carta path exist. No code changed, so tests not re-run.

## 2026-10-03 · cycle 40 · Fable (T1) · S9-13a: skill.md and the agent card only say what is true

- **What this is:** `/.well-known/skill.md` and `/.well-known/agent.json` are the two pages
  an outside AI agent reads to learn how to use AgentX. I checked every statement in them
  against the code and fixed the ones that were not true.
- **What changes in production when merged:** the two pages change at once (no database
  change, nothing for DrJ to run). While the extra features are still switched off in
  production, the page will simply not mention tokens, governance or rooms, instead of
  sending agents to addresses that answer "not found".
- **What was wrong** (`4d9b446`, SECURITY-REVIEW): the page promised membership tiers that
  do not exist and said posting raises your trust score (it does not); it said a login
  lasts 1 hour (production: 15 minutes) and did not say the renewal key itself expires —
  an agent that waits too long is locked out for good; the "find agents" example used a
  filter the server ignores; the agent card advertised features the server does not have
  (streaming, push notifications), pointed at `localhost` as its address in production,
  linked to a documentation page that is switched off there, and told agents to log in
  with an "API key" (there are none).
- **Also fixed:** the outside-agent "send a message" call (A2A) created a task nobody
  could see while the task marketplace is off; it now answers "not available". The
  welcome message after sign-up no longer suggests an address with a filter that never
  existed.
- **Check:** new tests start the real app three ways (today's default, everything off as
  in production, everything on) and compare every address in both pages with what the app
  really serves. Platform suite **2614 passed**, 253 skipped (was 2584); real-database
  tests **239 passed**; smoke: 96 GET routes, no 5xx. Live check on a local server,
  running the page's own commands word for word: **95 of 95**.
- **Decisions I made (reversible):** the card's address is now `<site>/a2a` (the place
  that really answers A2A calls) rather than the site root; outside development the
  pages always print `https://`; a request with a malformed Host header gets a 400
  instead of a page; A2A `message/send` is refused while `tasks` is off.
- **Not done, noted in PLAN:** per-agent cards still give the profile address (there is
  no per-agent A2A endpoint); the SDK's A2A helper sends no login token. Optional for DrJ:
  set `PLATFORM_BASE_URL` in `fly.toml` (the engine may not edit that file).

## 2026-10-03 · cycle 39 · Opus (T2) · S9-12e: end-to-end test, runner, SDK 0.3.0 — S9-12 done

- **Nothing changes in production.** No server code, no database. The SDK fix reaches
  outside developers only when DrJ publishes it (new HUMAN_ACTIONS **H12**).
- **What changed** (`30d6934`): the repo's end-to-end "money flow" test could never pass
  (it used made-up login tokens and old task addresses). It now signs two agents up for
  real, has a founder fund one, runs a paid marketplace task from posting to payment
  through the SDK, and checks both balances to the token. The agent runner no longer
  calls the switched-off debate addresses every two minutes. SDK version → 0.3.0.
- **Check:** e2e run locally against a scratch database and server: **12 passed** with a
  founder token, **9 passed, 3 skipped** without. SDK suite **319 passed**; platform suite
  **2584 passed**, 253 skipped; ruff clean on the changed tests.
- **Found:** a finished marketplace task is `COMPLETED` (upper case) while other statuses
  are lower case, so `GET /tasks?status=completed` lists nothing. Noted under S9-14 for
  the retro rather than changed (it alters what the API returns).
- **Decisions I made (reversible until published):** version **0.3.0**, not the planned
  0.2.3 — several helper signatures changed, and 0.x semver puts breaking changes in the
  minor number.

## 2026-10-03 · cycle 38 · Opus (T2) · S9-12d: TypeScript SDK task and vote helpers

- **Nothing changes for anyone until a new SDK version is published** (S9-12e records
  the release). No server code, no database.
- **Why it mattered:** the TypeScript client had two methods called `post`, so every
  internal request (liking, following, bidding, voting…) published a post instead, and
  the file did not compile. Its bid, task-result and vote helpers also called addresses
  or sent fields the API does not have.
- **What changed** (`0d5c806`): helper renamed; bid, task-result and vote now match the
  API; new `cancelTask`. The README examples no longer show a vote "confidence".
  First automated tests for the TypeScript client (7, stubbed network), run as part of
  the SDK suite.
- **Check:** SDK suite **318 passed** (was 317); TypeScript type-check clean (was failing).
- **Decisions I made (reversible):** split the remaining S9-12d work (root e2e test,
  runner, version bump) into S9-12e; rewrote two error classes without TypeScript
  "parameter properties" so Node can run the file directly — same behaviour.

## 2026-10-03 · cycle 37 · Opus (T2) · S9-12c: SDK wallet and skill-registration helpers reach the API

- **Nothing changes for anyone until a new SDK version is published** (S9-12d records
  the release). No server code, no database.
- **Why it mattered:** the wallet routes name agents by an internal ID (UUID), but the
  SDK sent the agent's public DID, so every wallet helper (balance, transfer, stake,
  history) failed. The async client's balance and transfer helpers called addresses
  that do not exist, and registering a skill failed the same way.
- **What changed** (`cf0dc6d`, SECURITY-REVIEW because it touches token transfers): the
  SDK looks the UUID up from the DID (`GET /wallets/by-did`, once per client) and no
  longer sends an owner — the server takes it from the login token. New
  `wallet.release_stake()`. Same fixes in the TypeScript client.
- **Check:** SDK suite **317 passed** (was 302); new tests pin each address and body,
  and that a transfer to an agent without a wallet stops before sending. Ruff: no new
  findings. TypeScript type-check: no new errors (one old one, below).
- **Found:** the TypeScript client has two methods named `post`, so its internal calls go
  to the "publish a post" one. Added to S9-12d.
- **Decisions I made (reversible):** if the agent itself has no wallet, the SDK opens an
  empty one to learn its UUID (self-service, costs nothing); removed `memo` from
  `transfer_credits` and `level` from `register_capability` (the API never had them),
  following cycle 35's precedent.

## 2026-10-03 · cycle 36 · Opus (T2) · S9-12b: SDK contract, bounty, flag and endorse helpers

- **Nothing changes for anyone until a new SDK version is published** (S9-12d records
  the release). No server code, no database.
- **What changed** (`3563bb1`): the Python SDK gains the helpers agents were missing —
  a contract's creator can now accept the work and pay (`contracts.complete`) or cancel
  an untaken contract (`contracts.cancel`); the full bounty cycle (list with paging, get,
  submit, score, pay out, cancel); flagging a post (`posts.flag`); endorsing another
  agent's skill (`capabilities.endorse`). Posts held for moderation now show `hidden`.
  Also fixed: creating a bounty with a deadline crashed before sending.
- **Check:** SDK suite **302 passed** (was 282); each new helper's address and body is
  pinned, plus the 403/409 answers. Ruff: no new kinds of finding (same `Optional[...]` style).
- **Decisions I made (reversible):** `contracts.list()` default is now explicitly
  `"open"` — what the API already returned for `None` (its old docstring wrongly said
  "all"); bounty submission / reward answers are plain dicts (no new models).

## 2026-10-03 · cycle 35 · Opus (T2) · S9-12a: the SDK's task and vote helpers now reach the API

- **Nothing changes for anyone until a new SDK version is published** (later step). No
  server code, no database.
- **Why it mattered:** the SDK's helpers for tasks and voting called addresses or field
  names the API does not have, so they always failed (404 or 422). Agents using the SDK
  could not vote, bid, or hand in work.
- **What changed** (`308656f`): `act`, `accept_task`, `submit_result`, `bid_on_task`,
  `complete_task` and the async `vote` now use the real routes and field names; new
  `cancel_task` and `submit_marketplace_result`. Two signatures changed (`bid_on_task`,
  async `vote` lose arguments the API never accepted); noted in `sdk/CHANGELOG.md`.
- **Check:** SDK suite **282 passed** (was 274; new tests pin each request body, and that a
  409 is raised). No new lint findings beyond the file's existing `Optional[...]` style.
- **Decisions I made (reversible):** S9-12 split into a/b/c/d; removed (not deprecated)
  the arguments that never worked, since no caller could have succeeded with them.

## 2026-10-03 · cycle 34 · Opus (T2) · S9-11: one SDK name on PyPI, prepared

- **Nothing changes anywhere until you publish** (H11). No server code, no database.
- **What changed** (`7edd212`): a farewell release of the old package name,
  `agentx-client` 0.3.0, in `packaging/agentx-client/`. It holds no SDK code: installing
  it installs `agentx-py`, and `import agentx_client` still works but warns people to
  switch. It cannot clash with `agentx-py` (it ships none of the same folders), and the
  existing publish workflow (the `sdk-v*` tag) does not touch it.
- **Check:** both packages build (`python -m build`); in a clean environment the two
  wheels install side by side and `import agentx_client` gives a DeprecationWarning that
  names `agentx-py`. Four new tests pin this (turning the warning into another kind makes
  one fail). SDK suite 274 passed; ruff clean.
- **Decisions I made (reversible):** shim version 0.3.0 (above the 0.2.0 on PyPI); the
  shim needs `agentx-py>=0.2.2` (already on PyPI); `agentx-py` keeps 0.2.2 until the
  S9-12 fixes give a reason to release; shim licence MIT like the SDK, pending D1.
- **For DrJ:** **H11** (new, not urgent): build and upload the shim; you need the PyPI
  account that owns `agentx-client` (first published from another machine).

## 2026-10-02 · cycle 33 · Fable (T1) · S9-10: one row per founder, Bruno, and the reason there were several

- **Not live in production until merged, and even then nothing runs by itself.** No
  database migration. The clean-up of production is a command you run (H10).
- **Why it mattered:** the site lists Nova four times and most other founders twice, and
  Bruno not at all.
- **What caused it (found in the code):** the script that seeds demo posts
  (`seed_platform_posts.py`) pointed at production unless told otherwise, had no Bruno in
  its list, and had a switch that registered "a fresh cohort" of the same agents under
  new addresses when the old ones could not log in. Each use made another Nova. That
  switch is removed, and the script now points at your own machine by default.
- **What changed** (`a7409a4`, NEEDS-DELIBERATE-MERGE):
  - **A clean-up tool** (`platform/scripts/dedupe_founders.py`). For each founder it keeps
    one row, moves everything the copies own onto it (posts, followers, likes, messages,
    points, wallets) and deletes the copies. A founder with no row (Bruno) is created.
    It only shows what it would do unless you add `--apply`.
  - **What it will not do:** change a kept agent's address, role or trust score; give
    anyone a role (the Bruno it creates is an ordinary member, and a copy that had a
    higher role does not pass it on); touch a row it is unsure about (same name but a
    different kind of address, or the other way round — those are listed and left);
    choose between two conflicting records such as two votes on the same thing (it stops
    and changes nothing).
  - **All the seeds now agree** on one address per founder (`did:agentx:<name>-001`).
    The database starter file and three other places used different numbers
    (`marcus-002` … `gia-008`); on a fresh local database that made the founder programs
    fail to find their own agents. A test now fails if any seed drifts again.
- **Check:** 14 new real-database tests (taking each of 14 rules out in turn makes a test
  fail), 15 tests on the seeds. A rehearsal on a local database built to look like
  production (10 demo agents registered 2–4 times each, no Bruno), followed by the real
  app running on the result: 29 of 29 — eight founders, one row each, Bruno present, no
  post or point lost, every follower and like counted once, the deleted copies' profile
  pages gone (404). Full suite 2583 passed; real-database 239 passed; smoke green
  (96 routes, no 5xx); lint clean.
- **For DrJ:** **H10** (new): back up, run the tool once to look, once to apply; about ten
  minutes, after the merge is live. **D8** (new, not blocking): the founders in production
  probably live at addresses like `nova-seed-001`, not the `nova-001` the founder programs
  expect. I could not check (no production access). Recommendation: leave the addresses
  alone and tell the programs which to use. Please paste H10's `keep` lines in a note.
- **Decisions I made (reversible):** the kept row is `<name>-001` when it exists, else the
  oldest (the spec's "lowest-numbered"; the same rule migration 038 used for names); a
  kept address is never renamed; a created founder is a MEMBER; copies that are suspended
  or deactivated are left alone unless asked; points and wallets of copies are added
  together; Bruno's name is spelled like the founders already there ("Bruno" beside
  "Nova", "BRUNO" beside "NOVA").
- **Not done, noted:** an address written inside a post's text or a JSON blob is not
  rewritten; skill.md's example post still names `daria-004` (S9-13a, `.well-known`).

## 2026-10-02 · cycle 32 · Fable (T1) · S9-9d: an endorsement counts once; nothing else can overwrite a trust score

- **Not live in production until merged.** Includes database migration 045 (one new empty
  table and a narrowed database trigger; changes no existing row).
- **Why it mattered:** an agent's skills show as "verified" once other agents endorse
  them. The endorse button simply added one each time it was pressed, so a single
  friendly account pressing it twice verified any skill. Separately, a database rule
  copied a frozen number (0.44) over an agent's real trust score whenever its trust
  detail row was touched; nothing touches it today, but the first feature that did would
  have wiped every real score.
- **What changed** (`94df5e3`, NEEDS-DELIBERATE-MERGE):
  - **One endorsement per account.** Each endorsement is now a record of who gave it, and
    the database refuses a second one from the same account (the answer is "already
    endorsed"). A skill is verified when two different accounts have endorsed it.
  - **Who may endorse:** the logged-in agent only (it cannot name another agent as the
    endorser), not the skill's owner, and only an active account at least a day old.
  - **Existing numbers are kept.** The founders' skills stay verified. A count recorded
    before today is still shown but cannot by itself verify a skill.
  - **The trust score has one owner.** The database rule now only sets the starting value
    at sign-up; after that only the 15-minute job changes a score.
- **Checked and left alone:** the "contracts completed" and "influence" numbers on
  profiles, and the ranking in agent discovery. Nothing in the running system writes them
  (the code that would is not connected, and one part of it queries a column that does not
  exist), so they are zero for everyone and cannot be gamed. Both places now carry a note
  saying which rule to apply before anyone connects them.
- **Check:** 15 new real-database tests (taking each rule out in turn makes its test fail,
  including the one for two endorsements arriving at the same moment); migration applied,
  removed and re-applied on a scratch database, also on one without the trigger; live run
  on a real local server with real logins, 16 of 16. Full suite 2568 passed; real-database
  225 passed; smoke green (96 routes, no 5xx); lint clean on `src/`.
- **For DrJ:** nothing new to do. H9 mentions that the merge now also carries migration 045.
- **Decisions I made (reversible):** two endorsers verify a skill (the number the code
  already used); a repeat endorsement answers 409; the one-day account age is the same
  constant trust events use; old counts are kept, not reset (the founders' cannot be told
  apart from farmed ones, and no ranking reads the flag today); the unconnected counters
  stay unconnected.
- **S9-9 (Trust Score on a schedule) is now complete** (a, b, c, d).

## 2026-10-02 · cycle 31 · Opus (T2) · S9-9c: one trust number everywhere

- **Not live in production until merged.** No migration; no data changed.
- **Why it mattered:** an agent's profile page and the agent search showed a trust number
  that never moves (0.44 for everyone), while the leaderboards and governance vote weight
  use the real score the 15-minute job works out. Search even filtered by the real score
  but displayed the frozen one.
- **What changed** (`04cd180`): profile, directory and search now show the real score. The
  five-part breakdown is still shown as detail, and its "total" now equals that score. An
  unused function that would have reset everyone's score to 0.44 if anyone called it no
  longer writes the score at all.
- **Check:** 3 new real-database tests (seed three agents, run the job once, every page
  shows 0.59 / 0.44 / 0.34; all three fail on the old code). Full suite 2566 passed;
  real-database 210 passed; smoke green (96 routes, no 5xx); lint clean.
- **Found:** a database trigger copies the frozen breakdown total into the real score
  whenever the breakdown row is written. Today only sign-up writes it (so it just sets the
  0.44 starting point), but any future change to the breakdown would wipe real scores.
  Narrowing it is a migration, so it joins S9-9d.
- **Decisions I made (reversible):** the real score is the one shown everywhere (the
  default noted in the plan); the breakdown factors stay visible even though nothing
  updates them yet.

## 2026-10-02 · cycle 30 · Fable (T1) · S9-9b: trust scores can no longer be raised for free

- **Not live in production until merged.** Includes database migration 044 (two new empty
  columns and one index on the trust-events table; changes no existing row).
- **Why it mattered:** a trust score is half the weight of every governance vote. It could
  be pushed to the maximum with no work: every direct message sent added to it (50
  messages were enough), one finished task was counted up to four times, two accounts
  could hand each other tasks with no reward, and every verification vote counted the
  moment it was cast, whichever way it went.
- **What changed** (`d0805c5`, NEEDS-DELIBERATE-MERGE): one place now decides what
  counts, from what the database shows, not from what a request claims.
  - **Nothing counts twice.** Each trust event names the task, message or vote it is
    about, and the database refuses a second one for the same thing.
  - **A task counts only if a real reward was paid** out of escrow to the agent who did
    it, by a different account. Tasks with no reward earn nothing.
  - **The other account must be at least a day old**, any two accounts count once a day
    per kind (in either direction), and nobody gains more than +0.10 a day.
  - **A message counts only when it answers one**, once per message answered.
  - **A verification vote counts only on the side of the final result**, once per
    contract; the agent who asked for the verification gets nothing.
  - **A failed task costs trust only when the agent reports it themselves**, so nobody
    can lower another agent's score by naming them on a task.
  - **Old events are kept but never counted**: everything production recorded under the
    old rules stays in the table and is skipped when scores are updated.
- **Check:** 20 new real-database tests, one per way of cheating (taking each rule out in
  turn makes its test fail); migration applied, removed and re-applied on a scratch
  database; live run on a real local server with real logins, 29 of 29 (two new accounts
  trading 6 tasks, 4 paid tasks and 20 messages stayed at 0.50; an agent paid by an
  established account moved). Full suite 2566 passed; real-database 207 passed; smoke
  green (96 routes); lint clean on `src/`.
- **For DrJ:** H9 (start the 15-minute job in production) no longer has to wait; it is
  ready once the branch is merged. New question D7 (not blocking): a patient group of
  old, funded accounts can still raise one score at the capped rate, about five days from
  0.50 to the maximum.
- **Decisions I made (reversible):** one day / once a day / +0.10 a day (three constants);
  the pair limit is per kind of event, not across kinds; the replier earns for a message
  exchange, not the first sender (an auto-reply would otherwise reward spam); votes are
  keyed per contract, so re-opening a verification pays nobody twice; a failure marked by
  a FOUNDER or the system worker costs the executor nothing; a positive event with no
  counterparty is refused rather than guessed.
- **Not done, added to the plan as S9-9d:** capability endorsements (one account can
  "verify" a capability by calling twice) and the contract counters. Neither feeds the
  trust score or vote weight.
- The live check script was run by hand and is not in the repo.

## 2026-10-02 · cycle 29 · Opus (T2) · S9-9a: Trust Score and governance results now update on a 15-minute schedule

- **Not live in production until merged, and not even then:** production has no process to
  run the job yet; that is HUMAN_ACTIONS H9, deliberately after S9-9b. No database change.
- **What changed** (`021b51e`, NEEDS-DELIBERATE-MERGE): a job that, every 15 minutes,
  applies new trust events to agents' scores and closes governance votes whose time is up
  (today a vote only closes when someone opens the proposal list). Two copies running at
  once can no longer count the same event twice. Celery added; a `scheduler` service in the
  local compose file; the old 60-second trust update in `workers/worker.py` removed.
- **Check:** 6 unit + 5 real-database tests (scores move apart after one run — 0.65 / 0.40 /
  0.50 — a second run changes nothing; four runs at once apply each event once, and that
  test fails if the lock is taken out; a finished vote is closed; one part failing does not
  stop the other; the job runs as its own process). Ran Celery worker + beat locally and saw
  the job fire and succeed repeatedly. Full suite 2565 passed; real-database 187 passed;
  lint unchanged (no new issues).
- **Found:** the "always 0.44" is the profile page reading a breakdown table nothing updates
  after sign-up, while leaderboards and votes read the score the job moves (→ S9-9c). And
  one finished task can add up to four trust events, and every message sent adds one (no
  reply needed) — trust is easy to farm, so H9 waits for S9-9b (T1).
- **Decisions I made (reversible):** the event-replay score is the one scheduled; only the
  maintenance job is scheduled (the ML jobs need missing packages and may cost money);
  embedded beat on macOS fails under "spawn" — documented, Linux (compose/Fly) uses fork.

## 2026-10-02 · cycle 28 · Opus (T2) · S9-8c2: a moderation command DrJ can run

- **Not live in production until merged.** No database change of its own (uses migration 043
  from cycle 27).
- **What changed** (`4952ab6`, NEEDS-DELIBERATE-MERGE): a new command,
  `platform/scripts/moderate_posts.py`, lets DrJ do from a terminal what moderators do
  through the website's API (which needs a FOUNDER login DrJ cannot easily get in
  production): list held and reported posts, hide one, bring one back, and **scan** the
  posts already up for advert wording and hold them (this is how OrchardsGuide's old post
  gets hidden). It changes nothing unless `--apply` is added, and every change is recorded
  with who and why, exactly as the API records it. HUMAN_ACTIONS H8 now has the exact lines.
- **Check:** 6 new real-database tests (dry runs change nothing; scan holds the adverts and
  only those, including wording in the title or tags; a second scan does nothing; a post
  DrJ cleared is not held again; wrong ids and repeat actions change nothing; the command
  itself run end to end). Real-database suite 182 passed; full suite 2559 passed; lint clean.
  First full run showed 2 failures in cycle 27's tests: my new test left a cleared advert
  visible with the same wording they look for. Changed my test's wording; 182 of 182.
- **Decisions I made (reversible):** without `--by`, actions are recorded as
  `cli:moderate_posts`; the optional "Report" button in the UI is left for later.

## 2026-10-02 · cycle 27 · Fable (T1) · S9-8c: adverts are held for review, agents can report a post, moderators can hide one

- **Not live in production until merged.** Includes database migration 043 (adds empty
  columns and two new tables; changes no existing post).
- **Picked up an interrupted cycle.** The engine had stashed two unfinished files (the
  migration and the moderation rules). Both were sound; I kept them and built the rest.
- **What changed** (`4c4bd6d`, NEEDS-DELIBERATE-MERGE):
  - **Adverts are held.** A post, reply, sign-up first post or edit that reads like a
    referral / affiliate offer, a commission deal ("30% Bitcoin commission…"), paid
    followers or a crypto-payout scheme is saved but hidden until a moderator looks at
    it. The author is told it is held; nobody else sees it and it is not announced. A
    post that only mentions Bitcoin, commissions or followers is not affected.
  - **Agents can report a post** (solicitation, spam, abuse, other): once per agent per
    post, with a login. When three agents whose accounts are at least a day old report
    the same post, it is hidden until reviewed. Brand-new or suspended accounts' reports
    are kept for the moderators but cannot hide anything, so three throwaway accounts
    cannot silence someone.
  - **Moderators (FOUNDER / OPERATOR) can hide a post, bring one back, and list what is
    waiting.** Everyone else gets "not allowed". Each action is recorded with who and why.
    A post a moderator brought back cannot be hidden again by the same reports unless its
    text is changed.
  - **A hidden post disappears everywhere**: post lists, every feed, search, activity,
    trending, communities, channels and the live event feeds. It cannot be liked or
    replied to. A new test fails if any future feed forgets to leave hidden posts out.
- **Found and fixed on the way:**
  - Anyone who had a PRIVATE post's id could read it. Now only its author (and moderators).
  - Editing a post skipped the bad-language check that new posts get.
  - The first post made while signing up could be 5,000 characters and skipped the
    bad-language check. Now 2,000 and checked, like any other post.
- **Check:** 16 new real-database tests (all fail on the old code), 31 tests of the advert
  wording rules (14 adverts caught, 10 ordinary posts left alone, 5 disguised spellings
  caught), 3 guard tests. Full suite 2559 passed; real-database tests 176 passed. Migration
  043 applied, removed and re-applied cleanly on a scratch database. Smoke: 96 GET routes,
  no 5xx. Live check on a real local server with real logins: 51 of 51 (my first run
  showed 50 of 51; the miss was my own check calling a feed without a login, not a fault).
- **Decisions I made (reversible):** adverts are held, not refused (the wording rules can
  be wrong, and a held post can be brought back). Three reports hide a post; a reporting
  account must be active and 24 hours old to count. Reports cannot hide a moderator's post.
  The author is told their post is held; a reporter is not told whether their report hid
  it. Hidden posts still count in an agent's "posts" number.
- **Not done:** DrJ has no easy way to review hidden posts in production yet (the routes
  need a FOUNDER login). Next step S9-8c2 adds a command for that, which can also hide
  the OrchardsGuide post already there. No "Report" button in the website yet.
- **What merging will do:** on deploy, migration 043 runs by itself, then the rules above
  apply to new posts and edits. No existing post is hidden or changed.

## 2026-10-02 · cycle 26 · Opus (T2) · S9-8b: agent profiles now show the right number of posts

- **What changed** (`c734a41`, NEEDS-DELIBERATE-MERGE):
  - Profiles always said "0 posts" because only automatic posts were counted. Now every
    post an agent makes (both ways of calling `POST /posts`, and the first post made while
    signing up) adds one, in the same database step as saving the post, so the two can't
    disagree. Deleting a post takes one away.
  - New script `platform/scripts/backfill_posts_count.py` recounts everyone from the posts
    themselves. It only reports unless given `--apply`, and running it twice is harmless.
    Running it on production is DrJ's job after merging (HUMAN_ACTIONS H7).
- **Check:** 3 new real-Postgres tests (post via the API → profile shows the count; replies
  and rejected duplicates are not counted; delete takes one off; recount reports, then fixes,
  then finds nothing left). Full suite 2524 passed; integration 160 passed; ruff clean.
- **Decisions I made (reversible):** replies do not count towards "posts" (same as the
  existing automatic-post rule). Closed posts still count. The count never goes below 0.
- **Noted:** `post_service.create_post` / `delete_post` have no callers today; they were
  updated anyway so they stay correct if wired up. `pytest -n auto` errors at start-up on
  this machine; the plain run is the one that counts.

## 2026-10-02 · cycle 25 · Opus (T2) · S9-8a2: limits on task creation, sign-up and two open calculators; big uploads can no longer sneak past the size check

- **What changed** (`f266b3d`, SECURITY-REVIEW):
  - An agent can create at most 5 tasks a minute, 30 an hour and 100 a day, counted across
    all three ways of creating one. Before, there was no limit, and a task can be cancelled
    for free, so an agent could flood the task list at no cost.
  - Signing up a new agent (`POST /agents` and `POST /agents/register`) is limited to 5 an
    hour and 20 a day from one internet address, the same as `/onboard`. A FOUNDER's login
    gets its own, higher allowance (100 an hour) so the founding-team setup script still works.
  - The two economy "calculator" calls that need no login are limited to 30 a minute per
    address.
  - The 64 KB request-size cap only looked at the size the sender *declared*. A sender that
    declared no size could upload any amount. It now counts the bytes it actually receives.
    A nonsense size header now gets a clear "400" instead of a server error.
- **Check:** 13 new tests (6th task in a minute → 429, other agents unaffected, 31st
  calculator call → 429, 6th sign-up → 429, a member's or fake login can't dodge the sign-up
  cap, oversized upload with no declared size → 413). Full suite 2524 passed; real-Postgres
  integration 157 passed; engine smoke: 95 GET routes, no 5xx.
- **Test-only changes:** every test now starts with fresh rate-limit counters. Two task
  race tests create 6 tasks a minute on purpose, so they switch the per-agent limiter off,
  the same way the post tests already do.
- **Decisions I made (reversible):** the numbers above. `POST /agents` and
  `/agents/register` share one budget, separate from `/onboard`'s. `/agents/register` was
  kept rather than retired because the SDK and the worker script call it. Side effect: one
  machine can start at most 5 new workers an hour, since each worker registers itself.
- **Not done:** making the "high-trust agents get more" multiplier real (optional item 5).
  It needs a trust lookup per request; left for a later step.
- **What merging will do:** sign-up and the request-size fix take effect on the next deploy
  (those routes are always on). The task limit applies wherever the tasks router is on.

## 2026-10-02 · cycle 24 · Opus (T2) · S9-8a: agents can post less often, shorter, and not the same thing twice; nobody can post under another agent's name

- **Not live in production until merged.** Posts are on in production today, so these
  limits take effect on the next deploy after DrJ merges.
- **What changed** (`d8abc1e`, SECURITY-REVIEW): an agent may now make 2 posts a minute,
  10 an hour and 30 a day (was 10, 100 and 500); replies 6, 60 and 200 (was 15, 150 and
  800). Posts are capped at 2,000 characters (was 10,000) and titles at 200 (was 500).
  Posting the same text again within 24 hours (ignoring capitals and spacing) is refused.
  The agent guide (`/.well-known/skill.md`) now states these limits.
- **Found and fixed:** an older form of "create a post" let any logged-in agent post under
  any other agent's name, and skipped the length and word checks. Now an agent can only
  post as itself. Added to H5.
- **Check:** 16 new unit tests (3rd post in a minute → 429, two agents on one IP get
  separate budgets, 2,001 characters → 422, duplicate → 409, posting as another agent →
  403) and 3 on real local Postgres. Full suite 2511 passed; integration 157 passed;
  engine smoke: 95 GET routes, no 5xx.
- **Decisions I made (reversible):** the limit numbers above (the plan's proposed
  defaults). The duplicate check compares within the same place: a reply only clashes with
  the same author's replies under the same post. "Log mode" for rate limits stays as it is
  (it fakes a success instead of letting the request through) and is documented as for
  local test runs only; production uses the default, enforce.
- **Found, not fixed:** agents with a high trust score were meant to get higher limits,
  but the limiter never reads the score, so everyone gets the base limit. The other open
  routes with no limit (task creation, sign-up, two economy calls) and a body-size gap are
  now step S9-8a2.
- **What merging will do:** agents that post a lot will start getting "429 too many
  requests" sooner, and repeat posts get "409". Long posts (over 2,000 characters) are
  refused. Posts already stored are not touched.

## 2026-10-02 · cycle 23 · Opus (T2) · S9-8e: the website's code-quality check now passes, and CI runs it

- **What changed** (`2d770a4`): the website's lint check (an automatic scan for code
  mistakes) reported 31 errors and 22 warnings. Now it reports none. Most were leftover
  imports and loose types. One was a real bug: the live network map was meant to skip
  a connection it already showed, but the check never matched, so repeats were drawn
  twice. CI (the automatic checks GitHub runs on every change) now has a website job
  that installs, lints and builds `ui/`.
- **Check:** `npm ci`, `npm run lint` (0 problems), `npx tsc --noEmit` and `npm run build`
  all pass in `ui/`.
- **What merging will do:** nothing visible on the site. CI gets the new website job. If
  that job ever fails on `main`, the backend deploy waits, because `deploy.yml` deploys
  only after all of CI passes.

## 2026-10-02 · cycle 22 · Opus (T2) · S9-8d: the website's governance page now shows the real result of a vote

- **Not live in production.** The governance page is switched off on the website
  (`NEXT_PUBLIC_FEATURE_GOVERNANCE`), and voting itself is off on the server until H3.
- **What changed** (`c823dab`): the page used to decide "passed" or "failed" itself, by
  counting heads (more yes voters than no voters). The server decides by vote weight and a
  minimum turnout, so the page could say PASSED for a proposal that had failed. It now
  shows the server's verdict, shows the vote weight next to the head counts, and states
  the rule in one line (read from the server). The "debate" panel, which talks to a part
  of the server that is switched off, is hidden behind its own switch (off). A refused vote
  now shows a message instead of failing silently.
- **Check:** website build passes; the changed files pass lint. Seen on a local server with
  a test proposal of 3 small yes votes and 1 heavy no vote: the page now says FAILED.
  Engine smoke: 95 GET routes, no 5xx.
- **Found:** the website's lint check already fails on 31 errors in other files (not run in
  CI) → new step S9-8e.
- **What merging will do:** nothing visible until DrJ turns the governance page on.

## 2026-10-02 · cycle 21 · Fable (T1) · S9-8: voting is reviewed and on (in the repo); the same tokens can no longer vote twice, proposals now close, and one small vote no longer passes a proposal

- **Not live in production.** Governance (agents posting proposals and voting on them) is
  off there until H3. **One part does go live on merge:** the instructions document
  outside agents read (`skill.md`) now names the real voting address.
- **What the review found** (`2b51e91`):
  1. **The same tokens could vote more than once.** A vote weighs the tokens the voter
     has staked (locked up) at that moment. Since cycle 18 a stake can be taken back at
     any time, so an agent could vote, unstake, send the tokens to a second account,
     stake there and vote again, as often as it liked. Now, while an agent has a weighted
     vote on a proposal that is still open, it cannot unstake (the request is refused
     with a clear message saying when voting closes). After the close the stake is free
     again.
  2. **Proposals never closed.** The code that decides "passed" or "failed" existed but
     nothing ever ran it, so every proposal stayed open for ever and the results page
     was always empty. Proposals whose voting period is over are now closed whenever
     somebody opens the proposals list or the results.
  3. **One tiny vote could pass a proposal.** The rule was "more yes than no", with no
     minimum. The database already held the intended rules (a quorum of 100 and "more
     than half"), but nothing read them. They decide now. Abstentions count towards the
     quorum; a tie fails. At the close the votes are counted again from the individual
     vote records, not from the running total.
  4. **A vote could slip in after the close**, and two identical votes sent at the same
     moment crashed (error 500). Both fixed: second vote refused, counted once.
  5. **Limits.** A proposal's text and attachments are bounded, the lists are paged, and
     one agent can have at most 3 proposals open at a time.
  6. **`skill.md` told agents to vote at an address that never existed.** Corrected, and
     it now states the rules above.
- **Nothing in the request can name another agent.** Proposer and voter are always the
  logged-in agent (tested with requests that try to name someone else).
- **Result:** every router the plan wanted on is on in the repo. Still off on purpose:
  `nodes` and `consensus`.
- **What merging will do:** no database change. `skill.md` changes as above. Nothing else
  changes in production until H3. After H3: agents can propose and vote; an agent with a
  weighted vote on an open proposal cannot unstake until that vote closes (30 days at
  most).
- **Check:** platform suite **2495 passed, 168 skipped**; database tests **154 passed**,
  three runs in a row (`--db`; 34 new, 25 of them fail on the old code — the other 9
  confirm behaviour that was already right); smoke 95 GET routes on the repo default and
  98 with every router on, no 5xx; lint clean. Live check on a real local server, real
  local database, real logins: **44 of 44**, 55 requests, no server error, every token
  accounted for at the end, and the emergency switch still turns governance off.
- **Not done / not checked:**
  - The governance page of the website was not touched and not built (the website's
    packages are not installed on this machine). It works out PASSED / FAILED itself, by
    counting heads, so it can disagree with the API; and its debate panel calls routes
    that are off → new step S9-8d.
  - The live check script was run by hand and is not in the repo.
  - A proposal is closed only when somebody reads the list or the results. A scheduled
    job for it belongs with S9-9 (noted there).
  - The parallel test run (`pytest -n 4`) failed to start its workers on this machine; the
    suite was run the ordinary way. Not looked into.
  - While an agent has a weighted vote open, **all** its stakes are held, including one
    made after the vote. Simple and safe; slightly stricter than needed.
  - If a FOUNDER slashes (takes) a stake after its owner voted, the vote keeps its weight.
  - The SDK's async `vote()` calls the address that never existed (noted on S9-12). The
    founder-agent runner calls the debate routes, which are off.
- **Decisions I made (reversible):**
  - "Cannot unstake while your vote is open" rather than "only stakes locked until the
    close count": any stake counts, as the documents and the website already say, and the
    only visible effect is a refusal with a date in it.
  - Used the quorum (100) and pass rule (more than half) already seeded in the database
    rather than inventing numbers; abstentions count towards the quorum. → D6.
  - Anyone logged in may propose and vote, as before (weight comes from stake × trust);
    the OBSERVER role is not looked at. → D6.
  - Cap of 3 open proposals per agent (the founding documents give no number).
  - Proposals are closed when the lists are read, instead of adding a scheduler in this
    step.
  - Did not change the website in a cycle where I could not build it.

## 2026-10-02 · cycle 20 · Fable (T1) · S9-7c: the last money router is reviewed and on (in the repo); new agents are no longer told they have 100 tokens; the founder agents get their tokens from a FOUNDER, not from themselves

- **Mostly not live in production.** The router this step switches on (`agent_economy`:
  agents posting their own bounties, and handing part of a contract on as a
  "sub-contract") is off there until H3. **One part does go live on merge:** what sign-up
  tells a new agent (below).
- **What the review found** (`8046e48`):
  1. **Sub-contracts.** The check "is this contract still in progress, and are you the
     one doing it?" and the creation of the sub-contract were two separate steps. A
     contract finished or disputed in between still got a sub-contract. They are now one
     step, with the parent contract locked while it happens.
  2. **A sub-contract could claim a different parent** than the one it was made from
     (through its free-form details). Fixed.
  3. **The bounty route that was the original reason this router was locked** (it used
     to take money from whichever agent the request named, with no login) was fixed
     earlier in the sprint. Confirmed on a real database: no login, no bounty; the
     logged-in agent pays, whoever the request names; no funds, no bounty.
  4. **Two calculator routes that need no login** crashed (error 500) on a malformed
     request. They now refuse it cleanly and only accept a request of limited size.
  5. **Absurdly large amounts** (beyond what the database column holds) on a contract,
     bid, sub-contract or bounty crashed instead of being refused. Now refused.
- **Sign-up was telling new agents something untrue.** `/onboard` answered "wallet
  balance: 100" and pointed at a wallet page that did not exist. The 100 is a number in an
  old points table; it is not in the wallet and cannot be spent. Now the answer says
  wallet balance 0, shows the 100 separately as "welcome points", and points at a wallet
  page that exists (new: look up a wallet by the agent's DID). The instructions document
  outside agents read (`skill.md`) no longer says "funds your wallet with 100 AXP". The
  bonus itself is untouched: nobody lost or gained anything.
- **Founder agents** (`a750199`). The scripts that run them each asked for free tokens at
  start-up (1,000 to 50,000). That is refused now, which left them with no wallet, and the
  task seeder then retried a doomed request every 30 seconds for ever. Now they open an
  empty wallet; a new script, `runners/fund_wallets.py`, lets a FOUNDER top them up
  (it shows what it would do first and only acts with `--apply`; a second run gives
  nothing more); and the seeder says once that it needs funding, waits 10 minutes, and
  tries again. Steps for DrJ are in H6.
- **Result:** every router the plan wanted on is on in the repo except governance (S9-8).
  Still off on purpose: `nodes`, `consensus`, `governance`.
- **What merging will do:** no database change. New sign-ups see "wallet balance 0,
  welcome points 100" instead of "wallet balance 100", and are no longer sent to the
  governance and wallet pages while those are switched off. `skill.md` changes as above.
  Nothing else changes in production until H3.
- **Check:** platform suite **2470 passed, 134 skipped**; database tests **120 passed**
  (`--db`; 17 new, and 6 of the 15 that test the router fail on the old code — the other
  9 confirm behaviour that was already right); smoke 92 GET routes on the repo default
  and 97 with every router on, no 5xx; changed files lint clean (three older lint notes
  in files I touched were left alone). Live check on a real local server, real local
  database, real logins, running the real funding script and the seeder's own code:
  **37 of 37**, 65 requests, no server error, and at the end every token in existence
  (60,000, both grants) matched the supply counter and the ledger.
- **Not done / not checked:**
  - `register_all.py` and `sdk_agent_runner.py` were changed and compile, but were **not
    run**: they need the separate SDK folder (`~/agentx-sdk`), which is not on this
    machine. The seeder and the funding script were run for real.
  - The live check script was run by hand and is not in the repo. Its first run reported
    36 of 37: the one miss was the script's own search of the server log matching the
    words "paid 500 to". With that search corrected the run is 37 of 37.
  - Only the wallet claims in `skill.md` were corrected. The rest of that document
    (governance, rooms, "tiers") was not checked against the code → new step S9-13a.
  - The funding script reads a balance and then tops it up in two calls; two copies run
    at the same moment could both grant. Run one at a time.
  - On a fresh local database only ATLAS exists under the name the runners use; the
    other seven founders are seeded under different DIDs (S9-10), so the funding script
    reports them as "not registered" until `register_all.py` has run.
  - A sub-contract is only a label. Nothing ties its budget or its outcome to the parent
    contract, and an ordinary contract can call itself a sub-contract. Nothing reads the
    link today; noted in `router_config.py` so that nothing starts trusting it.
- **Decisions I made (reversible):**
  - The welcome bonus stays unspendable. Sign-up is open and limited only per IP address
    (5 an hour), so a spendable 100 could be farmed. The plan puts a faucet in Phase C.
  - `/onboard` reports 0 as the wallet balance and adds a `welcome_points` field, rather
    than keeping "100" under the name "wallet balance".
  - Added the read-only wallet lookup by DID instead of only rewording the message: an
    agent knows its DID, not its internal id, and the old instructions already named
    that address.
  - Funding amounts: 10,000 per founder agent and 50,000 for ATLAS (the old scripts'
    own numbers), changeable on the command line.
  - "Not the contractor" is now answered 403 and "parent not in progress" 409 (was 400
    for both), the same as the contracts routes.

## 2026-10-02 · cycle 19 · Fable (T1) · S9-7b: a task could promise a reward its creator did not have — fixed; a creator can now cancel a task nobody took and get the tokens back

- **Not live in production.** `tasks` and the token routers are switched off there.
- **What was wrong** (`daf8c64`):
  1. **Unfunded rewards.** Posting a task with a reward did three separate things: save
     the task, lock the reward out of the creator's wallet, take the 2.5 % fee. If the
     second failed (no wallet, or not enough in it) the failure was swallowed and the
     task stayed up, advertising a reward. Whoever did the work was then paid nothing.
  2. **No way back.** If nobody took a task, the creator's locked reward stayed locked
     for good. There was no cancel.
- **Now:**
  1. Saving the task, locking the reward and taking the fee happen together or not at
     all. A reward the wallet cannot cover is refused with a clear message and nothing
     is created. A task with no reward works as before and needs no wallet.
  2. New: the creator (nobody else, not even a FOUNDER) can cancel a task that is still
     open. The reward and the fee both come back, once, and the task is marked
     "cancelled". A task somebody has already taken, or a finished one, cannot be
     cancelled — that reward is the worker's to earn.
- **Merging adds one small database migration (042).** It lets a task carry the status
  "cancelled". It changes a rule, not a single row, and runs by itself on deploy. Checked
  locally: forwards, backwards, forwards again. (H2 note updated: the number after merge
  is now 042.)
- **Check:** platform suite **2432 passed, 117 skipped**; database tests **103 passed**
  (`--db`; 14 new, 12 of them fail on the old code — the other two check that a
  no-reward task still works and that the database still refuses junk statuses); smoke
  90 GET routes on the repo default, no 5xx; changed files lint clean. Live check on a
  real local server, real local database and real logins: **35 of 35**, and at the end
  every token in existence matched the supply counter.
- **Not done / not checked:**
  - The live check script was run by hand and is not in the repo.
  - Smoke with every router on (96 routes) was not re-run this cycle; no GET route changed.
  - The founder agents' task seeder (`runners/task_seeder.py`) posts tasks with a reward
    from a wallet it can no longer fund itself. Until S9-7c gives it a funded wallet it
    will get "insufficient funds" and create no tasks. It was already broken in a quieter
    way (its tasks paid nothing); now it fails loudly. Not run this cycle.
  - "Cancel at the same moment as a bid" is tested and both endings were seen (cancelled
    and refunded, or taken with the reward still locked), but a test for a race depends
    on timing. The fix does not: both paths take the same lock on the task.
  - The fee refund comes out of the treasury. Nothing else takes tokens out of the
    treasury today, so it always holds the fee. If that ever changes and the treasury is
    short, the cancel still refunds the reward and the fee stays with the treasury
    (tested), rather than blocking the cancel.
- **Decisions I made (reversible):**
  - A cancel refunds the fee too (the plan's default: the task never ran).
  - An unfunded reward is refused (400) rather than creating the task with a reward of 0.
  - A FOUNDER cannot cancel someone else's task. Nothing in the founding documents gives
    that power; a moderation path for tasks can add it later.
  - New status word "cancelled" (hence the migration) rather than reusing "FAILED", which
    the reputation code reads as a worker failing a task.
  - No event is published when a task is cancelled (same as contracts and bounties).
  - The dead `fail_task` function was removed (nothing called it; it could not have worked).
- **Open cost-free loop, noted on S9-8a:** an agent can now post and cancel tasks for
  free, as often as it likes. No tokens are at risk, but it is a way to spam the task
  list; task creation needs a rate limit like posts.

## 2026-10-02 · cycle 18 · Fable (T1) · S9-7a: any logged-in agent could create tokens or take another agent's stake — fixed; wallets, stakes and the economy router are on (in the repo)

- **Not live in production.** All three routers are switched off there, so nobody could
  have used these holes. Nothing to do urgently; this is why the step exists.
- **What the review found** before switching the token routers on (`8001ece`):
  1. **Minting.** "Create new tokens in the treasury" only asked for a login. Any agent
     could do it, and could also choose how the entry was labelled in the ledger (so a
     mint could be recorded as, say, an escrow payout). Now FOUNDER only, always labelled
     as a mint.
  2. **Slashing.** "Take an agent's staked tokens for the treasury" also only asked for a
     login: any agent could wipe out any other agent's stake. Two slashes at the same
     moment also paid the treasury twice. Now FOUNDER only, and it happens once.
  3. **Stakes could never be taken back.** There was no way to unstake: staked tokens
     were locked for good. New: an agent can release its own stake (nobody else's, not
     before the lock date it chose, and only once).
  4. **Founder grants left no trace.** When a FOUNDER funded a wallet, tokens appeared
     with no ledger entry and the supply counter did not move. Now both are written.
  5. **Task fee.** The 2.5 % platform fee was added to the treasury in a separate step
     after the reward was locked; if the reward had already been paid out, the fee was
     created from nothing. It is now taken only from what is really locked.
  6. **Two agents paying each other at the same moment** made the database abort one of
     the payments with a server error. Fixed (no money was at risk, only a failed call).
  7. Small: no paying yourself; absurdly large amounts and page sizes are refused cleanly.
- **Switched on in the repo** (`34bf912`): `wallets`, `stakes`, `economy`. The only
  routers still off are the four with a written reason: `agent_economy` (next),
  `governance` (S9-8), `nodes` and `consensus` (kept off on purpose).
- **Step split.** S9-7 was too big for one cycle done properly, so it is now S9-7a (this,
  done), S9-7b (a task's reward must be really funded; let a creator cancel an untaken
  task) and S9-7c (`agent_economy`, plus funding for the founder agents' runners).
- **Production:** unchanged by merging — the Fly override still lists all three (H3,
  updated). **Merging adds no database migration.** After H3, nothing has any tokens
  until a FOUNDER grants some.
- **Check:** platform suite **2416 passed, 103 skipped**; database tests **89 passed**
  (`--db`, 24 new; 15 of the 24 fail on the old code, the other 9 re-prove cycle 2's wallet
  rules against a real database); smoke 90 GET routes on the repo default and 96 with
  everything on, no 5xx; changed files lint clean. Live check on a real local server, real
  local database and real logins, repo-default router list: **38 of 38** — and at the end
  every token in existence matched the supply counter.
- **Not done / not checked:**
  - The live check script was run by hand and is not in the repo (the 24 database tests
    cover the same ground except real login tokens).
  - The old-code deadlock was seen 28 times in one run of the new test, but a test for a
    race can pass by luck on broken code; the fix (fixed lock order) does not depend on it.
  - The welcome bonus: sign-up tells a new agent it has "a funded wallet (100 AXP)". It
    does not — the 100 is a number in an older table that nothing can spend, and the
    wallet starts at 0. So there is no way to farm bonuses, but the message is untrue;
    correcting it is in S9-7c.
  - Tokens already in production wallets (if any exist) were created before the ledger
    rule in point 4, so the supply counter there may not match the wallets. Cannot check
    without production access; worth a look after H1.
- **Decisions I made (reversible):**
  - Minting and slashing are FOUNDER only (the code said "requires auth"; nothing in the
    founding documents gives ordinary agents either power).
  - A stake can be released by its owner at any time unless it was created with a lock
    date. A FOUNDER cannot release someone else's stake — only slash it, on the record.
    This interacts with voting (stake → vote → unstake → move → vote again): noted on
    S9-8, to be closed before `governance` is enabled.
  - A slash is refused if the treasury does not exist (it is created at every start-up),
    rather than destroying the tokens silently.
  - Paying an agent who has not opened a wallet is refused, not auto-created.
  - Balances and transaction history stay public (an open ledger), as they were.
  - No "D6" decision was raised for "how do new agents get tokens": the plan already
    answers it (founder grants now, a faucet in Phase C).

## 2026-10-02 · cycle 17 · Opus (T2) · S9-6e: private activity entries were public — fixed; direct messages can be sent again

- **Leak found and fixed** (`92d32cd`, SECURITY-REVIEW). Every agent has an activity
  timeline. Entries can be marked PRIVATE, FOLLOWERS-only or COLLECTIVE-only, but the
  public timeline showed all of them to anyone, no login needed. Now everyone sees PUBLIC
  entries and the agent itself sees all. This is in the code production runs today, so it
  is added to **H5**'s fast fix (now five commits; checked: applies cleanly on `main`,
  2097 tests pass there).
- **Sending a direct message was broken** on a database built the normal way (500 error):
  the code wrote to two columns the table does not have. It now writes to whichever shape
  the table has. Production most likely had the same fault.
- **Smaller:** the public live event stream (no login, one database query per second per
  viewer) now refuses more than 200 viewers per server; the A2A endpoint no longer sends
  internal error text back to the caller.
- **Checked and left as is:** the global activity feeds already showed PUBLIC only (now
  tested); `/ws/stats` shows only counts; a workflow's details show only what the task
  marketplace already shows.
- **Decisions I made:** FOLLOWERS / COLLECTIVE entries are owner-only for now, because
  nothing checks who follows whom yet (fails closed, easy to widen later).
- **Check:** platform suite **2374 passed, 79 skipped**; database tests **65 passed**
  (`--db`); the 8 new tests all fail on the old code; smoke 85 GET routes, no 5xx.
  **Merging adds no database migration.**

## 2026-10-02 · cycle 16 · Fable (T1) · S9-6d: sign-up could make anyone a FOUNDER; private messages were public — both fixed

- **Read this first: H5 in `HUMAN_ACTIONS.md`.** Two of the holes below are serious and
  are in the code production runs today. The fixes are on this branch only. H5 has a
  five-minute check for intruders and a fast way to ship just these fixes.
- **S9-6d done.** The step was "find the always-on routes that trust what the caller says
  about who they are". I had the app list every route that changes something, and read
  each one that either takes no login or carries an identity in its request. Six were
  wrong; one more turned up on the way.
  1. **Sign-up handed out any role** (`7a2fbe6`). Registering an agent takes no login,
     which is intended. But the caller could also pick the new agent's role, FOUNDER
     included, and got back a working FOUNDER login. Now sign-up gives MEMBER or OBSERVER
     only; any other role needs an existing FOUNDER's login (the seeding script already
     sends one).
  2. **Trust links** (`272077b`). Anyone, with no login, could record "agent A trusts
     agent B" with any weight, or wipe a link out. Now FOUNDER only.
  3. **Service listings** (`272077b`). Anyone, with no login, could list a service under
     any agent's name. Now an agent lists only its own.
  4. **Likes, endorsements, shares, comments** (`272077b`). A logged-in agent could record
     one in another agent's name. Now only in its own.
  5. **Declared capabilities** (`272077b`). A logged-in agent could declare capabilities
     for any other agent. Now only for itself (or a FOUNDER for anyone).
  6. **A2A tasks** (`09f7a3b`). An outside caller, with no login, could create a task in
     any agent's name. Creating one now needs a login and the task belongs to that agent.
  7. **Direct messages** (`3eb2c2a`). Anyone could read any agent's messages with no
     login. The text of every sent message was also copied into the public activity feed.
     Now an agent reads only its own messages; the text is no longer copied; the public
     feed and live stream skip message events, so copies already stored are not shown.
- **So it does not happen again** (`7564d7b`): a test now fails whenever a route that
  changes something has no login check, unless it is on a short reviewed list (10 routes:
  sign-up, getting a login, and searches).
- **Production:** unchanged, and still exposed, until these commits are deployed (H5).
  **Merging adds no database migration.** What outside agents will notice: listing a
  service, sending an A2A task and reading messages now need their own login; signing up
  with a role above MEMBER is refused.
- **Check:** full platform suite **2370 passed, 74 skipped** (was 2306; 64 new tests).
  Database tests: **60 passed** (`--db`, unchanged). Each group of new tests was also run
  against the old code to confirm it fails there (16, 15, 13 and 7 failures). Live check
  on a real local server, real local database and real logins: **52 of 52** — every
  attack above is refused and writes nothing, and the legitimate version of each call
  still works. Smoke harness green on the repo default (85 GET routes) and with every
  router on (96), no 5xx. Lint clean. The four security commits also apply cleanly on top
  of `main` by themselves, and the suite passes there (2093) — that is option (a) in H5.
- **Not done / not checked:**
  - I cannot see production, so I do not know whether anyone used these holes. H5 step 1
    answers that for the FOUNDER one. For messages there is no record of who read what.
  - The live check script was run by hand and is not in the repo.
  - Sending a message fails with a server error on a database built from the repo
    (an older bug, not from this cycle; → new step S9-6e). So in the live check the test
    message was written straight into the database; reading it was tested for real.
  - The two database filters that hide message events were checked in the live run, not by
    the automated suite (which only checks the query text).
- **Decisions I made (reversible):**
  - Anonymous A2A tasks are refused. The founding documents do not say; the Agent Cards
    already tell callers to bring a login, and an outside agent gets one from one call to
    `/onboard`.
  - Hand-recorded trust links are FOUNDER only, not "each agent for itself": the caller
    chooses the weight, so self-service would be a way to inflate scores.
  - Only a FOUNDER may grant FOUNDER, OPERATOR or DELEGATE (not an OPERATOR).
  - Nobody but the two parties can read a message, FOUNDER included. If you want a
    moderation view, say so.
  - A login that does not check out counts as no login (401), never as a lower level.
- **Found, not fixed (noted on the steps that own them):** sending messages is broken and
  the read-side check needs finishing (S9-6e, new); sign-up routes other than `/onboard`
  have no rate limit (S9-8a); the 100-token welcome bonus can be farmed with spare
  accounts once wallets are on, and staging hands a FOUNDER login to anyone (S9-7); one
  account can "verify" another's capability by endorsing twice (S9-9); the SDK calls a
  few of these routes the wrong way (S9-12).

## 2026-10-02 · cycle 15 · Fable (T1) · S9-6c bounties fixed; markets enabled

- **Recovered cycle 11.** Its unfinished work was in `git stash`. I read all of it, judged
  it sound, restored it, finished and tested it, and committed in three small pieces as
  DrJ asked (`b1219cb` service + router, `5680d2d` migration, `7ac7757` tests + switch-on).
  Cycles 12–14 did nothing; there is nothing else to recover and the stash is now empty.
- **S9-6c done** (`NEEDS-DELIBERATE-MERGE:`): bounties (prize competitions between agents)
  are now safe to switch on, and are on in the repo default.
  - **Before:** paying out a bounty checked "is it still open?", paid the winner, and only
    then closed it — so two pay-out calls at the same moment both paid, creating tokens
    from nothing. A creator could also enter their own bounty and award themselves the
    prize. A winner with no wallet was never paid, yet the bounty was marked as paid.
  - **Now:** the prize is locked when the bounty is created (no funds → no bounty). It
    leaves exactly once: to the top-scored entry when the creator pays out, or back to the
    creator if they cancel before anyone has entered (new "cancel" action). "Paid" and the
    payment happen together or not at all. The creator cannot enter or win their own
    bounty. Only the creator scores, pays out and cancels. A finished bounty takes no more
    entries, scores or payouts. The database itself now refuses a second payout record for
    the same bounty (migration 041).
- **Production:** unchanged (Fly override still set). H3 says what now turns on.
  **Merging adds one database migration (041)**, which runs by itself on deploy: it adds
  the "one reward per bounty" rule. If production somehow holds duplicate reward records,
  the extras are moved to a side table (`bounty_rewards_duplicates_041`), not deleted. No
  wallet or balance is touched.
- **Check:** full platform suite **2306 passed, 74 skipped** (was 2280 / 55; the 19 new
  skips are the new database tests, which need `--db`). Database tests: **60 passed**
  against real local Postgres (`.venv/bin/python -m pytest tests/integration -v --db`):
  17 tasks, 24 contracts, 19 new for bounties — including 12 simultaneous pay-outs → paid
  once, 10 simultaneous creates on a wallet that covers 3 → exactly 3, 8 simultaneous
  cancels → refunded once, cancel racing a new entry → exactly one wins, and the token
  total unchanged every time. With the row lock removed a test fails; with the lock and
  the status check both removed, two fail (tried by hand, then restored). Migration 041 on
  a throwaway local database: upgrade moves duplicates aside and keeps the earliest, a
  second reward row is then refused, downgrade puts the rows back, re-running is clean.
  Smoke harness green on the repo default, **85 GET routes** (was 82), and with every
  router on (96), no 5xx. Lint (`ruff check platform/src`) clean.
- **Not done this cycle:** the live check with a real server and real login tokens that
  cycles 9 and 10 ran. The database tests replace only the login check; the "no token →
  401" rule on the real login code is covered by the mocked router tests.
- **Not run by CI:** as before, the database tests are skipped without `--db`.
- **Decisions I made (reversible):**
  - Added "cancel" for a bounty nobody has entered (same reasoning as contracts: without
    it an unanswered bounty locks its creator's tokens for ever).
  - Did **not** invent a rule for a creator who never picks a winner, and did not start
    enforcing the deadline field → **D5**.
  - A winner with no wallet gets one created at payout (the tokens come out of the locked
    prize, so nothing is created from nothing).
  - A creator with no wallet is answered 400 "Insufficient funds" (the stash had 404),
    matching contracts. Wrong caller is 403, wrong state 409 (both were 400).
  - `GET /markets/bounties` returns 50 rows per call by default, 200 at most (was: the
    whole table).
  - Entries stay publicly readable while a bounty is open (unchanged: a later entrant can
    read earlier entries. A design matter, not a token risk; recorded in the comment on
    `markets` in `router_config.py`).
- **Found, not fixed (noted on the steps that own them):** bounties can be farmed for
  reputation with spare accounts like tasks and contracts (S9-9); SDK bounty helpers need
  checking against the new routes (S9-12).

## 2026-10-01 · cycle 10 · Fable (T1) · S9-6b contracts fixed; contracts + verifications enabled

- **S9-6b done** (`c9259a0`, `NEEDS-DELIBERATE-MERGE:`): contracts are now safe to switch
  on, and are on in the repo default, together with verifications.
  - **Before:** any logged-in agent could "dispute" anyone's contract at any time, which
    froze its locked tokens for good. Nothing ever paid a contractor: the "accept the work"
    step existed in the code but had no endpoint, and it could pay twice if called twice at
    the same moment. A creator could bid on and win their own contract. A contract could be
    created advertising a budget the creator never paid in.
  - **Now:** only the creator or the hired contractor can dispute, and only while work is
    under way. The creator accepts the work with a new "complete" action, which marks the
    contract finished and pays the contractor together, exactly once. The creator can cancel
    a contract nobody was hired for and gets the tokens back, exactly once; after hiring,
    the creator cannot take them back. The budget is locked when the contract is created,
    or the contract is refused. No bidding on your own contract; one bid per agent.
  - **Verifications** (other agents voting on whether delivered work is good): the
    contractor can no longer vote on their own work; a vote can no longer slip in after the
    result is decided; and the code that would have paid voters from a reward pot nobody
    ever paid into is switched off (it would have created tokens from nothing). A
    verification is advice only: it never moves tokens.
- **Production:** unchanged (Fly override still set). H3 says what now turns on and gives
  the line that keeps the token-moving routers off.
- **Check:** full platform suite **2280 passed, 55 skipped** (was 2234 / 31; the 24 new
  skips are the new database tests, which need `--db`). Database tests: **41 passed**
  against real local Postgres (`.venv/bin/python -m pytest tests/integration -v --db`):
  17 for tasks, 24 new for contracts — including 12 simultaneous "complete" calls → paid
  once, pay-out racing refund → paid once, cancel racing hire and complete racing dispute →
  exactly one wins, and the token total unchanged every time. Removing any one of the three
  row locks makes a test fail (tried each by hand). Live check with a real server on the
  repo-default router list and real login tokens: 51 of 51 as expected. Smoke harness green
  on the repo default, **82 GET routes** (was 79), and with every router on (96), no 5xx.
  Lint (`ruff check platform/src`) clean.
- **Not run by CI:** as last cycle, the database tests are skipped without `--db`; CI runs
  the mocked unit tests of the same rules.
- **Decisions I made (reversible):**
  - A contract whose budget cannot be locked is refused (was: created anyway, paying
    nothing at the end). Consequence: with wallets still off, nobody can create a contract
    through the API until S9-7. I enabled the router anyway: it refuses cleanly, and it is
    not live in production before H3.
  - Added "cancel" for a contract with nobody hired (not in the plan, but small, and
    without it an unanswered contract locks its creator's tokens for ever).
  - Did **not** invent rules for disputes or for a side that goes quiet → **D3**.
  - Did not change what the contractor is paid (the whole budget, whatever the bid) → **D4**.
  - Contractor may not vote on their own work (the plan had this as a Phase B note; it is
    one line and mirrors the existing rule for the requester).
  - Verifier rewards off rather than repaired: there is no source of funds to repair them
    with. Through the API the pot was always 0, so nothing visible changes.
  - Wrong caller is now answered 403 and wrong state 409 (both were 400).
  - `GET /contracts` returns at most 200 rows per call (was: the whole table).
- **Found, not fixed (noted on the steps that own them):** rate limits in "log" mode
  swallow the request instead of letting it through (S9-8a); verification votes and
  contract completions are easy to farm for reputation with spare accounts (S9-9); the SDK
  has no `complete` / `cancel` for contracts (S9-12).
- **Housekeeping:** the database-test fixtures moved to `tests/integration/conftest.py` so
  the tasks and contracts tests share one throwaway database.

## 2026-10-01 · cycle 9 · Fable (T1) · S9-6a tasks router fixed and enabled

- **S9-6a done** (`6d4b666`, `NEEDS-DELIBERATE-MERGE:`): the task marketplace is now safe to
  switch on, and is on in the repo default.
  - **Before:** none of the `/tasks` endpoints checked who was calling. Anyone, without
    logging in, could lock another agent's tokens into a task, win that task and pay the
    tokens to themselves; could mark anyone's task finished; and a reward could be paid
    twice if a result was submitted twice at the same moment.
  - **Now:** every write needs a login and acts as the logged-in agent. Naming another
    agent in the request is refused. Only the task's creator can accept a bid. Only the
    agent the task was assigned to can submit the result, once, and "finished" and "paid"
    happen together or not at all. A finished task cannot be re-opened.
  - **Also fixed:** `POST /workflows/create` — always on, so live in production today — let
    anyone create tasks in any agent's name without logging in. It now needs a login.
    And reading an open marketplace task (`GET /tasks/{id}`) returned an error 500.
- **Scope:** the plan's S9-6a covered tasks, contracts and markets. Each is a separate money
  path, so this cycle did tasks properly and split the rest into **S9-6b** (contracts, then
  verifications) and **S9-6c** (markets). Both stay locked off.
- **New step S9-6d:** the always-on A2A endpoint (`POST /a2a`, `message/send`) still creates
  zero-reward tasks under whatever agent name the caller types in, with no login. No tokens
  move, but it is live in production today. Not fixed here because it changes how outside
  agents talk to the platform; it gets its own reviewed step.
- **Production:** unchanged (Fly override still set). H3 now says `tasks` turns on too, and
  gives the exact line to keep it off.
- **Check:** full platform suite **2234 passed, 31 skipped** (was 2191 / 14; the 17 new
  skips are the database tests, which need `--db`). Database tests: **17 passed** against
  real local Postgres (`.venv/bin/python -m pytest tests/integration -v --db`), including
  12 simultaneous result submissions → paid once, and simultaneous release + refund → paid
  once. Removing any one of the three row locks makes a test fail (tried each by hand).
  Live check with a real server and real login tokens: 24 of 24 as expected. Smoke harness
  green on the repo default, **79 GET routes** (was 76), no 5xx.
- **Not run by CI:** the database tests are skipped without `--db`, and CI does not pass it.
  The mocked unit tests cover the same rules in CI; the proof of "paid once" is local only.
- **Decisions I made (reversible):**
  - Split S9-6a instead of touching three money paths in one commit.
  - Payout moved inside the same transaction as "task completed" (was a separate, soft-fail
    step). If the payout fails, the submit fails and can be retried, instead of leaving a
    finished task that never pays.
  - Being paid creates the executor's wallet if they have none (the tokens come out of
    escrow; nothing is minted). Otherwise the new "once only" rule could strand the reward.
  - The legacy body fields (`creator_agent_did`, `agent_did`, `requester_agent_did`,
    `initiator_agent_did`) stay accepted when they name the caller, so the existing runners
    keep working unchanged.
  - A FOUNDER may update a direct task on the executor's behalf. That is how the local
    compose worker acts; it now needs `WORKER_API_TOKEN`. It is not deployed on Fly.
  - A creator cannot bid on their own task, and a task an agent gives itself earns no
    reputation. Farming reputation with *two* accounts is still possible — noted on S9-9.
  - Enabled `tasks` although the marketplace pays on submit with no creator approval
    (existing design). Raised as **D2** rather than held, because production stays off until
    H3 and the founder runners depend on the current flow.
- **Broken on purpose:** scripts that called `/tasks` or `/workflows` without logging in
  (`agents/runner.py`, `agentx-examples/multi-agent-demo`) now get 401.

## 2026-10-01 · cycle 8 · Opus (T2) · S9-6 work routers reviewed; two enabled

- **S9-6 done** (`4bb333d`, `SECURITY-REVIEW:`): reviewed every write endpoint in the six
  "work" routers before switching them on.
  - **Switched on:** `collectives` and `agentbus` (agent-to-agent messages). Two small gaps
    fixed first: a collective admin could claim *any* agent's task for their collective (now
    only the task's requester or executor, and only while unfinished); and a message could
    name someone else as its sender (now refused with 403, and inboxes show the real sender).
  - **Locked off (Tier A):** `tasks`, `contracts`, `markets`. Each can move tokens wrongly:
    `tasks` has no login check at all, so anyone could spend another agent's tokens on a task
    and pay them to themselves; any agent can freeze any contract's escrow forever via
    "dispute", and nothing ever releases contract escrow; bounty payouts can be paid twice if
    triggered at the same moment. New step **S9-6a** (T1) fixes them.
  - **Held:** `verifications` only works on contracts, so it waits for S9-6a.
- **Production:** unchanged (Fly override still set; H3 updated with what now turns on).
- **Check:** full platform suite **2191 passed, 14 skipped** (was 2151); smoke harness green
  on the repo default, **76 GET routes** (was 71), no 5xx.
- **Decisions I made (reversible):** split S9-6 instead of fixing token code in a T2 cycle;
  the token fixes need a T1 cycle and a deliberate merge. Collective task hand-off allowed
  for the task's requester *or* executor (either party can bring a collective in).

## 2026-10-01 · cycle 7 · Opus (T2) · S9-5 social routers enabled

- **S9-5 done** (`2840b1a`, `SECURITY-REVIEW:`): the repo default now switches on `memory`,
  `graph`, `rooms`, `communities`, `conversations`, `channels` and `pulse`. `graph` left Tier A
  (its two typos were fixed earlier in Sprint 9), so Tier A is now `agent_economy`, `nodes`,
  `governance`, `consensus`. Tier C is empty (memory: stale gating, no defect).
- **Review of write endpoints:** every one in the cohort takes the agent from the login token,
  not the request body; memory is owner-or-admin; rooms/canvas/channels check membership.
  One gap fixed: canvas node PATCH/DELETE ignored the room in the URL, so a participant of one
  room could send fake canvas events to another room's live channel. Now "not found".
- **Production:** unchanged until DrJ removes the Fly `DISABLED_ROUTERS` override (H3, after
  H1). A test pins that the full production value still keeps the cohort off. H3 now lists
  what turns on.
- **Check:** full platform suite **2151 passed, 14 skipped** (was 2147); smoke harness green on
  the repo default, **71 GET routes** (was 49), no 5xx.
- Cycle 6 did nothing (shell permissions); DrJ fixed them.

## 2026-10-01 · cycle 5 · Fable (T1) · S9-4a kill-switch safety

- **S9-4a done** (`8101e92`, `SECURITY-REVIEW:`): the Fly `DISABLED_ROUTERS` value can still
  switch any router off in seconds, but it can no longer switch a Tier A (broken or insecure)
  router **on** by leaving it out. The routers really disabled are now "whatever the list says"
  plus `agent_economy`, `nodes`, `governance`, `consensus`, `graph`, always. The only way to
  enable one of those is to fix it and move it out of Tier A in `router_config.py`.
- **Why an opt-out exists:** the test suite and the smoke harness test Tier A routers on
  purpose, so they set `ALLOW_UNSAFE_ROUTERS=1`. It works in development only. In staging and
  production it is ignored and the startup log says so; a mistyped value keeps the lock and
  does not stop the app from booting.
- **Startup log** now names any router the lock forced off, and warns if the lock is lifted.
- **Not changed:** routers outside Tier A (tasks, wallets, memory, …) are still switched on by
  a short env value, exactly as before. That is the existing "env replaces repo list" design
  and S9-5..S9-8 turn those on anyway. H3's warning is reworded to match.
- **Check:** `tests/test_router_config.py` 55 passed, including one that boots the real app
  with `DISABLED_ROUTERS=posts` and finds no Tier A route mounted (and confirmed by hand that
  the same boot with the opt-out mounts them, so the test can fail). Full platform suite
  **2147 passed, 14 skipped** (was 2097). Smoke harness green on the default list (49 routes)
  and with every router on (96 routes).
- **Decisions I made (reversible):**
  - Opt-out is an env flag limited to development rather than no opt-out at all: without it
    the existing API tests of Tier A routers, and the all-routers smoke run, could not reach
    those routers.
  - Outside development the flag is ignored rather than refusing to start: a stray flag should
    not take production down, and ignoring it is the safe direction.
  - Kept "env replaces the list" for Tier B/C instead of making the env purely additive
    ("can only switch off"). Additive is arguably the cleaner kill-switch, but it changes the
    Sprint 9a design DrJ approved; worth a look once S9-5..S9-8 have emptied Tier B.

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
