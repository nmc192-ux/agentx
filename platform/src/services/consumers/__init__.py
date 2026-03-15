"""
AgentX — Service-Layer Event Consumers
════════════════════════════════════════
Phase 12.5: Event-Driven Service Architecture

These consumers form the service-layer event processing tier.  They subscribe
to the agentx.events Redis Stream via a *separate* consumer group
(``agentx-service-layer``) so every event is delivered to BOTH:

  • The Phase-7 handler group (``agentx-services``)  — feed/reputation/notifications
  • The Phase-12.5 service group (``agentx-service-layer``) — domain service calls

Consumer modules
────────────────
  contract_consumer      CONTRACT_COMPLETED, CONTRACT_RESULT_SUBMITTED
  economy_consumer       TASK_REWARD_RELEASED, TOKEN_TRANSFER, TREASURY_REWARD
  reputation_consumer    TASK_COMPLETED, CONTRACT_VERIFIED, VERIFICATION_SUBMITTED
  verification_consumer  CONTRACT_VERIFICATION_REQUESTED
"""
from . import (
    contract_consumer,
    economy_consumer,
    reputation_consumer,
    verification_consumer,
)

__all__ = [
    "contract_consumer",
    "economy_consumer",
    "reputation_consumer",
    "verification_consumer",
]
