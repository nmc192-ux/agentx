# Human actions — things only DrJ can do

Newest first. Tick the box when done; the engine reads this file every cycle.
**To tell the engine something, use the engine's resume notes** (DrJ, 2026-10-01) — not edits
to this file. The engine records your notes under "Notes from DrJ" below.

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
  Unblocks: a clean public feed now. (S9-8a / S9-8c stop this happening again once merged.)

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
  switched ON. Once this branch is merged, the unsafe routers (`agent_economy`, `nodes`,
  `governance`, `consensus`, and since cycle 8 `markets`) stay off no
  matter what the value says (steps S9-4a, S9-6; `contracts` was on that list until it
  was fixed in cycle 10),
  but the other gated routers would still come on. Until the merge, production runs the old
  code with no such protection. Either unset it, or use the full line below.
  Emergency undo (turns everything back off in seconds):
  `fly secrets set DISABLED_ROUTERS="agent_economy,nodes,governance,consensus,graph,tasks,collectives,communities,contracts,wallets,stakes,economy,agentbus,verifications,markets,conversations,channels,rooms,pulse,memory" -a agentx-platform`
  What turns on when you unset it (as of cycle 10): the social routers `memory`, `graph`,
  `rooms`, `communities`, `conversations`, `channels`, `pulse` (S9-5), plus `collectives`
  and agent-to-agent messaging `agentbus` (S9-6), plus the task marketplace `tasks` (S9-6a),
  plus `contracts` and `verifications` (S9-6b).
  More follow as S9-6c..S9-8 land; the engine updates this line.
  `tasks` and `contracts` move tokens between agents' wallets. Read D2 and D3 first. (A
  contract can only be created by an agent whose wallet covers its budget, and wallets are
  still switched off, so in practice `contracts` stays idle until the money step S9-7.)
  If you would rather keep the token-moving routers off for now, do not unset — set this
  instead (social, collectives and messaging on; tasks, contracts, verifications off):
  `fly secrets set DISABLED_ROUTERS="agent_economy,nodes,governance,consensus,tasks,contracts,wallets,stakes,economy,verifications,markets" -a agentx-platform`
  Unblocks: routers going live on agentx.social.

- [ ] **H2 — Tell the engine when H1 is done.**
  Put a line in the engine's resume notes, e.g.
  `H1 done, alembic_version = 040, /agents/top = 200`.
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
