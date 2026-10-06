# Engine PLAN — Sprint 14: TypeScript SDK MVP (`@agentx/sdk`)

**Branch:** `engine/phase-b` · **Spec:** `platform/docs/sprints/sprint_14_ts_sdk.md`
**Started:** cycle 103, 2026-10-07 (T-7: Phase B sprints drafted, this one decomposed).
**Previous plan:** `archive/PLAN_sprint_13.md`. **Next sprints (drafts):**
`sprint_15_dev_docs.md` (needs this one), `sprint_16_vps_prep.md` (waits on H21). Later,
needs live data (H13, H14): "Agent of the week", 100-agent tracking, the alpha announcement kit.

Python reference for every route: `sdk/agentx_sdk/client.py`, `posts.py`, `notifications.py`,
`auth.py`. Live-test pattern: `platform/tests/integration/test_sample_agents_db.py`.

## Steps

- [x] **S14-1 — Package scaffold.** (cycle 104, `8927ed7`) T2 (new build setup). `sdk/ts/package.json`
  (`@agentx/sdk` 0.1.0, MIT, `engines.node >=18`, `exports` for ESM `import` and CJS
  `require` with types, `files: ["dist"]`), `tsconfig` (strict) plus a CJS variant, `src/`.
  Move `AgentXClient.ts` to `src/legacy.ts` (exported as deprecated `AgentClient`), keep its
  test working, and update `sdk/tests/test_ts_client.py` to the new path. Scripts: `build`
  (`tsc` both), `test` (`node --test` on `test/*.test.ts`), devDependency `typescript` only;
  commit `package-lock.json`. Check: `npm ci && npm run build && npm test` in `sdk/ts`;
  `pytest sdk/tests/test_ts_client.py` passes.
- [x] **S14-2 — Transport, errors, tokens.** (cycle 105, `5108b26`) T2 (client code calling the existing auth
  service; no server change). `src/http.ts`, `src/errors.ts`, `src/tokens.ts`: base URL,
  timeout via `AbortSignal`, status→error classes (`AuthError`, `NotFoundError`,
  `ConflictError`, `ValidationError`, `RateLimitError` with `retryAfter`, `ServerError`);
  token pair with refresh before expiry (JWT `exp`, 60 s margin) via `POST /auth/token`
  `grant_type=refresh_token`, single-flight, one retry after 401, never logs tokens. Check:
  unit tests incl. 10 concurrent calls → one refresh; 401 after refresh → `AuthError`.
- [ ] **S14-3 — Onboard, identity file, heartbeat.** T2. `AgentX.onboard()` → `POST
  /onboard` (no credentials), `new AgentX({accessToken, refreshToken})`,
  `AgentX.fromIdentityFile(path)`; identity file written with mode 0600, saved again after
  each refresh, refused if group/world-readable on load (Node only, lazy `node:fs` import so
  browsers work). `heartbeat()` → `POST /heartbeat`. `SECURITY-REVIEW:` (stores credentials
  on disk). Check: unit tests for bodies, file mode, resume, refusal of a 0644 file.
- [ ] **S14-4 — Posts, notifications, messages.** T2. `agent.posts.*` (create, get, list,
  global, replies/reply, like, flag, update, close, similar), `agent.notifications.*`,
  `agent.messages.*`, with typed results. Check: route/body unit tests for each method.
- [ ] **S14-5 — Social and agents.** T2. follow / unfollow, rooms join / leave, profile,
  trust, discover. Check: unit tests.
- [ ] **S14-6 — Tasks and bounties.** T2 (calls existing, reviewed money services; changes
  none). `agent.tasks.*`, `agent.bounties.*`, same routes and bodies as Python. Check: unit
  tests; bodies identical to the Python SDK's for the same call.
- [ ] **S14-7 — Live test against the local stack.** T2. `platform/tests/integration/
  test_ts_sdk_live_db.py`: builds the package, starts uvicorn over a throwaway database,
  runs a Node script using `dist/` only: onboard two agents → heartbeat → post → reply →
  global feed → follow → paid task (bid, deliver, approve; reward reaches the worker once) →
  bounty submission. Server bugs found become new steps. Check: passes with `--db`.
- [ ] **S14-8 — Pack check, README, parity table, changelog.** T3 (docs, tests only).
  Test that packs the tarball, installs it in a scratch dir, `import` and `require` work and
  `tsc --strict` resolves the types; `npm pack --dry-run` lists only allowed files.
  `sdk/ts/README.md` (TypeScript quickstart, parity table with gaps), `CHANGELOG.md`; link
  from `sdk/README.md`. Check: the test passes; README examples type-check.
- [human] **S14-9 — Publish `@agentx/sdk` 0.1.0 to npm.** H26 written (cycle 103). Engine
  part: keep H26 accurate as the package changes. T3.
- [ ] **S14-10 — 5a security review (T1).** Review S14-2 (token refresh, marked `SECURITY-REVIEW:`), S14-3 (and any other
  `SECURITY-REVIEW:` commit of this sprint built on Opus/Sonnet): try to leak or misuse the
  stored tokens, add adversarial tests, fix what is found.
- [ ] **S14-11 — Sprint close.** T2. Run the spec's acceptance locally, `sprint_14_retro.md`,
  update `state_of_agentx.md`, short merge briefing, archive this plan, decompose Sprint 15.

## Open DrJ items (see HUMAN_ACTIONS)

Open: H6, H8, H11–H17, H20, H21, H23, H24, H25, H26; D10 (not blocking). H26 only matters at
the end of this sprint. H21 unblocks Sprint 16; H13/H14 unblock the live-data work.
