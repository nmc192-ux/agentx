from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services.reputation import recalculate_agent_trust, record_event


def _tx_context(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


@pytest.mark.asyncio
async def test_record_event_persists_normalized_weight():
    agent_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"agent_id": agent_id})
    conn.execute = AsyncMock()

    with patch("src.services.reputation.transaction", return_value=_tx_context(conn)):
        await record_event(
            "did:agentx:atlas-001",
            "TASK_SUCCESS",
            {"source": "unit-test"},
        )

    conn.fetchrow.assert_awaited_once()
    execute_args = conn.execute.await_args.args
    assert execute_args[1] == agent_id
    assert execute_args[2] == "did:agentx:atlas-001"
    assert execute_args[3] == "task_success"
    assert execute_args[4] == 0.05


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
    read_conn.fetch = AsyncMock(return_value=[{"agent_did": "did:agentx:atlas-001"}])

    with (
        patch("src.services.reputation.transaction", return_value=_tx_context(conn)),
        patch("src.services.reputation.get_db", return_value=_tx_context(read_conn)),
        patch("src.services.reputation.cache_delete", new=AsyncMock()) as mock_cache_delete,
    ):
        result = await recalculate_agent_trust()

    assert result == {"processed_events": 2, "updated_agents": 1}
    assert conn.execute.await_count == 6
    mock_cache_delete.assert_awaited_once()
