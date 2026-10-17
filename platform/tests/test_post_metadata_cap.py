"""EG-5: post metadata is capped, because it rides along on every feed row."""
import pytest
from pydantic import ValidationError

from src.models.post import MAX_METADATA_BYTES, PostCreate


def _post(metadata):
    return PostCreate(post_type="UPDATE", title="t", content="c", metadata=metadata)


def test_typical_metadata_is_accepted():
    assert _post({"progress_percent": 40}).metadata == {"progress_percent": 40}


def test_metadata_at_the_cap_is_accepted():
    # {"k":"<pad>"} is 8 bytes of JSON around the padding
    _post({"k": "a" * (MAX_METADATA_BYTES - 8)})


def test_metadata_over_the_cap_is_rejected():
    with pytest.raises(ValidationError, match="metadata too large"):
        _post({"k": "a" * (MAX_METADATA_BYTES - 7)})


def test_multibyte_text_is_counted_in_bytes():
    with pytest.raises(ValidationError, match="metadata too large"):
        _post({"k": "é" * (MAX_METADATA_BYTES // 2)})
