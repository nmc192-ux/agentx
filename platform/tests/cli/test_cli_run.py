"""
Tests: agentx_cli — run command (Phase 14)
══════════════════════════════════════════

Covers:
  run_cmd.run_agent       — config loading, module import, runtime startup
  run_cmd._load_agent_module — dynamic import helper
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from agentx_cli.main import app

runner = CliRunner()

# ── Fixtures / helpers ────────────────────────────────────────────────────────

VALID_AGENT_YAML = dedent("""\
    name: test_agent
    api_url: http://localhost:8000
    api_key: test-jwt
    did: did:agentx:test-agent
    agent_id: null
    capabilities:
      - test
""")

VALID_AGENT_PY = dedent("""\
    from agentx_sdk import Agent

    agent = Agent(name="test_agent", capabilities=["test"])

    @agent.contract("test")
    async def handle_test(data: dict) -> dict:
        return {"result": "ok"}
""")


def _write_project(base_dir: Path | None = None) -> None:
    """Write agent.yaml and agent.py in the current directory."""
    if base_dir:
        (base_dir / "agent.yaml").write_text(VALID_AGENT_YAML)
        (base_dir / "agent.py").write_text(VALID_AGENT_PY)
    else:
        Path("agent.yaml").write_text(VALID_AGENT_YAML)
        Path("agent.py").write_text(VALID_AGENT_PY)


# ═════════════════════════════════════════════════════════════════════════════
# Config loading
# ═════════════════════════════════════════════════════════════════════════════

class TestRunLoadsConfig:

    def test_missing_agent_yaml_exits_with_error(self):
        with runner.isolated_filesystem():
            # No agent.yaml present
            result = runner.invoke(app, ["run"])
            assert result.exit_code != 0

    def test_missing_agent_yaml_prints_error(self):
        with runner.isolated_filesystem():
            result = runner.invoke(app, ["run"])
            # With default mix_stderr=True, stderr is merged into result.output
            assert "error" in result.output.lower() or "not found" in result.output.lower()

    def test_missing_agent_py_exits_with_error(self):
        with runner.isolated_filesystem():
            Path("agent.yaml").write_text(VALID_AGENT_YAML)
            # No agent.py
            result = runner.invoke(app, ["run"])
            assert result.exit_code != 0

    def test_run_prints_agent_name_from_config(self):
        with runner.isolated_filesystem():
            _write_project()
            mock_runtime = MagicMock()
            mock_runtime.start = AsyncMock()
            with patch("agentx_cli.run_cmd.AgentRuntime", return_value=mock_runtime):
                result = runner.invoke(app, ["run"])
            assert "test_agent" in result.output

    def test_run_prints_api_url_from_config(self):
        with runner.isolated_filesystem():
            _write_project()
            mock_runtime = MagicMock()
            mock_runtime.start = AsyncMock()
            with patch("agentx_cli.run_cmd.AgentRuntime", return_value=mock_runtime):
                result = runner.invoke(app, ["run"])
            assert "localhost:8000" in result.output


# ═════════════════════════════════════════════════════════════════════════════
# Runtime startup
# ═════════════════════════════════════════════════════════════════════════════

class TestRunStartsRuntime:

    def test_runtime_start_is_called(self):
        with runner.isolated_filesystem():
            _write_project()
            mock_runtime = MagicMock()
            mock_runtime.start = AsyncMock()
            with patch("agentx_cli.run_cmd.AgentRuntime", return_value=mock_runtime):
                result = runner.invoke(app, ["run"])
            mock_runtime.start.assert_called_once()

    def test_agentx_client_created_with_correct_url(self):
        with runner.isolated_filesystem():
            _write_project()
            mock_runtime = MagicMock()
            mock_runtime.start = AsyncMock()
            with patch("agentx_cli.run_cmd.AgentRuntime", return_value=mock_runtime):
                with patch("agentx_cli.run_cmd.AgentXClient") as mock_client_cls:
                    mock_client_cls.return_value = MagicMock()
                    runner.invoke(app, ["run"])
            call_kwargs = mock_client_cls.call_args.kwargs
            assert call_kwargs.get("base_url") == "http://localhost:8000"

    def test_agentx_client_gets_api_key_from_config(self):
        with runner.isolated_filesystem():
            _write_project()
            mock_runtime = MagicMock()
            mock_runtime.start = AsyncMock()
            with patch("agentx_cli.run_cmd.AgentRuntime", return_value=mock_runtime):
                with patch("agentx_cli.run_cmd.AgentXClient") as mock_client_cls:
                    mock_client_cls.return_value = MagicMock()
                    runner.invoke(app, ["run"])
            call_kwargs = mock_client_cls.call_args.kwargs
            assert call_kwargs.get("api_key") == "test-jwt"

    def test_runtime_created_with_correct_poll_interval(self):
        with runner.isolated_filesystem():
            _write_project()
            mock_runtime = MagicMock()
            mock_runtime.start = AsyncMock()
            with patch("agentx_cli.run_cmd.AgentRuntime", return_value=mock_runtime) as mock_rt_cls:
                runner.invoke(app, ["run", "--poll-interval", "15"])
            call_kwargs = mock_rt_cls.call_args.kwargs
            assert call_kwargs.get("poll_interval") == 15.0

    def test_no_register_flag_disables_auto_register(self):
        with runner.isolated_filesystem():
            _write_project()
            mock_runtime = MagicMock()
            mock_runtime.start = AsyncMock()
            with patch("agentx_cli.run_cmd.AgentRuntime", return_value=mock_runtime) as mock_rt_cls:
                runner.invoke(app, ["run", "--no-register"])
            call_kwargs = mock_rt_cls.call_args.kwargs
            assert call_kwargs.get("auto_register") is False

    def test_keyboard_interrupt_exits_gracefully(self):
        with runner.isolated_filesystem():
            _write_project()
            mock_runtime = MagicMock()
            # Simulate Ctrl-C
            mock_runtime.start = AsyncMock(side_effect=KeyboardInterrupt())
            with patch("agentx_cli.run_cmd.AgentRuntime", return_value=mock_runtime):
                result = runner.invoke(app, ["run"])
            # Should exit 0 (graceful stop)
            assert result.exit_code == 0
            assert "stopped" in result.output.lower()


# ═════════════════════════════════════════════════════════════════════════════
# _load_agent_module helper
# ═════════════════════════════════════════════════════════════════════════════

class TestLoadAgentModule:

    def test_loads_agent_from_valid_file(self, tmp_path):
        agent_py = tmp_path / "agent.py"
        agent_py.write_text(VALID_AGENT_PY)

        from agentx_cli.run_cmd import _load_agent_module
        agent = _load_agent_module(agent_py)

        from agentx_sdk.agent import Agent
        assert isinstance(agent, Agent)

    def test_raises_attribute_error_when_no_agent_var(self, tmp_path):
        agent_py = tmp_path / "agent.py"
        agent_py.write_text("# no agent variable here\nx = 42")

        from agentx_cli.run_cmd import _load_agent_module
        with pytest.raises(AttributeError):
            _load_agent_module(agent_py)

    def test_agent_has_correct_name(self, tmp_path):
        agent_py = tmp_path / "agent.py"
        agent_py.write_text(VALID_AGENT_PY)

        from agentx_cli.run_cmd import _load_agent_module
        agent = _load_agent_module(agent_py)
        assert agent.name == "test_agent"

    def test_agent_has_registered_handlers(self, tmp_path):
        agent_py = tmp_path / "agent.py"
        agent_py.write_text(VALID_AGENT_PY)

        from agentx_cli.run_cmd import _load_agent_module
        agent = _load_agent_module(agent_py)
        assert agent.has_handler("test")
