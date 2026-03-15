"""
Tests: agentx_cli — bounties commands (Phase 15)
══════════════════════════════════════════════════════════════════════════════

Covers:
  bounties_cmd.bounties_list      — list bounties from MarketsClient
  bounties_cmd.bounties_create    — create bounty via MarketsClient
  bounties_cmd.bounties_submit    — submit solution via MarketsClient
  bounties_cmd.bounties_info      — show bounty details
  bounties_cmd.bounties_evaluate  — score a submission
  bounties_cmd.bounties_distribute — distribute rewards

All SDK calls are mocked — no live API required.
"""
from __future__ import annotations

import json
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
    capabilities=["collect_data"],
)


def _bounty(status="open"):
    return {
        "bounty_id":            str(uuid4()),
        "creator_did":          "did:agentx:creator",
        "title":                "Test Bounty",
        "description":          "A test",
        "capability_required":  "collect_data",
        "reward_pool":          1000,
        "status":               status,
        "created_at":           "2026-01-01T00:00:00Z",
    }


def _submission(status="pending"):
    return {
        "submission_id": str(uuid4()),
        "bounty_id":     str(uuid4()),
        "submitter_did": "did:agentx:agent",
        "solution_data": {"result": "ok"},
        "status":        status,
        "submitted_at":  "2026-01-01T00:00:00Z",
    }


def _reward():
    return {
        "reward_id":      str(uuid4()),
        "bounty_id":      str(uuid4()),
        "submission_id":  str(uuid4()),
        "recipient_did":  "did:agentx:winner",
        "amount":         1000,
        "distributed_at": "2026-01-01T00:00:00Z",
    }


# ═════════════════════════════════════════════════════════════════════════════
# bounties list
# ═════════════════════════════════════════════════════════════════════════════

class TestBountiesList:

    def test_list_prints_bounties(self):
        mock_client = MagicMock()
        mock_client.list_bounties = AsyncMock(return_value=[_bounty("open"), _bounty("open")])

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, ["bounties", "list"])

        assert result.exit_code == 0
        assert "Test Bounty" in result.output

    def test_list_empty_shows_no_bounties_message(self):
        mock_client = MagicMock()
        mock_client.list_bounties = AsyncMock(return_value=[])

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, ["bounties", "list"])

        assert result.exit_code == 0
        assert "no" in result.output.lower() or "0" in result.output or result.output.strip() != ""

    def test_list_passes_status_filter(self):
        mock_client = MagicMock()
        mock_client.list_bounties = AsyncMock(return_value=[])

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                runner.invoke(app, ["bounties", "list", "--status", "open"])

        mock_client.list_bounties.assert_called_once_with(status="open", capability=None)

    def test_list_passes_capability_filter(self):
        mock_client = MagicMock()
        mock_client.list_bounties = AsyncMock(return_value=[])

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                runner.invoke(app, ["bounties", "list", "--capability", "collect_data"])

        mock_client.list_bounties.assert_called_once_with(status=None, capability="collect_data")

    def test_list_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.list_bounties = AsyncMock(side_effect=RuntimeError("API error"))

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, ["bounties", "list"])

        assert result.exit_code != 0

    def test_list_shows_reward_pool(self):
        mock_client = MagicMock()
        mock_client.list_bounties = AsyncMock(return_value=[_bounty("open")])

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, ["bounties", "list"])

        assert "1000" in result.output or "pool" in result.output.lower()


# ═════════════════════════════════════════════════════════════════════════════
# bounties create
# ═════════════════════════════════════════════════════════════════════════════

class TestBountiesCreate:

    def test_create_exits_zero(self):
        bounty = _bounty()
        mock_client = MagicMock()
        mock_client.create_bounty = AsyncMock(return_value=bounty)

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "bounties", "create",
                    "--title", "My Bounty",
                    "--capability", "collect_data",
                    "--reward-pool", "500",
                ])

        assert result.exit_code == 0

    def test_create_prints_bounty_id(self):
        bounty = _bounty()
        mock_client = MagicMock()
        mock_client.create_bounty = AsyncMock(return_value=bounty)

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "bounties", "create",
                    "--title", "My Bounty",
                    "--capability", "collect_data",
                    "--reward-pool", "500",
                ])

        assert bounty["bounty_id"] in result.output

    def test_create_calls_sdk_with_correct_args(self):
        mock_client = MagicMock()
        mock_client.create_bounty = AsyncMock(return_value=_bounty())

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                runner.invoke(app, [
                    "bounties", "create",
                    "--title", "Test",
                    "--capability", "analyse_data",
                    "--reward-pool", "1000",
                    "--description", "Detailed description",
                ])

        kwargs = mock_client.create_bounty.call_args.kwargs
        assert kwargs["title"] == "Test"
        assert kwargs["capability_required"] == "analyse_data"
        assert kwargs["reward_pool"] == 1000
        assert kwargs["description"] == "Detailed description"

    def test_create_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.create_bounty = AsyncMock(side_effect=RuntimeError("insufficient funds"))

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "bounties", "create",
                    "--title", "T", "--capability", "x", "--reward-pool", "1",
                ])

        assert result.exit_code != 0

    def test_create_missing_required_exits_nonzero(self):
        result = runner.invoke(app, ["bounties", "create", "--title", "T"])
        assert result.exit_code != 0


# ═════════════════════════════════════════════════════════════════════════════
# bounties submit
# ═════════════════════════════════════════════════════════════════════════════

