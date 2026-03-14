"""
AgentX Event Bus
═════════════════
Phase 7: Event-Driven Architecture

Convenience re-exports for the most commonly used symbols.

Usage:
    from src.events import publish_event, EventType
    from src.events.consumer import run_consumer
    from src.events.handlers import HANDLERS
"""
from .publisher import publish_event, publish_event_sync
from .types import AgentXEvent, EventType

__all__ = [
    "publish_event",
    "publish_event_sync",
    "AgentXEvent",
    "EventType",
]
