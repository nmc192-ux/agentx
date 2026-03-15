"""
Tests: agentx_cli — contracts commands (Phase 14)
══════════════════════════════════════════════════

Covers:
  contracts_cmd.contracts_list     — list contracts from ContractsClient
  contracts_cmd.contracts_create   — create contract via ContractsClient
  contracts_cmd.contracts_submit   — submit result via ContractsClient
  contracts_cmd.contracts_complete — mark contract completed via ContractsClient
  contracts_cmd.contracts_info     — fetch single contract via ContractsClient

All SDK calls are mocked — no live API required.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from typer.testing import CliRunner

from agentx_cli.config import AgentConfig
from agentx_cli.main import app

runner = CliRunner()

# ── Shared fixtures ───────────────────────────────────────────────────────────

_API_URL = "http://localhost:8000"
_API_KEY = "test-jwt"

MOCK_CONFIG = AgentConfig(
    name="test_agent",
    api_url=_API_URL,
    api_key=_API_KEY,
    agent_id=str(uuid4()),
    capabilities=["test"],
)


def _contract(status="open"):
    return {
        "contract_id":         str(uuid4()),
        "title":               "Test Contract",
        "status":              status,
        "budget":              1000,
        "capability_required": "collect_data",
    }


# ═════════════════════════════════════════════════════════════════════════════
# contracts list
# ═════════════════════════════════════════════════════════════════════════════

class TestContractsList:

    def test_list_prints_contracts(self):
        contracts = [_contract("open"), _contract("assigned")]
        mock_client = MagicMock()
        mock_client.list = AsyncMock(return_value=contracts)

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, ["contracts", "list"])

        assert result.exit_code == 0
        assert "Test Contract" in result.output

    def test_list_empty_shows_none_found_message(self):
        mock_client = MagicMock()
        mock_client.list = AsyncMock(return_value=[])

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, ["contracts", "list"])

        assert result.exit_code == 0
        assert "no" in result.output.lower() or "0" in result.output

    def test_list_passes_status_filter(self):
        mock_client = MagicMock()
        mock_client.list = AsyncMock(return_value=[])

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                runner.invoke(app, ["contracts", "list", "--status", "open"])

        mock_client.list.assert_called_once_with(status="open")

    def test_list_no_status_filter_passes_none(self):
        mock_client = MagicMock()
        mock_client.list = AsyncMock(return_value=[])

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                runner.invoke(app, ["contracts", "list"])

        mock_client.list.assert_called_once_with(status=None)

    def test_list_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.list = AsyncMock(side_effect=RuntimeError("API error"))

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, ["contracts", "list"])

        assert result.exit_code != 0

    def test_list_shows_contract_status_in_output(self):
        contracts = [_contract("assigned")]
        mock_client = MagicMock()
        mock_client.list = AsyncMock(return_value=contracts)

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, ["contracts", "list"])

        assert "assigned" in result.output


# ═════════════════════════════════════════════════════════════════════════════
# contracts create
# ═════════════════════════════════════════════════════════════════════════════

class TestContractsCreate:

    def test_create_calls_sdk_with_correct_args(self):
        contract_id = str(uuid4())
        mock_client = MagicMock()
        mock_client.create = AsyncMock(return_value={"contract_id": contract_id, "status": "open"})

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "contracts", "create",
                    "--title", "My Contract",
                    "--capability", "collect_data",
                    "--budget", "500",
                ])

        assert result.exit_code == 0
        mock_client.create.assert_called_once_with(
            title="My Contract",
            capability_required="collect_data",
            budget=500,
            description=None,
        )

    def test_create_prints_contract_id(self):
        contract_id = str(uuid4())
        mock_client = MagicMock()
        mock_client.create = AsyncMock(return_value={"contract_id": contract_id, "status": "open"})

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "contracts", "create",
                    "--title", "My Contract",
                    "--capability", "collect_data",
                    "--budget", "500",
                ])

        assert contract_id in result.output

    def test_create_with_description(self):
        mock_client = MagicMock()
        mock_client.create = AsyncMock(return_value={"contract_id": str(uuid4()), "status": "open"})

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                runner.invoke(app, [
                    "contracts", "create",
                    "--title", "Test",
                    "--capability", "x",
                    "--budget", "100",
                    "--description", "Detailed work description",
                ])

        call_kwargs = mock_client.create.call_args.kwargs
        assert call_kwargs["description"] == "Detailed work description"

    def test_create_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.create = AsyncMock(side_effect=RuntimeError("API error"))

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "contracts", "create",
                    "--title", "T", "--capability", "x", "--budget", "1",
                ])

        assert result.exit_code != 0

    def test_create_missing_required_options_exits_nonzero(self):
        result = runner.invoke(app, ["contracts", "create", "--title", "T"])
        # Missing --capability and --budget
        assert result.exit_code != 0


# ═════════════════════════════════════════════════════════════════════════════
# contracts submit
# ═════════════════════════════════════════════════════════════════════════════

class TestContractsSubmit:

    def test_submit_calls_sdk_with_parsed_json(self):
        contract_id = str(uuid4())
        result_id   = str(uuid4())
        result_data = {"rows": 42, "status": "ok"}

        mock_client = MagicMock()
        mock_client.submit_result = AsyncMock(return_value={"result_id": result_id})

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "contracts", "submit",
                    "--id", contract_id,
                    "--result", json.dumps(result_data),
                ])

        assert result.exit_code == 0
        mock_client.submit_result.assert_called_once_with(
            contract_id=contract_id,
            result_data=result_data,
            summary=None,
        )

    def test_submit_prints_result_id(self):
        contract_id = str(uuid4())
        result_id   = str(uuid4())
        mock_client = MagicMock()
        mock_client.submit_result = AsyncMock(return_value={"result_id": result_id})

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "contracts", "submit",
                    "--id", contract_id,
                    "--result", '{"ok": true}',
                ])

        assert result_id in result.output

    def test_submit_invalid_json_exits_nonzero(self):
        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            result = runner.invoke(app, [
                "contracts", "submit",
                "--id", str(uuid4()),
                "--result", "not-json",
            ])

        assert result.exit_code != 0

    def test_submit_with_summary(self):
        mock_client = MagicMock()
        mock_client.submit_result = AsyncMock(return_value={"result_id": str(uuid4())})

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                runner.invoke(app, [
                    "contracts", "submit",
                    "--id", str(uuid4()),
                    "--result", '{"x": 1}',
                    "--summary", "Completed successfully",
                ])

        call_kwargs = mock_client.submit_result.call_args.kwargs
        assert call_kwargs["summary"] == "Completed successfully"

    def test_submit_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.submit_result = AsyncMock(side_effect=RuntimeError("Not authorized"))

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "contracts", "submit",
                    "--id", str(uuid4()),
                    "--result", '{"ok": true}',
                ])

        assert result.exit_code != 0


# ═════════════════════════════════════════════════════════════════════════════
# contracts complete
# ═════════════════════════════════════════════════════════════════════════════

class TestContractsComplete:

    def test_complete_calls_sdk_with_contract_id(self):
        contract_id = str(uuid4())
        mock_client = MagicMock()
        mock_client.complete = AsyncMock(return_value={"contract_id": contract_id, "status": "completed"})

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, ["contracts", "complete", "--id", contract_id])

        assert result.exit_code == 0
        mock_client.complete.assert_called_once_with(contract_id=contract_id)

    def test_complete_prints_confirmation(self):
        contract_id = str(uuid4())
        mock_client = MagicMock()
        mock_client.complete = AsyncMock(
            return_value={"contract_id": contract_id, "status": "completed"}
        )

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, ["contracts", "complete", "--id", contract_id])

        assert "complete" in result.output.lower()
        assert contract_id in result.output

    def test_complete_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.complete = AsyncMock(side_effect=RuntimeError("not authorized"))

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, ["contracts", "complete", "--id", str(uuid4())])

        assert result.exit_code != 0


# ═════════════════════════════════════════════════════════════════════════════
# contracts info
# ═════════════════════════════════════════════════════════════════════════════

class TestContractsInfo:

    def test_info_prints_contract_fields(self):
        contract_id = str(uuid4())
        contract    = _contract("submitted")
        contract["contract_id"] = contract_id

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=contract)

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, ["contracts", "info", contract_id])

        assert result.exit_code == 0
        assert "submitted" in result.output or "Test Contract" in result.output

    def test_info_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("not found"))

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client):
                result = runner.invoke(app, ["contracts", "info", str(uuid4())])

        assert result.exit_code != 0


# ═════════════════════════════════════════════════════════════════════════════
# ContractsClient instantiation
# ═════════════════════════════════════════════════════════════════════════════

class TestContractsClientInit:

    def test_client_created_with_api_url_from_config(self):
        mock_client = MagicMock()
        mock_client.list = AsyncMock(return_value=[])

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client) as mock_cls:
                runner.invoke(app, ["contracts", "list"])

        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs.get("base_url") == _API_URL

    def test_client_created_with_api_key_from_config(self):
        mock_client = MagicMock()
        mock_client.list = AsyncMock(return_value=[])

        with patch("agentx_cli.contracts_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.contracts_cmd.ContractsClient", return_value=mock_client) as mock_cls:
                runner.invoke(app, ["contracts", "list"])

        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs.get("token") == _API_KEY
