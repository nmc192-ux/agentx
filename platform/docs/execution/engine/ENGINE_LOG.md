# Engine log

Newest at the top.

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
