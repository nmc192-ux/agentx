"""
Tests: src/services/consensus_service.py
Phase 1 Enhanced Social Layer — Enhanced Consensus Engine

Covers:
  open_debate()
  add_statement()
  get_debate()
  compute_consensus()
  advance_round()
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services.consensus_service import (
    open_debate,
    add_statement,
    get_debate,
    compute_consensus,
    advance_round,
)
from src.models.consensus import StatementCreate, StatementPosition


def _round_row(**overrides):
    defaults = {
        "round_id": uuid4(),
        "proposal_id": uuid4(),
        "round_number": 1,
        "phase": "OPENING",
        "starts_at": datetime.now(UTC),
        "ends_at": datetime.now(UTC) + timedelta(hours=24),
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return defaults


def _statement_row(**overrides):
    defaults = {
        "statement_id": uuid4(),
        "round_id": uuid4(),
        "author_did": "did:agentx:atlas-001",
        "position": "FOR",
        "content": "I support this proposal because...",
        "evidence_refs": json.dumps([]),
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return defaults


def _snapshot_row(**overrides):
    defaults = {
        "snapshot_id": uuid4(),
        "proposal_id": uuid4(),
        "vote_tally": json.dumps({"FOR": 3, "AGAINST": 1, "ABSTAIN": 1}),
        "weighted_tally": json.dumps({"FOR": 2.5, "AGAINST": 0.8, "ABSTAIN": 0.5}),
        "total_voters": 5,
        "quorum_met": True,
        "quorum_threshold": 0.33,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return defaults


class _FakeConn:
    def __init__(self, rows=None, fetchrow_val=None, fetchval_val=None, execute_val="INSERT 0 1"):
        self._rows = rows or []
        self._fetchrow_val = fetchrow_val
        self._fetchval_val = fetchval_val
        self._execute_val = execute_val

    async def fetch(self, *a, **kw):
        return [MagicMock(**{k: v for k, v in r.items()}, __getitem__=lambda s, k: r[k]) for r in self._rows]

    async def fetchrow(self, *a, **kw):
        if self._fetchrow_val is not None:
            r = self._fetchrow_val
            return MagicMock(**{k: v for k, v in r.items()}, __getitem__=lambda s, k: r[k])
        return None

    async def fetchval(self, *a, **kw):
        return self._fetchval_val

    async def execute(self, *a, **kw):
        return self._execute_val


class _TxCtx:
    def __init__(self, conn):
        self.conn = conn
    async def __aenter__(self):
        return self.conn
    async def __aexit__(self, *a):
        pass


class _DbCtx(_TxCtx):
    pass


@pytest.mark.asyncio
async def test_open_debate_not_proposal():
    post_row = {"post_id": uuid4(), "post_type": "REQUEST"}
    conn = _FakeConn(fetchrow_val=post_row, fetchval_val=0)

    with patch("src.services.consensus_service.transaction", return_value=_TxCtx(conn)):
        with pytest.raises(ValueError, match="not a PROPOSAL"):
            await open_debate(uuid4())


@pytest.mark.asyncio
async def test_open_debate_success():
    proposal_id = uuid4()
    post_row = {"post_id": proposal_id, "post_type": "PROPOSAL"}
    round_row = _round_row(proposal_id=proposal_id)

    call_count = {"fetchrow": 0}

    async def mock_fetchrow(sql, *args, **kw):
        call_count["fetchrow"] += 1
        if call_count["fetchrow"] == 1:
            return MagicMock(**post_row, __getitem__=lambda s, k: post_row[k])
        return MagicMock(**round_row, __getitem__=lambda s, k: round_row[k])

    conn = _FakeConn(fetchval_val=0)
    conn.fetchrow = mock_fetchrow

    with patch("src.services.consensus_service.transaction", return_value=_TxCtx(conn)):
        result = await open_debate(proposal_id)

    assert result.proposal_id == proposal_id
    assert result.phase == "OPENING"


@pytest.mark.asyncio
async def test_add_statement_voting_phase():
    round_data = {"round_id": uuid4(), "phase": "VOTING", "ends_at": None}
    conn = _FakeConn(fetchrow_val=round_data)

    with patch("src.services.consensus_service.transaction", return_value=_TxCtx(conn)):
        with pytest.raises(ValueError, match="Cannot add statements during VOTING"):
            await add_statement(
                uuid4(),
                "did:agentx:atlas-001",
                StatementCreate(position=StatementPosition.FOR, content="I support this because of strong evidence"),
            )


@pytest.mark.asyncio
async def test_get_debate_empty():
    conn = _FakeConn(rows=[], fetchrow_val=None)

    with patch("src.services.consensus_service.get_db", return_value=_DbCtx(conn)):
        result = await get_debate(uuid4())

    assert result.rounds == []
    assert result.statements == []
    assert result.snapshot is None


@pytest.mark.asyncio
async def test_advance_round_no_rounds():
    conn = _FakeConn(fetchrow_val=None)

    with patch("src.services.consensus_service.transaction", return_value=_TxCtx(conn)):
        with pytest.raises(ValueError, match="No debate rounds exist"):
            await advance_round(uuid4())


@pytest.mark.asyncio
async def test_advance_round_already_voting():
    round_data = _round_row(phase="VOTING")
    conn = _FakeConn(fetchrow_val=round_data)

    with patch("src.services.consensus_service.transaction", return_value=_TxCtx(conn)):
        with pytest.raises(ValueError, match="already in the final phase"):
            await advance_round(uuid4())
