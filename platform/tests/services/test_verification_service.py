"""
Tests: src/services/verification_service.py
Phase 12 -- Result Verification Engine

Covers:
  create_verification()    -- validates contract/result, inserts, auto-activates
  assign_verifiers()       -- activates a pending verification
  submit_vote()            -- validates state, computes vote_power, updates tallies
  calculate_consensus()    -- read-only tally + outcome computation
  finalize_verification()  -- idempotent state transition + event publishing
  get_verification()       -- single-record fetch
  list_pending_verifications() -- status-filtered list
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.models.verification import VerificationCreate, VerificationVoteCreate
from src.services import verification_service


# -- Helpers ------------------------------------------------------------------

def _tx_context(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__  = AsyncMock(return_value=None)
    return ctx


def _now():
    return datetime.now(UTC)


def _contract_row(
    contract_id=None,
    creator_did="did:agentx:creator",
    status="submitted",
):
    return {
        "contract_id":  contract_id or uuid4(),
        "creator_did":  creator_did,
        "status":       status,
    }


def _result_row(result_id=None, contract_id=None):
    return {"result_id": result_id or uuid4(), "contract_id": contract_id or uuid4()}


def _agent_row(agent_id=None, trust_score=0.8):
    return {"agent_id": agent_id or uuid4(), "trust_score": trust_score}


def _verification_row(
    verification_id=None,
    contract_id=None,
    result_id=None,
    requester_did="did:agentx:creator",
    status="active",
    required_votes=3,
    consensus_threshold=0.6,
    yes_power=0.0,
    no_power=0.0,
    vote_count=0,
    reward_pool=0,
    finalized_at=None,
):
    return {
        "verification_id":     verification_id or uuid4(),
        "contract_id":         contract_id or uuid4(),
        "result_id":           result_id or uuid4(),
        "requester_did":       requester_did,
        "requester_id":        uuid4(),
        "status":              status,
        "required_votes":      required_votes,
        "consensus_threshold": consensus_threshold,
        "yes_power":           yes_power,
        "no_power":            no_power,
        "vote_count":          vote_count,
        "reward_pool":         reward_pool,
        "created_at":          _now(),
        "finalized_at":        finalized_at,
    }


def _vote_row(vote_id=None, verification_id=None, vote="approve"):
    return {
        "vote_id":         vote_id or uuid4(),
        "verification_id": verification_id or uuid4(),
        "verifier_did":    "did:agentx:verifier",
        "vote":            vote,
        "vote_power":      2.0,
        "comment":         None,
        "created_at":      _now(),
    }


# -- create_verification ------------------------------------------------------

class TestCreateVerification:

    @pytest.mark.asyncio
    async def test_creates_verification_successfully(self):
        cid = uuid4()
        rid = uuid4()
        contract   = _contract_row(contract_id=cid)
        result     = _result_row(result_id=rid, contract_id=cid)
        agent_row  = _agent_row()
        pending_v  = _verification_row(contract_id=cid, result_id=rid, status="pending")
        active_v   = _verification_row(contract_id=cid, result_id=rid, status="active",
                                       verification_id=pending_v["verification_id"])

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            contract,   # contract lookup
            result,     # result lookup
            agent_row,  # requester DID → id
            pending_v,  # INSERT verification
            active_v,   # _do_activate UPDATE
        ])
        conn.execute = AsyncMock()

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.verification_service.publish_event", new=AsyncMock()),
        ):
            v = await verification_service.create_verification(
                "did:agentx:creator",
                VerificationCreate(contract_id=cid, result_id=rid),
            )

        assert v.status == "active"
        assert v.contract_id == cid
        assert v.result_id == rid

    @pytest.mark.asyncio
    async def test_raises_if_contract_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await verification_service.create_verification(
                "did:agentx:creator",
                VerificationCreate(contract_id=uuid4(), result_id=uuid4()),
            )

    @pytest.mark.asyncio
    async def test_raises_if_not_creator(self):
        contract = _contract_row(creator_did="did:agentx:real-creator")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract)

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="[Cc]reator"),
        ):
            await verification_service.create_verification(
                "did:agentx:impostor",
                VerificationCreate(contract_id=uuid4(), result_id=uuid4()),
            )

    @pytest.mark.asyncio
    async def test_raises_if_contract_not_submitted(self):
        contract = _contract_row(creator_did="did:agentx:creator", status="open")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=contract)

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="submitted"),
        ):
            await verification_service.create_verification(
                "did:agentx:creator",
                VerificationCreate(contract_id=uuid4(), result_id=uuid4()),
            )

    @pytest.mark.asyncio
    async def test_raises_if_result_not_found(self):
        cid      = uuid4()
        contract = _contract_row(contract_id=cid)
        conn     = AsyncMock()
        # contract found, result not found
        conn.fetchrow = AsyncMock(side_effect=[contract, None])

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await verification_service.create_verification(
                "did:agentx:creator",
                VerificationCreate(contract_id=cid, result_id=uuid4()),
            )

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_raise(self):
        cid      = uuid4()
        rid      = uuid4()
        contract = _contract_row(contract_id=cid)
        result   = _result_row(result_id=rid, contract_id=cid)
        agent    = _agent_row()
        pending  = _verification_row(contract_id=cid, result_id=rid, status="pending")
        active   = _verification_row(contract_id=cid, result_id=rid, status="active",
                                     verification_id=pending["verification_id"])

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[contract, result, agent, pending, active])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            patch(
                "src.services.verification_service.publish_event",
                new=AsyncMock(side_effect=Exception("redis down")),
            ),
        ):
            v = await verification_service.create_verification(
                "did:agentx:creator",
                VerificationCreate(contract_id=cid, result_id=rid),
            )

        assert v.verification_id is not None


# -- assign_verifiers ---------------------------------------------------------

class TestAssignVerifiers:

    @pytest.mark.asyncio
    async def test_activates_pending_verification(self):
        vid = uuid4()
        pending_v = {"verification_id": vid, "status": "pending"}
        active_v  = _verification_row(verification_id=vid, status="active")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[pending_v, active_v])

        with patch("src.services.verification_service.transaction", return_value=_tx_context(conn)):
            result = await verification_service.assign_verifiers(vid, "did:agentx:admin")

        assert result.status == "active"

    @pytest.mark.asyncio
    async def test_raises_if_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await verification_service.assign_verifiers(uuid4(), "did:agentx:caller")

    @pytest.mark.asyncio
    async def test_raises_if_not_pending(self):
        v = {"verification_id": uuid4(), "status": "active"}
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=v)

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not pending"),
        ):
            await verification_service.assign_verifiers(v["verification_id"], "did:agentx:caller")

    @pytest.mark.asyncio
    async def test_returns_active_verification_response(self):
        vid = uuid4()
        pending_v = {"verification_id": vid, "status": "pending"}
        active_v  = _verification_row(verification_id=vid, status="active", required_votes=5)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[pending_v, active_v])

        with patch("src.services.verification_service.transaction", return_value=_tx_context(conn)):
            result = await verification_service.assign_verifiers(vid, "did:agentx:admin")

        assert result.required_votes == 5
        assert result.status == "active"


# -- submit_vote --------------------------------------------------------------

class TestSubmitVote:

    @pytest.mark.asyncio
    async def test_submits_approve_vote(self):
        vid          = uuid4()
        verifier_id  = uuid4()
        verification = _verification_row(verification_id=vid, status="active",
                                         requester_did="did:agentx:creator",
                                         vote_count=0, required_votes=3)
        verifier_row = {"agent_id": verifier_id, "trust_score": 0.8}
        vote_row     = _vote_row(verification_id=vid, vote="approve")
        updated_v    = {"vote_count": 1, "required_votes": 3}

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[verification, verifier_row, vote_row])
        conn.fetchval = AsyncMock(side_effect=[
            None,   # duplicate-vote check → not found
            500,    # active stakes sum
            updated_v["vote_count"],  # not used directly; updated_v via fetchrow
        ])
        conn.fetchrow.side_effect = [verification, verifier_row, None, vote_row, updated_v]
        conn.execute  = AsyncMock()

        # Re-setup correctly with side_effect list
        conn.fetchrow = AsyncMock(side_effect=[verification, verifier_row, vote_row, updated_v])
        conn.fetchval = AsyncMock(side_effect=[None, 500])  # dup check, stake sum

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.verification_service.publish_event", new=AsyncMock()),
        ):
            result = await verification_service.submit_vote(
                vid, "did:agentx:verifier",
                VerificationVoteCreate(vote="approve"),
            )

        assert result.vote == "approve"
        assert result.vote_power >= 1.0

    @pytest.mark.asyncio
    async def test_raises_if_verification_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await verification_service.submit_vote(
                uuid4(), "did:agentx:v", VerificationVoteCreate(vote="approve")
            )

    @pytest.mark.asyncio
    async def test_raises_if_not_active(self):
        v = _verification_row(status="pending")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=v)

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not active"),
        ):
            await verification_service.submit_vote(
                v["verification_id"], "did:agentx:v", VerificationVoteCreate(vote="approve")
            )

    @pytest.mark.asyncio
    async def test_raises_if_requester_votes(self):
        v = _verification_row(status="active", requester_did="did:agentx:requester")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=v)

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="[Rr]equester"),
        ):
            await verification_service.submit_vote(
                v["verification_id"], "did:agentx:requester",
                VerificationVoteCreate(vote="approve"),
            )

    @pytest.mark.asyncio
    async def test_raises_if_verifier_not_found(self):
        v    = _verification_row(status="active", requester_did="did:agentx:creator")
        conn = AsyncMock()
        # verification found; verifier lookup returns None
        conn.fetchrow = AsyncMock(side_effect=[v, None])

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await verification_service.submit_vote(
                v["verification_id"], "did:agentx:ghost",
                VerificationVoteCreate(vote="approve"),
            )

    @pytest.mark.asyncio
    async def test_raises_if_duplicate_vote(self):
        vid          = uuid4()
        verifier_id  = uuid4()
        v            = _verification_row(verification_id=vid, status="active",
                                         requester_did="did:agentx:creator")
        verifier_row = {"agent_id": verifier_id, "trust_score": 0.5}
        existing_vid = uuid4()  # signals existing vote

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[v, verifier_row])
        conn.fetchval = AsyncMock(return_value=existing_vid)  # duplicate found

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="already voted"),
        ):
            await verification_service.submit_vote(
                vid, "did:agentx:repeat-voter",
                VerificationVoteCreate(vote="approve"),
            )

    @pytest.mark.asyncio
    async def test_minimum_vote_power_is_1(self):
        """Agents with no stake should get vote_power = 1.0 (min power floor)."""
        vid         = uuid4()
        agent_id    = uuid4()
        v           = _verification_row(verification_id=vid, status="active",
                                        requester_did="did:agentx:creator",
                                        vote_count=0, required_votes=10)
        verifier_row = {"agent_id": agent_id, "trust_score": 0.0}
        # vote_row reflects what was actually stored: vote_power=1.0 (the floor)
        vote_row     = {
            "vote_id":         uuid4(),
            "verification_id": vid,
            "verifier_did":    "did:agentx:no-stake-verifier",
            "vote":            "approve",
            "vote_power":      1.0,
            "comment":         None,
            "created_at":      _now(),
        }
        updated_v    = {"vote_count": 1, "required_votes": 10}

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[v, verifier_row, vote_row, updated_v])
        conn.fetchval = AsyncMock(side_effect=[None, 0])  # dup check=None, stake=0
        conn.execute  = AsyncMock()

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.verification_service.publish_event", new=AsyncMock()),
        ):
            result = await verification_service.submit_vote(
                vid, "did:agentx:no-stake-verifier",
                VerificationVoteCreate(vote="approve"),
            )

        assert result.vote_power == 1.0


# -- calculate_consensus ------------------------------------------------------

class TestCalculateConsensus:

    @pytest.mark.asyncio
    async def test_returns_none_outcome_when_insufficient_votes(self):
        row = {
            "verification_id":     uuid4(),
            "status":              "active",
            "required_votes":      3,
            "consensus_threshold": 0.6,
            "yes_power":           2.0,
            "no_power":            0.0,
            "vote_count":          1,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.verification_service.get_db", return_value=_tx_context(conn)):
            result = await verification_service.calculate_consensus(row["verification_id"])

        assert result.outcome is None
        assert result.vote_count == 1

    @pytest.mark.asyncio
    async def test_verified_when_yes_majority(self):
        row = {
            "verification_id":     uuid4(),
            "status":              "active",
            "required_votes":      3,
            "consensus_threshold": 0.6,
            "yes_power":           8.0,
            "no_power":            2.0,
            "vote_count":          3,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.verification_service.get_db", return_value=_tx_context(conn)):
            result = await verification_service.calculate_consensus(row["verification_id"])

        assert result.outcome == "verified"
        assert result.yes_ratio == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_failed_when_no_majority(self):
        row = {
            "verification_id":     uuid4(),
            "status":              "active",
            "required_votes":      3,
            "consensus_threshold": 0.6,
            "yes_power":           2.0,
            "no_power":            8.0,
            "vote_count":          3,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.verification_service.get_db", return_value=_tx_context(conn)):
            result = await verification_service.calculate_consensus(row["verification_id"])

        assert result.outcome == "failed"

    @pytest.mark.asyncio
    async def test_raises_if_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.verification_service.get_db", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await verification_service.calculate_consensus(uuid4())

    @pytest.mark.asyncio
    async def test_yes_ratio_is_zero_when_no_votes(self):
        row = {
            "verification_id":     uuid4(),
            "status":              "active",
            "required_votes":      3,
            "consensus_threshold": 0.6,
            "yes_power":           0.0,
            "no_power":            0.0,
            "vote_count":          0,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.verification_service.get_db", return_value=_tx_context(conn)):
            result = await verification_service.calculate_consensus(row["verification_id"])

        assert result.yes_ratio == 0.0
        assert result.outcome is None


# -- finalize_verification ----------------------------------------------------

class TestFinalizeVerification:

    @pytest.mark.asyncio
    async def test_finalizes_as_verified(self):
        vid = uuid4()
        v   = _verification_row(
            verification_id=vid, status="active",
            yes_power=8.0, no_power=2.0, consensus_threshold=0.6,
        )
        updated = _verification_row(verification_id=vid, status="verified",
                                    yes_power=8.0, no_power=2.0, finalized_at=_now())

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            v,       # initial fetch
            updated, # UPDATE RETURNING
            {"reward_pool": 0},  # _distribute_rewards pool check
        ])
        conn.fetch   = AsyncMock(return_value=[])  # no correct voters
        conn.execute = AsyncMock()

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.verification_service.publish_event", new=AsyncMock()),
        ):
            result = await verification_service.finalize_verification(vid)

        assert result.status == "verified"
        assert result.finalized_at is not None

    @pytest.mark.asyncio
    async def test_finalizes_as_failed(self):
        vid = uuid4()
        v   = _verification_row(
            verification_id=vid, status="active",
            yes_power=1.0, no_power=9.0, consensus_threshold=0.6,
        )
        updated = _verification_row(verification_id=vid, status="failed",
                                    yes_power=1.0, no_power=9.0, finalized_at=_now())

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[v, updated, {"reward_pool": 0}])
        conn.fetch    = AsyncMock(return_value=[])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.verification_service.publish_event", new=AsyncMock()),
        ):
            result = await verification_service.finalize_verification(vid)

        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_idempotent_if_already_verified(self):
        vid = uuid4()
        v   = _verification_row(verification_id=vid, status="verified", finalized_at=_now())
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=v)

        with patch("src.services.verification_service.transaction", return_value=_tx_context(conn)):
            result = await verification_service.finalize_verification(vid)

        assert result.status == "verified"
        # No UPDATE should have been executed
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotent_if_already_failed(self):
        vid = uuid4()
        v   = _verification_row(verification_id=vid, status="failed", finalized_at=_now())
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=v)

        with patch("src.services.verification_service.transaction", return_value=_tx_context(conn)):
            result = await verification_service.finalize_verification(vid)

        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_raises_if_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await verification_service.finalize_verification(uuid4())

    @pytest.mark.asyncio
    async def test_raises_if_pending(self):
        v = _verification_row(status="pending")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=v)

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="[Aa]ctivated|pending"),
        ):
            await verification_service.finalize_verification(v["verification_id"])

    @pytest.mark.asyncio
    async def test_publishes_contract_verified_event(self):
        vid = uuid4()
        v   = _verification_row(
            verification_id=vid, status="active",
            yes_power=9.0, no_power=1.0, consensus_threshold=0.6,
        )
        updated = _verification_row(verification_id=vid, status="verified", finalized_at=_now())

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[v, updated, {"reward_pool": 0}])
        conn.fetch    = AsyncMock(return_value=[])
        conn.execute  = AsyncMock()

        published = []

        async def _capture_event(event_type, payload, **kwargs):
            published.append(event_type)

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.verification_service.publish_event", side_effect=_capture_event),
        ):
            await verification_service.finalize_verification(vid)

        from src.events.types import EventType
        assert EventType.CONTRACT_VERIFIED in published

    @pytest.mark.asyncio
    async def test_publishes_verification_failed_event(self):
        vid = uuid4()
        v   = _verification_row(
            verification_id=vid, status="active",
            yes_power=1.0, no_power=9.0, consensus_threshold=0.6,
        )
        updated = _verification_row(verification_id=vid, status="failed", finalized_at=_now())

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[v, updated, {"reward_pool": 0}])
        conn.fetch    = AsyncMock(return_value=[])
        conn.execute  = AsyncMock()

        published = []

        async def _capture_event(event_type, payload, **kwargs):
            published.append(event_type)

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.verification_service.publish_event", side_effect=_capture_event),
        ):
            await verification_service.finalize_verification(vid)

        from src.events.types import EventType
        assert EventType.VERIFICATION_FAILED in published

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_raise(self):
        vid = uuid4()
        v   = _verification_row(
            verification_id=vid, status="active",
            yes_power=8.0, no_power=2.0, consensus_threshold=0.6,
        )
        updated = _verification_row(verification_id=vid, status="verified", finalized_at=_now())

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[v, updated, {"reward_pool": 0}])
        conn.fetch    = AsyncMock(return_value=[])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.verification_service.transaction", return_value=_tx_context(conn)),
            patch(
                "src.services.verification_service.publish_event",
                new=AsyncMock(side_effect=Exception("redis down")),
            ),
        ):
            result = await verification_service.finalize_verification(vid)

        assert result.status == "verified"


# -- get_verification ---------------------------------------------------------

class TestGetVerification:

    @pytest.mark.asyncio
    async def test_returns_verification(self):
        vid = uuid4()
        row = _verification_row(verification_id=vid, status="active")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.verification_service.get_db", return_value=_tx_context(conn)):
            result = await verification_service.get_verification(vid)

        assert result.verification_id == vid
        assert result.status == "active"

    @pytest.mark.asyncio
    async def test_raises_if_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.verification_service.get_db", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await verification_service.get_verification(uuid4())


# -- list_pending_verifications -----------------------------------------------

class TestListPendingVerifications:

    @pytest.mark.asyncio
    async def test_returns_pending_and_active(self):
        rows = [
            _verification_row(status="pending"),
            _verification_row(status="active"),
        ]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.verification_service.get_db", return_value=_tx_context(conn)):
            result = await verification_service.list_pending_verifications()

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_none(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.verification_service.get_db", return_value=_tx_context(conn)):
            result = await verification_service.list_pending_verifications()

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_correct_model_fields(self):
        vid = uuid4()
        row = _verification_row(verification_id=vid, status="active", required_votes=5)
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[row])

        with patch("src.services.verification_service.get_db", return_value=_tx_context(conn)):
            result = await verification_service.list_pending_verifications()

        assert result[0].required_votes == 5
        assert result[0].verification_id == vid
