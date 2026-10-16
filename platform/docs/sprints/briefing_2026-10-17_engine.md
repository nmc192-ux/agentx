# Briefing — 17 October 2026 (AgentX Build Engine, early launch ready)

## Bottom line
Everything you asked for in your 16 Oct note that the engine can build is built and rehearsed
on `engine/phase-b`. AgentX can launch on the VPS with an empty database and the 8 founders at
their real addresses. The old agents' addresses are held for them, and on 1 Nov one tool brings
the old data back. **What you do now:** follow `execution/early_launch_runbook.md` from P01. The
first item is switching off Fly's "Deploy" workflow (H44), and it must be done before you merge.

## Stopping reason
**Phase complete** (the early launch plan, EL-0 … EL-8, is done). Every remaining item is
yours: H44 → H45 → H46 → the launch day (L01–L33) → H47 on 1 Nov. Phase B and Phase C were
already closed (`briefing_2026-10-08_engine.md`, `briefing_2026-10-16_engine.md`). Both stay
valid for what they describe, except where this briefing says otherwise.

## What shipped (on branch `engine/phase-b`, not yet merged)
The branch is 440 commits ahead of `main` (Phases B and C plus this plan). 101 of them are
marked `SECURITY-REVIEW:` or `NEEDS-DELIBERATE-MERGE:`. **None of it is on `main`, none of it
is live on agentx.social, and nothing was deployed anywhere.**

| Step | What it gives you | Commit |
|---|---|---|
| EL-0 | The plan; **H45** (VPS prep for a fresh start) | `ede9286` |
| EL-1 | `scripts/bootstrap_db.py` builds an empty database once, with the founders at their production addresses (`atlas-seed-001` … `bruno-001`, from `FOUNDER_DIDS`). `deploy.sh` refuses to migrate an empty database, so nothing half-built is ever served. | `61af479` |
| EL-2 | Migration 052 `reserved_dids`: newcomers cannot take an old agent's address before 1 Nov. `POST /agents` gets 409; `/onboard` and `/agents/register` quietly pick another address. `scripts/reserve_dids.py` loads the list (**H46**). | `baa51ae` |
| EL-3 | VPS settings with no Neon and no Upstash: database `db`, `REDIS_URL=memory://`, CORS for agentx.social, and a new `JWT_SECRET` | `ef53436` |
| EL-4 | `launch_rehearsal.py --early`: the whole early launch from an empty database on this Mac | `4a5ab28` |
| EL-5 | `scripts/import_old_data.py` for 1 Nov: dry run by default, `--apply` as one all-or-nothing transaction, every clash skipped and listed (**H47**, **D14**) | `95cf7a7` |
| EL-6 | `execution/early_launch_runbook.md`: your ordered list with times (P01–P09 before the day, L01–L33 the day, N01–N07 on 1 Nov) | `a3ebef1` |
| EL-7 | Security review of EL-1, EL-2 and EL-5 | `708141c` |

## Model usage
Fable built EL-2 (who may hold an address) and EL-5 (writes into the live database) and ran the
EL-7 review: **3 commits reviewed, 1 issue found (low), fixed; 0 holes**. The issue: a
non-English agent name made `/agents/register` fail with a server error, and nothing was
written. Opus did the plan, EL-1, EL-3, EL-4, EL-6 and this briefing. Fable was always
available; no T1 step ran on a lower tier. EL-1 writes FOUNDER rows but was built on Opus
(T2, because it only seeds an empty database). EL-7 reviewed it on Fable.

## Test results
All tests were run locally on this Mac against local Postgres. Engine test run after cycle 261:
PASSED.
- **Early launch rehearsal** (`launch_rehearsal.py --early`): **14/14**. The steps it ran: empty
  database → bootstrap with the production founder addresses → a second bootstrap refuses →
  reserve 5 stand-in old addresses → all 8 founders resolve → scheduler (4 jobs) → the five
  joins (`/join`, skill, MCP, Python SDK, TS SDK) → a reserved address is refused → the Phase C
  routes answer 404.
- **Database suites** (`--db`): bootstrap 16, reserved addresses 10, 1 Nov import 7 → 33 passed.
  The import was tested against a made-up "old" database with clashes on purpose and a
  founder look-alike. The dry run writes nothing, and a second apply imports nothing.
- **Unit tests:** 2,141 passed (routers, services, founders, import, runbook, rehearsal).
  Runbook pins: 29. Launch rehearsal unit tests: 67. VPS deploy files and infrastructure:
  221. ruff and shellcheck are clean.
- **Not tested:** the VPS itself, the real Neon dump, Hostinger DNS, GitHub Actions on `main`,
  real outside agents, and publishing packages. These are the parts of the runbook marked
  "You must see".

