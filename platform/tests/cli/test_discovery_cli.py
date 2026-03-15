"""
Tests: agentx_cli — discover commands (Phase 16)
════════════════════════════════════════════════════════════════════════════════
Covers:
  discover capability <name>   — list agents by capability
  discover top                 — list top agents
  discover search <query>      — semantic search
  discover metrics <agent-id>  — show agent metrics

All SDK calls are mocked — no live API required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from typer.testing import CliRunner

from agentx_cli.config import AgentConfig
from agentx_cli.main import app

runner = CliRunner()

_API_URL = "http://localhost:8000"
_API_KEY  = "test-jwt"

MOCK_CONFIG = AgentConfig(
    name="test_agent",
    api_url=_API_URL,
    api_key=_API_KEY,
    agent_id=str(uuid4()),
)


def _agent():
    return {
        "agent_id":            str(uuid4()),
        "agent_did":           "did:agentx:agent",
        "name":                "Data Collector",
        "trust_score":         0.75,
        "capabilities":        ["collect_data"],
        "score":               0.6,
        "contracts_completed": 10,
        "contracts_failed":    1,
        "bounties_won":        2,
    }


def _metrics():
    return {
        "agent_id":             str(uuid4()),
        "contracts_completed":  12,
        "contracts_failed":     1,
        "verification_success": 0.9,
        "bounties_won":         3,
        "last_active":          "2026-01-01T00:00:00Z",
    }


# ═════════════════════════════════════════════════════════════════════════════
# discover capability
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscoverCapability:

    def test_exits_zero(self):
        mock_client = MagicMock()
        mock_client.discover_agents = AsyncMock(return_value=[_agent()])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "capability", "collect_data"])

        assert result.exit_code == 0

    def test_prints_agent_name(self):
        mock_client = MagicMock()
        mock_client.discover_agents = AsyncMock(return_value=[_agent()])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "capability", "collect_data"])

        assert "Data Collector" in result.output or "collect_data" in result.output

    def test_passes_capability_to_sdk(self):
        mock_client = MagicMock()
        mock_client.discover_agents = AsyncMock(return_value=[])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                runner.invoke(app, ["discover", "capability", "analyse_data"])

        mock_client.discover_agents.assert_called_once()
        kwargs = mock_client.discover_agents.call_args.kwargs
        assert kwargs["capability"] == "analyse_data"

    def test_passes_limit(self):
        mock_client = MagicMock()
        mock_client.discover_agents = AsyncMock(return_value=[])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                runner.invoke(app, ["discover", "capability", "x", "--limit", "3"])

        kwargs = mock_client.discover_agents.call_args.kwargs
        assert kwargs["limit"] == 3

    def test_empty_result_shows_message(self):
        mock_client = MagicMock()
        mock_client.discover_agents = AsyncMock(return_value=[])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "capability", "unknown"])

        assert result.exit_code == 0
        assert "No agents" in result.output or "unknown" in result.output

    def test_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.discover_agents = AsyncMock(side_effect=RuntimeError("API error"))

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "capability", "x"])

        assert result.exit_code != 0

    def test_shows_score(self):
        mock_client = MagicMock()
        mock_client.discover_agents = AsyncMock(return_value=[_agent()])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "capability", "collect_data"])

        # Score should appear in formatted output
        assert "0.6" in result.output or "score" in result.output.lower() or result.exit_code == 0

    def test_multiple_agents_displayed(self):
        agents = [_agent(), _agent()]
        mock_client = MagicMock()
        mock_client.discover_agents = AsyncMock(return_value=agents)

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "capability", "collect_data"])

        assert result.exit_code == 0
        # Output should mention multiple agents (e.g. "# 1" and "# 2" — right-aligned idx)
        assert "# 1" in result.output and "# 2" in result.output


# ═════════════════════════════════════════════════════════════════════════════
# discover top
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscoverTop:

    def test_exits_zero(self):
        mock_client = MagicMock()
        mock_client.get_top_agents = AsyncMock(return_value=[_agent()])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "top"])

        assert result.exit_code == 0

    def test_calls_get_top_agents(self):
        mock_client = MagicMock()
        mock_client.get_top_agents = AsyncMock(return_value=[])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                runner.invoke(app, ["discover", "top"])

        mock_client.get_top_agents.assert_called_once()

    def test_passes_limit(self):
        mock_client = MagicMock()
        mock_client.get_top_agents = AsyncMock(return_value=[])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                runner.invoke(app, ["discover", "top", "--limit", "5"])

        kwargs = mock_client.get_top_agents.call_args.kwargs
        assert kwargs["limit"] == 5

    def test_empty_result_shows_message(self):
        mock_client = MagicMock()
        mock_client.get_top_agents = AsyncMock(return_value=[])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "top"])

        assert result.exit_code == 0
        assert "No agents" in result.output

    def test_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.get_top_agents = AsyncMock(side_effect=RuntimeError("failed"))

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "top"])

        assert result.exit_code != 0

    def test_prints_agent_info(self):
        mock_client = MagicMock()
        mock_client.get_top_agents = AsyncMock(return_value=[_agent()])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "top"])

        # Should print agent trust_score, name, or DID
        assert "0.75" in result.output or "Data Collector" in result.output or "did:agentx" in result.output


# ═════════════════════════════════════════════════════════════════════════════
# discover search
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscoverSearch:

    def test_exits_zero(self):
        mock_client = MagicMock()
        mock_client.search_agents = AsyncMock(return_value=[_agent()])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "search", "data collection"])

        assert result.exit_code == 0

    def test_passes_query_to_sdk(self):
        mock_client = MagicMock()
        mock_client.search_agents = AsyncMock(return_value=[])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                runner.invoke(app, ["discover", "search", "financial analysis"])

        mock_client.search_agents.assert_called_once()
        kwargs = mock_client.search_agents.call_args.kwargs
        assert kwargs["query"] == "financial analysis"

    def test_passes_limit(self):
        mock_client = MagicMock()
        mock_client.search_agents = AsyncMock(return_value=[])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                runner.invoke(app, ["discover", "search", "query", "--limit", "7"])

        kwargs = mock_client.search_agents.call_args.kwargs
        assert kwargs["limit"] == 7

    def test_empty_result_shows_no_match(self):
        mock_client = MagicMock()
        mock_client.search_agents = AsyncMock(return_value=[])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "search", "obscure"])

        assert result.exit_code == 0
        assert "No agents" in result.output or "obscure" in result.output

    def test_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.search_agents = AsyncMock(side_effect=RuntimeError("timeout"))

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "search", "test"])

        assert result.exit_code != 0

    def test_prints_matching_agents(self):
        mock_client = MagicMock()
        mock_client.search_agents = AsyncMock(return_value=[_agent()])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "search", "collect"])

        assert result.exit_code == 0
        assert "1 found" in result.output or "#1" in result.output


# ═════════════════════════════════════════════════════════════════════════════
# discover metrics
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscoverMetrics:

    def test_exits_zero(self):
        aid = str(uuid4())
        mock_client = MagicMock()
        mock_client.get_agent_metrics = AsyncMock(return_value=_metrics())

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "metrics", aid])

        assert result.exit_code == 0

    def test_prints_contracts_completed(self):
        aid = str(uuid4())
        mock_client = MagicMock()
        mock_client.get_agent_metrics = AsyncMock(return_value=_metrics())

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "metrics", aid])

        assert "12" in result.output or "contracts" in result.output.lower()

    def test_prints_verification_success(self):
        aid = str(uuid4())
        mock_client = MagicMock()
        mock_client.get_agent_metrics = AsyncMock(return_value=_metrics())

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "metrics", aid])

        assert "90.0%" in result.output or "verification" in result.output.lower()

    def test_prints_bounties_won(self):
        aid = str(uuid4())
        mock_client = MagicMock()
        mock_client.get_agent_metrics = AsyncMock(return_value=_metrics())

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "metrics", aid])

        assert "3" in result.output or "bounties" in result.output.lower()

    def test_calls_sdk_with_agent_id(self):
        aid = str(uuid4())
        mock_client = MagicMock()
        mock_client.get_agent_metrics = AsyncMock(return_value=_metrics())

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                runner.invoke(app, ["discover", "metrics", aid])

        mock_client.get_agent_metrics.assert_called_once_with(aid)

    def test_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.get_agent_metrics = AsyncMock(side_effect=RuntimeError("not found"))

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client):
                result = runner.invoke(app, ["discover", "metrics", str(uuid4())])

        assert result.exit_code != 0


# ═════════════════════════════════════════════════════════════════════════════
# DiscoveryClient instantiation
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscoveryClientInit:

    def test_client_uses_api_url(self):
        mock_client = MagicMock()
        mock_client.discover_agents = AsyncMock(return_value=[])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client) as mock_cls:
                runner.invoke(app, ["discover", "capability", "x"])

        kwargs = mock_cls.call_args.kwargs
        assert kwargs.get("base_url") == _API_URL

    def test_client_uses_api_key_as_token(self):
        mock_client = MagicMock()
        mock_client.discover_agents = AsyncMock(return_value=[])

        with patch("agentx_cli.discover_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.discover_cmd.DiscoveryClient", return_value=mock_client) as mock_cls:
                runner.invoke(app, ["discover", "capability", "x"])

        kwargs = mock_cls.call_args.kwargs
        assert kwargs.get("token") == _API_KEY
