"""
Tests: agentx_cli — init command (Phase 14)
═══════════════════════════════════════════

Covers:
  init_cmd.init_agent   — directory creation, file generation, slugification
  config._slugify        — name → URL-safe slug
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agentx_cli.main import app

runner = CliRunner()


# ═════════════════════════════════════════════════════════════════════════════
# Directory / file creation
# ═════════════════════════════════════════════════════════════════════════════

class TestInitCreatesProjectStructure:

    def test_creates_agent_directory(self):
        with runner.isolated_filesystem():
            result = runner.invoke(app, ["init", "my_agent"])
            assert result.exit_code == 0, result.output
            assert Path("my_agent").is_dir()

    def test_creates_agent_py(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "my_agent"])
            assert Path("my_agent/agent.py").exists()

    def test_creates_agent_yaml(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "my_agent"])
            assert Path("my_agent/agent.yaml").exists()

    def test_creates_requirements_txt(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "my_agent"])
            assert Path("my_agent/requirements.txt").exists()

    def test_success_output_mentions_agent_name(self):
        with runner.isolated_filesystem():
            result = runner.invoke(app, ["init", "cool_agent"])
            assert "cool_agent" in result.output

    def test_success_output_mentions_next_steps(self):
        with runner.isolated_filesystem():
            result = runner.invoke(app, ["init", "my_agent"])
            assert "agentx run" in result.output


class TestInitAgentYamlContent:

    def test_yaml_contains_correct_name(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "data_agent"])
            cfg = yaml.safe_load(Path("data_agent/agent.yaml").read_text())
            assert cfg["name"] == "data_agent"

    def test_yaml_contains_default_api_url(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "data_agent"])
            cfg = yaml.safe_load(Path("data_agent/agent.yaml").read_text())
            assert "api_url" in cfg
            assert "localhost" in cfg["api_url"]

    def test_yaml_api_url_custom(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "data_agent", "--api-url", "https://prod.agentx.io"])
            cfg = yaml.safe_load(Path("data_agent/agent.yaml").read_text())
            assert cfg["api_url"] == "https://prod.agentx.io"

    def test_yaml_contains_capabilities_list(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "data_agent"])
            cfg = yaml.safe_load(Path("data_agent/agent.yaml").read_text())
            assert isinstance(cfg["capabilities"], list)
            assert len(cfg["capabilities"]) >= 1

    def test_yaml_did_contains_slug(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "My Cool Agent"])
            cfg = yaml.safe_load(Path("My Cool Agent/agent.yaml").read_text())
            assert "did:agentx:" in cfg["did"]


class TestInitAgentPyContent:

    def test_agent_py_imports_sdk(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "my_agent"])
            content = Path("my_agent/agent.py").read_text()
            assert "from agentx_sdk import Agent" in content

    def test_agent_py_contains_agent_name(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "my_agent"])
            content = Path("my_agent/agent.py").read_text()
            assert "my_agent" in content

    def test_agent_py_contains_contract_decorator(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "my_agent"])
            content = Path("my_agent/agent.py").read_text()
            assert "@agent.contract" in content

    def test_agent_py_handler_is_async(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "my_agent"])
            content = Path("my_agent/agent.py").read_text()
            assert "async def" in content


class TestInitRequirementsTxt:

    def test_requirements_mentions_agentx(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "my_agent"])
            content = Path("my_agent/requirements.txt").read_text()
            assert "agentx" in content.lower()


class TestInitEdgeCases:

    def test_init_fails_if_directory_already_exists(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "my_agent"])
            result = runner.invoke(app, ["init", "my_agent"])
            assert result.exit_code != 0
            assert "already exists" in result.output.lower() or \
                   "already exists" in (result.stderr or "").lower()

    def test_init_force_overwrites_existing(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init", "my_agent"])
            # Modify a file so we can verify overwrite
            Path("my_agent/requirements.txt").write_text("# modified")
            result = runner.invoke(app, ["init", "my_agent", "--force"])
            assert result.exit_code == 0
            # Should be regenerated
            content = Path("my_agent/requirements.txt").read_text()
            assert "# modified" not in content

    def test_init_agent_name_with_spaces(self):
        with runner.isolated_filesystem():
            result = runner.invoke(app, ["init", "Research Agent"])
            assert result.exit_code == 0
            assert Path("Research Agent").is_dir()

    def test_init_agent_name_with_underscores(self):
        with runner.isolated_filesystem():
            result = runner.invoke(app, ["init", "data_collector"])
            assert result.exit_code == 0
            assert Path("data_collector").is_dir()


# ═════════════════════════════════════════════════════════════════════════════
# _slugify helper
# ═════════════════════════════════════════════════════════════════════════════

class TestSlugify:

    def test_lower_case_passthrough(self):
        from agentx_cli.init_cmd import _slugify
        assert _slugify("myagent") == "myagent"

    def test_spaces_become_hyphens(self):
        from agentx_cli.init_cmd import _slugify
        assert _slugify("my agent") == "my-agent"

    def test_underscores_become_hyphens(self):
        from agentx_cli.init_cmd import _slugify
        assert _slugify("my_agent") == "my-agent"

    def test_uppercase_lowered(self):
        from agentx_cli.init_cmd import _slugify
        assert _slugify("MyAgent") == "myagent"

    def test_multiple_spaces_collapsed(self):
        from agentx_cli.init_cmd import _slugify
        assert _slugify("my  agent") == "my-agent"

    def test_special_chars_stripped(self):
        from agentx_cli.init_cmd import _slugify
        result = _slugify("my@agent!")
        assert "@" not in result
        assert "!" not in result

    def test_empty_string_returns_agent(self):
        from agentx_cli.init_cmd import _slugify
        assert _slugify("") == "agent"
