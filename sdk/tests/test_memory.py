"""
agentx_sdk — MemoryNamespace unit tests (no live server required).

Uses respx to mock httpx requests at http://testserver — same pattern as
all other SDK namespace tests.

Coverage:
  - save()      — PUT /agents/{did}/memory/{key}
  - load()      — GET hit, 404 → None
  - list_keys() — GET /agents/{did}/memory
  - delete()    — DELETE hit → True, 404 → False
  - clear()     — DELETE /agents/{did}/memory → count
  - save_json() — serialises to JSON string then saves
  - load_json() — deserialises saved JSON string; handles native dict; handles None
  - _did()      — raises RuntimeError when identity is not set
"""
import json

import httpx
import pytest
import respx

from agentx_sdk import AgentXClient, AgentIdentity, MemoryNamespace
from agentx_sdk.exceptions import NotFoundError

# ── Helpers ───────────────────────────────────────────────────────────────────

BASE      = "http://testserver"
AGENT_DID = "did:agentx:testbot-001"


def make_client(with_identity: bool = True) -> AgentXClient:
    client = AgentXClient(api_key="test-key", base_url=BASE, max_retries=0)
    if with_identity:
        client.identity = AgentIdentity(agent_did=AGENT_DID, api_key="test-key")
    return client


def memory_entry(key: str = "my_key", value=None) -> dict:
    return {
        "memory_id":  "aabb0000-0000-0000-0000-000000000001",
        "agent_did":  AGENT_DID,
        "key":        key,
        "value":      value if value is not None else "stored-value",
        "created_at": "2026-03-22T12:00:00+00:00",
        "updated_at": "2026-03-22T12:00:00+00:00",
    }


# ── MemoryNamespace instantiation ─────────────────────────────────────────────

class TestMemoryNamespaceInit:
    def test_attached_to_client(self):
        client = make_client()
        assert isinstance(client.memory, MemoryNamespace)

    def test_did_raises_without_identity(self):
        client = make_client(with_identity=False)
        with pytest.raises(RuntimeError, match="registered identity"):
            client.memory._did()

    def test_did_returns_agent_did(self):
        client = make_client()
        assert client.memory._did() == AGENT_DID


# ── save() ────────────────────────────────────────────────────────────────────

class TestSave:
    @respx.mock
    def test_save_string_value(self):
        entry = memory_entry(key="task_id", value="abc-123")
        respx.put(f"{BASE}/agents/{AGENT_DID}/memory/task_id").mock(
            return_value=httpx.Response(200, json=entry)
        )
        result = make_client().memory.save("task_id", "abc-123")
        assert result["key"]   == "task_id"
        assert result["value"] == "abc-123"

    @respx.mock
    def test_save_dict_value(self):
        payload = {"step": 3, "score": 0.91}
        entry   = memory_entry(key="checkpoint", value=payload)
        respx.put(f"{BASE}/agents/{AGENT_DID}/memory/checkpoint").mock(
            return_value=httpx.Response(200, json=entry)
        )
        result = make_client().memory.save("checkpoint", payload)
        assert result["value"] == payload

    @respx.mock
    def test_save_integer_value(self):
        entry = memory_entry(key="counter", value=42)
        respx.put(f"{BASE}/agents/{AGENT_DID}/memory/counter").mock(
            return_value=httpx.Response(200, json=entry)
        )
        result = make_client().memory.save("counter", 42)
        assert result["value"] == 42

    @respx.mock
    def test_save_sends_put_request(self):
        entry = memory_entry()
        route = respx.put(f"{BASE}/agents/{AGENT_DID}/memory/my_key").mock(
            return_value=httpx.Response(200, json=entry)
        )
        make_client().memory.save("my_key", "stored-value")
        assert route.called

    @respx.mock
    def test_save_returns_full_entry(self):
        entry = memory_entry(key="k", value="v")
        respx.put(f"{BASE}/agents/{AGENT_DID}/memory/k").mock(
            return_value=httpx.Response(200, json=entry)
        )
        result = make_client().memory.save("k", "v")
        assert "memory_id"  in result
        assert "created_at" in result
        assert "updated_at" in result


# ── load() ────────────────────────────────────────────────────────────────────

class TestLoad:
    @respx.mock
    def test_load_returns_value_on_hit(self):
        entry = memory_entry(key="task_id", value="abc-123")
        respx.get(f"{BASE}/agents/{AGENT_DID}/memory/task_id").mock(
            return_value=httpx.Response(200, json=entry)
        )
        result = make_client().memory.load("task_id")
        assert result == "abc-123"

    @respx.mock
    def test_load_returns_none_on_404(self):
        respx.get(f"{BASE}/agents/{AGENT_DID}/memory/missing").mock(
            return_value=httpx.Response(404, json={"detail": "not found"})
        )
        result = make_client().memory.load("missing")
        assert result is None

    @respx.mock
    def test_load_unwraps_dict_value(self):
        payload = {"role": "user", "content": "hi"}
        entry   = memory_entry(key="msg", value=payload)
        respx.get(f"{BASE}/agents/{AGENT_DID}/memory/msg").mock(
            return_value=httpx.Response(200, json=entry)
        )
        result = make_client().memory.load("msg")
        assert result == payload

    @respx.mock
    def test_load_unwraps_list_value(self):
        payload = [1, 2, 3]
        entry   = memory_entry(key="nums", value=payload)
        respx.get(f"{BASE}/agents/{AGENT_DID}/memory/nums").mock(
            return_value=httpx.Response(200, json=entry)
        )
        result = make_client().memory.load("nums")
        assert result == [1, 2, 3]


