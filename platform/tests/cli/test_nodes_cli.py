"""
Tests: agentx_cli/node_cmd.py — Node CLI Commands
Phase 17 — Federated AgentX Nodes

Subcommands covered
───────────────────
  agentx node start       — register this node
  agentx node peers       — list peer nodes
  agentx node register    — register a peer URL
  agentx node send-event  — push a federated event
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from agentx_cli.main import app

runner = CliRunner()
NOW = datetime.now(timezone.utc)

# ─────────────────────────────────────────────────────────────────────────────
# Mock fixtures
# ─────────────────────────────────────────────────────────────────────────────

MOCK_CONFIG = MagicMock()
MOCK_CONFIG.api_url = "https://api.agentx.io"
MOCK_CONFIG.api_key = "tok"


def _node(url: str = "https://peer.io", name: str = "PeerNode") -> dict:
    return {
        "node_id":       str(uuid4()),
        "node_url":      url,
        "node_name":     name,
        "public_key":    None,
        "status":        "active",
        "trust_level":   0.5,
        "registered_at": NOW.isoformat(),
        "last_seen_at":  None,
    }


def _msg(event_type: str = "CONTRACT_COMPLETED") -> dict:
    return {
        "message_id": str(uuid4()),
        "node_id":    None,
        "event_type": event_type,
        "payload":    {},
        "direction":  "inbound",
        "created_at": NOW.isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# agentx node start
# ─────────────────────────────────────────────────────────────────────────────

class TestNodeStart:

    def test_start_success(self):
        node = _node()
        mock_client = MagicMock()
        mock_client.register_node = AsyncMock(return_value=node)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "start", "https://my-node.io"])
        assert result.exit_code == 0
        assert "Node registered" in result.output

    def test_start_shows_node_id(self):
        node = _node()
        mock_client = MagicMock()
        mock_client.register_node = AsyncMock(return_value=node)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "start", "https://my-node.io"])
        assert node["node_id"] in result.output

    def test_start_shows_url(self):
        node = _node(url="https://custom.io")
        mock_client = MagicMock()
        mock_client.register_node = AsyncMock(return_value=node)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "start", "https://custom.io"])
        assert "https://custom.io" in result.output

    def test_start_with_name_option(self):
        node = _node(name="MyNode")
        mock_client = MagicMock()
        mock_client.register_node = AsyncMock(return_value=node)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(
                    app,
                    ["node", "start", "https://my-node.io", "--name", "MyNode"],
                )
        assert result.exit_code == 0
        mock_client.register_node.assert_called_once_with(
            node_url="https://my-node.io",
            node_name="MyNode",
        )

    def test_start_shows_status(self):
        node = _node()
        mock_client = MagicMock()
        mock_client.register_node = AsyncMock(return_value=node)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "start", "https://my-node.io"])
        assert "Status" in result.output or "status" in result.output.lower()

    def test_start_missing_url_exits_with_error(self):
        result = runner.invoke(app, ["node", "start"])
        assert result.exit_code != 0


# ─────────────────────────────────────────────────────────────────────────────
# agentx node peers
# ─────────────────────────────────────────────────────────────────────────────

class TestNodePeers:

    def test_peers_empty(self):
        mock_client = MagicMock()
        mock_client.list_nodes = AsyncMock(return_value=[])
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "peers"])
        assert result.exit_code == 0
        assert "No peer nodes" in result.output

    def test_peers_lists_nodes(self):
        nodes = [_node(url=f"https://peer{i}.io") for i in range(2)]
        mock_client = MagicMock()
        mock_client.list_nodes = AsyncMock(return_value=nodes)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "peers"])
        assert result.exit_code == 0
        assert "2 peer node" in result.output

    def test_peers_shows_url(self):
        nodes = [_node(url="https://unique-peer.io")]
        mock_client = MagicMock()
        mock_client.list_nodes = AsyncMock(return_value=nodes)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "peers"])
        assert "https://unique-peer.io" in result.output

    def test_peers_active_flag(self):
        mock_client = MagicMock()
        mock_client.list_nodes = AsyncMock(return_value=[])
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                runner.invoke(app, ["node", "peers", "--active"])
        mock_client.list_nodes.assert_called_once_with(active_only=True)

    def test_peers_shows_trust_level(self):
        nodes = [_node()]
        mock_client = MagicMock()
        mock_client.list_nodes = AsyncMock(return_value=nodes)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "peers"])
        assert "trust=" in result.output

    def test_peers_multiple_nodes_numbered(self):
        nodes = [_node(url=f"https://p{i}.io") for i in range(3)]
        mock_client = MagicMock()
        mock_client.list_nodes = AsyncMock(return_value=nodes)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "peers"])
        assert "# 1" in result.output
        assert "# 2" in result.output
        assert "# 3" in result.output


# ─────────────────────────────────────────────────────────────────────────────
# agentx node register
# ─────────────────────────────────────────────────────────────────────────────

class TestNodeRegister:

    def test_register_success(self):
        node = _node(url="https://newpeer.io")
        mock_client = MagicMock()
        mock_client.register_node = AsyncMock(return_value=node)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "register", "https://newpeer.io"])
        assert result.exit_code == 0
        assert "Peer registered" in result.output

    def test_register_shows_url(self):
        node = _node(url="https://x.io")
        mock_client = MagicMock()
        mock_client.register_node = AsyncMock(return_value=node)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "register", "https://x.io"])
        assert "https://x.io" in result.output

    def test_register_shows_node_id(self):
        node = _node()
        mock_client = MagicMock()
        mock_client.register_node = AsyncMock(return_value=node)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "register", "https://x.io"])
        assert node["node_id"] in result.output

    def test_register_with_name(self):
        node = _node(name="TestPeer")
        mock_client = MagicMock()
        mock_client.register_node = AsyncMock(return_value=node)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(
                    app,
                    ["node", "register", "https://x.io", "--name", "TestPeer"],
                )
        assert result.exit_code == 0
        mock_client.register_node.assert_called_once_with(
            node_url="https://x.io",
            node_name="TestPeer",
        )

    def test_register_missing_url_exits_error(self):
        result = runner.invoke(app, ["node", "register"])
        assert result.exit_code != 0


# ─────────────────────────────────────────────────────────────────────────────
# agentx node send-event
# ─────────────────────────────────────────────────────────────────────────────

class TestNodeSendEvent:

    def test_send_event_success(self):
        msg = _msg("CONTRACT_COMPLETED")
        mock_client = MagicMock()
        mock_client.send_event = AsyncMock(return_value=msg)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "send-event", "CONTRACT_COMPLETED"])
        assert result.exit_code == 0
        assert "Event accepted" in result.output

    def test_send_event_shows_message_id(self):
        msg = _msg()
        mock_client = MagicMock()
        mock_client.send_event = AsyncMock(return_value=msg)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "send-event", "X"])
        assert msg["message_id"] in result.output

    def test_send_event_shows_direction(self):
        msg = _msg()
        mock_client = MagicMock()
        mock_client.send_event = AsyncMock(return_value=msg)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "send-event", "X"])
        assert "inbound" in result.output

    def test_send_event_with_source_option(self):
        msg = _msg()
        mock_client = MagicMock()
        mock_client.send_event = AsyncMock(return_value=msg)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                runner.invoke(
                    app,
                    ["node", "send-event", "TASK_COMPLETED", "--source", "https://src.io"],
                )
        mock_client.send_event.assert_called_once_with(
            event_type="TASK_COMPLETED",
            payload={},
            source_node_url="https://src.io",
        )

    def test_send_event_missing_event_type_fails(self):
        result = runner.invoke(app, ["node", "send-event"])
        assert result.exit_code != 0

    def test_send_event_shows_event_type(self):
        msg = _msg("BOUNTY_REWARD_DISTRIBUTED")
        mock_client = MagicMock()
        mock_client.send_event = AsyncMock(return_value=msg)
        with patch("agentx_cli.node_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.node_cmd.NodesClient", return_value=mock_client):
                result = runner.invoke(app, ["node", "send-event", "BOUNTY_REWARD_DISTRIBUTED"])
        assert "BOUNTY_REWARD_DISTRIBUTED" in result.output
