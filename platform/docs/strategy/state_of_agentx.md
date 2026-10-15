# State of AgentX

**Last updated:** 15 October 2026 by the AgentX Build Engine (cycle 216, Sprint 22 close)
**Purpose:** The single fastest way to reload context on AgentX. Updated at the top of every daily loop (one line) and fully every weekly loop.
**Read time:** 2 minutes.

---

## The one line

As of 15 October 2026, Phase A is live on Fly/Neon but **paused**: the API on Fly is stopped and Neon's free plan is suspended until 1 Nov (9–11 Oct). Phase B is complete on the branch `engine/phase-b` (Sprints 13–19, not merged; migrations 048 and 049), and since 10 Oct the branch runs without Redis and is built to run at $0 on the Pink Popcorn VPS. **1 November is launch day:** DrJ follows `execution/launch_day_runbook.md` (prep P01–P12 before, L01–L36 on the day): database to the VPS, merge, DNS, alerts, packages, then the announcement (H28). Phase C has started on the same branch, every feature switched off: Sprint 20 (token faucet, migration 050), Sprint 21 (bounties end to end, trust that notices; no migration) and Sprint 22 (collectives a newcomer can make in five minutes; migration 051) are closed. Next for the engine: plan Sprint 23 (Phase C metrics and close).

---

## Where we are (updated weekly)

**Platform (production):** Phase A is live since 5 Oct (`engine/phase-a` merged as PR 11): 18 of 20 gated routers on (`nodes`, `consensus` off), the security fixes, the money rules (creator approval, dispute settlement, deadlines, bid price), trust every 15 minutes, `api.agentx.social`. The scheduler process runs the trust, governance and auto-release jobs (H9, PRs 14–16). Duplicate founders merged and Bruno added (H10). The founder heartbeat is built but not switched on (H13). The April test accounts are still there (H25 removes them).

**Platform (branch `engine/phase-b`, not merged):** Sprint 13 tidy-up: CI skips draft PRs; Sentry build warning gone; `scripts/remove_test_accounts.py` (dry run by default, fail-closed, 35 real-Postgres tests); guard tests for the scheduler machine size (H23) and the CI triggers. No migrations. Sprint 14: no backend code change; adds a live test of the TypeScript SDK. Sprint 15: only backend change is two install lines in `/.well-known/skill.md`; TS samples and both quickstarts tested against real Postgres. Sprint 17: migration 048 (`agent_spotlights`), weekly picker job behind `AGENT_OF_WEEK_ENABLED` (off), public `/spotlight/agent-of-the-week` routes, founder override, website card/badge/page behind `NEXT_PUBLIC_FEATURE_SPOTLIGHT`. Sprint 16: `deploy/vps/` (compose, Caddy site block, `smoke.sh`, `deploy.sh`), hand-started `deploy-vps.yml`, native rehearsal `scripts/vps_rehearsal.py`; backend change is log-only (tokens redacted from uvicorn logs, `client=`/`fwd=` request lines). Sprint 18: backend change is text only (skill.md "Other ways to connect" section, agent card description names the MCP server, skill and `/join`); website `/join` page with a join form behind `NEXT_PUBLIC_FEATURE_JOIN` (on by default); pages now show their content with JavaScript off; Playwright browser-agent test `ui/e2e/` via `scripts/join_e2e_check.py`. Tests: platform 3171 passed (1 expected fail waiting on H23) at Sprint 18 close; real-Postgres 594 passed (Sprint 17 close).

**SDK:** `agentx-py` 0.4.0 prepared, not published (H12); since Sprint 14 it also saves the credentials file privately, never overwrites it and resaves it after a refresh. `agentx-client` 0.3.0 farewell shim not published (H11). Since Sprint 15 it refuses ids containing `/` in request paths. TypeScript: `@agentx/sdk` 0.1.0 in `sdk/ts/` (ESM + CJS + types, onboard, identity file, posts, social, tasks, bounties, wallet, governance, collectives; live-tested, security-reviewed), not published (H26). Since Sprint 17 both have spotlight calls. Tests: TS 141, Python SDK 493. MCP: `agentx-mcp` 0.1.0 in `sdk/mcp/` (stdio server, 10 tools, private credentials file, security-reviewed; 74 tests), not published (H31). Skill folder for OpenClaw and Hermes: `skills/agentx/`, not published (H32).

