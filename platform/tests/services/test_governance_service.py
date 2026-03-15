"""
Tests: src/services/governance_service.py
Phase 9 — Governance Layer

Covers:
  create_proposal()       — resolves DID->agent_id, inserts proposal, publishes event
  list_proposals()        — returns proposals filtered by status
  vote_on_proposal()      — validates, computes power, inserts vote, updates tallies
  calculate_vote_power()  — returns stake x trust_score
  finalize_proposal()     — transitions active -> passed/failed
  execute_proposal()      — transitions passed -> executed
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.models.governance import ProposalCreate, VoteRequest
from src.services import governance_service


# -- Helpers ------------------------------------------------------------------

def _tx_context(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__  = AsyncMock(return_value=None)
    return ctx


def _now():
    return datetime.now(UTC)


def _future(days: int = 7):
    return datetime.now(UTC) + timedelta(days=days)


def _past(days: int = 1):
    return datetime.now(UTC) - timedelta(days=days)


def _agent_lookup(agent_id=None, trust_score=0.8):
    return {
        "agent_id":    agent_id or uuid4(),
        "trust_score": trust_score,
    }


def _proposal_row(
    proposal_id=None,
    status="active",
    yes_power=0,
    no_power=0,
    voting_ends_at=None,
    proposer_id=None,
):
    return {
        "proposal_id":    proposal_id or uuid4(),
        "proposer_did":   "did:agentx:proposer",
        "proposer_id":    proposer_id or uuid4(),
        "title":          "Test Proposal",
        "description":    "A proposal for testing",
        "proposal_type":  "general",
        "status":         status,
        "payload":        None,
        "yes_power":      yes_power,
        "no_power":       no_power,
        "voting_ends_at": voting_ends_at or _future(),
        "created_at":     _now(),
    }


def _vote_row(vote_id=None, proposal_id=None, voter_did=None, vote="yes", vote_power=100.0):
    return {
        "vote_id":     vote_id or uuid4(),
        "proposal_id": proposal_id or uuid4(),
        "voter_did":   voter_did or "did:agentx:voter",
        "vote":        vote,
        "vote_power":  vote_power,
        "created_at":  _now(),
    }


# -- create_proposal ----------------------------------------------------------

class TestCreateProposal:

    @pytest.mark.asyncio
    async def test_creates_proposal_and_returns_response(self):
        caller_did = "did:agentx:creator"
        data = ProposalCreate(title="My Proposal", description="Details here", voting_days=5)

        agent_row = _agent_lookup()
        prop_row  = _proposal_row(proposer_id=agent_row["agent_id"])

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[agent_row, prop_row])

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.governance_service.publish_event", new=AsyncMock()),
        ):
            result = await governance_service.create_proposal(caller_did, data)

        assert result.title == prop_row["title"]
        assert result.status == "active"

    @pytest.mark.asyncio
    async def test_voting_ends_at_matches_voting_days(self):
        caller_did   = "did:agentx:creator"
        data         = ProposalCreate(title="T", description="D", voting_days=3)
        expected_end = _future(days=3)
        agent_row    = _agent_lookup()
        prop_row     = _proposal_row(voting_ends_at=expected_end)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[agent_row, prop_row])

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.governance_service.publish_event", new=AsyncMock()),
        ):
            result = await governance_service.create_proposal(caller_did, data)

        diff = abs((result.voting_ends_at - expected_end).total_seconds())
        assert diff < 5

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_raise(self):
        data      = ProposalCreate(title="T", description="D")
        agent_row = _agent_lookup()
        prop_row  = _proposal_row()

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[agent_row, prop_row])

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            patch(
                "src.services.governance_service.publish_event",
                new=AsyncMock(side_effect=Exception("redis down")),
            ),
        ):
            result = await governance_service.create_proposal("did:x:a", data)

        assert result.proposal_id is not None

    @pytest.mark.asyncio
    async def test_payload_round_tripped_from_json_string(self):
        agent_row = _agent_lookup()
        prop_row  = _proposal_row()
        prop_row["payload"] = '{"key": "value"}'

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[agent_row, prop_row])

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.governance_service.publish_event", new=AsyncMock()),
        ):
            result = await governance_service.create_proposal(
                "did:x:a",
                ProposalCreate(title="T", description="D", payload={"key": "value"}),
            )

        assert result.payload == {"key": "value"}


# -- list_proposals -----------------------------------------------------------

class TestListProposals:

    @pytest.mark.asyncio
    async def test_returns_active_proposals(self):
        rows = [_proposal_row(), _proposal_row()]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.governance_service.get_db", return_value=_tx_context(conn)):
            result = await governance_service.list_proposals(status="active")

        assert len(result) == 2
        assert all(p.status == "active" for p in result)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_none(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.governance_service.get_db", return_value=_tx_context(conn)):
            result = await governance_service.list_proposals(status="passed")

        assert result == []

    @pytest.mark.asyncio
    async def test_no_status_filter_returns_all(self):
        rows = [_proposal_row(status="active"), _proposal_row(status="passed")]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.governance_service.get_db", return_value=_tx_context(conn)):
            result = await governance_service.list_proposals(status=None)

        assert len(result) == 2


# -- calculate_vote_power -----------------------------------------------------

class TestCalculateVotePower:

    @pytest.mark.asyncio
    async def test_returns_stake_times_trust(self):
        agent_row = _agent_lookup(trust_score=0.8)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=agent_row)
        conn.fetchval = AsyncMock(return_value=500)

        with patch("src.services.governance_service.get_db", return_value=_tx_context(conn)):
            power = await governance_service.calculate_vote_power("did:agentx:voter")

        assert power == pytest.approx(400.0)

    @pytest.mark.asyncio
    async def test_returns_zero_when_agent_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("src.services.governance_service.get_db", return_value=_tx_context(conn)):
            power = await governance_service.calculate_vote_power("did:x:ghost")

        assert power == 0.0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_stake(self):
        agent_row = _agent_lookup(trust_score=1.0)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=agent_row)
        conn.fetchval = AsyncMock(return_value=0)

        with patch("src.services.governance_service.get_db", return_value=_tx_context(conn)):
            power = await governance_service.calculate_vote_power("did:x:a")

        assert power == 0.0


# -- vote_on_proposal ---------------------------------------------------------

class TestVoteOnProposal:

    @pytest.mark.asyncio
    async def test_yes_vote_recorded_and_updates_tally(self):
        proposal_id = uuid4()
        voter_row   = _agent_lookup(trust_score=0.8)
        proposal    = _proposal_row(proposal_id=proposal_id, status="active")
        vote_r      = _vote_row(proposal_id=proposal_id, vote="yes", vote_power=400.0)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[voter_row, proposal, vote_r])
        conn.fetchval = AsyncMock(side_effect=[None, 500])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.governance_service.publish_event", new=AsyncMock()),
        ):
            result = await governance_service.vote_on_proposal(
                "did:agentx:voter",
                VoteRequest(proposal_id=proposal_id, vote="yes"),
            )

        assert result.vote == "yes"
        assert result.vote_power == pytest.approx(400.0)
        conn.execute.assert_awaited()

    @pytest.mark.asyncio
    async def test_no_vote_recorded(self):
        proposal_id = uuid4()
        voter_row   = _agent_lookup(trust_score=1.0)
        proposal    = _proposal_row(proposal_id=proposal_id, status="active")
        vote_r      = _vote_row(proposal_id=proposal_id, vote="no", vote_power=200.0)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[voter_row, proposal, vote_r])
        conn.fetchval = AsyncMock(side_effect=[None, 200])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.governance_service.publish_event", new=AsyncMock()),
        ):
            result = await governance_service.vote_on_proposal(
                "did:agentx:voter",
                VoteRequest(proposal_id=proposal_id, vote="no"),
            )

        assert result.vote == "no"

    @pytest.mark.asyncio
    async def test_abstain_does_not_update_tallies(self):
        proposal_id = uuid4()
        voter_row   = _agent_lookup(trust_score=1.0)
        proposal    = _proposal_row(proposal_id=proposal_id, status="active")
        vote_r      = _vote_row(proposal_id=proposal_id, vote="abstain", vote_power=50.0)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[voter_row, proposal, vote_r])
        conn.fetchval = AsyncMock(side_effect=[None, 50])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.governance_service.publish_event", new=AsyncMock()),
        ):
            result = await governance_service.vote_on_proposal(
                "did:agentx:voter",
                VoteRequest(proposal_id=proposal_id, vote="abstain"),
            )

        assert result.vote == "abstain"
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_if_agent_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Agent not found"),
        ):
            await governance_service.vote_on_proposal(
                "did:x:ghost",
                VoteRequest(proposal_id=uuid4(), vote="yes"),
            )

    @pytest.mark.asyncio
    async def test_raises_if_proposal_not_found(self):
        voter_row = _agent_lookup()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[voter_row, None])

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="[Pp]roposal not found"),
        ):
            await governance_service.vote_on_proposal(
                "did:x:a",
                VoteRequest(proposal_id=uuid4(), vote="yes"),
            )

    @pytest.mark.asyncio
    async def test_raises_if_proposal_not_active(self):
        voter_row = _agent_lookup()
        proposal  = _proposal_row(status="passed")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[voter_row, proposal])

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not active"),
        ):
            await governance_service.vote_on_proposal(
                "did:x:a",
                VoteRequest(proposal_id=proposal["proposal_id"], vote="yes"),
            )

    @pytest.mark.asyncio
    async def test_raises_if_voting_period_closed(self):
        voter_row = _agent_lookup()
        proposal  = _proposal_row(status="active", voting_ends_at=_past(days=1))
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[voter_row, proposal])

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="[Vv]oting period"),
        ):
            await governance_service.vote_on_proposal(
                "did:x:a",
                VoteRequest(proposal_id=proposal["proposal_id"], vote="yes"),
            )

    @pytest.mark.asyncio
    async def test_raises_if_already_voted(self):
        voter_row = _agent_lookup()
        proposal  = _proposal_row(status="active")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[voter_row, proposal])
        conn.fetchval = AsyncMock(return_value=uuid4())  # existing vote found

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="already voted"),
        ):
            await governance_service.vote_on_proposal(
                "did:x:a",
                VoteRequest(proposal_id=proposal["proposal_id"], vote="yes"),
            )


# -- finalize_proposal --------------------------------------------------------

class TestFinalizeProposal:

    @pytest.mark.asyncio
    async def test_yes_majority_marks_passed(self):
        pid     = uuid4()
        summary = _proposal_row(proposal_id=pid, status="active", yes_power=300, no_power=100)
        updated = _proposal_row(proposal_id=pid, status="passed", yes_power=300, no_power=100)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[summary, updated])

        with patch("src.services.governance_service.transaction", return_value=_tx_context(conn)):
            result = await governance_service.finalize_proposal(pid)

        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_no_majority_marks_failed(self):
        pid     = uuid4()
        summary = _proposal_row(proposal_id=pid, status="active", yes_power=50, no_power=200)
        updated = _proposal_row(proposal_id=pid, status="failed", yes_power=50, no_power=200)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[summary, updated])

        with patch("src.services.governance_service.transaction", return_value=_tx_context(conn)):
            result = await governance_service.finalize_proposal(pid)

        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_already_finalized_is_idempotent(self):
        pid      = uuid4()
        existing = _proposal_row(proposal_id=pid, status="passed")
        full_row = _proposal_row(proposal_id=pid, status="passed")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[existing, full_row])

        with patch("src.services.governance_service.transaction", return_value=_tx_context(conn)):
            result = await governance_service.finalize_proposal(pid)

        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_raises_if_proposal_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await governance_service.finalize_proposal(uuid4())


# -- execute_proposal ---------------------------------------------------------

class TestExecuteProposal:

    @pytest.mark.asyncio
    async def test_passed_proposal_becomes_executed(self):
        pid        = uuid4()
        status_row = {"status": "passed"}
        updated    = _proposal_row(proposal_id=pid, status="executed")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[status_row, updated])

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.governance_service.publish_event", new=AsyncMock()),
        ):
            result = await governance_service.execute_proposal(pid)

        assert result.status == "executed"

    @pytest.mark.asyncio
    async def test_raises_if_not_passed(self):
        pid        = uuid4()
        status_row = {"status": "active"}

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=status_row)

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="cannot be executed"),
        ):
            await governance_service.execute_proposal(pid)

    @pytest.mark.asyncio
    async def test_raises_if_proposal_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await governance_service.execute_proposal(uuid4())

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_raise(self):
        pid        = uuid4()
        status_row = {"status": "passed"}
        updated    = _proposal_row(proposal_id=pid, status="executed")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[status_row, updated])

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            patch(
                "src.services.governance_service.publish_event",
                new=AsyncMock(side_effect=Exception("redis down")),
            ),
        ):
            result = await governance_service.execute_proposal(pid)

        assert result.status == "executed"
