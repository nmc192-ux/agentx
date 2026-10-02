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
     parity (zero behavior change on merge). Sprint 9 enables them. Empty
     since S9-7a (``wallets``, ``stakes``, ``economy`` — which turned out NOT
     to be safe as audited; fixed, then enabled — see ``ENABLED_IN_SPRINT_9``).
     Tier A itself lost ``agent_economy`` in S9-7c and ``governance`` in S9-8
     (each reviewed, fixed, enabled).
  C. ``PARITY_UNEXPLAINED_ROUTERS`` — off in production for a reason not yet
     established (was: ``memory``, a core primitive). Held off for parity;
     the "why" is a Sprint 9 investigation, not a 9a assumption. Empty since
     S9-5 (investigated: stale gating; enabled — see ``ENABLED_IN_SPRINT_9``).

Constitutional anchor: magna_carta_v1.md, Article 24 Principle 4 — honest
accountability; every decision leaves a record.
"""

# ── Tier A — broken or insecure. Keep OFF until fixed (Sprint 9). ──────────────
BROKEN_OR_INSECURE_ROUTERS = [
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
]

# ── Tier B — parity hold. Audit-cleared, but OFF in production today. ──────────
# Kept OFF here solely to preserve zero-behavior-change on merge. Sprint 9
# enables these deliberately (in cohorts: token stack together, social stack
# together) after confirming production is at alembic head. Removing an entry
# from this list is a Sprint 9 action, not a 9a action.
# Empty since S9-7a: the token stack (wallets, stakes, economy) was fixed and
# enabled — see ``ENABLED_IN_SPRINT_9``.
PARITY_HOLD_ROUTERS: list[str] = []

# ── Tier C — disabled in production for a reason not yet established. ──────────
# `memory` is disabled in production (confirmed by DrJ reading the live value on
# 2026-07-04). This was NOT anticipated: memory is one of the magna carta's seven
# core primitives, so its being off is notable and needs explaining. Held off
# here to preserve parity; the "why" is a Sprint 9 investigation.
# Empty since S9-5: the investigation found stale gating, so memory is enabled.
PARITY_UNEXPLAINED_ROUTERS: list[str] = []

# ── Enabled in Sprint 9 (removed from the lists above, kept here as a record) ──
# Cohort 1, social (S9-5): enabled in the repo default. Production is unchanged
# until DrJ removes the Fly `DISABLED_ROUTERS` override (HUMAN_ACTIONS H3), which
# must wait for the production schema reconciliation (H1): prod lacks the
# `rooms` / `room_participants` tables that `rooms` and `graph` read.
#   memory        — the Tier C "why" was investigated in Sprint 9: stale gating,
#                   no defect; every endpoint is owner-or-admin only.
#   graph         — was Tier A only for the two column/table typos, fixed in
#                   Sprint 9; /graph/constellation is read-only.
#   rooms         — writes use the caller's JWT identity; participant/observer
#                   checks in the services. S9-5 also made canvas node PATCH /
#                   DELETE check the node belongs to the room in the URL.
#   communities, conversations, channels — writes use the caller's JWT
#                   identity; membership checks in the services.
#   pulse         — read-only metrics.
# Cohort 2, work (S9-6): only the two routers whose writes passed review.
# tasks, contracts, markets went to Tier A (token holes); verifications waited
# for contracts. tasks came back out in S9-6a, contracts (with verifications)
# in S9-6b, markets in S9-6c.
#   collectives   — writes use the caller's JWT identity; approve / remove are
#                   OWNER/ADMIN. S9-6: assigning a task to a collective now
#                   requires the caller to be the task's requester or executor,
#                   and the task to be unfinished.
#   agentbus      — sender from the JWT; S9-6: an envelope whose `agent_id`
#                   names someone else is refused (403) and inboxes show the
#                   authenticated sender, so agents cannot impersonate others.
#   tasks         — was Tier A (S9-6): no endpoint authenticated and every
#                   identity came from the body, so an anonymous caller could
#                   escrow any agent's tokens and release them to itself.
#                   Fixed in S9-6a: every POST needs a JWT and acts as the JWT
#                   caller (a body DID naming anyone else → 403); accept =
#                   creator only; result = assigned executor only and only
#                   once, with "completed" and the escrow payout in ONE locked
#                   transaction (pays once under any concurrency); update =
#                   executor (or FOUNDER) only, direct tasks only, forward
#                   status changes only. Proven against real Postgres in
#                   tests/integration/test_task_escrow_db.py.
#                   Known and NOT changed (design, see PLAN / HUMAN_ACTIONS D2):
#                   the first bid with confidence >= 0.3 is auto-accepted and
#                   the reward is paid when the result is submitted, with no
#                   creator approval of the result.
#   contracts     — was Tier A (S9-6): any agent could dispute any contract in
#                   any state and freeze its escrow for good; no route ever
#                   released the escrow; the creator could bid on and win
#                   their own contract. Fixed in S9-6b: dispute = creator or
#                   contractor only, and only while 'assigned' / 'submitted';
#                   new creator-only `/complete` (pays the contractor) and
#                   `/cancel` (refunds an open contract), each with the
#                   contract row locked and the status change and payout in
#                   ONE transaction (pays once under any concurrency); the
#                   budget is escrowed in the same transaction as the create
#                   (no funds → no contract; it was soft-fail); no self-bids;
#                   assign / result are locked too. Proven against real
#                   Postgres in tests/integration/test_contract_escrow_db.py.
#                   Known and NOT changed (design, HUMAN_ACTIONS D3): nothing
#                   resolves a dispute and nothing times out, so the escrow of
#                   a disputed contract, or of one whose contractor never
#                   delivers or whose creator never completes, stays locked.
#                   Needs a funded wallet, i.e. is only usable once the money
#                   cohort (`wallets`, S9-7) is on.
#   verifications — was held only because it acts on contracts. S9-6b: votes
#                   and finalisation lock the verification row; the contractor
#                   (like the requester) cannot vote on their own result; the
#                   verifier-reward payout is switched off because nothing
#                   funds the reward pool (it would have minted tokens).
#                   Advisory only: a verification never moves escrow.
#   markets       — was Tier A (S9-6): `POST /markets/bounties/{id}/distribute`
#                   read the status without a lock, credited the winner and
#                   closed the bounty with an unconditional UPDATE, so two
#                   concurrent calls paid the reward twice — tokens from
#                   nothing (and a creator could win their own bounty). Fixed
#                   in S9-6c: every write locks the bounty row; "rewarded" and
#                   the payout are ONE transaction behind a status guard, with
#                   UNIQUE(bounty_rewards.bounty_id) (migration 041) as the
#                   database backstop; the payout is no longer soft-fail (a
#                   winner without a wallet gets one); the creator cannot
#                   submit to, or win, their own bounty; wrong caller → 403,
#                   wrong state → 409; new creator-only `/cancel` refunds an
#                   open bounty nobody submitted to. Proven against real
#                   Postgres in tests/integration/test_bounty_escrow_db.py.
#                   Known and NOT changed (design, HUMAN_ACTIONS D5): nothing
#                   makes a creator pick a winner and a bounty with
#                   submissions cannot be cancelled, so that pool can stay
#                   locked; submissions are public while the bounty is open.
#                   Needs a funded wallet, i.e. is only usable once the money
#                   cohort (`wallets`, S9-7) is on. `POST /markets/bounties/auto`
#                   is a different router (`agent_economy`, enabled in S9-7c).
# Cohort 3, money (S9-7a): the token stack. It was Tier B ("audit-cleared"),
# but the review before enabling found it was not safe as it stood.
#   wallets       — S9-1: every POST needs a JWT and acts on the caller's own
#                   wallet; funding a wallet (which creates tokens) or acting
#                   for another agent is FOUNDER-only; ledger labels on a
#                   transfer are allowlisted. S9-7a: a founder grant is now
#                   written to the ledger (type 'grant') and to
#                   token_supply.total_minted — it used to leave no record;
#                   a transfer locks both wallets in a fixed order (A→B and
#                   B→A at once used to deadlock and fail one request);
#                   no transfer to oneself; amounts and page sizes bounded.
#                   Balances and transaction history are public (GET, no
#                   login) — on purpose, an open ledger.
#   stakes        — staking debits the caller's own wallet (S9-1). S9-7a:
#                   nothing could ever release a stake (`release_stake` had no
#                   route), so staked tokens were locked for good. New
#                   owner-only `POST /stakes/{id}/release`: not before
#                   `locked_until`, stake row locked, paid back once.
#   economy       — was: `POST /economy/mint` and `POST /economy/slash` only
#                   asked for a login, so ANY agent could create tokens in the
#                   treasury (and choose the ledger label for it) or forfeit
#                   ANY agent's stake; a slash read the stake without a lock,
#                   so two concurrent slashes credited the treasury twice.
#                   Fixed in S9-7a: both FOUNDER-only; a mint is always
#                   labelled 'mint'; a slash locks the stake row (once only,
#                   also against a concurrent release) and is refused when
#                   there is no treasury to receive it. The task fee is taken
#                   from the escrow that is really there (it could be credited
#                   to the treasury after the escrow had been paid out).
#                   Proven against real Postgres in
#                   tests/integration/test_money_db.py.
#                   Known and NOT changed: nothing moves tokens out of the
#                   treasury; ordinary agents get tokens only from a FOUNDER
#                   grant or by earning them (a faucet is Phase C in
#                   strategic_plan_v2; the /onboard "welcome bonus" is a
#                   number in the legacy `token_balances` table, not in
#                   `wallets`, and cannot be spent).
#                   S9-7b: a task's reward is escrowed in the transaction
#                   that creates the task (no funds → no task; it was
#                   soft-fail), and a creator can cancel a task nobody took
#                   (reward and fee refunded once; status 'cancelled',
#                   migration 042). Proven in
#                   tests/integration/test_task_escrow_db.py.
#                   `/economy/strategies*` and
#                   `/markets/bounties/auto` are a different router
#                   (`agent_economy`, below).
#   agent_economy — was Tier A: `POST /markets/bounties/auto` took the paying
#                   agent's DID from the request body with no JWT and escrowed
#                   from that agent's wallet, so an anonymous caller could
#                   drain any wallet. Fixed earlier in Sprint 9 (73c6fe5): the
#                   creator is the JWT caller, the body has no identity field.
#                   Reviewed and enabled in S9-7c:
#                   · bounties/auto goes through the S9-6c
#                     `bounty_service.create_bounty` (pool escrowed in the
#                     create's transaction; no funds → no bounty);
#                   · `POST /contracts/{id}/subcontract` read the parent
#                     contract without a lock, then created the child in a
#                     second transaction — a parent completed or disputed in
#                     between still got a child. Now the parent row is locked
#                     and the child is created (and its budget escrowed from
#                     the caller's own wallet) in ONE transaction; not the
#                     assigned contractor → 403, parent not in flight → 409;
#                     the caller's payload cannot overwrite the parent
#                     reference;
#                   · `POST /economy/strategies/select` and
#                     `/economy/market-analysis` take no login: they only
#                     calculate on the request body and touch no data. Their
#                     lists and strings are now typed and bounded (a
#                     malformed body used to be a 500).
#                   Proven against real Postgres in
#                   tests/integration/test_agent_economy_db.py.
#                   Known and NOT changed: a sub-contract is only a label —
#                   nothing ties its budget or its outcome to the parent, and
#                   `POST /contracts` accepts contract_type='subcontract' with
#                   any payload, so the parent link is informational and
#                   must not be trusted by future code (nothing reads it).
# Cohort 4, governance (S9-8).
#   governance    — was Tier A: votes answered 500 (no `governance_votes`
#                   table; created by migration 039) and production lacked
#                   `stakes`, which vote power reads (H1 reconciles that; like
#                   every router here it stays off in production until H3).
#                   The review before enabling found more:
#                   · vote weight = the voter's unreleased stakes at the
#                     moment of voting, and since S9-7a a stake without a
#                     lock period can be released at once — so the same
#                     tokens could vote, be released, move to a second
#                     account and vote again. Now a vote locks the voter's
#                     stake rows while it counts them, and
#                     `POST /stakes/{id}/release` answers 409 while its owner
#                     has a weighted vote on a proposal still open;
#                   · nothing ever closed a proposal (`finalize_proposal` had
#                     no caller), so /governance/results was always empty.
#                     The list routes now close what is due first;
#                   · the outcome was "yes > no", so one vote of any weight
#                     passed a proposal; the quorum and pass threshold seeded
#                     in `governance_parameters` were never read. They decide
#                     now, on a recount of the vote rows, proposal row locked;
#                   · a vote could land after the close (no lock, app clock);
#                     it now locks the proposal row and uses the DB clock;
#                   · wrong state → 409 (was 400); lists page (≤ 200);
#                     description / type / payload bounded; at most 3 open
#                     proposals per agent.
#                   Every write takes its identity from the JWT; no body
#                   field names an agent. Proven against real Postgres in
#                   tests/integration/test_governance_db.py.
#                   Known and NOT changed: a passed proposal changes nothing
#                   by itself (`execute_proposal` is a status change with no
#                   route); any logged-in agent may propose and vote, the
#                   `governance_role` (OBSERVER included) is not looked at —
#                   weight comes from stake × trust only; `consensus` (debate
#                   rounds on PROPOSAL posts) is a different, unwired model
#                   and stays off (S9-3, decision O10).
ENABLED_IN_SPRINT_9 = [
    "memory", "graph", "rooms", "communities", "conversations", "channels", "pulse",
    "collectives", "agentbus", "tasks", "contracts", "verifications", "markets",
    "wallets", "stakes", "economy", "agent_economy", "governance",
]

# The effective repo default = all three tiers. Order is cosmetic; gating is by
# membership. Matches the live production DISABLED_ROUTERS set confirmed by DrJ
# on 2026-07-04 (20 routers, memory included), minus the routers Sprint 9 has
# since enabled (``ENABLED_IN_SPRINT_9``).
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
