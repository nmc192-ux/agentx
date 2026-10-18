# Engine PLAN — Sprint "Truthful founders" (DrJ note, cycle 266)

**Branch:** `engine/phase-b` · **Source:** DrJ's note of 18 Oct 2026 (launch done 00:48 PKT, PR #18
merged and deployed as `459e8f4`; founders run on Claude Haiku with `FOUNDER_LLM_PROVIDER=anthropic`,
`FOUNDER_LLM_DAILY_CALLS=60`). The feature freeze is lifted for this one sprint only. The previous
plan (early launch, all steps done) is in `archive/PLAN_early_launch.md`.

## What DrJ asked for (the acceptance of this sprint)

1. **Founders never claim work that did not happen.** No "tested load", "audit findings",
   "deployed X" unless it is real. Every founder post is grounded in real, readable data:
   - THEA: real platform numbers (new agents, posts, rooms, trust distribution).
   - BRUNO: real ops facts (uptime, last deploy commit, backup and restore-test status,
     scheduler job results).
   - QUINN: real health and test results (CI status, smoke results if recorded).
   - ATLAS: real shipped changes (recent merged commits or changelog, in plain words).
   - GIA: actually welcomes each new agent and points it to a relevant room.
   - MARCUS: explains real security features (rate limits, anti-spoofing, moderation) and
     answers questions.
   - DARIA and NOVA: real onboarding friction and real matching or trust signals.
   - **No real fact available → the founder stays quiet** rather than inventing.
2. The LLM writes replies and welcomes too, inside the same daily cap (60). Templates only as
   fallback, and the fallback templates are truthful too.
3. Turn on founder welcomes once (1) is done, and tell DrJ the switch.
4. Small fix: every page logs a 404 for `/<hash>/script.js` (Vercel Analytics / Speed Insights in
   `ui/app/layout.tsx`); remove it or enable it properly.
5. Never push to main, never deploy, no Phase C. Open a PR into `main` with a short summary DrJ can
   understand.

## Rules for this sprint

- Founders read facts; they never invent them. A fact is something the code read this tick from
  the database, the app's own settings/state, or a file written by a real deploy/smoke/backup run.
  Missing or stale source → the fact is absent, never "probably fine".
- The LLM only gets facts and untrusted context inside clearly marked blocks; its output is
  checked before posting (no number or claim that is not in the facts; else template; else quiet).
- No migration unless a step proves one is needed (prefer existing tables: `scheduler_job_runs`,
  `founder_llm_calls`, posts/agents/rooms/trust). Nothing touches money or permissions; the paid
  founder handoffs keep their amounts and caps, only their text changes.
- Phase C settings stay off. Nothing is deployed by the engine.

## Steps

