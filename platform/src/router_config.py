"""
Router gating — version-controlled source of truth
═══════════════════════════════════════════════════

Which API routers are turned OFF is decided HERE, in the repo, where the
decision is readable, reviewable, and has a paper trail — not in an invisible
Fly.io environment variable.

How the two sources interact (see ``config.Settings.disabled_routers``):

    • Normal path — the repo default below (``DEFAULT_DISABLED_ROUTERS``)
      decides which routers are disabled.
    • Emergency override — if the ``DISABLED_ROUTERS`` environment variable is
      set, it *completely overrides* this list. That preserves the fast
      kill-switch: in a real production incident a router can be turned off in
      seconds via Fly.io, with no code deploy. The repo is the normal path;
      the env var is the emergency brake.

The startup log states which source was used and the effective list, so it is
never a mystery in production which path is active.

──────────────────────────────────────────────────────────────────────────────
PARITY NOTE (Sprint 9a — read before changing this list)
──────────────────────────────────────────────────────────────────────────────
This default is set to match what CURRENT PRODUCTION disables, so that moving
the decision into the repo causes ZERO change in which routers are actually on.
The set below is the LIVE production ``DISABLED_ROUTERS`` value, confirmed by
DrJ reading the running app on 2026-07-04 — 20 gated routers, ALL of them off,
including ``memory``. (The 5 May 2026 audit had inferred 19-with-memory-enabled;
DrJ's live read corrected that single point.) Enabling the audit-cleared routers
is the work of Sprint 9 proper (fix-then-enable), done deliberately — NOT here.

Three tiers of "disabled" are recorded separately so the distinctions are not lost:

  A. ``BROKEN_OR_INSECURE_ROUTERS`` — genuinely unsafe/broken; must stay off
     until the underlying defect is fixed (each fix is a Sprint 9 step).
  B. ``PARITY_HOLD_ROUTERS`` — the 5 May audit found these safe to enable, but
     they are OFF in production today. They are kept off here ONLY to preserve
     parity (zero behavior change on merge). Sprint 9 enables them.
  C. ``PARITY_UNEXPLAINED_ROUTERS`` — off in production for a reason not yet
     established (currently: ``memory``, a core primitive). Held off for parity;
     the "why" is a Sprint 9 investigation, not a 9a assumption.

Constitutional anchor: magna_carta_v1.md, Article 24 Principle 4 — honest
accountability; every decision leaves a record.
"""

# ── Tier A — broken or insecure. Keep OFF until fixed (Sprint 9). ──────────────
BROKEN_OR_INSECURE_ROUTERS = [
    # SECURITY: `POST /markets/bounties/auto` takes agent_did from the request
    # body with no JWT, then escrows tokens from that agent's wallet — any
    # anonymous caller can drain any agent's wallet. Re-enable ONLY after the
    # wallet-auth fix lands and is reviewed by DrJ as security code. (Sprint 9)
    "agent_economy",

    # SECURITY: node register / event-injection endpoints are intentionally
    # unauthenticated; hardening (signature verification, mandatory auth) is
    # deferred in code. Re-enable after hardening lands. (Sprint 9)
    "nodes",

    # BROKEN: vote casting 500s — the service writes to a `governance_votes`
    # table that no migration creates (silent name collision with the baseline
    # `votes` table). Re-enable after the migration lands. (Sprint 9)
    "governance",

    # NON-FUNCTIONAL: consensus tallies read a `votes` table that nothing
    # writes to (governance's votes go to the nonexistent `governance_votes`),
    # so results are permanently empty. Coupled to the governance fix. (Sprint 9)
    "consensus",

    # BROKEN: the default `GET /graph/constellation` call 500s — graph_service
    # JOINs a nonexistent `room_members` table (the table is `room_participants`).
    # Re-enable after the one-line typo fix. (Sprint 9)
    "graph",
]

# ── Tier B — parity hold. Audit-cleared, but OFF in production today. ──────────
# Kept OFF here solely to preserve zero-behavior-change on merge. Sprint 9
# enables these deliberately (in cohorts: token stack together, social stack
# together) after confirming production is at alembic head. Removing an entry
# from this list is a Sprint 9 action, not a 9a action.
PARITY_HOLD_ROUTERS = [
    "tasks",
    "collectives",
    "communities",
    "contracts",
    "wallets",
    "stakes",
    "economy",
    "agentbus",
    "verifications",
    "markets",
    "conversations",
    "channels",
    "rooms",
    "pulse",
]

# ── Tier C — disabled in production for a reason not yet established. ──────────
# `memory` is disabled in production (confirmed by DrJ reading the live value on
# 2026-07-04). This was NOT anticipated: memory is one of the magna carta's seven
# core primitives, so its being off is notable and needs explaining. Held off
# here to preserve parity; the "why" is a Sprint 9 investigation.
PARITY_UNEXPLAINED_ROUTERS = [
    # disabled to match production; reason TBD — see Sprint 9
    "memory",
]

# The effective repo default = all three tiers. Order is cosmetic; gating is by
# membership. Matches the live production DISABLED_ROUTERS set confirmed by DrJ
# on 2026-07-04 (20 routers, memory included).
DEFAULT_DISABLED_ROUTERS = (
    BROKEN_OR_INSECURE_ROUTERS
    + PARITY_HOLD_ROUTERS
    + PARITY_UNEXPLAINED_ROUTERS
)


def default_disabled_routers_csv() -> str:
    """Repo-default disabled list as the comma-separated string the
    ``disabled_routers`` setting expects. Used as the field default so the
    ``DISABLED_ROUTERS`` env var (if set) transparently overrides it."""
    return ",".join(DEFAULT_DISABLED_ROUTERS)
