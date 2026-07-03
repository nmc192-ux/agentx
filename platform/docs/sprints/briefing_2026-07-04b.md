# Briefing — 4 July 2026 (b) — Sprint 9a parity correction

**Branch:** `phase-a-autonomous`, latest commit `026033a` (pushed). **Not merged. Not on main. Not live.**

## Bottom line
The parity gap my first 9a briefing flagged is now closed. You read the **live** production `DISABLED_ROUTERS` and confirmed it's **20 routers, including `memory`** (the 5 May audit had wrongly inferred `memory` was enabled). I added `memory` to the repo default; **parity is now EXACT at 20**, verified two independent ways, and the full test suite is still green. **Ready for your review and merge — zero behavior change.**

## What was corrected
- One-line-of-intent change to `platform/src/router_config.py`: added `memory` to `DEFAULT_DISABLED_ROUTERS` (19 → 20), in its own `PARITY_UNEXPLAINED` tier with the comment `disabled to match production; reason TBD — see Sprint 9`. It's held separate from the other two tiers because — unlike the 19 — there's no known reason it's off, and `memory` is one of the magna carta's seven core primitives, so its being disabled is notable and flagged for Sprint 9 investigation.
- Header parity note updated: source is now your live read (2026-07-04), not the audit's inference.

## Parity re-verification (the key output)
**EXACT PARITY: YES — 20 routers, zero diff in either direction.** Confirmed two ways:
- Deterministic set-equality: repo default (20, no duplicates, `memory` present) == your confirmed live set. Nothing missing, nothing extra.
- Independent **Fable 5** adversarial check: every name in the repo default maps one-to-one to a real `_include_if_enabled(..., "name")` gate in `main.py` (no typos that would silently fail to disable; no gated router left uncovered); tier concatenation 5 + 14 + 1 = 20 verified by executing the module; normalization and env-override semantics sound.

## Tests (local)
- Live stack startup log: `Router gating: 20 disabled via repo default … — …,memory,…`.
- OpenAPI: `memory` routes (`/agents/{did}/memory[...]`) now absent — memory is gated off. Total registered paths 74 → 72.
- Full suite: **2031 passed, 14 skipped** (unchanged). The `conftest.py` override (`DISABLED_ROUTERS=""`) keeps every router — memory included — registered for tests, so nothing broke.

## What merging does
Same as before: code change is behavior-neutral while the Fly.io env var stays set (it overrides the repo default). Now that the repo default equals the live set exactly, **removing the env var after merge is also zero-change** — the repo becomes the sole, readable source of truth. Backend prod remains behind manual approval; no UI changes in this branch.

## Recommended next action
Review the diff (`055c5f2` + `026033a`) and merge. Optionally remove the Fly.io `DISABLED_ROUTERS` env var afterward so the repo governs gating. Then Sprint 9 — Stabilize can run (fix-then-enable), and should investigate why `memory` — a core primitive — is disabled in production.

---
*Branch clean, pushed, buildable. Nothing live. Correction complete.*
