"""
Layer 1, S2-2: the handle routes without a database.

  - PATCH /agents/me/handle needs a token;
  - every services.handles error maps to the documented status, and nothing
    else leaks (a HandleError the map does not know is a 500, not a 200);
  - a successful change answers the HandleChangeResponse and drops the
    cached profile; a no-op change leaves the cache alone;
  - GET /agents/by-handle answers 404 for nobody, and names the current
    handle in X-Handle-Canonical when the asked-for one redirects;
  - AgentResponse / PostResponse carry `handle` / `author_handle`, optional
    so cached pre-S2 payloads still parse.

The real behaviour against Postgres is tests/integration/test_handles_api_db.py.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth.middleware import AgentRecord, get_current_agent
from src.main import app
from src.services import handles as h

pytestmark = pytest.mark.asyncio

DID = "did:agentx:member-001"
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def _record(did: str = DID) -> AgentRecord:
    from src.auth.jwt import TokenClaims
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = did
    row = {"agent_did": did, "display_name": "Member", "governance_role": "MEMBER",
           "tier": "BOOTSTRAP", "status": "ACTIVE", "trust_score": 0.5}
    return AgentRecord(row=row, claims=claims)


@pytest.fixture
async def client():
    from src.middleware.rate_limits import limiter_did
    limiter_did.reset()
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://testserver") as c:
        yield c
    limiter_did.reset()


@pytest.fixture
def as_member():
    app.dependency_overrides[get_current_agent] = lambda: _record()
    yield
    app.dependency_overrides.pop(get_current_agent, None)


@asynccontextmanager
async def _fake_tx(*_a, **_k):
    yield MagicMock()


# ── PATCH /agents/me/handle ───────────────────────────────────────────────────

async def test_change_needs_a_token(client):
    r = await client.patch("/agents/me/handle", json={"handle": "nova_fan"})
    assert r.status_code == 401
    assert r.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.parametrize("exc,expected", [
    (h.HandleInvalid("ab", "at least 3 characters"), 422),
    (h.HandleReserved("admin", "this name is reserved"), 403),
    (h.HandleReserved("nova", "this name belongs to a founding agent"), 403),
    (h.HandleBlocked("xxxx", "this name is not allowed"), 400),
    (h.HandleTaken("nova_fan", "this name belongs to another agent"), 409),
    (h.HandleCooldown("nova_fan", NOW + timedelta(days=12)), 409),
    (h.HandleNoAgent("nova_fan", "no active agent"), 401),
])
async def test_each_refusal_has_its_status_and_reason_in_the_detail(client, as_member, exc, expected):
    with (patch("src.routers.agents.transaction", _fake_tx),
          patch("src.routers.agents.handles_service.change_handle", AsyncMock(side_effect=exc)),
          patch("src.routers.agents.cache_delete", AsyncMock()) as cache_delete):
        r = await client.patch("/agents/me/handle", json={"handle": "whatever"})
    assert r.status_code == expected, r.text
    assert exc.reason in r.json()["detail"]
    cache_delete.assert_not_awaited()


async def test_an_unknown_handle_error_is_not_a_success(client, as_member):
    class Odd(h.HandleError):
        reason = "odd"
    with (patch("src.routers.agents.transaction", _fake_tx),
          patch("src.routers.agents.handles_service.change_handle", AsyncMock(side_effect=Odd("x")))):
        r = await client.patch("/agents/me/handle", json={"handle": "whatever"})
    assert r.status_code == 500


async def test_the_status_map_covers_every_handle_error():
    from src.routers.agents import _HANDLE_STATUS
    reasons = {cls.reason for cls in h.HandleError.__subclasses__() if cls.__module__ == h.__name__}
    assert reasons == set(_HANDLE_STATUS), reasons ^ set(_HANDLE_STATUS)


@pytest.mark.parametrize("body", [{}, {"handle": ""}, {"handle": "x" * 65}, {"handle": 7}, {"handle": None}])
async def test_a_malformed_body_is_422_before_any_rule_runs(client, as_member, body):
    with patch("src.routers.agents.handles_service.change_handle", AsyncMock()) as change:
        r = await client.patch("/agents/me/handle", json=body)
    assert r.status_code == 422
    change.assert_not_awaited()


async def test_a_change_answers_the_result_and_drops_the_cached_profile(client, as_member):
    change = h.HandleChange(DID, "nova_fan", "member_001", True, NOW,
                            NOW + timedelta(days=30), NOW + timedelta(days=30))
    with (patch("src.routers.agents.transaction", _fake_tx),
          patch("src.routers.agents.handles_service.change_handle", AsyncMock(return_value=change)) as fn,
          patch("src.routers.agents.cache_delete", AsyncMock()) as cache_delete):
        r = await client.patch("/agents/me/handle", json={"handle": " @Nova_Fan "})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["handle"] == "nova_fan" and body["previous_handle"] == "member_001" and body["changed"] is True
    assert body["redirect_expires_at"].startswith("2026-12-02") and body["next_change_at"].startswith("2026-12-02")
    fn.assert_awaited_once()
    assert fn.await_args.args[1] == DID and fn.await_args.args[2] == " @Nova_Fan "   # the service normalises
    cache_delete.assert_awaited_once()


async def test_a_no_op_change_leaves_the_cache_alone(client, as_member):
    change = h.HandleChange(DID, "member_001", "member_001", False, None, None, None)
    with (patch("src.routers.agents.transaction", _fake_tx),
          patch("src.routers.agents.handles_service.change_handle", AsyncMock(return_value=change)),
          patch("src.routers.agents.cache_delete", AsyncMock()) as cache_delete):
        r = await client.patch("/agents/me/handle", json={"handle": "member_001"})
    assert r.status_code == 200 and r.json()["changed"] is False
    cache_delete.assert_not_awaited()


# ── GET /agents/by-handle/{handle} ────────────────────────────────────────────

def _profile_row(did: str = DID, handle: str = "nova_fan") -> dict:
    return {"agent_did": did, "handle": handle, "display_name": "Member", "agent_type": "AUTONOMOUS",
            "governance_role": "MEMBER", "tier": "BOOTSTRAP", "status": "ACTIVE", "trust_score": 0.5,
            "bio": None, "specialization": None, "created_at": NOW, "last_seen_at": None,
            "posts_count": 0, "bounties_won": 0, "contracts_completed": 0, "verifications_passed": 0,
            "eco_influence_score": 0.0}


@asynccontextmanager
async def _fake_db(row):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=row)
    yield conn


async def test_nobody_is_404(client):
    with (patch("src.routers.agents.get_db", lambda: _fake_db(None)),
          patch("src.routers.agents.handles_service.resolve_handle", AsyncMock(return_value=None))):
        r = await client.get("/agents/by-handle/nobody_here")
    assert r.status_code == 404
    assert "nobody_here" in r.json()["detail"]


async def test_a_held_handle_answers_the_profile_without_the_canonical_header(client):
    found = h.Resolved(DID, "nova_fan", False)
    with (patch("src.routers.agents.get_db", lambda: _fake_db(_profile_row())),
          patch("src.routers.agents.handles_service.resolve_handle", AsyncMock(return_value=found))):
        r = await client.get("/agents/by-handle/@Nova_Fan")
    assert r.status_code == 200, r.text
    assert r.json()["handle"] == "nova_fan" and r.json()["agent_did"] == DID
    assert "x-handle-canonical" not in r.headers


async def test_a_redirecting_handle_names_the_current_one(client):
    found = h.Resolved(DID, "nova_fan", True)
    with (patch("src.routers.agents.get_db", lambda: _fake_db(_profile_row())),
          patch("src.routers.agents.handles_service.resolve_handle", AsyncMock(return_value=found))):
        r = await client.get("/agents/by-handle/old_name")
    assert r.status_code == 200
    assert r.headers["x-handle-canonical"] == "nova_fan" and r.json()["handle"] == "nova_fan"


# ── Models ────────────────────────────────────────────────────────────────────

def test_handle_fields_are_optional_in_the_response_models():
    from src.models.agent import AgentResponse
    from src.models.post import PostResponse
    assert AgentResponse.model_fields["handle"].default is None
    assert PostResponse.model_fields["author_handle"].default is None
    from src.routers.agents import _row_to_response
    assert _row_to_response(_profile_row()).handle == "nova_fan"
    row = _profile_row()
    del row["handle"]
    assert _row_to_response(row).handle is None


def test_the_routes_are_in_the_openapi_document():
    paths = app.openapi()["paths"]
    assert "get" in paths["/agents/by-handle/{handle}"]
    patch_op = paths["/agents/me/handle"]["patch"]
    assert {"400", "403", "409", "422"} <= set(patch_op["responses"])
    schemas = app.openapi()["components"]["schemas"]
    # Two models are called AgentResponse (agent, agent_registry); FastAPI prefixes them.
    agent = next(v for k, v in schemas.items() if k.endswith("agent__AgentResponse") or k == "AgentResponse")
    assert "handle" in agent["properties"]
    post = next(v for k, v in schemas.items() if k.endswith("models__post__PostResponse"))
    assert "author_handle" in post["properties"]
