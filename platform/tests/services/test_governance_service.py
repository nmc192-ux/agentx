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


def _locked_proposal(proposal_id=None, status="active", voting_closed=False):
    """What the `SELECT … FOR UPDATE` in vote / finalize returns."""
    return {
        "proposal_id":   proposal_id or uuid4(),
        "status":        status,
        "voting_closed": voting_closed,
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
        conn.fetchval = AsyncMock(return_value=0)   # open proposals by this agent

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
        conn.fetchval = AsyncMock(return_value=0)   # open proposals by this agent

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
        conn.fetchval = AsyncMock(return_value=0)   # open proposals by this agent

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
        conn.fetchval = AsyncMock(return_value=0)   # open proposals by this agent

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
        proposal    = _locked_proposal(proposal_id)
        vote_r      = _vote_row(proposal_id=proposal_id, vote="yes", vote_power=400.0)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[voter_row, proposal, vote_r])
        conn.fetchval = AsyncMock(return_value=None)          # no earlier vote
        conn.fetch    = AsyncMock(return_value=[{"amount": 500}])
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
        # proposal row and the voter's stake rows are locked; weight = 500 × 0.8
        assert "FOR UPDATE" in conn.fetchrow.await_args_list[1].args[0]
        assert "FOR UPDATE" in conn.fetch.await_args_list[0].args[0]
        assert conn.fetchrow.await_args_list[2].args[-1] == pytest.approx(400.0)

    @pytest.mark.asyncio
    async def test_no_vote_recorded(self):
        proposal_id = uuid4()
        voter_row   = _agent_lookup(trust_score=1.0)
        proposal    = _locked_proposal(proposal_id)
        vote_r      = _vote_row(proposal_id=proposal_id, vote="no", vote_power=200.0)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[voter_row, proposal, vote_r])
        conn.fetchval = AsyncMock(return_value=None)          # no earlier vote
        conn.fetch    = AsyncMock(return_value=[{"amount": 200}])
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
        proposal    = _locked_proposal(proposal_id)
        vote_r      = _vote_row(proposal_id=proposal_id, vote="abstain", vote_power=50.0)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[voter_row, proposal, vote_r])
        conn.fetchval = AsyncMock(return_value=None)          # no earlier vote
        conn.fetch    = AsyncMock(return_value=[{"amount": 50}])
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
        proposal  = _locked_proposal(status="passed")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[voter_row, proposal])

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(governance_service.GovernanceConflictError, match="not active"),
        ):
            await governance_service.vote_on_proposal(
                "did:x:a",
                VoteRequest(proposal_id=proposal["proposal_id"], vote="yes"),
            )

    @pytest.mark.asyncio
    async def test_raises_if_voting_period_closed(self):
        voter_row = _agent_lookup()
        proposal  = _locked_proposal(status="active", voting_closed=True)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[voter_row, proposal])

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(governance_service.GovernanceConflictError, match="[Vv]oting period"),
        ):
            await governance_service.vote_on_proposal(
                "did:x:a",
                VoteRequest(proposal_id=proposal["proposal_id"], vote="yes"),
            )

    @pytest.mark.asyncio
    async def test_raises_if_already_voted(self):
        voter_row = _agent_lookup()
        proposal  = _locked_proposal()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[voter_row, proposal])
        conn.fetchval = AsyncMock(return_value=uuid4())  # existing vote found

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(governance_service.GovernanceConflictError, match="already voted"),
        ):
            await governance_service.vote_on_proposal(
                "did:x:a",
                VoteRequest(proposal_id=proposal["proposal_id"], vote="yes"),
            )


# -- finalize_proposal --------------------------------------------------------

def _tally(yes=0, no=0, abstain=0):
    return {"yes_power": yes, "no_power": no, "abstain_power": abstain}


_RULES = [
    {"name": "quorum_threshold", "value": "100"},
    {"name": "pass_threshold", "value": "0.5"},
]


