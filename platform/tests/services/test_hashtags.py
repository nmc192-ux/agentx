"""Layer 1 S3-6: #hashtag parsing and tag merging (pure, no DB)."""
from __future__ import annotations

import pytest

from src.models.post import PostCreate, PostType
from src.services import hashtags
from src.services.post_factory import PostValidationError, post_factory


@pytest.mark.parametrize("text, want", [
    ("#ai is fun", ["ai"]),
    ("love #AI and #ai and #Ai", ["ai"]),
    ("start #one, then (#two) and #three.", ["one", "two", "three"]),
    ("#snake_case_2", ["snake_case_2"]),
    ("line\n#next", ["next"]),
    ("#a", ["a"]),
    ("#" + "x" * 50, ["x" * 50]),
    ("first #b then #a", ["b", "a"]),
])
def test_extract_finds(text, want):
    assert hashtags.extract(text) == want


@pytest.mark.parametrize("text", [
    "",
    None,
    "no tags here",
    "a#b",                                 # after a word character
    "##double",                            # after '#'
    "it&#39;s",                            # an HTML entity
    "https://x.io/page#section",           # a URL fragment
    "see https://x.io/a?b=1#frag now",
    "www.x.io/#top",
    "ftp://host/file#part",
    "x.io/#top",                           # after '/'
    "issue #42",                           # digits only
    "#1",
    "#" + "x" * 51,                        # too long: plain text, never cut
    "#cafè",                               # a non-ASCII letter ends the token
    "#café",                         # a combining mark
    "#atlаs",                              # Cyrillic 'а'
    "# space",
])
def test_extract_ignores(text):
    assert hashtags.extract(text) == []


def test_markup_around_a_tag_yields_only_the_word():
    # The tag is the word only; the UI escapes the rest of the text (S3-8a).
    assert hashtags.extract("<script>#x</script>") == ["x"]


def test_url_then_tag_on_same_line():
    assert hashtags.extract("https://x.io/p#frag #real") == ["real"]


def test_merge_explicit_first_lower_distinct():
    assert hashtags.merge(["#AI", " ml ", "", "#"], "about #ai and #new") == ["ai", "ml", "new"]


def test_merge_ten_ok_eleven_refused():
    text = " ".join(f"#t{i}" for i in range(5))
    assert len(hashtags.merge([f"e{i}" for i in range(5)], text)) == 10
    with pytest.raises(hashtags.TooManyTags) as e:
        hashtags.merge([f"e{i}" for i in range(6)], text)
    assert "at most 10 tags" in str(e.value) and "11 found" in str(e.value)


def test_text_alone_over_ten_refused():
    with pytest.raises(hashtags.TooManyTags):
        hashtags.merge([], " ".join(f"#t{i}" for i in range(11)))


def test_repeated_tags_count_once():
    assert hashtags.merge([], " ".join(["#same"] * 50)) == ["same"]


def test_extract_is_linear_on_hostile_input():
    text = "#" + "a" * 100_000 + " " + "#a#" * 20_000
    hashtags.extract(text)                 # finishes (no catastrophic backtracking)


def test_post_factory_merges_content_hashtags():
    body = PostCreate(post_type=PostType.UPDATE, title="t", content="hi #Agents #x",
                      tags=["Explicit"])
    assert post_factory.build(body, author_did="did:agentx:a")["tags"] == [
        "explicit", "agents", "x",
    ]


def test_post_factory_refuses_over_ten():
    body = PostCreate(post_type=PostType.UPDATE, title="t",
                      content=" ".join(f"#c{i}" for i in range(4)),
                      tags=[f"e{i}" for i in range(7)])
    with pytest.raises(PostValidationError, match="at most 10 tags"):
        post_factory.build(body, author_did="did:agentx:a")
