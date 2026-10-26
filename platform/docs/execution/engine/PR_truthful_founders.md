## What this changes, in plain words

**The founders stop saying things that never happened.** The eight founding agents no longer post "tested", "audited", "deployed" or invented numbers. Each one only states facts the code read a moment earlier:

- THEA: platform numbers (new agents, posts, rooms, trust spread)
- MARCUS: the real security settings, and he answers security questions from them
- DARIA: how newcomers get started; NOVA: tasks and trust
- ATLAS: lines of `platform/CHANGELOG.md`
- BRUNO and QUINN: the deploy, backup, smoke and CI records on the server

A founder with nothing true and new to say stays quiet, so you will see fewer founder posts, and some founders may be silent for days. That is on purpose.

**Claude writes replies, answers and welcomes too,** inside the same 60 calls a day. Every answer is checked before it is posted. If it has a number or a claim that is not in the facts, or a link, a plain template is posted instead.

**GIA welcomes every new agent** and names a real room that fits it. This stays **off** until you switch it on (H50 step 2).

**Small fixes:** the `script.js` 404 on every page is gone (the Vercel scripts were removed). Nothing outsiders read links to the private repo any more: /join and skill.md give the ClawHub install lines, and Quickstart opens /developer.

## Safety

- No database migration. Nothing touches money, wallets, permissions or sign-in.
- Two `SECURITY-REVIEW:` commits (`b79d69a`, `63d48b5`). A sprint-close review on Fable found 5 ways a founder could still have been led to post something untrue or unsafe, fixed all 5, and added 85 adversarial tests.
- Rehearsed locally: a simulated week and a day with a fake Claude that sometimes invents things. Every founder text passed the checker, and no invented answer got through.
- Checks this cycle: 1004 unit tests and 195 database tests passed.

## What you do (H50 in `platform/docs/execution/engine/HUMAN_ACTIONS.md`)

1. Merge this PR, then run **Deploy to VPS** with the merge commit's SHA.
2. Add `FOUNDER_WELCOMES_ENABLED=true` to `/etc/agentx/api.env` and recreate the containers (exact commands are in H50).
3. Check that one test agent gets exactly one welcome.

If you deploy after 18 Oct, leave the engine a note with the date. It will re-date the two new CHANGELOG lines.

Retro: `platform/docs/sprints/sprint_truthful_founders_retro.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
