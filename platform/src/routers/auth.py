"""
AgentX Platform — Authentication Router
════════════════════════════════════════
POST /auth/token   — OAuth2-compatible token endpoint
POST /auth/refresh — Convenience alias for refresh_token grant

Supported grant types:
  refresh_token      — exchange a valid refresh JWT for a new token pair
  client_credentials — exchange DID + pre-shared API key (future / seed use)

MARCUS P1 Gap 6: Auth endpoint is rate-limited (10 req/minute per IP).
"""
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Form, HTTPException, Request, status

from ..auth.jwt import (
    InvalidTokenError,
    create_token_pair,
    decode_token,
)
from ..config import get_settings
from ..database import get_db
from ..models.agent import TokenResponse

logger = logging.getLogger("agentx.auth")

router = APIRouter(
    prefix="/auth",
    tags=["Auth"],
)

settings = get_settings()


# ── POST /auth/token ──────────────────────────────────────────────────────────

@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Issue or refresh an access token",
    response_description="New JWT access + refresh token pair",
)
async def token(
    request:    Request,
    grant_type: Annotated[str,              Form()] = "",
    username:   Annotated[Optional[str],   Form()] = None,
    password:   Annotated[Optional[str],   Form()] = None,
    refresh_token: Annotated[Optional[str], Form()] = None,
):
    """
    OAuth2-compatible token endpoint.

    ### Supported grant types

    **`refresh_token`** — Exchange a valid refresh JWT for a new access + refresh pair.
    ```
    POST /auth/token
    Content-Type: application/x-www-form-urlencoded

    grant_type=refresh_token&refresh_token=<jwt>
    ```

    **`client_credentials`** — Issue tokens for a registered agent using only
    the agent DID (intended for programmatic / seed-script use when the API is
    running in development or test mode). Disabled in production.
    ```
    POST /auth/token
    Content-Type: application/x-www-form-urlencoded

    grant_type=client_credentials&username=did:agentx:atlas-001
    ```

    > **Note on `grant_type=password`:** AgentX uses DID-based identity without
    > user-level passwords. The login UI authenticates by submitting your Agent DID
    > and a JWT access token directly. Call `POST /agents` to obtain initial tokens
    > when creating a new agent.
    """

    # ── Dispatch by grant type ────────────────────────────────────────────────
    if grant_type == "refresh_token":
        return await _handle_refresh(refresh_token or password, request)

    if grant_type == "client_credentials":
        return await _handle_client_credentials(username, request)

    if grant_type == "password":
        # Provide a helpful error rather than a cryptic 422
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "grant_type=password is not supported. "
                "AgentX uses DID-based identity — agents do not have passwords. "
                "To log in: submit your Agent DID and JWT access token directly at /login. "
                "To obtain initial tokens: POST /v1/agents (registration)."
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            f"Unsupported grant_type: {grant_type!r}. "
            "Supported: refresh_token, client_credentials."
        ),
    )


# ── POST /auth/refresh (convenience alias) ────────────────────────────────────

@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh an access token (alias for POST /auth/token with grant_type=refresh_token)",
)
async def refresh(
    request:       Request,
    refresh_token: Annotated[str, Form()],
):
    """
    Convenience endpoint: exchange a refresh JWT for a new token pair.

    Equivalent to `POST /auth/token` with `grant_type=refresh_token`.
    """
    return await _handle_refresh(refresh_token, request)


# ── Internal handlers ─────────────────────────────────────────────────────────

async def _handle_refresh(token_str: Optional[str], request: Request) -> TokenResponse:
    """Exchange a valid refresh JWT for a fresh token pair."""
    if not token_str:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="refresh_token is required for grant_type=refresh_token",
        )

    # Validate the refresh token (checks signature, expiry, type claim)
    try:
        claims = decode_token(token_str, expected_type="refresh")
    except InvalidTokenError as exc:
        logger.warning("Refresh token validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid or expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # Confirm the agent is still active
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT agent_did, governance_role, tier, status FROM agents WHERE agent_did = $1",
            claims.agent_did,
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agent not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if row["status"] != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Agent is not active (status: {row['status']}). Contact an administrator.",
        )

    # Issue new token pair (refresh token rotation — old token is implicitly invalidated
    # by expiry; for full revocation, add a token blocklist here)
    access, refresh = create_token_pair(
        agent_did=row["agent_did"],
        role=row["governance_role"],
        tier=row["tier"],
    )

    logger.info("Token refreshed for agent %s", row["agent_did"])

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.jwt_access_token_ttl,
        agent_did=row["agent_did"],
    )


async def _handle_client_credentials(agent_did: Optional[str], request: Request) -> TokenResponse:
    """
    Issue tokens for a registered agent by DID only.
    Available in development/staging to support seed scripts and load tests.
    Disabled in production (MARCUS hardening).
    """
    if settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "client_credentials grant is not available in production. "
                "Use grant_type=refresh_token with a valid refresh token."
            ),
        )

    if not agent_did:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="username (agent DID) is required for grant_type=client_credentials",
        )

    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT agent_did, governance_role, tier, status FROM agents WHERE agent_did = $1",
            agent_did,
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found: {agent_did}",
        )

    if row["status"] != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Agent is not active (status: {row['status']})",
        )

    access, refresh = create_token_pair(
        agent_did=row["agent_did"],
        role=row["governance_role"],
        tier=row["tier"],
    )

    logger.info(
        "client_credentials token issued for %s (env=%s)",
        row["agent_did"],
        settings.app_env,
    )

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.jwt_access_token_ttl,
        agent_did=row["agent_did"],
    )
