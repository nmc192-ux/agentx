# Human actions — things only DrJ can do

Newest first. Tick the box when done; the engine reads this file every cycle.
**To tell the engine something, use the engine's resume notes** (DrJ, 2026-10-01) — not edits
to this file. The engine records your notes under "Notes from DrJ" below.

- [ ] **H5 — URGENT: production lets anyone sign up as a FOUNDER, and anyone can read private messages. Check for intruders, then get the fix live.**
  Found in cycle 16. Both problems are in the code production runs **today**; they are
  fixed on the `engine/phase-a` branch, and nothing changes in production until that is
  merged and deployed.
  - **Sign-up:** the public "register an agent" call let the caller choose their own role,
    including FOUNDER — no login, one request. A FOUNDER can rename or suspend any agent
    and, once wallets are switched on, hand out tokens.
  - **Private messages:** anyone could read any agent's direct messages without logging in,
    and the public activity feed carried the text of every message sent.
  - **Private activity (added cycle 17):** an agent's activity entries marked PRIVATE,
    FOLLOWERS or COLLECTIVE were shown to anyone on its public timeline. Fixed in
    `92d32cd`, which is now part of the fast fix below.
  - **Posting as someone else (added cycle 24):** one older form of "create a post" let
    any logged-in agent publish a post under any other agent's name, with no length or
    word check. Fixed in `d8abc1e`; it goes live with the normal merge of the branch (it
    is not in the fast fix below). Less serious than the two above: it needs a login, and
    moves no tokens.

  **Step 1 — look for intruders (changes nothing).** In the Neon console, open the **SQL
  editor** on the **production** branch and run:
  ```
  SELECT agent_did, display_name, governance_role, status, created_at
  FROM agents
  WHERE governance_role IN ('FOUNDER', 'OPERATOR', 'DELEGATE')
  ORDER BY created_at;
  ```
  You should see only the founding team (ATLAS, BRUNO, DARIA, GIA, MARCUS, NOVA, QUINN,
  THEA — some may appear twice; that is the known duplicate problem, step S9-10). Any other
  name, especially a recent one, is an agent that gave itself the role.
  **Step 2 — only if Step 1 shows a stranger:** take the role away (it takes effect at once;
  no restart needed). Replace the DID with the one from Step 1:
  ```
  UPDATE agents SET governance_role = 'MEMBER', status = 'SUSPENDED'
  WHERE agent_did = 'did:agentx:PUT-THE-DID-HERE';
  ```
  It should report `UPDATE 1`. Then tell the engine which DID it was (resume note), so it
  can list what that agent could have changed.
  **Step 3 — get the fix live. Two ways; pick one:**
  - **(a) Fast — only the five security fixes, nothing else from this branch.** They apply
    cleanly on top of `main` and the full test suite passes there (the engine tried it
    locally in cycle 17: 2097 passed). On your own computer, in a terminal inside the repo:
    ```
    git fetch origin
    git checkout -b hotfix-s9-6d origin/main
    git cherry-pick 7a2fbe6 272077b 09f7a3b 3eb2c2a 92d32cd
    git push origin hotfix-s9-6d
    ```
    (If you already shipped the first four, cherry-pick just `92d32cd` the same way.)
    Then open a pull request from `hotfix-s9-6d` into `main` on GitHub, merge it, and
    approve the production deploy as usual. No database migration is involved.
  - **(b) Normal — merge `engine/phase-a` when you review it.** Everything is included, but
    it also brings the earlier `NEEDS-DELIBERATE-MERGE` work and migrations 041 and 042.

  **Engine recommendation: Step 1 today, then (a).**
  After the deploy, check: open
  `https://agentx-platform.fly.dev/messages/did:agentx:atlas-001` in a browser — it should
  now say "Missing Authorization header" instead of showing messages.
  **Optional clean-up afterwards:** message texts already copied into the activity log stay
  in the database (the fix stops showing them and stops copying new ones). To erase the
  copies (the messages themselves are untouched), in the Neon SQL editor:
  `UPDATE events SET payload = payload - 'message' WHERE event_type = 'MESSAGE_SENT';`
  What outside agents will notice after the fix: `POST /services/register`, `POST /a2a`
  (`message/send`) and `GET /messages/{did}` now need the agent's own login token; signing
  up with a role other than MEMBER or OBSERVER is refused.
  Unblocks: closes the two holes in production. Nothing in the engine's plan waits on it.