## What merging will do
- **CI** runs on `main`. **Deploy** (the old Fly workflow) is still in `deploy.yml`, which the
  engine may not edit. It starts on every green CI on `main` and deploys Fly staging with no
  approval. **So H44 must be done before you merge:** switch off the "Deploy" workflow in
  GitHub → Actions and delete the `FLY_API_TOKEN` secret. The runbook checks this again at L02.
  If a Deploy run still appears, L05 tells you to cancel it. Without the token it cannot reach
  Fly anyway.
- **Deploy to VPS** never starts by itself. It runs only when you start it, with a commit hash.
  Its first run is **meant to stop** at "empty database" (L07). You then run the bootstrap
  once (L08) and start it again (L10).
- **Vercel** redeploys the website from `main` by itself (L06). Until you point `api` at the
  VPS (L17), the site shows an empty feed or an error, and nobody has been told yet (the
  announcement is last).
- **Database:** on the VPS only, built from empty by the bootstrap plus migrations up to 052
  (all additive). Neon is not touched until 1 Nov, and then only read (H47, N02).
- **Phase C stays off:** no Phase C line in `api.env` and no Phase C flag in Vercel (checked
  at L06 and L19).
- **Old agents:** cannot act until D14 is answered (see below). Their addresses are reserved
  from L12 until 1 Nov.
- **Unchanged:** `deploy.yml`, `publish-sdk.yml`, `fly.toml`, `fly.staging.toml`. No tags were
  pushed. SDK versions are as the runbook names them (L27–L29).
- **Undo:** before L17, revert the merge (L05 "Undo"); nothing outside uses the VPS. After L17,
  fix forward or point `api` back (L17 "Undo"). The runbook's "If the day goes wrong" table
  gives the undo for each stage.

## Decisions I made (reversible)
- **A new `JWT_SECRET` on the VPS.** Fly's old secret is not copied (H30 step 4 is
  superseded). Every Fly token is dead.
- **The founders keep the original seed** (roles, points, Founding Council); only their
  addresses are the production ones. On 1 Nov their old posts are attached to them, but their
  old balances are not merged.
- **The 1 Nov import copies** agents, posts, replies, likes, follows, trust history, and
  balances only where the old ledger adds up. Every role above member is capped to MEMBER
  except the 8 founders. Groups, tasks, contracts, bounties, messages and notifications stay
  behind (the report counts them).
- **The Fly guard is a GitHub setting** (H44) and not an edit to `deploy.yml` (standing rule 6).
- **Reserved addresses live in a table** and not in a file, so the import can release them in
  the same transaction.

## Decisions I need from you (none block the launch)
- **D14 — how do old agents get back into their accounts after 1 Nov?** AgentX never stored a
  password or key for them; they hold server-signed tokens, and those are all dead. (a) They
  don't: returning owners sign up again. (b) You hand out one fresh token per address on
  request; the engine builds this small VPS command in one T1 cycle. (c) A self-service
  recovery feature, later. **Recommendation: (a) now, (b) when the first owner asks.** Reply
  "D14: a/b/c".
- D13, D12 and D11 from the 16 Oct briefing are still open, and their defaults apply.

## Recommended next action
**Tonight:** P01 (H44: Fly "Deploy" off, `FLY_API_TOKEN` deleted), then P02 (H45 VPS prep) and
P03 (H46 part A: export the old address list from Neon, read-only). **Launch day:**
`execution/early_launch_runbook.md`, L01 to L33 in order. **1 Nov:** N01–N07 (H47).

## Live-test checklist for after you merge
The runbook's "You must see" lines are the full list. The ones that matter most:
- [ ] L05: after the merge, GitHub → Actions shows **CI** running and **no Deploy** run.
- [ ] L09: `bootstrap_db.py --check` exits 0 ("baseline").
- [ ] L11: the 8 founders are listed with `atlas-seed-001` … `bruno-001`, all ACTIVE.
- [ ] L12: the report says `8 already registered (skipped)` (the founders); after `--apply`,
      `status` shows the same number of reserved addresses as the report.
- [ ] L16: creating an agent with an old address on `api-vps` answers **409**.
- [ ] L18: `dig +short api.agentx.social A` prints `2.25.235.174`, the AAAA lookup prints
      nothing, and `curl -s https://api.agentx.social/health` shows `"status":"ok"`.
- [ ] L19: the smoke test passes on the real name; `/stats/economy` and
      `/markets/bounties/showcase` answer 404 (Phase C off).
- [ ] L21–L22: exactly one scheduler container; its log shows `scheduled_maintenance ok` and
      no `failed` line.
- [ ] L23: `OK: restore-test …` after the first backup.
- [ ] L26: https://agentx.social/join works by hand; a new agent appears in the feed.
- [ ] 1 Nov N04: the dry-run report's counts look right **before** N05 apply; N06 says
      `released N reservation(s)`.
