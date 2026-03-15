"""
Tests: agentx_cli/simulate_cmd.py — agentx simulate
Phase 18 — Multi-Agent Local Simulation

SDK and runtime calls are fully mocked; no real agents start.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from agentx_cli.main import app

runner = CliRunner()

# ─────────────────────────────────────────────────────────────────────────────
# Mock fixtures
# ─────────────────────────────────────────────────────────────────────────────

MOCK_CONFIG = MagicMock()
MOCK_CONFIG.effective_api_url = "http://localhost:8000"
MOCK_CONFIG.effective_api_key = None


def _engine_mock(num_agents: int = 3) -> MagicMock:
    """Return a SimulationEngine mock whose start() returns immediately."""
    eng = MagicMock()
    eng.start = AsyncMock(return_value=None)
    eng.agents = [MagicMock(name=f"sim_agent_{i}", capabilities=["forecast"]) for i in range(1, num_agents + 1)]
    return eng


# ─────────────────────────────────────────────────────────────────────────────
# --dry-run mode (no real runtimes; purely unit-testable)
# ─────────────────────────────────────────────────────────────────────────────

class TestDryRun:

    def test_dry_run_exit_zero(self):
        result = runner.invoke(app, ["simulate", "--agents", "3", "--dry-run"])
        assert result.exit_code == 0

    def test_dry_run_shows_agent_names(self):
        result = runner.invoke(app, ["simulate", "--agents", "3", "--dry-run"])
        assert "sim_agent_1" in result.output
        assert "sim_agent_2" in result.output
        assert "sim_agent_3" in result.output

    def test_dry_run_creates_correct_count(self):
        result = runner.invoke(app, ["simulate", "--agents", "5", "--dry-run"])
        assert result.exit_code == 0
        assert "sim_agent_5" in result.output
        assert "sim_agent_6" not in result.output

    def test_dry_run_shows_dry_run_label(self):
        result = runner.invoke(app, ["simulate", "--agents", "2", "--dry-run"])
        assert "dry-run" in result.output.lower()

    def test_dry_run_shows_banner(self):
        result = runner.invoke(app, ["simulate", "--agents", "2", "--dry-run"])
        assert "simulation" in result.output.lower()
        assert "2" in result.output

    def test_dry_run_shows_capabilities(self):
        result = runner.invoke(app, ["simulate", "--agents", "2", "--dry-run"])
        assert "caps=" in result.output

    def test_dry_run_no_agents_arg_defaults_to_five(self):
        result = runner.invoke(app, ["simulate", "--dry-run"])
        assert result.exit_code == 0
        assert "sim_agent_5" in result.output

    def test_dry_run_with_url_option(self):
        result = runner.invoke(
            app,
            ["simulate", "--agents", "2", "--dry-run", "--url", "http://custom:9000"],
        )
        assert result.exit_code == 0
        assert "http://custom:9000" in result.output

    def test_dry_run_shows_api_url(self):
        result = runner.invoke(app, ["simulate", "--agents", "2", "--dry-run"])
        assert "API URL" in result.output or "api url" in result.output.lower()

    def test_dry_run_shows_poll_interval(self):
        result = runner.invoke(
            app, ["simulate", "--agents", "2", "--dry-run", "--poll", "3.0"]
        )
        assert "3.0" in result.output

    def test_dry_run_shows_market_cycle_interval(self):
        result = runner.invoke(
            app, ["simulate", "--agents", "2", "--dry-run", "--market-interval", "8.0"]
        )
        assert "8.0" in result.output

    def test_dry_run_count_message_shown(self):
        result = runner.invoke(app, ["simulate", "--agents", "4", "--dry-run"])
        assert "4" in result.output


# ─────────────────────────────────────────────────────────────────────────────
# Live simulation (mocked engine)
# ─────────────────────────────────────────────────────────────────────────────

class TestLiveSimulation:

    def test_invokes_simulation_engine(self):
        eng = _engine_mock(num_agents=3)
        with patch("agentx_cli.simulate_cmd.SimulationEngine", return_value=eng):
            with patch("agentx_cli.simulate_cmd.load_config", return_value=MOCK_CONFIG):
                result = runner.invoke(app, ["simulate", "--agents", "3"])
        assert result.exit_code == 0

    def test_engine_created_with_correct_agent_count(self):
        eng = _engine_mock(num_agents=5)
        with patch("agentx_cli.simulate_cmd.SimulationEngine", return_value=eng) as MockEng:
            with patch("agentx_cli.simulate_cmd.load_config", return_value=MOCK_CONFIG):
                runner.invoke(app, ["simulate", "--agents", "5"])
        MockEng.assert_called_once()
        kwargs = MockEng.call_args[1]
        assert kwargs["num_agents"] == 5

    def test_engine_created_with_base_url(self):
        eng = _engine_mock()
        with patch("agentx_cli.simulate_cmd.SimulationEngine", return_value=eng) as MockEng:
            runner.invoke(
                app,
                ["simulate", "--agents", "2", "--url", "http://custom:7777"],
            )
        kwargs = MockEng.call_args[1]
        assert kwargs["base_url"] == "http://custom:7777"

    def test_engine_created_with_poll_interval(self):
        eng = _engine_mock()
        with patch("agentx_cli.simulate_cmd.SimulationEngine", return_value=eng) as MockEng:
            runner.invoke(app, ["simulate", "--agents", "2", "--poll", "4.5"])
        kwargs = MockEng.call_args[1]
        assert kwargs["poll_interval"] == 4.5

    def test_engine_created_with_market_interval(self):
        eng = _engine_mock()
        with patch("agentx_cli.simulate_cmd.SimulationEngine", return_value=eng) as MockEng:
            runner.invoke(app, ["simulate", "--agents", "2", "--market-interval", "9.0"])
        kwargs = MockEng.call_args[1]
        assert kwargs["market_cycle_interval"] == 9.0

    def test_banner_shows_agent_count(self):
        eng = _engine_mock(num_agents=7)
        with patch("agentx_cli.simulate_cmd.SimulationEngine", return_value=eng):
            with patch("agentx_cli.simulate_cmd.load_config", return_value=MOCK_CONFIG):
                result = runner.invoke(app, ["simulate", "--agents", "7"])
        assert "7" in result.output

    def test_loads_config_when_no_url(self):
        eng = _engine_mock()
        with patch("agentx_cli.simulate_cmd.SimulationEngine", return_value=eng):
            with patch("agentx_cli.simulate_cmd.load_config", return_value=MOCK_CONFIG) as ml:
                runner.invoke(app, ["simulate", "--agents", "2"])
        ml.assert_called_once()

    def test_url_flag_skips_config_load(self):
        eng = _engine_mock()
        with patch("agentx_cli.simulate_cmd.SimulationEngine", return_value=eng):
            with patch("agentx_cli.simulate_cmd.load_config") as ml:
                runner.invoke(
                    app,
                    ["simulate", "--agents", "2", "--url", "http://x.io"],
                )
        ml.assert_not_called()

    def test_config_not_found_uses_localhost(self):
        eng = _engine_mock()
        with patch("agentx_cli.simulate_cmd.SimulationEngine", return_value=eng) as MockEng:
            with patch(
                "agentx_cli.simulate_cmd.load_config",
                side_effect=FileNotFoundError,
            ):
                runner.invoke(app, ["simulate", "--agents", "2"])
        kwargs = MockEng.call_args[1]
        assert "localhost" in kwargs["base_url"]


# ─────────────────────────────────────────────────────────────────────────────
# simulate command registration checks (no --help; Typer/Click rich mismatch
# in the container means --help exits non-zero for all commands)
# ─────────────────────────────────────────────────────────────────────────────

class TestSimulateRegistration:

    def test_simulate_command_registered(self):
        """simulate is registered as a top-level app command."""
        names = [c.name for c in app.registered_commands]
        assert "simulate" in names

    def test_simulate_function_has_docstring(self):
        from agentx_cli.simulate_cmd import simulate
        assert simulate.__doc__ is not None
        assert len(simulate.__doc__.strip()) > 0

    def test_simulate_accepts_agents_param(self):
        """--agents option: default 5 agents when not provided."""
        eng = _engine_mock(num_agents=5)
        with patch("agentx_cli.simulate_cmd.SimulationEngine", return_value=eng) as MockEng:
            with patch("agentx_cli.simulate_cmd.load_config", return_value=MOCK_CONFIG):
                runner.invoke(app, ["simulate"])
        kwargs = MockEng.call_args[1]
        assert kwargs["num_agents"] == 5

    def test_simulate_accepts_verbose_flag(self):
        """--verbose flag does not crash the command."""
        eng = _engine_mock()
        with patch("agentx_cli.simulate_cmd.SimulationEngine", return_value=eng):
            with patch("agentx_cli.simulate_cmd.load_config", return_value=MOCK_CONFIG):
                result = runner.invoke(app, ["simulate", "--agents", "1", "--verbose"])
        assert result.exit_code == 0

    def test_simulate_dry_run_with_n_flag(self):
        """-n is short alias for --agents."""
        result = runner.invoke(app, ["simulate", "-n", "3", "--dry-run"])
        assert result.exit_code == 0
        assert "sim_agent_3" in result.output
