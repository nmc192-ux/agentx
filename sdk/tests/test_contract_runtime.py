"""
agentx_sdk — Contract-decorator runtime pattern tests.

Tests that run_contracts polls tasks, dispatches to Agent handlers,
and submits results — all via respx-mocked HTTP.
"""
import asyncio
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from agentx_sdk import Agent, AgentXClient, AgentRuntime

BASE = "http://testserver"


def _make_client() -> AgentXClient:
    c = AgentXClient.__new__(AgentXClient)
    c._http = httpx.Client(base_url=BASE)
    c._base_url = BASE
    c._log = MagicMock()
    c._max_retries = 0
    c._token = MagicMock()
    c._token.headers = {"Authorization": "Bearer test-token"}
    c.identity = MagicMock()
    c.identity.agent_did = "did:agentx:test-agent"
    return c


# -- _poll_contracts ---------------------------------------------------------

class TestPollContracts:
    """Test the single-cycle _poll_contracts method directly."""

    @respx.mock
    def test_pending_task_dispatched(self):
        """A PENDING task with matching handler is accepted, executed, completed."""
        agent = Agent("bot", capabilities=["review"])

        @agent.contract("review")
        async def handle_review(data):
            return {"output": "LGTM"}

        client = _make_client()
        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.client = client
        runtime._log = client._log

        # Mock: GET tasks returns one PENDING task
        respx.get(f"{BASE}/tasks/did:agentx:test-agent").mock(
            return_value=httpx.Response(200, json=[
                {
                    "task_id": "task-001",
                    "status": "PENDING",
                    "task_type": "review",
                    "payload": {"code": "print('hi')"},
                }
            ])
        )

        # Mock: POST accept
        accept_route = respx.post(f"{BASE}/tasks/task-001/update").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )

        runtime._poll_contracts(agent, "did:agentx:test-agent")

        # accept was called with IN_PROGRESS, then COMPLETED
        assert accept_route.call_count == 2

    @respx.mock
    def test_non_pending_task_skipped(self):
        """Tasks that are not PENDING are skipped."""
        agent = Agent("bot", capabilities=["review"])

        @agent.contract("review")
        async def handle_review(data):
            return {"output": "done"}

        client = _make_client()
        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.client = client
        runtime._log = client._log

        respx.get(f"{BASE}/tasks/did:agentx:test-agent").mock(
            return_value=httpx.Response(200, json=[
                {
                    "task_id": "task-002",
                    "status": "IN_PROGRESS",
                    "task_type": "review",
                    "payload": {},
                }
            ])
        )

        update_route = respx.post(f"{BASE}/tasks/task-002/update").mock(
            return_value=httpx.Response(200, json={})
        )

        runtime._poll_contracts(agent, "did:agentx:test-agent")

        # No task update calls since it was not PENDING
        assert update_route.call_count == 0

    @respx.mock
    def test_unhandled_capability_skipped(self):
        """Tasks with no matching handler are skipped."""
        agent = Agent("bot", capabilities=["review"])

        @agent.contract("review")
        async def handle_review(data):
            return {}

        client = _make_client()
        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.client = client
        runtime._log = client._log

        respx.get(f"{BASE}/tasks/did:agentx:test-agent").mock(
            return_value=httpx.Response(200, json=[
                {
                    "task_id": "task-003",
                    "status": "PENDING",
                    "task_type": "coding",  # no handler for this
                    "payload": {},
                }
            ])
        )

        update_route = respx.post(f"{BASE}/tasks/task-003/update").mock(
            return_value=httpx.Response(200, json={})
        )

        runtime._poll_contracts(agent, "did:agentx:test-agent")
        assert update_route.call_count == 0

    @respx.mock
    def test_envelope_response_unwrapped(self):
        """Tasks returned in an {items: [...]} envelope are unwrapped."""
        agent = Agent("bot", capabilities=["review"])

        @agent.contract("review")
        async def handle_review(data):
            return {"result": "ok"}

        client = _make_client()
        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.client = client
        runtime._log = client._log

        respx.get(f"{BASE}/tasks/did:agentx:test-agent").mock(
            return_value=httpx.Response(200, json={
                "items": [
                    {
                        "task_id": "task-004",
                        "status": "PENDING",
                        "task_type": "review",
                        "payload": {"x": 1},
                    }
                ]
            })
        )

        update_route = respx.post(f"{BASE}/tasks/task-004/update").mock(
            return_value=httpx.Response(200, json={})
        )

        runtime._poll_contracts(agent, "did:agentx:test-agent")
        assert update_route.call_count == 2

    @respx.mock
    def test_handler_error_logged_not_raised(self):
        """If a handler raises, it is logged but does not crash the poll."""
        agent = Agent("bot", capabilities=["review"])

        @agent.contract("review")
        async def handle_review(data):
            raise RuntimeError("boom")

        client = _make_client()
        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.client = client
        runtime._log = client._log

        respx.get(f"{BASE}/tasks/did:agentx:test-agent").mock(
            return_value=httpx.Response(200, json=[
                {
                    "task_id": "task-005",
                    "status": "PENDING",
                    "task_type": "review",
                    "payload": {},
                }
            ])
        )

        accept_route = respx.post(f"{BASE}/tasks/task-005/update").mock(
            return_value=httpx.Response(200, json={})
        )

        # Should not raise
        runtime._poll_contracts(agent, "did:agentx:test-agent")

        # Accept was called (IN_PROGRESS) but not COMPLETED
        assert accept_route.call_count == 1

    @respx.mock
    def test_poll_failure_logged(self):
        """If GET tasks fails, it is logged and the method returns."""
        agent = Agent("bot")
        client = _make_client()
        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.client = client
        runtime._log = client._log

        respx.get(f"{BASE}/tasks/did:agentx:test-agent").mock(
            return_value=httpx.Response(500, json={"error": "internal"})
        )

        # Should not raise
        runtime._poll_contracts(agent, "did:agentx:test-agent")

    @respx.mock
    def test_multiple_tasks_dispatched(self):
        """Multiple PENDING tasks in one poll cycle are all handled."""
        agent = Agent("bot", capabilities=["review", "coding"])

        @agent.contract("review")
        async def handle_review(data):
            return {"output": "reviewed"}

        @agent.contract("coding")
        async def handle_coding(data):
            return {"output": "coded"}

        client = _make_client()
        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.client = client
        runtime._log = client._log

        respx.get(f"{BASE}/tasks/did:agentx:test-agent").mock(
            return_value=httpx.Response(200, json=[
                {"task_id": "t1", "status": "PENDING", "task_type": "review", "payload": {}},
                {"task_id": "t2", "status": "PENDING", "task_type": "coding", "payload": {}},
            ])
        )

        t1_route = respx.post(f"{BASE}/tasks/t1/update").mock(
            return_value=httpx.Response(200, json={})
        )
        t2_route = respx.post(f"{BASE}/tasks/t2/update").mock(
            return_value=httpx.Response(200, json={})
        )

        runtime._poll_contracts(agent, "did:agentx:test-agent")

        # Each task gets accept + complete = 2 calls each
        assert t1_route.call_count == 2
        assert t2_route.call_count == 2
