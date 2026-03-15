"""
Tests: markets router (Phase 15)
══════════════════════════════════════════════════════════════════════════════
Covers:
  POST /markets/bounties          — create bounty (auth required)
  GET  /markets/bounties          — list bounties (public)
  GET  /markets/bounties/{id}     — get bounty (public)
  POST /markets/bounties/{id}/submit — submit solution (auth required)
  GET  /markets/bounties/{id}/submissions — list submissions (public)
  POST /markets/bounties/{id}/submissions/{sid}/evaluate — evaluate (auth)
  POST /markets/bounties/{id}/distribute — distribute rewards (auth)

All service calls and auth are mocked; no live DB/Redis required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.models.markets import BountyResponse, RewardResponse, SubmissionResponse

client = TestClient(app, raise_server_exceptions=False)

# ── Shared fixtures ───────────────────────────────────────────────────────────

_CREATOR_DID = "did:agentx:creator"
_AGENT_DID   = "did:agentx:agent"

MOCK_AGENT = MagicMock()
MOCK_AGENT.did = _CREATOR_DID


def _make_bounty(status="open"):
    return BountyResponse(
        bounty_id=uuid4(),
        creator_did=_CREATOR_DID,
        title="Test Bounty",
        description="A test",
        capability_required="collect_data",
        reward_pool=1000,
        status=status,
        created_at="2026-01-01T00:00:00Z",
    )


def _make_submission(status="pending"):
    return SubmissionResponse(
        submission_id=uuid4(),
        bounty_id=uuid4(),
        submitter_did=_AGENT_DID,
        solution_data={"result": "ok"},
        status=status,
        submitted_at="2026-01-01T00:00:00Z",
    )


def _make_reward():
    return RewardResponse(
        reward_id=uuid4(),
        bounty_id=uuid4(),
        submission_id=uuid4(),
        recipient_did=_AGENT_DID,
        amount=1000,
        distributed_at="2026-01-01T00:00:00Z",
    )


def _auth():
    """Override get_current_agent for all authenticated routes."""
    from src.auth.middleware import get_current_agent
    app.dependency_overrides[get_current_agent] = lambda: MOCK_AGENT


def _clear_auth():
    app.dependency_overrides.clear()


# ═════════════════════════════════════════════════════════════════════════════
# POST /markets/bounties — create
# ═════════════════════════════════════════════════════════════════════════════

class TestCreateBountyEndpoint:

    def setup_method(self):
        _auth()

    def teardown_method(self):
        _clear_auth()

    def test_create_returns_201(self):
        bounty = _make_bounty()
        with patch(
            "src.routers.markets.bounty_service.create_bounty",
            new_callable=AsyncMock,
            return_value=bounty,
        ):
            resp = client.post(
                "/markets/bounties",
                json={
                    "title": "Test",
                    "capability_required": "collect_data",
                    "reward_pool": 1000,
                },
            )
        assert resp.status_code == 201

    def test_create_returns_bounty_id(self):
        bounty = _make_bounty()
        with patch(
            "src.routers.markets.bounty_service.create_bounty",
            new_callable=AsyncMock,
            return_value=bounty,
        ):
            resp = client.post(
                "/markets/bounties",
                json={
                    "title": "Test",
                    "capability_required": "collect_data",
                    "reward_pool": 1000,
                },
            )
        data = resp.json()
        assert "bounty_id" in data
        assert data["bounty_id"] == str(bounty.bounty_id)

    def test_create_insufficient_funds_returns_400(self):
        with patch(
            "src.routers.markets.bounty_service.create_bounty",
            new_callable=AsyncMock,
            side_effect=ValueError("Insufficient funds"),
        ):
            resp = client.post(
                "/markets/bounties",
                json={"title": "T", "capability_required": "x", "reward_pool": 99999},
            )
        assert resp.status_code == 400

    def test_create_unauthenticated_returns_401(self):
        _clear_auth()
        resp = client.post(
            "/markets/bounties",
            json={"title": "T", "capability_required": "x", "reward_pool": 100},
        )
        assert resp.status_code in (401, 403, 422)

    def test_create_missing_required_fields_returns_422(self):
        resp = client.post("/markets/bounties", json={"title": "No pool"})
        assert resp.status_code == 422


# ═════════════════════════════════════════════════════════════════════════════
# GET /markets/bounties — list
# ═════════════════════════════════════════════════════════════════════════════

class TestListBountiesEndpoint:

    def test_list_returns_200(self):
        with patch(
            "src.routers.markets.bounty_service.list_bounties",
            new_callable=AsyncMock,
            return_value=[_make_bounty(), _make_bounty()],
        ):
            resp = client.get("/markets/bounties")
        assert resp.status_code == 200

    def test_list_returns_list(self):
        with patch(
            "src.routers.markets.bounty_service.list_bounties",
            new_callable=AsyncMock,
            return_value=[_make_bounty(), _make_bounty()],
        ):
            resp = client.get("/markets/bounties")
        assert isinstance(resp.json(), list)
        assert len(resp.json()) == 2

    def test_list_passes_status_filter(self):
        mock_list = AsyncMock(return_value=[])
        with patch("src.routers.markets.bounty_service.list_bounties", mock_list):
            client.get("/markets/bounties?status=open")
        mock_list.assert_called_once_with(status="open", capability=None)

    def test_list_passes_capability_filter(self):
        mock_list = AsyncMock(return_value=[])
        with patch("src.routers.markets.bounty_service.list_bounties", mock_list):
            client.get("/markets/bounties?capability=collect_data")
        mock_list.assert_called_once_with(status=None, capability="collect_data")

    def test_list_is_public(self):
        """No auth required for listing."""
        with patch(
            "src.routers.markets.bounty_service.list_bounties",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/markets/bounties")
        assert resp.status_code == 200


# ═════════════════════════════════════════════════════════════════════════════
# GET /markets/bounties/{id} — get
# ═════════════════════════════════════════════════════════════════════════════

class TestGetBountyEndpoint:

    def test_get_returns_200(self):
        bounty = _make_bounty()
        with patch(
            "src.routers.markets.bounty_service.get_bounty",
            new_callable=AsyncMock,
            return_value=bounty,
        ):
            resp = client.get(f"/markets/bounties/{bounty.bounty_id}")
        assert resp.status_code == 200

    def test_get_returns_correct_bounty(self):
        bounty = _make_bounty()
        with patch(
            "src.routers.markets.bounty_service.get_bounty",
            new_callable=AsyncMock,
            return_value=bounty,
        ):
            resp = client.get(f"/markets/bounties/{bounty.bounty_id}")
        assert resp.json()["bounty_id"] == str(bounty.bounty_id)

    def test_get_missing_returns_404(self):
        with patch(
            "src.routers.markets.bounty_service.get_bounty",
            new_callable=AsyncMock,
            side_effect=ValueError("Bounty not found"),
        ):
            resp = client.get(f"/markets/bounties/{uuid4()}")
        assert resp.status_code == 404

    def test_get_is_public(self):
        """No auth required."""
        bounty = _make_bounty()
        with patch(
            "src.routers.markets.bounty_service.get_bounty",
            new_callable=AsyncMock,
            return_value=bounty,
        ):
            resp = client.get(f"/markets/bounties/{bounty.bounty_id}")
        assert resp.status_code == 200


# ═════════════════════════════════════════════════════════════════════════════
# POST /markets/bounties/{id}/submit
# ═════════════════════════════════════════════════════════════════════════════

class TestSubmitSolutionEndpoint:

    def setup_method(self):
        _auth()

    def teardown_method(self):
        _clear_auth()

    def test_submit_returns_201(self):
        submission = _make_submission()
        with patch(
            "src.routers.markets.bounty_service.submit_solution",
            new_callable=AsyncMock,
            return_value=submission,
        ):
            resp = client.post(
                f"/markets/bounties/{uuid4()}/submit",
                json={"solution_data": {"result": "ok"}},
            )
        assert resp.status_code == 201

    def test_submit_returns_submission_id(self):
        submission = _make_submission()
        with patch(
            "src.routers.markets.bounty_service.submit_solution",
            new_callable=AsyncMock,
            return_value=submission,
        ):
            resp = client.post(
                f"/markets/bounties/{uuid4()}/submit",
                json={"solution_data": {"result": "ok"}},
            )
        assert "submission_id" in resp.json()

    def test_submit_missing_bounty_returns_404(self):
        with patch(
            "src.routers.markets.bounty_service.submit_solution",
            new_callable=AsyncMock,
            side_effect=ValueError("Bounty not found"),
        ):
            resp = client.post(
                f"/markets/bounties/{uuid4()}/submit",
                json={"solution_data": {}},
            )
        assert resp.status_code == 404

    def test_submit_closed_bounty_returns_400(self):
        with patch(
            "src.routers.markets.bounty_service.submit_solution",
            new_callable=AsyncMock,
            side_effect=ValueError("Bounty is not open"),
        ):
            resp = client.post(
                f"/markets/bounties/{uuid4()}/submit",
                json={"solution_data": {}},
            )
        assert resp.status_code == 400


# ═════════════════════════════════════════════════════════════════════════════
# GET /markets/bounties/{id}/submissions
# ═════════════════════════════════════════════════════════════════════════════

class TestListSubmissionsEndpoint:

    def test_list_submissions_returns_200(self):
        bid = uuid4()
        with patch(
            "src.routers.markets.bounty_service.list_submissions",
            new_callable=AsyncMock,
            return_value=[_make_submission(), _make_submission()],
        ):
            resp = client.get(f"/markets/bounties/{bid}/submissions")
        assert resp.status_code == 200

    def test_list_submissions_is_public(self):
        bid = uuid4()
        with patch(
            "src.routers.markets.bounty_service.list_submissions",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get(f"/markets/bounties/{bid}/submissions")
        assert resp.status_code == 200

    def test_list_submissions_missing_bounty_returns_404(self):
        with patch(
            "src.routers.markets.bounty_service.list_submissions",
            new_callable=AsyncMock,
            side_effect=ValueError("Bounty not found"),
        ):
            resp = client.get(f"/markets/bounties/{uuid4()}/submissions")
        assert resp.status_code == 404


# ═════════════════════════════════════════════════════════════════════════════
# POST /markets/bounties/{id}/submissions/{sid}/evaluate
# ═════════════════════════════════════════════════════════════════════════════

class TestEvaluateEndpoint:

    def setup_method(self):
        _auth()

    def teardown_method(self):
        _clear_auth()

    def test_evaluate_returns_200(self):
        sub = _make_submission(status="evaluated")
        with patch(
            "src.routers.markets.bounty_service.evaluate_submission",
            new_callable=AsyncMock,
            return_value=sub,
        ):
            resp = client.post(
                f"/markets/bounties/{uuid4()}/submissions/{uuid4()}/evaluate",
                json={"score": 0.85},
            )
        assert resp.status_code == 200

    def test_evaluate_non_creator_returns_400(self):
        with patch(
            "src.routers.markets.bounty_service.evaluate_submission",
            new_callable=AsyncMock,
            side_effect=ValueError("Only the bounty creator"),
        ):
            resp = client.post(
                f"/markets/bounties/{uuid4()}/submissions/{uuid4()}/evaluate",
                json={"score": 0.5},
            )
        assert resp.status_code == 400

    def test_evaluate_invalid_score_returns_422(self):
        resp = client.post(
            f"/markets/bounties/{uuid4()}/submissions/{uuid4()}/evaluate",
            json={"score": 2.0},  # > 1.0
        )
        assert resp.status_code == 422


# ═════════════════════════════════════════════════════════════════════════════
# POST /markets/bounties/{id}/distribute
# ═════════════════════════════════════════════════════════════════════════════

class TestDistributeEndpoint:

    def setup_method(self):
        _auth()

    def teardown_method(self):
        _clear_auth()

    def test_distribute_returns_200(self):
        reward = _make_reward()
        with patch(
            "src.routers.markets.bounty_service.distribute_rewards",
            new_callable=AsyncMock,
            return_value=reward,
        ):
            resp = client.post(f"/markets/bounties/{uuid4()}/distribute")
        assert resp.status_code == 200

    def test_distribute_returns_reward_data(self):
        reward = _make_reward()
        with patch(
            "src.routers.markets.bounty_service.distribute_rewards",
            new_callable=AsyncMock,
            return_value=reward,
        ):
            resp = client.post(f"/markets/bounties/{uuid4()}/distribute")
        data = resp.json()
        assert "reward_id" in data
        assert "amount" in data
        assert data["amount"] == reward.amount

    def test_distribute_non_creator_returns_400(self):
        with patch(
            "src.routers.markets.bounty_service.distribute_rewards",
            new_callable=AsyncMock,
            side_effect=ValueError("Only the bounty creator"),
        ):
            resp = client.post(f"/markets/bounties/{uuid4()}/distribute")
        assert resp.status_code == 400

    def test_distribute_already_rewarded_returns_400(self):
        with patch(
            "src.routers.markets.bounty_service.distribute_rewards",
            new_callable=AsyncMock,
            side_effect=ValueError("rewards already distributed"),
        ):
            resp = client.post(f"/markets/bounties/{uuid4()}/distribute")
        assert resp.status_code == 400

    def test_distribute_no_submissions_returns_400(self):
        with patch(
            "src.routers.markets.bounty_service.distribute_rewards",
            new_callable=AsyncMock,
            side_effect=ValueError("No evaluated submissions"),
        ):
            resp = client.post(f"/markets/bounties/{uuid4()}/distribute")
        assert resp.status_code == 400
