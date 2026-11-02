"""
Layer 1 S3-5: the @mention parser (pure, no database).

`mentions.extract` decides which ``@names`` in a text are candidates. It has
to be strict: a look-alike must never resolve to someone else's handle, an
e-mail address or a URL path is not a mention, and more than ten distinct
names refuses the text instead of trimming it.
"""
from __future__ import annotations

import pytest

from src.services import mentions
from src.services.mentions import MAX_MENTIONS, TooManyMentions, extract


def test_basic_mentions_in_order_of_first_appearance():
    assert extract("hi @nova, @atlas and @nova again; cc @sol_7") == ["nova", "atlas", "sol_7"]


def test_case_is_folded_and_a_leading_at_is_the_only_marker():
    assert extract("@Nova @NOVA @nova") == ["nova"]
    assert extract("nova atlas") == []
    assert extract("") == [] and extract(None) == []


@pytest.mark.parametrize("text", [
    "write to nova@agentx.social",       # e-mail
    "see https://agentx.social/@nova",    # URL path to a profile
    "a@@nova",                            # doubled marker
    "@@nova",
    "x@nova",                             # glued to a word
    "_@nova",
    "1@nova",
])
def test_email_url_path_and_glued_markers_are_not_mentions(text):
    assert extract(text) == []


@pytest.mark.parametrize("text", [
    "(@nova)", "[@nova]", "\"@nova\"", "'@nova'", "@nova.", "@nova,", "@nova!", "@nova?",
    "@nova:", "@nova;", "-@nova", "…@nova", "\n@nova", "\t@nova", ".@nova", ":@nova",
    "Hello,@nova", "#tag @nova", "@nova's post",
])
def test_punctuation_around_a_mention_is_fine(text):
    assert extract(text) == ["nova"]


def test_too_short_and_too_long_tokens_are_plain_text():
    assert extract("@no @n @_") == []
    assert extract("@" + "a" * 30) == ["a" * 30]
    assert extract("@" + "a" * 31) == []
    assert extract("@" + "a" * 80) == []


@pytest.mark.parametrize("text", [
    "@atlаs",            # Cyrillic а in the middle: not "@atl" + text
    "@аtlas",            # Cyrillic а first
    "@novaё",            # a word character of another script right after
    "@nová",       # combining accent
    "@ｎｏｖａ",          # full-width letters
    "@noväx",      # diaeresis then text
])
def test_unicode_look_alikes_never_resolve_to_a_shorter_ascii_name(text):
    assert extract(text) == []


def test_a_real_separator_after_the_name_still_ends_it():
    assert extract("@nova\u200b_x") == ["nova"]           # zero-width space is not a mark
    assert extract("@nova\u00a0@atlas") == ["nova", "atlas"]


def test_more_than_ten_distinct_names_is_refused_not_trimmed():
    ten = " ".join(f"@agent_{i}" for i in range(MAX_MENTIONS))
    assert len(extract(ten)) == MAX_MENTIONS
    with pytest.raises(TooManyMentions) as exc:
        extract(ten + " @agent_x")
    assert exc.value.count == 11
    assert "at most 10" in str(exc.value)


def test_the_same_name_many_times_counts_once():
    assert extract(" ".join(["@nova"] * 50)) == ["nova"]


def test_unknown_names_are_the_resolver_s_job_not_the_parser_s():
    # The parser only knows handle shape; "@everyone" is a candidate here and
    # a reserved word nobody holds, so record() leaves it as plain text.
    assert extract("@everyone @admin") == ["everyone", "admin"]


def test_the_cap_is_ten_and_the_daily_notification_cap_is_sane():
    assert MAX_MENTIONS == 10
    assert 10 <= mentions.NOTIFICATIONS_PER_DAY <= 1000
