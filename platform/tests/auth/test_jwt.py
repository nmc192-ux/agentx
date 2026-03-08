"""
Tests: JWT generation and validation
Sprint 2 — auth/jwt.py

Coverage:
  - Token generation (access + refresh)
  - Signature validation (valid, expired, tampered)
  - Token type enforcement (access ≠ refresh)
  - Bearer extraction
  - Token pair creation
"""
import time
import pytest

from src.auth.jwt import (
    InvalidTokenError,
    TokenClaims,
    create_access_token,
    create_refresh_token,
    create_token_pair,
    decode_token,
    extract_bearer_token,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

AGENT_DID = "did:agentx:atlas-001"
ROLE      = "FOUNDER"
TIER      = "ELITE"


# ── Token generation ──────────────────────────────────────────────────────────

class TestTokenGeneration:
    """create_access_token and create_refresh_token produce valid JWTs."""

    def test_access_token_is_string(self):
        token = create_access_token(AGENT_DID, ROLE, TIER)
        assert isinstance(token, str)
        assert len(token) > 20

    def test_refresh_token_is_string(self):
        token = create_refresh_token(AGENT_DID, ROLE, TIER)
        assert isinstance(token, str)

    def test_access_token_decodes_to_correct_sub(self):
        token  = create_access_token(AGENT_DID, ROLE, TIER)
        claims = decode_token(token, expected_type="access")
        assert claims.sub == AGENT_DID

    def test_access_token_carries_role_and_tier(self):
        token  = create_access_token(AGENT_DID, ROLE, TIER)
        claims = decode_token(token, expected_type="access")
        assert claims.role == ROLE
        assert claims.tier == TIER

    def test_access_token_type_claim_is_access(self):
        token  = create_access_token(AGENT_DID, ROLE, TIER)
        claims = decode_token(token, expected_type="access")
        assert claims.token_type == "access"

    def test_refresh_token_type_claim_is_refresh(self):
        token  = create_refresh_token(AGENT_DID, ROLE, TIER)
        claims = decode_token(token, expected_type="refresh")
        assert claims.token_type == "refresh"

    def test_access_token_has_jti(self):
        """Each token must have a unique JTI for replay prevention."""
        t1 = decode_token(create_access_token(AGENT_DID), expected_type="access")
        t2 = decode_token(create_access_token(AGENT_DID), expected_type="access")
        assert t1.jti != t2.jti

    def test_create_token_pair_returns_two_strings(self):
        access, refresh = create_token_pair(AGENT_DID, ROLE, TIER)
        assert isinstance(access, str)
        assert isinstance(refresh, str)
        assert access != refresh

    def test_ttl_override_shortens_expiry(self):
        token  = create_access_token(AGENT_DID, ttl_override=1)
        claims = decode_token(token, expected_type="access")
        assert claims.exp > 0
        now = int(time.time())
        assert claims.exp <= now + 5  # expires very soon


# ── Token validation ──────────────────────────────────────────────────────────

class TestTokenValidation:
    """decode_token rejects invalid tokens."""

    def test_tampered_signature_raises(self):
        token    = create_access_token(AGENT_DID)
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(InvalidTokenError):
            decode_token(tampered, expected_type="access")

    def test_wrong_type_raises(self):
        """Using an access token where refresh is expected must fail."""
        token = create_access_token(AGENT_DID)
        with pytest.raises(InvalidTokenError, match="Expected 'refresh'"):
            decode_token(token, expected_type="refresh")

    def test_refresh_where_access_expected_raises(self):
        token = create_refresh_token(AGENT_DID)
        with pytest.raises(InvalidTokenError, match="Expected 'access'"):
            decode_token(token, expected_type="access")

    def test_expired_token_raises(self):
        """Token with TTL=1 second should be expired by the time we decode it."""
        token = create_access_token(AGENT_DID, ttl_override=-1)  # already expired
        with pytest.raises(InvalidTokenError):
            decode_token(token, expected_type="access")

    def test_empty_string_raises(self):
        with pytest.raises(InvalidTokenError):
            decode_token("", expected_type="access")

    def test_garbage_string_raises(self):
        with pytest.raises(InvalidTokenError):
            decode_token("not.a.jwt", expected_type="access")

    def test_agent_did_property(self):
        token  = create_access_token(AGENT_DID)
        claims = decode_token(token, expected_type="access")
        assert claims.agent_did == AGENT_DID


# ── Bearer extraction ─────────────────────────────────────────────────────────

class TestBearerExtraction:
    """extract_bearer_token parses Authorization headers."""

    def test_valid_bearer_header(self):
        raw    = create_access_token(AGENT_DID)
        header = f"Bearer {raw}"
        assert extract_bearer_token(header) == raw

    def test_missing_bearer_prefix_raises(self):
        with pytest.raises(InvalidTokenError):
            extract_bearer_token("justthetoken")

    def test_wrong_scheme_raises(self):
        with pytest.raises(InvalidTokenError):
            extract_bearer_token("Basic abc123")

    def test_extra_spaces_raises(self):
        with pytest.raises(InvalidTokenError):
            extract_bearer_token("Bearer token extra")

    def test_empty_raises(self):
        with pytest.raises(InvalidTokenError):
            extract_bearer_token("")
