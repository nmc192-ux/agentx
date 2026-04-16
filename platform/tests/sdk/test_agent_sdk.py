"""
Tests: agentx_sdk — Agent SDK (Phase 13)
═════════════════════════════════════════

Covers:
  agent.py      — Agent class, @agent.contract() decorator, handle_contract()
  client.py     — AgentXClient HTTP methods (httpx mocked)
  runtime.py    — AgentRuntime lifecycle, polling loop, handler execution
  bus.py        — BusClient send/receive/stream
  wallet.py     — WalletClient balance/transfer/stakes
  contracts.py  — ContractsClient full lifecycle
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ═════════════════════════════════════════════════════════════════════════════
# agentx_sdk.agent — Agent class
# ═════════════════════════════════════════════════════════════════════════════

class TestAgent:

    def test_agent_initialises_with_name_and_capabilities(self):
        from agentx_sdk.agent import Agent
        agent = Agent(name="data_agent", capabilities=["collect_data"])
        assert agent.name == "data_agent"
        assert agent.capabilities == ["collect_data"]
        assert agent.did is None
        assert agent.agent_id is None

    def test_agent_contract_decorator_registers_handler(self):
        from agentx_sdk.agent import Agent

        agent = Agent(name="data_agent", capabilities=["collect_data"])

        @agent.contract("collect_data")
        async def handler(data: dict) -> dict:
            return {"result": "ok"}

        assert "collect_data" in agent._handlers
        assert agent.has_handler("collect_data")

    def test_agent_contract_decorator_returns_original_function(self):
        from agentx_sdk.agent import Agent

        agent = Agent(name="data_agent", capabilities=["collect_data"])

        @agent.contract("collect_data")
        async def handler(data: dict) -> dict:
            return {}

        # The decorated function is returned unchanged
        assert callable(handler)

    def test_agent_contract_rejects_sync_function(self):
        from agentx_sdk.agent import Agent

        agent = Agent(name="data_agent", capabilities=["collect_data"])

        with pytest.raises(TypeError, match="async"):
            @agent.contract("collect_data")
            def sync_handler(data: dict) -> dict:  # sync — should raise
                return {}

    def test_agent_contract_allows_multiple_capabilities(self):
        from agentx_sdk.agent import Agent

        agent = Agent(name="multi", capabilities=["cap_a", "cap_b"])

        @agent.contract("cap_a")
        async def handler_a(data: dict) -> dict:
            return {"cap": "a"}

        @agent.contract("cap_b")
        async def handler_b(data: dict) -> dict:
            return {"cap": "b"}

        assert set(agent.registered_capabilities()) == {"cap_a", "cap_b"}

    @pytest.mark.asyncio
    async def test_handle_contract_executes_registered_handler(self):
        from agentx_sdk.agent import Agent

        agent = Agent(name="data_agent", capabilities=["collect_data"])

        @agent.contract("collect_data")
        async def handler(data: dict) -> dict:
            return {"rows": data.get("expected_rows", 0)}

        result = await agent.handle_contract("collect_data", {"expected_rows": 42})
        assert result == {"rows": 42}

    @pytest.mark.asyncio
    async def test_handle_contract_raises_for_unknown_capability(self):
        from agentx_sdk.agent import Agent

        agent = Agent(name="data_agent", capabilities=["collect_data"])
        with pytest.raises(ValueError, match="no handler"):
            await agent.handle_contract("unknown_cap", {})

    def test_registered_capabilities_returns_list(self):
        from agentx_sdk.agent import Agent

        agent = Agent(name="a", capabilities=["x"])

        @agent.contract("x")
        async def h(d: dict) -> dict:
            return {}

        assert agent.registered_capabilities() == ["x"]

    def test_has_handler_returns_false_for_unregistered(self):
        from agentx_sdk.agent import Agent
        agent = Agent(name="a", capabilities=[])
        assert not agent.has_handler("nonexistent")

    def test_agent_repr_contains_name(self):
        from agentx_sdk.agent import Agent
        agent = Agent(name="my_agent", capabilities=["cap"])
        assert "my_agent" in repr(agent)


# ═════════════════════════════════════════════════════════════════════════════
# agentx_sdk.client — AgentXClient
# ═════════════════════════════════════════════════════════════════════════════

def _mock_httpx_response(status_code: int = 200, json_data: dict | list | None = None):
    """Create a mock httpx Response-like object."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json = MagicMock(return_value=json_data or {})
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestAgentXClient:

    def test_client_sets_bearer_token_header(self):
        from agentx_sdk.client import AgentXClient
        client = AgentXClient(base_url="http://test.local", api_key="test-jwt")
        assert client._headers["Authorization"] == "Bearer test-jwt"

    def test_client_without_api_key_has_no_auth_header(self):
        from agentx_sdk.client import AgentXClient
        client = AgentXClient(base_url="http://test.local")
        assert "Authorization" not in client._headers

    def test_base_url_strips_trailing_slash(self):
        from agentx_sdk.client import AgentXClient
        client = AgentXClient(base_url="http://test.local/")
        assert client.base_url == "http://test.local"

    @pytest.mark.asyncio
    async def test_register_agent_posts_to_agents_endpoint(self):
        from agentx_sdk.client import AgentXClient

        agent_data = {
            "agent_id": str(uuid4()),
            "name": "data_agent",
            "did": "did:agentx:data-001",
        }

        mock_resp = _mock_httpx_response(201, agent_data)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.client.httpx.AsyncClient", return_value=mock_client):
            client = AgentXClient(base_url="http://test.local", api_key="jwt")
            result = await client.register_agent(
                name="data_agent",
                did="did:agentx:data-001",
                capabilities=["collect_data"],
            )

        assert result == agent_data
        mock_client.post.assert_awaited_once()
        call_kwargs = mock_client.post.await_args
        assert call_kwargs.args[0] == "/agents"

    @pytest.mark.asyncio
    async def test_register_agent_includes_bio_when_provided(self):
        from agentx_sdk.client import AgentXClient

        mock_resp = _mock_httpx_response(201, {"agent_id": str(uuid4())})
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.client.httpx.AsyncClient", return_value=mock_client):
            client = AgentXClient(base_url="http://test.local")
            await client.register_agent(
                name="agent", did="did:agentx:x", capabilities=[], bio="My bio"
            )

        payload = mock_client.post.await_args.kwargs["json"]
        assert payload["bio"] == "My bio"

    @pytest.mark.asyncio
    async def test_create_contract_posts_to_contracts_endpoint(self):
        from agentx_sdk.client import AgentXClient

        contract_data = {
            "contract_id": str(uuid4()),
            "title": "Collect data",
            "status": "open",
        }

        mock_resp = _mock_httpx_response(201, contract_data)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.client.httpx.AsyncClient", return_value=mock_client):
            client = AgentXClient(base_url="http://test.local", api_key="jwt")
            result = await client.create_contract(
                title="Collect data",
                capability_required="collect_data",
                budget=1000,
            )

        assert result == contract_data
        call_args = mock_client.post.await_args
        assert call_args.args[0] == "/contracts"
        payload = call_args.kwargs["json"]
        assert payload["budget"] == 1000

    @pytest.mark.asyncio
    async def test_submit_result_posts_to_contract_result_endpoint(self):
        from agentx_sdk.client import AgentXClient

        contract_id = str(uuid4())
        result_data = {"result_id": str(uuid4())}

        mock_resp = _mock_httpx_response(201, result_data)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.client.httpx.AsyncClient", return_value=mock_client):
            client = AgentXClient(base_url="http://test.local", api_key="jwt")
            result = await client.submit_result(
                contract_id=contract_id,
                result_data={"rows": 42},
            )

        assert result == result_data
        call_args = mock_client.post.await_args
        assert f"/tasks/{contract_id}/result" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_get_wallet_fetches_wallet_endpoint(self):
        from agentx_sdk.client import AgentXClient

        agent_id = str(uuid4())
        wallet = {"wallet_id": str(uuid4()), "balance": 5000}

        mock_resp = _mock_httpx_response(200, wallet)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.client.httpx.AsyncClient", return_value=mock_client):
            client = AgentXClient(base_url="http://test.local")
            result = await client.get_wallet(agent_id)

        assert result == wallet
        call_url = mock_client.get.await_args.args[0]
        assert agent_id in call_url

    @pytest.mark.asyncio
    async def test_send_message_posts_to_agentbus_messages(self):
        from agentx_sdk.client import AgentXClient

        msg_data = {"message_id": str(uuid4()), "content": "Hello"}

        mock_resp = _mock_httpx_response(201, msg_data)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.client.httpx.AsyncClient", return_value=mock_client):
            client = AgentXClient(base_url="http://test.local", api_key="jwt")
            result = await client.send_message(
                receiver_did="did:agentx:other",
                content="Hello!",
            )

        assert result == msg_data
        call_args = mock_client.post.await_args
        assert call_args.args[0] == "/agentbus/messages"
        payload = call_args.kwargs["json"]
        assert payload["receiver_did"] == "did:agentx:other"
        assert payload["content"] == "Hello!"


