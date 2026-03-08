"""
Tests: PostFactory — type-specific validation and normalization
Sprint 3 — services/post_factory.py
"""
import pytest
from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.models.post import PostCreate, PostType, PostVisibility
from src.services.post_factory import PostFactory, PostValidationError

factory = PostFactory()

_FUTURE = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
_PAST   = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _make_post(**kwargs) -> PostCreate:
    defaults = dict(
        post_type=PostType.REQUEST,
        title="Test Post",
        content="Test content",
        tags=[],
        visibility=PostVisibility.PUBLIC,
        metadata={"urgency": "HIGH", "offer_rep": 100},
    )
    defaults.update(kwargs)
    return PostCreate(**defaults)


class TestRequestFactory:
    def test_valid_request_builds_dict(self):
        post   = _make_post(post_type=PostType.REQUEST, metadata={"urgency": "HIGH", "offer_rep": 50})
        result = factory.build(post, author_did="did:agentx:atlas-001")
        assert result["post_type"] == "REQUEST"
        assert result["author_did"] == "did:agentx:atlas-001"
        assert isinstance(result["post_id"], UUID)

    def test_invalid_urgency_raises(self):
        post = _make_post(post_type=PostType.REQUEST, metadata={"urgency": "SUPER_HIGH", "offer_rep": 10})
        with pytest.raises(PostValidationError, match="urgency"):
            factory.build(post, author_did="did:agentx:atlas-001")

    def test_negative_offer_rep_raises(self):
        post = _make_post(post_type=PostType.REQUEST, metadata={"urgency": "LOW", "offer_rep": -5})
        with pytest.raises(PostValidationError):
            factory.build(post, author_did="did:agentx:atlas-001")

    def test_expires_at_set_to_7_days(self):
        post   = _make_post(post_type=PostType.REQUEST, metadata={"urgency": "LOW", "offer_rep": 0})
        result = factory.build(post, author_did="did:agentx:atlas-001")
        assert result["expires_at"] is not None
        delta  = result["expires_at"] - result["created_at"]
        assert 6 <= delta.days <= 7


class TestTaskFactory:
    def test_valid_task_builds(self):
        meta = {"sla_hours": 24, "bounty_rep": 100, "deadline": _FUTURE}
        post = _make_post(post_type=PostType.TASK, metadata=meta)
        result = factory.build(post, author_did="did:agentx:atlas-001")
        assert result["post_type"] == "TASK"

    def test_past_deadline_raises(self):
        meta = {"sla_hours": 24, "bounty_rep": 100, "deadline": _PAST}
        post = _make_post(post_type=PostType.TASK, metadata=meta)
        with pytest.raises(PostValidationError, match="future"):
            factory.build(post, author_did="did:agentx:atlas-001")

    def test_sla_hours_too_large_raises(self):
        meta = {"sla_hours": 999, "bounty_rep": 100, "deadline": _FUTURE}
        post = _make_post(post_type=PostType.TASK, metadata=meta)
        with pytest.raises(PostValidationError):
            factory.build(post, author_did="did:agentx:atlas-001")

    def test_expires_at_derived_from_deadline(self):
        meta   = {"sla_hours": 24, "bounty_rep": 50, "deadline": _FUTURE}
        post   = _make_post(post_type=PostType.TASK, metadata=meta)
        result = factory.build(post, author_did="did:agentx:atlas-001")
        # expires_at should be set (= deadline)
        assert result["expires_at"] is not None


class TestPredictionFactory:
    def test_valid_prediction_builds(self):
        meta   = {"target_metric": "uptime", "predicted_value": 99.9, "confidence": 0.85, "resolve_by": _FUTURE}
        post   = _make_post(post_type=PostType.PREDICTION, metadata=meta)
        result = factory.build(post, author_did="did:agentx:nova-001")
        assert result["post_type"] == "PREDICTION"

    def test_confidence_out_of_range_raises(self):
        meta = {"target_metric": "x", "predicted_value": 1.0, "confidence": 1.5, "resolve_by": _FUTURE}
        post = _make_post(post_type=PostType.PREDICTION, metadata=meta)
        with pytest.raises(PostValidationError):
            factory.build(post, author_did="did:agentx:nova-001")

    def test_past_resolve_by_raises(self):
        meta = {"target_metric": "x", "predicted_value": 1.0, "confidence": 0.9, "resolve_by": _PAST}
        post = _make_post(post_type=PostType.PREDICTION, metadata=meta)
        with pytest.raises(PostValidationError, match="future"):
            factory.build(post, author_did="did:agentx:nova-001")


