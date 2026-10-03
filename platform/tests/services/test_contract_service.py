"""
Tests: src/services/contract_service.py
Phase 10 -- Agent Contract Engine

Covers:
  create_contract()    -- resolves DID, inserts contract, escrows budget (hard-fail)
  list_contracts()     -- returns contracts filtered by status
  submit_bid()         -- validates contract+bidder, inserts bid; no self-bids
  assign_contract()    -- validates creator, accepts bid, updates contract
  submit_result()      -- validates contractor, inserts result
  complete_contract()  -- validates creator, pays the escrow to the contractor
  cancel_contract()    -- validates creator, refunds the escrow of an open contract
  open_dispute()       -- parties only, in-flight contracts only

Sprint 9, S9-6b: who may do what (PermissionError), in which state
(ContractConflictError), with the contract row locked. These tests mock the
connection; the proof that money moves once against real Postgres is
tests/integration/test_contract_escrow_db.py.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.models.contract import (
    ContractBidCreate,
    ContractCreate,
    ContractResultCreate,
)
from src.services import contract_service


# -- Helpers ------------------------------------------------------------------

def _tx_context(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__  = AsyncMock(return_value=None)
    return ctx


def _now():
    return datetime.now(UTC)


def _agent_row(agent_id=None):
    return {"agent_id": agent_id or uuid4()}


def _contract_row(
    contract_id=None,
    creator_did="did:agentx:creator",
    creator_id=None,
    contractor_did=None,
    contractor_id=None,
    status="open",
    budget=1000,
    escrowed_budget=1000,
):
    return {
        "contract_id":     contract_id or uuid4(),
        "creator_did":     creator_did,
        "creator_id":      creator_id or uuid4(),
        "contractor_did":  contractor_did,
        "contractor_id":   contractor_id,
        "title":           "Test Contract",
        "description":     "Contract description",
        "contract_type":   "general",
        "status":          status,
        "budget":          budget,
        "escrowed_budget": escrowed_budget,
        "deadline":        None,
        "payload":         None,
        "created_at":      _now(),
    }


def _bid_row(bid_id=None, contract_id=None, bidder_did="did:agentx:bidder", status="pending"):
    return {
        "bid_id":      bid_id or uuid4(),
        "contract_id": contract_id or uuid4(),
        "bidder_did":  bidder_did,
        "bid_amount":  500,
        "proposal":    "I can do this",
        "status":      status,
        "created_at":  _now(),
    }


def _result_row(result_id=None, contract_id=None):
    return {
        "result_id":      result_id or uuid4(),
        "contract_id":    contract_id or uuid4(),
        "contractor_did": "did:agentx:contractor",
        "result_payload": None,
        "submitted_at":   _now(),
    }


def _dispute_row(dispute_id=None, contract_id=None):
    return {
        "dispute_id":    dispute_id or uuid4(),
        "contract_id":   contract_id or uuid4(),
        "initiator_did": "did:agentx:initiator",
        "reason":        "Work not delivered",
        "status":        "open",
        "created_at":    _now(),
    }


def _sql(conn) -> str:
    """Every SQL statement the service sent on this connection, joined."""
    calls = (
        conn.fetchrow.call_args_list
        + conn.fetchval.call_args_list
        + conn.execute.call_args_list
    )
    return "\n".join(" ".join(str(c.args[0]).split()) for c in calls)


CREATOR    = "did:agentx:creator"
CONTRACTOR = "did:agentx:contractor"
OUTSIDER   = "did:agentx:outsider"


# -- create_contract ----------------------------------------------------------

class TestCreateContract:

    @pytest.mark.asyncio
    async def test_creates_contract_and_escrows_budget(self):
        data      = ContractCreate(title="Build API", description="REST API", budget=500)
        agent_row = _agent_row()
        initial   = _contract_row(creator_id=agent_row["agent_id"], budget=500, escrowed_budget=0)
        escrowed  = _contract_row(creator_id=agent_row["agent_id"], budget=500, escrowed_budget=500)

        conn = AsyncMock()
        # fetchrow: 1) agent lookup, 2) INSERT contract, 3) wallet debit, 4) re-fetch
        conn.fetchrow = AsyncMock(side_effect=[agent_row, initial, {"wallet_id": uuid4()}, escrowed])
        record_tx = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=AsyncMock()),
            patch("src.services.contract_service._record_transaction", new=record_tx),
        ):
            result = await contract_service.create_contract(CREATOR, data)

        assert result.status == "open"
        assert result.escrowed_budget == 500
        # The debit is the caller's own wallet, guarded by the balance.
        debit = conn.fetchrow.call_args_list[2]
        assert "balance >= $1" in " ".join(debit.args[0].split())
        assert debit.args[1:] == (500, agent_row["agent_id"])
        assert record_tx.call_args.kwargs["tx_type"] == "contract_escrow"
        assert record_tx.call_args.kwargs["amount"] == 500

    @pytest.mark.asyncio
    async def test_insufficient_funds_refuses_the_contract(self):
        """No soft-fail: the error leaves the transaction, so the INSERT rolls back."""
        data      = ContractCreate(title="T", description="D", budget=9999)
        agent_row = _agent_row()
        row       = _contract_row(budget=9999, escrowed_budget=0)

        conn = AsyncMock()
        # INSERT succeeds; the wallet debit matches no row (no wallet / too poor)
        conn.fetchrow = AsyncMock(side_effect=[agent_row, row, None])
        publish = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=publish),
            pytest.raises(ValueError, match="Insufficient funds") as exc,
        ):
            await contract_service.create_contract(CREATOR, data)

        assert "not found" not in str(exc.value).lower()   # → 400, not 404
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_creator_is_refused(self):
        data = ContractCreate(title="T", description="D", budget=500)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None])

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=AsyncMock()),
            pytest.raises(ValueError, match="not found"),
        ):
            await contract_service.create_contract("did:x:unknown", data)

        assert conn.fetchrow.await_count == 1                # nothing inserted

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_raise(self):
        data      = ContractCreate(title="T", description="D", budget=100)
        agent_row = _agent_row()
        row       = _contract_row(budget=100, escrowed_budget=100)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[agent_row, row, {"wallet_id": uuid4()}, row])

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service._record_transaction", new=AsyncMock()),
            patch(
                "src.services.contract_service.publish_event",
                new=AsyncMock(side_effect=Exception("redis down")),
            ),
        ):
            result = await contract_service.create_contract("did:x:a", data)

        assert result.contract_id is not None


# -- list_contracts -----------------------------------------------------------

class TestListContracts:

    @pytest.mark.asyncio
    async def test_returns_open_contracts(self):
        rows = [_contract_row(status="open"), _contract_row(status="open")]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.contract_service.get_db", return_value=_tx_context(conn)):
            result = await contract_service.list_contracts(status="open")

        assert len(result) == 2
        assert all(c.status == "open" for c in result)

    @pytest.mark.asyncio
    async def test_returns_empty_when_none(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.contract_service.get_db", return_value=_tx_context(conn)):
            result = await contract_service.list_contracts(status="completed")

        assert result == []

    @pytest.mark.asyncio
    async def test_none_status_returns_all(self):
        rows = [_contract_row(status="open"), _contract_row(status="completed")]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.contract_service.get_db", return_value=_tx_context(conn)):
            result = await contract_service.list_contracts(status=None)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_is_paged(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.contract_service.get_db", return_value=_tx_context(conn)):
            await contract_service.list_contracts(status="open", limit=7, offset=14)

        call = conn.fetch.call_args
        assert "LIMIT" in call.args[0] and "OFFSET" in call.args[0]
        assert call.args[1:] == ("open", 7, 14)


# -- submit_bid ---------------------------------------------------------------

class TestSubmitBid:

    @pytest.mark.asyncio
    async def test_submits_bid_successfully(self):
        contract_id = uuid4()
        contract    = _contract_row(contract_id=contract_id, creator_did=CREATOR, status="open")
        bidder_row  = _agent_row()
        bid_row     = _bid_row(contract_id=contract_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract, bidder_row, bid_row])
        conn.fetchval = AsyncMock(return_value=None)          # no earlier bid

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=AsyncMock()),
        ):
            result = await contract_service.submit_bid(
                contract_id,
                "did:agentx:bidder",
                ContractBidCreate(bid_amount=500, proposal="I can do this"),
            )

        assert result.bid_amount == 500
        assert result.status == "pending"
        assert "FOR UPDATE" in conn.fetchrow.call_args_list[0].args[0]

    @pytest.mark.asyncio
    async def test_creator_cannot_bid_on_own_contract(self):
        contract = _contract_row(creator_did=CREATOR, status="open")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract])

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(PermissionError, match="own contract"),
        ):
            await contract_service.submit_bid(
                contract["contract_id"], CREATOR, ContractBidCreate(bid_amount=100)
            )

        assert "INSERT" not in _sql(conn)

    @pytest.mark.asyncio
    async def test_second_bid_from_same_agent_is_a_conflict(self):
        contract = _contract_row(creator_did=CREATOR, status="open")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract, _agent_row()])
        conn.fetchval = AsyncMock(return_value=1)             # already bid

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(contract_service.ContractConflictError, match="already bid"),
        ):
            await contract_service.submit_bid(
                contract["contract_id"], "did:agentx:bidder", ContractBidCreate(bid_amount=100)
            )

        assert "INSERT" not in _sql(conn)

    @pytest.mark.asyncio
    async def test_raises_if_contract_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await contract_service.submit_bid(
                uuid4(), "did:x:a", ContractBidCreate(bid_amount=100)
            )

    @pytest.mark.asyncio
    async def test_raises_if_contract_not_open(self):
        contract = _contract_row(status="assigned")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(contract_service.ContractConflictError, match="not open"),
        ):
            await contract_service.submit_bid(
                contract["contract_id"], "did:x:a", ContractBidCreate(bid_amount=100)
            )

    @pytest.mark.asyncio
    async def test_raises_if_bidder_not_found(self):
        contract   = _contract_row(status="open")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract, None])  # bidder not found

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await contract_service.submit_bid(
                contract["contract_id"], "did:x:ghost", ContractBidCreate(bid_amount=100)
            )


# -- assign_contract ----------------------------------------------------------

class TestAssignContract:

    @pytest.mark.asyncio
    async def test_assigns_contract_successfully(self):
        contract_id = uuid4()
        bid_id      = uuid4()
        bidder_id   = uuid4()

        contract_q = _contract_row(contract_id=contract_id, creator_did=CREATOR, status="open")
        bid_q      = {"bid_id": bid_id, "bidder_did": "did:agentx:bidder", "bidder_id": bidder_id,
                      "bid_amount": 1000}
        updated    = _contract_row(contract_id=contract_id, status="assigned",
                                   contractor_did="did:agentx:bidder", contractor_id=bidder_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_q, bid_q, updated])
        conn.fetchval = AsyncMock(return_value=1000)          # escrow == bid: no refund
        conn.execute  = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=AsyncMock()),
        ):
            result = await contract_service.assign_contract(contract_id, CREATOR, bid_id)

        assert result.status == "assigned"
        assert result.contractor_did == "did:agentx:bidder"
        assert "FOR UPDATE" in conn.fetchrow.call_args_list[0].args[0]

    @pytest.mark.asyncio
    async def test_raises_if_not_creator(self):
        contract_q = _contract_row(creator_did="did:agentx:real-creator", status="open")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_q)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(PermissionError, match="[Cc]reator"),
        ):
            await contract_service.assign_contract(
                contract_q["contract_id"], "did:agentx:impostor", uuid4()
            )

    @pytest.mark.asyncio
    async def test_raises_if_not_open(self):
        contract_q = _contract_row(creator_did="did:x:c", status="assigned")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_q)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(contract_service.ContractConflictError, match="cannot be assigned"),
        ):
            await contract_service.assign_contract(
                contract_q["contract_id"], "did:x:c", uuid4()
            )

    @pytest.mark.asyncio
    async def test_raises_if_bid_not_found(self):
        contract_q = _contract_row(creator_did="did:x:c", status="open")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_q, None])  # bid not found

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="[Bb]id not found"),
        ):
            await contract_service.assign_contract(
                contract_q["contract_id"], "did:x:c", uuid4()
            )

    @pytest.mark.asyncio
    async def test_cannot_assign_to_the_creators_own_bid(self):
        """Backstop for a self-bid that predates the no-self-bid rule."""
        contract_q = _contract_row(creator_did=CREATOR, status="open")
        bid_q      = {"bid_id": uuid4(), "bidder_did": CREATOR, "bidder_id": uuid4()}
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_q, bid_q])

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(PermissionError, match="own creator"),
        ):
            await contract_service.assign_contract(
                contract_q["contract_id"], CREATOR, bid_q["bid_id"]
            )

        conn.execute.assert_not_awaited()


# -- submit_result ------------------------------------------------------------

class TestSubmitResult:

    @pytest.mark.asyncio
    async def test_submits_result_successfully(self):
        contract_id   = uuid4()
        contract_q    = _contract_row(
            contract_id=contract_id, status="assigned",
            contractor_did=CONTRACTOR, contractor_id=uuid4(),
        )
        result_r = _result_row(contract_id=contract_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_q, result_r])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=AsyncMock()),
        ):
            result = await contract_service.submit_result(
                contract_id,
                CONTRACTOR,
                ContractResultCreate(result_payload={"output": "done"}),
            )

        assert result.contractor_did == CONTRACTOR
        sql = _sql(conn)
        assert "FOR UPDATE" in sql
        # Submitting a result never touches a wallet: only /complete pays.
        assert "wallets" not in sql

    @pytest.mark.asyncio
    async def test_raises_if_not_assigned(self):
        """A second result (status already 'submitted') is a conflict."""
        contract_q = _contract_row(
            status="submitted", contractor_did=CONTRACTOR, contractor_id=uuid4(),
        )
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_q)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(contract_service.ContractConflictError, match="assigned state"),
        ):
            await contract_service.submit_result(
                contract_q["contract_id"], CONTRACTOR, ContractResultCreate()
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("contractor_did", ["did:agentx:real-contractor", None])
    async def test_raises_if_not_contractor(self, contractor_did):
        contract_q = _contract_row(
            status="assigned" if contractor_did else "open",
            contractor_did=contractor_did,
            contractor_id=uuid4() if contractor_did else None,
        )
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_q)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(PermissionError, match="[Cc]ontractor"),
        ):
            await contract_service.submit_result(
                contract_q["contract_id"], "did:x:impostor", ContractResultCreate()
            )

    @pytest.mark.asyncio
    async def test_raises_if_contract_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await contract_service.submit_result(uuid4(), "did:x:a", ContractResultCreate())


# -- complete_contract --------------------------------------------------------

def _submitted(contract_id=None, contractor_id=None, escrowed_budget=1000):
    return _contract_row(
        contract_id=contract_id or uuid4(),
        creator_did=CREATOR,
        status="submitted",
        escrowed_budget=escrowed_budget,
        contractor_did=CONTRACTOR,
        contractor_id=contractor_id or uuid4(),
    )


class TestCompleteContract:

    @pytest.mark.asyncio
    async def test_completes_contract_and_pays_the_contractor(self):
        contract_id   = uuid4()
        contractor_id = uuid4()
        contract_full = _submitted(contract_id, contractor_id)
        updated = _contract_row(
            contract_id=contract_id, creator_did=CREATOR, status="completed",
            escrowed_budget=0, contractor_did=CONTRACTOR, contractor_id=contractor_id,
        )
        wallet_id = uuid4()

        conn = AsyncMock()
        # fetchrow: 1) locked contract, 2) wallet upsert, 3) status UPDATE
        conn.fetchrow = AsyncMock(side_effect=[contract_full, {"wallet_id": wallet_id}, updated])
        conn.fetchval = AsyncMock(return_value=1000)          # escrowed_budget, locked read
        record_tx = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=AsyncMock()),
            patch("src.services.contract_service._record_transaction", new=record_tx),
        ):
            result = await contract_service.complete_contract(contract_id, CREATOR)

        assert result.status == "completed"
        assert result.escrowed_budget == 0

        assert "FOR UPDATE" in conn.fetchrow.call_args_list[0].args[0]
        assert "FOR UPDATE" in conn.fetchval.call_args.args[0]
        # Paid to the contractor on the contract row, the full escrow, once.
        credit = conn.fetchrow.call_args_list[1]
        assert "INSERT INTO wallets" in credit.args[0]
        assert credit.args[1:] == (1000, contractor_id)
        record_tx.assert_awaited_once()
        assert record_tx.call_args.kwargs == {
            "from_wallet": None, "to_wallet": wallet_id, "amount": 1000,
            "tx_type": "contract_release", "related_id": contract_id,
        }
        # The status change is guarded as well as locked.
        status_update = " ".join(conn.fetchrow.call_args_list[2].args[0].split())
        assert "SET status = 'completed'" in status_update
        assert "AND status = 'submitted'" in status_update

    @pytest.mark.asyncio
    async def test_payout_failure_fails_the_completion(self):
        """No soft-fail: a failed payout must not leave a 'completed' unpaid contract."""
        contract_full = _submitted()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_full, RuntimeError("wallet write failed")])
        conn.fetchval = AsyncMock(return_value=1000)
        publish = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=publish),
            pytest.raises(RuntimeError, match="wallet write failed"),
        ):
            await contract_service.complete_contract(contract_full["contract_id"], CREATOR)

        assert "SET status = 'completed'" not in _sql(conn)
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caller", [CONTRACTOR, OUTSIDER])
    async def test_raises_if_not_creator(self, caller):
        """Not even the contractor can release the escrow to themselves."""
        contract_full = _submitted()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_full)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(PermissionError, match="[Cc]reator"),
        ):
            await contract_service.complete_contract(contract_full["contract_id"], caller)

        assert "wallets" not in _sql(conn)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["open", "assigned", "completed", "cancelled", "disputed"])
    async def test_raises_if_not_submitted(self, status):
        contract_full = _contract_row(
            creator_did=CREATOR, status=status,
            contractor_did=CONTRACTOR, contractor_id=uuid4(),
        )
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_full)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(contract_service.ContractConflictError, match="submitted state"),
        ):
            await contract_service.complete_contract(contract_full["contract_id"], CREATOR)

        assert "wallets" not in _sql(conn)

    @pytest.mark.asyncio
    async def test_raises_if_contractor_is_gone(self):
        contract_full = _contract_row(
            creator_did=CREATOR, status="submitted",
            contractor_did=CONTRACTOR, contractor_id=None,
        )
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_full)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(contract_service.ContractConflictError, match="no contractor"),
        ):
            await contract_service.complete_contract(contract_full["contract_id"], CREATOR)

        assert "wallets" not in _sql(conn)

    @pytest.mark.asyncio
    async def test_raises_if_contract_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await contract_service.complete_contract(uuid4(), "did:x:a")

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_raise(self):
        contract_id   = uuid4()
        contract_full = _submitted(contract_id, escrowed_budget=0)
        updated = _contract_row(contract_id=contract_id, status="completed", escrowed_budget=0)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_full, updated])
        conn.fetchval = AsyncMock(return_value=0)             # nothing in escrow

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch(
                "src.services.contract_service.publish_event",
                new=AsyncMock(side_effect=Exception("redis down")),
            ),
        ):
            result = await contract_service.complete_contract(contract_id, CREATOR)

        assert result.status == "completed"
        assert "INSERT INTO wallets" not in _sql(conn)


# -- cancel_contract ----------------------------------------------------------

class TestCancelContract:

    @pytest.mark.asyncio
    async def test_cancels_open_contract_and_refunds_the_creator(self):
        contract_id = uuid4()
        creator_id  = uuid4()
        contract_q  = _contract_row(
            contract_id=contract_id, creator_did=CREATOR, creator_id=creator_id,
            status="open", escrowed_budget=1000,
        )
        updated = _contract_row(
            contract_id=contract_id, creator_did=CREATOR, creator_id=creator_id,
            status="cancelled", escrowed_budget=0,
        )
        wallet_id = uuid4()

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_q, {"wallet_id": wallet_id}, updated])
        conn.fetchval = AsyncMock(return_value=1000)
        record_tx = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service._record_transaction", new=record_tx),
        ):
            result = await contract_service.cancel_contract(contract_id, CREATOR)

        assert result.status == "cancelled"
        assert result.escrowed_budget == 0
        credit = conn.fetchrow.call_args_list[1]
        assert credit.args[1:] == (1000, creator_id)          # back to the creator
        assert record_tx.call_args.kwargs["tx_type"] == "contract_refund"
        status_update = " ".join(conn.fetchrow.call_args_list[2].args[0].split())
        assert "AND status = 'open'" in status_update

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caller", [CONTRACTOR, OUTSIDER])
    async def test_raises_if_not_creator(self, caller):
        contract_q = _contract_row(creator_did=CREATOR, status="open")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_q)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(PermissionError, match="[Cc]reator"),
        ):
            await contract_service.cancel_contract(contract_q["contract_id"], caller)

        assert "wallets" not in _sql(conn)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["assigned", "submitted", "completed", "cancelled", "disputed"])
    async def test_only_an_open_contract_can_be_cancelled(self, status):
        """Once a contractor is assigned the creator cannot pull the escrow back."""
        contract_q = _contract_row(
            creator_did=CREATOR, status=status,
            contractor_did=CONTRACTOR, contractor_id=uuid4(),
        )
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_q)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(contract_service.ContractConflictError, match="open contract"),
        ):
            await contract_service.cancel_contract(contract_q["contract_id"], CREATOR)

        assert "wallets" not in _sql(conn)

    @pytest.mark.asyncio
    async def test_raises_if_contract_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await contract_service.cancel_contract(uuid4(), CREATOR)


# -- open_dispute -------------------------------------------------------------

class TestOpenDispute:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caller", [CREATOR, CONTRACTOR])
    @pytest.mark.parametrize("status", ["assigned", "submitted"])
    async def test_a_party_opens_a_dispute(self, caller, status):
        contract_id = uuid4()
        contract_q  = _contract_row(
            contract_id=contract_id, creator_did=CREATOR, status=status,
            contractor_did=CONTRACTOR, contractor_id=uuid4(),
        )
        dispute_r = _dispute_row(contract_id=contract_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_q, _agent_row(), dispute_r])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=AsyncMock()),
        ):
            result = await contract_service.open_dispute(contract_id, caller, "Work not delivered")

        assert result.reason == "Work not delivered"
        assert result.status == "open"
        sql = _sql(conn)
        assert "FOR UPDATE" in sql
        assert "SET status = 'disputed'" in sql
        assert "wallets" not in sql                            # a dispute moves no tokens

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["open", "assigned", "submitted", "completed"])
    async def test_outsider_cannot_dispute(self, status):
        """The hole S9-6 found: any agent could freeze anyone's contract."""
        contractor = CONTRACTOR if status != "open" else None
        contract_q = _contract_row(
            creator_did=CREATOR, status=status,
            contractor_did=contractor, contractor_id=uuid4() if contractor else None,
        )
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_q)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(PermissionError, match="creator or contractor"),
        ):
            await contract_service.open_dispute(contract_q["contract_id"], OUTSIDER, "grief")

        # Only the locked read happened: no dispute row, no status change.
        assert conn.fetchrow.await_count == 1
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["open", "completed", "cancelled", "disputed"])
    async def test_party_cannot_dispute_outside_in_flight_states(self, status):
        contract_q = _contract_row(
            creator_did=CREATOR, status=status,
            contractor_did=CONTRACTOR, contractor_id=uuid4(),
        )
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_q)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(contract_service.ContractConflictError, match="cannot be disputed"),
        ):
            await contract_service.open_dispute(contract_q["contract_id"], CREATOR, "late")

        # Only the locked read happened: no dispute row, no status change.
        assert conn.fetchrow.await_count == 1
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_if_contract_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await contract_service.open_dispute(uuid4(), "did:x:a", "Dispute reason")

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_raise(self):
        contract_id = uuid4()
        contract_q  = _contract_row(
            contract_id=contract_id, creator_did=CREATOR, status="submitted",
            contractor_did=CONTRACTOR, contractor_id=uuid4(),
        )
        dispute_r   = _dispute_row(contract_id=contract_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_q, _agent_row(), dispute_r])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch(
                "src.services.contract_service.publish_event",
                new=AsyncMock(side_effect=Exception("redis down")),
            ),
        ):
            result = await contract_service.open_dispute(contract_id, CREATOR, "Dispute reason")

        assert result.dispute_id is not None