# ═════════════════════════════════════════════════════════════════════════════
# agentx_sdk.runtime — AgentRuntime
# ═════════════════════════════════════════════════════════════════════════════

class TestAgentRuntime:

    def _make_runtime(self, agent=None, client=None, poll_interval=0.01):
        from agentx_sdk.agent import Agent
        from agentx_sdk.client import AgentXClient
        from agentx_sdk.runtime import AgentRuntime

        if agent is None:
            agent = Agent(
                name="test_agent",
                capabilities=["test_cap"],
                did="did:agentx:test-001",
            )
        if client is None:
            client = MagicMock(spec=AgentXClient)

        return AgentRuntime(
            agent=agent,
            client=client,
            poll_interval=poll_interval,
            auto_register=False,
        )

    @pytest.mark.asyncio
    async def test_runtime_stops_when_stop_called(self):
        from agentx_sdk.runtime import AgentRuntime

        runtime = self._make_runtime()
        runtime._running = True

        # Patch _loop so it checks _running immediately
        async def fake_loop():
            runtime._running = False

        runtime._loop = fake_loop
        runtime._register = AsyncMock()
        runtime.auto_register = True

        await runtime.start()
        assert not runtime._running

    @pytest.mark.asyncio
    async def test_runtime_executes_handler_and_submits_result(self):
        from agentx_sdk.agent import Agent
        from agentx_sdk.runtime import AgentRuntime

        agent = Agent(
            name="executor",
            capabilities=["do_work"],
            did="did:agentx:executor",
        )

        @agent.contract("do_work")
        async def do_work(data: dict) -> dict:
            return {"output": "done", "count": data.get("count", 0) + 1}

        contract_id = str(uuid4())
        contract_record = {
            "contract_id": contract_id,
            "capability_required": "do_work",
            "assigned_agent_did": "did:agentx:executor",
            "count": 5,
        }

        mock_client = AsyncMock()
        mock_client.list_contracts = AsyncMock(return_value=[contract_record])
        mock_client.submit_result  = AsyncMock(return_value={"result_id": str(uuid4())})

        runtime = AgentRuntime(
            agent=agent,
            client=mock_client,
            poll_interval=0.01,
            auto_register=False,
        )

        # Run one polling cycle
        await runtime._poll_and_execute()

        mock_client.submit_result.assert_awaited_once()
        call_kwargs = mock_client.submit_result.await_args.kwargs
        assert call_kwargs["contract_id"] == contract_id
        assert call_kwargs["result_data"]["output"] == "done"

    @pytest.mark.asyncio
    async def test_runtime_skips_contract_for_different_agent(self):
        """Contracts assigned to another agent are not executed."""
        from agentx_sdk.agent import Agent
        from agentx_sdk.runtime import AgentRuntime

        agent = Agent(name="mine", capabilities=["x"], did="did:agentx:mine")

        mock_client = AsyncMock()
        mock_client.list_contracts = AsyncMock(return_value=[
            {
                "contract_id": str(uuid4()),
                "capability_required": "x",
                "assigned_agent_did": "did:agentx:somebody-else",
            }
        ])
        mock_client.submit_result = AsyncMock()

        runtime = AgentRuntime(
            agent=agent, client=mock_client, poll_interval=0.01, auto_register=False,
        )
        await runtime._poll_and_execute()

        mock_client.submit_result.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_runtime_handles_missing_handler_gracefully(self):
        """Unknown capability → logs warning but does not crash."""
        from agentx_sdk.agent import Agent
        from agentx_sdk.runtime import AgentRuntime

        agent = Agent(name="a", capabilities=[], did="did:agentx:a")
        # No handlers registered

        mock_client = AsyncMock()
        mock_client.list_contracts = AsyncMock(return_value=[
            {
                "contract_id": str(uuid4()),
                "capability_required": "unknown_cap",
                "assigned_agent_did": "did:agentx:a",
            }
        ])
        mock_client.submit_result = AsyncMock()

        runtime = AgentRuntime(
            agent=agent, client=mock_client, poll_interval=0.01, auto_register=False,
        )
        await runtime._poll_and_execute()

        mock_client.submit_result.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_runtime_handles_poll_failure_gracefully(self):
        """list_contracts raising should not crash the runtime."""
        from agentx_sdk.agent import Agent
        from agentx_sdk.runtime import AgentRuntime

        agent = Agent(name="a", capabilities=[], did="did:agentx:a")
        mock_client = AsyncMock()
        mock_client.list_contracts = AsyncMock(side_effect=ConnectionError("API down"))

        runtime = AgentRuntime(
            agent=agent, client=mock_client, poll_interval=0.01, auto_register=False,
        )
        await runtime._poll_and_execute()  # must not raise

    @pytest.mark.asyncio
    async def test_runtime_registration_skips_if_no_did(self):
        """auto_register skips silently when agent.did is None."""
        from agentx_sdk.agent import Agent
        from agentx_sdk.runtime import AgentRuntime

        agent = Agent(name="a", capabilities=[], did=None)
        mock_client = AsyncMock()
        mock_client.register_agent = AsyncMock()

        runtime = AgentRuntime(
            agent=agent, client=mock_client, poll_interval=0.01, auto_register=True,
        )
        await runtime._register()

        mock_client.register_agent.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_runtime_registration_calls_register_agent(self):
        from agentx_sdk.agent import Agent
        from agentx_sdk.runtime import AgentRuntime

        agent = Agent(name="reg_agent", capabilities=["x"], did="did:agentx:reg")
        agent_id = str(uuid4())

        mock_client = AsyncMock()
        mock_client.register_agent = AsyncMock(
            return_value={"agent_id": agent_id, "name": "reg_agent"}
        )

        runtime = AgentRuntime(
            agent=agent, client=mock_client, poll_interval=0.01, auto_register=True,
        )
        await runtime._register()

        mock_client.register_agent.assert_awaited_once()
        assert agent.agent_id == agent_id

    @pytest.mark.asyncio
    async def test_runtime_submit_result_failure_does_not_raise(self):
        from agentx_sdk.agent import Agent
        from agentx_sdk.runtime import AgentRuntime

        agent = Agent(name="a", capabilities=["x"], did="did:agentx:a")
        mock_client = AsyncMock()
        mock_client.submit_result = AsyncMock(side_effect=RuntimeError("API error"))

        runtime = AgentRuntime(
            agent=agent, client=mock_client, poll_interval=0.01, auto_register=False,
        )
        await runtime._submit_result(str(uuid4()), {"output": "done"})  # must not raise


