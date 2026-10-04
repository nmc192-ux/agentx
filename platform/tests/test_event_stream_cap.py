"""
S9-6e: WS /events/stream takes no login and each open socket polls the
database once a second, so the number of sockets is capped per process.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services import events


def _socket():
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest.fixture(autouse=True)
def _empty_registry(monkeypatch):
    monkeypatch.setattr(events, "_connections", set())


async def test_socket_under_the_cap_is_accepted():
    ws = _socket()
    assert await events.register_connection(ws) is True
    ws.accept.assert_awaited_once()
    assert ws in events._connections


async def test_socket_over_the_cap_is_refused_before_accept(monkeypatch):
    monkeypatch.setattr(events, "MAX_STREAM_CONNECTIONS", 2)
    for _ in range(2):
        assert await events.register_connection(_socket()) is True

    extra = _socket()
    assert await events.register_connection(extra) is False
    extra.accept.assert_not_awaited()
    extra.close.assert_awaited_once_with(code=1013)
    assert extra not in events._connections
    assert len(events._connections) == 2


async def test_a_freed_slot_can_be_reused(monkeypatch):
    monkeypatch.setattr(events, "MAX_STREAM_CONNECTIONS", 1)
    first = _socket()
    assert await events.register_connection(first) is True
    assert await events.register_connection(_socket()) is False
    await events.unregister_connection(first)
    assert await events.register_connection(_socket()) is True
