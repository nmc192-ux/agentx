# Human actions — things only DrJ can do

Newest first. Tick the box when done; the engine reads this file every cycle.
**To tell the engine something, use the engine's resume notes** (DrJ, 2026-10-01) — not edits
to this file. The engine records your notes under "Notes from DrJ" below.

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
  `governance`, `consensus`) stay off no matter what the value says (step S9-4a),
  but the other gated routers would still come on. Until the merge, production runs the old
  code with no such protection. Either unset it, or use the full line below.
  Emergency undo (turns everything back off in seconds):
  `fly secrets set DISABLED_ROUTERS="agent_economy,nodes,governance,consensus,graph,tasks,collectives,communities,contracts,wallets,stakes,economy,agentbus,verifications,markets,conversations,channels,rooms,pulse,memory" -a agentx-platform`
  What turns on when you unset it (as of cycle 7): the social routers `memory`, `graph`,
  `rooms`, `communities`, `conversations`, `channels`, `pulse` (S9-5). More follow as
  S9-6..S9-8 land; the engine updates this line.
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
