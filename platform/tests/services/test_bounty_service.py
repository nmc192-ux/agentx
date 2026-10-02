"""
Tests: bounty_service (Phase 15)
══════════════════════════════════════════════════════════════════════════════
Covers:
  create_bounty          — escrows tokens, inserts bounty, fires event
  list_bounties          — filters by status and capability
  get_bounty             — fetch by ID, missing → ValueError
  submit_solution        — validates open bounty, inserts submission
  evaluate_submission    — validates creator, scores submission
  distribute_rewards     — finds winner, credits wallet, records reward
  cancel_bounty          — creator only, no submissions, refunds the pool
  list_submissions       — lists submissions for a bounty

All DB and event calls are mocked; no live DB/Redis required. The money rules
(paid once under concurrency, tokens conserved) are proven against real
Postgres in tests/integration/test_bounty_escrow_db.py.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.models.markets import BountyCreate, SubmissionCreate
from src.services.markets import bounty_service


# ── Shared helpers ────────────────────────────────────────────────────────────

def _bounty_row(
    bounty_id=None, status="open", reward_pool=1000,
    creator_did="did:agentx:creator",
):
    """Build a dict-backed mock row for capability_bounties."""
    data = {
        "bounty_id":            bounty_id or uuid4(),
        "creator_did":          creator_did,
        "creator_id":           uuid4(),
        "title":                "Test Bounty",
        "description":          "A test bounty",
        "capability_required":  "collect_data",
        "reward_pool":          reward_pool,
        "status":               status,
        "deadline":             None,
        "winner_submission_id": None,
        "created_at":           "2026-01-01T00:00:00Z",
        "closed_at":            None,
    }
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=data.__getitem__)
    row.get = MagicMock(side_effect=data.get)
    return row


def _submission_row(
    submission_id=None, bounty_id=None, submitter_did="did:agentx:agent1",
    status="pending", score=None,
):
    """Build a dict-backed mock row for bounty_submissions."""
    data = {
        "submission_id": submission_id or uuid4(),
        "bounty_id":     bounty_id or uuid4(),
        "submitter_did": submitter_did,
        "submitter_id":  uuid4(),
        "solution_data": json.dumps({"result": "ok"}),
        "summary":       "Test summary",
        "score":         score,
        "status":        status,
        "submitted_at":  "2026-01-01T00:00:00Z",
        "evaluated_at":  None,
    }
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=data.__getitem__)
    row.get = MagicMock(side_effect=data.get)
    return row


def _simple_bounty_row(bid, creator_did="did:agentx:creator", status="open",
                        reward_pool=500):
    """Minimal dict-backed bounty row for distribute_rewards tests."""
    data = {
        "bounty_id":            bid,
        "status":               status,
        "creator_did":          creator_did,
        "reward_pool":          reward_pool,
        "creator_id":           uuid4(),
        "title":                "T",
        "description":          "",
        "capability_required":  "x",
        "deadline":             None,
        "winner_submission_id": None,
        "created_at":           "2026-01-01T00:00:00Z",
        "closed_at":            None,
    }
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=data.__getitem__)
    row.get = MagicMock(side_effect=data.get)
    return row


def _agent_row():
    data = {"agent_id": uuid4()}
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=data.__getitem__)
    return row


def _wallet_row():
    data = {"wallet_id": uuid4()}
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=data.__getitem__)
    return row


@asynccontextmanager
async def _fake_transaction_with(conn):
    yield conn


@pytest.fixture(autouse=True)
def ledger():
    """The ledger insert (token_service._record_transaction) is not under test here."""
    with patch(
        "src.services.markets.bounty_service._record_transaction", new_callable=AsyncMock
    ) as mock:
        yield mock


@asynccontextmanager
async def _fake_db_with(conn):
    yield conn


# ═════════════════════════════════════════════════════════════════════════════
# create_bounty
# ═════════════════════════════════════════════════════════════════════════════

class TestCreateBounty:

    @pytest.mark.asyncio
    async def test_create_bounty_returns_bounty(self):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [_agent_row(), _wallet_row(), _bounty_row(bounty_id=bid)]
        conn.execute = AsyncMock()

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with patch("src.services.markets.bounty_service.publish_event", new_callable=AsyncMock):
                data = BountyCreate(title="T", capability_required="collect_data", reward_pool=1000)
                result = await bounty_service.create_bounty("did:agentx:creator", data)

        assert result.reward_pool == 1000
        assert result.title == "Test Bounty"

    @pytest.mark.asyncio
    async def test_create_bounty_records_escrow_against_the_bounty(self, ledger):
        bid = uuid4()
        wallet = _wallet_row()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [_agent_row(), wallet, _bounty_row(bounty_id=bid)]

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with patch("src.services.markets.bounty_service.publish_event", new_callable=AsyncMock):
                data = BountyCreate(title="T", capability_required="x", reward_pool=250)
                await bounty_service.create_bounty("did:agentx:creator", data)

        ledger.assert_awaited_once()
        kwargs = ledger.await_args.kwargs
        assert kwargs["from_wallet"] == wallet["wallet_id"]
        assert kwargs["to_wallet"] is None
        assert kwargs["amount"] == 250
        assert kwargs["tx_type"] == "bounty_escrow"
        assert kwargs["related_id"] == bid

    @pytest.mark.asyncio
    async def test_create_bounty_refused_for_unknown_agent(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)   # no such agent

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            data = BountyCreate(title="T", capability_required="x", reward_pool=100)
            with pytest.raises(ValueError, match="Creator agent not found"):
                await bounty_service.create_bounty("did:agentx:ghost", data)

        assert conn.fetchrow.await_count == 1          # nothing debited, nothing inserted

    @pytest.mark.asyncio
    async def test_create_bounty_raises_on_insufficient_funds(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _agent_row(),  # agent lookup
            None,          # wallet update returns None
        ]
        conn.fetchval = AsyncMock(return_value=1)  # wallet exists

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            data = BountyCreate(title="T", capability_required="x", reward_pool=99999)
            with pytest.raises(ValueError, match="Insufficient funds"):
                await bounty_service.create_bounty("did:agentx:creator", data)

    @pytest.mark.asyncio
    async def test_create_bounty_raises_wallet_not_found(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _agent_row(),
            None,
        ]
        conn.fetchval = AsyncMock(return_value=None)  # wallet does not exist

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            data = BountyCreate(title="T", capability_required="x", reward_pool=100)
            with pytest.raises(ValueError, match="Wallet not found"):
                await bounty_service.create_bounty("did:agentx:creator", data)

    @pytest.mark.asyncio
    async def test_create_bounty_publishes_event(self):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [_agent_row(), _wallet_row(), _bounty_row(bounty_id=bid)]
        conn.execute = AsyncMock()

        publish_mock = AsyncMock()
        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with patch("src.services.markets.bounty_service.publish_event", publish_mock):
                data = BountyCreate(title="T", capability_required="x", reward_pool=100)
                await bounty_service.create_bounty("did:agentx:creator", data)

        publish_mock.assert_called_once()
        assert publish_mock.call_args[0][0].value == "BOUNTY_CREATED"

    @pytest.mark.asyncio
    async def test_create_bounty_event_failure_does_not_propagate(self):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [_agent_row(), _wallet_row(), _bounty_row(bounty_id=bid)]
        conn.execute = AsyncMock()

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with patch(
                "src.services.markets.bounty_service.publish_event",
                side_effect=RuntimeError("Redis down"),
            ):
                data = BountyCreate(title="T", capability_required="x", reward_pool=100)
                result = await bounty_service.create_bounty("did:agentx:creator", data)

        assert result is not None


# ═════════════════════════════════════════════════════════════════════════════
# list_bounties
# ═════════════════════════════════════════════════════════════════════════════

class TestListBounties:

    @pytest.mark.asyncio
    async def test_list_returns_all_bounties(self):
        rows = [_bounty_row(), _bounty_row()]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.markets.bounty_service.get_db", lambda: _fake_db_with(conn)):
            result = await bounty_service.list_bounties()

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_passes_status_filter(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.markets.bounty_service.get_db", lambda: _fake_db_with(conn)):
            await bounty_service.list_bounties(status="open")

        call_args = conn.fetch.call_args[0]  # positional args
        assert "open" in call_args

    @pytest.mark.asyncio
    async def test_list_passes_capability_filter(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.markets.bounty_service.get_db", lambda: _fake_db_with(conn)):
            await bounty_service.list_bounties(capability="collect_data")

        call_args = conn.fetch.call_args[0]
        assert "collect_data" in call_args

    @pytest.mark.asyncio
    async def test_list_empty_returns_empty_list(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.markets.bounty_service.get_db", lambda: _fake_db_with(conn)):
            result = await bounty_service.list_bounties()

        assert result == []

    @pytest.mark.asyncio
    async def test_list_no_filter_passes_no_extra_params(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.markets.bounty_service.get_db", lambda: _fake_db_with(conn)):
            await bounty_service.list_bounties()

        # Only the query string plus the default page (limit, offset)
        call_args = conn.fetch.call_args[0]
        assert call_args[1:] == (50, 0)


# ═════════════════════════════════════════════════════════════════════════════
# get_bounty
# ═════════════════════════════════════════════════════════════════════════════

class TestGetBounty:

    @pytest.mark.asyncio
    async def test_get_bounty_returns_bounty(self):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_bounty_row(bounty_id=bid))

        with patch("src.services.markets.bounty_service.get_db", lambda: _fake_db_with(conn)):
            result = await bounty_service.get_bounty(bid)

        assert result.bounty_id == bid

    @pytest.mark.asyncio
    async def test_get_bounty_raises_on_missing(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("src.services.markets.bounty_service.get_db", lambda: _fake_db_with(conn)):
            with pytest.raises(ValueError, match="Bounty not found"):
                await bounty_service.get_bounty(uuid4())


# ═════════════════════════════════════════════════════════════════════════════
# submit_solution
# ═════════════════════════════════════════════════════════════════════════════

class TestSubmitSolution:

    def _open_bounty_row(self, bid):
        data = {"bounty_id": bid, "status": "open", "creator_did": "did:agentx:creator"}
        row = MagicMock()
        row.__getitem__ = MagicMock(side_effect=data.__getitem__)
        return row

    @pytest.mark.asyncio
    async def test_submit_returns_submission(self):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            self._open_bounty_row(bid),
            _agent_row(),
            _submission_row(bounty_id=bid),
        ]

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with patch("src.services.markets.bounty_service.publish_event", new_callable=AsyncMock):
                data = SubmissionCreate(solution_data={"result": "ok"}, summary="test")
                result = await bounty_service.submit_solution(bid, "did:agentx:agent1", data)

        assert result.bounty_id == bid

    @pytest.mark.asyncio
    async def test_submit_rejects_closed_bounty(self):
        bid = uuid4()
        data = {"bounty_id": bid, "status": "rewarded", "creator_did": "did:agentx:creator"}
        row = MagicMock()
        row.__getitem__ = MagicMock(side_effect=data.__getitem__)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(bounty_service.BountyConflictError, match="not open"):
                await bounty_service.submit_solution(
                    bid, "did:agentx:agent1", SubmissionCreate(solution_data={})
                )

    @pytest.mark.asyncio
    async def test_submit_rejects_the_bounty_creator(self):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._open_bounty_row(bid))

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(PermissionError, match="own bounty"):
                await bounty_service.submit_solution(
                    bid, "did:agentx:creator", SubmissionCreate(solution_data={})
                )

        assert conn.fetchrow.await_count == 1          # no submission inserted

    @pytest.mark.asyncio
    async def test_submit_locks_the_bounty_row(self):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            self._open_bounty_row(bid), _agent_row(), _submission_row(bounty_id=bid),
        ]

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with patch("src.services.markets.bounty_service.publish_event", new_callable=AsyncMock):
                await bounty_service.submit_solution(
                    bid, "did:agentx:agent1", SubmissionCreate(solution_data={})
                )

        assert "FOR UPDATE" in conn.fetchrow.await_args_list[0].args[0]

    @pytest.mark.asyncio
    async def test_submit_raises_on_missing_bounty(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(ValueError, match="Bounty not found"):
                await bounty_service.submit_solution(
                    uuid4(), "did:agentx:agent1", SubmissionCreate(solution_data={})
                )

    @pytest.mark.asyncio
    async def test_submit_publishes_event(self):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            self._open_bounty_row(bid),
            _agent_row(),
            _submission_row(bounty_id=bid),
        ]

        publish_mock = AsyncMock()
        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with patch("src.services.markets.bounty_service.publish_event", publish_mock):
                await bounty_service.submit_solution(
                    bid, "did:agentx:agent1", SubmissionCreate(solution_data={})
                )

        publish_mock.assert_called_once()
        assert publish_mock.call_args[0][0].value == "BOUNTY_SUBMISSION"

    @pytest.mark.asyncio
    async def test_submit_event_failure_does_not_propagate(self):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            self._open_bounty_row(bid),
            _agent_row(),
            _submission_row(bounty_id=bid),
        ]

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with patch(
                "src.services.markets.bounty_service.publish_event",
                side_effect=RuntimeError("bus down"),
            ):
                result = await bounty_service.submit_solution(
                    bid, "did:agentx:agent1", SubmissionCreate(solution_data={})
                )

        assert result is not None


# ═════════════════════════════════════════════════════════════════════════════
# evaluate_submission
# ═════════════════════════════════════════════════════════════════════════════

class TestEvaluateSubmission:

    def _bounty(self, bid, creator_did="did:agentx:creator", status="open"):
        data = {"bounty_id": bid, "status": status, "creator_did": creator_did}
        row = MagicMock()
        row.__getitem__ = MagicMock(side_effect=data.__getitem__)
        return row

    @pytest.mark.asyncio
    async def test_evaluate_returns_scored_submission(self):
        bid = uuid4()
        sid = uuid4()
        creator_did = "did:agentx:creator"

        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            self._bounty(bid, creator_did),
            _submission_row(submission_id=sid, bounty_id=bid, score=0.9, status="evaluated"),
        ]
        conn.execute = AsyncMock()

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with patch("src.services.markets.bounty_service.publish_event", new_callable=AsyncMock):
                result = await bounty_service.evaluate_submission(bid, sid, creator_did, 0.9)

        assert result.score == pytest.approx(0.9)
        assert result.status == "evaluated"

    @pytest.mark.asyncio
    async def test_evaluate_rejects_non_creator(self):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._bounty(bid, "did:agentx:real-creator"))

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(PermissionError, match="Only the bounty creator"):
                await bounty_service.evaluate_submission(
                    bid, uuid4(), "did:agentx:interloper", 0.5
                )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("closed_status", ["rewarded", "cancelled", "closed"])
    async def test_evaluate_refused_once_the_bounty_is_closed(self, closed_status):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._bounty(bid, status=closed_status))

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(bounty_service.BountyConflictError, match="cannot be evaluated"):
                await bounty_service.evaluate_submission(bid, uuid4(), "did:agentx:creator", 0.5)

        assert conn.fetchrow.await_count == 1          # no score written

    @pytest.mark.asyncio
    async def test_evaluate_raises_on_missing_bounty(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(ValueError, match="Bounty not found"):
                await bounty_service.evaluate_submission(
                    uuid4(), uuid4(), "did:agentx:creator", 0.5
                )

    @pytest.mark.asyncio
    async def test_evaluate_raises_on_missing_submission(self):
        bid = uuid4()
        creator_did = "did:agentx:creator"

        conn = AsyncMock()
        conn.fetchrow.side_effect = [self._bounty(bid, creator_did), None]
        conn.execute = AsyncMock()

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(ValueError, match="not found"):
                await bounty_service.evaluate_submission(bid, uuid4(), creator_did, 0.5)

    @pytest.mark.asyncio
    async def test_evaluate_publishes_event(self):
        bid = uuid4()
        sid = uuid4()
        creator_did = "did:agentx:creator"

        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            self._bounty(bid, creator_did),
            _submission_row(submission_id=sid, bounty_id=bid, score=0.8, status="evaluated"),
        ]
        conn.execute = AsyncMock()

        publish_mock = AsyncMock()
        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with patch("src.services.markets.bounty_service.publish_event", publish_mock):
                await bounty_service.evaluate_submission(bid, sid, creator_did, 0.8)

        publish_mock.assert_called_once()
        assert publish_mock.call_args[0][0].value == "BOUNTY_EVALUATED"


# ═════════════════════════════════════════════════════════════════════════════
# distribute_rewards
# ═════════════════════════════════════════════════════════════════════════════

class TestDistributeRewards:

    def _winner_row(self, sid, recipient_id=None):
        data = {
            "submission_id": sid,
            "submitter_did": "did:agentx:winner",
            "submitter_id":  recipient_id or uuid4(),
            "score":         0.9,
        }
        row = MagicMock()
        row.__getitem__ = MagicMock(side_effect=data.__getitem__)
        row.get = MagicMock(side_effect=data.get)
        return row

    def _reward_row(self, bid, sid, recipient_id):
        data = {
            "reward_id":      uuid4(),
            "bounty_id":      bid,
            "submission_id":  sid,
            "recipient_did":  "did:agentx:winner",
            "recipient_id":   recipient_id,
            "amount":         500,
            "distributed_at": "2026-01-01T00:00:00Z",
        }
        row = MagicMock()
        row.__getitem__ = MagicMock(side_effect=data.__getitem__)
        row.get = MagicMock(side_effect=data.get)
        return row

    @pytest.mark.asyncio
    async def test_distribute_returns_reward(self):
        bid = uuid4()
        sid = uuid4()
        recipient_id = uuid4()

        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _simple_bounty_row(bid),
            self._winner_row(sid, recipient_id),
            self._reward_row(bid, sid, recipient_id),
            _wallet_row(),
        ]
        conn.fetchval = AsyncMock(return_value=bid)    # status-guarded close succeeded
        conn.execute = AsyncMock()

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with patch("src.services.markets.bounty_service.publish_event", new_callable=AsyncMock):
                result = await bounty_service.distribute_rewards(bid, "did:agentx:creator")

        assert result.amount == 500
        assert result.recipient_did == "did:agentx:winner"

    @pytest.mark.asyncio
    async def test_distribute_locks_the_row_and_pays_the_winner_from_escrow(self, ledger):
        bid, sid, recipient_id = uuid4(), uuid4(), uuid4()
        wallet = _wallet_row()

        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _simple_bounty_row(bid),
            self._winner_row(sid, recipient_id),
            self._reward_row(bid, sid, recipient_id),
            wallet,
        ]
        conn.fetchval = AsyncMock(return_value=bid)

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with patch("src.services.markets.bounty_service.publish_event", new_callable=AsyncMock):
                await bounty_service.distribute_rewards(bid, "did:agentx:creator")

        calls = conn.fetchrow.await_args_list
        assert "FOR UPDATE" in calls[0].args[0]
        # the winner query can never pick the creator's own submission
        assert "submitter_did  <> $2" in calls[1].args[0]
        assert calls[1].args[1:] == (bid, "did:agentx:creator")
        # the close is status-guarded
        assert "status IN ('open', 'evaluating')" in conn.fetchval.await_args.args[0]
        # wallet credit: created if missing, credited with the pool
        assert "ON CONFLICT (agent_id) DO UPDATE" in calls[3].args[0]
        assert calls[3].args[1:] == (500, recipient_id)
        kwargs = ledger.await_args.kwargs
        assert (kwargs["from_wallet"], kwargs["to_wallet"]) == (None, wallet["wallet_id"])
        assert (kwargs["amount"], kwargs["tx_type"], kwargs["related_id"]) == (500, "bounty_reward", bid)

    @pytest.mark.asyncio
    async def test_distribute_pays_nothing_if_the_guarded_close_matches_no_row(self, ledger):
        bid, sid = uuid4(), uuid4()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [_simple_bounty_row(bid), self._winner_row(sid)]
        conn.fetchval = AsyncMock(return_value=None)   # someone else closed it first

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(bounty_service.BountyConflictError, match="already distributed"):
                await bounty_service.distribute_rewards(bid, "did:agentx:creator")

        assert conn.fetchrow.await_count == 2          # no reward row, no wallet credit
        ledger.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_distribute_payout_failure_propagates(self):
        """No soft-fail: if the credit fails, the whole transaction must roll back."""
        bid, sid, recipient_id = uuid4(), uuid4(), uuid4()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _simple_bounty_row(bid),
            self._winner_row(sid, recipient_id),
            self._reward_row(bid, sid, recipient_id),
            RuntimeError("wallet write failed"),
        ]
        conn.fetchval = AsyncMock(return_value=bid)

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(RuntimeError, match="wallet write failed"):
                await bounty_service.distribute_rewards(bid, "did:agentx:creator")

    @pytest.mark.asyncio
    async def test_distribute_rejects_non_creator(self):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_simple_bounty_row(bid, creator_did="did:agentx:real-creator")
        )

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(PermissionError, match="Only the bounty creator"):
                await bounty_service.distribute_rewards(bid, "did:agentx:other")

        assert conn.fetchrow.await_count == 1          # stopped before any payout

    @pytest.mark.asyncio
    @pytest.mark.parametrize("closed_status", ["rewarded", "cancelled", "closed"])
    async def test_distribute_raises_when_already_closed(self, closed_status, ledger):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_simple_bounty_row(bid, status=closed_status)
        )

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(bounty_service.BountyConflictError, match="cannot be distributed"):
                await bounty_service.distribute_rewards(bid, "did:agentx:creator")

        assert conn.fetchrow.await_count == 1          # stopped before any payout
        ledger.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_distribute_raises_on_no_evaluated_submissions(self):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [_simple_bounty_row(bid), None]

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(bounty_service.BountyConflictError, match="No evaluated submissions"):
                await bounty_service.distribute_rewards(bid, "did:agentx:creator")

    @pytest.mark.asyncio
    async def test_distribute_raises_on_missing_bounty(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(ValueError, match="Bounty not found"):
                await bounty_service.distribute_rewards(uuid4(), "did:agentx:creator")

    @pytest.mark.asyncio
    async def test_distribute_publishes_event(self):
        bid = uuid4()
        sid = uuid4()
        recipient_id = uuid4()

        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _simple_bounty_row(bid),
            self._winner_row(sid, recipient_id),
            self._reward_row(bid, sid, recipient_id),
            _wallet_row(),
        ]
        conn.fetchval = AsyncMock(return_value=bid)    # status-guarded close succeeded
        conn.execute = AsyncMock()

        publish_mock = AsyncMock()
        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with patch("src.services.markets.bounty_service.publish_event", publish_mock):
                await bounty_service.distribute_rewards(bid, "did:agentx:creator")

        publish_mock.assert_called_once()
        assert publish_mock.call_args[0][0].value == "BOUNTY_REWARD_DISTRIBUTED"
        payload = publish_mock.call_args[0][1]
        assert payload["recipient_id"] == str(recipient_id)   # discovery_consumer reads it
        assert payload["amount"] == 500


# ═════════════════════════════════════════════════════════════════════════════
# cancel_bounty
# ═════════════════════════════════════════════════════════════════════════════

class TestCancelBounty:

    @pytest.mark.asyncio
    async def test_cancel_refunds_the_creator(self, ledger):
        bid = uuid4()
        bounty = _simple_bounty_row(bid)
        wallet = _wallet_row()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [bounty, _simple_bounty_row(bid, status="cancelled"), wallet]
        conn.fetchval = AsyncMock(return_value=None)   # no submissions

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            result = await bounty_service.cancel_bounty(bid, "did:agentx:creator")

        assert result.status == "cancelled"
        calls = conn.fetchrow.await_args_list
        assert "FOR UPDATE" in calls[0].args[0]
        assert "AND status    = 'open'" in calls[1].args[0]
        assert calls[2].args[1:] == (500, bounty["creator_id"])
        kwargs = ledger.await_args.kwargs
        assert (kwargs["from_wallet"], kwargs["to_wallet"]) == (None, wallet["wallet_id"])
        assert (kwargs["amount"], kwargs["tx_type"], kwargs["related_id"]) == (500, "bounty_refund", bid)

    @pytest.mark.asyncio
    async def test_cancel_rejects_non_creator(self, ledger):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_simple_bounty_row(bid))

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(PermissionError, match="Only the bounty creator"):
                await bounty_service.cancel_bounty(bid, "did:agentx:other")

        ledger.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["evaluating", "rewarded", "cancelled"])
    async def test_cancel_only_an_open_bounty(self, status, ledger):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_simple_bounty_row(bid, status=status))

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(bounty_service.BountyConflictError, match="Only an open bounty"):
                await bounty_service.cancel_bounty(bid, "did:agentx:creator")

        ledger.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_refused_once_there_are_submissions(self, ledger):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_simple_bounty_row(bid))
        conn.fetchval = AsyncMock(return_value=1)      # a submission exists

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(bounty_service.BountyConflictError, match="has submissions"):
                await bounty_service.cancel_bounty(bid, "did:agentx:creator")

        assert conn.fetchrow.await_count == 1          # status untouched, nothing refunded
        ledger.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_raises_on_missing_bounty(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("src.services.markets.bounty_service.transaction", lambda: _fake_transaction_with(conn)):
            with pytest.raises(ValueError, match="Bounty not found"):
                await bounty_service.cancel_bounty(uuid4(), "did:agentx:creator")


# ═════════════════════════════════════════════════════════════════════════════
# list_submissions
# ═════════════════════════════════════════════════════════════════════════════

class TestListSubmissions:

    @pytest.mark.asyncio
    async def test_list_submissions_returns_list(self):
        bid = uuid4()
        rows = [_submission_row(bounty_id=bid), _submission_row(bounty_id=bid)]

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.markets.bounty_service.get_db", lambda: _fake_db_with(conn)):
            result = await bounty_service.list_submissions(bid)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_submissions_raises_on_missing_bounty(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)

        with patch("src.services.markets.bounty_service.get_db", lambda: _fake_db_with(conn)):
            with pytest.raises(ValueError, match="Bounty not found"):
                await bounty_service.list_submissions(uuid4())

    @pytest.mark.asyncio
    async def test_list_submissions_empty_returns_empty(self):
        bid = uuid4()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.markets.bounty_service.get_db", lambda: _fake_db_with(conn)):
            result = await bounty_service.list_submissions(bid)

        assert result == []
