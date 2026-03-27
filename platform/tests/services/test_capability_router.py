"""
Tests: src/services/capability_router.py
Phase 5 — Agent Capability Graph

Covers:
  - register_capability()        — inserts new capability, idempotent for existing
  - assign_capability_to_agent() — links capability to agent, validates both exist
  - find_best_agents()           — delegates to find_eligible_agents, converts dataclass
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services import capability_router
from src.services.capability_matcher import EligibleAgent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tx_context(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _now():
    return datetime.now(UTC)


def _cap_row(cap_id="infrastructure.kubernetes.advanced"):
    return {
        "capability_id":        cap_id,
        "name":                 "Kubernetes Advanced",
        "description":          "Advanced k8s operations",
        "domain":               "INFRASTRUCTURE",
        "level":                "ADVANCED",
        "requires_verification": False,
        "rep_reward":           50,
        "prerequisites":        [],
        "verified_by":          [],
        "created_at":           _now(),
    }


def _eligible_agent(
    agent_did="did:agentx:agent-001",
    display_name="Agent One",
    score=0.85,
    cap_score=0.9,
    trust=0.8,
    rep=50_000,
    missing=None,
):
    return EligibleAgent(
        agent_did=agent_did,
        display_name=display_name,
        score=score,
        capability_match_score=cap_score,
        trust_score=trust,
        rep_balance=rep,
        missing_capabilities=missing or [],
    )


# ── register_capability ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_capability_inserts_new_record():
    from src.models.capability import CapabilityCreate, CapabilityDomain, CapabilityLevel

    cap_id = "infrastructure.kubernetes.advanced"
    data = CapabilityCreate(
        capability_id=cap_id,
        name="Kubernetes Advanced",
        description="Advanced k8s operations",
        domain=CapabilityDomain.INFRASTRUCTURE,
        level=CapabilityLevel.ADVANCED,
        requires_verification=False,
        rep_reward=50,
        prerequisites=[],
    )
    row = _cap_row(cap_id)

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        None,  # no existing capability
        row,   # INSERT RETURNING
    ])

    with patch("src.services.capability_router.transaction", return_value=_tx_context(conn)):
        result = await capability_router.register_capability(data)

    assert result.capability_id == cap_id
    assert result.name == "Kubernetes Advanced"
    assert result.domain.value == "INFRASTRUCTURE"
    assert conn.fetchrow.await_count == 2


@pytest.mark.asyncio
async def test_register_capability_returns_existing_idempotently():
    from src.models.capability import CapabilityCreate, CapabilityDomain, CapabilityLevel

    cap_id = "infrastructure.kubernetes.advanced"
    existing_row = _cap_row(cap_id)
    data = CapabilityCreate(
        capability_id=cap_id,
        name="Kubernetes Advanced",
        description="Advanced k8s operations",
        domain=CapabilityDomain.INFRASTRUCTURE,
        level=CapabilityLevel.ADVANCED,
    )

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=existing_row)  # found on first lookup

    with patch("src.services.capability_router.transaction", return_value=_tx_context(conn)):
        result = await capability_router.register_capability(data)

    # Should have returned the existing record without a second INSERT
    assert result.capability_id == cap_id
    assert conn.fetchrow.await_count == 1


# ── assign_capability_to_agent ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_assign_capability_to_agent_success():
    agent_did = "did:agentx:agent-001"
    cap_id = "infrastructure.kubernetes.advanced"

    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=[1, 1])  # agent exists, cap exists
    conn.fetchrow = AsyncMock(return_value={
        "agent_did":        agent_did,
        "capability_id":    cap_id,
        "verified":         False,
        "verified_by_count": 0,
        "acquired_at":      _now(),
    })

    with patch("src.services.capability_router.transaction", return_value=_tx_context(conn)):
        result = await capability_router.assign_capability_to_agent(agent_did, cap_id)

    assert result["agent_did"] == agent_did
    assert result["capability_id"] == cap_id
    conn.fetchval.assert_awaited()
    conn.fetchrow.assert_awaited_once()


@pytest.mark.asyncio
async def test_assign_capability_raises_if_agent_not_found():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)  # agent not found

    with (
        patch("src.services.capability_router.transaction", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="Agent not found"),
    ):
        await capability_router.assign_capability_to_agent(
            "did:agentx:ghost-001",
            "infrastructure.kubernetes.advanced",
        )


@pytest.mark.asyncio
async def test_assign_capability_raises_if_capability_not_found():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=[1, None])  # agent exists, cap missing

    with (
        patch("src.services.capability_router.transaction", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="Capability not found in registry"),
    ):
        await capability_router.assign_capability_to_agent(
            "did:agentx:agent-001",
            "infrastructure.kubernetes.advanced",
        )


# ── find_best_agents ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_best_agents_converts_eligible_agents():
    agents = [
        _eligible_agent("did:agentx:agent-001", score=0.90),
        _eligible_agent("did:agentx:agent-002", score=0.75, missing=["ml.train.advanced"]),
    ]

    with patch(
        "src.services.capability_router.find_eligible_agents",
        new=AsyncMock(return_value=agents),
    ):
        results = await capability_router.find_best_agents(
            required_capabilities=["infrastructure.kubernetes.advanced"],
            limit=5,
            min_trust_score=0.0,
        )

    assert len(results) == 2
    assert results[0].agent_did == "did:agentx:agent-001"
    assert results[0].score == 0.90
    assert results[1].missing_capabilities == ["ml.train.advanced"]


@pytest.mark.asyncio
async def test_find_best_agents_empty_result():
    with patch(
        "src.services.capability_router.find_eligible_agents",
        new=AsyncMock(return_value=[]),
    ):
        results = await capability_router.find_best_agents(
            required_capabilities=["ml.train.expert"],
            limit=5,
            min_trust_score=0.8,
        )

    assert results == []


@pytest.mark.asyncio
async def test_find_best_agents_passes_params_to_matcher():
    with patch(
        "src.services.capability_router.find_eligible_agents",
        new=AsyncMock(return_value=[]),
    ) as mock_find:
        await capability_router.find_best_agents(
            required_capabilities=["security.audit.expert"],
            limit=3,
            min_trust_score=0.5,
        )

    mock_find.assert_awaited_once_with(
        required_capabilities=["security.audit.expert"],
        limit=3,
        min_trust_score=0.5,
    )
