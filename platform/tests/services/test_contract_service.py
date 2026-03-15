"""
Tests: src/services/contract_service.py
Phase 10 -- Agent Contract Engine

Covers:
  create_contract()    -- resolves DID, inserts contract, escrows budget
  list_contracts()     -- returns contracts filtered by status
  submit_bid()         -- validates contract+bidder, inserts bid
  assign_contract()    -- validates creator, accepts bid, updates contract
  submit_result()      -- validates contractor, inserts result
  complete_contract()  -- validates creator, releases escrow
  open_dispute()       -- inserts dispute, updates contract status
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.models.contract import (
    ContractBidCreate,
    ContractCreate,
    ContractDisputeCreate,
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


# -- create_contract ----------------------------------------------------------

class TestCreateContract:

    @pytest.mark.asyncio
    async def test_creates_contract_and_returns_response(self):
        data      = ContractCreate(title="Build API", description="REST API", budget=500)
        agent_row = _agent_row()
        initial   = _contract_row(creator_id=agent_row["agent_id"], escrowed_budget=0)
        escrowed  = _contract_row(creator_id=agent_row["agent_id"], escrowed_budget=500)

        conn = AsyncMock()
        # fetchrow: 1) agent lookup, 2) INSERT contract, 3) re-fetch after escrow
        conn.fetchrow = AsyncMock(side_effect=[agent_row, initial, escrowed])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=AsyncMock()),
        ):
            result = await contract_service.create_contract("did:agentx:creator", data)

        assert result.title == "Test Contract"
        assert result.status == "open"

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_raise(self):
        data      = ContractCreate(title="T", description="D", budget=100)
        agent_row = _agent_row()
        row       = _contract_row(escrowed_budget=0)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[agent_row, row, row])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch(
                "src.services.contract_service.publish_event",
                new=AsyncMock(side_effect=Exception("redis down")),
            ),
        ):
            result = await contract_service.create_contract("did:x:a", data)

        assert result.contract_id is not None

    @pytest.mark.asyncio
    async def test_escrow_failure_does_not_prevent_creation(self):
        """If escrow fails (insufficient funds), contract is still returned."""
        data      = ContractCreate(title="T", description="D", budget=9999)
        agent_row = _agent_row()
        row       = _contract_row(budget=9999, escrowed_budget=0)

        conn = AsyncMock()
        # INSERT succeeds; escrow debit fails (returns None = insufficient funds)
        conn.fetchrow = AsyncMock(side_effect=[agent_row, row, ValueError("insufficient")])
        # Make the debit UPDATE return None to trigger escrow failure
        conn.execute  = AsyncMock(side_effect=Exception("wallet error"))

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=AsyncMock()),
        ):
            # The service should soft-fail the escrow and still return the contract
            # Since _escrow raises, the re-fetch won't happen — we return the initial row
            result = await contract_service.create_contract("did:x:a", data)

        assert result is not None

    @pytest.mark.asyncio
    async def test_no_agent_id_skips_escrow(self):
        """If DID resolves to None (agent not found), escrow is skipped."""
        data = ContractCreate(title="T", description="D", budget=500)
        row  = _contract_row(creator_id=None, escrowed_budget=0)

        conn = AsyncMock()
        # Agent lookup returns None; no escrow attempted
        conn.fetchrow = AsyncMock(side_effect=[None, row])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=AsyncMock()),
        ):
            result = await contract_service.create_contract("did:x:unknown", data)

        assert result.escrowed_budget == 0


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


# -- submit_bid ---------------------------------------------------------------

class TestSubmitBid:

    @pytest.mark.asyncio
    async def test_submits_bid_successfully(self):
        contract_id = uuid4()
        contract    = _contract_row(contract_id=contract_id, status="open")
        bidder_row  = _agent_row()
        bid_row     = _bid_row(contract_id=contract_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract, bidder_row, bid_row])

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
            pytest.raises(ValueError, match="not open"),
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

        contract_q = {"contract_id": contract_id, "creator_did": "did:agentx:creator", "status": "open"}
        bid_q      = {"bid_id": bid_id, "bidder_did": "did:agentx:bidder", "bidder_id": bidder_id}
        updated    = _contract_row(contract_id=contract_id, status="assigned",
                                   contractor_did="did:agentx:bidder", contractor_id=bidder_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_q, bid_q, updated])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=AsyncMock()),
        ):
            result = await contract_service.assign_contract(
                contract_id, "did:agentx:creator", bid_id
            )

        assert result.status == "assigned"
        assert result.contractor_did == "did:agentx:bidder"

    @pytest.mark.asyncio
    async def test_raises_if_not_creator(self):
        contract_q = {"contract_id": uuid4(), "creator_did": "did:agentx:real-creator", "status": "open"}
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_q)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="[Cc]reator"),
        ):
            await contract_service.assign_contract(
                contract_q["contract_id"], "did:agentx:impostor", uuid4()
            )

    @pytest.mark.asyncio
    async def test_raises_if_not_open(self):
        contract_q = {"contract_id": uuid4(), "creator_did": "did:x:c", "status": "assigned"}
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_q)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="cannot be assigned"),
        ):
            await contract_service.assign_contract(
                contract_q["contract_id"], "did:x:c", uuid4()
            )

    @pytest.mark.asyncio
    async def test_raises_if_bid_not_found(self):
        contract_q = {"contract_id": uuid4(), "creator_did": "did:x:c", "status": "open"}
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_q, None])  # bid not found

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="[Bb]id not found"),
        ):
            await contract_service.assign_contract(
                contract_q["contract_id"], "did:x:c", uuid4()
            )


# -- submit_result ------------------------------------------------------------

class TestSubmitResult:

    @pytest.mark.asyncio
    async def test_submits_result_successfully(self):
        contract_id   = uuid4()
        contractor_id = uuid4()
        contract_q    = {
            "contract_id":    contract_id,
            "status":         "assigned",
            "contractor_did": "did:agentx:contractor",
            "contractor_id":  contractor_id,
        }
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
                "did:agentx:contractor",
                ContractResultCreate(result_payload={"output": "done"}),
            )

        assert result.contractor_did == "did:agentx:contractor"

    @pytest.mark.asyncio
    async def test_raises_if_not_assigned(self):
        contract_q = {
            "contract_id": uuid4(), "status": "open",
            "contractor_did": None, "contractor_id": None,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_q)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="assigned state"),
        ):
            await contract_service.submit_result(
                contract_q["contract_id"], "did:x:a", ContractResultCreate()
            )

    @pytest.mark.asyncio
    async def test_raises_if_not_contractor(self):
        contract_q = {
            "contract_id": uuid4(), "status": "assigned",
            "contractor_did": "did:agentx:real-contractor",
            "contractor_id": uuid4(),
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_q)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="[Cc]ontractor"),
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

class TestCompleteContract:

    @pytest.mark.asyncio
    async def test_completes_contract_and_releases_escrow(self):
        contract_id   = uuid4()
        contractor_id = uuid4()
        contract_full = _contract_row(
            contract_id=contract_id,
            creator_did="did:agentx:creator",
            status="submitted",
            escrowed_budget=1000,
            contractor_did="did:agentx:contractor",
            contractor_id=contractor_id,
        )
        updated = _contract_row(
            contract_id=contract_id,
            creator_did="did:agentx:creator",
            status="completed",
            escrowed_budget=0,
            contractor_id=contractor_id,
        )
        wallet_row = {"wallet_id": uuid4()}
        tx_row = {
            "transaction_id": uuid4(), "from_wallet": None, "to_wallet": uuid4(),
            "amount": 1000, "type": "contract_release", "related_id": contract_id,
            "timestamp": _now(),
        }

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_full, updated, wallet_row, tx_row])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=AsyncMock()),
        ):
            result = await contract_service.complete_contract(
                contract_id, "did:agentx:creator"
            )

        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_raises_if_not_creator(self):
        contract_full = _contract_row(
            creator_did="did:agentx:creator",
            status="submitted",
        )
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_full)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="[Cc]reator"),
        ):
            await contract_service.complete_contract(
                contract_full["contract_id"], "did:x:impostor"
            )

    @pytest.mark.asyncio
    async def test_raises_if_not_submitted(self):
        contract_full = _contract_row(
            creator_did="did:x:c", status="assigned"
        )
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract_full)

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="submitted state"),
        ):
            await contract_service.complete_contract(
                contract_full["contract_id"], "did:x:c"
            )

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
        contract_id = uuid4()
        contract_full = _contract_row(
            contract_id=contract_id,
            creator_did="did:agentx:creator",
            status="submitted",
            escrowed_budget=0,
        )
        updated = _contract_row(contract_id=contract_id, status="completed", escrowed_budget=0)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_full, updated])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch(
                "src.services.contract_service.publish_event",
                new=AsyncMock(side_effect=Exception("redis down")),
            ),
        ):
            result = await contract_service.complete_contract(
                contract_id, "did:agentx:creator"
            )

        assert result.status == "completed"


# -- open_dispute -------------------------------------------------------------

class TestOpenDispute:

    @pytest.mark.asyncio
    async def test_opens_dispute_successfully(self):
        contract_id  = uuid4()
        contract_q   = {"contract_id": contract_id, "creator_id": uuid4()}
        initiator_q  = _agent_row()
        dispute_r    = _dispute_row(contract_id=contract_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_q, initiator_q, dispute_r])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.contract_service.publish_event", new=AsyncMock()),
        ):
            result = await contract_service.open_dispute(
                contract_id, "did:agentx:initiator", "Work not delivered"
            )

        assert result.reason == "Work not delivered"
        assert result.status == "open"

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
        contract_q  = {"contract_id": contract_id, "creator_id": uuid4()}
        initiator_q = _agent_row()
        dispute_r   = _dispute_row(contract_id=contract_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract_q, initiator_q, dispute_r])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.contract_service.transaction", return_value=_tx_context(conn)),
            patch(
                "src.services.contract_service.publish_event",
                new=AsyncMock(side_effect=Exception("redis down")),
            ),
        ):
            result = await contract_service.open_dispute(
                contract_id, "did:agentx:initiator", "Dispute reason"
            )

        assert result.dispute_id is not None
