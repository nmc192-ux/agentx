"""
Tests: request models for custom feeds and labelers (Layer 1 S6-1)

The API refuses malformed input before it reaches the database; these limits
must match the CHECK constraints of migration 057, and the kill switches
default on.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.config import Settings
from src.models.custom_feed import (
    MAX_FEED_ITEMS,
    FeedCreate,
    FeedItemSkipped,
    FeedItemsSet,
    FeedUpdate,
)
from src.models.labeler import (
    MAX_LABEL_BATCH,
    MAX_LABELER_VALUES,
    LabelBatch,
    LabelerCreate,
    LabelerUpdate,
    LabelItem,
    LabelValue,
)


@pytest.mark.parametrize("slug", ["abc", "ai-news", "x" * 40, "2026-picks", "---"])
def test_feed_slug_accepted(slug):
    assert FeedCreate(slug=slug, name="Feed").slug == slug


@pytest.mark.parametrize("slug", ["ab", "x" * 41, "AI-news", "ai_news", "ai news", "ai/news", "../etc",
                                  "ai-news\n", "", "émoji"])
def test_feed_slug_refused(slug):
    with pytest.raises(ValidationError):
        FeedCreate(slug=slug, name="Feed")


def test_feed_name_and_description_limits():
    f = FeedCreate(slug="abc", name="  Padded  ", description="d" * 300)
    assert f.name == "Padded" and f.description == "d" * 300
    for bad in ({"name": ""}, {"name": "   "}, {"name": "n" * 61}, {"description": "d" * 301}):
        with pytest.raises(ValidationError):
            FeedCreate(slug="abc", **{"name": "Feed", **bad})
    assert FeedUpdate().name is None and FeedUpdate().description is None
    assert FeedUpdate(name=" New ").name == "New"
    with pytest.raises(ValidationError):
        FeedUpdate(name="  ")


def test_feed_items_cap_and_skip_reason():
    ids = [uuid4() for _ in range(MAX_FEED_ITEMS)]
    assert len(FeedItemsSet(post_ids=ids).post_ids) == 500
    assert FeedItemsSet(post_ids=[]).post_ids == []   # an empty list clears the feed
    with pytest.raises(ValidationError):
        FeedItemsSet(post_ids=ids + [uuid4()])
    with pytest.raises(ValidationError):
        FeedItemsSet(post_ids=["not-a-uuid"])
    # One reason for every skipped id: a feed must not tell hidden from unknown.
    assert FeedItemSkipped(post_id=uuid4()).reason == "not_available"
    with pytest.raises(ValidationError):
        FeedItemSkipped(post_id=uuid4(), reason="hidden")


@pytest.mark.parametrize("value", ["ok", "satire", "unverified-claim", "x" * 30])
def test_label_value_accepted(value):
    assert LabelValue(value=value).value == value
    assert LabelItem(post_id=uuid4(), label=value).label == value


@pytest.mark.parametrize("value", ["a", "x" * 31, "Satire", "no_way", "two words", "<b>", "", "spam\n"])
def test_label_value_refused(value):
    with pytest.raises(ValidationError):
        LabelValue(value=value)
    with pytest.raises(ValidationError):
        LabelItem(post_id=uuid4(), label=value)


def test_label_meaning_limit():
    LabelValue(value="ok", meaning="m" * 100)
    with pytest.raises(ValidationError):
        LabelValue(value="ok", meaning="m" * 101)


def test_labeler_vocabulary_limits():
    vals = [{"value": f"v{i:02d}"} for i in range(MAX_LABELER_VALUES)]
    assert len(LabelerCreate(name="Check", values=vals).values) == 20
    with pytest.raises(ValidationError):
        LabelerCreate(name="Check", values=vals + [{"value": "v99"}])
    with pytest.raises(ValidationError):
        LabelerCreate(name="Check", values=[])
    with pytest.raises(ValidationError):
        LabelerCreate(name="Check", values=[{"value": "satire"}, {"value": "satire"}])
    for bad in ({"name": "  "}, {"name": "n" * 61}, {"description": "d" * 301}):
        with pytest.raises(ValidationError):
            LabelerCreate(**{"name": "Check", "values": [{"value": "ok"}], **bad})


def test_labeler_update_is_partial():
    u = LabelerUpdate()
    assert u.name is None and u.description is None and u.values is None
    assert LabelerUpdate(values=[{"value": "spam"}]).values[0].value == "spam"
    with pytest.raises(ValidationError):
        LabelerUpdate(values=[])   # removing every value is DELETE /labelers/me
    with pytest.raises(ValidationError):
        LabelerUpdate(values=[{"value": "spam"}, {"value": "spam"}])


def test_label_batch_limits():
    items = [{"post_id": str(uuid4()), "label": "satire"} for _ in range(MAX_LABEL_BATCH)]
    assert len(LabelBatch(items=items).items) == 50
    with pytest.raises(ValidationError):
        LabelBatch(items=items + [{"post_id": str(uuid4()), "label": "satire"}])
    with pytest.raises(ValidationError):
        LabelBatch(items=[])


def test_switches_default_on():
    assert Settings.model_fields["custom_feeds_enabled"].default == "true"
    assert Settings.model_fields["labelers_enabled"].default == "true"
