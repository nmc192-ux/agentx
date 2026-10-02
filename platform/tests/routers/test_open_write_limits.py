"""
Tests: Sprint 9 S9-8a2 — limits on the remaining open write routes.

  - task creation: POST /tasks, /tasks/create and /tasks/route share one
    per-agent budget (5/min); the 6th inside a minute → 429, and another
    agent still has its own budget
  - POST /economy/strategies/select and /economy/market-analysis (no login)
    share one per-IP budget (30/min); the 31st → 429
  - open sign-up: POST /agents and /agents/register share one per-IP budget
    (5/hr); the 6th → 429. A MEMBER token does not escape it; a FOUNDER token
    gets a bucket of its own.
  - body size: a chunked upload with no Content-Length over 64 KiB → 413;
    a non-numeric Content-Length → 400; a small chunked body still arrives

Limit hits are counted before the handler runs, so the requests here are
built to be refused cheaply by the handler (403/401) without a database.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from src.main import MAX_BODY_BYTES, app
from src.middleware.body_limit import BodySizeLimitMiddleware

from .test_posts import _make_caller


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides = {}


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


def _bearer(did: str, role: str = "MEMBER") -> dict:
    from src.auth.jwt import create_access_token
    return {"Authorization": f"Bearer {create_access_token(agent_did=did, role=role, trust_score=0.0)}"}


def _as(did: str, role: str = "MEMBER"):
    from src.auth.middleware import get_current_agent, get_current_agent_optional
    app.dependency_overrides[get_current_agent] = lambda: _make_caller(did=did, role=role)
    app.dependency_overrides[get_current_agent_optional] = lambda: _make_caller(did=did, role=role)


class TestLimitValues:

    def test_budgets(self):
        from src.middleware import rate_limits as rl
        assert [f() for f in (rl.LIMIT_TASK_CREATE, rl.LIMIT_TASK_CREATE_HR, rl.LIMIT_TASK_CREATE_DAY)] \
            == ["5/minute", "30/hour", "100/day"]
        assert (rl.LIMIT_ECONOMY_CALC, rl.LIMIT_ECONOMY_CALC_HR) == ("30/minute", "300/hour")
        assert rl.LIMIT_SIGNUP_HR("ip:1.2.3.4") == "5/hour"
        assert rl.LIMIT_SIGNUP_DAY("ip:1.2.3.4") == "20/day"
        assert rl.LIMIT_SIGNUP_HR("founder:did:agentx:atlas-001") == "100/hour"
        assert rl.LIMIT_SIGNUP_DAY("founder:did:agentx:atlas-001") == "500/day"


class TestTaskCreateBudget:
    # Naming another agent as requester/creator answers 403 from the handler,
    # after the limiter has counted the hit.

    async def test_sixth_create_in_a_minute_across_routes_is_429(self, client):
        me = "did:agentx:alice-001"
        _as(me)
        h = _bearer(me)
        other = "did:agentx:mallory-001"
        calls = [
            ("/tasks/create", {"requester_agent_did": other, "executor_agent_did": other, "task_type": "x"}),
            ("/tasks/route", {"requester_agent_did": other, "task_type": "x"}),
            ("/tasks", {"creator_agent_did": other, "task_type": "x"}),
            ("/tasks/create", {"requester_agent_did": other, "executor_agent_did": other, "task_type": "x"}),
            ("/tasks", {"creator_agent_did": other, "task_type": "x"}),
        ]
        for path, body in calls:
            r = await client.post(path, json=body, headers=h)
            assert r.status_code == 403, (path, r.text)

        r = await client.post("/tasks/route", json={"requester_agent_did": other, "task_type": "x"}, headers=h)
        assert r.status_code == 429
        assert r.json()["scope"] == "per-did"

    async def test_budget_is_per_agent(self, client):
        other = "did:agentx:mallory-001"
        body = {"creator_agent_did": other, "task_type": "x"}
        _as("did:agentx:alice-001")
        for _ in range(5):
            assert (await client.post("/tasks", json=body, headers=_bearer("did:agentx:alice-001"))).status_code == 403
        assert (await client.post("/tasks", json=body, headers=_bearer("did:agentx:alice-001"))).status_code == 429

        _as("did:agentx:bob-001")
        r = await client.post("/tasks", json=body, headers=_bearer("did:agentx:bob-001"))
        assert r.status_code == 403


class TestEconomyCalcBudget:

    async def test_thirty_first_call_per_ip_across_both_routes_is_429(self, client):
        for i in range(30):
            if i % 2:
                r = await client.post("/economy/strategies/select", json={"agent_id": "a", "capabilities": []})
            else:
                r = await client.post("/economy/market-analysis", json={"bounties": [], "agents": []})
            assert r.status_code == 200, r.text

        r = await client.post("/economy/market-analysis", json={"bounties": [], "agents": []})
        assert r.status_code == 429
        assert r.json()["scope"] == "per-ip"


class TestSignupBudget:
    # Anonymous sign-up as FOUNDER answers 401 from the handler (no DB),
    # after the limiter has counted the hit.

    _founder_body = {"agent_did": "did:agentx:sneaky-001", "display_name": "S", "governance_role": "FOUNDER"}

    async def _use_up_ip_budget(self, client):
        for _ in range(5):
            r = await client.post("/agents", json=self._founder_body)
            assert r.status_code == 401, r.text

    async def test_sixth_signup_per_ip_across_both_routes_is_429(self, client):
        await self._use_up_ip_budget(client)
        r = await client.post(
            "/agents/register",
            json={"name": "w", "description": "d", "skills": [], "capabilities": [], "endpoint": "http://w", "owner": "o"},
        )
        assert r.status_code == 429
        r = await client.post("/agents", json=self._founder_body)
        assert r.status_code == 429

    async def test_member_token_shares_the_ip_budget(self, client):
        await self._use_up_ip_budget(client)
        _as("did:agentx:alice-001", role="MEMBER")
        r = await client.post("/agents", json=self._founder_body, headers=_bearer("did:agentx:alice-001"))
        assert r.status_code == 429

    async def test_founder_token_has_its_own_bucket(self, client):
        await self._use_up_ip_budget(client)
        # The token says FOUNDER (own rate-limit bucket); the DB record says
        # MEMBER, so the handler still refuses the FOUNDER role with 403.
        _as("did:agentx:atlas-001", role="MEMBER")
        r = await client.post(
            "/agents", json=self._founder_body, headers=_bearer("did:agentx:atlas-001", role="FOUNDER"),
        )
        assert r.status_code == 403

    async def test_forged_founder_token_does_not_escape(self, client):
        await self._use_up_ip_budget(client)
        h = {"Authorization": "Bearer not-a-real-token"}
        r = await client.post("/agents", json=self._founder_body, headers=h)
        assert r.status_code == 429


class TestBodySize:

    @staticmethod
    async def _chunks(total: int, size: int = 8192):
        sent = 0
        while sent < total:
            n = min(size, total - sent)
            sent += n
            yield b"a" * n

    async def test_chunked_body_over_limit_is_413(self, client):
        r = await client.post(
            "/economy/market-analysis",
            content=self._chunks(MAX_BODY_BYTES + 1),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 413
        assert r.json()["max_bytes"] == MAX_BODY_BYTES

    async def test_declared_length_over_limit_is_413(self, client):
        r = await client.post("/economy/market-analysis", content=b"a" * (MAX_BODY_BYTES + 1))
        assert r.status_code == 413

    async def test_bad_content_length_is_400(self):
        status = {}

        async def app_(scope, receive, send):  # pragma: no cover - must not run
            raise AssertionError("app should not be called")

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        async def send(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]

        mw = BodySizeLimitMiddleware(app_, max_bytes=10)
        scope = {"type": "http", "method": "POST", "headers": [(b"content-length", b"abc")]}
        await mw(scope, receive, send)
        assert status["code"] == 400

    async def test_small_chunked_body_reaches_the_app_intact(self, client):
        import json as _json

        async def body():
            payload = _json.dumps({"agent_id": "a", "capabilities": []}).encode()
            yield payload[:5]
            yield payload[5:]

        r = await client.post(
            "/economy/strategies/select", content=body(), headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["agent_id"] == "a"

    async def test_body_at_exact_limit_passes_middleware(self):
        seen = {}

        async def app_(scope, receive, send):
            chunks = []
            while True:
                m = await receive()
                chunks.append(m.get("body", b""))
                if not m.get("more_body"):
                    break
            seen["body"] = b"".join(chunks)

        msgs = [
            {"type": "http.request", "body": b"a" * 6, "more_body": True},
            {"type": "http.request", "body": b"a" * 4, "more_body": False},
        ]

        async def receive():
            return msgs.pop(0)

        async def send(msg):  # pragma: no cover - app sends nothing
            pass

        mw = BodySizeLimitMiddleware(app_, max_bytes=10)
        await mw({"type": "http", "method": "POST", "headers": []}, receive, send)
        assert seen["body"] == b"a" * 10
