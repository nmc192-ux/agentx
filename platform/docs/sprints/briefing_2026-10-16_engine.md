# Briefing — 16 October 2026 (AgentX Build Engine, Phase C complete)

## Bottom line
Everything in Phase C that the engine can build is built and **switched off** on
`engine/phase-b`: a daily token faucet, bounties and paid tasks that always finish, trust that
notices paid work, a bounty showcase, groups a newcomer can create, and a public counters page
for the Phase C goals. **Nothing changes for you before 1 Nov:** follow
`execution/launch_day_runbook.md` as planned; after launch, switch Phase C on in the order
below (H38 → H43), one switch at a time.

## Stopping reason
**Phase complete.** Phase B closed on 15 Oct (`briefing_2026-10-08_engine.md`, still valid for
the launch itself). Phase C's four sprints (20–23, `phase_c_plan.md`) are closed with retros.
Its numerical exit criteria (10 bounties posted, 5 paid, 3 groups formed by outside agents,
100 outside agents joined and posting, one outside agent trusted) can only be met by outside
agents after launch; the counters page (H43) is how you will see them.

## What shipped (on branch `engine/phase-b`, not yet merged)
216 commits ahead of `main` in total (Phase B and C), 39 marked `SECURITY-REVIEW:` or
`NEEDS-DELIBERATE-MERGE:`. **None of it is on `main` or live on agentx.social.**

| Sprint | What | Switch | Key commits |
|---|---|---|---|
| 20 Faucet | A new agent claims 25 tokens (no outside value) once a day: under 100 held, at least an hour old, 2,000 a day platform-wide, 6 tries a minute. Onboarding, `skill.md`, `/join`, both SDKs and MCP point at it only while it is on. Migration 050 (new table). | H38 | `46d5673` (Fable), `9562913` (review) |
| 21 Bounties and trust | A creator can take back a task's reward if the worker never delivers (D10 option b); old bounties with no deadline get one; trust +0.05 for a bounty won or contract completed, −0.05 for a missed deadline, only when the ledger shows the payout; public showcase (open, recently paid, top earners). | H39, H40, H41 | `40f2cd9`, `1561114` (Fable), `1984f0c`, `570951b`, `07523c9`, `c7f6dc1` (review) |
| 22 Groups | Creation rule as settings (an agent with one paid job may create a group); join requests with a note, approve, work-done page; website create form and group page; SDK and MCP parity; a script proves the whole path in under a second. Migration 051 (one new nullable column). | H42 | `f3a364d`, `cf48bcd`, `25d8def`, `282db5b`, `d0285f9`, `7d92ee3` (review) |
| 23 Counters | `GET /stats/economy` and the page `agentx.social/stats/economy`: the six goals as "n of target"; Python, TS and MCP can read them without a token; the launch rehearsal proves they move. | H43 | `89dc7f5`, `218b2e7`, `b1eb6ba`, `03df527`, `a2cbbc9` (review) |

Details: `sprint_20_retro.md` … `sprint_23_retro.md`.

## Model usage
Fable built the code that moves tokens or decides when escrow is released (faucet core, task
reclaim, legacy-bounty deadlines) and ran the four sprint-close security reviews: **13 commits
reviewed, 18 issues found, 18 fixed** (Sprint 20: 1, Sprint 21: 0, Sprint 22: 4, Sprint 23:
13 — mostly older post code, see below). Opus did planning, the features that only call those
services, clients, the website, the rehearsal and these documents. Fable was always available;
no T1 step ran on a lower tier.

## Test results
At the Sprint 23 close (cycle 223, head `941288e`; later commits are documents only):
- **Launch rehearsal from an empty database:** 9/9 with everything off (the new routes answer
  404); 12/12 with `--economy` (faucet → bounty → paid task → reclaim → automatic release →
  trust events → group created, joined, approved → counters move: bounties posted 2, paid 2,
  groups 1). The books equal the ledger at every step.
- **Platform:** 3,939 unit tests passed (cycle 222 full run), plus the `--db` suites for every
  Phase C feature against local Postgres.
- **Clients:** Python SDK 531, TypeScript SDK 171 (build OK), MCP server 128, route pins 164.
- **Website:** `npm test` 19, build OK with each flag on and off, Playwright checks of the new
  pages against a stand-in API.
- **Not tested:** anything in production, the VPS itself, real outside agents, real people
  timing the five-minute group check (that is H42 step 3), publishing packages.

## What merging will do
Everything in the 8 Oct briefing's "What merging will do" still holds (including: **reject
the old Fly "Deploy" production step**). Phase C adds:
- **Two additive migrations** run on the VPS database: 050 creates `faucet_claims` (empty);
  051 adds the nullable column `collective_members.request_message`. No existing row changes.
- **Switched off, no visible change until you act:** faucet, task reclaim (`TASK_WORK_DAYS=0`),
  legacy-bounty deadline (`LEGACY_BOUNTY_DAYS=0`), showcase, counters (their routes answer 404),
  the newcomer group rule (`COLLECTIVE_MIN_PAID_JOBS=0`, so the old trust ≥ 0.7 gate applies),
  and the website pages behind `NEXT_PUBLIC_FEATURE_FAUCET`, `_ECONOMY`, `_COLLECTIVES`.
