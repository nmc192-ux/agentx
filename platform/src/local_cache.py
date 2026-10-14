"""
AgentX Platform — In-process TTL cache (EG-3, Neon egress)
══════════════════════════════════════════════════════════
A small per-machine cache that needs no Redis. Two users:

  • ``src.cache`` falls back to it when Redis is disabled (production runs
    with ``REDIS_URL=memory://`` since the 9 Oct 2026 outage), so the trust
    score, agent profile, pulse and feed caches that already call
    ``cache_get``/``cache_set`` work again without Redis.
  • ``src.middleware.response_cache`` keeps whole anonymous responses of the
    heavy public lists for a few seconds.

Per machine, so a ``cache_delete`` on one Fly machine does not reach another;
that is why every entry's lifetime is capped (``LOCAL_CACHE_MAX_TTL``) — a
stale read is bounded to that many seconds. Bounded in size too: least
recently used entries go first.

``LOCAL_CACHE=off`` switches both users off (escape hatch).
"""
from __future__ import annotations

import os
import time
from collections import OrderedDict
from typing import Any

LOCAL_CACHE_MAX_TTL = 30        # seconds; bounds cross-machine staleness
LOCAL_CACHE_MAX_ENTRIES = 1000


def local_cache_enabled() -> bool:
    return os.getenv("LOCAL_CACHE", "on").strip().lower() not in ("off", "0", "false", "no")


class TTLCache:
    """Not thread-safe; used from one event loop. Values are stored as given,
    so callers that hand out mutable values must copy (``src.cache`` stores
    JSON strings, the response cache stores bytes)."""

    def __init__(self, max_entries: int = LOCAL_CACHE_MAX_ENTRIES,
                 max_ttl: float = LOCAL_CACHE_MAX_TTL, clock=time.monotonic,
                 max_bytes: int | None = None, size_of=None):
        """``max_bytes`` with ``size_of(value)`` adds a byte budget on top of
        the entry cap (SR-1): one value too big for the budget is not stored,
        and expired entries are swept before a live one is evicted for room."""
        self.max_entries = max_entries
        self.max_ttl = max_ttl
        self.max_bytes = max_bytes
        self._size_of = size_of or (lambda _v: 0)
        self._clock = clock
        self._data: OrderedDict[str, tuple[float, Any, int]] = OrderedDict()
        self._bytes = 0

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value, _size = item
        if self._clock() >= expires:
            self.delete(key)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        ttl = self.max_ttl if ttl is None else min(ttl, self.max_ttl)
        if ttl <= 0:
            return
        size = self._size_of(value) if self.max_bytes is not None else 0
        self.delete(key)
        if self.max_bytes is not None and size > self.max_bytes:
            return
        self._data[key] = (self._clock() + ttl, value, size)
        self._bytes += size
        if len(self._data) > self.max_entries or self._over_budget():
            self._sweep_expired()
        while self._data and (len(self._data) > self.max_entries or self._over_budget()):
            self.delete(next(iter(self._data)))

    def _over_budget(self) -> bool:
        return self.max_bytes is not None and self._bytes > self.max_bytes

    def _sweep_expired(self) -> None:
        now = self._clock()
        for key in [k for k, (exp, _v, _s) in self._data.items() if now >= exp]:
            self.delete(key)

    def delete(self, key: str) -> None:
        item = self._data.pop(key, None)
        if item is not None:
            self._bytes -= item[2]

    def delete_prefix(self, prefix: str) -> None:
        for key in [k for k in self._data if k.startswith(prefix)]:
            self.delete(key)

    def clear(self) -> None:
        self._data.clear()
        self._bytes = 0

    @property
    def bytes_used(self) -> int:
        return self._bytes

    def __len__(self) -> int:
        return len(self._data)


# Shared store behind src.cache when Redis is off.
store = TTLCache()
