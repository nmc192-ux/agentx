"""
Tests: onboarding points at the token faucet (Phase C, Sprint 20, FC-2).

The faucet itself (FC-1) is tested in tests/test_faucet.py and, against
Postgres, in tests/integration/test_faucet_db.py. Here: the places that
TELL an agent about it — `/onboard` next_steps, the heartbeat's
`faucet_hint`, and `/.well-known/skill.md` — say so only while the faucet is
really on (FAUCET_ENABLED and the `wallets` router), say that tokens have no
outside value, and never write anything.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.a2a.skill import render_skill_md
from src.config import Settings, get_settings
from src.main import app
from src.services import faucet_service, heartbeat_service
from src.services.heartbeat_service import HeartbeatResult

AGENT_DID = "did:agentx:newcomer-001"
OTHER_DID = "did:agentx:someone-002"
AGENT_ID = uuid4()
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def _settings(enabled: str = "true", disabled_routers: str = "", **kw) -> Settings:
    return Settings(
        _env_file=None, faucet_enabled=enabled, disabled_routers=disabled_routers, **kw
    )


# ── faucet_available / faucet_terms / how_to_claim ────────────────────────────

class TestAvailability:
    def test_off_by_default(self):
        assert faucet_service.faucet_available(Settings(_env_file=None)) is False
        assert faucet_service.faucet_terms(Settings(_env_file=None)) is None

    def test_on(self):
        assert faucet_service.faucet_available(_settings()) is True

    def test_on_but_wallets_router_off_is_unavailable(self):
        s = _settings(disabled_routers="wallets")
        assert faucet_service.faucet_enabled(s) is True
        assert faucet_service.faucet_available(s) is False
        assert faucet_service.faucet_terms(s) is None

    @pytest.mark.parametrize("field", ["faucet_amount", "faucet_daily_budget"])
    def test_zero_amount_or_budget_is_unavailable(self, field):
        assert faucet_service.faucet_available(_settings(**{field: 0})) is False

    def test_terms_are_the_settings(self):
        s = _settings(faucet_amount=7, faucet_balance_ceiling=40,
                      faucet_min_age_minutes=120, faucet_daily_budget=300)
        assert faucet_service.faucet_terms(s) == {
            "amount": 7, "ceiling": 40, "min_age_minutes": 120, "budget": 300,
        }

    def test_how_to_claim_names_route_limits_and_no_outside_value(self):
        text = faucet_service.how_to_claim(_settings(faucet_amount=25))
        assert "POST /wallets/faucet" in text
        assert "25 free tokens" in text
        assert "no outside value" in text


# ── /onboard next_steps ───────────────────────────────────────────────────────

class TestOnboardNextSteps:
    def _steps(self, monkeypatch, settings) -> list[str]:
        from src.routers import onboard
        monkeypatch.setattr(onboard, "get_settings", lambda: settings)
        return onboard._build_next_steps(AGENT_DID, ["research"])

    def test_no_faucet_step_while_off(self, monkeypatch):
        steps = self._steps(monkeypatch, _settings(enabled="false"))
        assert not any("faucet" in s for s in steps)
        # The wallet step is still there, unchanged.
        assert any("starts at 0" in s for s in steps)

    def test_faucet_step_while_on(self, monkeypatch):
        steps = self._steps(monkeypatch, _settings())
        faucet = [s for s in steps if "/wallets/faucet" in s]
        assert len(faucet) == 1
        assert "no outside value" in faucet[0]
        # It follows the wallet step, which still says the wallet starts empty.
        wallet_i = next(i for i, s in enumerate(steps) if "starts at 0" in s)
        assert steps.index(faucet[0]) == wallet_i + 1

    def test_no_faucet_step_when_wallets_router_off(self, monkeypatch):
        steps = self._steps(monkeypatch, _settings(disabled_routers="wallets"))
        assert not any("faucet" in s or "wallet" in s.lower() for s in steps)

    def test_welcome_points_never_called_spendable(self):
        from src.routers.onboard import OnboardResponse
        desc = OnboardResponse.model_fields["welcome_points"].description
        assert "Not spendable" in desc


# ── faucet_service.claim_hint (read-only) ─────────────────────────────────────

def _conn(balance, claimed):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"balance": balance, "claimed": claimed})
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock()
    return conn


class TestClaimHint:
    async def test_off_reads_nothing(self):
        conn = _conn(0, False)
        assert await faucet_service.claim_hint(conn, AGENT_ID, settings=_settings("false")) is None
        conn.fetchrow.assert_not_awaited()

    async def test_wallets_router_off_reads_nothing(self):
        conn = _conn(0, False)
        hint = await faucet_service.claim_hint(
            conn, AGENT_ID, settings=_settings(disabled_routers="wallets"))
        assert hint is None
        conn.fetchrow.assert_not_awaited()

    @pytest.mark.parametrize("balance", [None, 0, 99])
    async def test_low_wallet_not_claimed_gets_hint(self, balance):
        conn = _conn(balance, False)
        hint = await faucet_service.claim_hint(conn, AGENT_ID, settings=_settings(), now=NOW)
        assert hint and "POST /wallets/faucet" in hint and "no outside value" in hint
        # Asked about today's UTC day, for this agent only.
        args = conn.fetchrow.await_args.args
        assert args[1] == AGENT_ID and args[2] == NOW.date()

    async def test_already_claimed_today_no_hint(self):
        hint = await faucet_service.claim_hint(_conn(0, True), AGENT_ID, settings=_settings())
        assert hint is None

    @pytest.mark.parametrize("balance", [100, 5000])
    async def test_wallet_at_or_above_ceiling_no_hint(self, balance):
        hint = await faucet_service.claim_hint(
            _conn(balance, False), AGENT_ID, settings=_settings(faucet_balance_ceiling=100))
        assert hint is None

    async def test_writes_nothing(self):
        conn = _conn(0, False)
        await faucet_service.claim_hint(conn, AGENT_ID, settings=_settings())
        conn.execute.assert_not_awaited()
        sql = conn.fetchrow.await_args.args[0].upper()
        for word in ("INSERT", "UPDATE", "DELETE", "FOR UPDATE", "ADVISORY"):
            assert word not in sql


# ── heartbeat ─────────────────────────────────────────────────────────────────

class TestHeartbeatServiceHint:
    async def test_hint_failure_does_not_break_heartbeat(self, monkeypatch):
        monkeypatch.setattr(
            faucet_service, "claim_hint", AsyncMock(side_effect=RuntimeError("no table")))
        assert await heartbeat_service._faucet_hint(MagicMock(), AGENT_ID) is None

    async def test_no_agent_id_no_query(self, monkeypatch):
        spy = AsyncMock(return_value="x")
        monkeypatch.setattr(faucet_service, "claim_hint", spy)
        assert await heartbeat_service._faucet_hint(MagicMock(), None) is None
        spy.assert_not_awaited()

    async def test_hint_passed_through(self, monkeypatch):
        monkeypatch.setattr(faucet_service, "claim_hint", AsyncMock(return_value="claim"))
        assert await heartbeat_service._faucet_hint(MagicMock(), AGENT_ID) == "claim"


def _record(did: str, role: str):
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = did
    return AgentRecord(
        row={"agent_did": did, "display_name": "X", "governance_role": role,
             "tier": "BOOTSTRAP", "status": "ACTIVE", "trust_score": 0.5},
        claims=claims,
    )


class TestHeartbeatRoute:
    async def _post(self, caller, body_did, hint):
        from src.auth.middleware import get_current_agent
        result = HeartbeatResult(acknowledged=True, suggested_action="browse_feed",
                                 faucet_hint=hint)
        app.dependency_overrides[get_current_agent] = lambda: caller
        try:
            with patch.object(heartbeat_service, "process_heartbeat",
                              new=AsyncMock(return_value=result)):
                async with AsyncClient(transport=ASGITransport(app=app),
                                       base_url="http://testserver") as c:
                    return await c.post("/heartbeat", json={
                        "agent_did": body_did, "status": "active", "capabilities": []})
        finally:
            app.dependency_overrides.pop(get_current_agent, None)

    async def test_own_heartbeat_carries_hint(self):
        resp = await self._post(_record(AGENT_DID, "MEMBER"), AGENT_DID, "claim it")
        assert resp.status_code == 200
        assert resp.json()["faucet_hint"] == "claim it"

    async def test_no_hint_is_null(self):
        resp = await self._post(_record(AGENT_DID, "MEMBER"), AGENT_DID, None)
        assert resp.json()["faucet_hint"] is None

    async def test_founder_heartbeat_for_another_agent_gets_no_hint(self):
        resp = await self._post(_record(AGENT_DID, "FOUNDER"), OTHER_DID, "claim it")
        assert resp.status_code == 200
        assert resp.json()["faucet_hint"] is None

    async def test_suggested_action_values_unchanged(self):
        """The hint is a new field; suggested_action keeps its four values so
        clients with a strict enum do not break."""
        from typing import get_args
        from src.routers.heartbeat import HeartbeatResponse
        ann = HeartbeatResponse.model_fields["suggested_action"].annotation
        literal = next(a for a in get_args(ann) if a is not type(None))
        assert set(get_args(literal)) == {
            "respond_to_task", "check_notifications", "post_update", "browse_feed"}


# ── skill.md ──────────────────────────────────────────────────────────────────

def _render(faucet, on=lambda name: True):
    return render_skill_md("https://api.example", on, access_token_ttl=3600,
                           refresh_token_ttl=86400 * 30, faucet=faucet)


class TestSkillMd:
    def test_no_faucet_section_when_off(self):
        assert "/wallets/faucet" not in _render(None)

    def test_faucet_section_when_on(self):
        doc = _render({"amount": 25, "ceiling": 100, "min_age_minutes": 60, "budget": 2000})
        assert 'curl -s -X POST "https://api.example/wallets/faucet"' in doc
        assert "claim\n25 free tokens once a day" in doc
        assert "less than 100" in doc and "from 1 hour after you" in doc
        assert "at most 2000 a day" in doc
        assert "**no outside value**" in doc
        # Inside the Economy section, before governance.
        assert doc.index("## Economy") < doc.index("/wallets/faucet")

    def test_no_faucet_when_wallets_router_off(self):
        doc = _render({"amount": 25, "ceiling": 100, "min_age_minutes": 60, "budget": 2000},
                      on=lambda name: name != "wallets")
        assert "/wallets/faucet" not in doc

    async def test_live_document_follows_the_switch(self, monkeypatch):
        settings = get_settings()
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://testserver") as c:
            monkeypatch.setattr(settings, "faucet_enabled", "false")
            off = (await c.get("/.well-known/skill.md")).text
            monkeypatch.setattr(settings, "faucet_enabled", "true")
            monkeypatch.setattr(settings, "faucet_amount", 25)
            monkeypatch.setattr(settings, "faucet_daily_budget", 2000)
            on = (await c.get("/.well-known/skill.md")).text
        assert "/wallets/faucet" not in off
        assert "/wallets/faucet" in on and "no outside value" in on


class TestStaticDocs:
    """The skill folder, quickstart and /join page name the faucet."""

    def _read(self, *parts):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        return root.joinpath(*parts).read_text()

    def test_skill_folder(self):
        text = self._read("skills", "agentx", "SKILL.md")
        # The skill only names ungated routes (test_skill_folder.py), so it
        # points at the heartbeat's hint rather than at the gated route.
        assert "faucet_hint" in text and "/wallets/faucet" not in text
        assert "no outside value" in text

    def test_quickstart(self):
        text = self._read("platform", "docs", "quickstart.md")
        assert "POST /wallets/faucet" in text and "no outside value" in text
        assert "off by default" in text

    def test_join_page_gated_by_flag(self):
        page = self._read("ui", "app", "join", "page.tsx")
        flags = self._read("ui", "lib", "flags.ts")
        assert "{FEATURE_FAUCET && (" in page
        assert "/wallets/faucet" in page and "no outside value" in page
        assert 'NEXT_PUBLIC_FEATURE_FAUCET        === "true"' in flags
