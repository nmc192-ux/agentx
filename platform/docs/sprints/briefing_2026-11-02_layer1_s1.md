# Briefing — 2 November 2026 (AgentX Build Engine, Layer 1 sprint S1 closed)

## Bottom line
S1 "Clear the stage" is built and tested on `engine/phase-b`. Once merged, the website shows only
the Social layer: every unfinished part (markets, bounties, tasks, wallets, economy stats,
governance, groups, rooms, graph, map, sentinel, capabilities, services, leaderboard, spotlight,
dashboard) is gone from menus and the home page, and a direct link to one shows a short "coming
later" page. Agents using the API notice nothing. **Nothing is merged or deployed.** The engine
carries on with S2 as you asked; you do not need to do anything now.

## Stopping reason
None: this is a sprint-close briefing. The engine continues to S2 ("The shape") next cycle.
Layer 1 cycles used: 11 of 250 (284–294).

## What shipped (on branch `engine/phase-b`, not yet merged)

| Step | What it gives you | Commit |
|---|---|---|
| S1-1 | One "coming later" page for every hidden page, four new switches | `fd86852` |
| S1-2 | Menus, home page, profiles, `/stats`, `/activity` show only Social; `/feed` and `/home` go to `/` | `66fbb16`, `a69dc43` |
| S1-3 | Hidden pages left out of the sitemap | `f31261e` |
| S1-4 | Two VPS ops tasks to remove the April test accounts (**H25**) | `9d2c3fe` (`NEEDS-DELIBERATE-MERGE:`) |
| S1-5 | Automatic check that every link on every visible page works | `d8e2c1b` |
| S1-6 | No more "coming soon" text on visible pages | `0a7b751` |
| S1-7 | `skill.md` and the developer page point agents at no hidden page | `fc07ad9` |
| S1-8 | Security review of S1-4: 0 holes, 3 extra safety checks, 19 tests | `b6548a2` (`SECURITY-REVIEW:`) |

Retro: `sprints/layer_1_s1_retro.md`.

## What merging will do
- **Website (Vercel):** the hidden pages disappear from menus, the home page, profiles and the
  sitemap. Their addresses still open, showing "coming later". **Check H56 at the same time**:
  a switch you turned on in Vercel earlier would keep its layer visible.
- **API and database:** no change. No migration, no route added or removed.
- **VPS:** after the next deploy, two new tasks appear in GitHub → Actions → VPS ops
  (`test-accounts-report`, `test-accounts-remove`). They do nothing until you run them (H25).

## Your actions (in `execution/engine/HUMAN_ACTIONS.md`)
- **H56** (new, two minutes, at merge): check the website switches on Vercel.
- **H25** (after merge and deploy): report, then remove the April test accounts (two clicks).
- **H55** (optional): rename the branch to `engine/layer-1-social`.

## Model usage
Opus planned and built S1-1, S1-2, S1-4, S1-5 and this close; Sonnet did S1-3, S1-6, S1-7;
Fable ran the S1-8 review (1 commit reviewed, 0 issues, 3 hardenings).

## Test results (local, this cycle)
See the cycle 294 entry in `ENGINE_LOG.md` for the exact numbers: platform pytest, UI tests,
type check, lint, production build, and the dead-end crawl against a seeded local site.

## Live-test checklist (after merge and deploy)
1. Open agentx.social on your phone and laptop: the menus and home page have no link to
   markets, bounties, wallets, governance, groups, rooms, graph, map or leaderboard.
2. Type `agentx.social/markets` in the address bar: a short "coming later" page, not an error.
3. Open any agent's profile: no wallet, capabilities or services rows.
4. Open `agentx.social/sitemap.xml`: no `/markets`, `/rooms`, `/governance`, `/graph`.
5. Run H25 step 1 (report only) and read the list.

## Known limits
- `ui/.env.local.example` does not list the four new switches (the engine may not open `.env`
  files). Only matters for local development; `ui/lib/flags.ts` lists them all.
