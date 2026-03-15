"""
Tests: agentx_cli — wallet commands (Phase 14)
═══════════════════════════════════════════════

Covers:
  wallet_cmd.wallet_balance   — prints balance from WalletClient
  wallet_cmd.wallet_transfer  — calls WalletClient.transfer
  wallet_cmd.wallet_stake     — calls WalletClient.stake
  wallet_cmd.wallet_history   — prints transaction list from WalletClient

All SDK calls are mocked — no live API required.
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from typer.testing import CliRunner

from agentx_cli.main import app
from agentx_cli.config import AgentConfig

runner = CliRunner()

# ── Shared fixtures ───────────────────────────────────────────────────────────

_AGENT_ID  = str(uuid4())
_API_URL   = "http://localhost:8000"
_API_KEY   = "test-jwt"

MOCK_CONFIG = AgentConfig(
    name="test_agent",
    api_url=_API_URL,
    api_key=_API_KEY,
    agent_id=_AGENT_ID,
    capabilities=["test"],
)


def _invoke_wallet(*args, config=MOCK_CONFIG) -> object:
    """Helper to invoke wallet commands with a mocked config."""
    with patch("agentx_cli.wallet_cmd.load_config", return_value=config):
        return runner.invoke(app, ["wallet", *args])


# ═════════════════════════════════════════════════════════════════════════════
# wallet balance
# ═════════════════════════════════════════════════════════════════════════════

class TestWalletBalance:

    def test_balance_prints_token_amount(self):
        mock_wallet = MagicMock()
        mock_wallet.get_balance = AsyncMock(return_value=9_999)

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                result = runner.invoke(app, ["wallet", "balance"])

        assert result.exit_code == 0
        assert "9" in result.output   # balance amount present
        assert "token" in result.output.lower()

    def test_balance_calls_get_balance_with_agent_id(self):
        mock_wallet = MagicMock()
        mock_wallet.get_balance = AsyncMock(return_value=500)

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                runner.invoke(app, ["wallet", "balance"])

        mock_wallet.get_balance.assert_called_once_with(_AGENT_ID)

    def test_balance_accepts_agent_id_override(self):
        other_id = str(uuid4())
        mock_wallet = MagicMock()
        mock_wallet.get_balance = AsyncMock(return_value=100)

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                runner.invoke(app, ["wallet", "balance", "--agent-id", other_id])

        mock_wallet.get_balance.assert_called_once_with(other_id)

    def test_balance_fails_when_no_agent_id_in_config(self):
        config_no_id = AgentConfig(
            name="no_id_agent", api_url=_API_URL, agent_id=None
        )
        result = _invoke_wallet("balance", config=config_no_id)
        assert result.exit_code != 0

    def test_balance_api_error_exits_nonzero(self):
        mock_wallet = MagicMock()
        mock_wallet.get_balance = AsyncMock(side_effect=ConnectionError("API down"))

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                result = runner.invoke(app, ["wallet", "balance"])

        assert result.exit_code != 0

    def test_wallet_client_created_with_correct_url(self):
        mock_wallet = MagicMock()
        mock_wallet.get_balance = AsyncMock(return_value=0)

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet) as mock_cls:
                runner.invoke(app, ["wallet", "balance"])

        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs.get("base_url") == _API_URL


# ═════════════════════════════════════════════════════════════════════════════
# wallet transfer
# ═════════════════════════════════════════════════════════════════════════════

class TestWalletTransfer:

    def test_transfer_calls_sdk_with_correct_args(self):
        to_id  = str(uuid4())
        amount = 500

        mock_wallet = MagicMock()
        mock_wallet.transfer = AsyncMock(return_value={"transaction_id": str(uuid4())})

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                result = runner.invoke(app, ["wallet", "transfer", to_id, str(amount)])

        assert result.exit_code == 0
        mock_wallet.transfer.assert_called_once_with(
            from_agent_id=_AGENT_ID,
            to_agent_id=to_id,
            amount=amount,
        )

    def test_transfer_prints_confirmation(self):
        to_id  = str(uuid4())
        tx_id  = str(uuid4())

        mock_wallet = MagicMock()
        mock_wallet.transfer = AsyncMock(return_value={"transaction_id": tx_id})

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                result = runner.invoke(app, ["wallet", "transfer", to_id, "100"])

        assert "complete" in result.output.lower() or "transfer" in result.output.lower()

    def test_transfer_api_error_exits_nonzero(self):
        mock_wallet = MagicMock()
        mock_wallet.transfer = AsyncMock(side_effect=RuntimeError("insufficient funds"))

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                result = runner.invoke(app, ["wallet", "transfer", str(uuid4()), "999"])

        assert result.exit_code != 0


# ═════════════════════════════════════════════════════════════════════════════
# wallet stake
# ═════════════════════════════════════════════════════════════════════════════

class TestWalletStake:

    def test_stake_calls_sdk_with_amount_and_agent_id(self):
        stake_id = str(uuid4())

        mock_wallet = MagicMock()
        mock_wallet.stake = AsyncMock(return_value={"stake_id": stake_id})

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                result = runner.invoke(app, ["wallet", "stake", "200"])

        assert result.exit_code == 0
        mock_wallet.stake.assert_called_once_with(
            agent_id=_AGENT_ID,
            amount=200,
            locked_until=None,
        )

    def test_stake_with_locked_until(self):
        mock_wallet = MagicMock()
        mock_wallet.stake = AsyncMock(return_value={"stake_id": str(uuid4())})

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                result = runner.invoke(
                    app,
                    ["wallet", "stake", "100", "--locked-until", "2027-01-01T00:00:00Z"],
                )

        assert result.exit_code == 0
        call_kwargs = mock_wallet.stake.call_args.kwargs
        assert call_kwargs["locked_until"] == "2027-01-01T00:00:00Z"

    def test_stake_prints_stake_id(self):
        stake_id = str(uuid4())
        mock_wallet = MagicMock()
        mock_wallet.stake = AsyncMock(return_value={"stake_id": stake_id})

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                result = runner.invoke(app, ["wallet", "stake", "150"])

        assert stake_id[:8] in result.output  # at least first 8 chars of UUID

    def test_stake_api_error_exits_nonzero(self):
        mock_wallet = MagicMock()
        mock_wallet.stake = AsyncMock(side_effect=RuntimeError("not enough balance"))

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                result = runner.invoke(app, ["wallet", "stake", "999"])

        assert result.exit_code != 0


# ═════════════════════════════════════════════════════════════════════════════
# wallet history
# ═════════════════════════════════════════════════════════════════════════════

class TestWalletHistory:

    def test_history_prints_transactions(self):
        txs = [
            {"transaction_id": str(uuid4()), "tx_type": "transfer", "amount": 100},
            {"transaction_id": str(uuid4()), "tx_type": "stake",    "amount": 200},
        ]
        mock_wallet = MagicMock()
        mock_wallet.get_transactions = AsyncMock(return_value=txs)

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                result = runner.invoke(app, ["wallet", "history"])

        assert result.exit_code == 0
        assert "transfer" in result.output
        assert "stake" in result.output

    def test_history_empty_prints_no_transactions_message(self):
        mock_wallet = MagicMock()
        mock_wallet.get_transactions = AsyncMock(return_value=[])

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                result = runner.invoke(app, ["wallet", "history"])

        assert result.exit_code == 0
        assert "no" in result.output.lower() or "0" in result.output

    def test_history_respects_limit_option(self):
        mock_wallet = MagicMock()
        mock_wallet.get_transactions = AsyncMock(return_value=[])

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                runner.invoke(app, ["wallet", "history", "--limit", "5"])

        mock_wallet.get_transactions.assert_called_once_with(
            agent_id=_AGENT_ID, limit=5
        )

    def test_history_api_error_exits_nonzero(self):
        mock_wallet = MagicMock()
        mock_wallet.get_transactions = AsyncMock(side_effect=RuntimeError("API error"))

        with patch("agentx_cli.wallet_cmd.load_config", return_value=MOCK_CONFIG):
            with patch("agentx_cli.wallet_cmd.WalletClient", return_value=mock_wallet):
                result = runner.invoke(app, ["wallet", "history"])

        assert result.exit_code != 0