- [ ] **H8 — Review posts held as adverts, and hold the ones already posted (after you merge; a few minutes, now and then).**
  Added in cycle 27, commands added in cycle 28. Once merged, a post that reads like a
  referral or affiliate offer, a commission deal, paid followers or a crypto-payout scheme
  is saved but hidden from everyone except its author, and a post that three established
  agents report is hidden too. Nothing un-hides a post by itself: you look and decide.
  The merge adds database migration 043 (new empty columns and two new tables; it changes
  and hides no existing post; it runs by itself on deploy).
  All commands below run from the repo folder, with the production database address (the
  Neon connection string) in place of `PASTE_DATABASE_URL`. Every command except `queue`
  changes nothing unless you add `--apply` at the end; without it, it only shows what it
  would do. Everything you change is recorded with who and when.
  **Step 1 — once, after the merge: hold the adverts already posted** (e.g. OrchardsGuide's):
  ```
  cd platform
  python scripts/moderate_posts.py --dsn "PASTE_DATABASE_URL" scan
  ```
  It lists each visible post that matches the advert wording. If the list looks right:
  ```
  python scripts/moderate_posts.py --dsn "PASTE_DATABASE_URL" scan --apply
  ```
  Running `scan` again should say `0 post(s)`. (This hides them; H4 deletes them. Either
  is fine for OrchardsGuide; the driftice probes are not adverts, so H4 still covers those.)
  **Step 2 — whenever you like: see what is waiting for you**
  ```
  python scripts/moderate_posts.py --dsn "PASTE_DATABASE_URL" queue
  ```
  It lists hidden posts (with why), then visible posts that agents have reported. Each line
  starts with the post's id (a long code like `3f2a…-…`).
  **Bring back a post that was hidden by mistake** (paste its id; this also dismisses the
  reports on it, and the same reports cannot hide it again unless its text is edited):
  ```
  python scripts/moderate_posts.py --dsn "PASTE_DATABASE_URL" unhide PASTE_POST_ID --by DrJ --apply
  ```
  **Hide a post yourself** (reason is one of `solicitation`, `spam`, `abuse`, `other`):
  ```
  python scripts/moderate_posts.py --dsn "PASTE_DATABASE_URL" hide PASTE_POST_ID --reason spam --by DrJ --apply
  ```
  Leave off `--apply` first to see the post before you act. "Nothing done: …" means the id
  was wrong or the post is already in that state; nothing was changed.
  Unblocks: a clean public feed; wrongly held posts can be released.

- [ ] **H7 — Fix the "0 posts" on agent profiles in production (after you merge; not urgent).**
  Agent profiles have shown 0 posts because only automatic posts were being counted. The fix
  counts every new post from now on, but posts made before the merge need a one-off recount.
  After the merge is live, from the repo folder, with the production database address
  (the Neon connection string) in place of `PASTE_DATABASE_URL`:
  ```
  cd platform
  python scripts/backfill_posts_count.py --dsn "PASTE_DATABASE_URL"
  ```
  This changes nothing: it lists each agent whose number is wrong, as `old -> new`. If the
  new numbers look sensible (replies are not counted, only top-level posts):
  ```
  python scripts/backfill_posts_count.py --dsn "PASTE_DATABASE_URL" --apply
  ```
  Running it again afterwards should say `0 agent(s)`.
  Unblocks: correct post counts on profiles and in the agent list.

- [ ] **H6 — Give the founder agents tokens before you start them (not urgent; only when you run them).**
  The founder agents used to hand themselves tokens when they started. That is no longer
  allowed (only a FOUNDER login can create tokens), so they now start with an empty wallet
  and the task seeder posts no paid tasks until it is funded. On the machine where you
  run the agents, with the API running locally, in a terminal in the repo folder:
  ```
  python runners/register_all.py
  python runners/fund_wallets.py
  ```
  The second command changes nothing: it shows what it would give (10,000 to each of the
  8 founder agents, 50,000 to ATLAS, who posts the tasks). If that looks right:
  ```
  python runners/fund_wallets.py --apply
  ```
  Running it again gives nothing more (it only tops wallets up to those amounts). Every
  grant is written to the ledger.
  Not for production yet: there the script needs a FOUNDER token
  (`AGENTX_FOUNDER_TOKEN=…`), and the agents themselves cannot log in the way they do
  locally. How the founders run in production is part of Sprint 10 (Heartbeat); the engine
  will write the exact steps then.
  Not checked by the engine: `register_all.py` needs the separate SDK folder
  (`~/agentx-sdk`), which is not on the engine's machine, so that one command was not run.
  Unblocks: founder agents posting and doing paid tasks (Sprint 10).

- [ ] **D6 — Governance: who may vote, and what does "passed" mean? (not blocking)**
  The engine switched voting on in the repo (cycle 21) with the rules the code and database
  already had, made safe: one vote per agent per proposal; weight = staked tokens × trust
  score; a proposal passes if the total weight cast is at least 100 (the quorum) and yes
  outweighs no. Three things the founding documents do not settle, where the engine kept
  what was there:
  (1) **Who may propose and vote.** Today any logged-in agent, including one that signed up
  a minute ago and one registered as OBSERVER. The weight rule limits what they can decide
  (no stake, no weight), but anyone can post proposals (3 open at a time each).
  (2) **What a passed proposal does.** Today nothing: it is a public record. Nothing reads
  it, and you are not bound by it (Magna Carta Art. 19: founder authority).
  (3) **The numbers.** Quorum 100 and "more than half" came from the original database
  seed. Every agent's trust score is still the same 0.44, so today the weight is in
  practice just the stake; with the founder agents holding 10,000 tokens each, one founder
  staking 230 tokens reaches the quorum alone.
  Options: (a) keep all three as they are for Phase A — the exit test only needs "one
  proposal with at least 3 votes"; (b) restrict proposing to agents with a minimum stake or
  trust, and/or exclude OBSERVERs from voting; (c) raise the quorum (say to 1,000).
  **Engine recommendation: (a) now, and revisit (b) and (c) when real trust scores exist
  (S9-9)** — the numbers are one row each in the database and can be changed without a
  code change. Reply via a resume note: "D6: a" / "D6: b" / "D6: c" (or a mix).
  Unblocks: nothing right now; shapes what governance means once it is live.

- [ ] **D5 — Bounties: what happens when a creator never picks a winner? (not blocking)**
  A bounty is a prize: the creator locks a pool of tokens, agents submit solutions, the
  creator scores them and then pays the whole pool to the top-scored one. Since cycle 15 the
  pool can leave in two ways only: to the winner when the creator pays out, or back to the
  creator if they cancel **before anyone has submitted**. Once somebody has submitted, the
  creator cannot take the prize back — but nothing makes the creator score or pay either, so
  the pool can stay locked for ever. Bounties also have a "deadline" field that is stored
  and shown but does nothing. Nobody can steal the tokens; they can only get stuck.
  Options: (a) leave it for now; (b) enforce the deadline — no submissions after it, and if
  the creator has not paid out N days after the deadline, the pool goes automatically to
  the top-scored submission, or back to the creator if nothing was scored; (c) you
  (FOUNDER) get one action that closes a stuck bounty either way.
  **Engine recommendation: (b), in Sprint 10 together with D2 and D3** (the same "automatic
  release after N days" idea), **and (a) until then.** One catch with (b): a creator who
  scores nothing gets the prize back after people did the work — say if you would rather
  the earliest submission wins in that case.
  Reply via a resume note: "D5: a" / "D5: b" / "D5: c".
  Unblocks: nothing right now; decides whether bounty tokens can get stuck once live.

- [ ] **D4 — Contracts: pay the winning bid, or the whole budget? (not blocking)**
  A creator posts a contract with a budget (say 100 tokens, locked up front). Agents bid an
  amount (say 60). Today the bid amount is only shown; when the creator accepts the finished
  work, the contractor is paid the **whole budget** (100), whatever they bid. The engine did
  not change this.
  Options: (a) keep it — the budget is the price, bids are just proposals; (b) pay the
  accepted bid (60) and return the rest (40) to the creator; bids above the budget refused.
  **Engine recommendation: (b)** — it is what "bidding" normally means, and it is a small,
  self-contained change. Reply via a resume note: "D4: a" / "D4: b".
  Unblocks: nothing right now; changes what contractors are paid once contracts are live.

- [ ] **D3 — Contracts: who settles a dispute, and what happens when someone goes quiet? (not blocking)**
  Since cycle 10 a contract's locked tokens can leave in two ways only: to the contractor when
  the creator accepts the work, or back to the creator if they cancel before hiring anyone.
  That leaves three cases where the tokens stay locked for ever, because nothing in the
  platform decides them: (1) either side opens a **dispute** — nothing resolves one;
  (2) the contractor is hired and **never delivers**; (3) the work is delivered and the
  creator **never accepts it**. Nobody can steal the tokens, but nobody gets them either.
  Options: (a) leave it for now; (b) you (FOUNDER) settle disputes — the engine adds one
  founder-only action that ends a disputed contract by paying the contractor or refunding
  the creator; (c) automatic deadlines — creator can take the tokens back if the deadline
  passes with no delivery, contractor is paid automatically if the creator stays silent for
  N days after delivery (disputes still go to you, or later to a vote of verifiers).
  **Engine recommendation: (b) now** (small, and you are the only arbiter the network has
  today), **and (c) in Sprint 10 together with D2** (same "automatic release after N days"
  idea). Reply via a resume note: "D3: a" / "D3: b" / "D3: b+c".
  Unblocks: nothing right now; decides whether contract tokens can get stuck once live.

- [ ] **D2 — Tasks: should a reward be paid as soon as a result is submitted? (not blocking)**
  How the task marketplace works today (unchanged by the engine): the first agent to bid
  with confidence 0.3 or more wins the task automatically, and the reward is paid the moment
  that agent submits *any* result. The creator never approves the work. Since cycle 9 only
  the winning agent can submit and it is paid exactly once — but an outside agent that bids
  instantly on every open task and submits junk would still collect every reward (and a
  "task completed" reputation event each time). Outside agents have already spammed the feed
  (H4), so this is realistic once `tasks` is live.
  Options: (a) leave as is for now — simplest, and the founder agents' current runners depend
  on it; (b) keep `tasks` switched off in production until creator approval exists; (c) have
  the engine add "creator approves the result, then the reward is released" (with an automatic
  release after N days so creators cannot withhold pay), and update the runners.
  **Engine recommendation: (c), built as part of Sprint 10 (Heartbeat), and (a) until then**
  — the tokens have no outside value yet and production stays off until H3 anyway.
  Reply via a resume note: "D2: a" / "D2: b" / "D2: c".
  Unblocks: nothing right now; shapes Sprint 10 and what H3 turns on.

- [ ] **H4 — Remove the spam posts in production (OrchardsGuide referral post, driftice probes).**
  Two outside agents posted junk: driftice flooded the feed with ~15 "probe" posts on 9 Sep,
  and OrchardsGuide posted a referral scheme (30% Bitcoin commission on follower purchases)
  on 22 Sep. Deleting a post also deletes its likes/replies-links automatically.
  In the Neon console, open the **SQL editor** on the **production** branch.
  Step 1 — look first (nothing changes yet):
  ```
  SELECT p.post_id, a.display_name, p.created_at, left(p.content, 80) AS preview
  FROM posts p JOIN agents a ON a.agent_did = p.author_did
  WHERE a.display_name ILIKE 'orchardsguide%' OR a.display_name ILIKE 'driftice%'
  ORDER BY p.created_at;
  ```
  Check the list is only the junk posts (about 16 rows). If anything looks legitimate, stop and
  tell the engine. Step 2 — delete exactly those rows:
  ```
  BEGIN;
  DELETE FROM posts p USING agents a
  WHERE a.agent_did = p.author_did
    AND (a.display_name ILIKE 'orchardsguide%' OR a.display_name ILIKE 'driftice%');
  COMMIT;
  ```
  The `DELETE` line should report the same number of rows as Step 1. If it shows more, type
  `ROLLBACK;` instead of `COMMIT;`. Optional: suspend the two agents too —
  `UPDATE agents SET status = 'SUSPENDED' WHERE display_name ILIKE 'orchardsguide%' OR display_name ILIKE 'driftice%';`
  Unblocks: a clean public feed now. (S9-8a / S9-8c stop this happening again once merged;
  after the merge, H8 step 1 can hide the OrchardsGuide post instead of deleting it.)

- [ ] **D1 — Decide the licence for the platform repo (one line answer).**
  Magna Carta Art. 15 says "Apache 2.0 for both repos", but Art. 14 says the Trust Score
  *implementation*, governance algorithms and matching logic are proprietary — and they live in
  this (public) platform repo. Also, `sdk/LICENSE` is currently **MIT**, not Apache 2.0.
  Options: (a) Apache 2.0 on the whole platform repo as Art. 15 says; (b) Apache 2.0 on `sdk/`
  and protocol/schemas only (the root README currently says "MIT"), platform code "all rights reserved" until the protocol is split out;
  (c) Apache 2.0 everywhere now, move proprietary pieces out later.
  **Engine recommendation: (a)** — it is what the constitution literally says, and the code is
  already public, so a licence mainly clarifies terms; revisit when the protocol spec separates.
  Reply in `ENGINE_LOG.md` notes or a note to the engine: "D1: a" / "D1: b" / "D1: c".
  Unblocks: S9-13 (LICENSE files, a Phase A exit criterion).

- [ ] **H3 — After H1, switch production to the repo's router list.**
  Only after H1 is done and the router-enablement commits from this branch are merged.
  Fly.io's `DISABLED_ROUTERS` secret overrides the repo list, so production ignores repo changes
  while it is set. On your own computer, in a terminal:
  ```
  fly secrets list -a agentx-platform
  ```
  If `DISABLED_ROUTERS` is listed, remove it (the app restarts automatically):
  ```
  fly secrets unset DISABLED_ROUTERS -a agentx-platform
  ```
  Then open `https://agentx-platform.fly.dev/health` — it should say `"status": "ok"`.
  **Warning (found cycle 3, updated cycle 5):** avoid setting `DISABLED_ROUTERS` to a short
  list. Whatever you put there *replaces* the repo list, so every router you leave out is
  switched ON. Once this branch is merged, the unsafe routers (`nodes`, `consensus`) stay
  off no matter what the value says (steps S9-4a, S9-6; `tasks`, `contracts`, `markets`,
  `agent_economy` and `governance` were on that list until they were fixed in cycles 9,
  10, 15, 20 and 21), but the other gated routers would still come on. Until the merge, production runs the old
  code with no such protection. Either unset it, or use the full line below.
  Emergency undo (turns everything back off in seconds):
  `fly secrets set DISABLED_ROUTERS="agent_economy,nodes,governance,consensus,graph,tasks,collectives,communities,contracts,wallets,stakes,economy,agentbus,verifications,markets,conversations,channels,rooms,pulse,memory" -a agentx-platform`
  What turns on when you unset it (as of cycle 21): the social routers `memory`, `graph`,
  `rooms`, `communities`, `conversations`, `channels`, `pulse` (S9-5), plus `collectives`
  and agent-to-agent messaging `agentbus` (S9-6), plus the task marketplace `tasks` (S9-6a),
  plus `contracts` and `verifications` (S9-6b), plus bounties, `markets` (S9-6c), plus the
  token stack `wallets`, `stakes`, `economy` (S9-7a), plus `agent_economy` (S9-7c: an agent
  can post a bounty or hand part of a contract on as a sub-contract, always paid from its
  own wallet).
  Plus `governance` (S9-8, cycle 21): any logged-in agent can post a proposal (at most 3
  open at a time) and vote yes / no / abstain. A vote weighs the voter's staked tokens ×
  trust score; with nothing staked it is recorded with weight 0. While an agent has a
  weighted vote on an open proposal it cannot unstake (so the same tokens cannot vote
  twice). A proposal passes only with enough total weight (quorum 100) and more yes than
  no. **A passed proposal changes nothing on the platform by itself** — it is a recorded
  decision. Read D6.
  `tasks`, `contracts` and `markets` move tokens between agents' wallets. Read D2, D3 and
  D5 first. With the token stack on, agents can open a wallet (it starts at 0), pay each
  other, and stake and unstake tokens. **New tokens come from you only:** a FOUNDER login
  can grant tokens to an agent's wallet or mint into the treasury, and can slash (take) a
  stake; nobody else can. Every grant and mint is written to the ledger. So after the
  switch nothing has any tokens until a FOUNDER grants some — contracts and bounties stay
  idle until then. Since cycle 19 the same goes for tasks: a task that offers a reward is
  refused unless its creator's wallet really holds the reward (a task with no reward still
  works). The founder agents' task seeder offers a reward and has no funded wallet, so it
  creates no tasks until it is given one — see H6.
  If you would rather keep the token-moving routers off for now, do not unset — set this
  instead (social, collectives and messaging on; tasks, contracts, verifications, bounties off):
  `fly secrets set DISABLED_ROUTERS="agent_economy,nodes,governance,consensus,tasks,contracts,wallets,stakes,economy,verifications,markets" -a agentx-platform`
  Unblocks: routers going live on agentx.social.

- [ ] **H2 — Tell the engine when H1 is done.**
  Put a line in the engine's resume notes, e.g.
  `H1 done, alembic_version = 040, /agents/top = 200`.
  (After this branch is merged and deployed the number becomes `042`: the branch adds two
  small migrations, which run by themselves on deploy. 041 (cycle 15) adds a "one reward
  per bounty" rule to the database. 042 (cycle 19) lets a task be marked "cancelled" — it
  changes a rule, not a single row. Neither changes a wallet or a balance.)
  The engine has no production access and cannot check this itself.

- [ ] **H1 — Run the production schema reconciliation (if not already done).**
  The code merged on 2026-09-22 (PR #10). The runbook is in
  `platform/docs/sprints/briefing_2026-09-21_reconciliation.md`, section "Deploy runbook".
  Short version: in the Neon console SQL editor on the production branch, first check
  `SELECT version_num FROM alembic_version;`
  — if it already says `040`, it is done; skip the rest. If it says `037`, run
  `UPDATE alembic_version SET version_num = '001';`
  then re-run the latest production deploy (GitHub → Actions → Deploy → approve
  "Deploy to Production"). Afterwards `https://agentx-platform.fly.dev/agents/top` should load
  (not an error). Safety net: Neon snapshot `pre-reconciliation-2026-09-21`.
  Unblocks: every router enablement in production.

## Notes from DrJ

- 2026-09-30 (via resume note, recorded cycle 2): H1 is **not** done — production still runs
  the old build; `/agents/top`, `/activity`, `/search` return 500. Keep H1 open.
- 2026-10-01 (via resume note, recorded cycle 2): add post rate limits / max length,
  posts_count fix and a solicitation moderation path to Sprint 9 (now S9-8a/b/c); add H4.
  Future notes come through resume notes, not edits to this file.
