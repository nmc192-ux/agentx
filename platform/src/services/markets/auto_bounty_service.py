"""
AgentX Platform — Agent-Created (Auto) Bounty Service
══════════════════════════════════════════════════════
Phase 19: Autonomous Agent Economies.

Allows agents to autonomously publish capability bounties without a
human operator.  This thin service wraps the existing bounty_service: it
fills in a default title and description, nothing else. The creator is the
DID the router passes in, which is always the JWT-authenticated caller —
never a value from the request body.

Public API
──────────
  create_agent_bounty(agent_did, capability, reward_pool, *,
                      title, description)  → BountyResponse

Design notes
────────────
• Fully delegates to bounty_service.create_bounty(), which escrows the
  pool from the creator's wallet in the same transaction as the create
  (no wallet / insufficient funds → ValueError, no bounty), writes the
  ledger entry and publishes the event.
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
    debited by *reward_pool* tokens to escrow the prize. If the wallet is
    missing or cannot cover the pool, ValueError is raised and no bounty is
    created (see bounty_service.create_bounty).

    Args:
        agent_did:   DID of the agent creating the bounty (the authenticated
                     caller; the router never takes it from the body).
        capability:  Capability tag that solvers must possess.
        reward_pool: Token prize pool (clamped to ≥ 1).
        title:       Optional bounty title; auto-generated if omitted.
        description: Optional description; defaults to a generic message.

    Returns:
        BountyResponse with status='open'.

    Raises:
        ValueError: Delegated from bounty_service (creator not found, no
                    wallet, or insufficient funds).
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
