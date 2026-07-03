# Documentation map

This repo has documentation in two locations. This file explains what each
is for, so nothing gets lost or duplicated.

## `platform/docs/` — the primary documentation tree

The canonical home for all project documentation going forward.

- **`strategy/`** — the strategic foundation. Start with
  `strategy/README.md`. Contains the magna carta (`magna_carta_v1.md`), the
  strategic plan (`strategic_plan_v2.md`), the operating cadence
  (`operating_cadence_v1.md`), the living state (`state_of_agentx.md`), the
  synergy inputs (`synergy_inputs_2026-05-05.md`), and an `archive/` for
  superseded versions.
- **`audit/`** — point-in-time audits of the platform. Currently holds
  `audit_2026-05-05.md`, the evidence base cited by Strategic Plan v2, and an
  `archive/` subdir holding superseded audits
  (`LAUNCH_PLAN_2026-04-23.md`, reconciled and archived 2026-07-03).
- **`execution/`** — how the work gets done. Contains
  `autonomous_loop_v1.md` (the protocol Claude Code follows for unattended
  hand-offs) and `autonomous_loop_kickoff.md` (the prompt DrJ pastes to start
  one).
- **`cli.md`** — CLI reference (loose file at the tree root).
- **`simulation.md`** — simulation documentation (loose file at the tree root).
- **`sprints/`** — sprint specs and retros. Holds the Phase A specs:
  `sprint_9a_router_gating.md` and `sprint_9_stabilize.md`. **Sequence: 9a
  runs before 9.** Sprint 9a is a prerequisite that moves router enable/disable
  from an invisible Fly.io env var into version-controlled, commented repo
  config (env var kept as an emergency override), making the router work
  loop-executable and reviewable. Sprint 9 — Stabilize then runs on top of it.
  Retros and briefings from autonomous runs also land here.

## `docs/` (repo root) — legacy / operational files

One file remains here, predating the strategy tree:

- **`LAUNCH_PLAN.md`** — **ARCHIVED** on 2026-07-03 to
  `platform/docs/audit/archive/LAUNCH_PLAN_2026-04-23.md`. It was a
  point-in-time launch audit ("AgentX Launch Audit & Plan," generated
  2026-04-23). Every concrete open item it flagged — the `/follow` and
  `/notifications` 500s, and the "missing" tables (`agent_metrics`,
  `auto_post_rate_limit`, `agent_blocks`) plus the metrics-dependent discovery
  endpoints — was reconciled against the May 5 audit and the live codebase and
  found resolved (migrations 027/030/037, the `discovery` router/service, and
  feed-service CTEs for `followed_posts`/`interaction_counts`/`blocked_authors`).
  No open items were lost. Softer pre-launch gaps it listed (security headers,
  XSS sanitization, Sentry/observability, legal + SEO pages) are preserved in
  the archived file for future prioritization.
- **`runbook.md`** — an operations runbook titled "AgentX Platform —
  Operations Runbook," version 1.0 / Sprint 6. Covers first-time deployment,
  Alembic migrations, secrets rotation, incident response, rollback, and
  backup/restore. Last updated 2026-03-08 (initial commit `dc3801f`); its own
  footer says "Next review: Sprint 7" (never done; the platform is now at
  Sprint 9). Status: **STALE** — it documents a Docker Compose / Kubernetes
  self-hosted model (20 compose refs, 28 k8s refs, 0 Fly.io refs), which does
  not match the live managed deployment (Fly.io + Vercel + Neon per Magna
  Carta §"Deployment" and the `.github/workflows/deploy.yml` pipeline).
  Strategic Plan v2's intended layout separately reserves an
  `ops/deployment.md` as the "Fly.io / Vercel runbook," implying this file is
  superseded-in-intent by a doc that has not been written yet. Its generic
  procedures (rotation, incident response, rollback structure) may still be
  useful source material for that future doc.

**Note on the two `docs/` locations:** the strategy docs reference paths as
`docs/strategy/...` treating `docs/` as rooted at `platform/docs/`. The
root-level `docs/` is a separate, older location — now down to a single stale
file (`runbook.md`). Consolidation is a possible future housekeeping pass; as
of now both are documented here to prevent confusion.

## Known inconsistencies (to resolve deliberately, not silently)

- **Date stamps.** The strategy foundation documents are stamped "5 May 2026"
  while the actual calendar date of this review is 2026-07-03. This is a known
  discrepancy in the foundation docs, recorded here rather than silently
  edited. DrJ to decide whether to correct the foundation doc dates in a
  future amendment.
- **`runbook.md` is stale.** See its top banner. A real
  `platform/docs/ops/deployment.md` is owed and not yet written.
- **`LAUNCH_PLAN.md` disposition.** Reconciled against the May 5 audit and the
  live codebase on 2026-07-03 (see commit message); all concrete open items
  (500s, missing tables, discovery endpoints) verified resolved, so the file
  was **archived** to `platform/docs/audit/archive/LAUNCH_PLAN_2026-04-23.md`
  with no open items lost.

## Last reviewed

2026-07-03 — by DrJ, assisted by Claude Code. Next review: whenever a file's
status changes or a consolidation is decided.
