# Layer 1 (Social), Sprint S1 "Clear the stage": Retro (engine run)

**Sprint:** S1 of `sprints/layer_1_social_plan.md` (DrJ, 1 Nov 2026)
**Dates:** 2026-11-01 to 2026-11-02, engine cycles 284–294
**Branch:** `engine/phase-b` (H55 renames it, optional). **Not merged.** At this close the branch is
18 commits ahead of `origin/main` (`9d6afbe`), 2 of them marked: `9d2c3fe`
(`NEEDS-DELIBERATE-MERGE:`, S1-4) and `b6548a2` (`SECURITY-REVIEW:`, S1-8). **No migration. No API
route changed** (`platform/src` routers untouched; checked in S1-7). Nothing touches money,
wallets, permissions or auth.
**Step list:** `docs/execution/engine/PLAN.md` (S1-0 to S1-9). **Per-cycle record:**
`docs/execution/engine/ENGINE_LOG.md`. **Briefing for DrJ:** `sprints/briefing_2026-11-02_layer1_s1.md`.

## What was intended

Show only Layer 1 (Social) on the website: every unfinished layer hidden from menus and the home
page behind a default-off flag, a direct link to a hidden page shows a short "coming later" page
(not a redirect, never a broken page), the API unchanged; a two-click way for DrJ to remove the
April test accounts; no dead links or buttons; every empty state true.

## What shipped (on the branch)

- **S1-1 "Coming later" page and layer flags** (`fd86852`). Four new flags (`ROOMS`,
  `LEADERBOARD`, `CAPABILITIES`, `SERVICES`); tasks, wallets, dashboard and economy stats under
  `ECONOMY`; communities under `COLLECTIVES`; graph and map under `CONSTELLATION`. Every hidden
  route, including `[id]` sub-routes, renders one `ComingLater` component (HTTP 200) instead of
  redirecting to `/`.
- **S1-2a/b Menus, home and profile** (`66fbb16`, `a69dc43`). Sidebar, top bar, footer, command
  palette and the Live Pulse box only list visible pages; profiles drop the capabilities and
  services rows and skip their API calls; `/stats` drops hidden-layer tiles; `/activity` shows
  only posts while the economy is off; `/feed` and `/home` go to `/`.
- **S1-3 Sitemap** (`f31261e`). Hidden pages are not in `sitemap.xml`.
- **S1-4 Test-account removal as VPS ops tasks** (`9d2c3fe`, `NEEDS-DELIBERATE-MERGE:`).
  `test-accounts-report` (show + dry run, keeps the exact address list on the VPS for 24 h) and
  `test-accounts-remove` (backup, then removes only those addresses). The reviewed script itself
  is unchanged. H25 rewritten as two clicks.
- **S1-5 Dead-end crawl** (`d8e2c1b`). `ui/e2e/dead_ends.spec.ts` follows every internal link from
  every visible page on a seeded local site; a source test checks every button has a handler.
  Nothing to fix (26 pages clean); a planted `/rooms` and a 404 were both caught.
- **S1-6 Truthful empty states** (`0a7b751`). Five "coming soon" lines reworded; a test keeps
  them out of visible pages.
- **S1-7 Agent-first check** (`fc07ad9`). `skill.md` and the developer page send agents to no
  hidden page; a test keeps it so.
- **S1-8 Security review** (`b6548a2`). 1 commit reviewed, 0 exploitable holes, 3 fail-closed
  hardenings, 19 adversarial tests.

## Acceptance (run locally at close, cycle 294)

| # | Criterion | Result |
|---|---|---|
| 1 | Unfinished layers hidden from menus and home, each behind a default-off flag | Met. Nav-list and layer tests pass with all flags off. |
| 2 | Direct URL to a hidden page shows "coming later" (200), API routes unchanged | Met. Route-gate test; `platform/src` diff empty. |
| 3 | VPS ops tasks for the April test accounts; H25 rewritten | Met (built and reviewed). **Running them is DrJ's (H25)**, after merge and deploy. |
| 4 | Zero dead ends; true empty states | Met. Crawl passed; no "coming soon" on visible pages. |
| 5 | Existing tests keep passing | Met. See numbers in the cycle 294 log entry. |

## What went well

- Small steps, each with its own guard test, so later sprints cannot quietly undo S1 (nav lists,
  sitemap, buttons, placeholders, agent-first links all have tests).
- The crawl was proven to fail before it was trusted to pass.
- The test-account tasks keep the workflow's "no free-text input" rule by carrying the dry run's
  own address list, which is stricter than a typed count.

## What didn't

- `ui/.env.local.example` still does not list the four new flags: the engine's file guard will not
  open it (it matches `.env*`). `lib/flags.ts` documents every flag instead. Low impact: the
  example file is only for local development.
- Production flags live in the Vercel project, outside the repo. If any `NEXT_PUBLIC_FEATURE_*`
  (other than `JOIN`) was switched on there earlier, that layer stays
  visible after merge. Recorded as **H56** (a two-minute check).
- The first full pytest run of this cycle used the wrong Python (no `python` on PATH outside the
  venv); rerun with `platform/.venv`.

## Decisions I made (reversible)

- Built on `engine/phase-b` (identical to `main` at the start) instead of a new branch (H55).
- Test-account removal confirmed by the report's address list, not a typed count (S1-4).
- Buttons checked in the source, not by clicking in the crawl (S1-5).
- `/trending`, `/tags`, `/explore`, `/activity`, `/stats`, `/welcome` kept as Social pages;
  `/feed` and `/home` redirect to `/` (S1-2b).

## Next

S2 "The shape" (app shell, Home Latest/Following, `@handles` with an additive migration, one post
card, profile/DMs/notifications in the shell). Decomposed into `PLAN.md` in the next cycle. Handles
are a T1 area (the plan names them for Fable).
