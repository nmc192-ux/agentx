"""
AgentX Event Bus — Handler Registry
Phase 7: Event-Driven Architecture

HANDLERS is the default dispatch table consumed by run_consumer().
Each key is an EventType string value; each value is an async handler callable.

Step 5.1 additions:
  websocket_handler covers all economic / contract / governance events so
  SDK agents listening via client.listen_events() receive them in real time.
  Existing handlers (reputation, feed, notification) are unchanged; where
  an event type already had a handler AND needs WS forwarding, both are
  chained via _chain().
"""
from . import feed_handler, notification_handler, reputation_handler, websocket_handler


# ── Chain helper ───────────────────────────────────────────────────────────────

def _chain(*handlers):
    """Return a single async callable that invokes all *handlers* in order."""
    async def _multi(event):
        for h in handlers:
            try:
                await h(event)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "_chain: handler %s raised: %s", h, exc
                )
    return _multi


# ── Dispatch table ─────────────────────────────────────────────────────────────

HANDLERS: dict[str, object] = {
    # ── Pre-existing handlers (Step 5.1: unchanged) ───────────────────────────
    "TASK_COMPLETED":     reputation_handler.handle,
    "TASK_FAILED":        reputation_handler.handle,
    "POST_CREATED":       feed_handler.handle,
    "AGENT_REGISTERED":   feed_handler.handle,
    "COLLECTIVE_CREATED": notification_handler.handle,
    "COLLECTIVE_JOINED":  notification_handler.handle,
    "TRUST_UPDATED":      notification_handler.handle,

    # ── Step 5.1: Contract lifecycle → WS ────────────────────────────────────
    "CONTRACT_CREATED":           websocket_handler.handle,
    "CONTRACT_BID_SUBMITTED":     websocket_handler.handle,
    "CONTRACT_ASSIGNED":          websocket_handler.handle,
    "CONTRACT_RESULT_SUBMITTED":  websocket_handler.handle,
    "CONTRACT_COMPLETED":         websocket_handler.handle,
    "CONTRACT_DISPUTED":          websocket_handler.handle,

    # ── Step 5.1: Token economy → WS ─────────────────────────────────────────
    "TOKEN_TRANSFER":       websocket_handler.handle,
    "TASK_ESCROWED":        websocket_handler.handle,
    "TASK_REWARD_RELEASED": websocket_handler.handle,
    "STAKE_SLASHED":        websocket_handler.handle,

    # ── Step 5.1: Governance → WS (broadcast_global) ─────────────────────────
    "PROPOSAL_CREATED":  websocket_handler.handle,
    "VOTE_CAST":         websocket_handler.handle,
    "PROPOSAL_EXECUTED": websocket_handler.handle,

    # ── Step 5.1: Verification engine → WS ───────────────────────────────────
    "CONTRACT_VERIFICATION_REQUESTED": websocket_handler.handle,
    "VERIFICATION_SUBMITTED":          websocket_handler.handle,
    "CONTRACT_VERIFIED":               websocket_handler.handle,

    # ── Step 5.1: Bounty markets → WS ────────────────────────────────────────
    "BOUNTY_CREATED":            websocket_handler.handle,
    "BOUNTY_SUBMISSION":         websocket_handler.handle,
    "BOUNTY_EVALUATED":          websocket_handler.handle,
    "BOUNTY_REWARD_DISTRIBUTED": websocket_handler.handle,
}

__all__ = [
    "HANDLERS",
    "reputation_handler",
    "feed_handler",
    "notification_handler",
    "websocket_handler",
]
