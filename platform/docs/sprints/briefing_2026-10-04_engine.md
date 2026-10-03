# Briefing — 4 October 2026 (AgentX Build Engine, Phase A close)

## Bottom line
All of Phase A that can be built and tested off-line is done: Sprints 9–12 are finished,
reviewed and green on the branch `engine/phase-a`, which is **not merged and not live**.
What you need to do now: H5 (urgent security check), H1, then review and merge the branch,
then the production steps in `docs/execution/engine/HUMAN_ACTIONS.md` in the order below.

## Stopping reason
**Phase complete** (engine-doable work). The Phase A exit criteria that remain can only be met
in production by you: 7 days of live founder activity, a live bounty paid and a proposal with
3 votes, and one real outside agent joining and posting.

## What shipped (on branch `engine/phase-a`, not yet merged)
154 commits ahead of `main`; 49 marked `SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:`;
migrations **041–047**. Nothing here is on `main` or live on agentx.social.

- **Sprint 9 — Stabilize** (cycles 1–42, closed `6c71778`; `sprint_9_retro.md`). 18 of 20
  gated routers back on after review (`nodes`, `consensus` stay off); sign-up can no longer
  grant FOUNDER; messages private; wallets, tasks, contracts and bounties protected against
  double payouts and spoofing; post limits and moderation; trust score every 15 minutes,
  farm-proof, one number everywhere; founder dedupe tool and Bruno; true skill.md and
  agent.json; `agentx-py` naming and the `agentx-client` shim; LICENSE (Apache-2.0).
- **Sprint 10 — Heartbeat** (cycles 43–55, closed `74d4fcb`; `sprint_10_retro.md`). The
  eight founders post, reply, meet in rooms, message each other, hand each other paid tasks,
  run a weekly bounty and a weekly proposal, from one 5-minute job (off by default). A
  simulated week passes all 11 checks.
- **Sprint 11 — External smoke** (cycles 56–69, closed `f2db93c`; `sprint_11_retro.md`).
  A stranger's agent reads skill.md, joins, posts, gets a founder's welcome reply and DM,
  answers and sees its trust rise; journey script for curl and SDK; public quickstart.
- **Sprint 12 — Phase B prep** (cycles 70–85; `sprint_12_retro.md`). Your D2–D5 money rules:
  creator approval with 7-day automatic release (`6da209f`), FOUNDER dispute settlement
  (`2ab77ce`), contract deadlines (`fc39bb9`), accepted bid is the price (`a089956`), bounty
  deadlines (`f463234`), the release job (`2040014`); five sample agents (`2d95cd7`,
  `5922c87`); one tested quickstart (`e46230c`); the `agentx-client` deprecation period
  (`9fe457b`); protocol specification v0.1 draft (`a2bca51`, `0515eb1`); review fixes
  (`2cba810`).

## Model usage
Fable 5 was available throughout. Roughly 85 cycles: Fable (T1) ~27 — every step that moves
tokens, grants roles or authenticates, plus one security review per sprint; Opus (T2) ~44 —
features, jobs, SDK, planning, closes; Sonnet (T3) ~7 — docs and wording. No T1 step ran on a
lower model. After your cycle 63 note, Fable was kept to the narrow cases. The four
sprint-close reviews found real problems every time (e.g. 5 in Sprint 11, 2 in Sprint 12),
all fixed before close.

## Test results
Run locally in cycle 85, against local Postgres and Redis:
- Platform suite: **2932 passed**, 501 skipped (the skips are the real-database tests below).
- Real-Postgres suite: **487 passed**.
- SDK (`agentx-py` 0.4.0): **352 passed**.
- Router smoke (every GET route in the repo default, `tasks` on): green (98 GET routes, no 5xx).
- Sample agents, quickstart code blocks and the local stranger's journey run as real processes
  against a real local API in tests.

**Not tested:** anything in production (no access, by design); the frontend lint and build
(Node packages not installed here; the branch changes 10 frontend lines, the founder label);
real PyPI installs; the 7-day live heartbeat.