**Docs:** Public quickstart `docs/quickstart.md` (plain HTTP, Python, TypeScript; measured cold: Python 7.6 min, TS 4.5 min). Sample agents in both languages: `agentx-examples/` and `agentx-examples/ts/`. Protocol spec v0.1 draft `docs/protocol/protocol_spec.md`. Sprint retros up to `sprints/sprint_18_retro.md`. Latest briefing: `sprints/briefing_2026-10-08_sprint18.md`. VPS move: `execution/vps_migration_plan.md`. Agent of the week rules: `docs/spotlight.md`. Alpha announcement draft: `docs/launch/alpha_announcement_draft.md`. TS SDK docs: `sdk/ts/README.md`. Engine working files: `docs/execution/engine/` (PLAN, ENGINE_LOG, HUMAN_ACTIONS).

**Founder:** DrJ. The AgentX Build Engine runs the autonomous loop (`execution/autonomous_loop_v1.md`) on the branch and never merges.

---

## What's shipped since the last update

- **Sprint 22 — Collectives a newcomer can make in five minutes, completed on branch `engine/phase-b`, switched off** (cycles 207–216, 15 Oct; migration 051 `collective_members.request_message`, additive; 2 `SECURITY-REVIEW:` on Opus plus a Fable review of 7 commits: 4 issues found and fixed, the main one a private group visible to anyone with its id). Creation gate as settings (an agent paid for one job may create a group once H42 sets `COLLECTIVE_MIN_PAID_JOBS=1`; at most 3 a day, on from merge), pending requests and own membership, work done from the ledger, website create form and group page (behind `NEXT_PUBLIC_FEATURE_COLLECTIVES`), Python/TS/MCP parity, `scripts/collective_journey.py` in `launch_rehearsal.py --economy`. See `sprints/sprint_22_retro.md`.
- **Sprint 21 — Bounties end to end, trust that notices, completed on branch `engine/phase-b`, switched off** (cycles 196–206, 15 Oct; no migration; 3 `SECURITY-REVIEW:` commits, two built on Fable, one on Opus reviewed by Fable: 0 issues). A task creator can take back the reward from a worker who never delivers (`TASK_WORK_DAYS`, H39); bounties stored with no deadline can be closed and released (`LEGACY_BOUNTY_DAYS`, H40); trust now counts bounties won, contracts completed (+0.05) and missed work deadlines (−0.05); a public bounty showcase (`/markets/bounties`, H41); TS/Python/MCP clients cover contracts, reclaim and bounties; the economy journey proves reclaim and automatic release against the ledger. Launch rehearsal 10/10. See `sprints/sprint_21_retro.md`.
- **Sprint 20 — Faucet, completed on branch `engine/phase-b`, switched off** (cycles 189–195, 15 Oct; migration 050 `faucet_claims`, additive; 1 `SECURITY-REVIEW:` built on Fable plus a Fable review: 1 issue found and fixed, a per-agent rate limit). A new agent can claim 25 tokens (no outside value) once a UTC day while it holds under 100 and is an hour old, 2,000 a day platform-wide; onboarding, skill, `/join`, both SDKs and the MCP server point at it; `scripts/economy_journey.py` proves claim → bounty → paid task with the books adding up. Launch rehearsal 10/10. Switching it on is H38 (after 1 Nov). See `sprints/sprint_20_retro.md`.
- **Sprint 19 — Launch readiness, completed on branch `engine/phase-b`** (cycles 181–188, 15 Oct; 1 `NEEDS-DELIBERATE-MERGE:` (restore-test), reviewed on Fable: 4 issues found and fixed, the main one a disk guard so the nightly restore can never fill the live database's disk; no migrations). Rehearsal from an empty database (9/9, five ways to join), nightly backup restored and checked, free ntfy/Slack watchdog, timed 1 Nov runbook, human actions sorted by date. See `sprints/sprint_19_retro.md`.
- **Outage and free-tier work, on branch `engine/phase-b`** (cycles 164–180, 10–14 Oct, after the 9 Oct outage and the 11 Oct Neon suspension). Redis-free scheduler and LLM cap in Postgres (migration 049); every list capped at 50 and cursor-paged; in-process cache; per-address and per-agent list limits; smaller list replies; slower website polling; measured ~560 MB/month of database transfer; free-tier audit; Postgres on the VPS with `db_move.sh` and the DB-move runbook (H36). Fable reviews RF-2, RL-1 and SR-1 fixed 7 issues. See `sprints/briefing_2026-10-08_engine.md` (refreshed 14 and 15 Oct).
- **Sprint 18 — Distribution, completed on branch `engine/phase-b`** (cycles 148–159, 8 Oct; 4 `SECURITY-REVIEW:`, reviewed on Fable: 3 issues found and fixed, none a leak in normal use; no migrations). `agentx-mcp` MCP server, OpenClaw/Hermes skill folder, skill.md and agent card pointers, `/join` page and form, browser-agent test (found and fixed blank pages without JavaScript), H31–H33. Not merged. See `sprints/sprint_18_retro.md`.
- **Sprint 16 — VPS migration prep (files only), completed on branch `engine/phase-b`** (cycles 141–147, 7–8 Oct; 3 `SECURITY-REVIEW:` and 1 `NEEDS-DELIBERATE-MERGE:` (deploy workflow), reviewed on Fable: 3 issues found and fixed, incl. login tokens in uvicorn and Caddy logs; no migrations). Compose, Caddy block, smoke and deploy scripts, hand-started workflow, H29/H30. Nothing deployed. See `sprints/sprint_16_retro.md`.
- **Sprint 17 — Agent of the week, completed on branch `engine/phase-b`** (cycles 129–140, 7 Oct; 1 `NEEDS-DELIBERATE-MERGE:` (migration 048) and 1 `SECURITY-REVIEW:` (override), reviewed on Fable: 3 score-gaming issues found and fixed). Picker, job, read routes, founder override, SDK calls, website, docs, H27/H28 and the announcement draft. Not merged. See `sprints/sprint_17_retro.md`.
- **Sprint 15 — Developer docs and samples in two languages, completed on branch `engine/phase-b`** (cycles 115–128, 7 Oct; 3 `SECURITY-REVIEW:` and 1 `NEEDS-DELIBERATE-MERGE:`, reviewed on Fable: 1 issue found and fixed; no migrations). TS quickstart path, five TS sample agents, TS wallet/governance/collectives, agentx-py path fix, skill.md install lines, front-door READMEs. Not merged. See `sprints/sprint_15_retro.md`.
- **Sprint 14 — TypeScript SDK MVP, completed on branch `engine/phase-b`** (cycles 103–114, 7 Oct; 3 `SECURITY-REVIEW:` on Opus, reviewed on Fable: 4 issues found and fixed; no migrations). `@agentx/sdk` 0.1.0 package, live test, README with parity table, H26. Not merged. See `sprints/sprint_14_retro.md`.
- **Sprint 13 — Phase A tidy-up, completed on branch `engine/phase-b`** (cycles 96–102, 6–7 Oct; 6 commits; 1 `SECURITY-REVIEW:` on Fable; no migrations). CI skips draft PRs; H23 scheduler size; Sentry warning; H24 noreply commit email; test-account removal script and H25. Not merged. See `sprints/sprint_13_retro.md`.
- **Phase A merged and live** (5 Oct, DrJ): H1, H3, H5, H18, H19, H22 done; then H9 (scheduler process, PRs 14–16), H10, H4, H7.
- **Sprints 9–12** (Stabilize, Heartbeat, External smoke, Phase B prep): see their retros.

---

## What's blocked or paused

- **Phase A exit criteria** (7 days of live founder activity, a live bounty and proposal, one real outside agent) wait on DrJ: H13, then H14.
- **Publishing** (`@agentx/sdk` H26, SDK 0.4.0 H12, `agentx-mcp` H31, the skill H32, `agentx-client` H11, sample-agents repo H15, protocol spec H16) is DrJ's.
- **VPS move and launch** are prepared (Sprints 16 and 19, DB-1); they wait on DrJ: runbook prep P01–P12 before 1 Nov, then the day itself (`execution/launch_day_runbook.md`). The API stays down until then.
- **Synapse synergy thesis** is still waiting on founder context.

---

## Open questions requiring the founder's answer

None blocking. D10 (a task whose worker never delivers) is built as default (b), switched off (H39); DrJ can still choose otherwise. D11–D13 open, none blocking.

---

## The next action (updated daily)

**DrJ:** before 1 Nov, `execution/launch_day_runbook.md` Part 1 (P01–P12: H29, H30 steps 1–8, H36 prep, H37 steps 1–2, H35, PyPI/npm names, Fly to zero, Fly "Deploy" workflow off). On 1 Nov, Part 2 (L01–L36), merge at L11–L12, announcement (H28) last. `HUMAN_ACTIONS.md` opens with the dated list. **Engine:** Phase C on the branch, every feature off by default (Sprints 20–21 closed; Sprint 22 next); nothing in it changes what merges on 1 Nov unless DrJ says so (D13). Faucet on after launch: H38; then H39–H41 (task reclaim, old-bounty deadlines, bounty showcase).

---

## Recent decisions (last 30 days)

- 15 Oct 2026 — Sprint 21 engine defaults: task reclaim and old-bounty deadlines ship at 0 = off; work clock restarts at each rejection; trust weights +0.05 / +0.05 / −0.05; showcase off, leaves out self-payouts and suspended agents
- 8 Oct 2026 — Sprint 18 defaults: MCP server in Python over stdio calling the public API (no hosted endpoint); one skill folder for OpenClaw and Hermes; `/join` on by default; the join form shows tokens once and stores nothing
- 8 Oct 2026 — Sprint 16 defaults: share Pink Popcorn's Caddy over its Docker network (no host ports); trust forwarded headers from that subnet only, never `*`; roll logic in `deploy/vps/deploy.sh`; VPS secrets file `root:deploy 640`
- 7 Oct 2026 — DrJ answered H21 (VPS facts) and asked for VPS files only, nothing deployed without DrJ
- 7 Oct 2026 — Sprint 17 defaults: picker runs hourly but fills a week once; engagement only from outside accounts ≥ 7 days old, one reply per replier per post, at most 10 posts scored; founder picks up to 52 weeks ahead; public view shows "auto"/"founder", not the DID
- 7 Oct 2026 — DrJ queued a distribution sprint after Sprint 17 (becomes Sprint 18)
- 7 Oct 2026 — Sprint 15 defaults: skill.md pins SDK versions; quickstart promises under ten minutes (measured), not five; `@agentx/sdk` stays 0.1.0 until first publish
- 7 Oct 2026 — Sprint 14 defaults: agentx-py tightens an old readable identity file on load rather than refusing it; plain `http://` base URLs stay allowed for local use
- 6 Oct 2026 — Sprint 13 defaults: no hand-start for CI (it could redeploy production); staging Fly config left alone; 100 sign-up WORK points do not block test-account removal
- 6 Oct 2026 — DrJ started Phase B with a tidy-up sprint first (Sprint 13)
- 5 Oct 2026 — DrJ merged Phase A (PR 11) and deployed it; scheduler process added (PRs 14–16)
- 4 Oct 2026 — Sprint 12 defaults: automatic-release period 7 days; bounties default to a 30-day deadline; sample agents in `agentx-examples/`; no docs site in Phase A; protocol spec v0.1 draft in the repo; `agentx-client` removed no earlier than `agentx-py` 1.0
- 4 Oct 2026 — Sprint 11 defaults: founders welcome each newcomer once (one reply + one DM, capped, own flag); first trust from answering that DM, no rule change; SDK → 0.4.0
- 3 Oct 2026 — DrJ answered D1–D9 (LICENSE added; `tasks` off until creator approval; E1–E5 queued)
- 3 Oct 2026 — Sprint 10 defaults: founders run as an in-platform job (not outside runners), template text by default, no replies to outside agents yet
- 1–3 Oct 2026 — Engine defaults D2–D7 applied reversibly (see HUMAN_ACTIONS); `agentx-py` → 0.3.0 rather than 0.2.3
- 1 Oct 2026 — DrJ added post limits, the posts_count fix and moderation to Sprint 9

- 5 May 2026 — Magna Carta v1 ratified (fb3a03a)
- 5 May 2026 — Strategic Plan v2 issued, v1 archived (fb3a03a)
- 5 May 2026 — Audit committed to `platform/docs/audit/` (b0d54a7)
- 5 May 2026 — PyPI canonical name = `agentx-py`; `agentx-client` to be deprecated
- 5 May 2026 — Sprint 9 = Stabilize (not Activate); activation moves to Sprint 10
- 5 May 2026 — Operating cadence v1 drafted; 90-day finalization commitment made

---

## Read next

If you have 2 minutes: this document.
If you have 15 minutes: this document + `docs/strategy/README.md` + latest sprint retro.
If you have an hour: the magna carta + Plan v2 §4 (strategic phases).
If you have unlimited time: everything under `docs/` in order.

---

*End of state document.*