- [x] **TF-0 — Plan the sprint.** Done cycle 266. T2. This list; H49 ticked (DrJ deployed PR #18).
- [x] **TF-1 — Truth audit of every fallback text, and a lint that keeps it that way.** Done cycle 267 (`6834cab`). T2 (text +
  tests across founders; no money/auth change). Every fixed sentence a founder can post today:
  post openers/hooks/closers (`generation.py`), reply openers/answers/room lines (`replies.py`),
  DM openings/answers (`messages.py`), task briefs/results (`tasks.py`), bounty/submission/proposal
  text (`civics.py`), welcome reply/DM (`welcome.py`). Rewrite anything that claims work, a test,
  an audit, a measurement, a deploy, a cost or a status ("Tested {topic}", "Audit note", "Checked
  … today", "Status: mostly green", "Cost unchanged", "two paths fail open", "tested the empty
  input", …) into a question, an invitation or an honest description. Handoff results say plainly
  that they are a founder-to-founder exchange that exercises the marketplace, not a claim of work
  done. Add `src/founders/truth.py` with a claim checker (banned claim patterns + "no digits that
  are not in the facts") and `tests/founders/test_truthful_text.py` that runs it over every
  template string and over many rendered outputs of every compose function. Check: the new test
  green; `tests/founders/` and `tests/jobs/` founder tests green; ruff clean.
- [x] **TF-1b — Fix the date-dependent founder DB tests.** T3 (tests only). 10 `--db` tests in
  `tests/integration/test_founder_{civics,messages,trust_replay}_db.py` fail on 18 Oct 2026 with
  and without TF-1 (e.g. `dm_trust` 'not_a_reply' instead of 'recorded'); they use a fixed
  `NOW` of 5 Oct while rows get the database clock, so windows have run out. Make them clock-
  independent (pass the test moment into the rows or derive `NOW` from today). Check: those three
  files green with `--db`. Done cycle 268.
- [x] **TF-2 — Platform facts for THEA, MARCUS, DARIA, NOVA.** Done cycle 269 (`02ca1d6`). T2 (read-only queries).
  `src/founders/facts.py`: a `Fact` (text, value, source, as-of) and per-persona readers.
  THEA: new agents 24h/7d, top-level posts and replies 24h, active rooms and joins, trust-score
  distribution (buckets). MARCUS: real security settings read from config/code (route rate limits
  from `limits`, anti-spoofing/DID rules, moderation counts held/hidden in the last 7 days).
  DARIA: onboarding friction from data (agents registered in 7 days with no post / no profile /
  no room; time to first post). NOVA: matching and trust signals (tasks matched/assigned 7 days,
  trust-score movements, follows). Every reader returns nothing when its numbers are zero or the
  query fails. Check: `tests/founders/test_facts.py` (no DB, fake conn) + `--db` test on local
  Postgres seeding a few agents/posts and asserting the exact numbers.
- [x] **TF-3 — Ops and health facts for BRUNO and QUINN.** Done cycle 271. T2 (deploy scripts write a small
  read-only status file; no secrets). BRUNO: process uptime and `/health/ready` state, deployed
  commit (`settings.git_commit`; make sure the VPS deploy passes it), last deploy time, scheduler
  job results (`scheduler_job_runs`), backup and restore-test status. QUINN: last smoke result
  and CI status. The VPS has no record of smoke/backup/CI today, so: `deploy/vps/deploy.sh` and
  `smoke.sh` (and the backup / restore-test script if the VPS has one; if not, the fact is simply
  absent and a human action says how to add it) write `/var/lib/agentx/status/*.json`, mounted
  read-only into the API; CI status is written by the deploy workflow from the commit's checks
  (`deploy-vps.yml`, read-only `gh`/API call already authorised there, or absent). Stale (> 7 days)
  or missing → no fact. Check: unit tests for the readers (missing/stale/garbled file → absent);
  `test_vps_deploy_files.py` pins the new writes and the mount; shellcheck clean.
- [ ] **TF-4 — Shipped changes for ATLAS.** T2. A plain-words `platform/CHANGELOG.md` (newest
  first, one dated line per user-visible change, seeded from the merged PRs #1–#18) baked into the
  image; ATLAS posts one entry it has not posted before (marker in post metadata), never invents
  one. The engine adds a line with every future user-visible change. Check: reader tests (parse,
  "already posted" skip, empty file → quiet); Dockerfile / `.dockerignore` include the file.
- [ ] **TF-5 — Fact-grounded posts, or silence.** T2. The heartbeat's top-level post path gives
  each persona only its own facts (TF-2/3/4). LLM prompt: a `<facts>` block, the rule "only state
  what the facts say; if nothing is worth saying, answer SKIP", untrusted feed text kept in
  `<platform_context>`. Output goes through the TF-1 claim checker against the facts; on failure
  the template renders the facts directly; no facts → no post (the schedule moves on, logged as
  `quiet_no_facts`). Topic-only posts with no fact are gone. Check: tests with a fake Anthropic
  client (SKIP, invented number, banned claim, good post), a no-facts persona posts nothing,
  budget still spent at most once per call; founder job tests green.
- [ ] **TF-6 — LLM replies and DM answers (same daily cap) + MARCUS answers questions.** T2.
  Replies, root answers and DM answers ask the LLM first (same `DailyCallBudget`, same 60/day),
  with the parent post / message as untrusted context and the persona's facts; MARCUS answers
  security questions from his fact list only. Claim checker on every output; truthful template
  on any failure. Budget order: welcomes first, then replies, then posts (a reserved share so
  posts cannot starve welcomes). Check: fake-client tests for each path, prompt-injection text in
  the parent does not change the output shape, budget accounting test (60 calls max across all
  kinds, fail closed on DB error).
- [ ] **TF-7 — GIA welcomes every new agent and points to a real room.** T2. GIA is the welcomer
  (others only if GIA is rate-limited or quiet, as today). Welcome every new ACTIVE agent within
  the window, not only those who already posted: if it has a visible first post, a reply there;
  otherwise the welcome DM only. Pick a real, existing, public room that matches the newcomer's
  capabilities/description/first post (fallback: the busiest public room; no rooms → no room
  line, never an invented one). LLM-written within the cap, truthful template fallback. Same
  caps (per hour, never twice). Check: `--db` test on local Postgres (newcomer with and without a
  post, room chosen exists, no room → no mention, second tick does nothing); founder tests green.
- [ ] **TF-8 — Remove the Vercel script that 404s on every page.** T3. `<Analytics/>` and
  `<SpeedInsights/>` in `ui/app/layout.tsx` load `/<hash>/script.js`, which only exists when the
  Vercel project has Web Analytics / Speed Insights switched on. Default: remove both components
  and the two packages (reversible; nobody reads those dashboards today); the human action says how
  to bring them back properly if DrJ wants them. Check: no `@vercel/analytics` / `speed-insights`
  left; ui lint, node tests and build green; a local `next start` page load requests no
  `script.js` under a hashed path.
- [ ] **TF-9 — Local rehearsal and the switch.** T2. Run the heartbeat for a simulated day on a
  local DB (fake LLM client plus template-only run): every produced text passes the claim checker,
  every number traces to a fact, quiet founders stay quiet, welcomes reach every newcomer once.
  Record **H50** for DrJ: deploy the PR, then switch welcomes on (`FOUNDER_WELCOMES_ENABLED=true`
  in `/etc/agentx/settings.env` or the repo's `deploy/vps/settings.env`, then redeploy), with how
  to check it worked and how to switch it off. Plus any TF-3 setup (status-file directory).
- [ ] **TF-10 — Sprint close: security review, retro, PR.** T1 for the review half (LLM output
  posted publicly + untrusted input in prompts), T2 for the rest. Adversarial tests on the
  prompts and the claim checker; `platform/docs/sprints/sprint_truthful_founders_retro.md`; open
  the PR into `main` with a short plain-words summary (what changes for visitors, what DrJ must
  do: H50). Never merge it.
