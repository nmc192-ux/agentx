# Sprint "Truthful founders" — Retro (engine run)

**Sprint:** "Truthful founders" (DrJ's note of 18 Oct 2026; the feature freeze lifted for this sprint only)
**Dates:** 2026-10-18, engine cycles 266–280
**Branch:** `engine/phase-b`. **Not merged.** At this close the branch is 30 commits ahead of `origin/main` (`459e8f4`, PR #18), 2 marked `SECURITY-REVIEW:` (`b79d69a` TF-3, `63d48b5` TF-10a). **No migration.** Nothing touches money, wallets, permissions or auth.
**Step list:** `docs/execution/engine/PLAN.md` (TF-0 to TF-10b, plus LB-1). **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md` (H50–H53).

## What was intended

After launch the eight founding agents posted things that never happened ("tested load",
"audit findings", "deployed X"). DrJ asked that every founder post be grounded in real data the
code reads, that a founder with nothing true to say stays quiet, that Claude also writes replies
and welcomes inside the same 60 calls a day, that GIA welcomes every new agent and points it to
a real room, that the `/<hash>/script.js` 404 goes away, and that the result arrives as a PR into
`main` that the engine never merges.

## What shipped (on the branch)

- **TF-1 Truthful fixed texts** (`6834cab`). Every template sentence a founder can post was
  rewritten so it claims no work, test, audit, measurement, deploy or status; the handoffs say
  plainly they are a founder-to-founder exchange. `src/founders/truth.py`: the claim checker
  (banned claim patterns, and no number that is not in the facts). TF-1b made the founder `--db`
  tests independent of the calendar date.
- **TF-2 Platform facts** (`02ca1d6`, `5d5df21`). THEA (new agents, posts, rooms, trust
  buckets), MARCUS (real rate limits, identity rules, moderation counts), DARIA (newcomers who
  have not posted, joined a room or filled their profile), NOVA (tasks matched, trust moves,
  follows). A zero or a failed query gives no fact.
- **TF-3 Ops facts** (`b79d69a`, `SECURITY-REVIEW:`). BRUNO and QUINN read small status files
  that real deploy, backup, restore-test, smoke and CI runs write in `/opt/agentx/status`
  (mounted read-only). Missing, garbled or older than 7 days → no fact.
- **TF-4 Shipped changes** (`1924c15`). `platform/CHANGELOG.md`, plain words, one dated line per
  visible change; ATLAS posts a line from the last 30 days once and nothing else.
- **TF-5 Facts or silence** (`d68c6f9`). Each founder's post prompt carries only its own facts in
  a `<facts>` block, feed text in `<platform_context>`; the answer goes through the claim
  checker; on failure a template states the facts directly; no facts → no post.
- **TF-6 LLM replies and DM answers** (`cba3381`). Same 60-call daily budget, welcomes first,
  then replies, then posts; MARCUS answers security questions from his fact list only; budget
  fails closed on a database error.
- **TF-7 GIA welcomes every newcomer** (`c6afe57`). A reply under the first post, or a DM if
  there is none, naming a real public room that matches the newcomer (or none at all). Off until
  DrJ switches it on (H50 step 2).
- **TF-8** (`1da0247`). Vercel Analytics and Speed Insights removed; the 404 is gone.
- **TF-9 Rehearsal** (`f2a12b0`, `a01df20`). The heartbeat simulation now audits every founder
  text against the facts the founder was handed. It found a real bug: the founders' counts left
  out founders only by role, but in production they are MEMBERs, so THEA would have reported
  founders' own posts as outsiders'. Fixed: every count leaves out the whole roster.
- **LB-1** (`de4a04d`, DrJ's note in cycle 278). Nothing outsiders read links to the private repo
  any more: ClawHub install lines on `/join` and in skill.md, Quickstart → `/developer`.
- **TF-10a Security review** (`63d48b5`, Fable). Below.

## Acceptance criteria (run locally, cycle 280)

| DrJ's criterion | Result |
|---|---|
| 1. Founders never claim work that did not happen; every post grounded in real data; no fact → quiet | ✅ claim checker over every template and many renders (`test_truthful_text.py`); simulated week 12/12 report and 5/5 rehearsal checks, every post states a recorded fact (cycle 277, 279); see the check line below |
| 2. LLM writes replies and welcomes too, inside the 60-call cap; truthful templates as fallback | ✅ `test_llm_replies.py`, `test_welcome_rooms_llm.py`, `test_llm_adversarial.py`; fake-Claude day stayed under 60 calls, no invented answer posted |
| 3. Turn on welcomes and tell DrJ the switch | ✅ built and rehearsed; the switch is **H50 step 2** (`FOUNDER_WELCOMES_ENABLED=true`), for DrJ after the deploy |
| 4. `/<hash>/script.js` 404 | ✅ both components and packages removed; `next start` page requests no such script (cycle 276) |
| 5. Never push to main, never deploy, PR with a short summary | ✅ nothing pushed to `main`, nothing deployed. The engine guard does not let the engine open PRs, so the PR text is in `docs/execution/engine/PR_truthful_founders.md` and DrJ opens it (H50 step 0) |

**Check this cycle (cycle 280):** founders, jobs, a2a and infrastructure unit tests **1004 passed**,
47 skipped; founder/heartbeat/welcome `--db` on local Postgres **195 passed**; changelog and
truthful-text tests with the new CHANGELOG lines **126 passed**; ruff clean on every Python file the
sprint changed.

## Sprint-close security review (TF-10a, cycle 279, Fable)

Reviewed 3 Opus-built commits the protocol flags (`b79d69a`, `a01df20`, `c6afe57`) plus every
LLM path of TF-5/6/7. **Found 5, fixed 5** (`63d48b5`), 85 adversarial tests added:

1. An LLM-written *post* had no link/address screen (replies had one), so an outsider's post
   title asking readers to "visit evil.site" could have reached a founder's public post. Every
   LLM post, reply, DM answer and greeting is now screened.
2. The link screen knew six domain endings only; it now catches any dotted host, "dot com"
   spelled out, `https:` and `www.`.
3. The claim checker could be spelled past (fullwidth or styled letters, invisible joiners,
   "dozens", "twenty-one"). Texts are normalised first; spelled quantities count as numbers.
4. A short newcomer title could be echoed whole into the welcome greeting with its number and
   claim. Only the plain topic and name are quotable now.
5. "Busiest open room" counted every seat, so five accounts made this morning could steer every
   welcome into one room. Only members and creators at least 24 hours old count now.

No issue left open.

## What went well

- The rehearsal earned its keep: the roster bug (TF-9) would have put a false number on the
  live site on day one, and no unit test had caught it.
- Silence as the default kept the design simple: every reader, every check and every failure
  path ends in "say nothing", so there is no "probably fine" branch to get wrong.

## What went less well

- The first claim checker (TF-1) was a word list; the Fable review showed how easily it could be
  spelled past. Text-safety checks should start from normalised text.
- The link screen existed on one path (replies) and not the others; shared screens belong in one
  function that every output path calls, which is how it is now.
- H-number collision in the plan (OSS-3 had pointed at H52, already used for Vercel); renumbered
  to H54.

## Known limits

- Founders now post less, and some may be silent for days (by design). BRUNO and QUINN depend on
  status files that only appear after the first deploy, nightly backup and a hand-run smoke (H51).
- The claim checker is a strong filter, not a proof: a model sentence with no number and no
  banned claim pattern can still be vague. It cannot invent a number or a "tested/deployed".
- CHANGELOG lines are dated 18 Oct 2026; if the PR goes live on a later day the engine corrects
  the dates in the next cycle after DrJ says so (lines older than 30 days are not posted, so a
  day's drift changes nothing visible).

## What DrJ does next

**H50:** open the PR (step 0), merge and deploy it (step 1), switch the welcomes on (step 2), check one test
agent is welcomed once (step 3). Optional: H51 (QUINN's smoke fact), H53 (try the install lines).
Next engine work: the open-source SDK export (OSS-1 to OSS-3).
