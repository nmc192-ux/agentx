"""
Tests: GET /.well-known/skill.md — what it tells a new agent about tokens.

Sprint 9 (S9-7c): the document promised "a funded wallet (100 AXP)" and sent
agents to a wallet route that did not exist. External agents act on this
text, so the claims are pinned here.
"""
from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture
async def skill_md() -> str:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        resp = await client.get("/.well-known/skill.md")
    assert resp.status_code == 200
    return resp.text


@pytest.mark.asyncio
async def test_does_not_promise_a_funded_wallet(skill_md):
    lowered = skill_md.lower()
    assert "funds your wallet" not in lowered
    assert "funded wallet" not in lowered
    assert "100 axp" not in lowered
    assert '"wallet_balance":  0' in skill_md
    assert "starts at **0 AXP**" in skill_md


@pytest.mark.asyncio
async def test_wallet_commands_name_routes_that_exist(skill_md):
    routes = {(m, r.path) for r in app.routes for m in (getattr(r, "methods", None) or [])}
    economy = skill_md.split("## Economy")[1].split("## Governance")[0]
    paths = set(re.findall(r'"http://testserver(/[^"?]*)', economy))
    assert paths == {"/wallets", "/wallets/by-did"}
    assert ("POST", "/wallets") in routes
    assert ("GET", "/wallets/by-did") in routes


@pytest.mark.asyncio
async def test_template_renders_without_leftover_placeholders(skill_md):
    assert "{base_url}" not in skill_md
    assert "-d '{}'" in skill_md
