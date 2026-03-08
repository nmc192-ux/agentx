"""
AgentX Platform — JWT Authentication
══════════════════════════════════════
HS256 JWT generation and validation for agent identity.

MARCUS P1 Gap 6: JWT with short-lived access tokens + refresh rotation.

Token types:
  access:  short-lived (15 min default), used for API requests
  refresh: long-lived (7 days default), used to obtain new access tokens

Payload:
  sub   — agent DID (string, e.g. "did:agentx:atlas-001")
  role  — governance role (string)
  tier  — agent tier (string)
  type  — "access" | "refresh"
  jti   — UUID (prevents token replay)
  iat   — issued-at timestamp
  exp   — expiry timestamp
"""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, Optional

from jose import JWTError, jwt

from ..config import get_settings

# ── Token payload type ────────────────────────────────────────────────────────

class TokenClaims:
    """Parsed claims from a validated JWT."""
    __slots__ = ("sub", "role", "tier", "token_type", "jti", "iat", "exp")

    def __init__(self, payload: dict):
        self.sub        = payload["sub"]
        self.role       = payload.get("role", "MEMBER")
        self.tier       = payload.get("tier", "BOOTSTRAP")
        self.token_type = payload.get("type", "access")
        self.jti        = payload.get("jti", "")
        self.iat        = payload.get("iat")
        self.exp        = payload.get("exp")

    @property
    def agent_did(self) -> str:
        return self.sub


# ── Token generation ──────────────────────────────────────────────────────────

def _make_payload(
    agent_did: str,
    role:       str,
    tier:       str,
    token_type: Literal["access", "refresh"],
    ttl_seconds: int,
) -> dict:
    """Build JWT payload dict."""
    now = datetime.now(UTC)
    return {
        "sub":  agent_did,
        "role": role,
        "tier": tier,
        "type": token_type,
        "jti":  str(uuid.uuid4()),
        "iat":  int(now.timestamp()),
        "exp":  int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }


def create_access_token(
    agent_did: str,
    role:      str = "MEMBER",
    tier:      str = "BOOTSTRAP",
    ttl_override: Optional[int] = None,
) -> str:
    """
    Generate a signed JWT access token.

    Args:
        agent_did:    DID of the agent (becomes token `sub`)
        role:         Governance role (FOUNDER, OPERATOR, DELEGATE, MEMBER, OBSERVER)
        tier:         Agent tier (BOOTSTRAP, BASIC, PROFESSIONAL, ELITE)
        ttl_override: Override TTL in seconds (default: settings.jwt_access_token_ttl)

    Returns:
        Signed JWT string.
    """
    settings = get_settings()
    ttl = ttl_override if ttl_override is not None else settings.jwt_access_token_ttl
    payload = _make_payload(agent_did, role, tier, "access", ttl)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    agent_did: str,
    role:      str = "MEMBER",
    tier:      str = "BOOTSTRAP",
) -> str:
    """
    Generate a signed JWT refresh token (longer TTL, type='refresh').

    Args:
        agent_did: DID of the agent
        role:      Current governance role
        tier:      Current agent tier

    Returns:
        Signed JWT string.
    """
    settings = get_settings()
    payload = _make_payload(agent_did, role, tier, "refresh", settings.jwt_refresh_token_ttl)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_token_pair(
    agent_did: str,
    role:      str = "MEMBER",
    tier:      str = "BOOTSTRAP",
) -> tuple[str, str]:
    """
    Create an (access_token, refresh_token) pair.

    Returns:
        Tuple of (access_jwt, refresh_jwt).
    """
    access  = create_access_token(agent_did, role, tier)
    refresh = create_refresh_token(agent_did, role, tier)
    return access, refresh


# ── Token validation ──────────────────────────────────────────────────────────

class InvalidTokenError(Exception):
    """Raised when a JWT cannot be validated."""
    pass


def decode_token(token: str, expected_type: Literal["access", "refresh"] = "access") -> TokenClaims:
    """
    Validate and decode a JWT.

    Args:
        token:         Raw JWT string (without 'Bearer ' prefix)
        expected_type: "access" or "refresh" — validates the `type` claim

    Returns:
        TokenClaims object with parsed payload.

    Raises:
        InvalidTokenError: If the token is expired, tampered, or wrong type.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        raise InvalidTokenError(f"Token validation failed: {e}") from e

    claims = TokenClaims(payload)

    if claims.token_type != expected_type:
        raise InvalidTokenError(
            f"Expected {expected_type!r} token but got {claims.token_type!r}"
        )

    return claims


def extract_bearer_token(authorization: str) -> str:
    """
    Extract the raw JWT from an Authorization header value.

    Args:
        authorization: e.g. "Bearer eyJhbGci..."

    Returns:
        Raw token string.

    Raises:
        InvalidTokenError: If header format is wrong.
    """
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise InvalidTokenError(
            "Authorization header must be: 'Bearer <token>'"
        )
    return parts[1]
