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
      set, it replaces the Tier B / Tier C part of this list. That preserves
      the fast kill-switch: in a real production incident a router can be
      turned off in seconds via Fly.io, with no code deploy. The repo is the
      normal path; the env var is the emergency brake.
    • Tier A lock (Sprint 9, S9-4a) — the env var can switch routers OFF, but
      it can never switch a Tier A router (``BROKEN_OR_INSECURE_ROUTERS``) ON.
      Because the env value *replaces* the repo list, a short emergency value
      such as ``DISABLED_ROUTERS=contracts`` used to turn ON every router it
      did not name, the unsafe ones included. Tier A is now always added back
      (see ``effective_disabled_routers``). The only way to enable a Tier A
      router is to fix it and move it out of Tier A in this file, in a
      reviewed commit. Tests and the local smoke harness opt out with
      ``ALLOW_UNSAFE_ROUTERS=1``, which is honoured in development only.

The startup log states which source was used, the effective list and which
routers the Tier A lock forced off, so it is never a mystery in production
which path is active.

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

    # HARDENED (Sprint 9, S9-2), KEPT OFF ON PURPOSE: `POST /nodes/register` and
    # `POST /nodes/events` are now FOUNDER-only and peer URLs must be public
    # https (SSRF guard, re-checked before every outbound broadcast). Before
    # that, anyone could register a URL and this node would POST every
    # CONTRACT_COMPLETED / TASK_COMPLETED / BOUNTY_REWARD_DISTRIBUTED payload to
    # it — node_consumer runs whether or not this router is mounted.
    # Still disabled because federation has no signed-event protocol yet
    # (inbound events cannot be attributed to a peer; outbound ones are
    # unsigned) and nothing in Phase A needs it. Enable only once signed events
    # exist AND there is a real peer to federate with. (Phase D)
    "nodes",

    # CODE FIXED (Sprint 9), NOT PROD-READY: the missing `governance_votes`
    # table is now created by migration 039, and vote-casting returns 200 on a
    # correctly-migrated DB (verified locally). STILL DISABLED because
    # production's schema is divergent — governance also reads `stakes` (for
    # vote power), which prod lacks. Enable only after the production schema is
    # reconciled. See briefing_2026-07-04_chain.md.
    "governance",

    # NON-FUNCTIONAL, KEPT OFF ON PURPOSE (Sprint 9, S9-3): consensus tallies
    # read the baseline `votes` table (votes on PROPOSAL *posts*: post_id /
    # choice / weight), which no code writes to, so every snapshot is empty and
    # quorum can never be met. It cannot simply be pointed at `governance_votes`:
    # debates and snapshots are keyed on posts(post_id), while governance votes
    # are keyed on proposals(proposal_id) — two unrelated id spaces with
    # different vote values (FOR/AGAINST/ABSTAIN vs yes/no/abstain) and weights.
    # Also unresolved: any logged-in agent can open or advance a debate on any
    # proposal (no proposer / role check). Wiring it up means choosing ONE
    # proposal model (decision O10, debate + consensus in rooms) — a design
    # step, not a stabilisation fix. Never enable an empty router.
    "consensus",

    # CODE FIXED (Sprint 9), NOT PROD-READY: graph_service had two column/table
    # typos (`room_members`→`room_participants`, `followed_did`→`following_did`);
    # both fixed, /graph/constellation returns 200 locally. STILL DISABLED
    # because prod lacks the `rooms`/`room_participants` tables (migration 035 is
    # stamped-past on prod, so it won't create them). Enable only after the
    # production schema is reconciled. See briefing_2026-07-04_chain.md.
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


def effective_disabled_routers(configured: set[str], unlock_tier_a: bool = False) -> set[str]:
    """The routers that are really off: the configured list (env override or
    repo default) plus every Tier A router, whatever the configured list says.

    ``unlock_tier_a`` skips the lock. It exists for the test suite and the
    local smoke harness, which exercise Tier A routers on purpose; the caller
    (``config.Settings``) only passes True in development."""
    if unlock_tier_a:
        return set(configured)
    return set(configured) | set(BROKEN_OR_INSECURE_ROUTERS)
