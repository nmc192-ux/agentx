"""Tests: Agent directory and discovery service."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.services.agent_directory import (
    get_agent_profile,
    search_agents_by_capability,
    search_agents_by_reputation,
    search_agents_by_skill,
)
from src.services.trust_score import TrustScore


def _agent_row(agent_did: str, trust_score: float = 0.72) -> dict:
    return {
        "agent_did": agent_did,
        "display_name": "Atlas",
        "agent_type": "AUTONOMOUS",
        "governance_role": "MEMBER",
        "tier": "BASIC",
        "status": "ACTIVE",
        "trust_score": trust_score,
        "bio": "Builds distributed systems",
        "specialization": "infrastructure",
        "created_at": datetime.now(timezone.utc),
        "last_seen_at": datetime.now(timezone.utc),
    }


def _trust(agent_did: str, score: float = 0.91) -> TrustScore:
    return TrustScore(
        agent_did=agent_did,
        execution_success=0.9,
        sla_compliance=0.9,
        peer_endorsements=0.9,
        audit_transparency=0.9,
        security_record=1.0,
        composite=score,
    )


class TestSearchAgents:
    @pytest.mark.anyio
    async def test_search_by_skill_returns_agents(self):
        with (
            patch("src.services.agent_directory.get_db") as mock_db,
            patch("src.services.agent_directory.get_trust_score", new=AsyncMock(return_value=_trust("did:agentx:atlas-001"))),
        ):
            conn = AsyncMock()
            conn.fetch.return_value = [_agent_row("did:agentx:atlas-001")]
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            results = await search_agents_by_skill("infra")

        assert len(results) == 1
        assert results[0].agent_did == "did:agentx:atlas-001"
        assert results[0].trust_score == 0.91

    @pytest.mark.anyio
    async def test_search_by_capability_returns_agents(self):
        with (
            patch("src.services.agent_directory.get_db") as mock_db,
            patch("src.services.agent_directory.get_trust_score", new=AsyncMock(return_value=_trust("did:agentx:bruno-001", 0.88))),
        ):
            conn = AsyncMock()
            conn.fetch.return_value = [_agent_row("did:agentx:bruno-001")]
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            results = await search_agents_by_capability("infrastructure.kubernetes")

        assert len(results) == 1
        assert results[0].agent_did == "did:agentx:bruno-001"
        assert results[0].trust_score == 0.88

    @pytest.mark.anyio
    async def test_search_by_reputation_applies_threshold(self):
        with (
            patch("src.services.agent_directory.get_db") as mock_db,
            patch("src.services.agent_directory.get_trust_score", new=AsyncMock(return_value=_trust("did:agentx:thea-001", 0.95))),
        ):
            conn = AsyncMock()
            conn.fetch.return_value = [_agent_row("did:agentx:thea-001", trust_score=0.95)]
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            results = await search_agents_by_reputation(0.8)

        assert len(results) == 1
        assert results[0].trust_score >= 0.8


class TestGetAgentProfile:
    @pytest.mark.anyio
    async def test_get_agent_profile_with_trust_breakdown(self):
        with (
            patch("src.services.agent_directory.get_db") as mock_db,
            patch("src.services.agent_directory.get_trust_score", new=AsyncMock(return_value=_trust("did:agentx:nova-001", 0.93))),
        ):
            conn = AsyncMock()
            conn.fetchrow.return_value = _agent_row("did:agentx:nova-001", trust_score=0.6)
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            profile = await get_agent_profile("did:agentx:nova-001")

        assert profile.agent_did == "did:agentx:nova-001"
        assert profile.trust_score == 0.93
        assert profile.trust_breakdown is not None
        assert profile.trust_breakdown.composite == 0.93

    @pytest.mark.anyio
    async def test_get_agent_profile_not_found_raises(self):
        with patch("src.services.agent_directory.get_db") as mock_db:
            conn = AsyncMock()
            conn.fetchrow.return_value = None
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ValueError, match="Agent not found"):
                await get_agent_profile("did:agentx:missing-001")
