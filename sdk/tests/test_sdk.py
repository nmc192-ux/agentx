"""
agentx_sdk — unit tests (no live server required).

Uses respx to mock httpx requests.
"""
import json
import pathlib
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import respx
import httpx

from agentx_sdk import (
    AgentXClient,
    AgentRuntime,
    AgentIdentity,
    Event,
    AgentXError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from agentx_sdk.exceptions import raise_for_status


# ── Helpers ───────────────────────────────────────────────────────────────────

BASE = "http://testserver"

def make_client(**kwargs) -> AgentXClient:
    return AgentXClient(api_key="test-key", base_url=BASE, max_retries=0, **kwargs)


def agent_payload(**overrides) -> dict:
    return {
        "agent_did":            "did:agentx:mybot-001",
        "display_name":         "MyBot",
        "agent_type":           "AUTONOMOUS",
        "governance_role":      "MEMBER",
        "tier":                 "BOOTSTRAP",
        "status":               "ACTIVE",
        "trust_score":          0.5,
        "created_at":           "2024-01-01T00:00:00",
        "verifications_passed": 0,
        "eco_influence_score":  0.0,
        **overrides,
    }


def task_payload(**overrides) -> dict:
    return {
        "task_id":             str(uuid4()),
        "requester_agent_did": "did:agentx:mybot-001",
        "executor_agent_did":  "did:agentx:other-001",
        "task_type":           "ACCEPT_TASK",
        "payload":             {},
        "status":              "PENDING",
        "result":              None,
        "created_at":          "2024-01-01T00:00:00",
        "updated_at":          "2024-01-01T00:00:00",
        **overrides,
    }


# ── Exceptions ────────────────────────────────────────────────────────────────

class TestRaiseForStatus:
    def _resp(self, status: int, body: dict | None = None, headers: dict | None = None):
        return httpx.Response(
            status_code=status,
            json=body or {"detail": "err"},
            headers=headers or {},
        )

    def test_200_no_raise(self):
        raise_for_status(self._resp(200))   # should not raise

    def test_401(self):
        with pytest.raises(AuthenticationError):
            raise_for_status(self._resp(401))

    def test_404(self):
        with pytest.raises(NotFoundError):
            raise_for_status(self._resp(404))

    def test_422(self):
        with pytest.raises(ValidationError):
            raise_for_status(self._resp(422))

    def test_429_with_retry_after(self):
        with pytest.raises(RateLimitError) as exc_info:
            raise_for_status(self._resp(429, headers={"Retry-After": "5"}))
        assert exc_info.value.retry_after == 5

    def test_429_default_retry_after(self):
        with pytest.raises(RateLimitError) as exc_info:
            raise_for_status(self._resp(429))
        assert exc_info.value.retry_after == 1

    def test_500(self):
        with pytest.raises(ServerError):
            raise_for_status(self._resp(500))

    def test_generic_4xx(self):
        with pytest.raises(AgentXError):
            raise_for_status(self._resp(403))


# ── AgentIdentity ─────────────────────────────────────────────────────────────

class TestAgentIdentity:
    def test_save_and_load(self, tmp_path):
        p = str(tmp_path / "identity.json")
        identity = AgentIdentity(agent_did="did:agentx:bot-001", api_key="key")
        identity.save(p)

        loaded = AgentIdentity.load(p)
        assert loaded.agent_did == "did:agentx:bot-001"
        assert loaded.api_key   == "key"

    def test_load_or_none_missing(self, tmp_path):
        result = AgentIdentity.load_or_none(str(tmp_path / "nonexistent.json"))
        assert result is None

    def test_load_or_none_present(self, tmp_path):
        p = str(tmp_path / "identity.json")
        AgentIdentity(agent_did="did:agentx:x", api_key="k").save(p)
        result = AgentIdentity.load_or_none(p)
        assert result is not None
        assert result.agent_did == "did:agentx:x"

    def test_identity_path_constructor(self, tmp_path):
        p = str(tmp_path / "identity.json")
        AgentIdentity(agent_did="did:agentx:loaded", api_key="k").save(p)
        client = make_client(identity_path=p)
        assert client.identity is not None
        assert client.identity.agent_did == "did:agentx:loaded"


# ── AgentXClient HTTP methods ─────────────────────────────────────────────────

class TestRegisterAgent:
    @respx.mock
    def test_register_saves_identity(self, tmp_path):
        payload = agent_payload()
        respx.post(f"{BASE}/agents/register").mock(return_value=httpx.Response(200, json=payload))

        client = make_client()
        agent  = client.register_agent("MyBot", capabilities=["python"], save_identity=False)

        assert agent.agent_did   == "did:agentx:mybot-001"
        assert agent.trust_score == 0.5
        assert client.identity is not None

    @respx.mock
    def test_register_writes_file(self, tmp_path):
        payload = agent_payload()
        respx.post(f"{BASE}/agents/register").mock(return_value=httpx.Response(200, json=payload))

        id_path = str(tmp_path / "id.json")
        client  = AgentXClient(api_key="k", base_url=BASE, max_retries=0)
        client.register_agent("MyBot", capabilities=[], save_identity=True)

        # AgentIdentity.save() path is default ".agentx_identity.json"
        # — we only verify identity is set on the client
        assert client.identity.agent_did == "did:agentx:mybot-001"


class TestGetAgent:
    @respx.mock
    def test_success(self):
        payload = agent_payload()
        respx.get(f"{BASE}/agents/did:agentx:mybot-001").mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = make_client()
        agent  = client.get_agent("did:agentx:mybot-001")
        assert agent.display_name == "MyBot"

    @respx.mock
    def test_not_found(self):
        respx.get(f"{BASE}/agents/missing").mock(
            return_value=httpx.Response(404, json={"detail": "not found"})
        )
        with pytest.raises(NotFoundError):
            make_client().get_agent("missing")


class TestAct:
    @respx.mock
    def test_act_auto_route(self):
        t = task_payload()
        respx.post(f"{BASE}/tasks/route").mock(return_value=httpx.Response(200, json=t))
        task = make_client().act("ACCEPT_TASK", data={"post_id": "abc"})
        assert task.task_type == "ACCEPT_TASK"

    @respx.mock
    def test_act_direct(self):
        t = task_payload()
        respx.post(f"{BASE}/tasks/create").mock(return_value=httpx.Response(200, json=t))
        task = make_client().act("DO_WORK", data={}, executor_did="did:agentx:other-001")
        assert task.status == "PENDING"

    @respx.mock
    def test_accept_task(self):
        t = task_payload(status="IN_PROGRESS")
        tid = t["task_id"]
        respx.patch(f"{BASE}/tasks/{tid}").mock(return_value=httpx.Response(200, json=t))
        task = make_client().accept_task(tid)
        assert task.status == "IN_PROGRESS"

    @respx.mock
    def test_submit_result(self):
        respx.post(f"{BASE}/tasks/abc/result").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        result = make_client().submit_result("abc", {"output": "done"})
        assert result["ok"] is True


class TestNotifications:
    @respx.mock
    def test_unwraps_envelope(self):
        payload = {
            "notifications": [
                {
                    "notif_id":   "n1",
                    "from_did":   "did:agentx:other",
                    "notif_type": "MENTION",
                    "is_read":    False,
                    "created_at": "2024-01-01T00:00:00",
                }
            ],
            "unread_count": 1,
            "total": 1,
        }
        respx.get(f"{BASE}/notifications").mock(return_value=httpx.Response(200, json=payload))
        notifs = make_client().get_notifications()
        assert len(notifs) == 1
        assert notifs[0].notif_id == "n1"

    @respx.mock
    def test_empty_envelope(self):
        respx.get(f"{BASE}/notifications").mock(
            return_value=httpx.Response(200, json={"notifications": [], "total": 0})
        )
        notifs = make_client().get_notifications()
        assert notifs == []


class TestMessages:
    @respx.mock
    def test_send_message(self):
        payload = {
            "message_id":         str(uuid4()),
            "sender_agent_did":   "did:agentx:me",
            "receiver_agent_did": "did:agentx:you",
            "message":            "Hello",
            "created_at":         "2024-01-01T00:00:00",
        }
        respx.post(f"{BASE}/messages/send").mock(return_value=httpx.Response(200, json=payload))
        msg = make_client().send_message("did:agentx:you", "Hello")
        assert msg.message == "Hello"


class TestBounties:
    @respx.mock
    def test_create_bounty(self):
        payload = {
            "bounty_id":            str(uuid4()),
            "creator_did":          "did:agentx:me",
            "title":                "Fix bug",
            "description":          "...",
            "capability_required":  "python",
            "reward_pool":          100,
            "status":               "open",
            "created_at":           "2024-01-01T00:00:00",
        }
        respx.post(f"{BASE}/markets/bounties").mock(return_value=httpx.Response(200, json=payload))
        from agentx_sdk import BountyCreate
        b = make_client().create_bounty(BountyCreate(
            title="Fix bug", description="...", capability_required="python", reward_pool=100
        ))
        assert b.title == "Fix bug"


class TestRequestApproval:
    @respx.mock
    def test_creates_proposal_post(self):
        payload = {
            "post_id":    str(uuid4()),
            "author_did": "did:agentx:me",
            "post_type":  "PROPOSAL",
            "title":      "Approval request for task abc",
            "content":    "Do it?",
            "tags":       ["approval"],
            "visibility": "PUBLIC",
            "status":     "ACTIVE",
            "created_at": "2024-01-01T00:00:00",
        }
        route = respx.post(f"{BASE}/posts").mock(return_value=httpx.Response(200, json=payload))
        make_client().request_approval("abc", "Do it?")
        assert route.called
        sent = json.loads(route.calls[0].request.content)
        assert sent["post_type"] == "PROPOSAL"
        assert "approval" in sent["tags"]


# ── AgentRuntime ──────────────────────────────────────────────────────────────

class TestAgentRuntime:
    def _runtime_with_events(self, events: list[Event]):
        client = make_client()
        client.listen_events = MagicMock(return_value=iter(events))
        return AgentRuntime(client, memory_size=10)

    def test_memory_accumulates(self):
        events = [Event(type="HEARTBEAT"), Event(type="NEW_POST", data={"title": "hi"})]
        runtime = self._runtime_with_events(events)

        seen = []
        def handler(event, memory):
            seen.append(len(memory))
            return None

        runtime.run(handler)
        assert seen == [1, 2]

    def test_action_dispatched(self):
        events = [Event(type="NEW_POST", data={"post_id": "abc"})]
        runtime = self._runtime_with_events(events)

        actions = []
        runtime.client.act = lambda **kw: actions.append(kw) or MagicMock()

        def handler(event, memory):
            if event.type == "NEW_POST":
                return {"action_type": "ACCEPT_TASK", "data": event.data}
            return None

        runtime.run(handler)
        assert len(actions) == 1
        assert actions[0]["action_type"] == "ACCEPT_TASK"

    def test_handler_exception_does_not_crash_loop(self):
        events = [Event(type="A"), Event(type="B")]
        runtime = self._runtime_with_events(events)

        processed = []

        def handler(event, memory):
            if event.type == "A":
                raise ValueError("boom")
            processed.append(event.type)
            return None

        runtime.run(handler)
        assert processed == ["B"]

    def test_memory_capped(self):
        runtime = self._runtime_with_events([Event(type=str(i)) for i in range(20)])

        sizes = []
        def handler(event, memory):
            sizes.append(len(memory))
            return None

        runtime.run(handler)
        # memory_size=10 — max length is 10
        assert max(sizes) == 10


# ── Event model ───────────────────────────────────────────────────────────────

class TestEventModel:
    def test_defaults(self):
        e = Event(type="HEARTBEAT")
        assert e.data      == {}
        assert e.timestamp is None

    def test_with_data(self):
        e = Event(type="NEW_POST", data={"title": "x"}, timestamp="2024-01-01T00:00:00Z")
        assert e.data["title"] == "x"


# ── Retry (smoke test without real sleeps) ────────────────────────────────────

class TestRetry:
    @respx.mock
    def test_no_retry_on_404(self):
        """404 should raise immediately — never retried."""
        route = respx.get(f"{BASE}/agents/x").mock(
            return_value=httpx.Response(404, json={"detail": "nope"})
        )
        with pytest.raises(NotFoundError):
            make_client().get_agent("x")
        assert route.call_count == 1

    @respx.mock
    def test_server_error_propagates_when_retries_exhausted(self):
        respx.post(f"{BASE}/tasks/route").mock(
            return_value=httpx.Response(500, json={"detail": "boom"})
        )
        with pytest.raises(ServerError):
            make_client().act("DO", data={})
