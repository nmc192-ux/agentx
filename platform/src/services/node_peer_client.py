"""
AgentX Platform — Node Peer Client
════════════════════════════════════
Phase 17: Low-level HTTP client for broadcasting events to individual peer nodes.

This module sends a single HTTP POST to a peer node's /nodes/events endpoint.
All network errors are caught and logged; the caller receives a boolean result.

Usage::

    from src.services.node_peer_client import post_event

    ok = await post_event(
        node_url="https://peer.agentx.io",
        event_type="CONTRACT_COMPLETED",
        payload={"contract_id": "..."},
    )
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT: float = 10.0  # seconds


async def post_event(
    node_url: str,
    event_type: str,
    payload: dict,
    source_node_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """POST a federated event to a peer node's /nodes/events endpoint.

    Args:
        node_url:        Base URL of the peer node (trailing slash stripped).
        event_type:      The event type string (e.g. "CONTRACT_COMPLETED").
        payload:         Arbitrary event payload dict.
        source_node_url: Optional URL identifying the originating node so the
                         recipient can correlate the sender.
        timeout:         HTTP request timeout in seconds.

    Returns:
        True  — if the peer responded with HTTP 2xx.
        False — on any network error or HTTP 4xx/5xx response.
    """
    url = node_url.rstrip("/") + "/nodes/events"
    body: dict = {
        "event_type": event_type,
        "payload": payload,
    }
    if source_node_url is not None:
        body["source_node_url"] = source_node_url

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body)

        if resp.status_code < 400:
            logger.debug(
                "node_peer_client: broadcast %s → %s OK (HTTP %d)",
                event_type,
                node_url,
                resp.status_code,
            )
            return True

        logger.warning(
            "node_peer_client: broadcast %s → %s failed (HTTP %d): %s",
            event_type,
            node_url,
            resp.status_code,
            resp.text[:200],
        )
        return False

    except httpx.TimeoutException:
        logger.warning(
            "node_peer_client: broadcast %s → %s timed-out after %.1fs",
            event_type,
            node_url,
            timeout,
        )
        return False

    except Exception as exc:
        logger.warning(
            "node_peer_client: broadcast %s → %s raised %s: %s",
            event_type,
            node_url,
            type(exc).__name__,
            exc,
        )
        return False