# ═════════════════════════════════════════════════════════════════════════════
# agentx_sdk.bus — BusClient
# ═════════════════════════════════════════════════════════════════════════════

class TestBusClient:

    def _make_bus(self):
        from agentx_sdk.bus import BusClient
        return BusClient(
            base_url="http://test.local",
            agent_did="did:agentx:test",
            token="jwt",
        )

    @pytest.mark.asyncio
    async def test_send_message_posts_to_agentbus_messages(self):
        from agentx_sdk.bus import BusClient

        msg = {"message_id": str(uuid4()), "content": "hi"}
        mock_resp = _mock_httpx_response(201, msg)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.bus.httpx.AsyncClient", return_value=mock_client):
            bus = self._make_bus()
            result = await bus.send_message("did:agentx:other", "hi")

        assert result == msg
        mock_client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_inbox_fetches_inbox_endpoint(self):
        from agentx_sdk.bus import BusClient

        messages = [{"message_id": str(uuid4()), "content": "hello"}]
        mock_resp = _mock_httpx_response(200, messages)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.bus.httpx.AsyncClient", return_value=mock_client):
            bus = self._make_bus()
            result = await bus.get_inbox()

        assert result == messages
        call_url = mock_client.get.await_args.args[0]
        assert "/agentbus/inbox" in call_url

    @pytest.mark.asyncio
    async def test_stream_messages_yields_parsed_sse_lines(self):
        """stream_messages() parses SSE data lines into dicts."""
        from agentx_sdk.bus import BusClient

        msg_payload = {"message_id": str(uuid4()), "content": "streamed"}
        sse_lines   = [f"data: {json.dumps(msg_payload)}", ""]

        # Build mock SSE response with aiter_lines support
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        async def _aiter_lines():
            for line in sse_lines:
                yield line

        mock_response.aiter_lines = _aiter_lines
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_http_client = AsyncMock()
        mock_http_client.stream = MagicMock(return_value=mock_response)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.bus.httpx.AsyncClient", return_value=mock_http_client):
            bus = self._make_bus()
            collected = []
            async for msg in bus.stream_messages():
                collected.append(msg)

        assert collected == [msg_payload]


