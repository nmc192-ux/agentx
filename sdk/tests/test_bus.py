"""
agentx_sdk — BusNamespace unit tests (no live server required).

Uses respx to mock httpx requests at http://testserver.

Coverage:
  - send()               — POST /agentbus/send with receiver_did
  - broadcast()          — POST /agentbus/send without receiver_did
  - receive()            — GET /agentbus/inbox with pagination + filters
  - _validate_type()     — raises ValueError on unknown ACP type
  - _build_envelope()    — correct ACP-1.0 fields, UUID, timestamp
  - _did()               — raises RuntimeError when identity not set
  - ACPMessage model     — protocol_version, type, agent_id validators
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

import httpx
import pytest
import respx

from agentx_sdk import AgentXClient, AgentIdentity, ACPMessage
from agentx_sdk.bus import ALLOWED_TYPES, ACP_VERSION, BusNamespace

# ── Fixtures ───────────────────────────────────────────────────────────────────

BASE      = "http://testserver"
AGENT_DID = "did:agentx:testbot-001"
OTHER_DID = "did:agentx:other-001"


def _client_with_identity() -> AgentXClient:
    client = AgentXClient(api_key="test-token", base_url=BASE)
    client.identity = AgentIdentity(
        agent_did=AGENT_DID,
        api_key="test-token",
        display_name="TestBot",
    )
    return client


def _acp_response(**overrides) -> dict:
    base = {
        "protocol_version": ACP_VERSION,
        "message_id":       str(uuid.uuid4()),
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "agent_id":         AGENT_DID,
        "type":             "task_request",
        "human_summary":    "Please process this task",
        "machine_payload":  {"priority": "high"},
        "metadata":         {},
        "receiver_did":     OTHER_DID,
        "channel":          "default",
    }
    base.update(overrides)
    return base


# ── BusNamespace._did() ───────────────────────────────────────────────────────

def test_did_raises_when_no_identity():
    client = AgentXClient(api_key="tok", base_url=BASE)
    bus = BusNamespace(client)
    with pytest.raises(RuntimeError, match="register_agent"):
        bus._did()


def test_did_returns_agent_did():
    client = _client_with_identity()
    assert client.bus._did() == AGENT_DID


# ── _validate_type() ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("msg_type", sorted(ALLOWED_TYPES))
def test_all_valid_types_pass_validation(msg_type: str):
    client = _client_with_identity()
    client.bus._validate_type(msg_type)   # must not raise


def test_unknown_type_raises_value_error():
    client = _client_with_identity()
    with pytest.raises(ValueError, match="hack_the_planet"):
        client.bus._validate_type("hack_the_planet")


# ── _build_envelope() ─────────────────────────────────────────────────────────

def test_envelope_has_correct_acp_fields():
    client = _client_with_identity()
    env = client.bus._build_envelope(
        message_type="task_request",
        human_summary="Do some work",
        machine_payload={"x": 1},
        receiver_did=OTHER_DID,
        channel="ops",
        metadata={"trace": "abc"},
    )
    assert env["protocol_version"] == ACP_VERSION
    assert env["agent_id"] == AGENT_DID
    assert env["type"] == "task_request"
    assert env["receiver_did"] == OTHER_DID
    assert env["channel"] == "ops"
    assert env["metadata"] == {"trace": "abc"}
    # message_id must be a valid UUID string
    uuid.UUID(env["message_id"])


def test_envelope_receiver_none_for_broadcast():
    client = _client_with_identity()
    env = client.bus._build_envelope(
        message_type="system_event",
        human_summary="Broadcast",
        machine_payload={},
        receiver_did=None,
        channel="default",
        metadata=None,
    )
    assert env["receiver_did"] is None
    assert env["metadata"] == {}


# ── send() ────────────────────────────────────────────────────────────────────

@respx.mock
def test_send_posts_acp_envelope_to_agentbus():
    client = _client_with_identity()
    response_data = _acp_response()

    respx.post(f"{BASE}/agentbus/send").mock(
        return_value=httpx.Response(201, json=response_data)
    )

    result = client.bus.send(
        to_did=OTHER_DID,
        message_type="task_request",
        human_summary="Please process this task",
        machine_payload={"priority": "high"},
    )

    assert result["type"] == "task_request"
    assert result["receiver_did"] == OTHER_DID
    assert result["protocol_version"] == ACP_VERSION

    # Verify correct fields were POSTed
    sent_body = json.loads(respx.calls.last.request.content)
    assert sent_body["agent_id"] == AGENT_DID
    assert sent_body["receiver_did"] == OTHER_DID
    assert sent_body["type"] == "task_request"


@respx.mock
def test_send_uses_default_channel_and_empty_metadata():
    client = _client_with_identity()
    respx.post(f"{BASE}/agentbus/send").mock(
        return_value=httpx.Response(201, json=_acp_response())
    )

    client.bus.send(OTHER_DID, "task_bid", "My bid is 50 AXP")

    sent = json.loads(respx.calls.last.request.content)
    assert sent["channel"] == "default"
    assert sent["metadata"] == {}
    assert sent["machine_payload"] == {}


@respx.mock
def test_send_with_custom_channel_and_metadata():
    client = _client_with_identity()
    respx.post(f"{BASE}/agentbus/send").mock(
        return_value=httpx.Response(201, json=_acp_response())
    )

    client.bus.send(
        OTHER_DID,
        "task_assignment",
        "Assigning task 42",
        machine_payload={"task_id": "42"},
        channel="ops",
        metadata={"priority": "high"},
    )

    sent = json.loads(respx.calls.last.request.content)
    assert sent["channel"] == "ops"
    assert sent["metadata"] == {"priority": "high"}
    assert sent["machine_payload"] == {"task_id": "42"}


def test_send_rejects_invalid_type_before_network():
    client = _client_with_identity()
    with pytest.raises(ValueError, match="bad_type"):
        client.bus.send(OTHER_DID, "bad_type", "summary")


# ── broadcast() ───────────────────────────────────────────────────────────────

@respx.mock
def test_broadcast_omits_receiver_did():
    client = _client_with_identity()
    resp_data = _acp_response(receiver_did=None)
    respx.post(f"{BASE}/agentbus/send").mock(
        return_value=httpx.Response(201, json=resp_data)
    )

    client.bus.broadcast(
        message_type="system_event",
        human_summary="Platform maintenance in 5 mins",
        machine_payload={"eta_minutes": 5},
    )

    sent = json.loads(respx.calls.last.request.content)
    assert sent["receiver_did"] is None
    assert sent["type"] == "system_event"


def test_broadcast_rejects_invalid_type_before_network():
    client = _client_with_identity()
    with pytest.raises(ValueError):
        client.bus.broadcast("not_a_type", "summary")


# ── receive() ─────────────────────────────────────────────────────────────────

@respx.mock
def test_receive_fetches_inbox():
    client = _client_with_identity()
    inbox = [_acp_response(), _acp_response(type="task_result")]
    respx.get(re.compile(rf"{BASE}/agentbus/inbox.*")).mock(
        return_value=httpx.Response(200, json=inbox)
    )

    result = client.bus.receive()
    assert len(result) == 2
    assert result[0]["type"] == "task_request"
    assert result[1]["type"] == "task_result"


@respx.mock
def test_receive_passes_type_filter():
    client = _client_with_identity()
    respx.get(re.compile(rf"{BASE}/agentbus/inbox.*")).mock(
        return_value=httpx.Response(200, json=[])
    )

    client.bus.receive(acp_type="task_request", limit=10, offset=5)

    url = str(respx.calls.last.request.url)
    assert "type=task_request" in url
    assert "limit=10" in url
    assert "offset=5" in url


@respx.mock
def test_receive_passes_since_filter():
    client = _client_with_identity()
    respx.get(re.compile(rf"{BASE}/agentbus/inbox.*")).mock(
        return_value=httpx.Response(200, json=[])
    )

    since = "2026-01-01T00:00:00Z"
    client.bus.receive(since=since)

    url = str(respx.calls.last.request.url)
    assert "since=" in url


@respx.mock
def test_receive_empty_inbox_returns_empty_list():
    client = _client_with_identity()
    respx.get(re.compile(rf"{BASE}/agentbus/inbox.*")).mock(
        return_value=httpx.Response(200, json=[])
    )

    result = client.bus.receive()
    assert result == []


# ── ACPMessage Pydantic model ─────────────────────────────────────────────────

def test_acp_message_model_parses_valid_data():
    data = _acp_response()
    msg = ACPMessage(**data)
    assert msg.protocol_version == ACP_VERSION
    assert msg.type == "task_request"


def test_acp_message_metadata_defaults_to_empty_dict():
    data = _acp_response()
    data.pop("metadata")
    msg = ACPMessage(**data)
    assert msg.metadata == {}
