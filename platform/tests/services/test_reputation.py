from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services.reputation import (
    DUPLICATE,
    NO_COUNTERPARTY,
    RECORDED,
    recalculate_agent_trust,
    record_event,
    record_message_reply,
    record_task_completed,
    record_task_failed,
    record_verification_outcome,
)


def _tx_context(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


@pytest.mark.asyncio
async def test_record_event_persists_normalized_weight_and_key():
    """A negative event: no counterparty and no caps, but still keyed."""
    agent_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"agent_id": agent_id})
    conn.fetchval = AsyncMock(return_value=uuid4())     # INSERT … RETURNING event_id

    with patch("src.services.reputation.transaction", return_value=_tx_context(conn)):
        outcome = await record_event(
            "did:agentx:atlas-001",
            "TASK_FAILED",
            {"source": "unit-test"},
            dedupe_key="task_failed:t1",
        )

    assert outcome == RECORDED
    insert_args = conn.fetchval.await_args.args
    assert "ON CONFLICT (dedupe_key)" in insert_args[0]
    assert insert_args[1] == agent_id
    assert insert_args[2] == "did:agentx:atlas-001"
    assert insert_args[3] == "task_failed"
    assert insert_args[4] == -0.10
    assert insert_args[6] == "task_failed:t1"


@pytest.mark.asyncio
async def test_record_event_reports_a_duplicate_key():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"agent_id": uuid4()})
    conn.fetchval = AsyncMock(return_value=None)        # ON CONFLICT DO NOTHING

    with patch("src.services.reputation.transaction", return_value=_tx_context(conn)):
        outcome = await record_event(
            "did:agentx:atlas-001", "task_failed", dedupe_key="task_failed:t1",
        )

    assert outcome == DUPLICATE


@pytest.mark.asyncio
@pytest.mark.parametrize("counterparty", [None, "did:agentx:atlas-001"])
async def test_positive_event_without_another_agent_is_not_recorded(counterparty):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"agent_id": uuid4()})

    with patch("src.services.reputation.transaction", return_value=_tx_context(conn)):
        outcome = await record_event(
            "did:agentx:atlas-001", "task_completed",
            dedupe_key="task_completed:t1", counterparty_did=counterparty,
        )

    assert outcome == NO_COUNTERPARTY
    conn.fetchval.assert_not_awaited()                   # nothing looked up, nothing written


@pytest.mark.asyncio
async def test_record_event_needs_a_key_and_a_known_type():
    with pytest.raises(ValueError, match="dedupe_key"):
        await record_event("did:agentx:atlas-001", "task_failed", dedupe_key="")
    with pytest.raises(ValueError, match="Unsupported"):
        await record_event("did:agentx:atlas-001", "made_up", dedupe_key="k")
    with pytest.raises(TypeError):
        await record_event("did:agentx:atlas-001", "task_failed")   # the key is required


@pytest.mark.asyncio
async def test_reporting_functions_never_raise():
    """They run after the caller's transaction has committed: a broken trust
    path must not turn a finished task or a sent message into a 500."""
    boom = MagicMock(side_effect=RuntimeError("database down"))
    with (
        patch("src.services.reputation.get_db", new=boom),
        patch("src.services.reputation.transaction", new=boom),
    ):
        assert await record_task_completed(uuid4()) == "error"
        assert await record_task_failed(uuid4(), reported_by_did="did:agentx:a-001") == "error"
        assert await record_message_reply("did:agentx:a-001", "did:agentx:b-001", uuid4()) == "error"
        assert await record_verification_outcome(uuid4()) == {}
    assert await record_task_completed("not-a-uuid") == "unknown_task"


@pytest.mark.asyncio
async def test_recalculate_agent_trust_updates_scores_and_history():
    agent_id = uuid4()
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "event_id": uuid4(),
                "agent_id": agent_id,
                "agent_did": "did:agentx:atlas-001",
                "event_type": "task_success",
                "event_weight": 0.05,
                "created_at": datetime.now(UTC),
            },
            {
                "event_id": uuid4(),
                "agent_id": agent_id,
                "agent_did": "did:agentx:atlas-001",
                "event_type": "peer_validation",
                "event_weight": 0.03,
                "created_at": datetime.now(UTC),
            },
        ]
    )
    conn.fetchval = AsyncMock(return_value=0.5)
    conn.execute = AsyncMock()

    read_conn = AsyncMock()
    read_conn.fetch = AsyncMock(
        return_value=[{"agent_id": agent_id, "agent_did": "did:agentx:atlas-001"}]
    )

    with (
        patch("src.services.reputation.transaction", return_value=_tx_context(conn)),
        patch("src.services.reputation.get_db", return_value=_tx_context(read_conn)),
        patch("src.services.reputation.cache_delete", new=AsyncMock()) as mock_cache_delete,
    ):
        result = await recalculate_agent_trust()

    assert result == {"processed_events": 2, "updated_agents": 1}
    # 1 advisory lock + 3 writes per event
    assert conn.execute.await_count == 7
    # The score moved: both the trust cache and the profile cache are cleared.
    assert mock_cache_delete.await_count == 2