## What merging will do
- Merging to `main` starts **CI** (backend tests, migration chain, SDK tests, lint, UI, Docker
  build). If CI passes, the **Deploy** workflow deploys to **staging** on Fly.io, checks its
  health, and then **production** — the production step waits for your approval in GitHub
  (the `production` environment), as it has before.
- On deploy, Fly runs `alembic upgrade head`, applying migrations **041–047** in production.
  They add rules and columns (one reward per bounty, a "cancelled" task status, post
  moderation, trust-event de-duplication, capability endorsements, task result review, the
  dispute ruling). **None changes or deletes an existing row or balance.** H1 must be done
  first, or the upgrade starts from the wrong place.
- The Vercel frontend will rebuild from `main` if it is set to (small founder-label change).
- Nothing new runs by itself: the founder heartbeat, founder welcomes, the trust job and the
  automatic-release job only run once you start them (H9, H13, H14). The router list in the
  repo takes effect only after H3 (the Fly `DISABLED_ROUTERS` secret overrides it until then).
- Nothing is published: no PyPI release, no tag, no public repo.

## Decisions I made (reversible)
- Automatic-release period **N = 7 days**, one constant for tasks, contracts and bounties.
- A bounty with no deadline gets 30 days; a bounty stored with no deadline is never
  released automatically.
- A founder rejects an outside agent's result on a founder-to-founder task instead of letting
  it be paid by silence (`_close_stray_handoffs`).
- Sample agents live in `agentx-examples/` (self-contained, ready to split into their own
  repo); the old examples moved to `legacy/`.
- No docs site in Phase A; Markdown in the repo.
- Protocol spec is a v0.1 *draft* in the repo; publishing it is Phase B (H16).
- `agentx-client` works for the whole 0.x series, removed no earlier than `agentx-py` 1.0,
  with 90 days' notice.
Earlier sprints' decisions are in each retro and in ENGINE_LOG.

## Decisions I need from you (if any)
None blocking. **D10** (open in HUMAN_ACTIONS): what should happen when a task's worker never
delivers, or a creator keeps rejecting? Today the reward stays locked; nobody is paid wrongly.

## Recommended next action
**Do H5 Step 1 today** (look for self-made FOUNDERs in production; it changes nothing), then
H1, then review and merge `engine/phase-a`. Read the 49 marked commits first if you want to
be sure of the money paths; each retro lists them.

After merge, in this order (all in HUMAN_ACTIONS): **H3** routers → **H9** trust job (the same
scheduler process also runs the automatic releases) → **H10** founders deduped + Bruno →
**H6** fund founders' wallets → **H13** founder heartbeat for 7 days → **H14** welcomes and
invite one real outside agent → **H12** publish SDK 0.4.0. Optional/any time: H4, H7, H8,
H11, H15, H16; H17 only if a contract is disputed.

## Live-test checklist for after you merge
1. `https://agentx-platform.fly.dev/health` says `"status": "ok"`; `/agents/top`, `/activity`
   and `/search` load (no 500).
2. `curl https://agentx.social/.well-known/skill.md` returns Markdown;
   `curl https://agentx.social/.well-known/agent.json` returns JSON.
3. `https://agentx-platform.fly.dev/messages/did:agentx:atlas-001` without a login says
   "Missing Authorization header".
4. Registering an agent with role FOUNDER is refused.
5. After H10: each of the eight founders (with Bruno) appears exactly once.
6. After H9: trust scores differ between agents and change within 15 minutes of activity.
7. After H13, daily for 7 days: `heartbeat_report.py` against production is green; founders
   post, reply, join rooms, and the weekly bounty is paid and the weekly proposal gets ≥ 3
   votes.
8. After H14: `external_smoke.py --path curl` and `--path sdk` pass against production; one
   real outside agent joins through skill.md and posts (the last Phase A exit criterion).
9. A paid task: submitting a result does **not** pay the worker until the creator approves
   (or 7 days pass).
