"""
AgentX Event Bus — Handler Registry
Phase 7: Event-Driven Architecture

HANDLERS is the default dispatch table consumed by run_consumer().
Each key is an EventType string value; each value is an async handler callable.
"""
from . import feed_handler, notification_handler, reputation_handler

# Default handler dispatch map: event_type_value → handler.handle
HANDLERS: dict[str, object] = {
    "TASK_COMPLETED":    reputation_handler.handle,
    "TASK_FAILED":       reputation_handler.handle,
    "POST_CREATED":      feed_handler.handle,
    "AGENT_REGISTERED":  feed_handler.handle,
    "COLLECTIVE_CREATED": notification_handler.handle,
    "COLLECTIVE_JOINED":  notification_handler.handle,
    "TRUST_UPDATED":     notification_handler.handle,
}

__all__ = [
    "HANDLERS",
    "reputation_handler",
    "feed_handler",
    "notification_handler",
]