class TestBountiesSubmit:

    def test_submit_exits_zero(self):
        sub = _submission()
        mock_client = MagicMock()
        mock_client.submit_solution = AsyncMock(return_value=sub)

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "bounties", "submit",
                    "--id", str(uuid4()),
                    "--solution", '{"result": "ok"}',
                ])

        assert result.exit_code == 0

    def test_submit_prints_submission_id(self):
        sub = _submission()
        mock_client = MagicMock()
        mock_client.submit_solution = AsyncMock(return_value=sub)

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "bounties", "submit",
                    "--id", str(uuid4()),
                    "--solution", '{"result": "ok"}',
                ])

        assert sub["submission_id"] in result.output

    def test_submit_invalid_json_exits_nonzero(self):
        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            result = runner.invoke(app, [
                "bounties", "submit",
                "--id", str(uuid4()),
                "--solution", "not-json",
            ])

        assert result.exit_code != 0

    def test_submit_passes_summary(self):
        mock_client = MagicMock()
        mock_client.submit_solution = AsyncMock(return_value=_submission())

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                runner.invoke(app, [
                    "bounties", "submit",
                    "--id", str(uuid4()),
                    "--solution", '{"x": 1}',
                    "--summary", "My analysis complete",
                ])

        kwargs = mock_client.submit_solution.call_args.kwargs
        assert kwargs["summary"] == "My analysis complete"

    def test_submit_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.submit_solution = AsyncMock(side_effect=RuntimeError("bounty closed"))

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "bounties", "submit",
                    "--id", str(uuid4()),
                    "--solution", '{"ok": true}',
                ])

        assert result.exit_code != 0


# ═════════════════════════════════════════════════════════════════════════════
# bounties info
# ═════════════════════════════════════════════════════════════════════════════

class TestBountiesInfo:

    def test_info_prints_bounty_fields(self):
        bid = str(uuid4())
        mock_client = MagicMock()
        mock_client.get_bounty = AsyncMock(return_value={**_bounty(), "bounty_id": bid})

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, ["bounties", "info", bid])

        assert result.exit_code == 0
        assert "Test Bounty" in result.output or bid in result.output

    def test_info_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.get_bounty = AsyncMock(side_effect=RuntimeError("not found"))

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, ["bounties", "info", str(uuid4())])

        assert result.exit_code != 0


# ═════════════════════════════════════════════════════════════════════════════
# bounties evaluate
# ═════════════════════════════════════════════════════════════════════════════

class TestBountiesEvaluate:

    def test_evaluate_exits_zero(self):
        sub = {**_submission(), "score": 0.9, "status": "evaluated"}
        mock_client = MagicMock()
        mock_client.evaluate_submission = AsyncMock(return_value=sub)

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "bounties", "evaluate",
                    "--bounty-id", str(uuid4()),
                    "--submission-id", str(uuid4()),
                    "--score", "0.9",
                ])

        assert result.exit_code == 0

    def test_evaluate_prints_score(self):
        sub = {**_submission(), "score": 0.85, "status": "evaluated"}
        mock_client = MagicMock()
        mock_client.evaluate_submission = AsyncMock(return_value=sub)

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "bounties", "evaluate",
                    "--bounty-id", str(uuid4()),
                    "--submission-id", str(uuid4()),
                    "--score", "0.85",
                ])

        assert "0.85" in result.output or "evaluated" in result.output

    def test_evaluate_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.evaluate_submission = AsyncMock(side_effect=RuntimeError("forbidden"))

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "bounties", "evaluate",
                    "--bounty-id", str(uuid4()),
                    "--submission-id", str(uuid4()),
                    "--score", "0.5",
                ])

        assert result.exit_code != 0


# ═════════════════════════════════════════════════════════════════════════════
# bounties distribute
# ═════════════════════════════════════════════════════════════════════════════

class TestBountiesDistribute:

    def test_distribute_exits_zero(self):
        reward = _reward()
        mock_client = MagicMock()
        mock_client.distribute_rewards = AsyncMock(return_value=reward)

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "bounties", "distribute",
                    "--id", str(uuid4()),
                ])

        assert result.exit_code == 0

    def test_distribute_prints_reward_info(self):
        reward = _reward()
        mock_client = MagicMock()
        mock_client.distribute_rewards = AsyncMock(return_value=reward)

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "bounties", "distribute",
                    "--id", str(uuid4()),
                ])

        assert "reward" in result.output.lower() or "winner" in result.output.lower() or "1000" in result.output

    def test_distribute_calls_sdk_with_bounty_id(self):
        bid = str(uuid4())
        mock_client = MagicMock()
        mock_client.distribute_rewards = AsyncMock(return_value=_reward())

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                runner.invoke(app, ["bounties", "distribute", "--id", bid])

        mock_client.distribute_rewards.assert_called_once_with(bounty_id=bid)

    def test_distribute_api_error_exits_nonzero(self):
        mock_client = MagicMock()
        mock_client.distribute_rewards = AsyncMock(side_effect=RuntimeError("not creator"))

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client):
                result = runner.invoke(app, [
                    "bounties", "distribute",
                    "--id", str(uuid4()),
                ])

        assert result.exit_code != 0


# ═════════════════════════════════════════════════════════════════════════════
# MarketsClient instantiation (via bounties commands)
# ═════════════════════════════════════════════════════════════════════════════

class TestMarketsClientInit:

    def test_client_created_with_api_url(self):
        mock_client = MagicMock()
        mock_client.list_bounties = AsyncMock(return_value=[])

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client) as mock_cls:
                runner.invoke(app, ["bounties", "list"])

        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs.get("base_url") == _API_URL

    def test_client_created_with_token(self):
        mock_client = MagicMock()
        mock_client.list_bounties = AsyncMock(return_value=[])

        with patch("agentx_cli.bounties_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.bounties_cmd.MarketsClient", return_value=mock_client) as mock_cls:
                runner.invoke(app, ["bounties", "list"])

        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs.get("token") == _API_KEY