# ═════════════════════════════════════════════════════════════════════════════
# agentx_sdk.wallet — WalletClient
# ═════════════════════════════════════════════════════════════════════════════

class TestWalletClient:

    def _make_wallet(self):
        from agentx_sdk.wallet import WalletClient
        return WalletClient(base_url="http://test.local", token="jwt")

    @pytest.mark.asyncio
    async def test_get_wallet_returns_wallet_record(self):
        agent_id = str(uuid4())
        wallet_rec = {"wallet_id": str(uuid4()), "balance": 1234, "agent_id": agent_id}

        mock_resp = _mock_httpx_response(200, wallet_rec)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.wallet.httpx.AsyncClient", return_value=mock_client):
            wallet = self._make_wallet()
            result = await wallet.get_wallet(agent_id)

        assert result["balance"] == 1234

    @pytest.mark.asyncio
    async def test_get_balance_returns_integer(self):
        agent_id = str(uuid4())
        wallet_rec = {"balance": 9999}

        mock_resp = _mock_httpx_response(200, wallet_rec)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.wallet.httpx.AsyncClient", return_value=mock_client):
            wallet = self._make_wallet()
            balance = await wallet.get_balance(agent_id)

        assert balance == 9999
        assert isinstance(balance, int)

    @pytest.mark.asyncio
    async def test_transfer_posts_to_transfer_endpoint(self):
        tx_rec = {"transaction_id": str(uuid4()), "amount": 500}

        mock_resp = _mock_httpx_response(201, tx_rec)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.wallet.httpx.AsyncClient", return_value=mock_client):
            wallet = self._make_wallet()
            result = await wallet.transfer(
                from_agent_id=str(uuid4()),
                to_agent_id=str(uuid4()),
                amount=500,
            )

        assert result == tx_rec
        call_url = mock_client.post.await_args.args[0]
        assert "/tokens/transfer" in call_url

    @pytest.mark.asyncio
    async def test_get_stakes_returns_list(self):
        agent_id = str(uuid4())
        stakes = [{"stake_id": str(uuid4()), "amount": 200}]

        mock_resp = _mock_httpx_response(200, stakes)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.wallet.httpx.AsyncClient", return_value=mock_client):
            wallet = self._make_wallet()
            result = await wallet.get_stakes(agent_id)

        assert result == stakes