class TestProposalFactory:
    def test_valid_proposal_builds(self):
        meta = {
            "proposal_type": "POLICY",
            "voting_deadline": _FUTURE,
            "quorum_required": 0.5,
            "pass_threshold": 0.67,
        }
        post   = _make_post(post_type=PostType.PROPOSAL, metadata=meta)
        result = factory.build(post, author_did="did:agentx:atlas-001")
        assert result["post_type"] == "PROPOSAL"

    def test_invalid_proposal_type_raises(self):
        meta = {
            "proposal_type": "WHIM",
            "voting_deadline": _FUTURE,
            "quorum_required": 0.5,
            "pass_threshold": 0.6,
        }
        post = _make_post(post_type=PostType.PROPOSAL, metadata=meta)
        with pytest.raises(PostValidationError):
            factory.build(post, author_did="did:agentx:atlas-001")

    def test_pass_threshold_below_half_raises(self):
        meta = {
            "proposal_type": "BUDGET",
            "voting_deadline": _FUTURE,
            "quorum_required": 0.3,
            "pass_threshold": 0.4,   # below 0.5 minimum
        }
        post = _make_post(post_type=PostType.PROPOSAL, metadata=meta)
        with pytest.raises(PostValidationError):
            factory.build(post, author_did="did:agentx:atlas-001")


class TestOfferFactory:
    def test_valid_offer_builds(self):
        meta   = {"price": 50.0, "currency": "WORK", "availability": "IMMEDIATE"}
        post   = _make_post(post_type=PostType.OFFER, metadata=meta)
        result = factory.build(post, author_did="did:agentx:bruno-001")
        assert result["post_type"] == "OFFER"

    def test_invalid_currency_raises(self):
        meta = {"price": 10.0, "currency": "BTC", "availability": "IMMEDIATE"}
        post = _make_post(post_type=PostType.OFFER, metadata=meta)
        with pytest.raises(PostValidationError, match="currency"):
            factory.build(post, author_did="did:agentx:bruno-001")

    def test_negative_price_raises(self):
        meta = {"price": -5.0, "currency": "GOV", "availability": "SCHEDULED"}
        post = _make_post(post_type=PostType.OFFER, metadata=meta)
        with pytest.raises(PostValidationError):
            factory.build(post, author_did="did:agentx:bruno-001")


class TestUpdateFactory:
    def test_valid_update_builds(self):
        meta   = {"progress_percent": 75, "related_task_id": None}
        post   = _make_post(post_type=PostType.UPDATE, metadata=meta)
        result = factory.build(post, author_did="did:agentx:bruno-001")
        assert result["post_type"] == "UPDATE"

    def test_progress_over_100_raises(self):
        meta = {"progress_percent": 110, "related_task_id": None}
        post = _make_post(post_type=PostType.UPDATE, metadata=meta)
        with pytest.raises(PostValidationError):
            factory.build(post, author_did="did:agentx:bruno-001")


class TestCommonFields:
    def test_author_did_set_correctly(self):
        post   = _make_post(metadata={"urgency": "LOW", "offer_rep": 10})
        result = factory.build(post, author_did="did:agentx:quinn-001")
        assert result["author_did"] == "did:agentx:quinn-001"

    def test_status_always_active(self):
        post   = _make_post(metadata={"urgency": "LOW", "offer_rep": 0})
        result = factory.build(post, author_did="did:agentx:quinn-001")
        assert result["status"] == "ACTIVE"

    def test_post_id_is_uuid(self):
        post   = _make_post(metadata={"urgency": "LOW", "offer_rep": 0})
        result = factory.build(post, author_did="did:agentx:quinn-001")
        assert isinstance(result["post_id"], UUID)

    def test_metadata_is_json_string(self):
        import json
        post   = _make_post(metadata={"urgency": "LOW", "offer_rep": 42})
        result = factory.build(post, author_did="did:agentx:quinn-001")
        parsed = json.loads(result["metadata"])
        assert isinstance(parsed, dict)
