"""
AgentX — Tests: POST /auth/token  ·  POST /auth/refresh
═══════════════════════════════════════════════════════
Sprint 7: auth token endpoint

Tests cover:
  - refresh_token grant: valid / expired / wrong type
  - client_credentials grant: dev env / production blocked
  - password grant: helpful 400 error
  - unknown grant: 400 error
  - /auth/refresh alias
"""
import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from jose import jwt

from src.main import app
from src.auth.jwt import create_token_pair, create_refresh_token, create_access_token
from src.config import get_settings

settings = get_settings()

client = TestClient(app)

# ── Fixtures ───────────────────────────────────────────────────────────────────

TEST_DID  = "did:agentx:atlas-001"
TEST_ROLE = "FOUNDER"
TEST_TIER = "ELITE"

ACTIVE_ROW = {
    "agent_did":        TEST_DID,
    "governance_role":  TEST_ROLE,
    "tier":             TEST_TIER,
    "status":           "ACTIVE",
    "trust_score":      0.42,
}


def _make_refresh_token(did: str = TEST_DID, role: str = TEST_ROLE, tier: str = TEST_TIER) -> str:
    return create_token_pair(did, role, tier)[1]   # [1] = refresh token


def _make_expired_refresh(did: str = TEST_DID) -> str:
    payload = {
        "sub":  did,
        "role": TEST_ROLE,
        "tier": TEST_TIER,
        "type": "refresh",
        "jti":  str(uuid4()),
        "iat":  int((datetime.now(UTC) - timedelta(days=10)).timestamp()),
        "exp":  int((datetime.now(UTC) - timedelta(days=3)).timestamp()),  # expired
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _make_access_token_as_refresh(did: str = TEST_DID) -> str:
    """Access token passed where refresh is expected — should fail type check."""
    return create_access_token(did, TEST_ROLE, TEST_TIER)


# ── refresh_token grant ────────────────────────────────────────────────────────

class TestRefreshTokenGrant:

    def test_valid_refresh_returns_new_token_pair(self):
        token = _make_refresh_token()
        with patch("src.routers.auth.get_db") as mock_db:
            conn = AsyncMock()
            conn.fetchrow = AsyncMock(return_value=ACTIVE_ROW)
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)

            resp = client.post(
                "/auth/token",
                data={"grant_type": "refresh_token", "refresh_token": token},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token"  in body
        assert "refresh_token" in body
        assert body["token_type"]  == "bearer"
        assert body["agent_did"]   == TEST_DID
        assert body["expires_in"]  > 0

    def test_new_access_token_is_valid_jwt(self):
        token = _make_refresh_token()
        with patch("src.routers.auth.get_db") as mock_db:
            conn = AsyncMock()
            conn.fetchrow = AsyncMock(return_value=ACTIVE_ROW)
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)

            resp = client.post(
                "/auth/token",
                data={"grant_type": "refresh_token", "refresh_token": token},
            )

        access = resp.json()["access_token"]
        claims = jwt.decode(access, settings.jwt_secret, algorithms=["HS256"])
        assert claims["sub"]  == TEST_DID
        assert claims["type"] == "access"

    def test_expired_refresh_token_returns_401(self):
        expired = _make_expired_refresh()
        resp = client.post(
            "/auth/token",
            data={"grant_type": "refresh_token", "refresh_token": expired},
        )
        assert resp.status_code == 401
        assert "invalid or expired" in resp.json()["detail"].lower()

    def test_access_token_used_as_refresh_returns_401(self):
        """Passing an access token where a refresh token is expected must fail."""
        access = _make_access_token_as_refresh()
        resp = client.post(
            "/auth/token",
            data={"grant_type": "refresh_token", "refresh_token": access},
        )
        assert resp.status_code == 401

    def test_missing_refresh_token_field_returns_422(self):
        resp = client.post(
            "/auth/token",
            data={"grant_type": "refresh_token"},
        )
        assert resp.status_code == 422

    def test_suspended_agent_returns_403(self):
        token = _make_refresh_token()
        suspended = {**ACTIVE_ROW, "status": "SUSPENDED"}
        with patch("src.routers.auth.get_db") as mock_db:
            conn = AsyncMock()
            conn.fetchrow = AsyncMock(return_value=suspended)
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)

            resp = client.post(
                "/auth/token",
                data={"grant_type": "refresh_token", "refresh_token": token},
            )

        assert resp.status_code == 403

    def test_deleted_agent_returns_401(self):
        token = _make_refresh_token()
        with patch("src.routers.auth.get_db") as mock_db:
            conn = AsyncMock()
            conn.fetchrow = AsyncMock(return_value=None)  # not found in DB
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)

            resp = client.post(
                "/auth/token",
                data={"grant_type": "refresh_token", "refresh_token": token},
            )

        assert resp.status_code == 401

    def test_tampered_token_returns_401(self):
        resp = client.post(
            "/auth/token",
            data={"grant_type": "refresh_token", "refresh_token": "totally.fake.jwt"},
        )
        assert resp.status_code == 401


