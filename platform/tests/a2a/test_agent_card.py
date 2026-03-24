"""
Tests: A2A Agent Card generation and router endpoints
  platform/src/a2a/agent_card.py
  platform/src/a2a/router.py

Coverage:
  AgentCard model          — required fields, defaults, serialisation
  generate_agent_card()    — skills from specialization + capabilities, DID encoding
  generate_platform_card() — platform-level card structure
  GET /.well-known/agent.json             — platform card endpoint
  GET /agents/{did}/.well-known/agent.json — per-agent card, 404 on unknown DID
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.a2a.agent_card import (
    A2AAuthentication,
    A2ACapabilities,
    A2ASkill,
    AgentCard,
    generate_agent_card,
    generate_platform_card,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

AGENT_DID   = "did:agentx:testbot-001"
DISPLAY_NAME = "TestBot"
BASE_URL    = "http://testserver"


def _db_ctx(row):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=_conn(row))
    ctx.__aexit__  = AsyncMock(return_value=None)
    return ctx


def _conn(row):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    return conn


def _agent_row(**overrides):
    base = {
        "agent_did":      AGENT_DID,
        "display_name":   DISPLAY_NAME,
        "specialization": "data_analysis, nlp",
        "capabilities":   '["summarise", "classify"]',
        "bio":            "A test agent",
    }
    base.update(overrides)
    return base


# ── AgentCard model ───────────────────────────────────────────────────────────

class TestAgentCardModel:

    def test_minimal_card_with_required_fields(self):
        card = AgentCard(
            name="MyBot",
            description="Does things",
            url="http://example.com",
        )
        assert card.name == "MyBot"
        assert card.version == "0.3"
        assert card.defaultInputModes == ["text"]
        assert card.defaultOutputModes == ["text"]

    def test_capabilities_defaults(self):
        caps = A2ACapabilities()
        assert caps.streaming is True
        assert caps.pushNotifications is True
        assert caps.stateTransitionHistory is False

    def test_skill_defaults(self):
        skill = A2ASkill(id="code_review", name="Code Review", description="Reviews code")
        assert skill.tags == []
        assert skill.examples == []
        assert skill.inputModes == ["text"]
        assert skill.outputModes == ["text"]

    def test_authentication_default_scheme(self):
        auth = A2AAuthentication()
        assert "bearer" in auth.schemes

    def test_card_serialises_to_dict(self):
        card = AgentCard(name="X", description="Y", url="http://x.com")
        data = card.model_dump(exclude_none=True)
        assert data["name"] == "X"
        assert "capabilities" in data
        assert "authentication" in data


# ── generate_agent_card() ─────────────────────────────────────────────────────

class TestGenerateAgentCard:

    def test_basic_card_generation(self):
        card = generate_agent_card(
            agent_did=AGENT_DID,
            display_name=DISPLAY_NAME,
            base_url=BASE_URL,
        )
        assert card.name == DISPLAY_NAME
        assert AGENT_DID.replace(":", "%3A") in card.url
        assert card.version == "0.3"

    def test_specialization_becomes_skills(self):
        card = generate_agent_card(
            agent_did=AGENT_DID,
            display_name=DISPLAY_NAME,
            specialization="data analysis, nlp, forecasting",
            base_url=BASE_URL,
        )
        skill_ids = {s.id for s in card.skills}
        assert "data_analysis" in skill_ids
        assert "nlp" in skill_ids
        assert "forecasting" in skill_ids

    def test_capabilities_list_becomes_skills(self):
        card = generate_agent_card(
            agent_did=AGENT_DID,
            display_name=DISPLAY_NAME,
            capabilities_list=["summarise", "classify"],
            base_url=BASE_URL,
        )
        skill_ids = {s.id for s in card.skills}
        assert "summarise" in skill_ids
        assert "classify" in skill_ids

    def test_duplicate_skills_deduplicated(self):
        card = generate_agent_card(
            agent_did=AGENT_DID,
            display_name=DISPLAY_NAME,
            specialization="nlp",
            capabilities_list=["nlp"],   # same as specialization
            base_url=BASE_URL,
        )
        ids = [s.id for s in card.skills]
        assert ids.count("nlp") == 1

    def test_bio_used_as_description(self):
        card = generate_agent_card(
            agent_did=AGENT_DID,
            display_name=DISPLAY_NAME,
            bio="I am a helpful agent",
            base_url=BASE_URL,
        )
        assert card.description == "I am a helpful agent"

    def test_fallback_description_when_no_bio(self):
        card = generate_agent_card(
            agent_did=AGENT_DID,
            display_name=DISPLAY_NAME,
            base_url=BASE_URL,
        )
        assert DISPLAY_NAME in card.description or AGENT_DID in card.description

    def test_no_skills_when_empty_inputs(self):
        card = generate_agent_card(
            agent_did=AGENT_DID,
            display_name=DISPLAY_NAME,
            specialization=None,
            capabilities_list=[],
            base_url=BASE_URL,
        )
        assert card.skills == []

    def test_provider_set_to_agentx(self):
        card = generate_agent_card(
            agent_did=AGENT_DID,
            display_name=DISPLAY_NAME,
            base_url=BASE_URL,
        )
        assert card.provider is not None
        assert "AgentX" in card.provider.organization

    def test_authentication_uses_bearer(self):
        card = generate_agent_card(
            agent_did=AGENT_DID,
            display_name=DISPLAY_NAME,
            base_url=BASE_URL,
        )
        assert "bearer" in card.authentication.schemes


# ── generate_platform_card() ──────────────────────────────────────────────────

class TestGeneratePlatformCard:

    def test_platform_card_structure(self):
        card = generate_platform_card(base_url=BASE_URL)
        assert card.name == "AgentX Platform"
        assert card.version == "0.3"
        assert card.url == BASE_URL

    def test_platform_card_has_skills(self):
        card = generate_platform_card(base_url=BASE_URL)
        assert len(card.skills) > 0
        skill_ids = {s.id for s in card.skills}
        assert "agent_discovery" in skill_ids
        assert "contract_marketplace" in skill_ids
        assert "trust_scoring" in skill_ids

    def test_platform_card_state_transition_history(self):
        card = generate_platform_card(base_url=BASE_URL)
        assert card.capabilities.stateTransitionHistory is True

    def test_platform_card_documentation_url(self):
        card = generate_platform_card(base_url=BASE_URL)
        assert card.documentationUrl is not None
        assert "/docs" in card.documentationUrl


# ── Router endpoints ──────────────────────────────────────────────────────────

@pytest.fixture
def test_client():
    """Create a FastAPI test client with the a2a_router mounted."""
    from fastapi import FastAPI
    from src.a2a.router import a2a_router

    app = FastAPI()
    app.include_router(a2a_router)
    return TestClient(app)


class TestA2ARouterPlatformCard:

    def test_platform_card_returns_200(self, test_client):
        resp = test_client.get("/.well-known/agent.json")
        assert resp.status_code == 200

    def test_platform_card_content_type_json(self, test_client):
        resp = test_client.get("/.well-known/agent.json")
        assert "application/json" in resp.headers["content-type"]

    def test_platform_card_has_required_fields(self, test_client):
        data = test_client.get("/.well-known/agent.json").json()
        for field in ("name", "description", "url", "version", "capabilities",
                      "skills", "authentication"):
            assert field in data, f"missing field: {field}"

    def test_platform_card_version(self, test_client):
        data = test_client.get("/.well-known/agent.json").json()
        assert data["version"] == "0.3"

    def test_platform_card_cache_header(self, test_client):
        resp = test_client.get("/.well-known/agent.json")
        assert "Cache-Control" in resp.headers


class TestA2ARouterAgentCard:

    def test_agent_card_returns_200_for_known_agent(self, test_client):
        row = _agent_row()
        with patch("src.a2a.router.get_db", return_value=_db_ctx(row)):
            resp = test_client.get(f"/agents/{AGENT_DID}/.well-known/agent.json")
        assert resp.status_code == 200

    def test_agent_card_has_correct_name(self, test_client):
        row = _agent_row()
        with patch("src.a2a.router.get_db", return_value=_db_ctx(row)):
            data = test_client.get(
                f"/agents/{AGENT_DID}/.well-known/agent.json"
            ).json()
        assert data["name"] == DISPLAY_NAME

    def test_agent_card_includes_skills_from_specialization(self, test_client):
        row = _agent_row(specialization="data_analysis, nlp")
        with patch("src.a2a.router.get_db", return_value=_db_ctx(row)):
            data = test_client.get(
                f"/agents/{AGENT_DID}/.well-known/agent.json"
            ).json()
        skill_ids = [s["id"] for s in data.get("skills", [])]
        assert "data_analysis" in skill_ids
        assert "nlp" in skill_ids

    def test_agent_card_parses_json_capabilities_string(self, test_client):
        row = _agent_row(capabilities='["summarise", "classify"]')
        with patch("src.a2a.router.get_db", return_value=_db_ctx(row)):
            data = test_client.get(
                f"/agents/{AGENT_DID}/.well-known/agent.json"
            ).json()
        skill_ids = [s["id"] for s in data.get("skills", [])]
        assert "summarise" in skill_ids
        assert "classify" in skill_ids

    def test_agent_card_handles_list_capabilities(self, test_client):
        row = _agent_row(capabilities=["summarise", "classify"])
        with patch("src.a2a.router.get_db", return_value=_db_ctx(row)):
            data = test_client.get(
                f"/agents/{AGENT_DID}/.well-known/agent.json"
            ).json()
        skill_ids = [s["id"] for s in data.get("skills", [])]
        assert "summarise" in skill_ids

    def test_agent_card_404_for_unknown_agent(self, test_client):
        with patch("src.a2a.router.get_db", return_value=_db_ctx(None)):
            resp = test_client.get(
                "/agents/did:agentx:unknown-001/.well-known/agent.json"
            )
        assert resp.status_code == 404

    def test_agent_card_404_detail_mentions_did(self, test_client):
        with patch("src.a2a.router.get_db", return_value=_db_ctx(None)):
            data = test_client.get(
                "/agents/did:agentx:ghost-001/.well-known/agent.json"
            ).json()
        assert "ghost-001" in str(data.get("detail", ""))

    def test_agent_card_handles_null_specialization(self, test_client):
        row = _agent_row(specialization=None, capabilities="[]")
        with patch("src.a2a.router.get_db", return_value=_db_ctx(row)):
            data = test_client.get(
                f"/agents/{AGENT_DID}/.well-known/agent.json"
            ).json()
        assert data["skills"] == []

    def test_agent_card_uses_bio_as_description(self, test_client):
        row = _agent_row(bio="Expert in time-series forecasting")
        with patch("src.a2a.router.get_db", return_value=_db_ctx(row)):
            data = test_client.get(
                f"/agents/{AGENT_DID}/.well-known/agent.json"
            ).json()
        assert "time-series" in data["description"]

    def test_agent_card_version_is_a2a_spec(self, test_client):
        row = _agent_row()
        with patch("src.a2a.router.get_db", return_value=_db_ctx(row)):
            data = test_client.get(
                f"/agents/{AGENT_DID}/.well-known/agent.json"
            ).json()
        assert data["version"] == "0.3"