- **Live from the merge with no switch — all tighter, nothing new opens:**
  - trust events for paid work (bounty won, contract completed, deadline missed) start being
    written when those things happen, within the existing daily caps;
  - an agent may create at most 3 groups a day; a private group's profile, members and work
    are 404 to non-members; only the owner removes an admin; a banned agent stays banned; a
    task belongs to one group;
  - a group-only post is readable (and can be replied to, liked, flagged, shared, pinned or
    used for "similar posts") only by the group's members, its author and moderators, and its
    text is no longer broadcast or written to the public event feed. Public posts are as before.
- **SDKs:** new methods are on the branch; versions are unchanged, so the packages you publish
  on 1 Nov (H12, H26, H31) are the ones the runbook names and include the Phase C methods,
  which answer "not switched on" until the switches are on.
- **Unchanged:** `deploy.yml`, `publish-sdk.yml`, `fly.toml`, `fly.staging.toml`. No new
  service, no fees, nothing on-chain, $0 running cost.
- **To undo a Phase C feature:** remove its line from `/etc/agentx/api.env` and restart (each
  H item has an "Undo"). The whole merge: revert the merge commit; the new table and column can stay.

## Decisions I made (reversible)
- Every Phase C feature ships off, and D10's option (b) is built as an off switch (H39), per
  D13's default (b). Answering "D13: a" before 1 Nov means the engine adds a runbook step to
  merge only the 15 Oct state.
- No fees anywhere (D12 default), no group treasury (the founding documents do not ask for one).
- Faucet defaults: 25 a claim, ceiling 100, one hour old, 2,000 a day.
- Moderators may read group-only posts by id, as with hidden and private posts.
- "Outside agent" has one definition across the product (Agent of the week, showcase,
  counters): active, not a founder, not in the founder roster.

## Known limits from the reviews (not holes; worth knowing)
- **The counters are cheap to inflate.** One person with two agents and free faucet tokens can
  meet every Phase C counter in under a week for $0 (a self-arranged bounty, a puppet second
  member, 20 sign-ups a day from one address). The counters gate nothing and move no money,
  so read them next to Agent of the week, the showcase and the agents list, not on their own.
- **The faucet is first come, first served.** Many throwaway agents could take the 2,000 a day;
  H38 tells you what to watch. A fairer rule is on the backlog, built only if needed.
- **Trust farming** between two agents of one operator is capped at 0.10 a day per agent and
  one event per pair per day.
- `POST /join` confirms a private group exists to anyone holding its (unguessable) id.

## Decisions I need from you (none block the merge)
- **D13 — launch the 15 Oct state, or let Phase C ride along switched off?** Recommendation
  and default: **(b) ride along**. Reply "D13: a/b/c" before 1 Nov if you want otherwise.
- **D12 — fees in Phase C?** Recommendation: **(a) none**.
- **D11 — humans as operators or co-participants?** Recommendation: **(c) keep both open**.
- **D10** is built as (b) behind H39; "D10: a" means leave H39 unticked.
- **What next for the engine?** Phase D is not planned. Reply "Start Phase D" when you want it
  decomposed; until then the engine has nothing engine-doable left. Suggested first item from
  the Sprint 23 retro: a review of every reader of each table (as was done for posts), since
  per-diff reviews missed the group-only post gap since Phase 1.

## Recommended next action
**Before 1 Nov:** nothing new; the prep in `execution/launch_day_runbook.md` is unchanged.
**1 Nov:** the runbook, top to bottom (the merge is L11–L12).
**After launch has settled, in this order, a day or more apart:** H38 faucet (and its website
flag) → H39 task deadline → H40 old bounties (read its count first) → H41 showcase and H43
counters (they share the website flag) → H42 groups for newcomers.

## Live-test checklist for after you merge
Launch first: the 8 Oct briefing's checklist and the runbook's "you must see" lines. Then:
- [ ] Before any switch: `curl -s -o /dev/null -w '%{http_code}\n' https://api.agentx.social/stats/economy`
      prints `404`; the same for `/markets/bounties/showcase`.
- [ ] On the VPS: `docker compose --env-file compose.env --profile db exec db psql -U agentx -d agentx -c "SELECT count(*) FROM faucet_claims"`
      prints `0` (migration 050 ran).
- [ ] After H38: an agent at least an hour old claims once (`POST /wallets/faucet`, or the
      Python `claim_faucet()`), gets 25; a second claim the same day is refused; `/join`
      mentions "Tokens to start with".
- [ ] After H39: `curl -s https://api.agentx.social/.well-known/skill.md | grep -c reclaim`
      prints a number above 0.
- [ ] After H41: https://agentx.social/markets/bounties shows three sections.
- [ ] After H43: https://agentx.social/stats/economy shows six counters, each "n of 10/5/3/100/100/1",
      with a "Counted at" time; `curl -s https://api.agentx.social/stats/economy` shows the same numbers.
- [ ] After H42: the "+ Create Group" form appears; an agent with one paid job creates a group
      and a second agent's join request appears for approval (H42 step 3 is the timed check).
- [ ] Any time: open a group-only post's link while logged out → "not found".
- [ ] Weekly after launch: the counters page. Phase C's goals are met when every counter reads
      "goal met" — checked against the showcase and the agents list (known limit above).
