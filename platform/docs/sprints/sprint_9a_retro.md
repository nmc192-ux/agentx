# Sprint 9a — Router gating into the repo — Retro

**Sprint:** 9a (prerequisite to Sprint 9)
**Dates:** 2026-07-04 → 2026-07-04 (single autonomous session)
**Merged in:** *not yet merged* — on branch `phase-a-autonomous`. Awaiting DrJ review.

## Correction — 2026-07-04 (parity 19 → 20)
The original 9a work set the repo default to **19** routers, inferred from the 5 May audit, which recorded `memory` as *enabled* in production. DrJ then read the **live** production `DISABLED_ROUTERS` value from the running app and confirmed it is **20** routers — `memory` is in fact *disabled*. The audit was wrong on that single point. `memory` was added to `DEFAULT_DISABLED_ROUTERS` (its own `PARITY_UNEXPLAINED` tier, since — unlike the other 19 — there is no known reason it's off, and it is one of the magna carta's seven core primitives; the "why" is a Sprint 9 investigation). Repo default now equals the confirmed live set **exactly (20, zero diff)**; full suite still green (2031 passed). This correction is why the original "19" language below remains — it records what was true before the live read. The sections below are left as-written for the record; the operative parity number is **20**.

## What was intended
Move the router enable/disable decision out of an invisible Fly.io `DISABLED_ROUTERS` environment variable and into version-controlled, commented repo config — while keeping the env var as an emergency override — so that which features are on or off is readable in code, has a paper trail, and can be changed by the autonomous loop on a branch for review. Set the repo default to *exactly match current production* so merging produces zero behavior change; enabling routers stays deliberately in Sprint 9.

## What actually shipped
A new `platform/src/router_config.py` holding `DEFAULT_DISABLED_ROUTERS`, with every disabled router annotated by *why* it's off and *what* re-enables it, split into two tiers: `BROKEN_OR_INSECURE` (the 5 audit-flagged routers) and `PARITY_HOLD` (14 audit-cleared routers that are off in production today, held off only for parity). `config.py`'s `disabled_routers` field now defaults to that repo list, with the `DISABLED_ROUTERS` env var overriding it via Pydantic precedence (the emergency kill-switch), plus a `disabled_routers_source` indicator. `main.py` logs the effective disabled list and its source at startup. `conftest.py` sets `DISABLED_ROUTERS=""` so the test suite still exercises the full API surface. Nothing is in production yet — this is on the branch. **Not merged, not live.**

## What we learned
Two concrete facts. First, the mechanism was already latent: Pydantic Settings gives env vars precedence over field defaults, so "env overrides repo default" needed no custom precedence logic — just moving the default from `""` to the repo list. Second, and more important: the hand-off's stated premise — that production currently disables exactly five routers — is **contradicted by the documented evidence**. The 5 May audit (`audit_2026-05-05.md:304`) records production as disabling ~19 routers (every gated router except `memory`, ≈130 of 184 endpoints). The "five" is the Sprint 9 *target* (what should be off after the fixes), not current state. Setting the repo default to five would have *enabled ~14 currently-disabled routers on merge* — the exact behavior change this sprint forbids. Parity therefore required the 19-router set, not five.

## What we deferred
No fixes and no enablement — all deliberately out of scope (they are Sprint 9). One item is genuinely open rather than deferred: **confirming the exact current production `DISABLED_ROUTERS` value.** The loop is barred from reading Fly.io, so the repo default was set from the best documented source (the May 5 audit). DrJ must confirm the live value matches before removing the env var; until then the env var (still set in prod) overrides the repo default anyway, so the merge itself is zero-change regardless.

## What changed strategically
No magna carta or plan amendment needed, but a data correction worth recording: the "5 disabled routers" figure that has propagated (including into this sprint's own example config) is the post-Sprint-9 target, not the current production state, which is ~19. Future sprint specs should cite the 19→5 transition explicitly. This is exactly the kind of honest-accountability record Article 24 Principle 4 (this sprint's anchor) exists to produce — the gating decision and its rationale are now in the repo, not inferred.

## Next
Sprint 9 proper — fix-then-enable — remains the successor: fix the three defects (missing `governance_votes` table, `room_members` typo, wallet-auth hole — the last reviewed by DrJ as security code), then enable the 14 `PARITY_HOLD` routers in cohorts by editing `router_config.py` on a branch. But first, the open question that must be answered before 9a is merged: **does the live Fly.io `DISABLED_ROUTERS` value match the 19-router set documented in the May 5 audit?** DrJ confirms, then reviews and merges.