class TestFinalizeProposal:

    async def _finalize(self, locked, tally, updated, rules=_RULES):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[r for r in (locked, tally, updated) if r is not None])
        conn.fetch = AsyncMock(return_value=rules)
        with patch("src.services.governance_service.transaction", return_value=_tx_context(conn)):
            result = await governance_service.finalize_proposal(locked["proposal_id"])
        return result, conn

    @pytest.mark.asyncio
    async def test_yes_majority_marks_passed(self):
        pid     = uuid4()
        locked  = _locked_proposal(pid, voting_closed=True)
        updated = _proposal_row(proposal_id=pid, status="passed", yes_power=300, no_power=100)

        result, conn = await self._finalize(locked, _tally(yes=300, no=100), updated)

        assert result.status == "passed"
        assert "FOR UPDATE" in conn.fetchrow.await_args_list[0].args[0]
        update = conn.execute.await_args_list[0].args
        assert "status = 'active'" in update[0]      # only an open proposal is closed
        assert update[1] == "passed"

    @pytest.mark.asyncio
    async def test_no_majority_marks_failed(self):
        pid     = uuid4()
        locked  = _locked_proposal(pid, voting_closed=True)
        updated = _proposal_row(proposal_id=pid, status="failed", yes_power=50, no_power=200)

        result, conn = await self._finalize(locked, _tally(yes=50, no=200), updated)

        assert result.status == "failed"
        assert conn.execute.await_args_list[0].args[1] == "failed"

    @pytest.mark.asyncio
    async def test_below_quorum_marks_failed(self):
        pid     = uuid4()
        locked  = _locked_proposal(pid, voting_closed=True)
        updated = _proposal_row(proposal_id=pid, status="failed", yes_power=99)

        _, conn = await self._finalize(locked, _tally(yes=99), updated)

        assert conn.execute.await_args_list[0].args[1] == "failed"

    @pytest.mark.asyncio
    async def test_missing_rules_use_the_defaults(self):
        pid     = uuid4()
        locked  = _locked_proposal(pid, voting_closed=True)
        updated = _proposal_row(proposal_id=pid, status="failed", yes_power=99)

        _, conn = await self._finalize(locked, _tally(yes=99), updated, rules=[])

        assert conn.execute.await_args_list[0].args[1] == "failed"   # quorum 100 still applies

    @pytest.mark.asyncio
    async def test_refuses_while_voting_is_open(self):
        locked = _locked_proposal(voting_closed=False)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=locked)

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(governance_service.GovernanceConflictError, match="still open"),
        ):
            await governance_service.finalize_proposal(locked["proposal_id"])
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_finalized_is_idempotent(self):
        pid      = uuid4()
        existing = _locked_proposal(pid, status="passed", voting_closed=True)
        full_row = _proposal_row(proposal_id=pid, status="passed")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[existing, full_row])

        with patch("src.services.governance_service.transaction", return_value=_tx_context(conn)):
            result = await governance_service.finalize_proposal(pid)

        assert result.status == "passed"
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_if_proposal_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await governance_service.finalize_proposal(uuid4())


# -- decide_outcome -----------------------------------------------------------

class TestDecideOutcome:
    """quorum 100 (abstentions count), pass threshold 0.5 (strictly more)."""

    @pytest.mark.parametrize("yes, no, abstain, expected", [
        (300, 100, 0, "passed"),
        (51, 49, 0, "passed"),
        (50, 50, 0, "failed"),          # a tie
        (49, 51, 0, "failed"),
        (99, 0, 0, "failed"),           # one short of the quorum
        (99.999999, 0, 0, "failed"),
        (100, 0, 0, "passed"),
        (30, 0, 70, "passed"),          # abstentions carry the quorum
        (0, 0, 500, "failed"),          # nobody said yes or no
        (0, 0, 0, "failed"),
        (0.5, 0, 0, "failed"),          # the old rule ("yes > no") passed this
    ])
    def test_seeded_rules(self, yes, no, abstain, expected):
        from decimal import Decimal as D
        outcome = governance_service.decide_outcome(
            D(str(yes)), D(str(no)), D(str(abstain)), D("100"), D("0.5"),
        )
        assert outcome == expected

    def test_higher_pass_threshold(self):
        from decimal import Decimal as D
        decide = governance_service.decide_outcome
        assert decide(D("200"), D("100"), D("0"), D("100"), D("0.6667")) == "failed"
        assert decide(D("201"), D("100"), D("0"), D("100"), D("0.6667")) == "passed"


# -- create_proposal: the open-proposal cap -----------------------------------

class TestOpenProposalCap:

    @pytest.mark.asyncio
    async def test_refused_at_the_cap(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_agent_lookup())
        conn.fetchval = AsyncMock(return_value=governance_service.MAX_OPEN_PROPOSALS_PER_AGENT)

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(governance_service.GovernanceConflictError, match="limit"),
        ):
            await governance_service.create_proposal(
                "did:x:a", ProposalCreate(title="T", description="D"),
            )
        assert conn.fetchrow.await_count == 1        # nothing was inserted
        assert "FOR NO KEY UPDATE" in conn.fetchrow.await_args_list[0].args[0]

    @pytest.mark.asyncio
    async def test_unknown_agent_is_refused(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.governance_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Agent not found"),
        ):
            await governance_service.create_proposal(
                "did:x:ghost", ProposalCreate(title="T", description="D"),
            )


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
