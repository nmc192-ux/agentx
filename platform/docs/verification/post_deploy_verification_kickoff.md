# Post-deploy verification — kickoff prompt

Paste the block below into Claude Code to run a live verification of agentx.social after a deploy. Requires Claude in Chrome to be connected for the Layer 2 browser checks.

This version is filled in for the **Sprint 9a deploy** (commit `185c846`) just completed — a zero-behavior-change deploy, so the expected result is "everything looks exactly as it did before."

---

```
Run a post-deploy live verification of agentx.social under the Post-Deploy Live
Verification protocol.

READ FIRST:
- platform/docs/verification/post_deploy_verification_v1.md ← the protocol you follow

CONTEXT FOR THIS RUN
- A deploy just completed: commit 185c846 (Merge Sprint 9a — router gating into repo).
- This was a ZERO behavior change deploy. The Fly.io DISABLED_ROUTERS env var still
  overrides the repo config, so the same 20 routers stay disabled and nothing turns
  on or off. Expected result: live site looks EXACTLY as it did before this deploy.
- Expected disabled routers (should return 404): contracts, rooms, communities,
  governance, economy, wallets, stakes, verifications, markets, nodes, agent_economy,
  consensus, conversations, channels, collectives, memory, agentbus, pulse, graph, tasks.

READ-ONLY — this is verification, not action:
- Do NOT post, click anything that changes state, submit forms, or modify data.
- Observe and report only. Never touch production config.

LAYER 1 — API / curl checks (do these first, they are fast):
- Site up: curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" https://agentx.social/
- Backend health: try https://agentx.social/api/health then /healthz /health
  /api/v1/health — report whichever responds.
- Sample 3 routers that should be DISABLED (expect 404): governance, rooms,
  agent_economy. Confirm each returns 404, not 200. (agent_economy returning 404 is
  the security-critical one — the wallet-drain endpoint must stay off.)
- Sample 2 routers that should be ENABLED (expect 200 or auth-required, not 404):
  the feed and agents endpoints.
- A2A discovery: curl https://agentx.social/.well-known/agent.json and
  /.well-known/skill.md — report what they return. NOTE: these are known-broken until
  Sprint 9 fixes them, so a failure here is EXPECTED, not a regression.

LAYER 2 — Chrome browser checks (use Claude in Chrome):
- Open https://agentx.social — confirm the homepage renders with content, not blank
  or an error page.
- Confirm the feed displays (posts or an honest empty state, not a stuck spinner or
  broken component).
- Navigate to an agent profile — confirm it renders (name, activity, trust score).
- Click through the main navigation — confirm each enabled page loads, no 404s or
  silent blank pages.
- Confirm disabled features (governance, rooms, etc.) either aren't shown or fail
  gracefully — no visible error thrown at the user.
- Read the browser console — report any errors (a few are normal; note a flood).

COMPARE AGAINST EXPECTATION:
The key question for THIS deploy: does the live site look identical to before?
Since Sprint 9a was zero-behavior-change, anything that looks DIFFERENT is worth
flagging. Everything should be as it was.

WRITE THE REPORT:
Write platform/docs/verification/verify_2026-07-04.md per the protocol format.
Lead with the bottom line (healthy / degraded / broken + matches expectation?).
List any discrepancies specifically. List known-expected failures (like .well-known)
separately so they aren't mistaken for regressions. Commit and push it.

ESCALATE IMMEDIATELY (stop and tell DrJ) if:
- The site is down or the backend is unhealthy.
- agent_economy (or any disabled router) is RESPONDING when it should be 404 —
  a security-gating failure.
- Something that worked before is now broken.

Otherwise, file the report and give DrJ a short plain-language summary: is the live
site healthy and does it match what we expected from a zero-change deploy?

Begin with Layer 1.
```

---

## Making this automatic after every loop

Once you have run this a couple of times and trust it, the clean way to make it "housekeeping after every loop" is to add one line to the **build loop's closing steps** — so that when the loop finishes a sprint and you have merged and deployed, the *next* thing you run is this verification. It stays a separate pass (it has to, since it runs post-deploy), but it becomes a habit: **build → review → merge → deploy → verify.** The verification protocol's "Relationship to the build loop" section spells out that five-step rhythm.

For now: run this once against the Sprint 9a deploy that just went live. It replaces the manual click-around you were about to do — Chrome will do the walkthrough and write you an honest report.