# ── client_credentials grant ───────────────────────────────────────────────────

class TestClientCredentialsGrant:

    def test_client_credentials_returns_tokens_in_dev(self):
        with patch("src.routers.auth.get_db") as mock_db:
            conn = AsyncMock()
            conn.fetchrow = AsyncMock(return_value=ACTIVE_ROW)
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)

            resp = client.post(
                "/auth/token",
                data={"grant_type": "client_credentials", "username": TEST_DID},
            )

        # In test env (not production), this should succeed
        assert resp.status_code == 200
        assert resp.json()["agent_did"] == TEST_DID

    def test_client_credentials_unknown_agent_returns_404(self):
        with patch("src.routers.auth.get_db") as mock_db:
            conn = AsyncMock()
            conn.fetchrow = AsyncMock(return_value=None)
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)

            resp = client.post(
                "/auth/token",
                data={"grant_type": "client_credentials", "username": "did:agentx:nobody-999"},
            )

        assert resp.status_code == 404

    def test_client_credentials_missing_username_returns_422(self):
        resp = client.post(
            "/auth/token",
            data={"grant_type": "client_credentials"},
        )
        assert resp.status_code == 422

    def test_client_credentials_blocked_in_production(self):
        with patch("src.routers.auth.settings") as mock_settings:
            mock_settings.is_production = True

            resp = client.post(
                "/auth/token",
                data={"grant_type": "client_credentials", "username": TEST_DID},
            )

        assert resp.status_code == 403
        assert "production" in resp.json()["detail"].lower()


# ── password grant (unsupported — helpful error) ───────────────────────────────

class TestPasswordGrant:

    def test_password_grant_returns_400_with_guidance(self):
        resp = client.post(
            "/auth/token",
            data={"grant_type": "password", "username": TEST_DID, "password": "secret"},
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "grant_type=password is not supported" in detail
        assert "POST /v1/agents" in detail   # points to registration

    def test_password_grant_empty_password(self):
        resp = client.post(
            "/auth/token",
            data={"grant_type": "password", "username": TEST_DID, "password": ""},
        )
        assert resp.status_code == 400


# ── unknown grant type ─────────────────────────────────────────────────────────

class TestUnknownGrant:

    def test_unknown_grant_type_returns_400(self):
        resp = client.post(
            "/auth/token",
            data={"grant_type": "magic", "username": TEST_DID},
        )
        assert resp.status_code == 400
        assert "Unsupported grant_type" in resp.json()["detail"]

    def test_empty_grant_type_returns_400(self):
        resp = client.post("/auth/token", data={})
        assert resp.status_code == 400


# ── POST /auth/refresh alias ──────────────────────────────────────────────────

class TestRefreshAlias:

    def test_refresh_alias_works(self):
        token = _make_refresh_token()
        with patch("src.routers.auth.get_db") as mock_db:
            conn = AsyncMock()
            conn.fetchrow = AsyncMock(return_value=ACTIVE_ROW)
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=None)

            resp = client.post(
                "/auth/refresh",
                data={"refresh_token": token},
            )

        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_refresh_alias_expired_returns_401(self):
        expired = _make_expired_refresh()
        resp = client.post(
            "/auth/refresh",
            data={"refresh_token": expired},
        )
        assert resp.status_code == 401
