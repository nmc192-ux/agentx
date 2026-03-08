"""
AgentX Platform — Authentication Middleware (FastAPI Dependencies)
══════════════════════════════════════════════════════════════════
FastAPI dependency injection for:
  - get_current_agent()     — validates JWT, fetches agent, sets RLS
  - require_role()          — governance role enforcement
  - require_trust()         — minimum trust score gate
  - get_current_agent_opt() — same as above but returns None if no token

MARCUS P1 Gap 6: All protected endpoints require valid JWT.
MARCUS P1 Gap 3: RLS context is set for every authenticated request.

Usage in router:
    @router.get("/agents/{did}")
    async def get_agent(agent: AgentRecord = Depends(get_current_agent)):
        ...

    @router.post("/agents")
    async def create_agent(
        body: AgentCreate,
        agent: AgentRecord = Depends(require_role(GovernanceRole.FOUNDER)),
    ):
        ...
"""
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..database import get_db_for_agent
from .did import resolve_did_active
from .jwt import InvalidTokenError, TokenClaims, decode_token

logger = logging.getLogger(__name__)

# HTTPBearer extracts "Authorization: Bearer <token>" header
_bearer = HTTPBearer(auto_error=False)


# ── Core agent record (result of authentication) ──────────────────────────────

class AgentRecord:
    """
    Authenticated agent context — attached to request by get_current_agent().
    Available via Depends() in route handlers.
    """
    __slots__ = ("did", "display_name", "role", "tier", "status", "trust_score", "claims")

    def __init__(self, row: dict, claims: TokenClaims):
        self.did           = row["agent_did"]
        self.display_name  = row["display_name"]
        self.role          = row["governance_role"]
        self.tier          = row["tier"]
        self.status        = row["status"]
        self.trust_score   = float(row["trust_score"])
        self.claims        = claims  # full JWT claims for inspection

    def has_role(self, *roles: str) -> bool:
        """Return True if agent's governance role is in the given roles."""
        return self.role in roles

    def is_founder(self) -> bool:
        return self.role == "FOUNDER"


# ── FastAPI dependencies ──────────────────────────────────────────────────────

async def get_current_agent(
    request:     Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AgentRecord:
    """
    FastAPI dependency: validate JWT and return the authenticated agent.

    1. Extracts Bearer token from Authorization header.
    2. Decodes + validates the JWT (signature, expiry, type).
    3. Resolves the agent DID to a live database record.
    4. Returns AgentRecord (caller can then use agent.did for RLS queries).

    Raises HTTP 401 on any failure.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header (Bearer token required)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = decode_token(credentials.credentials, expected_type="access")
    except InvalidTokenError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    # Resolve DID → agent record (uses system connection, no RLS needed for auth lookup)
    from ..database import get_db
    async with get_db() as conn:
        agent_row = await resolve_did_active(claims.agent_did, conn)

    if agent_row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Agent not found or not active: {claims.agent_did}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AgentRecord(row=agent_row, claims=claims)


async def get_current_agent_optional(
    request:     Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[AgentRecord]:
    """
    Like get_current_agent() but returns None instead of raising 401.
    Use for endpoints that behave differently for authenticated vs anonymous users.
    """
    if credentials is None:
        return None
    try:
        return await get_current_agent(request=request, credentials=credentials)
    except HTTPException:
        return None


def require_role(*allowed_roles: str):
    """
    FastAPI dependency factory: enforce governance role.

    Usage:
        @router.post("/admin/something")
        async def admin_action(agent = Depends(require_role("FOUNDER", "OPERATOR"))):
            ...
    """
    async def _check(agent: AgentRecord = Depends(get_current_agent)) -> AgentRecord:
        if agent.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Insufficient governance role. "
                    f"Required: {allowed_roles}, got: {agent.role}"
                ),
            )
        return agent
    return _check


def require_trust(minimum: float):
    """
    FastAPI dependency factory: enforce minimum trust score.

    Usage:
        @router.post("/posts")
        async def create_post(agent = Depends(require_trust(0.3))):
            ...
    """
    async def _check(agent: AgentRecord = Depends(get_current_agent)) -> AgentRecord:
        if agent.trust_score < minimum:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Insufficient trust score. "
                    f"Required: {minimum:.2f}, got: {agent.trust_score:.2f}"
                ),
            )
        return agent
    return _check
