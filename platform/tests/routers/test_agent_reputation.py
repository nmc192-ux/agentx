from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport

from src.main import app
from src.models.reputation import AgentTrustScoreResponse, ReputationHistoryEntry


@pytest.fixture
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_get_agent_trust_returns_score(client):
    agent_id = uuid4()
    trust = AgentTrustScoreResponse(
        agent_id=agent_id,
        current_score=0.77,
        last_updated=datetime.now(UTC),
    )

    with patch("src.routers.agents.get_agent_trust", new=AsyncMock(return_value=trust)):
        response = await client.get(f"/agents/{agent_id}/trust")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_id"] == str(agent_id)
    assert payload["current_score"] == 0.77


@pytest.mark.asyncio
async def test_get_agent_reputation_history_returns_entries(client):
    agent_id = uuid4()
    history_entry = ReputationHistoryEntry(
        history_id=uuid4(),
        agent_id=agent_id,
        event_id=uuid4(),
        event_type="task_success",
        event_weight=0.05,
        score_before=0.5,
        score_after=0.55,
        metadata={"source": "test"},
        created_at=datetime.now(UTC),
    )

    with patch(
        "src.routers.agents.get_reputation_history",
        new=AsyncMock(return_value=[history_entry]),
    ):
        response = await client.get(f"/agents/{agent_id}/reputation-history")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["event_type"] == "task_success"
    assert payload[0]["score_after"] == 0.55
