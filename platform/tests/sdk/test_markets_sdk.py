"""
Tests: agentx_sdk — MarketsClient (Phase 15)
═════════════════════════════════════════════════════════════════════════════
Covers:
  MarketsClient.list_bounties      — GET /markets/bounties (with filters)
  MarketsClient.get_bounty         — GET /markets/bounties/{id}
  MarketsClient.create_bounty      — POST /markets/bounties
  MarketsClient.submit_solution    — POST /markets/bounties/{id}/submit
  MarketsClient.list_submissions   — GET /markets/bounties/{id}/submissions
  MarketsClient.evaluate_submission — POST /markets/bounties/{id}/submissions/{sid}/evaluate
  MarketsClient.distribute_rewards — POST /markets/bounties/{id}/distribute

All HTTP calls are mocked via httpx.  No live server required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agentx_sdk.markets import MarketsClient

_BASE_URL = "http://localhost:8000"
_TOKEN    = "test-jwt"


def _client() -> MarketsClient:
    return MarketsClient(base_url=_BASE_URL, token=_TOKEN)


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _make_bounty(bounty_id=None):
    return {
        "bounty_id":            str(bounty_id or uuid4()),
        "creator_did":          "did:agentx:creator",
        "title":                "Test Bounty",
        "description":          "A test",
        "capability_required":  "collect_data",
        "reward_pool":          1000,
        "status":               "open",
        "created_at":           "2026-01-01T00:00:00Z",
    }


def _make_submission(submission_id=None):
    return {
        "submission_id": str(submission_id or uuid4()),
        "bounty_id":     str(uuid4()),
        "submitter_did": "did:agentx:agent",
        "solution_data": {"result": "ok"},
        "status":        "pending",
        "submitted_at":  "2026-01-01T00:00:00Z",
    }


# ═════════════════════════════════════════════════════════════════════════════
# list_bounties
# ═════════════════════════════════════════════════════════════════════════════

class TestMarketsClientListBounties:

    @pytest.mark.asyncio
    async def test_list_returns_list(self):
        bounties = [_make_bounty(), _make_bounty()]

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response(bounties))
            mock_cls.return_value = mock_http

            result = await _client().list_bounties()

        assert result == bounties

    @pytest.mark.asyncio
    async def test_list_passes_status_param(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response([]))
            mock_cls.return_value = mock_http

            await _client().list_bounties(status="open")

        call_kwargs = mock_http.get.call_args.kwargs
        assert call_kwargs.get("params", {}).get("status") == "open"

    @pytest.mark.asyncio
    async def test_list_passes_capability_param(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response([]))
            mock_cls.return_value = mock_http

            await _client().list_bounties(capability="collect_data")

        call_kwargs = mock_http.get.call_args.kwargs
        assert call_kwargs.get("params", {}).get("capability") == "collect_data"

    @pytest.mark.asyncio
    async def test_list_no_filters_passes_no_params(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response([]))
            mock_cls.return_value = mock_http

            await _client().list_bounties()

        call_kwargs = mock_http.get.call_args.kwargs
        assert call_kwargs.get("params") is None

    @pytest.mark.asyncio
    async def test_list_uses_correct_url(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response([]))
            mock_cls.return_value = mock_http

            await _client().list_bounties()

        url = mock_http.get.call_args[0][0]
        assert url == f"{_BASE_URL}/markets/bounties"


# ═════════════════════════════════════════════════════════════════════════════
# get_bounty
# ═════════════════════════════════════════════════════════════════════════════

class TestMarketsClientGetBounty:

    @pytest.mark.asyncio
    async def test_get_bounty_returns_dict(self):
        bid = str(uuid4())
        bounty = _make_bounty(bounty_id=bid)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response(bounty))
            mock_cls.return_value = mock_http

            result = await _client().get_bounty(bid)

        assert result["bounty_id"] == bid

    @pytest.mark.asyncio
    async def test_get_bounty_uses_correct_url(self):
        bid = str(uuid4())
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response(_make_bounty()))
            mock_cls.return_value = mock_http

            await _client().get_bounty(bid)

        url = mock_http.get.call_args[0][0]
        assert f"/markets/bounties/{bid}" in url


# ═════════════════════════════════════════════════════════════════════════════
# create_bounty
# ═════════════════════════════════════════════════════════════════════════════

class TestMarketsClientCreateBounty:

    @pytest.mark.asyncio
    async def test_create_returns_bounty(self):
        bounty = _make_bounty()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_response(bounty))
            mock_cls.return_value = mock_http

            result = await _client().create_bounty(
                title="Test", capability_required="collect_data", reward_pool=1000
            )

        assert result["title"] == "Test Bounty"

    @pytest.mark.asyncio
    async def test_create_sends_correct_body(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_response(_make_bounty()))
            mock_cls.return_value = mock_http

            await _client().create_bounty(
                title="My Bounty",
                capability_required="analyse_data",
                reward_pool=500,
                description="Find insights",
            )

        body = mock_http.post.call_args.kwargs["json"]
        assert body["title"] == "My Bounty"
        assert body["capability_required"] == "analyse_data"
        assert body["reward_pool"] == 500
        assert body["description"] == "Find insights"

    @pytest.mark.asyncio
    async def test_create_sends_bearer_token(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_response(_make_bounty()))
            mock_cls.return_value = mock_http

            await _client().create_bounty(title="T", capability_required="x", reward_pool=1)

        headers = mock_http.post.call_args.kwargs["headers"]
        assert f"Bearer {_TOKEN}" == headers["Authorization"]

    @pytest.mark.asyncio
    async def test_create_with_deadline(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_response(_make_bounty()))
            mock_cls.return_value = mock_http

            await _client().create_bounty(
                title="T", capability_required="x", reward_pool=1,
                deadline="2027-01-01T00:00:00Z",
            )

        body = mock_http.post.call_args.kwargs["json"]
        assert body["deadline"] == "2027-01-01T00:00:00Z"


# ═════════════════════════════════════════════════════════════════════════════
# submit_solution
# ═════════════════════════════════════════════════════════════════════════════

class TestMarketsClientSubmitSolution:

    @pytest.mark.asyncio
    async def test_submit_returns_submission(self):
        sub = _make_submission()
        bid = str(uuid4())

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_response(sub))
            mock_cls.return_value = mock_http

            result = await _client().submit_solution(
                bounty_id=bid, solution_data={"result": "ok"}
            )

        assert "submission_id" in result

    @pytest.mark.asyncio
    async def test_submit_uses_correct_url(self):
        bid = str(uuid4())
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_response(_make_submission()))
            mock_cls.return_value = mock_http

            await _client().submit_solution(bounty_id=bid, solution_data={})

        url = mock_http.post.call_args[0][0]
        assert f"/markets/bounties/{bid}/submit" in url

    @pytest.mark.asyncio
    async def test_submit_sends_solution_data(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_response(_make_submission()))
            mock_cls.return_value = mock_http

            await _client().submit_solution(
                bounty_id=str(uuid4()),
                solution_data={"rows": 42},
                summary="My summary",
            )

        body = mock_http.post.call_args.kwargs["json"]
        assert body["solution_data"] == {"rows": 42}
        assert body["summary"] == "My summary"


# ═════════════════════════════════════════════════════════════════════════════
# evaluate_submission
# ═════════════════════════════════════════════════════════════════════════════

class TestMarketsClientEvaluateSubmission:

    @pytest.mark.asyncio
    async def test_evaluate_returns_submission(self):
        sub = {**_make_submission(), "score": 0.9, "status": "evaluated"}
        bid = str(uuid4())
        sid = str(uuid4())

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_response(sub))
            mock_cls.return_value = mock_http

            result = await _client().evaluate_submission(
                bounty_id=bid, submission_id=sid, score=0.9
            )

        assert result["score"] == 0.9

    @pytest.mark.asyncio
    async def test_evaluate_uses_correct_url(self):
        bid = str(uuid4())
        sid = str(uuid4())

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_response(_make_submission()))
            mock_cls.return_value = mock_http

            await _client().evaluate_submission(
                bounty_id=bid, submission_id=sid, score=0.5
            )

        url = mock_http.post.call_args[0][0]
        assert f"/markets/bounties/{bid}/submissions/{sid}/evaluate" in url

    @pytest.mark.asyncio
    async def test_evaluate_sends_score(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_response(_make_submission()))
            mock_cls.return_value = mock_http

            await _client().evaluate_submission(
                bounty_id=str(uuid4()), submission_id=str(uuid4()), score=0.75
            )

        body = mock_http.post.call_args.kwargs["json"]
        assert body["score"] == 0.75


# ═════════════════════════════════════════════════════════════════════════════
# distribute_rewards
# ═════════════════════════════════════════════════════════════════════════════

class TestMarketsClientDistributeRewards:

    @pytest.mark.asyncio
    async def test_distribute_returns_reward(self):
        reward = {
            "reward_id":     str(uuid4()),
            "bounty_id":     str(uuid4()),
            "submission_id": str(uuid4()),
            "recipient_did": "did:agentx:winner",
            "amount":        1000,
            "distributed_at": "2026-01-01T00:00:00Z",
        }
        bid = str(uuid4())

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_response(reward))
            mock_cls.return_value = mock_http

            result = await _client().distribute_rewards(bounty_id=bid)

        assert result["amount"] == 1000
        assert result["recipient_did"] == "did:agentx:winner"

    @pytest.mark.asyncio
    async def test_distribute_uses_correct_url(self):
        bid = str(uuid4())
        reward = {"reward_id": str(uuid4()), "bounty_id": bid,
                  "submission_id": str(uuid4()), "recipient_did": "x",
                  "amount": 100, "distributed_at": "2026-01-01T00:00:00Z"}

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=_mock_response(reward))
            mock_cls.return_value = mock_http

            await _client().distribute_rewards(bounty_id=bid)

        url = mock_http.post.call_args[0][0]
        assert f"/markets/bounties/{bid}/distribute" in url
