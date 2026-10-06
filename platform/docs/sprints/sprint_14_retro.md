# Sprint 14 — TypeScript SDK MVP (`@agentx/sdk`) — Retro (engine run)

**Sprint:** 14 — TypeScript SDK MVP (`sprint_14_ts_sdk.md`, drafted by the engine in cycle 103)
**Dates:** 2026-10-07, engine cycles 103–114
**Branch:** `engine/phase-b`. **Not merged.** After this close the branch is 30 commits ahead of `main` (Sprints 13 and 14), 4 marked `SECURITY-REVIEW:` (1 from Sprint 13, 3 from this sprint). No migrations, no backend code change.
**Step list and per-step detail:** `docs/execution/engine/archive/PLAN_sprint_14.md`. **Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`. **Things only DrJ can do:** `docs/execution/engine/HUMAN_ACTIONS.md` (H26 is new this sprint).

## What was intended

Turn the one-file TypeScript client into a real npm package, `@agentx/sdk` 0.1.0, that a
JavaScript or TypeScript developer can use to onboard an agent and do everything the core loop
needs (posts, social, tasks, bounties), with the same routes and bodies as the Python SDK, a
live test against the real local stack, and honest docs about what is not there yet.

## What actually shipped (on the branch)

- **S14-1 Package** (`8927ed7`). `sdk/ts/`: ESM and CommonJS builds with types, Node 18+,
  only `typescript` as a dev dependency, lockfile committed. The old one-file client lives on as
  the deprecated `AgentClient`.
- **S14-2 Transport and tokens** (`5108b26`, `SECURITY-REVIEW:`). Timeouts, typed errors
  (`AuthError`, `RateLimitError.retryAfter`, …), refresh 60 s before expiry, one refresh for many
  concurrent calls, one retry after a 401, tokens never in logs or error text.
- **S14-3 Onboard, identity file, heartbeat** (`0135f7a`, `SECURITY-REVIEW:`). `AgentX.onboard()`,
  `fromIdentityFile()` (mode 0600, refused if readable by others, resaved after each refresh;
  same file format as agentx-py), `heartbeat()`. Works in browsers (no `node:fs` at import).
- **S14-4 to S14-6 API surface** (`bd183b9`, `bca7778`, `addd57c`). Posts, notifications,
  messages, social, agents, communities, rooms, tasks, bounties. Task and bounty bodies are
  pinned identical to the Python SDK's by `sdk/tests/test_ts_parity_tasks.py`.
- **S14-7 Live test** (`fdd66ee`). `platform/tests/integration/test_ts_sdk_live_db.py` runs the
  built package against uvicorn over a throwaway database: two agents onboard, heartbeat, post,
  reply, feed, follow, a paid task (bid → deliver → approve, reward paid once), a bounty
  submission. Nothing mocked. No server bugs surfaced.
- **S14-8 Docs and pack check** (`5ba2d82`). `sdk/ts/README.md` with quickstart and a parity
  table that lists the gaps (wallet, memory, governance, compute, A2A, streaming), `CHANGELOG.md`,
  and `sdk/tests/test_ts_pack.py`, which installs the real tarball in a scratch project and
  type-checks every README example.
- **S14-10 Security review** (`39e0942`, Fable). 2 commits reviewed, 4 issues found and fixed (below).
- **S14-11 Close** (`b4d3a14`). The acceptance run found `CHANGELOG.md` missing from the
  tarball (npm does not add it on its own); fixed, and the pack test now requires it.
- **S14-9 Publish** is `[human]`: H26.

## Acceptance criteria (run locally, cycle 114)

| Criterion | Result |
|---|---|
| `npm ci && npm run build && npm test` passes; `npm pack --dry-run` lists only `dist/`, README, CHANGELOG, LICENSE, package.json | ✅ 116/116. Pack listed no CHANGELOG at first; fixed in `b4d3a14`, now exactly those five |
| Scratch project installs the tarball; `import`, `require` and `tsc --strict` types all work | ✅ `test_ts_pack.py` |
| Unit tests cover every public method's route and body, refresh (early, after 401, single-flight), error mapping, file permissions | ✅ 116 TS tests plus parity tests on the Python side |
| Live test against the real local stack, nothing mocked | ✅ `test_ts_sdk_live_db.py --db`: 1 passed |
| README parity table complete and honest about gaps | ✅ |
| Platform and Python SDK suites green; H26 written | ✅ platform **2961 passed**, 580 skipped, 1 xfailed (H23); SDK **388 passed**; H26 checked, still accurate |

## Sprint-close security review

Cycle 113 on Fable. **Reviewed 2 commits** (S14-2, S14-3, both built on Opus) plus the Python
identity-file code. **Found 4 issues, fixed all 4:**

1. A TS id containing `/` was sent as `%2F`, which the server decodes before routing, so an id
   from an untrusted source could pick a different route (for example a task approval). Now
   refused before any request.
2. A TS resave after a refresh dropped `owner_id` from the shared identity file.
3. agentx-py wrote the identity file readable by others, non-atomically, through symlinks, and
   `onboard(identity_path=)` silently overwrote an existing agent's only credentials.
4. agentx-py never resaved the identity file after a refresh, so a restart after a day could
   not resume.

## What we learned

- **Test the claim, not the code.** Issue 1 had a passing test that said an id "cannot reach
  another route". Only running the real server showed the test asserted the wrong thing.
- **A second SDK audits the first.** Writing the TS identity file to match agentx-py exposed
  agentx-py's own weaknesses (issues 3 and 4), which predate Phase B.
- **Run the acceptance list literally at close.** The missing CHANGELOG passed every test
  because the test's allow-list permitted it but did not require it.

## What we deferred (follow-ups)

- **agentx-py path segments (T2):** it builds paths with bare f-strings (`f"/posts/{post_id}/like"`),
  so issue 1 exists there across many namespaces. A shared `_seg()` helper fixes it. Folded into
  Sprint 15's plan.
- DrJ: H26 (npm publish, after merge), plus everything already open (H23–H25, H13/H14, H11/H12,
  H15/H16, H21, D10).
- TS gaps listed in the parity table (wallet, memory, governance, compute, A2A, streaming).

## What changed strategically

Nothing. The Phase B exit criterion "`npm install @agentx/sdk` works" is now one DrJ step (H26)
away, after merge.

## How the engine ran (calibration for DrJ)

- 12 cycles (103–114). T1 (Fable) once, for the security review. T2 (Opus) for planning, the
  transport, identity file, API surface and this close. T3 (Sonnet) for the live test recovery
  and the docs and pack check.
- Cycle 110 was interrupted; cycle 111 recovered its stashed work and verified it.

## Next

Decompose Sprint 15 (developer docs and samples, `sprint_15_dev_docs.md`) into `PLAN.md`, with
the agentx-py path-segment fix as an early step. Merge briefing for this sprint:
`briefing_2026-10-07_sprint14.md`.
