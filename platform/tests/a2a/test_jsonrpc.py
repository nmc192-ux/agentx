"""
Tests: A2A JSON-RPC 2.0 endpoint and handlers
  platform/src/a2a/jsonrpc.py  — models
  platform/src/a2a/handler.py  — message/send, tasks/get
  platform/src/a2a/router.py   — POST /a2a

Coverage:
  JSONRPCRequest / JSONRPCResponse / JSONRPCError models
  A2AMessage / A2APart / A2ATask models
  handle_message_send() — happy path, invalid params, task creation
  handle_tasks_get()    — happy path, unknown task, bad UUID
  POST /a2a — method dispatch, parse error, invalid request, method not found
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.a2a.jsonrpc import (
    A2AArtifact,
    A2AMessage,
    A2APart,
    A2ATask,
    A2ATaskStatus,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    MessageSendParams,
    TasksGetParams,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

TASK_ID = str(uuid4())
AGENT_DID = "did:agentx:external-001"


def _text_message(text: str = "Analyse this dataset") -> dict:
    return {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": str(uuid4()),
    }


def _send_params(text: str = "Do some work", caller_did: str = AGENT_DID) -> dict:
    return {
        "message": _text_message(text),
        "metadata": {"caller_did": caller_did},
    }


def _mock_task(task_id: str = TASK_ID, status: str = "open") -> MagicMock:
    t = MagicMock()
    t.task_id   = task_id
    t.task_type = "a2a_request"
    t.payload   = {"text": "Do some work"}
    t.reward    = 0
    t.status    = status
    t.created_at = datetime.now(timezone.utc)
    return t


def _db_ctx(row):
    ctx = MagicMock()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__  = AsyncMock(return_value=None)
    return ctx


def _db_row(task_id: str = TASK_ID, status: str = "open") -> MagicMock:
    row = MagicMock()
    data = {
        "task_id":    task_id,
        "task_type":  "a2a_request",
        "payload":    {"text": "test"},
        "reward":     0,
        "status":     status,
        "created_at": datetime.now(timezone.utc),
    }
    row.__getitem__ = lambda self, k: data[k]
    row.get = lambda k, default=None: data.get(k, default)
    return row


@pytest.fixture
def client():
    from src.a2a.router import a2a_router
    app = FastAPI()
    app.include_router(a2a_router)
    return TestClient(app)


def _rpc_body(method: str, params: dict, req_id: Any = 1) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}


# ── JSONRPCRequest model ──────────────────────────────────────────────────────

class TestJSONRPCRequest:

    def test_valid_request(self):
        req = JSONRPCRequest(method="message/send", params={"x": 1}, id=42)
        assert req.jsonrpc == "2.0"
        assert req.method == "message/send"
        assert req.id == 42

    def test_default_params_empty_dict(self):
        req = JSONRPCRequest(method="tasks/get")
        assert req.params == {}

    def test_none_id_allowed(self):
        req = JSONRPCRequest(method="tasks/get", id=None)
        assert req.id is None

    def test_string_id_allowed(self):
        req = JSONRPCRequest(method="tasks/get", id="abc-123")
        assert req.id == "abc-123"


class TestJSONRPCResponse:

    def test_ok_factory(self):
        resp = JSONRPCResponse.ok(1, {"task_id": TASK_ID})
        assert resp.jsonrpc == "2.0"
        assert resp.id == 1
        assert resp.result == {"task_id": TASK_ID}
        assert resp.error is None

    def test_err_factory(self):
        resp = JSONRPCResponse.err(2, -32601, "Method not found")
        assert resp.error is not None
        assert resp.error.code == -32601
        assert resp.result is None

    def test_err_with_data(self):
        resp = JSONRPCResponse.err(3, -32603, "Internal error", data="details")
        assert resp.error.data == "details"

    def test_serialises_without_none_fields(self):
        resp = JSONRPCResponse.ok(1, "pong")
        data = resp.model_dump(exclude_none=True)
        assert "error" not in data


# ── A2A models ────────────────────────────────────────────────────────────────

class TestA2APart:

    def test_text_part(self):
        p = A2APart(kind="text", text="hello")
        assert p.extract_text() == "hello"

    def test_data_part(self):
        p = A2APart(kind="data", data={"key": "value"})
        assert "key" in p.extract_text()

    def test_file_part_name(self):
        p = A2APart(kind="file", file={"name": "report.pdf"})
        assert "report.pdf" in p.extract_text()

    def test_empty_part_returns_empty_string(self):
        p = A2APart(kind="text")
        assert p.extract_text() == ""


class TestA2AMessage:

    def test_full_text_concatenates_parts(self):
        msg = A2AMessage(
            role="user",
            parts=[
                A2APart(kind="text", text="Part one."),
                A2APart(kind="text", text="Part two."),
            ],
        )
        text = msg.full_text()
        assert "Part one." in text
        assert "Part two." in text

    def test_message_id_auto_generated(self):
        msg = A2AMessage(role="user", parts=[])
        assert msg.messageId  # non-empty

    def test_empty_parts_full_text_is_empty(self):
        msg = A2AMessage(role="user", parts=[])
        assert msg.full_text() == ""


class TestA2ATask:

    def test_task_defaults(self):
        task = A2ATask(
            id=TASK_ID,
            status=A2ATaskStatus(state="submitted"),
        )
        assert task.artifacts == []
        assert task.history == []
        assert task.metadata == {}


# ── handle_message_send ────────────────────────────────────────────────────────

class TestHandleMessageSend:

    @pytest.mark.asyncio
    async def test_happy_path_returns_a2a_task(self):
        from src.a2a.handler import handle_message_send
        mock_task = _mock_task()
        with patch(
            "src.a2a.handler.task_service.create_task",
            new_callable=AsyncMock,
            return_value=mock_task,
        ):
            result = await handle_message_send(_send_params())

        assert "id" in result
        assert result["status"]["state"] == "submitted"

    @pytest.mark.asyncio
    async def test_text_extracted_from_parts(self):
        from src.a2a.handler import handle_message_send
        mock_task = _mock_task()
        with patch(
            "src.a2a.handler.task_service.create_task",
            new_callable=AsyncMock,
            return_value=mock_task,
        ) as mock_create:
            await handle_message_send(_send_params("Analyse revenue data"))

        call_kwargs = mock_create.call_args.kwargs
        assert "Analyse revenue data" in call_kwargs["payload"]["text"]

    @pytest.mark.asyncio
    async def test_task_type_is_a2a_request(self):
        from src.a2a.handler import handle_message_send
        mock_task = _mock_task()
        with patch(
            "src.a2a.handler.task_service.create_task",
            new_callable=AsyncMock,
            return_value=mock_task,
        ) as mock_create:
            await handle_message_send(_send_params())

        assert mock_create.call_args.kwargs["task_type"] == "a2a_request"

    @pytest.mark.asyncio
    async def test_reward_is_zero_for_external_tasks(self):
        from src.a2a.handler import handle_message_send
        mock_task = _mock_task()
        with patch(
            "src.a2a.handler.task_service.create_task",
            new_callable=AsyncMock,
            return_value=mock_task,
        ) as mock_create:
            await handle_message_send(_send_params())

        assert mock_create.call_args.kwargs["reward"] == 0

    @pytest.mark.asyncio
    async def test_invalid_params_raises_value_error(self):
        from src.a2a.handler import handle_message_send
        with pytest.raises(ValueError, match="Invalid message/send params"):
            await handle_message_send({"bad_field": "no_message"})

    @pytest.mark.asyncio
    async def test_completed_task_has_artifact(self):
        from src.a2a.handler import handle_message_send
        mock_task = _mock_task(status="completed")
        with patch(
            "src.a2a.handler.task_service.create_task",
            new_callable=AsyncMock,
            return_value=mock_task,
        ):
            result = await handle_message_send(_send_params())

        # completed state maps artifacts
        assert result["status"]["state"] == "completed"
        assert len(result.get("artifacts", [])) > 0


# ── handle_tasks_get ──────────────────────────────────────────────────────────

class TestHandleTasksGet:

    @pytest.mark.asyncio
    async def test_happy_path_returns_task(self):
        from src.a2a.handler import handle_tasks_get
        row = _db_row(task_id=TASK_ID)
        with patch("src.a2a.handler.get_db", return_value=_db_ctx(row)):
            result = await handle_tasks_get({"id": TASK_ID})

        assert result["id"] == TASK_ID
        assert "status" in result

    @pytest.mark.asyncio
    async def test_unknown_task_raises_value_error(self):
        from src.a2a.handler import handle_tasks_get
        with patch("src.a2a.handler.get_db", return_value=_db_ctx(None)):
            with pytest.raises(ValueError, match="Task not found"):
                await handle_tasks_get({"id": TASK_ID})

    @pytest.mark.asyncio
    async def test_bad_uuid_raises_value_error(self):
        from src.a2a.handler import handle_tasks_get
        with pytest.raises(ValueError, match="Invalid task ID"):
            await handle_tasks_get({"id": "not-a-uuid"})

    @pytest.mark.asyncio
    async def test_missing_id_raises_value_error(self):
        from src.a2a.handler import handle_tasks_get
        with pytest.raises(ValueError, match="Invalid tasks/get params"):
            await handle_tasks_get({})

    @pytest.mark.asyncio
    async def test_status_mapped_correctly(self):
        from src.a2a.handler import handle_tasks_get
        row = _db_row(task_id=TASK_ID, status="in_progress")
        with patch("src.a2a.handler.get_db", return_value=_db_ctx(row)):
            result = await handle_tasks_get({"id": TASK_ID})

        assert result["status"]["state"] == "working"


# ── POST /a2a router ──────────────────────────────────────────────────────────

class TestA2AJsonRpcEndpoint:

    def test_parse_error_on_non_json(self, client):
        resp = client.post("/a2a", content="not json", headers={"Content-Type": "application/json"})
        assert resp.status_code == 200  # JSON-RPC errors use 200
        data = resp.json()
        assert data["error"]["code"] == JSONRPCError.PARSE_ERROR

    def test_invalid_request_missing_method(self, client):
        resp = client.post("/a2a", json={"jsonrpc": "2.0", "id": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == JSONRPCError.INVALID_REQUEST

    def test_method_not_found(self, client):
        resp = client.post("/a2a", json=_rpc_body("unknown/method", {}))
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == JSONRPCError.METHOD_NOT_FOUND
        assert "unknown/method" in data["error"]["message"]

    def test_method_not_found_lists_available_methods(self, client):
        resp = client.post("/a2a", json=_rpc_body("no/such", {}))
        data = resp.json()
        assert "message/send" in data["error"]["data"]["available_methods"]
        assert "tasks/get"    in data["error"]["data"]["available_methods"]

    def test_message_send_happy_path(self, client):
        mock_task = _mock_task()
        with patch(
            "src.a2a.handler.task_service.create_task",
            new_callable=AsyncMock,
            return_value=mock_task,
        ):
            resp = client.post("/a2a", json=_rpc_body("message/send", _send_params()))

        assert resp.status_code == 200
        data = resp.json()
        assert data.get("error") is None
        assert "status" in data["result"]
        assert data["result"]["status"]["state"] == "submitted"

    def test_message_send_returns_correct_id(self, client):
        mock_task = _mock_task()
        with patch(
            "src.a2a.handler.task_service.create_task",
            new_callable=AsyncMock,
            return_value=mock_task,
        ):
            resp = client.post("/a2a", json=_rpc_body("message/send", _send_params(), req_id=99))

        assert resp.json()["id"] == 99

    def test_message_send_invalid_params(self, client):
        resp = client.post("/a2a", json=_rpc_body("message/send", {"wrong": "field"}))
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == JSONRPCError.INVALID_PARAMS

    def test_tasks_get_happy_path(self, client):
        row = _db_row(task_id=TASK_ID)
        with patch("src.a2a.handler.get_db", return_value=_db_ctx(row)):
            resp = client.post("/a2a", json=_rpc_body("tasks/get", {"id": TASK_ID}))

        assert resp.status_code == 200
        data = resp.json()
        assert data.get("error") is None
        assert data["result"]["id"] == TASK_ID

    def test_tasks_get_not_found(self, client):
        with patch("src.a2a.handler.get_db", return_value=_db_ctx(None)):
            resp = client.post("/a2a", json=_rpc_body("tasks/get", {"id": TASK_ID}))

        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == JSONRPCError.INVALID_PARAMS
        assert "not found" in data["error"]["message"]

    def test_tasks_get_invalid_uuid(self, client):
        resp = client.post("/a2a", json=_rpc_body("tasks/get", {"id": "not-a-uuid"}))
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == JSONRPCError.INVALID_PARAMS

    def test_jsonrpc_version_always_2_0(self, client):
        resp = client.post("/a2a", json=_rpc_body("unknown/x", {}))
        assert resp.json()["jsonrpc"] == "2.0"

    def test_notification_request_no_id(self, client):
        """Requests without id are notifications — response id must be null."""
        body = {"jsonrpc": "2.0", "method": "unknown/x", "params": {}}
        resp = client.post("/a2a", json=body)
        assert resp.status_code == 200
        # id absent or null in response
        assert resp.json().get("id") is None
