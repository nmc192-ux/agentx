"""
AgentX Platform — Agent-Created (Auto) Bounty Service
══════════════════════════════════════════════════════
Phase 19: Autonomous Agent Economies.

Allows agents to autonomously publish capability bounties without a
human operator.  This thin service wraps the existing bounty_service so
that the POST /markets/bounties/auto endpoint can accept the agent's DID
in the request body rather than from a JWT bearer token.

Public API
──────────
  create_agent_bounty(agent_did, capability, reward_pool, *,
                      title, description)  → BountyResponse

Design notes
────────────
• Fully delegates to bounty_service.create_bounty(), which handles
  wallet escrow, ledger entries, and event publishing.
• reward_pool is clamped to a minimum of 1 (BountyCreate requires ge=1).
• No new DB tables — uses existing capability_bounties table.
"""
from __future__ import annotations

import logging

from ...models.markets import BountyCreate, BountyResponse
from .bounty_service import create_bounty

logger = logging.getLogger(__name__)

_DEFAULT_DESCRIPTION = "Autonomously created work request."


async def create_agent_bounty(
    agent_did: str,
    capability: str,
    reward_pool: int,
    *,
    title: str | None = None,
    description: str | None = None,
) -> BountyResponse:
    """
    Autonomously create a capability bounty on behalf of an agent.

    The agent DID is used as the bounty creator; the agent's wallet is
    debited by *reward_pool* tokens to escrow the prize (soft-fail if the
    wallet has insufficient funds or doesn't exist — see bounty_service).

    Args:
        agent_did:   DID of the agent creating the bounty.
        capability:  Capability tag that solvers must possess.
        reward_pool: Token prize pool (clamped to ≥ 1).
        title:       Optional bounty title; auto-generated if omitted.
        description: Optional description; defaults to a generic message.

    Returns:
        BountyResponse with status='open'.

    Raises:
        ValueError: Delegated from bounty_service (e.g. insufficient funds).
    """
    effective_title = title or f"Auto-generated {capability} task"
    effective_desc  = description or f"{_DEFAULT_DESCRIPTION} Capability: {capability}."
    effective_pool  = max(1, reward_pool)

    data = BountyCreate(
        title=effective_title,
        description=effective_desc,
        capability_required=capability,
        reward_pool=effective_pool,
    )

    logger.info(
        "auto_bounty_service: agent %s creating bounty for capability=%s pool=%d",
        agent_did, capability, effective_pool,
    )

    return await create_bounty(caller_did=agent_did, data=data)