# ═════════════════════════════════════════════════════════════════════════════
# agentx_sdk.contracts — ContractsClient
# ═════════════════════════════════════════════════════════════════════════════

class TestContractsClient:

    def _make_contracts(self):
        from agentx_sdk.contracts import ContractsClient
        return ContractsClient(base_url="http://test.local", token="jwt")

    @pytest.mark.asyncio
    async def test_create_contract_posts_to_contracts(self):
        contract_rec = {"contract_id": str(uuid4()), "status": "open"}

        mock_resp = _mock_httpx_response(201, contract_rec)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.contracts.httpx.AsyncClient", return_value=mock_client):
            contracts = self._make_contracts()
            result = await contracts.create(
                title="My contract",
                capability_required="do_work",
                budget=1000,
            )

        assert result["status"] == "open"
        call_url = mock_client.post.await_args.args[0]
        assert call_url == "/contracts"

    @pytest.mark.asyncio
    async def test_get_contract_fetches_by_id(self):
        contract_id = str(uuid4())
        contract_rec = {"contract_id": contract_id, "status": "open"}

        mock_resp = _mock_httpx_response(200, contract_rec)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.contracts.httpx.AsyncClient", return_value=mock_client):
            contracts = self._make_contracts()
            result = await contracts.get(contract_id)

        assert result["contract_id"] == contract_id

    @pytest.mark.asyncio
    async def test_list_contracts_with_status_filter(self):
        contracts_list = [{"contract_id": str(uuid4()), "status": "open"}]

        mock_resp = _mock_httpx_response(200, contracts_list)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.contracts.httpx.AsyncClient", return_value=mock_client):
            contracts = self._make_contracts()
            result = await contracts.list(status="open")

        assert result == contracts_list
        params = mock_client.get.await_args.kwargs.get("params", {})
        assert params["status"] == "open"

    @pytest.mark.asyncio
    async def test_submit_bid_posts_to_bid_endpoint(self):
        contract_id = str(uuid4())
        bid_rec = {"bid_id": str(uuid4()), "proposed_fee": 800}

        mock_resp = _mock_httpx_response(201, bid_rec)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.contracts.httpx.AsyncClient", return_value=mock_client):
            contracts = self._make_contracts()
            result = await contracts.submit_bid(contract_id, proposed_fee=800)

        assert result == bid_rec
        call_url = mock_client.post.await_args.args[0]
        assert f"/contracts/{contract_id}/bid" in call_url

    @pytest.mark.asyncio
    async def test_assign_contract_posts_to_assign_endpoint(self):
        contract_id = str(uuid4())
        bid_id      = str(uuid4())
        updated = {"contract_id": contract_id, "status": "assigned"}

        mock_resp = _mock_httpx_response(200, updated)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.contracts.httpx.AsyncClient", return_value=mock_client):
            contracts = self._make_contracts()
            result = await contracts.assign(contract_id, bid_id)

        assert result["status"] == "assigned"
        call_url = mock_client.post.await_args.args[0]
        assert f"/contracts/{contract_id}/assign" in call_url

    @pytest.mark.asyncio
    async def test_submit_result_posts_to_result_endpoint(self):
        contract_id = str(uuid4())
        result_rec = {"result_id": str(uuid4())}

        mock_resp = _mock_httpx_response(201, result_rec)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.contracts.httpx.AsyncClient", return_value=mock_client):
            contracts = self._make_contracts()
            result = await contracts.submit_result(
                contract_id, result_data={"rows": 42}
            )

        assert result == result_rec

    @pytest.mark.asyncio
    async def test_open_dispute_posts_reason(self):
        contract_id = str(uuid4())
        dispute_rec = {"dispute_id": str(uuid4()), "reason": "bad result"}

        mock_resp = _mock_httpx_response(201, dispute_rec)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agentx_sdk.contracts.httpx.AsyncClient", return_value=mock_client):
            contracts = self._make_contracts()
            result = await contracts.open_dispute(contract_id, reason="bad result")

        assert result["reason"] == "bad result"
        payload = mock_client.post.await_args.kwargs["json"]
        assert payload["reason"] == "bad result"


# ═════════════════════════════════════════════════════════════════════════════
# agentx_sdk — Package-level imports
# ═════════════════════════════════════════════════════════════════════════════

class TestSDKPackageImports:

    def test_top_level_imports_work(self):
        import agentx_sdk
        assert hasattr(agentx_sdk, "Agent")
        assert hasattr(agentx_sdk, "AgentXClient")
        assert hasattr(agentx_sdk, "AgentRuntime")

    def test_version_is_set(self):
        import agentx_sdk
        assert agentx_sdk.__version__ == "0.1.0"

    def test_bus_client_importable(self):
        from agentx_sdk.bus import BusClient
        assert BusClient is not None

    def test_wallet_client_importable(self):
        from agentx_sdk.wallet import WalletClient
        assert WalletClient is not None

    def test_contracts_client_importable(self):
        from agentx_sdk.contracts import ContractsClient
        assert ContractsClient is not None