# ── list_keys() ───────────────────────────────────────────────────────────────

class TestListKeys:
    @respx.mock
    def test_list_keys_returns_strings(self):
        respx.get(f"{BASE}/agents/{AGENT_DID}/memory").mock(
            return_value=httpx.Response(200, json=["a_key", "b_key", "c_key"])
        )
        result = make_client().memory.list_keys()
        assert result == ["a_key", "b_key", "c_key"]

    @respx.mock
    def test_list_keys_empty(self):
        respx.get(f"{BASE}/agents/{AGENT_DID}/memory").mock(
            return_value=httpx.Response(200, json=[])
        )
        result = make_client().memory.list_keys()
        assert result == []

    @respx.mock
    def test_list_keys_sends_get_request(self):
        route = respx.get(f"{BASE}/agents/{AGENT_DID}/memory").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().memory.list_keys()
        assert route.called


# ── delete() ──────────────────────────────────────────────────────────────────

class TestDelete:
    @respx.mock
    def test_delete_returns_true_on_success(self):
        respx.delete(f"{BASE}/agents/{AGENT_DID}/memory/old_key").mock(
            return_value=httpx.Response(204)
        )
        result = make_client().memory.delete("old_key")
        assert result is True

    @respx.mock
    def test_delete_returns_false_on_404(self):
        respx.delete(f"{BASE}/agents/{AGENT_DID}/memory/missing").mock(
            return_value=httpx.Response(404, json={"detail": "not found"})
        )
        result = make_client().memory.delete("missing")
        assert result is False

    @respx.mock
    def test_delete_sends_delete_request(self):
        route = respx.delete(f"{BASE}/agents/{AGENT_DID}/memory/k").mock(
            return_value=httpx.Response(204)
        )
        make_client().memory.delete("k")
        assert route.called


# ── clear() ───────────────────────────────────────────────────────────────────

class TestClear:
    @respx.mock
    def test_clear_returns_count(self):
        respx.delete(f"{BASE}/agents/{AGENT_DID}/memory").mock(
            return_value=httpx.Response(200, json={"deleted": 7})
        )
        count = make_client().memory.clear()
        assert count == 7

    @respx.mock
    def test_clear_returns_zero_when_empty(self):
        respx.delete(f"{BASE}/agents/{AGENT_DID}/memory").mock(
            return_value=httpx.Response(200, json={"deleted": 0})
        )
        count = make_client().memory.clear()
        assert count == 0

    @respx.mock
    def test_clear_sends_delete_to_collection_endpoint(self):
        route = respx.delete(f"{BASE}/agents/{AGENT_DID}/memory").mock(
            return_value=httpx.Response(200, json={"deleted": 0})
        )
        make_client().memory.clear()
        assert route.called


# ── save_json() ───────────────────────────────────────────────────────────────

class TestSaveJson:
    @respx.mock
    def test_save_json_serialises_dict(self):
        obj   = [{"role": "user", "content": "hello"}]
        entry = memory_entry(key="history", value=json.dumps(obj))
        route = respx.put(f"{BASE}/agents/{AGENT_DID}/memory/history").mock(
            return_value=httpx.Response(200, json=entry)
        )
        make_client().memory.save_json("history", obj)
        assert route.called
        sent_body = json.loads(route.calls[0].request.content)
        # value should be a JSON *string* (double-encoded)
        assert isinstance(sent_body["value"], str)
        assert json.loads(sent_body["value"]) == obj

    @respx.mock
    def test_save_json_serialises_list(self):
        obj   = [1, 2, 3]
        entry = memory_entry(key="nums", value=json.dumps(obj))
        respx.put(f"{BASE}/agents/{AGENT_DID}/memory/nums").mock(
            return_value=httpx.Response(200, json=entry)
        )
        result = make_client().memory.save_json("nums", obj)
        assert result["key"] == "nums"


# ── load_json() ───────────────────────────────────────────────────────────────

class TestLoadJson:
    @respx.mock
    def test_load_json_deserialises_string(self):
        obj   = [{"role": "assistant", "content": "hi"}]
        entry = memory_entry(key="history", value=json.dumps(obj))
        respx.get(f"{BASE}/agents/{AGENT_DID}/memory/history").mock(
            return_value=httpx.Response(200, json=entry)
        )
        result = make_client().memory.load_json("history")
        assert result == obj

    @respx.mock
    def test_load_json_returns_native_dict_as_is(self):
        """If the value is already a dict (saved via save(), not save_json()), return it."""
        obj   = {"step": 5}
        entry = memory_entry(key="checkpoint", value=obj)
        respx.get(f"{BASE}/agents/{AGENT_DID}/memory/checkpoint").mock(
            return_value=httpx.Response(200, json=entry)
        )
        result = make_client().memory.load_json("checkpoint")
        assert result == obj

    @respx.mock
    def test_load_json_returns_none_on_missing_key(self):
        respx.get(f"{BASE}/agents/{AGENT_DID}/memory/missing").mock(
            return_value=httpx.Response(404, json={"detail": "not found"})
        )
        result = make_client().memory.load_json("missing")
        assert result is None

    @respx.mock
    def test_load_json_returns_none_on_bad_json(self):
        """A value that cannot be parsed as JSON returns None gracefully."""
        entry = memory_entry(key="broken", value="not-valid-{json")
        respx.get(f"{BASE}/agents/{AGENT_DID}/memory/broken").mock(
            return_value=httpx.Response(200, json=entry)
        )
        result = make_client().memory.load_json("broken")
        assert result is None
