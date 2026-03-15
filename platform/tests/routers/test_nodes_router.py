"""
Tests: src/routers/node_router.py
Phase 17 — Federated AgentX Nodes

Endpoints covered
─────────────────
  POST /nodes/register  — 201, 400
  GET  /nodes           — 200 (empty + populated, active_only filter)
  POST /nodes/events    — 202, 400, 422
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.models.node import NodeMessageResponse, NodeResponse
from src.services import node_service

client = TestClient(app)

NOW = datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ─────────────────────────────────────────────────────────────────────────────

def _node(
    url: str = "https://peer.agentx.io",
    name: str | None = "PeerNode",
    status: str = "active",
) -> NodeResponse:
    return NodeResponse(
        node_id=uuid4(),
        node_url=url,
        node_name=name,
        status=status,
        trust_level=0.5,
        registered_at=NOW,
    )


def _msg(
    event_type: str = "CONTRACT_COMPLETED",
    direction: str = "inbound",
    node_id: UUID | None = None,
) -> NodeMessageResponse:
    return NodeMessageResponse(
        message_id=uuid4(),
        node_id=node_id,
        event_type=event_type,
        payload={},
        direction=direction,
        created_at=NOW,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /nodes/register
# ─────────────────────────────────────────────────────────────────────────────

class TestRegisterNode:

    def test_register_returns_201(self):
        node = _node()
        with patch(
            "src.routers.node_router.node_service.register_node",
            new_callable=AsyncMock,
            return_value=node,
        ):
            resp = client.post("/nodes/register", json={"node_url": "https://peer.io"})
        assert resp.status_code == 201

    def test_register_returns_node_data(self):
        node = _node(url="https://peer2.io", name="Alpha")
        with patch(
            "src.routers.node_router.node_service.register_node",
            new_callable=AsyncMock,
            return_value=node,
        ):
            resp = client.post("/nodes/register", json={"node_url": "https://peer2.io", "node_name": "Alpha"})
        data = resp.json()
        assert "node_id" in data
        assert data["node_url"] == "https://peer2.io"

    def test_register_with_name_and_public_key(self):
        node = _node()
        with patch(
            "src.routers.node_router.node_service.register_node",
            new_callable=AsyncMock,
            return_value=node,
        ) as mock:
            resp = client.post(
                "/nodes/register",
                json={"node_url": "https://peer.io", "node_name": "X", "public_key": "pem"},
            )
        assert resp.status_code == 201
        mock.assert_called_once_with(
            node_url="https://peer.io",
            node_name="X",
            public_key="pem",
        )

    def test_register_missing_node_url_returns_422(self):
        resp = client.post("/nodes/register", json={})
        assert resp.status_code == 422

    def test_register_service_error_returns_400(self):
        with patch(
            "src.routers.node_router.node_service.register_node",
            new_callable=AsyncMock,
            side_effect=Exception("DB error"),
        ):
            resp = client.post("/nodes/register", json={"node_url": "https://peer.io"})
        assert resp.status_code == 400

    def test_register_upsert_idempotent(self):
        """Registering the same URL twice should still return 201."""
        node = _node()
        with patch(
            "src.routers.node_router.node_service.register_node",
            new_callable=AsyncMock,
            return_value=node,
        ):
            r1 = client.post("/nodes/register", json={"node_url": "https://peer.io"})
            r2 = client.post("/nodes/register", json={"node_url": "https://peer.io"})
        assert r1.status_code == 201
        assert r2.status_code == 201

    def test_register_node_url_too_long_returns_422(self):
        resp = client.post("/nodes/register", json={"node_url": "x" * 501})
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# GET /nodes
# ─────────────────────────────────────────────────────────────────────────────

class TestListNodes:

    def test_list_returns_200(self):
        with patch(
            "src.routers.node_router.node_service.list_nodes",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/nodes")
        assert resp.status_code == 200

    def test_list_empty(self):
        with patch(
            "src.routers.node_router.node_service.list_nodes",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/nodes")
        assert resp.json() == []

    def test_list_populated(self):
        nodes = [_node(url=f"https://peer{i}.io") for i in range(3)]
        with patch(
            "src.routers.node_router.node_service.list_nodes",
            new_callable=AsyncMock,
            return_value=nodes,
        ):
            resp = client.get("/nodes")
        assert len(resp.json()) == 3

    def test_list_contains_expected_fields(self):
        nodes = [_node()]
        with patch(
            "src.routers.node_router.node_service.list_nodes",
            new_callable=AsyncMock,
            return_value=nodes,
        ):
            resp = client.get("/nodes")
        item = resp.json()[0]
        assert "node_id"   in item
        assert "node_url"  in item
        assert "status"    in item
        assert "trust_level" in item

    def test_active_only_param_passed_to_service(self):
        with patch(
            "src.routers.node_router.node_service.list_nodes",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock:
            client.get("/nodes?active_only=true")
        mock.assert_called_once_with(active_only=True)

    def test_default_active_only_false(self):
        with patch(
            "src.routers.node_router.node_service.list_nodes",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock:
            client.get("/nodes")
        mock.assert_called_once_with(active_only=False)


# ─────────────────────────────────────────────────────────────────────────────
# POST /nodes/events
# ─────────────────────────────────────────────────────────────────────────────

class TestReceiveEvent:

    def test_receive_returns_202(self):
        msg = _msg()
        with patch(
            "src.routers.node_router.node_service.send_node_message",
            new_callable=AsyncMock,
            return_value=msg,
        ):
            with patch(
                "src.routers.node_router.node_service.list_nodes",
                new_callable=AsyncMock,
                return_value=[],
            ):
                resp = client.post(
                    "/nodes/events",
                    json={"event_type": "CONTRACT_COMPLETED", "payload": {}},
                )
        assert resp.status_code == 202

    def test_receive_returns_message_data(self):
        msg = _msg(event_type="TASK_COMPLETED")
        with patch(
            "src.routers.node_router.node_service.send_node_message",
            new_callable=AsyncMock,
            return_value=msg,
        ):
            with patch(
                "src.routers.node_router.node_service.list_nodes",
                new_callable=AsyncMock,
                return_value=[],
            ):
                resp = client.post(
                    "/nodes/events",
                    json={"event_type": "TASK_COMPLETED"},
                )
        data = resp.json()
        assert "message_id" in data
        assert data["event_type"] == "TASK_COMPLETED"

    def test_receive_direction_is_inbound(self):
        msg = _msg(direction="inbound")
        with patch(
            "src.routers.node_router.node_service.send_node_message",
            new_callable=AsyncMock,
            return_value=msg,
        ) as sm:
            with patch(
                "src.routers.node_router.node_service.list_nodes",
                new_callable=AsyncMock,
                return_value=[],
            ):
                client.post("/nodes/events", json={"event_type": "X"})
        sm.assert_called_once()
        assert sm.call_args[1]["direction"] == "inbound"

    def test_receive_missing_event_type_returns_422(self):
        resp = client.post("/nodes/events", json={"payload": {}})
        assert resp.status_code == 422

    def test_receive_with_source_node_url_resolves_node_id(self):
        """If source_node_url matches a registered node, node_id is filled."""
        nid  = uuid4()
        peer = NodeResponse(
            node_id=nid,
            node_url="https://source.io",
            status="active",
            trust_level=0.5,
            registered_at=NOW,
        )
        msg = _msg(node_id=nid)
        with patch(
            "src.routers.node_router.node_service.list_nodes",
            new_callable=AsyncMock,
            return_value=[peer],
        ):
            with patch(
                "src.routers.node_router.node_service.send_node_message",
                new_callable=AsyncMock,
                return_value=msg,
            ) as sm:
                client.post(
                    "/nodes/events",
                    json={
                        "event_type": "X",
                        "source_node_url": "https://source.io",
                    },
                )
        assert sm.call_args[1]["node_id"] == nid

    def test_receive_unknown_source_url_uses_null_node_id(self):
        msg = _msg(node_id=None)
        with patch(
            "src.routers.node_router.node_service.list_nodes",
            new_callable=AsyncMock,
            return_value=[],
        ):
            with patch(
                "src.routers.node_router.node_service.send_node_message",
                new_callable=AsyncMock,
                return_value=msg,
            ) as sm:
                client.post(
                    "/nodes/events",
                    json={"event_type": "X", "source_node_url": "https://unknown.io"},
                )
        assert sm.call_args[1]["node_id"] is None

    def test_receive_service_error_returns_400(self):
        with patch(
            "src.routers.node_router.node_service.list_nodes",
            new_callable=AsyncMock,
            return_value=[],
        ):
            with patch(
                "src.routers.node_router.node_service.send_node_message",
                new_callable=AsyncMock,
                side_effect=Exception("db error"),
            ):
                resp = client.post("/nodes/events", json={"event_type": "X"})
        assert resp.status_code == 400

    def test_receive_with_payload_data(self):
        msg = _msg()
        payload = {"contract_id": "c1", "agent_id": "a1"}
        with patch(
            "src.routers.node_router.node_service.send_node_message",
            new_callable=AsyncMock,
            return_value=msg,
        ) as sm:
            with patch(
                "src.routers.node_router.node_service.list_nodes",
                new_callable=AsyncMock,
                return_value=[],
            ):
                client.post("/nodes/events", json={"event_type": "CONTRACT_COMPLETED", "payload": payload})
        assert sm.call_args[1]["payload"] == payload

    def test_receive_empty_payload_default(self):
        msg = _msg()
        with patch(
            "src.routers.node_router.node_service.send_node_message",
            new_callable=AsyncMock,
            return_value=msg,
        ) as sm:
            with patch(
                "src.routers.node_router.node_service.list_nodes",
                new_callable=AsyncMock,
                return_value=[],
            ):
                client.post("/nodes/events", json={"event_type": "X"})
        # payload defaults to {}
        assert sm.call_args[1]["payload"] == {}
