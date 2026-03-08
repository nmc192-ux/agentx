"""
Tests: DID parsing and validation
Sprint 2 — auth/did.py

Coverage:
  - DID format validation (valid patterns, invalid patterns)
  - DID parsing to components (name, sequence)
  - DID construction (build_did)
  - resolve_did (mocked db connection)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.auth.did import (
    ParsedDID,
    build_did,
    is_valid_did,
    parse_did,
    resolve_did,
    resolve_did_active,
)


# ── Validation ────────────────────────────────────────────────────────────────

class TestIsValidDid:
    """is_valid_did() correctly identifies valid / invalid DIDs."""

    @pytest.mark.parametrize("did", [
        "did:agentx:atlas-001",
        "did:agentx:marcus-002",
        "did:agentx:some-agent-099",
        "did:agentx:a-001",
        "did:agentx:agent123-999",
        "did:agentx:multi-part-name-001",
    ])
    def test_valid_dids(self, did: str):
        assert is_valid_did(did) is True

    @pytest.mark.parametrize("did", [
        "",
        "did:agentx:",
        "did:agentx:ATLAS-001",           # uppercase not allowed
        "did:agentx:atlas",               # no sequence
        "did:agentx:atlas-01",            # sequence must be 3 digits
        "did:agentx:atlas-0001",          # sequence must be exactly 3 digits
        "did:agentx:atlas-!00",           # special chars
        "agentx:atlas-001",               # missing did: prefix
        "did:eth:atlas-001",              # wrong method
        "did:agentx: atlas-001",          # space
    ])
    def test_invalid_dids(self, did: str):
        assert is_valid_did(did) is False


# ── Parsing ───────────────────────────────────────────────────────────────────

class TestParseDid:
    """parse_did() returns correct ParsedDID components."""

    def test_atlas_001(self):
        p = parse_did("did:agentx:atlas-001")
        assert p.name     == "atlas"
        assert p.sequence == 1
        assert p.raw      == "did:agentx:atlas-001"

    def test_multi_part_name(self):
        p = parse_did("did:agentx:some-agent-099")
        assert p.name     == "some-agent"
        assert p.sequence == 99

    def test_returns_parsed_did_type(self):
        p = parse_did("did:agentx:bruno-003")
        assert isinstance(p, ParsedDID)

    def test_str_representation(self):
        p = parse_did("did:agentx:marcus-002")
        assert str(p) == "did:agentx:marcus-002"

    def test_invalid_did_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid DID"):
            parse_did("not-a-did")

    def test_uppercase_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_did("did:agentx:ATLAS-001")

    def test_frozen_dataclass(self):
        p = parse_did("did:agentx:atlas-001")
        with pytest.raises(Exception):
            p.name = "changed"  # type: ignore  — should be immutable


# ── Building ──────────────────────────────────────────────────────────────────

class TestBuildDid:
    """build_did() constructs canonical DID strings."""

    def test_single_digit_sequence_padded(self):
        assert build_did("atlas", 1) == "did:agentx:atlas-001"

    def test_three_digit_sequence(self):
        assert build_did("nova", 999) == "did:agentx:nova-999"

    def test_two_digit_sequence(self):
        assert build_did("quinn", 42) == "did:agentx:quinn-042"

    def test_hyphenated_name(self):
        assert build_did("some-agent", 7) == "did:agentx:some-agent-007"

    def test_invalid_name_raises(self):
        with pytest.raises(ValueError, match="Invalid name"):
            build_did("ATLAS", 1)          # uppercase

    def test_name_with_special_chars_raises(self):
        with pytest.raises(ValueError):
            build_did("my agent", 1)      # space

    def test_sequence_zero_raises(self):
        with pytest.raises(ValueError, match="Sequence must be"):
            build_did("atlas", 0)

    def test_sequence_too_large_raises(self):
        with pytest.raises(ValueError, match="Sequence must be"):
            build_did("atlas", 1000)


# ── Resolution (mocked DB) ───────────────────────────────────────────────────

class TestResolveDid:
    """resolve_did() delegates to the database and handles not-found."""

    @pytest.mark.asyncio
    async def test_resolve_existing_agent(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "agent_did":      "did:agentx:atlas-001",
            "display_name":   "ATLAS",
            "agent_type":     "AUTONOMOUS",
            "governance_role": "FOUNDER",
            "tier":           "ELITE",
            "status":         "ACTIVE",
            "trust_score":    0.98,
            "bio":            "Chief Architect",
            "specialization": "system.architecture.expert",
            "created_at":     None,
            "last_seen_at":   None,
        }

        result = await resolve_did("did:agentx:atlas-001", mock_conn)

        assert result is not None
        assert result["agent_did"] == "did:agentx:atlas-001"
        assert result["governance_role"] == "FOUNDER"
        mock_conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_nonexistent_agent_returns_none(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None

        result = await resolve_did("did:agentx:ghost-001", mock_conn)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_did_returns_none_without_db_call(self):
        mock_conn = AsyncMock()

        result = await resolve_did("not-a-did", mock_conn)

        assert result is None
        mock_conn.fetchrow.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_active_filters_suspended(self):
        """resolve_did_active must only return ACTIVE agents."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None  # DB returns nothing for SUSPENDED

        result = await resolve_did_active("did:agentx:suspended-001", mock_conn)
        assert result is None
