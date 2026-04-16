"""AgentX SDK — Memory namespace for server-side persistent key-value storage.

Agents can persist arbitrary JSON values across process restarts using the
platform's ``agent_memory`` table.  The namespace is accessed as
``client.memory``.

Usage::

    client.memory.save("last_task_id", "abc-123")
    client.memory.save_json("history", [{"role": "user", "content": "hi"}])

    # ... agent restarts ...

    last_task = client.memory.load("last_task_id")
    history   = client.memory.load_json("history")

All methods use the authenticated agent's DID (``client.identity.agent_did``)
as the namespace — each agent only sees its own memory.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    from .client import AgentXClient


class MemoryNamespace:
    """Server-side key-value memory — accessed as ``client.memory``.

    Every method uses the current agent's DID as the memory namespace so
    agents can never accidentally read or overwrite each other's state.

    Args:
        client: The parent :class:`~agentx_sdk.AgentXClient` instance.
    """

    def __init__(self, client: AgentXClient) -> None:
        self._client = client

    # ── Internal ─────────────────────────────────────────────────────────────

    def _did(self) -> str:
        """Return the authenticated agent's DID (raises if not set)."""
        identity = self._client.identity
        if identity is None:
            raise RuntimeError(
                "client.memory requires a registered identity. "
                "Call client.register_agent() or pass identity_path= to AgentXClient."
            )
        return identity.agent_did

    # ── Core operations ───────────────────────────────────────────────────────

    def save(self, key: str, value: Any) -> dict:
        """Persist *value* under *key* for the current agent (upsert).

        Creates the entry if it does not exist; overwrites if it does.

        Args:
            key:   Arbitrary string key (e.g. ``"last_task_id"``).
            value: Any JSON-serialisable value — string, int, list, dict, etc.

        Returns:
            The raw ``MemoryEntry`` dict from the platform
            (``memory_id``, ``key``, ``value``, ``created_at``, ``updated_at``).

        Example::

            client.memory.save("checkpoint", {"step": 3, "score": 0.91})
        """
        did = self._did()
        return self._client._put(f"/agents/{did}/memory/{key}", {"value": value})

    def load(self, key: str) -> Optional[Any]:
        """Load the value stored under *key*.

        Args:
            key: The key to retrieve.

        Returns:
            The stored value (any JSON type), or ``None`` if the key does
            not exist.

        Example::

            step = client.memory.load("checkpoint")
            if step is None:
                step = 0
        """
        from .exceptions import NotFoundError
        did = self._did()
        try:
            entry = self._client._get(f"/agents/{did}/memory/{key}")
            return entry.get("value")
        except NotFoundError:
            return None

    def list_keys(self) -> list[str]:
        """Return all stored keys for the current agent, sorted alphabetically.

        Returns:
            A list of key strings.  Empty list if no memory has been saved.

        Example::

            keys = client.memory.list_keys()
            # ["checkpoint", "last_task_id", "session_id"]
        """
        did = self._did()
        raw = self._client._get(f"/agents/{did}/memory")
        # The endpoint returns list[str] directly
        return raw if isinstance(raw, list) else []

    def delete(self, key: str) -> bool:
        """Delete the entry stored under *key*.

        Args:
            key: The key to delete.

        Returns:
            ``True`` if the key existed and was deleted.
            ``False`` if the key was not found.

        Example::

            client.memory.delete("old_session")
        """
        from .exceptions import NotFoundError
        did = self._did()
        try:
            self._client._delete(f"/agents/{did}/memory/{key}")
            return True
        except NotFoundError:
            return False

    def clear(self) -> int:
        """Delete ALL memory entries for the current agent.

        Returns:
            The number of entries deleted.

        Example::

            removed = client.memory.clear()
            print(f"Cleared {removed} memory entries")
        """
        did = self._did()
        result = self._client._delete(f"/agents/{did}/memory")
        # Backend returns {"deleted": N}
        return result.get("deleted", 0) if isinstance(result, dict) else 0

    # ── JSON convenience helpers ───────────────────────────────────────────────

    def save_json(self, key: str, obj: Union[dict, list]) -> dict:
        """Serialise *obj* to a JSON string and save it under *key*.

        Equivalent to ``save(key, json.dumps(obj))`` — use when you want to
        be explicit about storing JSON-encoded text rather than a native dict.

        Args:
            key: The key to store under.
            obj: A ``dict`` or ``list`` to serialise.

        Returns:
            The raw ``MemoryEntry`` dict from the platform.

        Example::

            client.memory.save_json("history", [{"role": "user", "content": "hi"}])
        """
        return self.save(key, json.dumps(obj))

    def load_json(self, key: str) -> Optional[Union[dict, list]]:
        """Load a value saved with :meth:`save_json` and deserialise it.

        Args:
            key: The key to retrieve.

        Returns:
            The deserialised ``dict`` or ``list``, or ``None`` if the key
            does not exist or the value cannot be parsed as JSON.

        Example::

            history = client.memory.load_json("history") or []
        """
        raw = self.load(key)
        if raw is None:
            return None
        if isinstance(raw, (dict, list)):
            # Saved natively (not via save_json) — return as-is
            return raw
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None
